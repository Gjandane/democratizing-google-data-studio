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
    assert struct.unpack('>II', path.read_bytes()[16:24]) == (1200, spec.canvas.height)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 1200, 'height': spec.canvas.height})
            page.set_content(html)
            label = page.locator(f'[data-cid="{SYNTHETIC_LABEL_ID}"]')
            assert label.inner_text() == 'Synthetic sample data'
            bounds = label.bounding_box()
            expected = label.screenshot()
            encoded = base64.b64encode(path.read_bytes()).decode()
            page.set_content(f'<body style="margin:0"><img src="data:image/png;base64,{encoded}"></body>')
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
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width':1200, 'height':spec.canvas.height})
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
            page.set_content(f'<body style="margin:0"><img src="data:image/png;base64,{encoded}"></body>')
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
    from test_plan import events
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


async def test_render_failure_does_not_publish_or_log_secrets(client, app, build_id, monkeypatch, caplog):
    from test_plan import seed, PLAN, FakeLLM, FakeBigQuery, events
    from dss.harness.guardrails import RunError
    docs = seed(app, build_id)
    def fail(*args):
        raise RuntimeError('test-key private-provider-diagnostic')
    monkeypatch.setattr(background, 'capture', fail)
    with pytest.raises(RunError, match='Prototype rendering failed'):
        await app.state.harness.run('plan', build_id,
            {'config':app.state.settings.get(), 'factory':lambda c:FakeBigQuery()}, llm=FakeLLM(response=json.dumps(PLAN)))
    assert not any(k == 'prototype.updated' for k, _ in events(app, build_id))
    assert client.get(f'/api/builds/{build_id}').json()['stage'] == 'interview'
    assert not (docs.parent / 'prototype.html').exists()
    assert 'private-provider-diagnostic' not in caplog.text
    with app.state.db.connect() as conn:
        traces = conn.execute('SELECT status FROM traces').fetchall()
    assert len(traces) == 1 and traces[0][0] == 'error'


@pytest.mark.live
def test_real_background_dimensions(dashboard, tmp_path):
    path = tmp_path / 'background_p1.png'
    background.capture(render(dashboard, layer='decoration'), path, 1200, 900)
    assert struct.unpack('>II', path.read_bytes()[16:24]) == (1200, 900)


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
    artifacts(dashboard, service, tmp_path)
    assert len(service.queries) == 12
