import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import struct
import threading
import time

import pytest

from dss.harness.nodes.render import artifacts, perform
from dss.render import background
from dss.render.prototype import aggregate_data, aggregate_sql, chart_option, render
from dss.spec.layout import box
from dss.spec.models import DashboardSpec, Sort
from test_blueprint import blueprint_api  # noqa: F401  (fixture)
from test_context_node import context_api  # noqa: F401  (fixture)


@pytest.fixture
def dashboard():
    return DashboardSpec.model_validate_json(Path('tests/data/thin_spec.json').read_text())


class FakeBigQuery:
    def __init__(self, delay=0):
        self.queries = []
        self.active = self.peak = 0
        self.lock = threading.Lock()
        self.delay = delay

    def aggregate(self, sql):
        with self.lock:
            self.queries.append(sql)
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        return [{'region': 'West', 'm0': 12345.5}, {'region': 'East', 'm0': 4000}]


class ContractParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.stack = []
        self.items = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'data-cid' in attrs:
            assert not any(self.stack), 'Nested data-cid'
            assert attrs['data-cid'] not in self.items, 'Duplicate data-cid'
            self.items[attrs['data-cid']] = attrs
        if tag not in ('meta', 'img', 'input', 'br', 'link'):
            self.stack.append('data-cid' in attrs)

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()


FIXTURE = Path('../contracts/fixtures/api/prototype.multipage.html')
EVIDENCE = Path('.blueprint/qa/task-15.9')
PAGE_NAMES = ('Overview', 'Where revenue comes from', 'Order mix')


def three_pages(per_page=8):
    """A validated 3-page spec: band header kit per page, then 4 scorecards, 2 bars, a pie, a table."""
    from dss.render.kits import content_row, decorations
    from dss.spec.models import Cell, Component, DataField, Metric, Page
    from dss.spec.validate import validate_spec
    spec = DashboardSpec.model_validate_json(Path('tests/data/thin_spec.json').read_text())
    spec.datasource.fields.append(DataField(name='category', type='STRING', label='Category', role='dimension'))
    spec.pages = []
    for n, name in enumerate(PAGE_NAMES, 1):
        top = content_row('band_header', name)
        cells = [(col, top, 3, 5, 'scorecard') for col in (1, 4, 7, 10)] + [
            (1, top + 5, 6, 14, 'bar'), (7, top + 5, 6, 14, 'bar'), (1, top + 19, 6, 14, 'pie'), (7, top + 19, 6, 14, 'table')]
        components = [Component(id=f'p{n}_{kind}_{i}', type=kind, label=f'{kind.title()} {i} on page {n}',
                                grid=Cell(col=col, row=row, w=w, h=h), metrics=[Metric(field='revenue', agg='sum')],
                                dimensions=[] if kind == 'scorecard' else ['category' if i % 2 else 'region'])
                      for i, (col, row, w, h, kind) in enumerate(cells[:per_page])]
        bottom = max(box(spec.canvas, spec.grid, c.grid, height=10 ** 5)['y'] + c.grid.h * 20 - 16 for c in components)
        spec.pages.append(Page(index=n, name=name, height=bottom + 24, components=components,
                               decorations=decorations('band_header', spec.theme, name, page=n)))
    spec.canvas.height = spec.pages[0].height
    assert validate_spec(spec) == []
    return spec


class PageParser(HTMLParser):
    """Each data-cid element's ancestors (tag, id, data-page) and the page sections in order."""
    def __init__(self, html):
        super().__init__()
        self.stack, self.items, self.sections, self.canvas = [], {}, [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id') == 'dss-canvas':
            self.canvas.append(attrs)
        if tag == 'section':
            self.sections.append((attrs.get('data-page'), attrs.get('data-page-name'), attrs.get('style', '')))
        if 'data-cid' in attrs:
            chain = [(t, a.get('id'), a.get('data-page')) for t, a in self.stack if 'data-cid' not in a and (a.get('id') == 'dss-canvas' or t == 'section')]
            assert not any('data-cid' in a for _, a in self.stack), 'Nested data-cid'
            assert attrs['data-cid'] not in self.items, 'Duplicate data-cid'
            self.items[attrs['data-cid']] = {**attrs, 'chain': chain}
        if tag not in ('meta', 'img', 'input', 'br', 'link'):
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()


def test_multipage_html_matches_contract_fixture():
    spec = three_pages()
    expected, parsed = PageParser(FIXTURE.read_text(encoding='utf-8')), PageParser(render(spec))
    for page in (expected, parsed):
        assert len(page.canvas) == 1 and page.sections
        # Every item sits directly in its page section, which sits in the one canvas.
        assert {tuple((t, i) for t, i, _ in a['chain']) for a in page.items.values()} == {(('div', 'dss-canvas'), ('section', None))}
        assert all(a['chain'][1][2] == a['data-cid'][1:a['data-cid'].index('_')] for a in page.items.values())
        assert {a['data-kind'] for a in page.items.values()} == {'component', 'decoration'}
    assert [(n, name) for n, name, _ in parsed.sections] == [(str(p.index), p.name) for p in spec.pages]
    assert all(f'height:{p.height}px' in style for p, (_, _, style) in zip(spec.pages, parsed.sections))
    assert f'height:{sum(p.height for p in spec.pages)}px' in parsed.canvas[0]['style']
    items = [(p, i) for p in spec.pages for i in p.decorations + p.components]
    assert len(parsed.items) == len(items) == 3 * (8 + 2)
    for page, item in items:
        attrs = parsed.items[item.id]
        assert attrs['chain'][1][2] == str(page.index) and attrs['data-label']
        b = box(spec.canvas, spec.grid, item.grid, height=page.height)
        assert all(f'{prop}:{b[key]}px' in attrs['style'] for prop, key in [('left','x'),('top','y'),('width','w'),('height','h')])


def test_decoration_layer_hides_components_on_every_page():
    spec = three_pages()
    parsed = PageParser(render(spec, layer='decoration'))
    assert len(parsed.items) == 30
    for attrs in parsed.items.values():
        assert ('display:none' in attrs['style']) == (attrs['data-kind'] == 'component')
    single = PageParser(render(spec, layer='decoration', page=2))
    assert [s[0] for s in single.sections] == ['2'] and set(single.items) == {i.id for i in spec.pages[1].decorations + spec.pages[1].components}
    assert f'height:{spec.pages[1].height}px' in single.canvas[0]['style']
    with pytest.raises(ValueError):
        render(spec, page=4)


def test_artifacts_capture_one_background_per_page(tmp_path, monkeypatch):
    spec = three_pages()
    captured = []
    def fake_capture(html, path, width, height):
        parsed = PageParser(html)
        assert len(parsed.sections) == 1 and all('display:none' in a['style'] for a in parsed.items.values() if a['data-kind'] == 'component')
        captured.append((parsed.sections[0][0], path.name, width, height))
        path.write_bytes(b'PNG ' + parsed.sections[0][0].encode())
    monkeypatch.setattr(background, 'capture', fake_capture)
    artifacts(spec, FakeBigQuery(), tmp_path)
    assert background.names(spec) == ['background_p1.png', 'background_p2.png', 'background_p3.png']
    assert captured == [(str(p.index), f'background_p{p.index}.tmp.png', 1200, p.height) for p in spec.pages]
    assert [(tmp_path / f'background_p{n}.png').read_bytes() for n in (1, 2, 3)] == [b'PNG 1', b'PNG 2', b'PNG 3']
    assert not list(tmp_path.glob('*.tmp.png'))


def test_three_pages_render_and_backgrounds_within_budget(tmp_path):
    """Real Chromium: 3 pages x 8 components, every background at 3x canvas size, <= 30 s."""
    spec = three_pages()
    service = FakeBigQuery(.1)
    start = time.monotonic()
    artifacts(spec, service, tmp_path)
    elapsed = time.monotonic() - start
    print(f'3 pages x 8 components with Chromium backgrounds: {elapsed:.2f}s')
    assert elapsed <= 30
    images = [(tmp_path / name).read_bytes() for name in background.names(spec)]
    assert [struct.unpack('>II', png[16:24]) for png in images] == [(3600, 3 * p.height) for p in spec.pages]
    assert len(set(images)) == 3  # each page's own header text
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    for name, png in zip(background.names(spec), images):
        (EVIDENCE / name).write_bytes(png)


def test_prototype_png_per_page_saved_for_visual_check(tmp_path):
    from playwright.sync_api import sync_playwright
    spec = three_pages()
    html = render(spec, data=aggregate_data(spec, FakeBigQuery(), tmp_path))
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / 'prototype.html').write_text(html, encoding='utf-8')
    total = sum(p.height for p in spec.pages)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 1200, 'height': total})
            page.set_content(html, wait_until='load', timeout=20000)
            page.wait_for_function('window.dssChartsReady === true', timeout=20000)
            for p in spec.pages:
                section = page.locator(f'section[data-page="{p.index}"]')
                bounds = section.bounding_box()
                assert (bounds['width'], bounds['height']) == (1200, p.height)
                path = EVIDENCE / f'prototype_p{p.index}.png'
                section.screenshot(path=str(path), animations='disabled')
                assert struct.unpack('>II', path.read_bytes()[16:24]) == (1200, p.height)
        finally:
            browser.close()


