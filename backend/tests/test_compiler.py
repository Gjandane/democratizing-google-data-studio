"""Recipe compiler on multi-page specs: one add_page + set_canvas + set_background_image per extra page."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dss.recipe.compiler import compile_recipe
from dss.spec.layout import box, with_synthetic_label
from dss.spec.models import SYNTHETIC_LABEL_ID
from test_render import three_pages, staged_flow  # noqa: F401  (fixture)
from test_blueprint import blueprint_api  # noqa: F401  (fixture)
from test_context_node import context_api  # noqa: F401  (fixture)

SCHEMA = json.loads(Path('../contracts/recipe.schema.json').read_text(encoding='utf-8'))
EVIDENCE = Path('.blueprint/qa/task-15.9')


def lines(text):
    assert text.endswith('\n') and '\n\n' not in text
    return [json.loads(line) for line in text.split('\n')[:-1]]


def test_three_page_recipe_ops_order_and_contract():
    spec = three_pages()
    text = compile_recipe(spec, 2)
    header, *ops = lines(text)
    for kind, values in (('header', [header]), ('op', ops)):
        validator = Draft202012Validator({**SCHEMA, '$ref': '#/$defs/' + kind})
        for value in values:
            validator.validate(value)
    assert header['canvas'] == {'width': 1200, 'height': spec.pages[0].height}
    assert [o['id'] for o in ops] == [f's{i:03d}' for i in range(1, len(ops) + 1)]
    expected = ['open_report', ('rename_page', spec.pages[0].name)]
    for page in spec.pages:
        if page.index > 1:
            expected.append(('add_page', page.name))
        expected += [('set_canvas', page.height), ('set_background_image', f'background_p{page.index}.png', page.height)]
        placed = sorted(page.components, key=lambda c: (box(spec.canvas, spec.grid, c.grid, height=page.height)['y'],
                                                        box(spec.canvas, spec.grid, c.grid, height=page.height)['x']))
        for c in placed:
            # 19.2: scorecards have no series swatch, so they get no set_style.
            expected += [('add_chart', c.id)] + ([] if c.type == 'scorecard' else [('set_style', c.id)])
    expected += ['save_report', 'get_link']
    assert {c.type for p in spec.pages for c in p.components} >= {'scorecard', 'bar'}
    def shape(o):
        if o['op'] in ('add_page', 'rename_page'):
            return (o['op'], o['name'])
        if o['op'] == 'set_canvas':
            assert o['width'] == 1200
            return ('set_canvas', o['height'])
        if o['op'] == 'set_background_image':
            assert (o['x'], o['y'], o['w']) == (0, 0, 1200)
            return ('set_background_image', o['path'], o['h'])
        if o['op'] in ('add_chart', 'set_style'):
            return (o['op'], o['component_id'])
        return o['op']
    assert [shape(o) for o in ops] == expected
    # Every chart lands on its own page: ids are page-prefixed and follow that page's add_page.
    page = 1
    for o in ops:
        page += o['op'] == 'add_page'
        if o['op'] == 'add_chart':
            assert o['component_id'].startswith(f'p{page}_')
    assert compile_recipe(three_pages(), 2) == text  # byte-identical
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / 'recipe.jsonl').write_text(text, encoding='utf-8', newline='\n')


def test_synthetic_compile_rebuilds_one_background_per_page(tmp_path, monkeypatch):
    from dss.harness.nodes import compile as node
    from test_render import PageParser
    spec = with_synthetic_label(three_pages(), True)
    captured = []
    def capture(html, path, width, height):
        captured.append(([s[0] for s in PageParser(html).sections], width, height))
        path.write_bytes(b'PNG')
    monkeypatch.setattr('dss.render.background.capture', capture)
    node.perform(spec, 1, tmp_path)
    assert captured == [([str(p.index)], 1200, p.height) for p in spec.pages]
    assert sorted(p.name for p in tmp_path.glob('background_p*.png')) == ['background_p1.png', 'background_p2.png', 'background_p3.png']


def test_hd_background_keeps_canvas_box_and_golden_bytes(tmp_path):
    """19.3: real Chromium backgrounds are 3x pixels under 2 MB; the recipe box and bytes don't change."""
    import struct
    from dss.render import background
    from dss.spec.models import DashboardSpec
    data = Path('tests/data')
    spec = DashboardSpec.model_validate_json((data / 'golden_spec.json').read_text(encoding='utf-8'))
    logo = tmp_path / 'images/logo.png'
    logo.parent.mkdir()
    background.capture('<div id="dss-canvas" style="width:8px;height:8px;background:#123456"></div>', logo, 8, 8)
    assert background.SCALE == 3
    background.write_pages(spec, tmp_path)
    for page in spec.pages:
        png = (tmp_path / f'background_p{page.index}.png').read_bytes()
        assert struct.unpack('>II', png[16:24]) == (3 * spec.canvas.width, 3 * page.height)
        assert len(png) < 2 * 1024 * 1024
    text = compile_recipe(spec, 3)
    assert text.encode('utf-8') == (data / 'golden_recipe.jsonl').read_bytes()
    boxes = [(o['x'], o['y'], o['w'], o['h']) for o in lines(text)[1:] if o['op'] == 'set_background_image']
    assert boxes == [(0, 0, spec.canvas.width, page.height) for page in spec.pages]


