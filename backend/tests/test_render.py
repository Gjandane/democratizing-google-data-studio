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
    from test_designer import DesignerLLM, ReferenceHTMLLLM
    pair = {'reference_brief': BriefLLM(), 'reference_html': ReferenceHTMLLLM(),
            'designer': DesignerLLM(plan={1: ['bad']})}
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


def recreate_build(blueprint_api, monkeypatch, data=None, synthetic=False, designer=None, designed=True,
                   brief=None, reference_html=None):
    """Staged build whose Blueprint answers the recreate fixture `data` (default: the electricity one); a
    synthetic (screenshot-only) source or the uploaded one; `designer` answers the designer node
    (`designed` False: Config.designed_pages off)."""
    from types import SimpleNamespace
    from test_blueprint import artifact, fixture
    from test_references import Capture, output
    from dss.artifacts.models import Context, Outline
    from dss.spec import references
    client, app, bid, sid, folder, bq, llm, value = blueprint_api
    context = fixture('context')
    context['datasets'][0]['source_id'] = sid
    data = ELECTRICITY if data is None else data
    if 'kpis' in data:
        # A release build's own confirmed KPIs and connected columns.
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
                            monkeypatch=monkeypatch,
                            vision=Capture(response=output(), requests=[]), extraction=None)
    from test_reference_brief import BriefLLM
    from test_designer import ReferenceHTMLLLM
    build.brief = brief or BriefLLM()
    build.reference_html = reference_html or designer or ReferenceHTMLLLM()
    monkeypatch.setattr(app.state.models, 'llm_for', lambda action: {
        'reference_extract': build.vision, 'capability_check': build.extraction, 'designer': designer,
        'reference_brief': build.brief, 'reference_html': build.reference_html}.get(action) or llm)
    return build


def approved_static_analysis():
    """An approved all-static analysis (zero native items is a valid approval): it passes the gate and adds no
    requirements."""
    from dss.spec import references
    item = references.AnalysisItem(id='r1', label='Reference page', kind='other', box={'x': 0, 'y': 0, 'w': 1, 'h': 1},
        disposition='static', type=None, shows='', reason='Fixture: everything stays art.',
        proposed={'disposition': 'static', 'type': None})
    return references.ReferenceAnalysis(revision=1, state='approved', summary=references.analysis_summary([item]),
        items=[item], note='', allowed_types=[], issues=[]).model_dump()


def saved_image(folder, image_id):
    """A saved fixture's reference image as references.image_entry records it (size and digest), written
    beside the set, so the blueprint planner and the brief can attach it."""
    import hashlib
    from test_references import png
    content = png()
    (folder / 'reference_img_000000000000.png').write_bytes(content)
    return {'id': image_id, 'name': 'reference.png', 'file': 'reference_img_000000000000.png', 'mime_type': 'image/png',
            'width': 1200, 'height': 900, 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}


NOTES = {'palette_notes': '', 'type_notes': '', 'spacing_notes': ''}


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


def spans(app, run_id):
    with app.state.db.connect() as conn:
        trace = conn.execute('SELECT * FROM traces WHERE run_id=?', (run_id,)).fetchone()
    return trace, json.loads(trace['spans_json'])


ELECTRICITY = json.loads((Path(__file__).parent / 'data/recreate_electricity.json').read_text(encoding='utf-8'))


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


# Task 26.4 (architecture.md#Reference analysis and approval gate): Argon plans from the image plus the
# approved items; the electricity split is the 26.2 fixture's (bar, area, region list native; the rest static).
NATIVE_ROWS = {
    'r3': {'type': 'fixed_size_list', 'label': 'Region Selector', 'dimensions': ['region'], 'metrics': [],
           'date_dimension': None, 'breakdown': None, 'sort': None, 'options': {}},
    'r6': {'type': 'area', 'label': 'Rural and urban access by country', 'dimensions': [], 'date_dimension': 'year',
           'metrics': [{'field': 'urban_pct', 'agg': 'avg'}, {'field': 'rural_pct', 'agg': 'avg'}],
           'breakdown': None, 'sort': None, 'options': {}},
    'r8': {'type': 'bar', 'label': 'People without access to electricity', 'dimensions': ['year'], 'date_dimension': None,
           'metrics': [{'field': 'people_without_access', 'agg': 'sum'}], 'breakdown': None, 'sort': None, 'options': {}}}