async def test_blueprint_accept_publishes_multipage_prototype(blueprint_flow):
    client, app, bid, folder, bq, run_id = blueprint_flow
    build = client.get(f'/api/builds/{bid}').json()
    assert build['stage'] == 'prototype' and build['artifacts']['blueprint'] == 'confirmed'
    spec = DashboardSpec.model_validate_json((folder / 'spec.json').read_text(encoding='utf-8'))
    table = spec.datasource.table
    assert table.endswith(f'dash_{bid}_v1_{run_id}') and bq.created == [table] and not bq.deleted
    assert [p.name for p in spec.pages] == ['Revenue snapshot', 'Where revenue comes from']
    assert [(folder / n).read_bytes() for n in background.names(spec)] == [b'PNG', b'PNG']
    sections = PageParser(client.get(f'/api/builds/{bid}/prototype').text).sections
    assert [(n, name) for n, name, _ in sections] == [('1', 'Revenue snapshot'), ('2', 'Where revenue comes from')]
    import yaml
    docs = yaml.safe_load((folder / 'docs/derived-fields.md').read_text(encoding='utf-8').split('---', 2)[1])
    assert docs['view'] == table and client.get(f'/api/builds/{bid}/blueprint').json()['view_table'] == table
    recipe = client.post(f'/api/builds/{bid}/recipe')
    assert recipe.status_code == 200, recipe.text
    assert [o['line'].split()[1] for o in recipe.json()['ops']].count('add-page') == 1
    with app.state.db.connect() as conn:
        trace = conn.execute('SELECT * FROM traces WHERE run_id=?', (run_id,)).fetchone()
        kinds = [r[0] for r in conn.execute('SELECT kind FROM events WHERE run_id=? ORDER BY rowid', (run_id,))]
    assert trace['status'] == 'ok' and trace['node'] == 'prototype'
    assert kinds.index('prototype.updated') < kinds.index('stage.changed') < kinds.index('run.finished')


@pytest.mark.parametrize('blueprint_flow', [{'fail': 'create_view'}, {'fail': 'render'}, {'fail': 'commit'}], indirect=True)
async def test_failed_accept_keeps_blueprint_stage_and_cleans_candidate(blueprint_flow):
    client, app, bid, folder, bq, run_id = blueprint_flow
    build = client.get(f'/api/builds/{bid}').json()
    assert build['stage'] == 'blueprint' and build['artifacts']['blueprint'] != 'confirmed'
    assert not (folder / 'spec.json').exists() and not (folder / 'background_p1.png').exists()
    # Only the run-owned candidate name is deleted, also after a failed (possibly late) CREATE.
    assert [t.rsplit('.', 1)[-1] for t in bq.deleted] == [f'dash_{bid}_v1_{run_id}']
    with app.state.db.connect() as conn:
        trace = conn.execute('SELECT * FROM traces WHERE run_id=?', (run_id,)).fetchone()
        finished = json.loads(conn.execute("SELECT payload_json FROM events WHERE run_id=? AND kind='run.finished'", (run_id,)).fetchone()[0])
    assert trace['status'] == 'error' and finished['status'] == 'error' and finished['error']


def other_record(app, bid, folder, tagged):
    """A supported outline Other record the blueprint does not mirror (a bar *breakdown*)."""
    from dss.spec import requirements as req
    from dss.spec.capabilities import Need
    text = 'Which product categories sell the most units?'
    with app.state.db.connect() as conn:
        conn.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)', ('m_other', bid, 'user', text, 'outline_other', '2026-10-21T00:00:00Z'))
    source = req.Source(id='m_other', kind='message', text=text)
    row = req.Requirement(id='req_other', source=source, text=text,
                          needs=[Need(capability='chart.bar'), Need(capability='argument.breakdown')],
                          mapping_origins={'origin': 'outline_other'} if tagged else {})
    req.save(folder, req.Ledger(requirements=[row], processed_sources={source.id: req.digest(source.model_dump())}))


@pytest.mark.parametrize('blueprint_flow,published', [({'other': True}, True), ({'other': False}, False)],
                         indirect=['blueprint_flow'])
async def test_outline_other_record_is_fulfilled_by_blueprint_rows(blueprint_flow, published):
    """Live 15.11: publish coverage rejected a blueprint bar *by* category for an Other text the
    extractor read as a bar *breakdown*; only comment/reference records are matched against the spec."""
    client, app, bid, folder, bq, run_id = blueprint_flow
    with app.state.db.connect() as conn:
        trace = conn.execute('SELECT * FROM traces WHERE run_id=?', (run_id,)).fetchone()
    assert (trace['status'], client.get(f'/api/builds/{bid}').json()['stage']) == (
        ('ok', 'prototype') if published else ('error', 'blueprint')), trace['error']


@pytest.fixture
def blueprint_flow(request, blueprint_api, monkeypatch):
    """Design confirm -> blueprint (ratio choice) -> accept, with fake BigQuery views and capture."""
    from test_blueprint import choose, confirm
    from test_context_node import wait
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    fail = getattr(request, 'param', {}).get('fail')
    bq.created, bq.deleted = [], []
    def create_view(table, sql):
        if fail == 'create_view':
            raise RuntimeError('sensitive provider text')
        bq.created.append(table)
    def delete_view(table):
        bq.deleted.append(table)
        return True
    bq.create_view, bq.delete_view = create_view, delete_view
    bq.aggregate = lambda sql: [{'region': 'West', 'product_category': 'A', 'm0': 10, 'm1': 2}]
    def capture(html, path, width, height):
        if fail == 'render':
            raise RuntimeError('chromium failed')
        path.write_bytes(b'PNG')
    monkeypatch.setattr(background, 'capture', capture)
    if fail == 'commit':
        # After the confirmation is saved, before the durable commit: both roll back.
        from dss.spec.publication import Candidate
        monkeypatch.setattr(Candidate, 'commit', lambda *a: (_ for _ in ()).throw(OSError('commit')))
    if 'other' in getattr(request, 'param', {}):
        other_record(app, bid, folder, request.param['other'])
    confirm(client, app, bid)
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    ratio = next(i for i in assessment['issues'] if i['requirement'] == 'q2')
    assert choose(client, bid, assessment, ratio, 'numerator_denominator').status_code == 200
    accepted = client.post(f'/api/builds/{bid}/blueprint/accept')
    assert accepted.status_code == 202, accepted.text
    wait(app)
    return client, app, bid, folder, bq, accepted.json()['run_id']


