import csv
import io
import json
import time

import pytest
from fastapi.testclient import TestClient
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.genai import types

from dss.config import Config
from dss.data import research as scraper
from dss.harness.guardrails import RunError
from dss.harness.nodes import research
from dss.main import create_app
from fakes import FakeLLM, fake_models
from test_intake import FakeBigQuery

CSV = b'Player,Points\nRAW_PLAYER_ALPHA,30\nRAW_PLAYER_BETA,20\n'


class FakeSearch(BaseTool):
    def __init__(self):
        super().__init__(name='google_search', description='Offline search')
        self.calls = 0

    async def process_llm_request(self, *, tool_context, llm_request):
        self.calls += 1


class ResearchLLM(FakeLLM):
    discovery: str = '{"urls":["https://example.com/stats.csv"]}'
    selection: str = '{"table_id":0}'
    requests: list[str] = []
    fail_selection: bool = False

    async def generate_content_async(self, llm_request, stream=False):
        if self.calls and self.fail_selection:
            raise RuntimeError('provider exception with test-key')
        self.calls += 1
        self.requests.append(str(llm_request))
        assert 'RAW_PLAYER_' not in str(llm_request)
        yield LlmResponse(content=types.Content(role='model', parts=[types.Part(
            text=self.discovery if self.calls == 1 else self.selection)]),
            grounding_metadata=types.GroundingMetadata(grounding_chunks=[types.GroundingChunk(
                web=types.GroundingChunkWeb(uri='https://example.com/discovery', title='Source'))]) if self.calls == 1 else None)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    bq = FakeBigQuery()
    model, search = ResearchLLM(), FakeSearch()
    monkeypatch.setattr(research, 'google_search', search)
    monkeypatch.setattr(scraper, 'http_get', lambda url, timeout: (200, {'content-type': 'text/csv'}, CSV))
    app = create_app(Config(data_dir=tmp_path, google_api_key='test-key', gcp_project_id='test-project'),
                     model_lister=fake_models, bigquery_factory=lambda _: bq)
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.harness.models, 'llm_for', lambda _: model)
        build = client.post('/api/builds', json={'archetype': 'analytical', 'mode': 'research'}).json()
        yield client, app, build['id'], model, search, bq


def run_direct(setup, **extra):
    client, app, build_id, model, search, _ = setup
    async def run():
        return await app.state.harness.run('research', build_id,
            {'config': app.state.settings.get(), 'prompt': 'Player points for the requested season',
             'factory': app.state.bigquery_factory, **extra}, llm=model)
    return client.portal.call(run)


def test_workflow_csv_sources_intake_one_trace_and_no_rows_in_prompts(setup):
    client, app, build_id, model, search, bq = setup
    result = run_direct(setup)
    folder = app.state.settings.get().data_dir / 'builds' / build_id / 'v1'
    rows = list(csv.reader(io.StringIO(next(folder.glob('research-*.csv')).read_text())))
    assert rows == [['player', 'points'], ['RAW_PLAYER_ALPHA', '30'], ['RAW_PLAYER_BETA', '20']]
    sources = (folder / 'docs/sources.md').read_text()
    assert 'https://example.com/stats.csv' in sources and 'https://example.com/discovery' in sources
    assert 'type: Research Sources' in sources
    assert model.calls == 2 and search.calls == 1
    assert 'table-metadata' not in model.requests[0] and 'row_count' in model.requests[1]
    assert 'grounding_chunks' not in model.requests[1]
    build = client.get(f'/api/builds/{build_id}').json()
    assert build['sources'][0]['kind'] == 'research' and build['sources'][0]['row_count'] == 2
    assert len(bq.loads) == 1
    with app.state.db.connect() as conn:
        traces = conn.execute("SELECT * FROM traces WHERE node='research'").fetchall()
        assert len(traces) == 1 and traces[0]['run_id'] == result['run_id'] and traces[0]['status'] == 'ok'
        assert traces[0]['tool_calls'] == 2
        events = [r[0] for r in conn.execute('SELECT kind FROM events WHERE run_id=?', (result['run_id'],))]
        assert 'build.updated' in events and 'docs.updated' in events and 'run.finished' in events
    assert build_id not in app.state.harness.active_builds