def item_row(item, component=None, question_id=None):
    return {'question_id': question_id, 'section_id': 's1', 'page': 1, 'note': '', 'status': 'ok', 'issue_ids': [],
            'reference_item': item, 'component': copy.deepcopy(component or NATIVE_ROWS[item])}


def items_build(blueprint_api, monkeypatch, items=('r3', 'r6', 'r8'), extra=(), replies=None, images=2, **options):
    """The electricity build with the 26.2 analysis committed (`images` reference images) and approved through
    the gate; the planner's draft adds rows naming `items` (plus `extra` rows) to the release build's rows."""
    from types import SimpleNamespace
    from dss.db import now
    from dss.spec import references
    from dss.spec.models import TYPES
    from test_reference_gate import FIXTURE, approve
    from test_references import png
    monkeypatch.setenv('DSS_ALLOWED_TYPES', ','.join(TYPES))
    build = recreate_build(blueprint_api, monkeypatch, data=ELECTRICITY, synthetic=True, **{'designed': False, **options})
    bq = blueprint_api[5]
    bq.dry_run = lambda sql: bq.sql.append(sql) or [SimpleNamespace(name='year_year', field_type='DATE', mode='NULLABLE')]
    reply = FIXTURE['reply']
    files = [{'id': f'img_{n:012d}', 'name': f'electricity-{n}.png', 'file': f'reference_img_{n:012d}.png',
              'mime_type': 'image/png', 'width': 160 + n, 'height': 100, 'content': png(160 + n, 100)} for n in range(images)]
    interpretation = references.interpret('recreate', 160, 100, {k: reply[k] for k in ('palette_notes', 'type_notes', 'spacing_notes')})
    analysis = references.analyze([references.AnalysisAnswer.model_validate(i) for i in reply['items']], list(TYPES))
    record = {'id': 'ref_0123456789ab', 'mode': 'recreate', 'instructions': FIXTURE['instructions'],
              'images': [references.image_entry(f) for f in files],
              'summary': references.summary(interpretation, reply['style']['palette'], images, analysis),
              'style': reply['style'], 'interpretation': interpretation.model_dump(), 'analysis': analysis.model_dump(),
              'created_at': now()}
    (build.folder / 'docs').mkdir(parents=True, exist_ok=True)
    references.commit(build.folder, record, files, {'reference.md': references.reference_doc(record)})
    build.images = [f['content'] for f in files]
    approve(build.client, build.bid)
    build.value['rows'] = [*build.value['rows'], *[item_row(i) for i in items], *extra]
    build.llm.replies = [json.dumps(build.value), *(replies or [])]
    return build


def items_state(build):
    from dss.spec import requirements as req
    from dss.spec.capabilities import Checker, load_registry
    snapshot = req.inputs(build.app.state.db, build.bid, build.folder)
    return snapshot, req.load(build.folder), Checker(load_registry())