def staged_rows(pages, questions):
    """`pages` sections x `questions` selected questions x 3 rows, one page per section (16.1)."""
    from test_blueprint import fixture
    outline, rows = fixture('outline'), []
    question = outline['sections'][0]['questions'][0]
    outline['sections'] = [{'id': f's{p}', 'title': f'Section {p}', 'purpose': f'Net revenue view {p}.', 'questions': [
        {**question, 'id': f'q{p}_{j}', 'text': f'How does net revenue split in view {p}.{j}?', 'kpi_refs': ['net_revenue']}
        for j in range(1, questions + 1)]} for p in range(1, pages + 1)]
    for p in range(1, pages + 1):
        for j in range(1, questions + 1):
            for kind, dimensions in (('scorecard', []), ('bar', ['region']), ('bar', ['product_category'])):
                rows.append({'question_id': f'q{p}_{j}', 'section_id': f's{p}', 'page': p, 'note': '', 'status': 'ok',
                    'issue_ids': [], 'component': {'type': kind, 'label': f'Net revenue {p}.{j} {"by " + dimensions[0] if dimensions else "total"}',
                    'dimensions': dimensions, 'metrics': [{'field': 'revenue', 'agg': 'sum'}], 'date_dimension': None,
                    'breakdown': None, 'sort': {'field': 'revenue', 'order': 'desc'} if dimensions else None, 'options': {}}})
    return outline, rows


@pytest.fixture
def staged_flow(request, blueprint_api, monkeypatch):
    """Design confirm -> ready blueprint of N pages x 3Q rows -> accept, with fake views and capture."""
    from test_blueprint import artifact, confirm
    from test_context_node import wait
    from dss.artifacts.models import Outline
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    pages, questions = getattr(request, 'param', (3, 3))
    outline, value['rows'] = staged_rows(pages, questions)
    artifact(folder, Outline.model_validate(outline))
    llm.replies = [json.dumps(value)]
    bq.created, bq.deleted = [], []
    bq.create_view = lambda table, sql: bq.created.append(table)
    bq.delete_view = lambda table: bq.deleted.append(table) or True
    bq.aggregate = lambda sql: [{'region': 'West', 'product_category': 'A', 'm0': 10}]
    monkeypatch.setattr(background, 'capture', lambda html, path, width, height: path.write_bytes(b'PNG'))
    confirm(client, app, bid)
    before = client.get(f'/api/builds/{bid}/feasibility').json()
    assert before['state'] == 'ready', before['issues']
    accepted = client.post(f'/api/builds/{bid}/blueprint/accept')
    assert accepted.status_code == 202, accepted.text
    wait(app)
    return client, app, bid, folder, bq, accepted.json()['run_id']


@pytest.mark.parametrize('staged_flow', [(3, 3), (5, 4)], indirect=True)
async def test_staged_multipage_scope_publishes_past_24_components(staged_flow):
    """Final re-audit 16.1: 9+9+9 (and 5 x 12) rows were blocked after layout by a global 24-component check."""
    client, app, bid, folder, bq, run_id = staged_flow
    from test_context_node import wait
    with app.state.db.connect() as conn:
        trace = conn.execute('SELECT * FROM traces WHERE run_id=?', (run_id,)).fetchone()
    assert (trace['status'], client.get(f'/api/builds/{bid}').json()['stage']) == ('ok', 'prototype'), trace['error']
    spec = DashboardSpec.model_validate_json((folder / 'spec.json').read_text(encoding='utf-8'))
    blueprint = client.get(f'/api/builds/{bid}/blueprint').json()
    per_page = [sum(r['page'] == p for r in blueprint['rows']) for p in range(1, len(spec.pages) + 1)]
    assert [len(p.components) for p in spec.pages] == per_page and sum(per_page) == 3 * sum(
        len(s['questions']) for s in client.get(f'/api/builds/{bid}/outline').json()['sections'])
    assert per_page in ([9, 9, 9], [12] * 5) and bq.created == [spec.datasource.table] and not bq.deleted
    items = PageParser(client.get(f'/api/builds/{bid}/prototype').text).items
    assert {c.id for p in spec.pages for c in p.components} <= set(items)
    after = client.get(f'/api/builds/{bid}/feasibility').json()
    assert after['state'] == 'ready' and not after['prototype_stale'], after['issues']
    # Explicit reassessment of the published prototype agrees with publication.
    assert client.post(f'/api/builds/{bid}/feasibility/check').status_code == 202
    wait(app)
    assert client.get(f'/api/builds/{bid}/feasibility').json()['state'] == 'ready'


def use_reference_model(app, monkeypatch):
    """Style extraction with no items; feasibility checks then have no new intent to extract."""
    from dss.spec import references
    from test_references import Capture, output
    monkeypatch.setattr(references, 'decode', lambda _: None)
    model = Capture(response=output(items=[]), requests=[])
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: model)
    return model


def upload_style(client, app, bid):
    from test_context_node import wait
    from test_references import png
    response = client.post(f'/api/builds/{bid}/reference-images', data={'mode': 'style'},
                           files=[('files', ('style.png', png(), 'image/png'))])
    assert response.status_code == 202, response.text
    wait(app)


def feasibility_check(client, app, bid):
    from test_context_node import wait
    response = client.post(f'/api/builds/{bid}/feasibility/check')
    assert response.status_code == 202, response.text
    wait(app)
    return client.get(f'/api/builds/{bid}/feasibility').json()


def execution_blocked(client, bid, code='feasibility_blocked'):
    for endpoint in ('recipe', 'run'):
        response = client.post(f'/api/builds/{bid}/{endpoint}')
        assert response.status_code == 409 and response.json()['error']['code'] == code, response.text


def replan(client, app, bid, llm, value, monkeypatch):
    """Explicit replan through the staged API: regenerate the Blueprint, then accept it."""
    from test_context_node import wait
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: llm)
    llm.replies.append(json.dumps(value))
    regenerated = client.post(f'/api/builds/{bid}/blueprint/regenerate')
    assert regenerated.status_code == 202, regenerated.text
    wait(app)
    accepted = client.post(f'/api/builds/{bid}/blueprint/accept')
    assert accepted.status_code == 202, accepted.text
    wait(app)
    with app.state.db.connect() as conn:
        trace = conn.execute('SELECT * FROM traces WHERE run_id=?', (accepted.json()['run_id'],)).fetchone()
    return trace


def executes(client, app, bid, monkeypatch):
    """Fresh proof: recipe compiles and the offline fake engine finishes the run."""
    from test_context_node import wait
    root = Path(__file__).resolve().parent
    monkeypatch.setenv('DSS_ENGINE_CMD', f'"{__import__("sys").executable}" "{root / "fake_engine.py"}"')
    monkeypatch.setenv('DSS_ENGINE_DRY_RUN', '1')
    recipe = client.post(f'/api/builds/{bid}/recipe')
    assert recipe.status_code == 200, recipe.text
    run = client.post(f'/api/builds/{bid}/run')
    assert run.status_code == 202, run.text
    wait(app)
    for _ in range(500):
        if client.get(f'/api/builds/{bid}').json()['stage'] != 'build':
            break
        time.sleep(.02)
    assert client.get(f'/api/builds/{bid}').json()['stage'] == 'done'


