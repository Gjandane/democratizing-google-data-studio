"""Recipe compiler on multi-page specs: one add_page + set_canvas + set_background_image per extra page."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dss.recipe.compiler import compile_recipe
from dss.spec.layout import box, with_synthetic_label
from dss.spec.models import SYNTHETIC_LABEL_ID
from test_render import blueprint_flow, recipe_13_spec, three_pages, staged_flow  # noqa: F401  (fixture)
from test_blueprint import blueprint_api  # noqa: F401  (fixture)
from test_context_node import context_api  # noqa: F401  (fixture)

SCHEMA = json.loads(Path('../contracts/recipe.schema.json').read_text(encoding='utf-8'))


def test_discriminated_validation_matches_full_contract_on_ops_and_corruptions():
    """The original complete contract is the oracle, including nested/wrapper rules."""
    from copy import deepcopy
    from dss.recipe.compiler import _op_validators
    from jsonschema import Draft202012Validator
    full = Draft202012Validator({**SCHEMA, '$ref': '#/$defs/op'})
    indexed = _op_validators(SCHEMA)
    samples = [json.loads(line) for line in Path('../contracts/fixtures/recipe.sample.jsonl').read_text(encoding='utf-8').splitlines()[1:]]
    samples.extend([
        {'id': 's001', 'op': 'rename_page', 'name': 'Overview'},
        {'id': 's001', 'op': 'go_to_page', 'index': 1},
        {'id': 's001', 'op': 'add_page', 'name': 'Next'},
        {'id': 's001', 'op': 'add_text', 'component_id': 'heading', 'text': 'Title', 'x': 0, 'y': 0, 'w': 20, 'h': 20},
        {'id': 's001', 'op': 'add_image', 'component_id': 'logo', 'path': 'logo.png', 'x': 0, 'y': 0, 'w': 20, 'h': 20},
        {'id': 's001', 'op': 'set_style', 'component_id': 'chart', 'style': {'colors': ['#123456']}},
        {'id': 's001', 'op': 'add_control', 'component_id': 'filter', 'control_type': 'fixed_size_list', 'field': 'country', 'x': 0, 'y': 0, 'w': 20, 'h': 20},
    ])
    assert set(indexed) <= {sample['op'] for sample in samples}
    corpus = []
    for sample in samples:
        assert full.is_valid(sample), sample
        corpus.append(sample)
        for field in sample:
            for value in (None, False, 0, -1, '', 'invalid', [], {}):
                corpus.append({**sample, field: value})
            corpus.append({key: value for key, value in sample.items() if key != field})
        corpus.append({**sample, 'unexpected': 'preserve contract behavior'})
        if 'metrics' in sample:
            corpus.append({**sample, 'metrics': [{'field': 'sales', 'agg': 'invalid'}]})
        if sample['op'] == 'set_style':
            corpus.append({**sample, 'style': {'colors': ['invalid']}})
    for value in corpus:
        name = value.get('op')
        selected = indexed.get(name, full) if isinstance(name, str) else full
        assert selected.is_valid(value) == full.is_valid(value), value
    # Future ambiguous/undiscriminated alternatives must use the complete union.
    for extra in ({'properties': {'op': {'const': 'open_report'}}}, {'type': 'object'}, True, False):
        changed = deepcopy(SCHEMA)
        changed['$defs']['op']['oneOf'].append(extra)
        assert _op_validators(changed) == {}
    # References to the original op union keep their original meaning.
    recursive = deepcopy(SCHEMA)
    recursive['$defs']['op']['oneOf'][0]['properties']['child'] = {'$ref': '#/$defs/op'}
    value = {'id': 's001', 'op': 'open_report', 'child': {'id': 's002', 'op': 'set_canvas', 'width': 2, 'height': 2}}
    assert Draft202012Validator({**recursive, '$ref': '#/$defs/op'}).is_valid(value)
    assert _op_validators(recursive)['open_report'].is_valid(value)
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
        ('Revenue Trend Over Time', 'order_date', None), ('Revenue by month (USD)', 'order_date_month', 'month')]  # 24.10: unit
    assert not any('date_granularity' in o['options'] for o in ops if o['op'] == 'add_chart' and o['chart_type'] != 'time_series')


def test_release_26_yearly_date_column_draws_one_point_per_year():
    """24.2: release 2.6 b_697880743b4f (spec/recipe copies, project renamed) drew s008/s010 on its `year`
    DATE (every value YYYY-01-01) as a daily axis: the model's `date_granularity: year` was rightly dropped
    and its profile predates the bucket fact. With the fact the code grain reaches only those two ops."""
    from dss.artifacts.models import ViewSources
    from dss.spec.auto_layout import base_grains
    from dss.spec.models import DashboardSpec
    spec = DashboardSpec.model_validate_json(Path('tests/data/release_2_6_spec.json').read_text(encoding='utf-8'))
    release = lines(Path('tests/data/release_2_6_recipe.jsonl').read_text(encoding='utf-8'))
    assert lines(compile_recipe(spec, 1)) == release  # a profile without the fact compiles as before
    source = {'id': 's_728c05b5e9af', 'columns': [{'name': f.name, 'bq_type': f.type,
                                                   **({'bucket_start': 'year'} if f.name == 'year' else {})}
                                                  for f in spec.datasource.fields]}
    grains = base_grains([source], ViewSources(base='s_728c05b5e9af', joins=[], union=[]))
    assert grains == {'year': 'year'}
    for field in spec.datasource.fields:
        field.date_granularity = grains.get(field.name)
    compiled = lines(compile_recipe(spec, 1))
    assert len(compiled) == len(release)
    changed = [(old['id'], new) for old, new in zip(release, compiled) if old != new]
    assert changed == [(old['id'], {**old, 'options': {'date_granularity': 'year'}})
                       for old in release if old.get('id') in ('s008', 's010')]
    # The model's matching grain is the code value; a different one never reaches the recipe.
    for c in (c for page in spec.pages for c in page.components if c.type == 'time_series'):
        c.options = {'date_granularity': 'month'}
    assert lines(compile_recipe(spec, 1)) == compiled


@pytest.fixture
def bucketed_source(blueprint_api):
    """The connected source's stored intake profile records `order_date` on month starts."""
    client, app, bid, sid, *_ = blueprint_api
    with app.state.db.connect() as conn:
        columns = json.loads(conn.execute('SELECT columns_json FROM sources WHERE id=?', (sid,)).fetchone()[0])
        date = next(c for c in columns if c['name'] == 'order_date')
        assert date['bq_type'] == 'DATE'
        date['bucket_start'] = 'month'
        conn.execute('UPDATE sources SET columns_json=? WHERE id=?', (json.dumps(columns), sid))