def test_workflow_cap_provenance_includes_failed_and_redirect_urls(setup):
    _, app, build_id, model, search, _ = setup
    urls = [f'https://example.com/{i}.csv' for i in range(20)]
    model.discovery = json.dumps({'urls': urls})
    requests = []
    def get(url, timeout):
        requests.append(url)
        if url == urls[0]:
            return 302, {'location': '/redirect.csv'}, b''
        if url == urls[1]:
            raise OSError('sensitive provider failure')
        return 200, {'content-type': 'text/csv'}, CSV
    run_direct(setup, getter=get)
    assert len(requests) == 20 and urls[-1] not in requests
    assert search.calls == 1
    sources = (app.state.settings.get().data_dir / 'builds' / build_id / 'v1/docs/sources.md').read_text()
    assert all(url in sources for url in requests)
    assert 'request_limit' in sources and 'sensitive provider failure' not in sources


@pytest.mark.parametrize('selection', ['{"table_id":null}', '{"table_id":200}', '{"table_id":true}', 'bad'])
def test_invalid_selection_fails_without_loading_and_releases(setup, selection):
    _, app, build_id, model, _, bq = setup
    model.selection = selection
    with pytest.raises(RunError, match='could not select'):
        run_direct(setup)
    assert not bq.loads and build_id not in app.state.harness.active_builds
    with app.state.db.connect() as conn:
        assert conn.execute("SELECT status FROM traces WHERE node='research'").fetchone()[0] == 'error'


def test_no_table_skips_selection_and_preserves_provenance(setup):
    _, app, build_id, model, _, bq = setup
    with pytest.raises(RunError, match='no usable'):
        run_direct(setup, getter=lambda *_: (403, {}, b''))
    assert model.calls == 1 and not bq.loads
    path = app.state.settings.get().data_dir / 'builds' / build_id / 'v1/docs/sources.md'
    assert '403: https://example.com/stats.csv' in path.read_text()


def test_selection_provider_failure_preserves_retrieval_provenance(setup, caplog):
    _, app, build_id, model, _, bq = setup
    model.fail_selection = True
    with pytest.raises(RunError):
        run_direct(setup)
    assert not bq.loads and build_id not in app.state.harness.active_builds
    path = app.state.settings.get().data_dir / 'builds' / build_id / 'v1/docs/sources.md'
    assert '200: https://example.com/stats.csv' in path.read_text()
    assert 'test-key' not in caplog.text


def test_unsafe_output_not_logged_or_written(setup, caplog):
    _, app, build_id, model, _, bq = setup
    model.discovery = '{"urls":["https://example.com/test-key"]}'
    with pytest.raises(RunError):
        run_direct(setup)
    assert 'test-key' not in caplog.text and not bq.loads
    assert build_id not in app.state.harness.active_builds


def test_research_api_accepts_returns_run_id_and_finishes(setup):
    client, app, build_id, _, _, _ = setup
    response = client.post(f'/api/builds/{build_id}/research', json={'prompt': 'Player stats'})
    assert response.status_code == 202 and set(response.json()) == {'run_id'}
    run_id = response.json()['run_id']
    for _ in range(100):
        with app.state.db.connect() as conn:
            trace = conn.execute('SELECT status FROM traces WHERE run_id=?', (run_id,)).fetchone()
        if trace:
            break
        time.sleep(.02)
    assert trace and trace[0] == 'ok'


def test_research_api_stage_mode_busy_and_validation(setup):
    client, app, build_id, model, _, bq = setup
    url = f'/api/builds/{build_id}/research'
    assert client.post('/api/builds/missing/research', json={'prompt': 'stats'}).status_code == 404
    for prompt in ('', ' ', 'a' * 4001):
        assert client.post(url, json={'prompt': prompt}).status_code == 422
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET mode='data' WHERE id=?", (build_id,))
    assert client.post(url, json={'prompt': 'stats'}).status_code == 409
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET mode='research',stage='prototype' WHERE id=?", (build_id,))
    assert client.post(url, json={'prompt': 'stats'}).status_code == 409
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='connect' WHERE id=?", (build_id,))
    app.state.harness.active_builds.add(build_id)
    assert client.post(url, json={'prompt': 'stats'}).status_code == 409
    app.state.harness.active_builds.discard(build_id)
    app.state.settings.update({'gcp_project_id': ''})
    assert client.post(url, json={'prompt': 'stats'}).status_code == 503
    assert not model.calls and not bq.loads