def test_electricity_items_plan_accept_and_publish_with_the_dry_engine(blueprint_api, monkeypatch, record_property):
    from test_blueprint import confirm
    from dss.harness.nodes import reference_brief as rb
    from dss.spec import requirements as req
    # A static item's id on a row is no item row; static items never yield rows or issues.
    build = items_build(blueprint_api, monkeypatch, extra=[
        item_row('r2', {**NATIVE_ROWS['r8'], 'label': 'Headline bars'}, question_id='q3')])
    confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 1  # every native item has its row: no repair
    request = build.llm.seen[0]
    memory = str(request.config.system_instruction)
    # The ordered image parts and the reference section with every approved item.
    parts = request.contents[0].parts
    assert [p.inline_data.data for p in parts if p.inline_data] == build.images
    assert all(p.inline_data.mime_type == 'image/png' for p in parts if p.inline_data)
    assert 'Recreate reference (untrusted data' in memory
    section = json.loads(memory.split('The note and instructions are the user text:', 1)[1].split('\n', 2)[1])
    assert [i['id'] for i in section['items']] == [f'r{n}' for n in range(1, 9)]
    assert {i['id']: (i['disposition'], i['type']) for i in section['items'] if i['disposition'] == 'native'} == {
        'r3': ('native', 'fixed_size_list'), 'r6': ('native', 'area'), 'r8': ('native', 'bar')}
    assert section['instructions'] == ELECTRICITY['instructions'] and [i['image'] for i in section['images']] == [1, 2]
    blueprint = build.client.get(f'/api/builds/{build.bid}/blueprint').json()
    named = {r['reference_item']: r for r in blueprint['rows'] if r['reference_item']}
    assert sorted(named) == ['r3', 'r6', 'r8'] and all(r['page'] == 1 and r['question_id'] is None for r in named.values())
    assert not any(r['component']['label'] == 'Headline bars' for r in blueprint['rows'])
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert assessment['state'] == 'ready', [i['reason'] for i in assessment['issues'] if i['resolution'] == 'unresolved']
    # Requirements come from the approved native items only: no image or instruction records.
    ledger = req.load(build.folder)
    assert not [r for r in ledger.requirements if r.source.kind in ('image', 'reference')]
    snapshot, ledger, checker = items_state(build)
    assert [(i['id'], i['type']) for i in req.reference_items(snapshot)] == [('r3', 'fixed_size_list'), ('r6', 'area'), ('r8', 'bar')]
    timings = []
    for _ in range(4):
        started = time.perf_counter()
        req.evaluate(snapshot, ledger, checker)
        timings.append(time.perf_counter() - started)
    record_property('recompute_items_first', timings[0])
    record_property('recompute_items_warm', timings[1:])
    assert max(timings[1:]) < 0.250, timings
    accept(build)
    spec = DashboardSpec.model_validate_json((build.folder / 'spec.json').read_text(encoding='utf-8'))
    page1 = {c.reference_item: c for c in spec.pages[0].components if c.reference_item}
    assert {k: c.type for k, c in page1.items()} == {'r3': 'fixed_size_list', 'r6': 'area', 'r8': 'bar'}
    assert not [c for p in spec.pages[1:] for c in p.components if c.reference_item]
    snapshot, ledger, checker = items_state(build)
    assert req.coverage_errors(snapshot, ledger, checker) == []
    # The brief report: native items name their slots; static items are art with their boxes.
    report = rb.report(snapshot, ledger, checker)[1]['reference_items']
    assert {i['id']: i['slots'] for i in report['native']} == {k: [c.id] for k, c in page1.items()}
    assert [i['id'] for i in report['static']] == ['r1', 'r2', 'r4', 'r5', 'r7']
    assert all(set(i) == {'id', 'kind', 'label', 'box', 'shows'} for i in report['static'])
    assert next(i for i in report['static'] if i['id'] == 'r4')['kind'] == 'image'
    executes(build.client, build.app, build.bid, monkeypatch)
    recipe = (build.folder / 'recipe.jsonl').read_text(encoding='utf-8')
    assert 'reference_item' not in recipe and '"fixed_size_list"' in recipe


def test_item_without_row_gets_the_one_repair(blueprint_api, monkeypatch):
    from test_blueprint import confirm
    repair = {'rows': [item_row('r8')]}
    build = items_build(blueprint_api, monkeypatch, items=('r3', 'r6'), replies=[json.dumps(repair)])
    confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 2
    text = str(build.llm.seen[1].config.system_instruction)
    assert 'Reference item r8' in text and 'component type bar' in text
    blueprint = build.client.get(f'/api/builds/{build.bid}/blueprint').json()
    assert sorted(r['reference_item'] for r in blueprint['rows'] if r['reference_item']) == ['r3', 'r6', 'r8']
    assert build.client.get(f'/api/builds/{build.bid}/feasibility').json()['state'] == 'ready'