async def test_staged_27_components_compile_and_fake_engine_run_done(staged_flow, monkeypatch):
    """16.1: a published 9+9+9 dashboard compiles every component and its run reaches done."""
    import sys
    from dss.spec.models import DashboardSpec
    from test_execute import engine_inputs
    from test_thin_slice import ROOT, wait_done
    client, app, bid, folder, bq, run_id = staged_flow
    spec = DashboardSpec.model_validate_json((folder / 'spec.json').read_text(encoding='utf-8'))
    recipe = client.post(f'/api/builds/{bid}/recipe')
    assert recipe.status_code == 200, recipe.text
    ops = lines((folder / 'recipe.jsonl').read_text(encoding='utf-8'))[1:]
    charts = [o['component_id'] for o in ops if o['op'] == 'add_chart']
    assert sorted(charts) == sorted(c.id for p in spec.pages for c in p.components) and len(charts) == 27
    assert [o['op'] for o in ops].count('add_page') == 2
    # 19.2: per_section page 1 carries its section name; later pages are named by add_page.
    assert ops[:2] == [{'id': 's001', 'op': 'open_report'}, {'id': 's002', 'op': 'rename_page', 'name': spec.pages[0].name}]
    assert [o['op'] for o in ops].count('rename_page') == 1
    assert [o['name'] for o in ops if o['op'] == 'add_page'] == [p.name for p in spec.pages[1:]]
    scorecards = {c.id for p in spec.pages for c in p.components if c.type == 'scorecard'}
    styled = {o['component_id'] for o in ops if o['op'] == 'set_style'}
    assert scorecards and not scorecards & styled
    assert styled == {c.id for p in spec.pages for c in p.components} - scorecards
    monkeypatch.setenv('DSS_ENGINE_CMD', f'"{sys.executable}" "{ROOT / "tests/fake_engine.py"}"')
    monkeypatch.setenv('DSS_ENGINE_DRY_RUN', '1')
    seen = engine_inputs(monkeypatch)
    started = client.post(f'/api/builds/{bid}/run')
    assert started.status_code == 202, started.text
    assert wait_done(client, bid)['stage'] == 'done'
    assert seen == [compile_recipe(spec, 1)]


def test_synthetic_label_is_drawn_by_the_page_one_background_only():
    """23.2: background_p1.png carries the label; a native text op drew it twice, overlapping."""
    spec = with_synthetic_label(three_pages(), True)
    ops = lines(compile_recipe(spec, 1))[1:]
    assert not [o for o in ops if o.get('component_id') == SYNTHETIC_LABEL_ID]
    assert [o['path'] for o in ops if o['op'] == 'set_background_image'] == ['background_p1.png', 'background_p2.png', 'background_p3.png']