def reloaded(app, bid):
    """A restarted application reads the persisted ledger and publication state only."""
    from fastapi.testclient import TestClient
    from dss.main import create_app
    from fakes import fake_models
    restarted = create_app(app.state.settings.get(), model_lister=fake_models, bigquery_factory=app.state.bigquery_factory)
    with TestClient(restarted) as api:
        return api.get(f'/api/builds/{bid}/feasibility').json(), api.get(f'/api/builds/{bid}').json()


@pytest.mark.parametrize('staged_flow', [(1, 1)], indirect=True)
@pytest.mark.parametrize('trigger', ['replace', 'delete'])
async def test_replan_recovers_freshness_after_reference_change(staged_flow, blueprint_api, monkeypatch, trigger):
    """Release 2.5 b_24747c71b7e3: ready but prototype_stale after a reference change and a successful replan."""
    client, app, bid, folder, bq, _ = staged_flow
    *_, llm, value = blueprint_api
    use_reference_model(app, monkeypatch)
    upload_style(client, app, bid)
    assert feasibility_check(client, app, bid)['prototype_stale']
    trace = replan(client, app, bid, llm, value, monkeypatch)
    assert trace['status'] == 'ok', trace['error']
    use_reference_model(app, monkeypatch)
    if trigger == 'replace':
        upload_style(client, app, bid)
    else:
        assert client.delete(f'/api/builds/{bid}/reference-images').status_code == 204
    stale = client.get(f'/api/builds/{bid}/feasibility').json()
    assert stale['state'] == 'stale' and stale['prototype_stale']
    execution_blocked(client, bid)
    # An explicit check alone (and GET) never re-authorizes the old artifact.
    checked = feasibility_check(client, app, bid)
    assert checked['state'] == 'ready' and checked['prototype_stale'], checked
    execution_blocked(client, bid)
    assert client.get(f'/api/builds/{bid}/feasibility').json()['prototype_stale']
    trace = replan(client, app, bid, llm, value, monkeypatch)
    assert trace['status'] == 'ok', trace['error']
    fresh = client.get(f'/api/builds/{bid}/feasibility').json()
    assert fresh['state'] == 'ready' and not fresh['prototype_stale'], fresh
    assert client.get(f'/api/builds/{bid}').json()['stage'] == 'prototype'
    executes(client, app, bid, monkeypatch)
    assessment, build = reloaded(app, bid)
    assert assessment['state'] == 'ready' and not assessment['prototype_stale'] and build['stage'] == 'done'
    assert assessment['id'] == fresh['id'] == published_proof(folder)


def published_proof(folder):
    """The fresh state and its proof are in the published ledger itself, not derived by GET."""
    from dss.spec import requirements as req
    ledger = req.load(folder)
    assert not ledger.prototype_stale and not ledger.invalidated and ledger.assessment.state == 'ready'
    return ledger.assessment.id


RECREATE = json.loads((Path(__file__).parent / 'data/recreate_definitions.json').read_text(encoding='utf-8'))
OBSERVED = ['o2', 'o3', 'o4', 'o5', 'o6']


def recreate_build(blueprint_api, monkeypatch, matching=True):
    """Staged build whose Blueprint answers the recreate fixture; KPIs that name its metrics or not."""
    from types import SimpleNamespace
    from test_blueprint import artifact, fixture
    from test_references import Capture, output
    from dss.artifacts.models import Context, Outline
    from dss.spec import references
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    context = fixture('context')
    context['datasets'][0]['source_id'] = sid
    if not matching:
        context['kpis'] = RECREATE['unmatched_kpis']
    artifact(folder, Context.model_validate(context))
    ids = dict(zip(('revenue', 'orders', 'units'), [k['id'] for k in context['kpis']]))
    outline = fixture('outline')
    template = outline['sections'][0]['questions'][0]
    outline['sections'] = [{'id': 's1', 'title': 'Store performance', 'purpose': 'Recreate the reference.', 'questions': [
        {**template, 'id': qid, 'text': text, 'kpi_refs': [ids[k] for k in dict.fromkeys(
            r['kpi'] for r in RECREATE['rows'] if r['question_id'] == qid)]} for qid, text in RECREATE['questions'].items()]}]
    artifact(folder, Outline.model_validate(outline))
    value['rows'] = [{'question_id': r['question_id'], 'section_id': 's1', 'page': 1, 'note': '', 'status': 'ok',
                      'issue_ids': [], 'component': r['component']} for r in RECREATE['rows']]
    value['derived_fields'] = [*value['derived_fields'], RECREATE['derived_field']]
    llm.replies = [json.dumps(value)]
    bq.created, bq.deleted = [], []
    bq.dry_run = lambda sql: bq.sql.append(sql) or [SimpleNamespace(name=n, field_type=t, mode='NULLABLE')
                                                     for n, t in (('order_size_band', 'STRING'), ('order_month', 'DATE'))]
    bq.create_view = lambda table, sql: bq.created.append(table)
    bq.delete_view = lambda table: bq.deleted.append(table) or True
    bq.aggregate = lambda sql: [{'region': 'West', 'order_month': '2026-01-01', 'm0': 10}]
    monkeypatch.setattr(background, 'capture', lambda html, path, width, height: path.write_bytes(b'PNG'))
    monkeypatch.setattr(references, 'decode', lambda _: None)
    build = SimpleNamespace(client=client, app=app, bid=bid, folder=folder, llm=llm, value=value, context=context,
                            vision=Capture(response=output(items=RECREATE['items']), requests=[]), extraction=None)
    monkeypatch.setattr(app.state.models, 'llm_for', lambda action: {
        'reference_extract': build.vision, 'capability_check': build.extraction}.get(action) or llm)
    return build


def upload_recreate(build, instructions=''):
    from test_references import png
    response = build.client.post(f'/api/builds/{build.bid}/reference-images', data={'mode': 'recreate', 'instructions': instructions},
                                 files=[('files', ('reference.png', png(), 'image/png'))])
    assert response.status_code == 202, response.text
    from test_context_node import wait
    wait(build.app)
    reference = build.client.get(f'/api/builds/{build.bid}/reference-images').json()
    # One extraction reply for exactly the new sources; code reconciles every definition.
    items = [{'source_id': f'{reference["id"]}:{oid}', **RECREATE['extraction'][oid]} for oid in OBSERVED]
    if instructions:
        items.append({'source_id': reference['id'] + ':instructions', **RECREATE['extraction']['instructions']})
    from test_references import Capture
    build.extraction = Capture(response=json.dumps({'requirements': items}), requests=[])
    return reference['id']


def observations(build):
    from dss.spec import requirements as req
    rows = [r for r in req.load(build.folder).requirements if r.source.kind == 'image']
    assert sorted(r.source.item_id for r in rows) == OBSERVED  # none dropped, none duplicated
    return rows


def accept(build):
    from test_blueprint import confirm
    from test_context_node import wait
    if build.client.get(f'/api/builds/{build.bid}/blueprint').json() is None:
        confirm(build.client, build.app, build.bid)
    accepted = build.client.post(f'/api/builds/{build.bid}/blueprint/accept')
    assert accepted.status_code == 202, accepted.text
    wait(build.app)
    with build.app.state.db.connect() as conn:
        trace = conn.execute('SELECT * FROM traces WHERE run_id=?', (accepted.json()['run_id'],)).fetchone()
    assert trace['status'] == 'ok', trace['error']
    assert build.client.get(f'/api/builds/{build.bid}').json()['stage'] == 'prototype'