def test_accept_publishes_a_profiled_bucket_start(bucketed_source, blueprint_flow):
    """24.2 live path: blueprint/accept hands layout the connected sources' stored profiles, so the
    published spec and recipe carry a base DATE column's grain (staged API, FakeBigQuery)."""
    from dss.spec.models import DashboardSpec
    client, app, bid, folder, bq, run_id = blueprint_flow
    spec = DashboardSpec.model_validate_json((folder / 'spec.json').read_text(encoding='utf-8'))
    assert {f.name: f.date_granularity for f in spec.datasource.fields if f.date_granularity} == {'order_date': 'month'}
    assert client.post(f'/api/builds/{bid}/recipe').status_code == 200
    ops = lines((folder / 'recipe.jsonl').read_text(encoding='utf-8'))[1:]
    assert [(o['date_dimension'], o['options']) for o in ops if o['op'] == 'add_chart' and o['chart_type'] == 'time_series'] == [
        ('order_date', {'date_granularity': 'month'})]


def validate_all(text):
    header, *ops = lines(text)
    Draft202012Validator({**SCHEMA, '$ref': '#/$defs/header'}).validate(header)
    for value in ops:
        Draft202012Validator({**SCHEMA, '$ref': '#/$defs/op'}).validate(value)
    return ops