def test_designed_recipe_uses_the_canvas_width_and_measured_boxes():
    from dss.spec.models import DashboardSpec
    spec = DashboardSpec.model_validate_json(Path('tests/data/designed_spec.json').read_text(encoding='utf-8'))
    page = spec.pages[0]
    header, *ops = lines(compile_recipe(spec, 1))
    for kind, values in (('header', [header]), ('op', ops)):
        validator = Draft202012Validator({**SCHEMA, '$ref': '#/$defs/' + kind})
        for value in values:
            validator.validate(value)
    assert header['canvas'] == {'width': 1440, 'height': page.height}
    assert [o for o in ops if o['op'] == 'set_canvas'] == [{'id': 's003', 'op': 'set_canvas', 'width': 1440, 'height': page.height}]
    assert [(o['x'], o['y'], o['w'], o['h']) for o in ops if o['op'] == 'set_background_image'] == [(0, 0, 1440, page.height)]
    charts = {o['component_id']: {k: o[k] for k in 'xywh'} for o in ops if o['op'] == 'add_chart'}
    assert charts == {c.id: c.box.model_dump() for c in page.components}
    # Charts are emitted in reading order of their boxes; the footer label is background pixels.
    assert list(charts) == [c.id for c in sorted(page.components, key=lambda c: (c.box.y, c.box.x))]
    assert not [o for o in ops if o.get('component_id') == SYNTHETIC_LABEL_ID]


def bucket_spec(grain='month', *, options=None, bar_on_bucket=False):
    """The golden spec with its time series on a code-built `sale_date_<grain>` bucket field."""
    from dss.spec.models import DashboardSpec
    value = json.loads(Path('tests/data/golden_spec.json').read_text(encoding='utf-8'))
    name = f'sale_date_{grain}'
    value['datasource']['fields'].append({'name': name, 'type': 'DATE', 'label': grain.title(), 'role': 'dimension',
                                          'default_agg': 'none', 'date_granularity': grain})
    for c in (c for p in value['pages'] for c in p['components']):
        if c['type'] == 'time_series':
            c.update(date_dimension=name, sort={'field': name, 'order': 'asc'})
            if options is not None:
                c['options'] = options
        if c['type'] == 'bar' and bar_on_bucket:
            c['dimensions'] = [name]
    return DashboardSpec.model_validate(value)


def golden_spec():
    from dss.spec.models import DashboardSpec
    return DashboardSpec.model_validate_json(Path('tests/data/golden_spec.json').read_text(encoding='utf-8'))


def charts(spec):
    return {o['component_id']: o for o in lines(compile_recipe(spec, 1))[1:] if o['op'] == 'add_chart'}


@pytest.mark.parametrize('function', ['DATE_TRUNC', 'DATETIME_TRUNC', 'TIMESTAMP_TRUNC'])
@pytest.mark.parametrize('grain', ['day', 'week', 'month', 'quarter', 'year'])
def test_time_series_on_a_bucket_carries_its_grain(function, grain):
    """23.1 (release 2.5 b_36f20b42159c s015): the derivation's grain becomes the time series'
    options.date_granularity, from the view SQL through the spec, so Data Studio draws one point per bucket."""
    from dss.spec.auto_layout import bucket_grain
    code = bucket_grain(f'{function}(sale_date, {grain.upper()})')
    spec = bucket_spec(code)
    text = compile_recipe(spec, 3)
    trend = charts(spec)['p1_time_series']
    assert (trend['date_dimension'], trend['options']) == (f'sale_date_{grain}', {'date_granularity': grain})
    for value in lines(text)[1:]:
        Draft202012Validator({**SCHEMA, '$ref': '#/$defs/op'}).validate(value)
    # Only that op changed against the golden recipe.
    golden = Path('tests/data/golden_recipe.jsonl').read_text(encoding='utf-8').split('\n')
    changed = [i for i, (a, b) in enumerate(zip(golden, text.split('\n'))) if a != b]
    assert len(golden) == len(text.split('\n')) and changed == [next(
        i for i, line in enumerate(golden) if '"component_id":"p1_time_series","date_dimension"' in line)]