def test_unfulfilled_item_is_an_issue_whose_drop_keeps_it_static(blueprint_api, monkeypatch):
    from test_blueprint import confirm
    from dss.harness.nodes import reference_brief as rb
    from dss.spec import requirements as req
    build = items_build(blueprint_api, monkeypatch, items=('r3', 'r6'), replies=[json.dumps({'rows': []})])
    confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 2  # the draft and the one row repair, no more
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    pending = [i for i in assessment['issues'] if i['resolution'] == 'unresolved']
    assert assessment['state'] == 'blocked' and len(pending) == 1, pending
    [issue] = pending
    assert issue['status'] == 'needs_clarification' and 'r8' in issue['reason'] and 'bar' in issue['reason']
    # Code-built alternatives only: the item's type on an existing row's fields, as a page-1 row naming it.
    for alternative in issue['alternatives']:
        assert alternative['label'].startswith('Show People without access to electricity as a bar')
    response = build.client.post(f'/api/builds/{build.bid}/blueprint/accept')
    assert response.status_code == 409 and response.json()['error']['code'] == 'feasibility_blocked'
    # The blocked accept re-saves the assessment (blueprint.preflight); decide on the current one.
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    [issue] = [i for i in assessment['issues'] if i['resolution'] == 'unresolved']
    dropped = build.client.post(f'/api/builds/{build.bid}/feasibility/decisions', json={
        'assessment_id': assessment['id'], 'decisions': [{'issue_id': issue['id'], 'action': 'drop', 'alternative_id': None}]})
    assert dropped.status_code == 200, dropped.text
    after = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert after['state'] == 'ready', [i['reason'] for i in after['issues'] if i['resolution'] == 'unresolved']
    assert {i['id']: i['resolution'] for i in after['issues']}[issue['id']] == 'dropped'
    assert "r8 'People without access to electricity' kept as static art (dropped)" in (
        build.folder / 'docs/feasibility.md').read_text(encoding='utf-8')
    accept(build)
    snapshot, ledger, checker = items_state(build)
    assert req.coverage_errors(snapshot, ledger, checker) == []
    report = rb.report(snapshot, ledger, checker)[1]['reference_items']
    assert [i['id'] for i in report['native']] == ['r3', 'r6']
    assert 'r8' in [i['id'] for i in report['static']]
    spec = DashboardSpec.model_validate_json((build.folder / 'spec.json').read_text(encoding='utf-8'))
    assert 'r8' not in {c.reference_item for p in spec.pages for c in p.components}


def test_unfulfilled_item_alternative_adds_its_row(blueprint_api, monkeypatch):
    from test_blueprint import confirm
    build = items_build(blueprint_api, monkeypatch, items=('r3', 'r6'), replies=[json.dumps({'rows': []})])
    confirm(build.client, build.app, build.bid)
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    [issue] = [i for i in assessment['issues'] if i['resolution'] == 'unresolved']
    assert issue['alternatives'], issue
    chosen = build.client.post(f'/api/builds/{build.bid}/feasibility/decisions', json={'assessment_id': assessment['id'],
        'decisions': [{'issue_id': issue['id'], 'action': 'accept_alternative', 'alternative_id': issue['alternatives'][0]['id']}]})
    assert chosen.status_code == 200, chosen.text
    assert build.client.get(f'/api/builds/{build.bid}/feasibility').json()['state'] == 'ready'
    rows = build.client.get(f'/api/builds/{build.bid}/blueprint').json()['rows']
    [row] = [r for r in rows if r['reference_item'] == 'r8']
    assert row['page'] == 1 and row['component']['type'] == 'bar'
    accept(build)


def test_publish_coverage_fails_a_candidate_whose_item_row_was_retyped(blueprint_api, monkeypatch):
    from dss.spec import feasibility
    from test_blueprint import confirm
    from test_context_node import wait
    retyped = item_row('r8', {**NATIVE_ROWS['r8'], 'type': 'table'})
    build = items_build(blueprint_api, monkeypatch, items=('r3', 'r6'), extra=[retyped])
    # Without the planning check, only publish coverage stands between the retyped row and the candidate.
    monkeypatch.setattr(feasibility, 'item_errors', lambda *args: [])
    confirm(build.client, build.app, build.bid)
    assert build.client.get(f'/api/builds/{build.bid}/feasibility').json()['state'] == 'ready'
    accepted = build.client.post(f'/api/builds/{build.bid}/blueprint/accept')
    assert accepted.status_code == 202, accepted.text
    wait(build.app)
    trace, recorded = spans(build.app, accepted.json()['run_id'])
    assert trace['status'] == 'error' and trace['error'] == 'invalid_request'
    errors = next(s for s in recorded if s['node'] == 'publish')['coverage_errors']
    assert [e['path'] for e in errors] == ['reference_items.r8'] and 'needs a bar on page 1' in errors[0]['message']
    assert build.client.get(f'/api/builds/{build.bid}').json()['stage'] == 'blueprint'