def test_html_spans_comments_whitespace_duplicates_and_headers():
    html = b'''<title>Season 2025-26</title><!-- <table><caption>Players</caption>
    <tr><th rowspan="2">Player</th><th colspan="2">Stats</th></tr>
    <tr><th>PTS</th><th>AST</th></tr>
    <tr><th>A &amp; B</th><td> 30 </td><td> 7 </td></tr>
    <tr><th>A &amp; B</th><td>30</td><td>7</td></tr>
    <tr><th>Player</th><th>PTS</th><th>AST</th></tr>
    <tr><th>C</th><td>20</td><td>5</td></tr></table> -->'''
    tables = scraper.parse_tables('https://example.com/', 'text/html', html)
    assert len(tables) == 1
    assert tables[0].headers == ['Player', 'Stats PTS', 'Stats AST']
    assert tables[0].rows == [['A & B', '30', '7'], ['C', '20', '5']]
    assert tables[0].csv_bytes().startswith(b'player,stats_pts,stats_ast\r\n')


def test_csv_cleaning_and_ragged_rejection():
    tables = scraper.parse_tables('https://example.com/a.csv', 'text/csv',
                                  b'Name,Score\n A , 2 \n\nName,Score\nA,2\nB,3\n')
    assert tables[0].rows == [['A', '2'], ['B', '3']]
    assert not scraper.parse_tables('https://example.com/a.csv', 'text/csv', b'A,B\nx,y,z\n')


def test_headerless_html_never_promotes_raw_rows_to_metadata():
    html = b'<table><tr><td>Alice</td><td>30</td></tr><tr><td>Bob</td><td>20</td></tr></table>'
    assert not scraper.parse_tables('https://example.com/', 'text/html', html)


def test_oversized_html_table_is_rejected_without_silent_truncation():
    html = b'<table><tr><th>A</th><th>B</th></tr>'
    html += b'<tr><td>x</td><td>1</td></tr>' * (scraper.MAX_ROWS + 20) + b'</table>'
    assert not scraper.parse_tables('https://example.com/', 'text/html', html)


def test_redirect_loop_and_twenty_failed_requests():
    calls = []
    def loop(url, timeout):
        calls.append(url)
        return 302, {'location': url}, b''
    collector = scraper.Collector(loop)
    collector.collect(['https://example.com/'])
    assert len(calls) == 1
    collector = scraper.Collector(lambda *_: (_ for _ in ()).throw(OSError('failed')))
    collector.collect([f'https://example.com/{i}' for i in range(100)])
    assert len(collector.attempts) == 20 and collector.stop_reason == 'request_limit'


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'https://user:pw@example.com/',
                                'http://example.com:8000/', 'http://example.com/\r\nx'])
def test_invalid_url_before_io(url):
    called = []
    scraper.Collector(lambda *args: called.append(args)).collect([url])
    assert called == []


@pytest.mark.parametrize('address', ['127.0.0.1', '169.254.169.254', '10.0.0.1', '::1', '::ffff:127.0.0.1'])
def test_public_only_dns(address, monkeypatch):
    monkeypatch.setattr(scraper.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', (address, 80))])
    with pytest.raises(scraper.RetrievalError, match='public addresses'):
        scraper.public_addresses('example.com', 80)


def test_redirect_to_private_host_rejected(monkeypatch):
    called = []
    def get(url, timeout):
        if len(called) == 0:
            called.append(url)
            return 302, {'location': 'http://127.0.0.1/'}, b''
        return scraper.http_get(url, timeout)
    monkeypatch.setattr(scraper.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 80))])
    collector = scraper.Collector(get)
    collector.collect(['https://example.com/'])
    assert len(collector.attempts) == 2 and collector.attempts[-1]['status'] == 'failed'


def test_response_size_cap():
    collector = scraper.Collector(lambda *_: (200, {'content-type': 'text/csv'}, b'x' * (scraper.MAX_BYTES + 1)))
    assert not collector.collect(['https://example.com/'])
    assert collector.attempts[0]['status'] == 'failed'


def test_research_counts_each_phase_without_extra_search_or_scraping(setup):
    from test_context import assert_counted, counting
    client, app, build_id, _, search, _ = setup
    model = counting(ResearchLLM)(requests=[])
    requests = []
    def get(url, timeout):
        requests.append(url)
        return 200, {'content-type': 'text/csv'}, CSV
    async def run():
        return await app.state.harness.run('research', build_id, {'config': app.state.settings.get(),
            'prompt': 'Player points', 'factory': app.state.bigquery_factory, 'getter': get}, llm=model)
    client.portal.call(run)
    with app.state.db.connect() as conn:
        spans = json.loads(conn.execute("SELECT spans_json FROM traces WHERE node='research'").fetchone()[0])
    for node in ('research_discover', 'research_select'):
        assert_counted(next(s for s in spans if s['node'] == node), model)
    assert model.calls == 2 and search.calls == 1 and len(requests) == 1 and len(model.counts) == 2