def assert_bound(build, evidence):
    """Every observation keeps its image provenance, its definition evidence and real component ids."""
    from dss.spec import requirements as req
    ledger = req.load(build.folder)
    spec = DashboardSpec.model_validate_json((build.folder / 'spec.json').read_text(encoding='utf-8'))
    components = {c.id: c for p in spec.pages for c in p.components}
    for row in observations(build):
        assert row.source.reference_id and row.source.image_id and row.source.item_id
        proof = ledger.verification[row.id]
        bound = [entry['fulfilled_by'] for entry in proof if 'fulfilled_by' in entry]
        assert bound and bound[0] and set(bound[0]) <= components.keys(), (row.source.item_id, proof)
        assert all(components[c].type == json.loads(row.source.text)['chart_candidate'] for c in bound[0])
        metrics = [entry for entry in proof if 'mapping' in entry and entry['mapping']['aggregation']]
        assert metrics and all(entry['status'] == 'supported' and entry['definition_evidence'] == evidence(entry['mapping'])
                               for entry in metrics), proof


@pytest.mark.parametrize('case', ['kpis', 'instructions', 'both'])
def test_recreate_observations_bind_to_confirmed_definitions(blueprint_api, monkeypatch, case):
    """Release 2.5 b_b4319fb6113d: explicit definitions left every observation needs_clarification."""
    from test_context_node import wait
    build = recreate_build(blueprint_api, monkeypatch, matching=case != 'instructions')
    rid = upload_recreate(build, RECREATE['instructions'] if case != 'kpis' else '')
    assessment = feasibility_check(build.client, build.app, build.bid)
    assert assessment['state'] == 'ready', assessment['issues']
    assert build.extraction.calls == 1  # reuse and revalidation add no model call
    kpi = {'Revenue': 'kpi:net_revenue', 'Orders': 'kpi:orders', 'Units sold': 'kpi:units_sold'}
    def evidence(mapping):
        return ([kpi[mapping['label']]] if case != 'instructions' else []) + ([rid + ':instructions'] if case != 'kpis' else [])
    accept(build)
    assert_bound(build, evidence)
    fresh = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert fresh['state'] == 'ready' and not fresh['prototype_stale'], fresh
    executes(build.client, build.app, build.bid, monkeypatch)
    assessment, saved = reloaded(build.app, build.bid)
    assert assessment['state'] == 'ready' and not assessment['prototype_stale'] and saved['stage'] == 'done'
    # A copied version keeps the observations and their valid evidence, never the old authorization.
    assert build.client.post(f'/api/builds/{build.bid}/versions').status_code == 201
    copied = build.folder.parent / 'v2'
    assert build.client.get(f'/api/builds/{build.bid}/feasibility').json()['state'] == 'unchecked'
    assert feasibility_check(build.client, build.app, build.bid)['state'] == 'ready'
    assert build.extraction.calls == 1
    build.folder = copied
    observations(build)
    from dss.spec import requirements as req
    assert all(json.loads(row.mapping_origins['observed:0'])['evidence'] == evidence(row.mappings[0].model_dump())
               for row in req.load(copied).requirements if row.source.kind == 'image')


@pytest.mark.parametrize('when', ['before', 'after'])
def test_recreate_instructions_clarify_and_their_removal_blocks(blueprint_api, monkeypatch, when):
    """No matching KPI: the observations ask for definitions; reference instructions answer them."""
    build = recreate_build(blueprint_api, monkeypatch, matching=False)
    if when == 'after':
        from test_blueprint import confirm
        confirm(build.client, build.app, build.bid)
        assert build.client.get(f'/api/builds/{build.bid}/blueprint').json() is not None
    upload_recreate(build)
    blocked = feasibility_check(build.client, build.app, build.bid)
    assert blocked['state'] == 'blocked' and {i['status'] for i in blocked['issues']} == {'needs_clarification'}
    reasons = ' '.join(i['reason'] for i in blocked['issues'])
    assert all(f'Define {label}' in reasons for label in ('Revenue', 'Orders', 'Units sold')), reasons
    observations(build)
    if when == 'after':
        refused = build.client.post(f'/api/builds/{build.bid}/blueprint/accept')
        assert refused.status_code == 409 and refused.json()['error']['code'] == 'feasibility_blocked'
    rid = upload_recreate(build, RECREATE['instructions'])
    assessment = feasibility_check(build.client, build.app, build.bid)
    assert assessment['state'] == 'ready', assessment['issues']
    accept(build)
    assert_bound(build, lambda mapping: [rid + ':instructions'])
    # Replacing the set without instructions leaves no orphaned instruction binding behind.
    old = rid
    upload_recreate(build)
    execution_blocked(build.client, build.bid)
    blocked = feasibility_check(build.client, build.app, build.bid)
    assert blocked['state'] == 'blocked' and blocked['prototype_stale']
    from dss.spec import requirements as req
    ledger = req.load(build.folder)
    assert not any(s.reference_id == old for r in ledger.requirements for s in (r.source, *r.clarifications))
    assert all('observed:0' not in r.mapping_origins for r in observations(build))
    execution_blocked(build.client, build.bid)


def test_recreate_draft_and_changed_kpis_never_authorize(blueprint_api, monkeypatch):
    """A draft KPI edit authorizes nothing; a confirmed edit must still match the screenshot."""
    from test_context_node import wait
    build = recreate_build(blueprint_api, monkeypatch)
    upload_recreate(build)
    assert feasibility_check(build.client, build.app, build.bid)['state'] == 'ready'
    accept(build)
    context = {k: v for k, v in build.context.items() if k not in ('revision', 'issues')}
    context['kpis'][0]['measure']['agg'] = 'avg'
    edited = build.client.put(f'/api/builds/{build.bid}/context', json=context)
    assert edited.status_code == 200, edited.text
    assert build.client.get(f'/api/builds/{build.bid}/feasibility').json()['state'] == 'stale'
    draft = feasibility_check(build.client, build.app, build.bid)
    assert draft['state'] == 'blocked' and any('Define Revenue' in i['reason'] for i in draft['issues']), draft['issues']
    execution_blocked(build.client, build.bid, 'wrong_stage')
    assert build.client.post(f'/api/builds/{build.bid}/context/confirm').status_code == 202
    wait(build.app)
    changed = feasibility_check(build.client, build.app, build.bid)
    reasons = [i['reason'] for i in changed['issues']]
    assert changed['state'] == 'blocked' and any('screenshot shows sum' in r and 'avg' in r for r in reasons), reasons
    assert build.extraction.calls == 1
    observations(build)


def test_html_contract_geometry_layers(dashboard):
    for layer in ('all', 'decoration'):
        parsed = ContractParser(render(dashboard, layer=layer))
        items = dashboard.pages[0].decorations + dashboard.pages[0].components
        assert len(parsed.items) == len(items)
        for item in items:
            attrs = parsed.items[item.id]
            assert attrs['data-label']
            assert attrs['data-kind'] in ('component', 'decoration')
            b = box(dashboard.canvas, dashboard.grid, item.grid, height=dashboard.pages[0].height)
            for prop, key in [('left','x'),('top','y'),('width','w'),('height','h')]:
                assert f'{prop}:{b[key]}px' in attrs['style']
            assert ('display:none' in attrs['style']) == (layer == 'decoration' and attrs['data-kind'] == 'component')
        if layer == 'decoration':
            assert '<script' not in render(dashboard, layer=layer)