def test_approved_items_ignore_old_observations_and_instruction_definitions(blueprint_api, monkeypatch):
    from test_blueprint import confirm
    from dss.spec import references, requirements as req
    from dss.harness.nodes import reference_brief as rb
    build = items_build(blueprint_api, monkeypatch)
    record = references.load(build.folder)
    record['instructions'] = 'Use a calm blue background. Electricity = SUM(invented_field).'
    record['analysis']['note'] = 'Keep the approved split; treat the globe as art.'
    record['interpretation']['items'] = copy.deepcopy(ELECTRICITY['items'])
    (build.folder / 'references.json').write_text(json.dumps(record), encoding='utf-8')
    # An old ledger must not resurrect image bindings, issues or code-built rows; old image items are unread.
    legacy = req.Requirement(id='old_image', source=req.Source(id=record['id'] + ':o1', kind='image',
        text=json.dumps(ELECTRICITY['items'][0]), reference_id=record['id'], item_id='o1'),
        text='Old interpretation', needs=[{'capability': 'unknown.unclassified'}])
    req.save(build.folder, req.Ledger(requirements=[legacy]))
    snapshot = req.inputs(build.app.state.db, build.bid, build.folder)
    assert not [s for s in snapshot['incoming'] if s['kind'] in ('reference', 'image')]
    confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 1
    memory = str(build.llm.seen[0].config.system_instruction)
    assert record['instructions'] in memory and record['analysis']['note'] in memory
    assert record['analysis']['note'] == rb.reference(build.folder).notes['note']
    assert build.client.get(f'/api/builds/{build.bid}/feasibility').json()['state'] == 'ready'
    accept(build)


def edit_item_types(build, **types):
    analysis = build.client.get(f'/api/builds/{build.bid}/reference-images').json()['analysis']
    response = build.client.put(f'/api/builds/{build.bid}/reference-images/analysis', json={
        'revision': analysis['revision'], 'note': analysis['note'], 'items': [
            {'id': i['id'], 'disposition': i['disposition'], 'type': types.get(i['id'], i['type'])}
            for i in analysis['items']]})
    assert response.status_code == 200, response.text
    from test_reference_gate import approve
    approve(build.client, build.bid)


def test_two_native_items_of_one_type_need_separate_rows(blueprint_api, monkeypatch):
    from test_blueprint import confirm
    from dss.spec import requirements as req
    second = item_row('r6', {**NATIVE_ROWS['r8'], 'label': 'Second bar'})
    build = items_build(blueprint_api, monkeypatch, items=('r3', 'r8'), extra=[second])
    edit_item_types(build, r6='bar')
    confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 1
    assert build.client.get(f'/api/builds/{build.bid}/feasibility').json()['state'] == 'ready'
    accept(build)
    snapshot, ledger, checker = items_state(build)
    slots = req.item_components(snapshot, ledger, checker)
    assert len(slots['r6']) == len(slots['r8']) == 1 and slots['r6'] != slots['r8']


def test_unfeedable_native_item_has_no_invented_field_alternative(blueprint_api, monkeypatch):
    from test_blueprint import confirm, choose
    build = items_build(blueprint_api, monkeypatch, items=('r3', 'r6'), replies=[json.dumps({'rows': []})])
    edit_item_types(build, r8='geo_map')
    confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 2
    assessment = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    [issue] = [i for i in assessment['issues'] if i['resolution'] == 'unresolved']
    assert issue['status'] == 'needs_clarification' and issue['alternatives'] == []
    response = choose(build.client, build.bid, assessment, issue)
    assert response.status_code == 200 and response.json()['state'] == 'ready', response.text


def test_zero_native_items_plan_and_publish_as_art_plus_outline_rows(blueprint_api, monkeypatch):
    from test_blueprint import confirm
    from test_reference_gate import approve
    from dss.spec import requirements as req
    from dss.harness.nodes import reference_brief as rb
    build = items_build(blueprint_api, monkeypatch, items=())
    analysis = build.client.get(f'/api/builds/{build.bid}/reference-images').json()['analysis']
    response = build.client.put(f'/api/builds/{build.bid}/reference-images/analysis', json={
        'revision': analysis['revision'], 'note': '', 'items': [
            {'id': i['id'], 'disposition': 'static', 'type': None} for i in analysis['items']]})
    assert response.status_code == 200, response.text
    approve(build.client, build.bid)
    confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 1
    assert build.client.get(f'/api/builds/{build.bid}/feasibility').json()['state'] == 'ready'
    accept(build)
    snapshot, ledger, checker = items_state(build)
    assert req.reference_items(snapshot) == [] and req.coverage_errors(snapshot, ledger, checker) == []
    split = rb.report(snapshot, ledger, checker)[1]['reference_items']
    assert split['native'] == [] and len(split['static']) == 8


