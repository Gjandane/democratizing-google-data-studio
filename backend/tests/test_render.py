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
from dss.spec import feasibility
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
    monkeypatch.setattr(background, 'capture', lambda html, path, width, height, scale=3: path.write_bytes(b'PNG'))
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
    from test_reference_brief import BriefLLM
    from test_designer import ReferenceHTMLLLM
    pair = {'reference_brief': BriefLLM(), 'reference_html': ReferenceHTMLLLM()}
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: pair.get(node) or llm)
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


def observed(data):
    return sorted(k for k in data['extraction'] if k != 'instructions')


def recreate_build(blueprint_api, monkeypatch, matching=True, data=RECREATE, synthetic=False, designer=None, designed=True,
                   brief=None, reference_html=None):
    """Staged build whose Blueprint answers the recreate fixture `data`; KPIs that name its metrics or
    not; a synthetic (screenshot-only) source or the uploaded one; `designer` answers the designer node
    (`designed` False: Config.designed_pages off)."""
    from types import SimpleNamespace
    from test_blueprint import artifact, fixture
    from test_references import Capture, output
    from dss.artifacts.models import Context, Outline
    from dss.spec import references
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    context = fixture('context')
    context['datasets'][0]['source_id'] = sid
    if not matching:
        context['kpis'] = data['unmatched_kpis']
    if 'kpis' in data:
        # A release build's own confirmed KPIs and connected columns (22.1 gap fixtures).
        context.update(kpis=data['kpis'], derived_fields=[])
        with app.state.db.connect() as conn:
            conn.execute('UPDATE sources SET columns_json=? WHERE id=?', (json.dumps([{**c, 'sample': []} for c in data['columns']]), sid))
    artifact(folder, Context.model_validate(context))
    ids = dict(zip(('revenue', 'orders', 'units'), [k['id'] for k in context['kpis']]))
    outline = fixture('outline')
    template = outline['sections'][0]['questions'][0]
    if 'sections' in data:
        outline['sections'] = data['sections']  # a release build's own sections and questions (24.7)
    else:
        outline['sections'] = [{'id': 's1', 'title': 'Store performance', 'purpose': 'Recreate the reference.', 'questions': [
            {**template, 'id': qid, **question} if isinstance(question, dict) else
            {**template, 'id': qid, 'text': question, 'kpi_refs': [ids[k] for k in dict.fromkeys(
                r['kpi'] for r in data['rows'] if r['question_id'] == qid)]} for qid, question in data['questions'].items()]}]
    artifact(folder, Outline.model_validate(outline))
    value['rows'] = [{'question_id': r['question_id'], 'section_id': r.get('section_id', 's1'), 'page': r.get('page', 1),
                      'note': r.get('note', ''), 'status': 'ok', 'issue_ids': [], 'component': r['component']} for r in data['rows']]
    value['derived_fields'] = data['derived_fields'] if 'derived_fields' in data else [*value['derived_fields'], data['derived_field']]
    llm.replies = [json.dumps(value)]
    bq.created, bq.deleted = [], []
    bq.dry_run = lambda sql: bq.sql.append(sql) or [SimpleNamespace(name=n, field_type=t, mode='NULLABLE')
                                                     for n, t in (('order_size_band', 'STRING'), ('order_month', 'DATE'))]
    bq.create_view = lambda table, sql: bq.created.append(table)
    bq.delete_view = lambda table: bq.deleted.append(table) or True
    bq.aggregate = lambda sql: [{'region': 'West', 'order_month': '2026-01-01', 'm0': 10}]
    monkeypatch.setattr(background, 'capture', lambda html, path, width, height, scale=None: path.write_bytes(b'PNG'))
    monkeypatch.setattr(references, 'decode', lambda _: None)
    if synthetic:
        from dss.spec.models import SYNTHETIC_LABEL
        with app.state.db.connect() as conn:
            conn.execute("UPDATE sources SET kind='synthetic', name=? WHERE id=?", (SYNTHETIC_LABEL, sid))
    if not designed:
        monkeypatch.setattr(app.state.settings, 'defaults', app.state.settings.defaults.model_copy(update={'designed_pages': False}))
    build = SimpleNamespace(client=client, app=app, bid=bid, folder=folder, llm=llm, value=value, context=context, data=data,
                            vision=Capture(response=output(items=data['items']), requests=[]), extraction=None)
    from test_reference_brief import BriefLLM
    from test_designer import ReferenceHTMLLLM
    build.brief = brief or BriefLLM()
    build.reference_html = reference_html or designer or ReferenceHTMLLLM()
    monkeypatch.setattr(app.state.models, 'llm_for', lambda action: {
        'reference_extract': build.vision, 'capability_check': build.extraction, 'designer': designer,
        'reference_brief': build.brief, 'reference_html': build.reference_html}.get(action) or llm)
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
    extraction = build.data['extraction']
    items = [{'source_id': f'{reference["id"]}:{oid}', **extraction[oid]} for oid in observed(build.data)]
    from dss.spec import requirements as req
    if instructions and not req._wholly_definitions(instructions):  # code reads definition-only instructions itself
        records = extraction['instructions']
        items += [{'source_id': reference['id'] + ':instructions', **record}
                  for record in (records if isinstance(records, list) else [records])]
    from test_references import Capture
    build.extraction = Capture(response=json.dumps({'requirements': items}), requests=[])
    return reference['id']


def observations(build):
    from dss.spec import requirements as req
    rows = [r for r in req.load(build.folder).requirements if r.source.kind == 'image']
    assert sorted(r.source.item_id for r in rows) == observed(build.data)  # none dropped, none duplicated
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


def assert_bound(build, evidence, dropped=()):
    """Every observation keeps its image provenance, its definition evidence and real component ids
    (`dropped`: item ids the user dropped)."""
    from dss.spec import requirements as req
    ledger = req.load(build.folder)
    spec = DashboardSpec.model_validate_json((build.folder / 'spec.json').read_text(encoding='utf-8'))
    components = {c.id: c for p in spec.pages for c in p.components}
    for row in observations(build):
        assert row.source.reference_id and row.source.image_id and row.source.item_id
        if row.source.item_id in dropped:
            continue
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


RECREATE_DESIGNED = json.loads((Path(__file__).parent / 'data/recreate_designed.json').read_text(encoding='utf-8'))
# 24.10: a code-assigned observed title shows its definition's unit (`Revenue = SUM(revenue) in USD`).
TITLES = {'Revenue (USD)', 'Orders', 'Units sold', 'Revenue by month (USD)', 'Revenue by region (USD)'}


def spans(app, run_id):
    with app.state.db.connect() as conn:
        trace = conn.execute('SELECT * FROM traces WHERE run_id=?', (run_id,)).fetchone()
    return trace, json.loads(trace['spans_json'])


@pytest.mark.parametrize('case', ['designed', 'code', 'synthetic'])
def test_recreate_accept_publishes_with_planner_titles(blueprint_api, monkeypatch, case):
    """Release 2.5 b_7ca302e800cc, b_dfb67c24f176: every recreate accept failed publish coverage. The
    planner titled the observed charts its own way, the extractor cited observation ids as
    components, and the month SQL ended in a space; designed pages were not the cause."""
    from test_designer import DesignerLLM
    designer = DesignerLLM() if case != 'code' else None
    build = recreate_build(blueprint_api, monkeypatch, data=RECREATE_DESIGNED, synthetic=case == 'synthetic',
                           designer=designer, designed=case != 'code')
    rid = upload_recreate(build, RECREATE_DESIGNED['instructions'])
    assessment = feasibility_check(build.client, build.app, build.bid)
    assert assessment['state'] == 'ready', assessment['issues']
    assert build.extraction.calls == 1
    accept(build)
    spec = DashboardSpec.model_validate_json((build.folder / 'spec.json').read_text(encoding='utf-8'))
    assert spec.datasource.synthetic == (case == 'synthetic')
    assert all(p.design for p in spec.pages) if designer else not any(p.design for p in spec.pages)
    # 23.2: the page-1 background draws the provenance label; the recipe never draws it again.
    from dss.recipe.compiler import compile_recipe
    from dss.spec.models import SYNTHETIC_LABEL
    assert (SYNTHETIC_LABEL in render(spec, layer='decoration', page=1)) == (case == 'synthetic')
    assert SYNTHETIC_LABEL not in compile_recipe(spec, 1)
    if designer:
        assert designer.calls == len(spec.pages) and build.brief.calls == len(spec.pages)
        # The designer laid its cards out around the observed titles.
        assert all(f'>{c.label}<' in p.design.html for p in spec.pages for c in p.components)
    components = [c for p in spec.pages for c in p.components]
    assert {c.label for c in components} == TITLES and len(components) == len(RECREATE_DESIGNED['rows'])
    kpi = {'Revenue': 'kpi:net_revenue', 'Orders': 'kpi:orders', 'Units sold': 'kpi:units_sold'}
    assert_bound(build, lambda mapping: [kpi[mapping['label']], rid + ':instructions'])
    from dss.spec import requirements as req
    ledger = req.load(build.folder)
    # Every image row keeps its provenance and binds only real components (no cited item ids).
    assert all(set(r.component_ids) <= {c.id for c in components} for r in ledger.requirements)
    month = next(r for r in ledger.requirements if r.text.startswith('Revenue by month ='))
    assert [e['fulfilled_by'] for e in ledger.verification[month.id] if 'fulfilled_by' in e] == [['p1_monthly_revenue_trend']]
    with build.app.state.db.connect() as conn:
        run_id = conn.execute("SELECT run_id FROM traces WHERE node='prototype' ORDER BY started_at DESC").fetchone()[0]
    trace, recorded = spans(build.app, run_id)
    assert next(s for s in recorded if s['node'] == 'layout')['observed_titles'] == len(TITLES)
    assert all('coverage_errors' not in s for s in recorded)
    fresh = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert fresh['state'] == 'ready' and not fresh['prototype_stale'], fresh
    executes(build.client, build.app, build.bid, monkeypatch)