def test_cache_layout_revision_and_parallel_budget(dashboard, tmp_path):
    base = dashboard.pages[0].components[0]
    dashboard.pages[0].components = []
    dashboard.datasource.fields += [dashboard.datasource.fields[1].model_copy(update={'name': f'revenue{i}'}) for i in range(12)]
    for i in range(12):
        item = copy.deepcopy(base)
        item.id = f'p1_kpi_{i}'
        item.metrics[0].field = f'revenue{i}'
        item.grid.col, item.grid.row, item.grid.w, item.grid.h = (i % 4)*3 + 1, (i // 4)*8 + 5, 3, 6
        dashboard.pages[0].components.append(item)
    service = FakeBigQuery(.1)
    start = time.monotonic()
    data = aggregate_data(dashboard, service, tmp_path)
    html = render(dashboard, data=data)
    assert time.monotonic() - start < 15
    assert len(service.queries) == 12 and 2 <= service.peak <= 8
    assert html.count('12,345.50') == 12
    assert aggregate_data(dashboard, service, tmp_path) == data
    dashboard.spec_version += 1
    dashboard.pages[0].components[0].grid.row += 1
    aggregate_data(dashboard, service, tmp_path)
    assert len(service.queries) == 12
    aggregate_data(dashboard, service, tmp_path / 'v2')
    assert len(service.queries) == 24


def test_sql_aggregation_bounds_sort(dashboard):
    c = dashboard.pages[0].components[1]
    c.breakdown = 'revenue'
    c.metrics[0].agg = 'count_distinct'
    c.sort = Sort(field='revenue', order='asc')
    sql = aggregate_sql(dashboard, c)
    assert 'COUNT(DISTINCT `revenue`) AS `m0`' in sql
    assert 'GROUP BY `region`, `revenue`' in sql
    assert sql.endswith('ORDER BY `m0` ASC LIMIT 50')
    c.type = 'pivot_table'
    assert aggregate_sql(dashboard, c).endswith('LIMIT 20')
    # Defense in depth: the renderer never interpolates an order the model would reject.
    c.sort = Sort.model_construct(field='revenue', order='desc; DROP TABLE x')
    with pytest.raises(ValueError):
        aggregate_sql(dashboard, c)
    c.sort = None
    c.dimensions = ['region`; SELECT *']
    with pytest.raises(ValueError):
        aggregate_sql(dashboard, c)


def test_empty_escaping_catalog_and_theme(dashboard, monkeypatch):
    dashboard.title = '</title><script>bad()</script>'
    dashboard.pages[0].components[1].label = 'A' * 500 + '</script>'
    dashboard.theme.surface = '#FFF0AA'
    html = render(dashboard, data={'p1_regions': [{'region':'</script><script>bad()</script>', 'm0': 4}]})
    assert 'No data' in html and '#FFF0AA' in html
    assert '<script>bad()' not in html
    assert '\\u003c/script' in html and 'title="AAAA' in html
    # Non-text decorations do not participate in text layout or its font constraints.
    panel = dashboard.pages[0].decorations[0].model_copy(deep=True)
    panel.id, panel.kind, panel.text = 'p1_panel', 'panel', None
    panel.style = {'font_size': 'large', 'font_weight': 600.0}
    dashboard.pages[0].decorations.append(panel)
    from dss.spec.validate import validate_spec
    assert validate_spec(dashboard) == []
    assert 'data-cid="p1_panel"' in render(dashboard)
    monkeypatch.setattr('dss.render.prototype.catalog', lambda: {})
    with pytest.raises(ValueError, match='catalog'):
        render(dashboard)


def test_geography_and_date_binding(dashboard):
    from dss.spec.models import DataField
    dashboard.datasource.fields.append(DataField(name='place', type='GEOGRAPHY', label='Place', role='dimension'))
    dashboard.datasource.fields.append(DataField(name='date', type='DATE', label='Date', role='dimension'))
    score = dashboard.pages[0].components[0]
    score.date_dimension = 'date'
    assert 'GROUP BY' not in aggregate_sql(dashboard, score)
    c = dashboard.pages[0].components[1]
    c.type, c.dimensions, c.date_dimension = 'geo_map', ['place'], 'date'
    sql = aggregate_sql(dashboard, c)
    assert 'ST_ASGEOJSON(ST_CENTROID(`place`)) AS `place`' in sql
    assert 'GROUP BY ST_ASGEOJSON(ST_CENTROID(`place`))' in sql
    assert '`date`' not in sql
    rows = [{'place':'{"type":"Point","coordinates":[121.0,14.6]}','m0':9}]
    option = chart_option(c, rows, dashboard.theme, 550)
    assert option['series'][0]['coordinateSystem'] == 'geo'
    assert option['series'][0]['data'][0]['value'] == [121.0,14.6,9]
    c.sort = Sort(field='region', order='asc')
    assert 'ORDER BY ANY_VALUE(`region`) ASC' in aggregate_sql(dashboard, c)


def time_series(dashboard):
    from dss.spec.models import DataField
    dashboard.datasource.fields.append(DataField(name='sale_date', type='DATE', label='Date', role='dimension'))
    c = dashboard.pages[0].components[1]
    c.type, c.dimensions, c.date_dimension = 'time_series', [], 'sale_date'
    return c


@pytest.mark.parametrize('kind', ['bar', 'table', 'time_series'])
@pytest.mark.parametrize('order', ['asc', 'desc'])
def test_explicit_sort_order(dashboard, kind, order):
    c = time_series(dashboard) if kind == 'time_series' else dashboard.pages[0].components[1]
    c.type = kind
    limit = ' LIMIT 20' if kind == 'table' else ' LIMIT 50'
    c.sort = Sort(field='revenue', order=order)
    assert aggregate_sql(dashboard, c).endswith(f'ORDER BY `m0` {order.upper()}{limit}')
    grouping = 'sale_date' if kind == 'time_series' else 'region'
    c.sort = Sort(field=grouping, order=order)
    assert aggregate_sql(dashboard, c).endswith(f'ORDER BY `{grouping}` {order.upper()}{limit}')


@pytest.mark.parametrize('kind, tail', [('bar', 'ORDER BY `m0` DESC LIMIT 50'),
    ('table', 'ORDER BY `m0` DESC LIMIT 20'), ('time_series', 'ORDER BY `sale_date` ASC LIMIT 50')])
def test_absent_sort_defaults(dashboard, kind, tail):
    c = time_series(dashboard) if kind == 'time_series' else dashboard.pages[0].components[1]
    c.type, c.sort = kind, None
    assert aggregate_sql(dashboard, c).endswith(tail)


@pytest.mark.parametrize('kind', ['time_series','bar','pie','table','pivot_table','geo_map','scatter'])
def test_each_echarts_type(dashboard, kind):
    c = dashboard.pages[0].components[1]
    c.type = kind
    c.dimensions = ['region', 'category'] if kind == 'pivot_table' else ['region']
    c.metrics += [c.metrics[0].model_copy()]
    if kind == 'time_series':
        c.dimensions = []
        c.date_dimension = 'region'
        c.breakdown = 'category'
    rows = [{'region':'West','category':'A','m0':7,'m1':2}, {'region':'West','category':'B','m0':8,'m1':3}]
    option = chart_option(c, rows, dashboard.theme, 550)
    if kind in ('table','pivot_table'):
        assert option['graphic'] and '7' in json.dumps(option)
        if kind == 'pivot_table':
            assert 'A / revenue' in json.dumps(option)
    else:
        assert option['series'][0]['type'] == {'time_series':'line','geo_map':'map'}.get(kind, kind)
    if kind == 'time_series':
        assert len(option['series']) == 4
        assert option['series'][0]['data'] == [7]


def test_capture_and_artifact_order(dashboard, tmp_path, monkeypatch):
    captured = []
    def fake_capture(html, path, width, height):
        parsed = ContractParser(html)
        assert all('display:none' in a['style'] for a in parsed.items.values() if a['data-kind'] == 'component')
        captured.append((width, height))
        path.write_bytes(b'PNG')
    monkeypatch.setattr(background, 'capture', fake_capture)
    artifacts(dashboard, FakeBigQuery(), tmp_path)
    assert captured == [(1200, 900)]
    assert (tmp_path / 'background_p1.png').read_bytes() == b'PNG'
    assert '12,345.50' in (tmp_path / 'prototype.html').read_text(encoding='utf-8')


def test_synthetic_background_has_visible_label_pixels(dashboard, tmp_path):
    import base64
    from playwright.sync_api import sync_playwright
    from dss.spec.layout import with_synthetic_label
    from dss.spec.models import SYNTHETIC_LABEL_ID
    spec = with_synthetic_label(dashboard, True)
    html = render(spec, layer='decoration')
    path = tmp_path / 'background_p1.png'
    background.capture(html, path, spec.canvas.width, spec.canvas.height)
    assert struct.unpack('>II', path.read_bytes()[16:24]) == (3600, 3 * spec.canvas.height)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            # At device scale 3 the 3x background maps 1:1 onto the reference pixels.
            page = browser.new_page(viewport={'width': 1200, 'height': spec.canvas.height}, device_scale_factor=3)
            page.set_content(html)
            label = page.locator(f'[data-cid="{SYNTHETIC_LABEL_ID}"]')
            assert label.inner_text() == 'Synthetic sample data'
            bounds = label.bounding_box()
            expected = label.screenshot()
            encoded = base64.b64encode(path.read_bytes()).decode()
            page.set_content(f'<body style="margin:0"><img style="display:block;width:1200px" src="data:image/png;base64,{encoded}"></body>')
            page.locator('img').wait_for()
            assert page.screenshot(clip=bounds) == expected
        finally:
            browser.close()


def test_heading_content_and_background_bounds(dashboard):
    """Independent DOM ranges assert visible text, contract geometry and matching pixels."""
    import base64
    from playwright.sync_api import sync_playwright
    from dss.spec.layout import with_synthetic_label
    from dss.spec.models import Decoration
    from dss.spec.validate import validate_spec
    evidence = Path('.blueprint/qa/task-13.3')
    evidence.mkdir(parents=True, exist_ok=True)
    dashboard.theme.radius = 1000  # Rounded backgrounds must not mask heading glyphs.
    dashboard.pages[0].components = []
    dashboard.pages[0].decorations = [
        Decoration(id='p1_title', kind='title', text='Weekly sales overview', grid=dict(col=1,row=1,w=12,h=3)),
        Decoration(id='p1_large', kind='title', text='Revenue by region', style={'font_size':40},
                   grid=dict(col=1,row=5,w=12,h=4)),
        Decoration(id='p1_subtitle', kind='subtitle', text='Weekly revenue\nRegional performance',
                   grid=dict(col=1,row=10,w=12,h=4)),
        Decoration(id='p1_wrap', kind='title', text='Regional revenue performance across business units',
                   grid=dict(col=1,row=15,w=4,h=12)),
        Decoration(id='p1_word', kind='subtitle', text='W' * 90,
                   style={'font-size':'18px', 'font-weight': 'bold'}, grid=dict(col=6,row=15,w=4,h=12)),
    ]
    spec = with_synthetic_label(dashboard, True)
    assert validate_spec(spec) == []
    html = render(spec)
    (evidence / 'prototype.html').write_text(html, encoding='utf-8')
    background_path = evidence / 'background_p1.png'
    background.capture(render(spec, layer='decoration'), background_path, 1200, spec.canvas.height)
    assert struct.unpack('>II', background_path.read_bytes()[16:24]) == (3600, 3 * spec.canvas.height)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width':1200, 'height':spec.canvas.height}, device_scale_factor=3)
            page.set_content(html)
            page.screenshot(path=str(evidence / 'prototype.png'), full_page=True)
            for item in spec.pages[0].decorations:
                locator = page.locator(f'[data-cid="{item.id}"]')
                assert locator.text_content() == item.text
                bounds = locator.bounding_box()
                expected = box(spec.canvas, spec.grid, item.grid)
                assert bounds == dict(x=expected['x'],y=expected['y'],width=expected['w'],height=expected['h'])
                assert 0 <= bounds['x'] < bounds['x'] + bounds['width'] <= 1200
                assert 0 <= bounds['y'] < bounds['y'] + bounds['height'] <= spec.canvas.height
                assert locator.evaluate('''el => {
                    const b=el.getBoundingClientRect(), s=getComputedStyle(el), pad=parseFloat(s.paddingTop);
                    const inner=el.firstElementChild, r=document.createRange(); r.selectNodeContents(inner);
                    return inner.getBoundingClientRect().height <= b.height-2*pad+.01 &&
                        [...r.getClientRects()].every(t => t.top>=b.top+pad-.01 && t.bottom<=b.bottom-pad+.01 &&
                            t.left>=b.left+pad-.01 && t.right<=b.right-pad+.01);
                }''')
            expected_png = page.screenshot()
            encoded = base64.b64encode(background_path.read_bytes()).decode()
            page.set_content(f'<body style="margin:0"><img style="display:block;width:1200px" src="data:image/png;base64,{encoded}"></body>')
            page.locator('img').wait_for()
            assert page.screenshot() == expected_png
        finally:
            browser.close()


def test_clipped_heading_cannot_be_rendered(dashboard):
    dashboard.pages[0].decorations[0].grid.h = 2
    for layer in ('all', 'decoration'):
        with pytest.raises(ValueError, match='text does not fit'):
            render(dashboard, layer=layer)


async def test_render_node_events_and_api(client, app, build_id, dashboard, tmp_path, monkeypatch):
    from dss.harness.tracing import Trace
    from dss.db import new_id
    def events(app, build_id):
        with app.state.db.connect() as conn:
            return [(row[0], json.loads(row[1])) for row in conn.execute(
                "SELECT kind,payload_json FROM events WHERE build_id=? ORDER BY rowid", (build_id,))]
    config = app.state.settings.get()
    folder = config.data_dir / 'builds' / build_id / 'v1'
    folder.mkdir(parents=True)
    (folder / 'spec.json').write_text(dashboard.model_dump_json())
    monkeypatch.setattr(background, 'capture', lambda html, path, w, h: path.write_bytes(b'PNG'))
    run_id = new_id('r')
    trace = Trace(app.state.db, run_id, build_id, 'render')
    await perform(app.state.harness, build_id, run_id, {'config':config,'factory':lambda c: FakeBigQuery()}, trace)
    assert ('prototype.updated', {'spec_version':1}) in events(app, build_id)
    assert ('stage.changed', {'stage':'prototype'}) in events(app, build_id)
    assert client.get(f'/api/builds/{build_id}').json()['stage'] == 'prototype'
    html = client.get(f'/api/builds/{build_id}/prototype').text
    assert '12,345.50' in html
    assert all('display:none' in a['style'] for a in ContractParser(client.get(f'/api/builds/{build_id}/prototype?layer=decoration').text).items.values() if a['data-kind'] == 'component')




@pytest.mark.live
def test_real_background_dimensions(dashboard, tmp_path):
    path = tmp_path / 'background_p1.png'
    background.capture(render(dashboard, layer='decoration'), path, 1200, 900)
    assert struct.unpack('>II', path.read_bytes()[16:24]) == (3600, 2700)


@pytest.mark.live
def test_twelve_component_full_render_budget(dashboard, tmp_path):
    base = dashboard.pages[0].components[0]
    dashboard.pages[0].components = []
    for i in range(12):
        item = copy.deepcopy(base)
        item.id = f'p1_kpi_{i}'
        item.grid.col, item.grid.row, item.grid.w, item.grid.h = (i % 4)*3+1, (i // 4)*8+5, 3, 6
        item.metrics[0].field = f'revenue{i}'
        dashboard.datasource.fields.append(dashboard.datasource.fields[1].model_copy(update={'name':f'revenue{i}'}))
        dashboard.pages[0].components.append(item)
    service = FakeBigQuery(.1)
    start = time.monotonic()
    artifacts(dashboard, service, tmp_path)
    elapsed = time.monotonic()-start
    print(f'12 components plus actual Chromium background: {elapsed:.2f}s; queries={len(service.queries)}')
    assert elapsed < 15
    assert len(service.queries) == 12
    png = (tmp_path / 'background_p1.png').read_bytes()
    assert struct.unpack('>II', png[16:24]) == (3600, 3 * dashboard.pages[0].height)
    assert len(png) < 2 * 1024 * 1024
    artifacts(dashboard, service, tmp_path)
    assert len(service.queries) == 12


DESIGNED = Path('tests/data/designed_spec.json')
# sha256 of render(golden_spec.json) for layer all / decoration, recorded before designed pages (20.2).
GOLDEN_PROTOTYPE = ('1481af850dd5c99f617b2a6524220be154b05ee17de988cfda58325fd1f10727',
                    '9d7b1aaa26c6d85d994835a5f598205b67fc7fa43366fb532a55da05e3080fd4')


def designed_spec():
    return DashboardSpec.model_validate_json(DESIGNED.read_text(encoding='utf-8'))


def test_golden_code_laid_prototype_is_byte_identical():
    from hashlib import sha256
    spec = DashboardSpec.model_validate_json(Path('tests/data/golden_spec.json').read_text(encoding='utf-8'))
    assert tuple(sha256(render(spec, layer=layer).encode()).hexdigest() for layer in (None, 'decoration')) == GOLDEN_PROTOTYPE
    assert '@scope' not in render(spec) and 'dss-design' not in render(spec)


def test_designed_prototype_html_contract():
    spec = designed_spec()
    page = spec.pages[0]
    for layer in (None, 'decoration'):
        html = render(spec, layer=layer)
        parsed = PageParser(html)  # asserts one data-cid per item and none nested
        assert set(parsed.items) == {i.id for i in page.decorations + page.components}
        assert {tuple((t, i) for t, i, _ in a['chain']) for a in parsed.items.values()} == {(('div', 'dss-canvas'), ('section', None))}
        assert f'width:1440px;height:{page.height}px' in parsed.canvas[0]['style']
        root = parsed.items['p1_design']
        assert root['data-kind'] == 'decoration' and 'display:none' not in root['style']
        assert all(f'{k}:{v}px' in root['style'] for k, v in (('left', 0), ('top', 0), ('width', 1440), ('height', page.height)))
        for c in page.components:
            attrs = parsed.items[c.id]
            assert all(f'{k}:{getattr(c.box, v)}px' in attrs['style'] for k, v in (('left', 'x'), ('top', 'y'), ('width', 'w'), ('height', 'h')))
            assert ('display:none' in attrs['style']) == (layer == 'decoration')
        # The design root comes first (under everything); the code-drawn footer is still there.
        assert list(parsed.items)[:2] == ['p1_design', 'p1_synthetic_sample_data']
        assert html.count('class="dss-design dss-design-p1"') == 1 and '@scope (#dss-canvas) to (.dss-design)' in html


def test_designed_prototype_sanitizes_the_stored_design_again():
    spec = designed_spec()
    spec.pages[0].design.html += ('<script>alert(1)</script><div onclick="steal()" data-cid="p1_fake">x</div>'
                                  '<style>.x{background:url(http://evil.test/a.png)}@import "http://evil.test";</style>'
                                  '<a href="javascript:alert(2)">link</a><svg><foreignObject>f</foreignObject></svg>')
    html = render(spec, layer='decoration')
    for hostile in ('alert(', 'steal', 'p1_fake', 'evil.test', 'javascript:', 'foreignObject', '<a '):
        assert hostile not in html
    assert 'Sales Operations Overview' in html and 'data-slot="p1_kpi_revenue"' in html


def test_designed_page_draws_components_on_their_slots_in_chromium():
    from playwright.sync_api import sync_playwright
    spec = designed_spec()
    page = spec.pages[0]
    script = '''() => { const s = document.querySelector('section').getBoundingClientRect();
      const rect = e => { const r = e.getBoundingClientRect(); return [r.x - s.x, r.y - s.y, r.width, r.height]; };
      return {slots: Object.fromEntries([...document.querySelectorAll('[data-slot]')].map(e => [e.dataset.slot, rect(e)])),
              items: Object.fromEntries([...document.querySelectorAll('[data-cid]')].map(e => [e.dataset.cid,
                     [...rect(e), getComputedStyle(e).display]]))}; }'''
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            tab = browser.new_page(viewport={'width': 1440, 'height': page.height})
            tab.set_content(render(spec))
            shown = tab.evaluate(script)
            tab.set_content(render(spec, layer='decoration'))
            hidden = tab.evaluate(script)
        finally:
            browser.close()
    for c in page.components:
        expected = [c.box.x, c.box.y, c.box.w, c.box.h]
        assert shown['slots'][c.id] == expected and shown['items'][c.id][:4] == expected
        assert hidden['items'][c.id][4] == 'none'
    assert shown['items']['p1_design'] == [0, 0, 1440, page.height, 'block'] == hidden['items']['p1_design']
    assert hidden['slots'] == shown['slots']


def test_designer_z_index_never_paints_over_components_or_the_footer():
    from playwright.sync_api import sync_playwright
    spec = designed_spec()
    page = spec.pages[0]
    page.design.html += '<style>.dss-design-p1{z-index:9}.card,.kpi{position:relative;z-index:5}</style>'
    items = page.components + [d for d in page.decorations if d.kind != 'design']
    centres = {i.id: (b['x'] + b['w'] // 2, b['y'] + b['h'] // 2) for i in items
               for b in [i.box.model_dump() if getattr(i, 'box', None) else box(spec.canvas, spec.grid, i.grid, height=page.height)]}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            tab = browser.new_page(viewport={'width': 1440, 'height': page.height})
            tab.set_content(render(spec))
            hits = tab.evaluate('''centres => Object.fromEntries(Object.entries(centres).map(([cid, [x, y]]) =>
                [cid, document.elementFromPoint(x, y).closest('[data-cid]').dataset.cid]))''', centres)
        finally:
            browser.close()
    assert hits == {cid: cid for cid in centres}


def test_designed_background_is_3x_and_under_2mb(tmp_path):
    spec = designed_spec()
    assert background.write_pages(spec, tmp_path) == {'background_p1.png': 3}
    png = (tmp_path / 'background_p1.png').read_bytes()
    assert struct.unpack('>II', png[16:24]) == (4320, 3 * spec.pages[0].height)
    assert len(png) < 2 * 1024 * 1024


def test_designed_background_over_2mb_at_3x_falls_back_to_2x(tmp_path, monkeypatch):
    calls = []
    def fake_capture(html, path, width, height, scale=background.SCALE):
        calls.append((width, height, scale))
        path.write_bytes(b'x' * (background.LIMIT if scale == 3 else 10))
    monkeypatch.setattr(background, 'capture', fake_capture)
    spec = designed_spec()
    assert background.write_pages(spec, tmp_path) == {'background_p1.png': 2}
    assert calls == [(1440, spec.pages[0].height, 3), (1440, spec.pages[0].height, 2)]
    assert (tmp_path / 'background_p1.png').read_bytes() == b'x' * 10
    # A code-laid page never drops below 3x.
    calls.clear()
    code = three_pages()
    assert background.write_pages(code, tmp_path) == {name: 3 for name in background.names(code)}
    assert [scale for *_, scale in calls] == [3, 3, 3]
