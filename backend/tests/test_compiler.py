"""Recipe compiler on multi-page specs: one add_page + set_canvas + set_background_image per extra page."""
import json
from pathlib import Path

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


def test_synthetic_label_is_emitted_once_on_page_one():
    spec = with_synthetic_label(three_pages(), True)
    ops = lines(compile_recipe(spec, 1))[1:]
    labels = [o for o in ops if o.get('component_id') == SYNTHETIC_LABEL_ID]
    assert len(labels) == 1 and labels[0]['op'] == 'add_text'
    assert ops.index(labels[0]) < next(i for i, o in enumerate(ops) if o['op'] == 'add_page')