def test_recreate_accept_uses_checked_brief_and_html_with_real_decisions(blueprint_api, monkeypatch):
    from test_reference_brief import BriefLLM, section, attached
    from test_designer import ReferenceHTMLLLM
    from dss.harness.context import COMPONENTS_HEADER
    from test_blueprint import choose, confirm
    from dss.spec import requirements as req
    # The gap fixture forces explicit substitutions/drops before composition.
    build = gap_build(blueprint_api, monkeypatch, 'table')
    monkeypatch.setattr(build.app.state.settings, 'defaults', build.app.state.settings.defaults.model_copy(
        update={'designed_pages': True}))
    brief, html = BriefLLM(), ReferenceHTMLLLM()
    route = build.app.state.models.llm_for
    monkeypatch.setattr(build.app.state.models, 'llm_for', lambda node: {
        'reference_brief': brief, 'reference_html': html}.get(node) or route(node))
    confirm(build.client, build.app, build.bid)
    blocked = build.client.post(f'/api/builds/{build.bid}/blueprint/accept')
    assert blocked.status_code == 409 and not brief.requests and not html.requests
    for oid, fix in GAP_FIXES['table'].items():
        assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
        assert choose(build.client, build.bid, assessment, gap_issues(assessment, build)[oid], fix).status_code == 200
    accept(build)
    spec = DashboardSpec.model_validate_json((build.folder / 'spec.json').read_text(encoding='utf-8'))
    assert all(p.design and p.design.model == html.model for p in spec.pages)
    assert len(brief.requests) == html.calls == 1
    approved = json.loads(section(str(brief.requests[0].config.system_instruction), COMPONENTS_HEADER))
    implementation = json.loads(section(str(html.requests[0].config.system_instruction), COMPONENTS_HEADER))
    strip_minima = lambda rows: [{k: v for k, v in c.items() if k not in ('min_w', 'min_h')} for c in rows]
    assert strip_minima(approved['components']) == strip_minima(implementation['components'])
    assert all(c['min_w'] and c['min_h'] for c in implementation['components'])
    assert approved['decisions'] == implementation['decisions'] and len(approved['decisions']) >= 3
    assert attached(brief.requests[0])[1] == attached(html.requests[0])[1]
    assert all(e['id'] in {c.id for p in spec.pages for c in p.components} for e in approved['components'])
    with build.app.state.db.connect() as conn:
        run_id = conn.execute("SELECT run_id FROM traces WHERE node='prototype' ORDER BY started_at DESC").fetchone()[0]
    trace, recorded = spans(build.app, run_id)
    assert [s['model'] for s in recorded if s['node'] in ('reference_brief', 'reference_html')] == [brief.model, html.model]
    assert req.load(build.folder).assessment.state == 'ready'


def test_failed_publish_coverage_records_its_errors_in_the_publish_span(blueprint_api, monkeypatch):
    """Release 2.5 b_48ef72ff1bff: a Blueprint with no month bucket cannot recreate the monthly chart;
    publish still refuses it, and the trace now says which requirements failed."""
    data = json.loads(json.dumps(RECREATE_DESIGNED))
    trend = next(r for r in data['rows'] if r['component']['type'] == 'time_series')
    trend['component'].update(date_dimension='order_date', sort={'field': 'order_date', 'order': 'asc'})
    build = recreate_build(blueprint_api, monkeypatch, data=data, designed=False)
    # 22.1 shows this gap at the Blueprint; without that check the Blueprint is ready, as it was in 2.5.
    monkeypatch.setattr(feasibility, 'observation_errors', lambda *args: [])
    upload_recreate(build, data['instructions'])
    assert feasibility_check(build.client, build.app, build.bid)['state'] == 'ready'
    from test_blueprint import confirm
    from test_context_node import wait
    if build.client.get(f'/api/builds/{build.bid}/blueprint').json() is None:
        confirm(build.client, build.app, build.bid)
    accepted = build.client.post(f'/api/builds/{build.bid}/blueprint/accept')
    assert accepted.status_code == 202, accepted.text
    wait(build.app)
    trace, recorded = spans(build.app, accepted.json()['run_id'])
    assert (trace['status'], trace['error']) == ('error', 'invalid_request')
    publish = next(s for s in recorded if s['node'] == 'publish')
    errors = publish['coverage_errors']
    from dss.spec import requirements as req
    ledger = req.load(build.folder)
    monthly = {r.id for r in ledger.requirements if 'by month' in r.text}
    assert {e['path'] for e in errors} == {'requirements.' + rid for rid in monthly} and len(monthly) == 2
    assert all(set(e) == {'path', 'message'} and e['message'].startswith('Candidate spec does not fulfill') for e in errors)
    # Nothing was dropped or relaxed to pass: the other observations kept their titles, the stage stays.
    observations(build)
    assert build.client.get(f'/api/builds/{build.bid}').json()['stage'] == 'blueprint'
    with build.app.state.db.connect() as conn:
        finished = [json.loads(r[0]) for r in conn.execute(
            "SELECT payload_json FROM events WHERE run_id=? AND kind='run.finished'", (accepted.json()['run_id'],))]
    assert finished == [{'run_id': accepted.json()['run_id'], 'node': 'prototype', 'status': 'error',
                         'error': 'Candidate no longer fulfills the active requirements'}]  # run.finished shape unchanged


GAPS = json.loads((Path(__file__).parent / 'data/recreate_blueprint_gaps.json').read_text(encoding='utf-8'))
# Each release build's gaps: {observation item id: the alternative that closes it}.
GAP_FIXES = {'monthly': {'o5': 'date_bucket'}, 'table': {'o5': 'date_bucket', 'o7': 'observed_type'}}


def gap_build(blueprint_api, monkeypatch, case):
    """A gap fixture build, ready before drafting, whose planner answers the draft and the one row
    repair with the release build's own rows."""
    data = GAPS[case]
    build = recreate_build(blueprint_api, monkeypatch, data=data, synthetic=data['synthetic'], designed=False)
    build.rid = upload_recreate(build, data['instructions'])
    assessment = feasibility_check(build.client, build.app, build.bid)
    # The user's own drops in the release build, replayed before drafting.
    from dss.spec import requirements as req
    owners = {r.text: r.source.item_id or 'instructions' for r in req.load(build.folder).requirements}
    pending = [i for i in assessment['issues'] if i['resolution'] == 'unresolved']
    assert {owners[i['requirement']] for i in pending} == set(data['dropped']), pending
    dropped = build.client.post(f'/api/builds/{build.bid}/feasibility/decisions', json={'assessment_id': assessment['id'],
        'decisions': [{'issue_id': i['id'], 'action': 'drop', 'alternative_id': None} for i in pending]})
    assert dropped.status_code == 200, dropped.text
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert assessment['state'] == 'ready', assessment['issues']
    rows = build.value['rows']
    build.llm.replies = [json.dumps(build.value), json.dumps({'rows': [r for r in rows if r['question_id'] in ('q5', 'q9')]})]
    return build


def observed_titles(build):
    """{observation item id: its code-assigned title} (24.10: requirements.observed_title)."""
    from dss.spec import requirements as req
    kpis = req.inputs(build.app.state.db, build.bid, build.folder).get('confirmed_kpis')
    return {r.source.item_id: req.observed_title(next(p.value for p in r.properties if p.path == 'label'), r, kpis)
            for r in req.load(build.folder).requirements if r.source.kind == 'image'}


def gap_issues(assessment, build):
    """{observation item id: its unresolved Blueprint issue} (instruction records get their own), named by
    the observation's code-assigned title."""
    titles = observed_titles(build)
    return {oid: issue for issue in assessment['issues'] for oid, title in titles.items()
            if issue['requirement'] == f'Observation {title!r}' and issue['resolution'] == 'unresolved'}