def test_item_repair_can_also_answer_a_selected_question(blueprint_api, monkeypatch):
    from test_blueprint import confirm
    build = items_build(blueprint_api, monkeypatch, items=('r3', 'r6'),
        replies=[json.dumps({'rows': [item_row('r8', question_id='q3')]})])
    confirm(build.client, build.app, build.bid)
    assert build.llm.calls == 2
    rows = build.client.get(f'/api/builds/{build.bid}/blueprint').json()['rows']
    assert any(r['reference_item'] == 'r8' and r['question_id'] == 'q3' and r['page'] == 1 for r in rows)
    assert build.client.get(f'/api/builds/{build.bid}/feasibility').json()['state'] == 'ready'


def test_designed_recreate_accept_uses_the_checked_brief_and_html_with_the_approved_split(blueprint_api, monkeypatch):
    """Port of the observation-era brief/HTML accept test: both composition requests carry the same code-built
    report and images, the pages publish designed, and the synthetic label stays code-drawn."""
    from test_blueprint import confirm
    from test_designer import ReferenceHTMLLLM
    from test_reference_brief import BriefLLM, attached, section
    from dss.harness.context import COMPONENTS_HEADER, ITEMS_HEADER
    from dss.recipe.compiler import compile_recipe
    from dss.spec import requirements as req
    from dss.spec.models import SYNTHETIC_LABEL
    brief, html = BriefLLM(), ReferenceHTMLLLM()
    build = items_build(blueprint_api, monkeypatch, designed=True, brief=brief, reference_html=html)
    confirm(build.client, build.app, build.bid)
    accept(build)
    spec = DashboardSpec.model_validate_json((build.folder / 'spec.json').read_text(encoding='utf-8'))
    assert spec.datasource.synthetic and all(p.design and p.design.model == html.model for p in spec.pages)
    assert len(brief.requests) == html.calls == len(spec.pages)
    first = str(brief.requests[0].config.system_instruction), str(html.requests[0].config.system_instruction)
    approved, implementation = (json.loads(section(text, COMPONENTS_HEADER)) for text in first)
    strip_minima = lambda rows: [{k: v for k, v in c.items() if k not in ('min_w', 'min_h')} for c in rows]
    assert strip_minima(approved['components']) == strip_minima(implementation['components'])
    assert all(c['min_w'] and c['min_h'] for c in implementation['components'])
    assert approved['decisions'] == implementation['decisions']
    # Page 1 names the approved split: native items by their slots, static items as art with boxes.
    split = [json.loads(section(text, ITEMS_HEADER)) for text in first]
    assert split[0] == split[1] and [i['id'] for i in split[0]['native']] == ['r3', 'r6', 'r8']
    assert {i['id'] for i in split[0]['static']} == {'r1', 'r2', 'r4', 'r5', 'r7'}
    page1 = {c.reference_item: c.id for c in spec.pages[0].components if c.reference_item}
    assert {i['id']: i['slots'] for i in split[0]['native']} == {k: [v] for k, v in page1.items()}
    assert attached(brief.requests[0])[1] == attached(html.requests[0])[1] == [('image/png', c) for c in build.images]
    with build.app.state.db.connect() as conn:
        run_id = conn.execute("SELECT run_id FROM traces WHERE node='prototype' ORDER BY started_at DESC").fetchone()[0]
    trace, recorded = spans(build.app, run_id)
    assert [s['model'] for s in recorded if s['node'] in ('reference_brief', 'reference_html')][:2] == [brief.model, html.model]
    assert all('coverage_errors' not in s for s in recorded)
    # The page-1 background draws the provenance label; the recipe never draws it again.
    assert SYNTHETIC_LABEL in render(spec, layer='decoration', page=1) and SYNTHETIC_LABEL not in compile_recipe(spec, 1)
    snapshot, ledger, checker = items_state(build)
    assert req.coverage_errors(snapshot, ledger, checker) == []
    fresh = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
    assert fresh['state'] == 'ready' and not fresh['prototype_stale'], fresh
    executes(build.client, build.app, build.bid, monkeypatch)