def test_recipe_13_types_compile_to_their_ops():
    """24.1: release 2.6's urban/rural area, rural/urban split bar and region checkbox list compile as
    Data Studio's area chart, 100% stacked bar and fixed-size list instead of stand-ins."""
    spec = recipe_13_spec()
    ops = validate_all(compile_recipe(spec, 3))
    by_id = {o['component_id']: o for o in ops if o['op'] in ('add_chart', 'add_control')}
    area, split, listed = by_id['p1_access_over_time'], by_id['p1_split'], by_id['p1_regions']
    assert (area['op'], area['chart_type'], area['date_dimension'], area['dimensions'], area['options']) == (
        'add_chart', 'area', 'sale_date', [], {'stacked_percent': True})
    assert area['metrics'] == [{'field': 'urban', 'agg': 'sum'}, {'field': 'rural', 'agg': 'sum'}]
    assert (split['chart_type'], split['options']) == ('bar', {'stacked_percent': True})
    page = spec.pages[0]
    box_of = {c.id: box(spec.canvas, spec.grid, c.grid, height=page.height) for c in page.components}
    assert listed == {'id': listed['id'], 'op': 'add_control', 'component_id': 'p1_regions', 'control_type': 'fixed_size_list',
                      'field': 'region', **box_of['p1_regions']}
    # Areas take the palette like any series chart; a control takes no style.
    assert {o['component_id'] for o in ops if o['op'] == 'set_style'} == {'p1_access_over_time', 'p1_split'}
    assert compile_recipe(recipe_13_spec(), 3) == compile_recipe(spec, 3)


@pytest.mark.parametrize('grain', ['day', 'week', 'month', 'quarter', 'year'])
def test_area_on_a_bucket_gets_the_time_series_grain(grain):
    """One date-grain rule: an area on a DATE_TRUNC bucket draws one point per bucket like a time series."""
    from dss.spec.auto_layout import bucket_grain
    spec = recipe_13_spec(bucket=bucket_grain(f'DATE_TRUNC(sale_date, {grain.upper()})'))
    ops = validate_all(compile_recipe(spec, 3))
    area = next(o for o in ops if o.get('chart_type') == 'area')
    assert (area['date_dimension'], area['options']) == (f'sale_{grain}', {'stacked_percent': True, 'date_granularity': grain})
    # A model-written grain never reaches the recipe: code overwrites it on a bucket and drops it on a raw date.
    spec.pages[0].components[0].options['date_granularity'] = 'day' if grain != 'day' else 'year'
    assert charts(spec)['p1_access_over_time']['options'] == {'stacked_percent': True, 'date_granularity': grain}
    raw = recipe_13_spec(area_options={'stacked': True, 'date_granularity': 'month'})
    assert charts(raw)['p1_access_over_time']['options'] == {'stacked': True}
    assert all('date_granularity' not in o['options'] for o in charts(spec).values() if o['chart_type'] != 'area')