@pytest.mark.parametrize('case', ['monthly', 'table'])
def test_recreate_gaps_show_at_the_blueprint_and_publish_after_the_decision(blueprint_api, monkeypatch, case):
    """Final audit 2026-10-23 (b_48ef72ff1bff, b_dfb67c24f176): the Blueprint reported ready and accept then
    failed publish coverage with no recovery. Each gap is now an Issue on the Assessment with its
    code-built alternative; the decision makes the Blueprint ready, and accept publishes."""
    from test_blueprint import choose, confirm
    build = gap_build(blueprint_api, monkeypatch, case)
    confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 2  # the draft and the one existing row repair, never a second
    repair = str(build.llm.seen[1].config.system_instruction)
    assert 'has no matching Blueprint row' in repair and 'Recreate observations' in repair
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert assessment['state'] == 'blocked'
    gaps = gap_issues(assessment, build)
    assert gaps.keys() == GAP_FIXES[case].keys(), assessment['issues']
    for oid, issue in gaps.items():
        assert issue['status'] == 'needs_clarification' and 'no matching Blueprint row' in issue['reason']
        assert GAP_FIXES[case][oid] in {a['id'] for a in issue['alternatives']}, issue
    assert 'month bucket of order_date' in gaps['o5']['reason']
    assert 'order_date_month' in ' '.join(a['label'] for a in gaps['o5']['alternatives'])
    if case == 'table':
        assert 'is a bar, the observation is a table' in gaps['o7']['reason']
    # Accept before deciding is refused like any other blocked row.
    refused = build.client.post(f'/api/builds/{build.bid}/blueprint/accept')
    assert refused.status_code == 409 and refused.json()['error']['code'] == 'feasibility_blocked'
    assert set(refused.json()['error']['detail']['issue_ids']) >= {i['id'] for i in gaps.values()}
    for oid, fix in GAP_FIXES[case].items():
        current = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
        decided = choose(build.client, build.bid, current, gap_issues(current, build)[oid], fix)
        assert decided.status_code == 200, decided.text
    ready = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert ready['state'] == 'ready', [i['reason'] for i in ready['issues'] if i['resolution'] == 'unresolved']
    assert build.llm.calls == 2  # the decision made it ready without a model call
    blueprint = build.client.get(f'/api/builds/{build.bid}/blueprint').json()
    assert any(f['name'] == 'order_date_month' and f['expression'] == 'DATE_TRUNC(order_date, MONTH)'
               for f in blueprint['derived_fields'])
    assert blueprint['view_table'] is None and all(r['status'] == 'ok' for r in blueprint['rows'])
    accept(build)
    kpi = {'Revenue': 'kpi:total_revenue', 'Orders': 'kpi:total_orders', 'Units sold': 'kpi:units_sold'}
    instructions = [] if 'instructions' in build.data['dropped'] else [build.rid + ':instructions']
    assert_bound(build, lambda mapping: [kpi[mapping['label']], *instructions], build.data['dropped'])
    from dss.spec import requirements as req
    drops = {d['requirement_id'] for d in req.load(build.folder).decisions if d['action'] == 'drop'}
    # Only the user's own earlier drops: code dropped no observation.
    assert {r.source.item_id for r in observations(build) if r.id in drops} == set(build.data['dropped']) - {'instructions'}
    spec = DashboardSpec.model_validate_json((build.folder / 'spec.json').read_text(encoding='utf-8'))
    components, titles = {c.label: c for p in spec.pages for c in p.components}, observed_titles(build)
    assert titles['o5'] == 'Revenue by month (USD)'  # 24.10: its definition's unit
    assert (components[titles['o5']].type, components[titles['o5']].date_dimension) == ('time_series', 'order_date_month')
    if case == 'table':
        assert components[titles['o7']].type == 'table'
    fresh = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert fresh['state'] == 'ready' and not fresh['prototype_stale'], fresh
    executes(build.client, build.app, build.bid, monkeypatch)


@pytest.mark.parametrize('case', ['monthly', 'table'])
def test_recreate_gap_fixtures_reproduce_the_release_failure(blueprint_api, monkeypatch, case):
    """Without the Blueprint observation check (the 2.5 code) each fixture's Blueprint is ready and accept
    fails publish coverage on exactly its gap observations."""
    from test_blueprint import confirm
    from test_context_node import wait
    monkeypatch.setattr(feasibility, 'observation_errors', lambda *args: [])
    build = gap_build(blueprint_api, monkeypatch, case)
    confirm(build.client, build.app, build.bid)
    assert build.client.get(f'/api/builds/{build.bid}/feasibility').json()['state'] == 'ready'
    accepted = build.client.post(f'/api/builds/{build.bid}/blueprint/accept')
    assert accepted.status_code == 202, accepted.text
    wait(build.app)
    trace, recorded = spans(build.app, accepted.json()['run_id'])
    assert (trace['status'], trace['error']) == ('error', 'invalid_request')
    from dss.spec import requirements as req
    failed = {e['path'].removeprefix('requirements.') for e in next(s for s in recorded if s['node'] == 'publish')['coverage_errors']}
    items = {r.id: r.source.item_id for r in req.load(build.folder).requirements if r.source.kind == 'image'}
    assert {items[rid] for rid in failed if rid in items} == GAP_FIXES[case].keys()


def test_recreate_planner_that_follows_the_observations_is_ready_on_first_draft(blueprint_api, monkeypatch):
    """The blueprint context carries the observations; a planner that drafts its rows from that section
    (a month bucket for the observed grain, the observed type on the row of its metric and dimension)
    needs no repair or decision, and accept publishes."""
    from types import SimpleNamespace
    from test_blueprint import confirm
    from test_context_node import ContextLLM
    build = gap_build(blueprint_api, monkeypatch, 'table')
    base = build.value

    class Planner(ContextLLM):
        async def generate_content_async(self, llm_request, stream=False):
            text = str(llm_request.config.system_instruction)
            observed = json.loads(text.split('Recreate observations:', 1)[1].split('\n', 1)[1].split('\n\n', 1)[0])
            draft = copy.deepcopy(base)
            for o in observed:
                metrics = [{'field': m['field'], 'agg': m['aggregation']} for m in o.get('metrics', [])]
                rows = [r['component'] for r in draft['rows'] if all(m in r['component']['metrics'] for m in metrics)
                        and set(o.get('dimensions', [])) <= set(r['component']['dimensions'])]
                grain = next((m['date_grain'] for m in o.get('metrics', []) if m.get('date_grain')), None)
                if grain:
                    name = f"{o['date_field']}_{grain}"
                    draft['derived_fields'].append({'name': name, 'expression': f"DATE_TRUNC({o['date_field']}, {grain.upper()})",
                                                    'type': 'date', 'description': f"{grain} of {o['date_field']}"})
                    for c in (c for c in rows if c['type'] == o['type']):
                        c.update(date_dimension=name, sort={'field': name, 'order': 'asc'})
                elif rows and not any(c['type'] == o['type'] for c in rows):
                    rows[0].update(type=o['type'], options={})
            self.replies = [json.dumps(draft)]
            async for response in super().generate_content_async(llm_request, stream):
                yield response
    planner = Planner(replies=[], seen=[])
    monkeypatch.setattr(build.app.state.models, 'llm_for', lambda action: planner)
    bq = blueprint_api[5]
    bq.dry_run = lambda sql: bq.sql.append(sql) or [SimpleNamespace(name='order_date_month', field_type='DATE', mode='NULLABLE')]
    confirm(build.client, build.app, build.bid)
    section = str(planner.seen[0].config.system_instruction).split('Recreate observations:', 1)[1].split('\n\n', 1)[0]
    assert '"title":"Top products by revenue (USD)"' in section and 'box' not in section and 'confidence' not in section
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert planner.calls == 1 and assessment['state'] == 'ready', [i['reason'] for i in assessment['issues'] if i['resolution'] == 'unresolved']
    accept(build)
    assert_bound(build, lambda mapping: ['kpi:total_revenue'], build.data['dropped'])


def test_recreate_gap_check_goes_stale_when_the_reference_is_removed(blueprint_api, monkeypatch):
    """A reference removed after drafting marks the Blueprint check stale (existing freshness rules), never ready."""
    from test_blueprint import choose, confirm
    build = gap_build(blueprint_api, monkeypatch, 'monthly')
    confirm(build.client, build.app, build.bid)
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert choose(build.client, build.bid, assessment, gap_issues(assessment, build)['o5'], 'date_bucket').status_code == 200
    assert build.client.get(f'/api/builds/{build.bid}/feasibility').json()['state'] == 'ready'
    assert build.client.delete(f'/api/builds/{build.bid}/reference-images').status_code == 204
    assert build.client.get(f'/api/builds/{build.bid}/feasibility').json()['state'] == 'stale'
    refused = build.client.post(f'/api/builds/{build.bid}/blueprint/accept')
    assert refused.status_code == 409 and refused.json()['error']['code'] == 'feasibility_blocked', refused.text


def test_recreate_gap_drop_is_an_explicit_recorded_choice(blueprint_api, monkeypatch):
    """Code never drops an observation; a user's drop is recorded with its provenance and keeps the rows."""
    from test_blueprint import choose, confirm
    build = gap_build(blueprint_api, monkeypatch, 'table')
    confirm(build.client, build.app, build.bid)
    before = build.client.get(f'/api/builds/{build.bid}/blueprint').json()['rows']
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    issue = gap_issues(assessment, build)['o7']
    assert choose(build.client, build.bid, assessment, issue).status_code == 200
    from dss.spec import requirements as req
    ledger = req.load(build.folder)
    table = next(r for r in ledger.requirements if r.source.item_id == 'o7')
    drop = next(d for d in ledger.decisions if d['requirement_id'] == table.id)
    assert (drop['action'], drop['issue_id'], drop['source_id']) == ('drop', issue['id'], table.source.id)
    # Dropping the observation waives none of its nearest row's question checks.
    assert [d['effect']['drop_questions'] for d in ledger.blueprint_decisions if d['issue']['id'] == issue['id']] == [[]]
    after = build.client.get(f'/api/builds/{build.bid}/blueprint').json()['rows']
    assert [r['component'] for r in after] == [r['component'] for r in before]
    current = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert {i['id']: i['resolution'] for i in current['issues']}[issue['id']] == 'dropped'
    assert 'o7' not in gap_issues(current, build) and 'o5' in gap_issues(current, build)