def test_raw_dates_and_other_charts_on_a_bucket_get_no_grain():
    golden = charts(golden_spec())
    assert 'date_granularity' not in golden['p1_time_series']['options']  # raw sale_date
    spec = bucket_spec(bar_on_bucket=True)
    bar = charts(spec)['p1_bar']
    assert bar['dimensions'] == ['sale_date_month'] and bar['options'] == {'orientation': 'horizontal', 'stacked': True}
    assert all('date_granularity' not in o['options'] for cid, o in charts(spec).items() if cid != 'p1_time_series')


def test_model_written_date_granularity_never_reaches_the_recipe():
    """A revise patch or designer output can write options; the code grain overwrites or drops theirs."""
    assert charts(bucket_spec(options={'date_granularity': 'day'}))['p1_time_series']['options'] == {'date_granularity': 'month'}
    assert charts(bucket_spec(options={'date_granularity': 'month'}))['p1_time_series']['options'] == {'date_granularity': 'month'}
    raw = golden_spec()
    for c in (c for p in raw.pages for c in p.components):
        if c.type in ('time_series', 'bar'):
            c.options = {**c.options, 'date_granularity': 'month'}
    compiled = charts(raw)
    assert compiled['p1_time_series']['options'] == {}
    assert compiled['p1_bar']['options'] == {'orientation': 'horizontal', 'stacked': True}
    # A name that only looks like a bucket carries no grain: the spec field has none.
    named = bucket_spec()
    named.datasource.fields[-1].date_granularity = None
    assert charts(named)['p1_time_series']['options'] == {}


def test_bucket_compile_is_a_pure_function_of_the_spec():
    spec = bucket_spec(options={'date_granularity': 'year'})
    before = spec.model_dump_json()
    assert compile_recipe(spec, 3) == compile_recipe(spec, 3)
    assert spec.model_dump_json() == before  # the compiler rewrote no option in place
    from dss.spec.models import DashboardSpec
    assert compile_recipe(DashboardSpec.model_validate_json(before), 3) == compile_recipe(spec, 3)


def test_decided_monthly_gap_publishes_a_monthly_time_series(blueprint_api, monkeypatch):
    """22.1's release gap (b_48ef72ff1bff), decided with its date-bucket alternative, publishes a recipe
    whose monthly time series carries date_granularity month (FakeLLM, FakeBigQuery, staged API)."""
    from dss.spec.models import DashboardSpec
    from test_blueprint import choose, confirm
    from test_render import GAP_FIXES, accept, gap_build, gap_issues
    build = gap_build(blueprint_api, monkeypatch, 'monthly')
    confirm(build.client, build.app, build.bid)
    for oid, fix in GAP_FIXES['monthly'].items():
        current = build.client.get(f'/api/builds/{build.bid}/feasibility').json()
        assert choose(build.client, build.bid, current, gap_issues(current, build)[oid], fix).status_code == 200
    accept(build)
    spec = DashboardSpec.model_validate_json((build.folder / 'spec.json').read_text(encoding='utf-8'))
    assert {f.name: f.date_granularity for f in spec.datasource.fields if f.date_granularity} == {'order_date_month': 'month'}
    recipe = build.client.post(f'/api/builds/{build.bid}/recipe')
    assert recipe.status_code == 200, recipe.text
    ops = lines((build.folder / 'recipe.jsonl').read_text(encoding='utf-8'))[1:]
    series = [o for o in ops if o['op'] == 'add_chart' and o['chart_type'] == 'time_series']
    # The release build's other trend stays on the raw order_date: no grain.
    assert sorted((o['title'], o['date_dimension'], o['options'].get('date_granularity')) for o in series) == [
        ('Revenue Trend Over Time', 'order_date', None), ('Revenue by month', 'order_date_month', 'month')]
    assert not any('date_granularity' in o['options'] for o in ops if o['op'] == 'add_chart' and o['chart_type'] != 'time_series')