def test_blueprint_rows_use_recipe_13_types(monkeypatch):
    """The planner sees the new types; a Blueprint row has no field slot, so a fixed-size list's one
    dimension becomes its field (like a dropdown's) in feasibility, layout and publish coverage ops."""
    from dss.artifacts.models import BlueprintRow
    from dss.harness.nodes.blueprint import catalog_summary
    from dss.spec import feasibility, requirements as req
    from dss.spec.capabilities import Checker, load_registry
    from dss.spec.models import TYPES
    monkeypatch.setenv('DSS_ALLOWED_TYPES', ','.join(TYPES))
    summary = {entry['type']: entry for entry in catalog_summary()}
    assert (summary['fixed_size_list']['min_dimensions'], summary['fixed_size_list']['max_dimensions']) == (1, 1)
    assert 'field' not in summary['fixed_size_list']['slot_roles']
    assert [o['key'] for o in summary['area']['options']] == ['stacked', 'stacked_percent', 'date_granularity']
    assert 'stacked_percent' in [o['key'] for o in summary['bar']['options']]
    fields = {'region': {'role': 'dimension', 'type': 'STRING'}, 'sale_date': {'role': 'dimension', 'type': 'DATE'},
              'urban': {'role': 'metric', 'type': 'FLOAT64'}, 'rural': {'role': 'metric', 'type': 'FLOAT64'}}
    metrics = [{'field': 'urban', 'agg': 'sum'}, {'field': 'rural', 'agg': 'sum'}]
    def row(**component):
        base = {'label': 'X', 'dimensions': [], 'metrics': [], 'date_dimension': None, 'breakdown': None, 'sort': None, 'options': {}}
        return BlueprintRow(question_id=None, section_id='s1', page=1, note='', status='ok', issue_ids=[], component={**base, **component})
    rows = [row(type='fixed_size_list', dimensions=['region']),
            row(type='area', date_dimension='sale_date', metrics=metrics, options={'stacked_percent': True}),
            row(type='bar', dimensions=['region'], metrics=metrics, options={'stacked_percent': True})]
    checker = Checker(load_registry(), allowed=TYPES)
    assert [feasibility.component_errors(r.component, fields, checker) for r in rows] == [[], [], []]
    assert feasibility.component_errors(row(type='fixed_size_list').component, fields, checker) == [
        ('needs_data', 'A fixed_size_list needs one dimension field', [])]
    assert feasibility.component_errors(row(type='area', metrics=metrics).component, fields, checker) == [
        ('needs_data', 'A date dimension is required', [])]
    laid = feasibility.laid_out(rows)
    assert (laid[0]['field'], laid[0]['dimensions']) == ('region', [])
    assert {'op': 'add_control', 'component_id': 'row_0', 'control_type': 'fixed_size_list', 'field': 'region'} in req._row_ops(laid[0], ['#123456'])
    area = next(o for o in req._row_ops(laid[1], ['#123456']) if o['op'] == 'add_chart')
    assert (area['chart_type'], area['date_dimension'], area['options']) == ('area', 'sale_date', {'stacked_percent': True})


# sha256 of compile_recipe for specs without recipe 1.3 types, recorded with the pre-24.1 compiler.
RECIPE_12_BYTES = {
    'golden_spec': '6356b8c82948c8c40ee216638417f906fce8f756aeb782ff81104f0fa69e290f',
    'designed_spec': '02e3442501edf71168b8205f8af6411e7295580f531e20b84b53088a55fb73fb',
    'golden_layout_spec': 'b05f0312346e294ee99cbe23fd3902866bd6e94af62323e716610fb6a0b49467',
    'thin_spec': '10389be7565932392da471bf033244845519c147a2e71f3c582b631fb3eb5270',
    'three_pages': 'd3ca7e5862c483336fc62971406015478bc59f807350f78c8bcfad30e9170927',
    'bucket_month': 'af975e6f728929dae4956981e53edf7d4236d46af8aa62950a8aee85f824ef7b'}


def test_specs_without_recipe_13_types_compile_byte_identically():
    from hashlib import sha256
    from dss.spec.models import DashboardSpec
    specs = {name: (DashboardSpec.model_validate_json(Path(f'tests/data/{name}.json').read_text(encoding='utf-8')), 3)
             for name in ('golden_spec', 'designed_spec', 'golden_layout_spec', 'thin_spec')}
    specs.update(three_pages=(three_pages(), 2), bucket_month=(bucket_spec('month'), 3))
    assert {name: sha256(compile_recipe(spec, v).encode()).hexdigest() for name, (spec, v) in specs.items()} == RECIPE_12_BYTES
    assert compile_recipe(golden_spec(), 3).encode('utf-8') == Path('tests/data/golden_recipe.jsonl').read_bytes()