ELECTRICITY = json.loads((Path(__file__).parent / 'data/recreate_electricity.json').read_text(encoding='utf-8'))
YEAR_RUNS = json.loads((Path(__file__).parent / 'data/recreate_year_buckets.json').read_text(encoding='utf-8'))


def saved_year_build(blueprint_api, monkeypatch, case, data=None):
    """Install the sanitized saved artifacts/profiles/ledger, without pretending replies were captured
    (`data`: another saved-run fixture case of the same shape)."""
    from types import SimpleNamespace
    from dss.artifacts.models import Context, Outline, Design
    from dss.spec import requirements as req
    from dss.spec.models import TYPES
    from test_blueprint import artifact
    from test_references import png
    monkeypatch.setenv('DSS_ALLOWED_TYPES', ','.join(TYPES))
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    data = copy.deepcopy(YEAR_RUNS['cases'][case] if data is None else data)
    old_id = data['sources'][0]['id']
    data = json.loads(json.dumps(data).replace(old_id, sid))
    source = data['sources'][0]
    # Empty display-only samples satisfy the source API; no original rows leak
    # into this aggregate fixture or any planner request.
    for column in source['columns']:
        column['sample'] = []
    with app.state.db.connect() as conn:
        conn.execute('UPDATE sources SET columns_json=?, bq_table=?, kind=? WHERE id=?',
                     (json.dumps(source['columns']), source['bq_table'], 'synthetic', sid))
    artifact(folder, Context.model_validate(data['context']))
    artifact(folder, Outline.model_validate(data['outline']))
    artifact(folder, Design.model_validate(data['design']))
    ledger = req.Ledger.model_validate(data['requirements'])
    image = next(r.source for r in ledger.requirements if r.source.kind == 'image')
    ref = {'id': image.reference_id, 'mode': 'recreate', 'instructions': data['instructions'], 'summary': 'Saved reference',
           'images': [{'id': image.image_id, 'name': 'reference.png', 'file': 'reference_img_000000000000.png',
                       'mime_type': 'image/png', 'width': 1200, 'height': 900}],
           'interpretation': {'mode': 'recreate', 'items': data['items'], 'aspect_ratio': 1.3333}}
    (folder / 'references.json').write_text(json.dumps(ref), encoding='utf-8')
    (folder / 'reference_img_000000000000.png').write_bytes(png())
    # Identity pseudonymization invalidates the old hashes. Rebind extracted
    # evidence to these current inputs, recheck it in code, and replay ONLY the
    # recorded approved drop through the real decision gate.
    snapshot = req.inputs(app.state.db, bid, folder)
    ledger.processed_sources = {s['id']: req.digest(s) for s in snapshot['incoming']}
    ledger.decisions = []
    ledger = req.merge(ledger, snapshot, req.Extraction(requirements=[]))
    from dss.spec.capabilities import Checker, load_registry
    checker = Checker(load_registry())
    assessment = req.evaluate(snapshot, ledger, checker, check_components=False)
    owners = {r.text: r.source.item_id for r in ledger.requirements}
    pending = [i for i in assessment.issues if i.resolution == 'unresolved']
    assert {owners.get(i.requirement) for i in pending} == set(data['dropped']), [i.reason for i in pending]
    req.save(folder, ledger, assessment)
    response = client.post(f'/api/builds/{bid}/feasibility/decisions', json={
        'assessment_id': assessment.id, 'decisions': [dict(issue_id=i.id, action='drop', alternative_id=None) for i in pending]})
    assert response.status_code == 200, response.text
    llm.replies = [json.dumps(data['draft']), json.dumps(data['repair']), json.dumps(data['view_reply'])]
    # A strict fake SQL boundary: invalid DATE arithmetic must never get here.
    def dry_run(sql):
        import re
        assert not re.search(r'INTERVAL\s+0\s+DAY|DATE_TRUNC\s*\([^)]*\)\s*\*\s*1', sql, re.I), sql
        bq.sql.append(sql)
        return [SimpleNamespace(name=f['name'], field_type={'number': 'FLOAT', 'date': 'DATE',
            'datetime': 'TIMESTAMP'}.get(f['type'], 'STRING'), mode='NULLABLE') for f in data['draft']['derived_fields']]
    bq.dry_run = dry_run
    bq.created, bq.deleted = [], []
    bq.create_view = lambda table, sql: bq.created.append(table)
    bq.delete_view = lambda table: bq.deleted.append(table) or True
    bq.aggregate = lambda sql: [{'year': '2011-01-01', 'region': 'Asia', 'country': 'Philippines', 'm0': 10, 'm1': 5}]
    monkeypatch.setattr(background, 'capture', lambda html, path, width, height, scale=None: path.write_bytes(b'PNG'))
    monkeypatch.setattr(app.state.settings, 'defaults', app.state.settings.defaults.model_copy(update={'designed_pages': False}))
    return SimpleNamespace(client=client, app=app, bid=bid, folder=folder, llm=llm, bq=bq, data=data)


@pytest.mark.parametrize('case', list(YEAR_RUNS['cases']))
def test_saved_year_runs_ready_publish_grain_recipe_and_fake_engine(blueprint_api, monkeypatch, case):
    from test_blueprint import confirm
    from dss.spec import requirements as req
    build = saved_year_build(blueprint_api, monkeypatch, case)
    confirm(build.client, build.app, build.bid)
    bp = build.client.get(f'/api/builds/{build.bid}/blueprint').json()
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert assessment['state'] == 'ready', [i['reason'] for i in assessment['issues'] if i['resolution'] == 'unresolved']
    assert len(build.bq.sql) == 1 and build.llm.calls <= 2
    assert not {'year_trunc', 'year_grain', 'year_year'} & {f['name'] for f in bp['derived_fields']}
    if case.endswith('34512aef'):
        assert build.llm.calls == 2
        repair = str(build.llm.seen[1].config.system_instruction)
        assert all(s in repair for s in ('q4', 'AVG(urban_rural_gap)', 'AVG(urban_pct)', 'AVG(rural_pct)', 'Missing:'))
    accept(build)
    spec = DashboardSpec.model_validate_json((build.folder / 'spec.json').read_text(encoding='utf-8'))
    assert next(f for f in spec.datasource.fields if f.name == 'year').date_granularity == 'year'
    components = {c.id: c for p in spec.pages for c in p.components}
    ledger = req.load(build.folder)
    dropped = {d['requirement_id'] for d in ledger.decisions if d['action'] == 'drop'}
    assert {r.source.item_id for r in ledger.requirements if r.id in dropped} == set(build.data['dropped'])
    for r in ledger.requirements:
        if r.source.kind == 'image' and r.id not in dropped:
            ids = [e['fulfilled_by'] for e in ledger.verification[r.id] if 'fulfilled_by' in e]
            assert ids and ids[0] and set(ids[0]) <= components.keys(), (r.source.item_id, ledger.verification[r.id])
    executes(build.client, build.app, build.bid, monkeypatch)
    recipe = [json.loads(line) for line in (build.folder / 'recipe.jsonl').read_text(encoding='utf-8').splitlines()]
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).parents[2] / 'contracts/recipe.schema.json').read_text(encoding='utf-8'))
    for op in recipe[1:]:
        Draft202012Validator({'$ref': '#/$defs/op', '$defs': schema['$defs']}).validate(op)
        if op['op'] == 'add_chart' and op['chart_type'] in ('time_series', 'area'):
            assert op['date_dimension'] == 'year' and op['options']['date_granularity'] == 'year'


@pytest.mark.parametrize('change', ['omit', 'wrong_agg', 'omit_urban', 'omit_rural'])
def test_saved_q4_unfaithful_single_repair_stays_blocked(blueprint_api, monkeypatch, change):
    from test_blueprint import confirm
    case = next(k for k in YEAR_RUNS['cases'] if k.endswith('34512aef'))
    build = saved_year_build(blueprint_api, monkeypatch, case)
    repair = copy.deepcopy(build.data['repair'])
    field = {'omit': 'urban_rural_gap', 'wrong_agg': 'urban_rural_gap', 'omit_urban': 'urban_pct', 'omit_rural': 'rural_pct'}[change]
    for row in repair['rows']:
        if row['question_id'] == 'q4':
            if change == 'wrong_agg':
                for metric in row['component']['metrics']:
                    if metric['field'] == field:
                        metric['agg'] = 'sum'
            else:
                row['component']['metrics'] = [m for m in row['component']['metrics'] if m['field'] != field]
    build.llm.replies[1] = json.dumps(repair)
    confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 2
    a = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert a['state'] == 'blocked' and any(i['requirement'] == 'q4' and field in i['reason'] for i in a['issues'])
    response = build.client.post(f'/api/builds/{build.bid}/blueprint/accept')
    assert response.status_code == 409 and response.json()['error']['code'] == 'feasibility_blocked'
    assert build.bq.created == []


@pytest.mark.parametrize('case', list(YEAR_RUNS['cases']))
def test_saved_year_sql_repair_recomputes_binding(blueprint_api, monkeypatch, case):
    from test_blueprint import confirm
    build = saved_year_build(blueprint_api, monkeypatch, case)
    original = build.bq.dry_run
    attempts = []

    def retry(sql):
        # Assert even the failing initial dry run never receives DATE arithmetic.
        schema = original(sql)
        attempts.append(sql)
        if len(attempts) == 1:
            raise ValueError('Transient fake SQL validation error')
        return schema

    build.bq.dry_run = retry
    # A row repair is not necessarily needed for the first fixture. Route this
    # reconstructed reply by the request rather than its ordinal position.
    previous = build.llm.generate_content_async

    async def route(request, stream=False):
        if 'ViewDraft' in str(request.config.response_json_schema):
            build.llm.replies[build.llm.calls] = json.dumps(build.data['view_reply'])
        async for response in previous(request, stream):
            yield response

    monkeypatch.setattr(type(build.llm), 'generate_content_async', lambda self, request, stream=False: route(request, stream))
    confirm(build.client, build.app, build.bid)
    a = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert a['state'] == 'ready', [i['reason'] for i in a['issues'] if i['resolution'] == 'unresolved']
    assert len(attempts) == 2 and build.llm.calls <= 3
    assert not {'year_trunc', 'year_grain', 'year_year'} & {
        f['name'] for f in build.client.get(f'/api/builds/{build.bid}/blueprint').json()['derived_fields']}


@pytest.mark.parametrize('case', list(YEAR_RUNS['cases']))
def test_saved_year_proof_removal_blocks_accept_reload_and_redraft(blueprint_api, monkeypatch, case):
    from test_blueprint import confirm
    from test_context_node import wait
    build = saved_year_build(blueprint_api, monkeypatch, case)
    confirm(build.client, build.app, build.bid)
    assert reloaded(build.app, build.bid)[0]['state'] == 'ready'
    with build.app.state.db.connect() as conn:
        row = conn.execute('SELECT id,columns_json FROM sources WHERE build_id=?', (build.bid,)).fetchone()
        columns = json.loads(row['columns_json'])
        for column in columns:
            column.pop('bucket_start', None)
        conn.execute('UPDATE sources SET columns_json=? WHERE id=?', (json.dumps(columns), row['id']))
    refused = build.client.post(f'/api/builds/{build.bid}/blueprint/accept')
    assert refused.status_code == 409 and refused.json()['error']['code'] == 'feasibility_blocked'
    assert build.bq.created == [] and reloaded(build.app, build.bid)[0]['state'] == 'blocked'
    # Reintroduce the reconstructed draft on an explicit redraft: the old alias
    # cannot be revived from any earlier canonicalization authorization.
    build.llm.replies = [json.dumps(build.data[k]) for k in ('draft', 'repair', 'view_reply')]
    build.llm.calls = 0
    result = build.client.post(f'/api/builds/{build.bid}/blueprint/regenerate')
    assert result.status_code == 202, result.text
    wait(build.app)
    a = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert a['state'] == 'blocked' and build.llm.calls <= 3
    refused = build.client.post(f'/api/builds/{build.bid}/blueprint/accept')
    assert refused.status_code == 409 and refused.json()['error']['code'] == 'feasibility_blocked'
    assert build.bq.created == []
PLACEMENT = json.loads((Path(__file__).parent / 'data/recreate_page_placement.json').read_text(encoding='utf-8'))
# The per-country urban/rural observations: the run extracted three; the reconstructed variant adds Belize.
COUNTRIES = {'recorded': ['o6', 'o7', 'o8'], 'four_countries': ['o6', 'o7', 'o8', 'o9']}
ACCESS_TITLE = 'have access to electricity worldwide (%)'
QUESTIONS_HEADER = 'Only these selected questions need rows (untrusted):\n'
REPAIR_HEADER = 'Repair only the named errors; return structured JSON, never SQL DDL:\n'


def placement_build(blueprint_api, monkeypatch, variant='recorded', repair='repair'):
    """Run 20261026-045323's saved inputs (task 24.10 block), the approved geo_map drop replayed. The
    planner's draft is the persisted Blueprint: the urban/rural area on page 3, a country table on page 1."""
    data = copy.deepcopy(PLACEMENT['case'])
    if variant == 'four_countries':
        data['items'].append(data['four_countries']['item'])
        data['requirements']['requirements'].append(data['four_countries']['requirement'])
    build = saved_year_build(blueprint_api, monkeypatch, None, data=data)
    build.llm.replies = [json.dumps(build.data[key]) for key in ('draft', repair, 'view_reply')]
    return build


def section_value(text, header):
    return json.JSONDecoder().raw_decode(text.split(header, 1)[1])[0]


def placement_snapshot(build, rows):
    """The Blueprint check's inputs for these rows, as the blueprint node drafts them."""
    from dss.artifacts import design as design_node
    from dss.artifacts.models import Blueprint
    from dss.harness.nodes import context as context_node, outline as outline_node
    from dss.spec import requirements as req
    snapshot = req.inputs(build.app.state.db, build.bid, build.folder)
    view = {k: build.data['draft'][k] for k in ('view_sources', 'derived_fields')}
    snapshot.update(blueprint=Blueprint(revision=1, **view, rows=rows, view_table=None, assessment_id=None).model_dump(),
                    context=context_node.load(build.folder).model_dump(), outline=outline_node.load(build.folder).model_dump(),
                    design=design_node.load(build.folder).model_dump(), blueprint_errors=[])
    return snapshot


def later_rows(rows):
    return [(r['page'], r['question_id'], r['component']) for r in rows if r['page'] > 1]


def bound_components(build):
    """{observation item id: the published component ids publish coverage bound it to}."""
    from dss.spec import requirements as req
    ledger = req.load(build.folder)
    return {r.source.item_id: next(e['fulfilled_by'] for e in ledger.verification[r.id] if 'fulfilled_by' in e)
            for r in ledger.requirements if r.source.kind == 'image' and r.source.item_id not in build.data['dropped']}


@pytest.mark.parametrize('variant', list(COUNTRIES))
def test_saved_page_placement_completes_the_urban_rural_area_on_page_one(blueprint_api, monkeypatch, variant):
    """Task 24.10 block (run 20261026-045323-8f75b9ce): coverage proved a binding on any page, so the per-country
    observations bound to a page-3 area while page 1 kept a country table, and the access scorecard read
    "in 2011" although AVG(access_pct) spans every year, with no `%`. Now they count only on page 1: the sole
    row repair targets page 1's questions, and when the planner leaves the area out, code adds it there."""
    from test_blueprint import confirm
    from dss.spec import requirements as req
    build = placement_build(blueprint_api, monkeypatch, variant)
    draft = build.data['draft']['rows']
    confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 2  # the draft and the sole row repair; code adds the rest
    repair = str(build.llm.seen[1].config.system_instruction)
    assert sorted(q['id'] for q in section_value(repair, QUESTIONS_HEADER)) == ['q1', 'q2', 'q3']
    sent = section_value(repair, REPAIR_HEADER)
    owners = {r.id: r.source.item_id for r in req.load(build.folder).requirements}
    errors = [e for e in sent['errors'] if e['code'] == 'observation']
    assert sorted(owners[e['requirement_id']] for e in errors) == COUNTRIES[variant], [e['message'] for e in errors]
    for e in errors:
        assert e['repairable'] and e['indices'] == [] and e['repair_qids'] == ['q1', 'q2', 'q3']
        assert all(s in e['message'] for s in ('page 1', 'a area of AVG(urban_pct) and AVG(rural_pct) by year of year')), e
        assert 'Urban vs. Rural Electricity Access Over Time' not in e['message']  # never the off-page row's gap
    # The repair shows the page-1 question rows it replaces.
    assert sorted({r['question_id'] for r in sent['rows']}) == ['q1', 'q2', 'q3']
    blueprint = build.client.get(f'/api/builds/{build.bid}/blueprint').json()
    added = [r for r in blueprint['rows'] if r['note'].startswith('observation ')]
    assert [(r['page'], r['component']['type'], r['component']['date_dimension'], [m['field'] for m in r['component']['metrics']])
            for r in added] == [(1, 'area', 'year', ['urban_pct', 'rural_pct'])]
    # Code moved, deleted and retyped nothing: the page-2 and page-3 rows are the planner's own.
    assert later_rows(blueprint['rows']) == later_rows(draft)
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert assessment['state'] == 'ready', [i['reason'] for i in assessment['issues'] if i['resolution'] == 'unresolved']
    accept(build)
    spec = DashboardSpec.model_validate_json((build.folder / 'spec.json').read_text(encoding='utf-8'))
    pages = {c.id: p.index for p in spec.pages for c in p.components}
    components = {c.id: c for p in spec.pages for c in p.components}
    bound = bound_components(build)
    assert all(pages[cid] == 1 for ids in bound.values() for cid in ids), bound
    [area] = {cid for item in COUNTRIES[variant] for cid in bound[item]}
    assert components[area].type == 'area' and [m.field for m in components[area].metrics] == ['urban_pct', 'rural_pct']
    # The page-3 urban/rural area and the Fiji area remain as additional analysis.
    page3 = [(c.type, c.label) for c in spec.pages[2].components]
    assert sorted(page3) == sorted((r['component']['type'], r['component']['label']) for r in draft if r['page'] == 3)
    assert components[bound['o3'][0]].label == ACCESS_TITLE
    # No other planner title is rewritten.
    observed = {cid for ids in bound.values() for cid in ids}
    planner = {r['component']['label'] for r in draft}
    assert all(c.label in planner for cid, c in components.items() if cid not in observed)
    executes(build.client, build.app, build.bid, monkeypatch)
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).parents[2] / 'contracts/recipe.schema.json').read_text(encoding='utf-8'))
    recipe = [json.loads(line) for line in (build.folder / 'recipe.jsonl').read_text(encoding='utf-8').splitlines()]
    for op in recipe[1:]:
        Draft202012Validator({'$ref': '#/$defs/op', '$defs': schema['$defs']}).validate(op)
    assert {op['title'] for op in recipe[1:] if op['op'] == 'add_chart' and op['component_id'] == bound['o3'][0]} == {ACCESS_TITLE}


def test_saved_page_placement_compliant_repair_needs_no_completion_row(blueprint_api, monkeypatch):
    from test_blueprint import confirm
    build = placement_build(blueprint_api, monkeypatch, repair='repair_compliant')
    confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 2
    blueprint = build.client.get(f'/api/builds/{build.bid}/blueprint').json()
    assert not [r for r in blueprint['rows'] if r['note'].startswith('observation ')]
    assert [r['component']['type'] for r in blueprint['rows'] if r['question_id'] == 'q3'] == ['table', 'area']
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert assessment['state'] == 'ready', [i['reason'] for i in assessment['issues'] if i['resolution'] == 'unresolved']
    accept(build)
    spec = DashboardSpec.model_validate_json((build.folder / 'spec.json').read_text(encoding='utf-8'))
    components = {c.id: (p.index, c) for p in spec.pages for c in p.components}
    [area] = {cid for item in COUNTRIES['recorded'] for cid in bound_components(build)[item]}
    assert components[area][0] == 1 and components[area][1].question_ref == 'q3'


def test_saved_page_placement_full_page_one_stays_an_issue(blueprint_api, monkeypatch):
    """With 12 rows on page 1 (two controls, three rows per question and the code-added yearly bar), completion
    has no room for the area: the observations stay Issues and accept is refused. Nothing moves to page 1."""
    from test_blueprint import confirm
    build = placement_build(blueprint_api, monkeypatch)
    draft = build.data['draft']['rows']
    q = {qid: next(r for r in draft if r['question_id'] == qid) for qid in ('q1', 'q2', 'q3')}

    def row(qid, kind, dimensions, field, agg, label):
        value = copy.deepcopy(q[qid])
        value['component'] = {**value['component'], 'type': kind, 'label': label, 'dimensions': dimensions, 'options': {},
                              'metrics': [{'field': field, 'agg': agg}], 'date_dimension': None, 'sort': None, 'breakdown': None}
        return value
    # The planner keeps no yearly bar: completion adds it (the 12th page-1 row) before it reaches the area.
    full = [q['q1'], row('q1', 'table', ['region'], 'access_pct', 'avg', 'Access by region'),
            row('q1', 'bar', ['country'], 'access_pct', 'avg', 'Access by country'),
            q['q2'], row('q2', 'bar', ['region'], 'people_without_access', 'sum', 'Unserved by region'),
            row('q2', 'table', ['country'], 'people_without_access', 'sum', 'Unserved by country'),
            q['q3'], row('q3', 'bar', ['region'], 'access_pct', 'avg', 'Regional access'),
            row('q3', 'table', ['country'], 'access_pct', 'avg', 'Country access')]
    build.llm.replies[1] = json.dumps({'rows': full})
    confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 2
    blueprint = build.client.get(f'/api/builds/{build.bid}/blueprint').json()
    assert sum(r['page'] == 1 for r in blueprint['rows']) == 12
    assert [r['component']['type'] for r in blueprint['rows'] if r['note'].startswith('observation ')] == ['bar']
    assert later_rows(blueprint['rows']) == later_rows(draft)
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    reasons = {i['requirement']: i['reason'] for i in assessment['issues'] if i['resolution'] == 'unresolved'}
    assert assessment['state'] == 'blocked' and len(reasons) == 3 and all('on page 1' in r for r in reasons.values()), reasons
    refused = build.client.post(f'/api/builds/{build.bid}/blueprint/accept')
    assert refused.status_code == 409 and refused.json()['error']['code'] == 'feasibility_blocked'
    assert build.bq.created == []


def test_saved_page_placement_matches_and_offers_only_page_one_rows(blueprint_api, monkeypatch):
    """Matching and code-built offers consider only reference-page rows: a page-1 urban/rural time series is the
    nearest row, never the exactly matching page-3 area; the yearly bar's offer retypes a page-1 table, never
    the page-3 bar of the same metric."""
    from dss.artifacts.models import BlueprintRow
    from dss.spec import requirements as req
    from dss.spec.capabilities import Checker, load_registry
    build = placement_build(blueprint_api, monkeypatch)
    checker, ledger = Checker(load_registry()), req.load(build.folder)
    draft = [BlueprintRow.model_validate(r) for r in build.data['draft']['rows']]
    owners = {r.id: r.source.item_id for r in ledger.requirements}

    def gaps(rows):
        return {owners[e['requirement_id']]: e for e in feasibility.diagnostics(placement_snapshot(build, rows), ledger, checker)
                if e['code'] == 'observation'}
    found = gaps(draft)
    assert sorted(found) == COUNTRIES['recorded']
    area = next(i for i, r in enumerate(draft) if r.page == 3 and r.component.type == 'area' and r.question_id == 'q7')
    assert all(area not in e['indices'] and not e['offers'] for e in found.values())
    trend = draft[area].model_copy(deep=True)
    trend.question_id, trend.section_id, trend.page = 'q3', 's1', 1
    trend.component = trend.component.model_copy(update={'type': 'time_series', 'options': {'date_granularity': 'year'}})
    rows = [*draft, trend]
    found = gaps(rows)
    assert sorted(found) == COUNTRIES['recorded']
    for e in found.values():
        assert e['indices'] == [len(draft)] and e['qids'] == ['q3'] and 'on page 1' in e['message']
        assert "row 'Urban vs. Rural Electricity Access Over Time' is a time_series, the observation is a area" in e['message']
    # The yearly bar as a page-1 table by year: its nearest row and offer are there, not the page-3 bar of SUM(people_without_access).
    # (Placed before the q2 scorecard, which ties with it as the nearest page-1 row.)
    bar = next(i for i, r in enumerate(draft) if r.page == 1 and r.component.type == 'bar')
    scorecard = next(i for i, r in enumerate(draft) if r.question_id == 'q2' and r.component.type == 'scorecard')
    table = draft[bar].model_copy(deep=True)
    table.component = table.component.model_copy(update={'type': 'table'})
    rows = list(draft)
    rows[scorecard], rows[bar] = table, draft[scorecard]
    e = gaps(rows)['o5']
    assert e['indices'] == [scorecard] and 'on page 1' in e['message']
    assert e['offers'] and all([r['index'] for r in o['replace']] == [scorecard] for o in e['offers'])
    offer = next(o for o in e['offers'] if o['id'] == 'observed_type')
    rows[scorecard] = BlueprintRow.model_validate(offer['replace'][0]['row'])
    assert rows[scorecard].page == 1 and rows[scorecard].component.type == 'bar' and 'o5' not in gaps(rows)


INPUTS = Path(__file__).parents[1] / ELECTRICITY['provenance']['run'] / 'build'


def electricity_build(blueprint_api, monkeypatch):
    """The 24.7 fixture build after the user's approved drops (the geo map, the legend control), whose
    planner answers the draft and the one row repair with the release build's own rows."""
    from types import SimpleNamespace
    from dss.spec.models import TYPES
    # The recipe 1.3 catalog (area, fixed_size_list), whatever the root .env narrows it to.
    monkeypatch.setenv('DSS_ALLOWED_TYPES', ','.join(TYPES))
    build = recreate_build(blueprint_api, monkeypatch, data=ELECTRICITY, synthetic=True, designed=False)
    bq = blueprint_api[5]
    bq.dry_run = lambda sql: bq.sql.append(sql) or [SimpleNamespace(name='year_year', field_type='DATE', mode='NULLABLE')]
    build.rid = upload_recreate(build, ELECTRICITY['instructions'])
    assessment = feasibility_check(build.client, build.app, build.bid)
    from dss.spec import requirements as req
    owners = {r.text: r.source.item_id for r in req.load(build.folder).requirements}
    pending = [i for i in assessment['issues'] if i['resolution'] == 'unresolved']
    # Selected by observation and status, never "first alternative".
    assert {(owners.get(i['requirement']), i['status']) for i in pending} == {('o5', 'needs_data'), ('o7', 'needs_clarification')}, pending
    dropped = build.client.post(f'/api/builds/{build.bid}/feasibility/decisions', json={'assessment_id': assessment['id'],
        'decisions': [{'issue_id': i['id'], 'action': 'drop', 'alternative_id': None} for i in pending]})
    assert dropped.status_code == 200, dropped.text
    assert build.client.get(f'/api/builds/{build.bid}/feasibility').json()['state'] == 'ready'
    build.llm.replies = [json.dumps(build.value), json.dumps({'rows': [r for r in build.value['rows'] if r['question_id']]})]
    return build


def test_electricity_fixture_inputs_are_the_recorded_read_only_copies():
    import ast
    import hashlib
    # The fixture's instructions are the live test's, read without importing the live module.
    tree = ast.parse((Path(__file__).parent / 'live/test_reference_design.py').read_text(encoding='utf-8'))
    [value] = [node.value for node in tree.body if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', None) == 'INSTRUCTIONS']
    assert ELECTRICITY['instructions'] == ast.literal_eval(value)
    if not INPUTS.is_dir():
        pytest.skip('the run evidence (.blueprint/, git-ignored) is local to the machine that recorded it')
    for name, digest in ELECTRICITY['provenance']['sha256'].items():
        assert hashlib.sha256((INPUTS / name).read_bytes()).hexdigest() == digest, name


def test_electricity_recreate_reaches_ready_and_publishes_every_observation(blueprint_api, monkeypatch):
    """24.7 block (run 20261025-104805-795461ae): definition-only instructions were 12 `unknown` rows, the
    region selector had no explicit field, the scorecard was asked for a year grain and no row showed
    the yearly bar. After only the approved drops the Blueprint is ready, with code-added rows."""
    from test_blueprint import confirm
    from dss.spec import requirements as req
    build = electricity_build(blueprint_api, monkeypatch)
    assert not [r for r in req.load(build.folder).requirements if r.source.kind == 'reference']
    run_id = confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 2  # the draft and the one row repair; code adds the rest
    blueprint = build.client.get(f'/api/builds/{build.bid}/blueprint').json()
    added = [r for r in blueprint['rows'] if r['note'].startswith('observation ')]
    # 24.10: the planner's region list is on page 2, so code adds the observed one on page 1 too.
    assert {(r['question_id'], r['page'], r['component']['type']) for r in added} == {
        (None, 1, 'bar'), (None, 1, 'area'), (None, 1, 'fixed_size_list')}
    notes = {r['component']['type']: r['note'].rsplit(':', 1)[1] for r in added}
    # One area row for the four per-country observations (the first of them in ledger order adds it).
    assert notes['bar'] == 'o6' and notes['area'] in ('o8', 'o9', 'o10', 'o11') and notes['fixed_size_list'] == 'o2'
    assert len(added) == 3
    assert not {'year_year', 'year_trunc', 'year_grain'} & {f['name'] for f in blueprint['derived_fields']}
    assert all('DATE_TRUNC' not in sql and 'AS `year`' in sql for sql in blueprint_api[5].sql)
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert assessment['state'] == 'ready', [i['reason'] for i in assessment['issues'] if i['resolution'] == 'unresolved']
    trace, recorded = spans(build.app, run_id)
    assert [s.get('observation_rows') for s in recorded if s['node'] == 'validate_blueprint_rows'][-1] == [r['note'] for r in added]
    with build.app.state.db.connect() as conn:
        check = json.loads(conn.execute("SELECT spans_json FROM traces WHERE node='capability_check' ORDER BY started_at").fetchall()[0][0])
    assert next(s for s in check if s['node'] == 'assess_capabilities')['unused_definitions'] == ['Region', 'Country', 'Urban', 'Rural']
    accept(build)
    spec = DashboardSpec.model_validate_json((build.folder / 'spec.json').read_text(encoding='utf-8'))
    components = {c.id: c for p in spec.pages for c in p.components}
    ledger = req.load(build.folder)
    bound = {r.source.item_id: next(e['fulfilled_by'] for e in ledger.verification[r.id] if 'fulfilled_by' in e)
             for r in ledger.requirements if r.source.kind == 'image' and r.source.item_id not in ELECTRICITY['dropped']}
    kinds = {item: {(components[c].type, components[c].field) for c in ids} for item, ids in bound.items()}
    assert kinds['o2'] == {('fixed_size_list', 'region')} and kinds['o3'] == {('scorecard', None)}
    assert kinds['o6'] == {('bar', None)} and components[bound['o6'][0]].dimensions == ['year']
    assert components[bound['o6'][0]].id.startswith('p1_') and components[bound['o6'][0]].label == 'People without access to electricity'
    [area] = {c for item in ('o8', 'o9', 'o10', 'o11') for c in bound[item]}
    assert components[area].type == 'area' and [m.field for m in components[area].metrics] == ['urban_pct', 'rural_pct']
    # Code dropped nothing: only the user's two decisions.
    assert {r.source.item_id for r in ledger.requirements if r.id in {d['requirement_id'] for d in ledger.decisions if d['action'] == 'drop'}} == {'o5', 'o7'}
    fresh = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert fresh['state'] == 'ready' and not fresh['prototype_stale'], fresh
    executes(build.client, build.app, build.bid, monkeypatch)


def test_electricity_sql_repair_that_fulfils_the_observation_drops_the_code_added_row(blueprint_api, monkeypatch):
    """Live run 20261025-124408: the planner's own yearly bar used a bucket the view gained only in the one
    SQL repair, so the code-added bar became surplus after the assessment and the check read `stale`."""
    from types import SimpleNamespace
    from test_blueprint import confirm
    build = electricity_build(blueprint_api, monkeypatch)
    bucket = {'name': 'year_grain', 'expression': 'DATE_TRUNC(year, YEAR)', 'type': 'date', 'description': 'Year'}
    bar = {'question_id': 'q2', 'section_id': 's1', 'page': 1, 'note': '', 'status': 'ok', 'issue_ids': [], 'component': {
        'type': 'bar', 'label': 'People without access to electricity', 'dimensions': ['year_grain'], 'date_dimension': None,
        'metrics': [{'field': 'people_without_access', 'agg': 'sum'}], 'breakdown': None, 'sort': None, 'options': {}}}
    draft = {**build.value, 'rows': [*build.value['rows'], bar]}
    build.llm.replies = [json.dumps(draft), json.dumps({'rows': [r for r in draft['rows'] if r['question_id']]}),
                         json.dumps({'view_sources': draft['view_sources'], 'derived_fields': [*draft['derived_fields'], bucket,
                                     {'name': 'year_year', 'expression': 'DATE_TRUNC(year, YEAR)', 'type': 'date', 'description': 'Year of year'}]})]
    bq, attempts = blueprint_api[5], []
    def dry_run(sql):
        attempts.append(sql)
        if len(attempts) == 1:
            raise ValueError('Unrecognized name: year_grain')
        return [SimpleNamespace(name=n, field_type='DATE', mode='NULLABLE') for n in ('year_grain', 'year_year')]
    bq.dry_run = dry_run
    confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 3 and len(attempts) == 2  # draft, row repair, the one SQL repair
    rows = build.client.get(f'/api/builds/{build.bid}/blueprint').json()['rows']
    # The bar is the planner's; the page-1 region list is code-added (24.10: the planner's is on page 2).
    assert [r['component']['type'] for r in rows if r['note'].startswith('observation ')] == ['area', 'fixed_size_list']
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert assessment['state'] == 'ready', (assessment['state'], [i['reason'] for i in assessment['issues']])


def test_electricity_completion_reruns_on_the_sql_repaired_view(blueprint_api, monkeypatch):
    """Live 24.8 run 20261025-214425: the draft's view sources were invalid, so completion after the row
    repair could build no fields and added nothing; the one SQL repair fixed the view but the per-country
    area observations stayed Issues. Completion runs again on the repaired view."""
    from test_blueprint import confirm
    build = electricity_build(blueprint_api, monkeypatch)
    draft = {**build.value, 'view_sources': {'base': 's_unknown', 'joins': [], 'union': []}}
    build.llm.replies = [json.dumps(draft), json.dumps({'rows': [r for r in draft['rows'] if r['question_id']]}),
                         json.dumps({k: build.value[k] for k in ('view_sources', 'derived_fields')})]
    run_id = confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 3  # draft, row repair, the one SQL repair
    blueprint = build.client.get(f'/api/builds/{build.bid}/blueprint').json()
    added = [r for r in blueprint['rows'] if r['note'].startswith('observation ')]
    # The row repair on the invalid view also dropped the question-less region list: code adds it too.
    assert {'area', 'bar'} <= {r['component']['type'] for r in added}, blueprint['rows']
    assert all('DATE_TRUNC' not in sql and 'AS `year`' in sql for sql in blueprint_api[5].sql)
    assert not {'year_year', 'year_trunc', 'year_grain'} & {f['name'] for f in blueprint['derived_fields']}
    _, recorded = spans(build.app, run_id)
    assert [s.get('observation_rows') for s in recorded if s['node'] == 'validate_blueprint_view'][-1] == [r['note'] for r in added]
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert assessment['state'] == 'ready', [i['reason'] for i in assessment['issues'] if i['resolution'] == 'unresolved']


def test_electricity_removed_instructions_remove_the_code_added_rows(blueprint_api, monkeypatch):
    from test_blueprint import confirm
    build = electricity_build(blueprint_api, monkeypatch)
    confirm(build.client, build.app, build.bid)
    rows = build.client.get(f'/api/builds/{build.bid}/blueprint').json()['rows']
    assert len([r for r in rows if r['note'].startswith('observation ')]) == 3  # 24.10: with the page-1 region list
    upload_recreate(build)
    blocked = feasibility_check(build.client, build.app, build.bid)
    assert blocked['state'] == 'blocked' and any('Define ' in i['reason'] for i in blocked['issues'])
    # A design reconfirmation keeps every unchanged row and recomputes the code-added ones: none is needed now.
    with build.app.state.db.connect() as conn:
        conn.execute('UPDATE builds SET stage=? WHERE id=?', ('design', build.bid))
    confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 2
    after = build.client.get(f'/api/builds/{build.bid}/blueprint').json()['rows']
    assert [r for r in after if r['note'].startswith('observation ')] == []
    assert [r['component'] for r in after] == [r['component'] for r in rows if not r['note'].startswith('observation ')]


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


def recipe_13_spec(*, area_options=None, bucket=None):
    """24.1 (release 2.6's stand-ins): a 100% stacked area of urban/rural over sale_date, a 100%
    stacked rural/urban split bar by region and a region fixed-size list. `bucket` puts the area on
    a code-built `sale_<grain>` DATE_TRUNC field."""
    from dss.spec.validate import catalog, validate_spec
    value = json.loads(Path('tests/data/thin_spec.json').read_text(encoding='utf-8'))
    fields = value['datasource']['fields']
    fields += [{'name': 'sale_date', 'type': 'DATE', 'label': 'Sale Date', 'role': 'dimension', 'default_agg': 'none'},
               {'name': 'urban', 'type': 'FLOAT64', 'label': 'Urban', 'role': 'metric', 'default_agg': 'sum'},
               {'name': 'rural', 'type': 'FLOAT64', 'label': 'Rural', 'role': 'metric', 'default_agg': 'sum'}]
    date = 'sale_date'
    if bucket:
        date = f'sale_{bucket}'
        fields.append({'name': date, 'type': 'DATE', 'label': bucket.title(), 'role': 'dimension',
                       'default_agg': 'none', 'date_granularity': bucket})
    metrics = [{'field': 'urban', 'agg': 'sum'}, {'field': 'rural', 'agg': 'sum'}]
    value['pages'][0]['components'] = [
        {'id': 'p1_access_over_time', 'type': 'area', 'label': 'Urban and rural access',
         'grid': {'col': 1, 'row': 6, 'w': 12, 'h': 14}, 'date_dimension': date, 'metrics': metrics,
         'options': {'stacked_percent': True} if area_options is None else area_options},
        {'id': 'p1_split', 'type': 'bar', 'label': 'Rural vs urban split', 'grid': {'col': 1, 'row': 21, 'w': 6, 'h': 14},
         'dimensions': ['region'], 'metrics': metrics[::-1], 'options': {'stacked_percent': True}},
        {'id': 'p1_regions', 'type': 'fixed_size_list', 'label': 'Region', 'grid': {'col': 7, 'row': 21, 'w': 3, 'h': 6},
         'field': 'region'}]
    assert validate_spec(value, allowed=catalog()) == []
    return DashboardSpec.model_validate(value)


AREA_ROWS = [{'sale_date': '2026-01-01', 'm0': 30, 'm1': 10}, {'sale_date': '2026-02-01', 'm0': 1, 'm1': 3},
             {'sale_date': '2026-03-01', 'm0': None, 'm1': 5}, {'sale_date': '2026-04-01', 'm0': 0, 'm1': 0}]
SPLIT_ROWS = [{'region': 'North', 'm0': 600, 'm1': 200}, {'region': 'South', 'm0': 50.5, 'm1': 49.5}]
LIST_ROWS = [{'region': 'East'}, {'region': 'North'}, {'region': None}, {'region': 'South <b>'}]


def test_recipe_13_aggregates_group_on_the_date_axis_and_the_list_field():
    spec = recipe_13_spec()
    area, split, listed = spec.pages[0].components
    assert aggregate_sql(spec, area) == ('SELECT `sale_date`, SUM(`urban`) AS `m0`, SUM(`rural`) AS `m1` FROM '
        '`sample-project.dss_demo.small_sales` GROUP BY `sale_date` ORDER BY `sale_date` ASC LIMIT 50')
    assert aggregate_sql(spec, listed) == ('SELECT `region` FROM `sample-project.dss_demo.small_sales` '
                                           'GROUP BY `region` ORDER BY `region` ASC LIMIT 50')
    assert aggregate_sql(spec, split).endswith('GROUP BY `region` ORDER BY `m0` DESC LIMIT 50')
    area.breakdown = 'region'
    assert 'GROUP BY `sale_date`, `region` ORDER BY `sale_date` ASC' in aggregate_sql(spec, area)


@pytest.mark.parametrize('options, stack, percent', [({}, None, False), ({'stacked': True}, 'total', False),
                                                     ({'stacked_percent': True}, 'total', True),
                                                     ({'stacked': True, 'stacked_percent': True}, 'total', True)])
def test_area_draws_filled_series_stacked_and_normalised_per_date(options, stack, percent):
    spec = recipe_13_spec(area_options=options)
    area = spec.pages[0].components[0]
    option = chart_option(area, AREA_ROWS, spec.theme, 900)
    series = option['series']
    assert option['xAxis']['data'] == ['2026-01-01', '2026-02-01', '2026-03-01', '2026-04-01']
    assert [(s['type'], s['areaStyle'], s.get('stack'), s['name']) for s in series] == [
        ('line', {}, stack, 'urban'), ('line', {}, stack, 'rural')]
    if percent:
        # Each date's parts sum to 100; a missing value stays a gap and an all-zero date stays 0.
        assert [s['data'] for s in series] == [[75.0, 25.0, None, 0], [25.0, 75.0, 100.0, 0]]
        assert option['yAxis']['max'] == 100
    else:
        assert [s['data'] for s in series] == [[30, 1, None, 0], [10, 3, 5, 0]] and 'max' not in option['yAxis']
    # One filled area per breakdown value with one metric.
    area.breakdown, area.metrics = 'region', area.metrics[:1]
    rows = [{'sale_date': '2026-01-01', 'region': r, 'm0': v} for r, v in (('North', 3), ('South', 1))]
    assert [(s['name'], s['data'], s.get('stack')) for s in chart_option(area, rows, spec.theme, 900)['series']] == [
        ('North / urban', [75.0 if percent else 3], stack), ('South / urban', [25.0 if percent else 1], stack)]


def test_hundred_percent_bar_segments_fill_each_bar():
    spec = recipe_13_spec()
    split = spec.pages[0].components[1]
    option = chart_option(split, SPLIT_ROWS, spec.theme, 550)
    series = option['series']
    assert [(s['type'], s['stack'], s['name']) for s in series] == [('bar', 'total', 'rural'), ('bar', 'total', 'urban')]
    for x in range(len(SPLIT_ROWS)):
        assert sum(s['data'][x] for s in series) == pytest.approx(100)
    assert [s['data'][0] for s in series] == [75.0, 25.0] and option['yAxis']['max'] == 100
    # BigQuery NUMERIC (Decimal) counts; a non-numeric value is a gap, never a failed render.
    from decimal import Decimal
    rows = [{'region': 'North', 'm0': Decimal('3'), 'm1': 1.0}, {'region': 'South', 'm0': 'n/a', 'm1': 2}]
    assert [s['data'] for s in chart_option(split, rows, spec.theme, 550)['series']] == [[75.0, None], [25.0, 100.0]]
    # Plain stacked bars keep their raw values and per-metric stacks.
    split.options = {'stacked': True}
    assert [(s['data'], s['stack']) for s in chart_option(split, SPLIT_ROWS, spec.theme, 550)['series']] == [
        ([600, 50.5], 'rural'), ([200, 49.5], 'urban')]


def test_fixed_size_list_renders_unchecked_values_at_its_box():
    import re
    spec = recipe_13_spec()
    page = spec.pages[0]
    data = {'p1_access_over_time': AREA_ROWS, 'p1_split': SPLIT_ROWS, 'p1_regions': LIST_ROWS}
    html = render(spec, data=data)
    parsed = ContractParser(html)
    assert set(parsed.items) == {i.id for i in page.decorations + page.components}
    for item in page.components:
        b = box(spec.canvas, spec.grid, item.grid, height=page.height)
        assert all(f'{prop}:{b[key]}px' in parsed.items[item.id]['style']
                   for prop, key in (('left', 'x'), ('top', 'y'), ('width', 'w'), ('height', 'h')))
        assert parsed.items[item.id]['class'] == f'item component {item.type}'
    listed = html.split('data-cid="p1_regions"', 1)[1].split('</ul>', 1)[0]
    assert '<ul aria-label="Region">' in listed and '<select' not in listed and 'class="label"' not in listed
    assert listed.count('<li><label><input type="checkbox"><span title=') == 4 and 'checked' not in listed
    assert re.findall(r'<span title="([^"]*)">([^<]*)</span>', listed) == [
        ('East', 'East'), ('North', 'North'), ('null', 'null'), ('South &lt;b&gt;', 'South &lt;b&gt;')]
    assert '.fixed_size_list ul{list-style:none;margin:0;padding:0;overflow-y:auto' in html
    assert ContractParser(render(spec, data=data, layer='decoration')).items['p1_regions']['style'].endswith('display:none')
    empty = render(spec, data={**data, 'p1_regions': []}).split('data-cid="p1_regions"', 1)[1].split('</div>', 2)
    assert '<div class="empty">No data' in empty[0] + '</div>' + empty[1]
    charts = json.loads(html.split('const charts=', 1)[1].split(';', 1)[0])
    assert {c['id']: [s['type'] for s in c['option']['series']] for c in charts} == {
        'chart_p1_access_over_time': ['line', 'line'], 'chart_p1_split': ['bar', 'bar']}


def test_recipe_13_types_leave_older_prototypes_unchanged():
    from hashlib import sha256
    golden = DashboardSpec.model_validate_json(Path('tests/data/golden_spec.json').read_text(encoding='utf-8'))
    assert tuple(sha256(render(golden, layer=layer).encode()).hexdigest() for layer in (None, 'decoration')) == GOLDEN_PROTOTYPE
    assert 'fixed_size_list' not in render(golden) and 'fixed_size_list' not in render(designed_spec())
