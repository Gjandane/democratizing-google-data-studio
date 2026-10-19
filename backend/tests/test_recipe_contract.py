"""Compiler oracle and HTTP contract, entirely offline."""
import json
from pathlib import Path
import random
import sys

from jsonschema import Draft202012Validator
import pytest

from dss.harness.guardrails import RunError
from dss.harness.nodes.compile import perform
from dss.recipe.compiler import compile_recipe
from dss.spec.models import DashboardSpec, TYPES
from dss.spec.validate import validate_spec

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT.parent / 'contracts/recipe.schema.json').read_text(encoding='utf-8'))
GOLDEN = ROOT / 'tests/data/golden_recipe.jsonl'


@pytest.fixture
def spec():
    return DashboardSpec.model_validate_json((ROOT / 'tests/data/golden_spec.json').read_text(encoding='utf-8'))


def validate_lines(text):
    assert text.endswith('\n') and '\r' not in text
    lines = [json.loads(line) for line in text.splitlines()]
    for i, line in enumerate(lines):
        ref = '#/$defs/op' if i else '#/$defs/header'
        Draft202012Validator({**SCHEMA, '$ref': ref}).validate(line)
    assert [op['id'] for op in lines[1:]] == [f's{i:03d}' for i in range(1, len(lines))]
    return lines


def test_golden_contract_and_bytes(spec, tmp_path):
    assert not validate_spec(spec, allowed=TYPES)
    before = spec.model_dump_json()
    expected = GOLDEN.read_bytes()
    for _ in range(2):
        text = perform(spec, 3, tmp_path)
        assert text.encode('utf-8') == expected
        assert (tmp_path / 'recipe.jsonl').read_bytes() == expected
        validate_lines(text)
    assert spec.model_dump_json() == before
    assert not (tmp_path / 'recipe.jsonl.tmp').exists()


def test_all_types_arguments_and_order(spec):
    lines = validate_lines(compile_recipe(spec, 3))
    header, *ops = lines
    assert header['version'] == 3  # Build version, not spec_version (7).
    assert header['datasource'] == dict(connector='bigQuery', project_id='public-source',
                                      dataset_id='analytics', table_id='sales_view_v3')
    assert [op['op'] for op in ops[:3]] == ['open_report', 'set_canvas', 'set_background_image']
    assert [op['op'] for op in ops[-2:]] == ['save_report', 'get_link']
    creations = [op for op in ops if op['op'].startswith('add_')]
    assert len(creations) == 12
    assert [op['component_id'] for op in creations] == ['p1_' + kind for kind in TYPES]
    by_id = {c.id: c for c in spec.pages[0].components}
    for op in creations:
        c = by_id[op['component_id']]
        if c.type in TYPES[:8]:
            assert op['op'] == 'add_chart' and op['chart_type'] == c.type
            assert op['dimensions'] == c.dimensions
            assert op['metrics'] == [metric.model_dump() for metric in c.metrics]
            assert op['options'] == c.options
            assert op['title'] == c.label
            for key in ('date_dimension', 'breakdown', 'sort'):
                if getattr(c, key) is None:
                    assert key not in op
                else:
                    assert op[key] == getattr(c, key)
        elif c.type == 'text':
            assert op['op'] == 'add_text' and op['text'] == c.text
        elif c.type == 'image':
            assert op['op'] == 'add_image' and op['path'] == 'images/logo.png'
        else:
            assert op['op'] == 'add_control' and op['control_type'] == c.type
            assert op.get('field') == c.field
    styles = [op for op in ops if op['op'] == 'set_style']
    assert [op['component_id'] for op in styles] == ['p1_' + kind for kind in TYPES[:8]]
    assert all(op['style'] == {'colors': spec.theme.palette} for op in styles)
    assert all(ops[ops.index(op) - 1]['component_id'] == op['component_id'] for op in styles)
    assert not any(op.get('component_id') == 'p1_title' for op in ops)


def test_reading_order_is_independent_of_input_order(spec):
    expected = GOLDEN.read_bytes()
    rng = random.Random(43)
    for _ in range(10):
        rng.shuffle(spec.pages[0].components)
        assert compile_recipe(spec, 3).encode('utf-8') == expected


def test_extra_page_op_order(spec):
    # The POC validator permits one page; exercise the compiler's specified future-page branch.
    page = spec.pages[0].model_copy(update={'index': 2, 'name': 'Details', 'height': 700,
                                           'components': [], 'decorations': []})
    spec.pages.append(page)
    ops = validate_lines(compile_recipe(spec, 3))[1:]
    assert [{k: v for k, v in op.items() if k != 'id'} for op in ops[-5:]] == [
        {'op': 'add_page', 'name': 'Details'},
        {'op': 'set_canvas', 'width': 1200, 'height': 700},
        {'op': 'set_background_image', 'path': 'background_p2.png', 'x': 0, 'y': 0, 'w': 1200, 'h': 700},
        {'op': 'save_report'}, {'op': 'get_link'}]


def test_text_fallback_and_missing_image_preserves_recipe(spec, tmp_path):
    note = next(c for c in spec.pages[0].components if c.type == 'text')
    note.text = None
    ops = validate_lines(compile_recipe(spec, 3))[1:]
    assert next(op for op in ops if op['op'] == 'add_text')['text'] == note.label
    perform(spec, 3, tmp_path)
    previous = (tmp_path / 'recipe.jsonl').read_bytes()
    next(c for c in spec.pages[0].components if c.type == 'image').image_path = None
    with pytest.raises(RunError) as error:
        perform(spec, 3, tmp_path)
    assert error.value.code == 'invalid_recipe'
    assert (tmp_path / 'recipe.jsonl').read_bytes() == previous


@pytest.mark.parametrize('count', [994, 995])
def test_op_id_capacity(spec, count):
    note = next(c for c in spec.pages[0].components if c.type == 'text')
    spec.pages[0].components = [note.model_copy(update={'id': f'p1_note_{i}'}) for i in range(count)]
    if count == 995:
        with pytest.raises(ValueError, match='three-digit op id capacity'):
            compile_recipe(spec, 3)
    else:
        ops = [json.loads(line) for line in compile_recipe(spec, 3).splitlines()[1:]]
        assert ops[-1]['id'] == 's999'


def test_recipe_api_uses_current_spec(client, app, build_id, spec, monkeypatch):
    monkeypatch.setenv('DSS_ENGINE_CMD', f'"{sys.executable}" "{ROOT / "tests/fake_engine.py"}"')
    folder = app.state.settings.get().data_dir / 'builds' / build_id / 'v1'
    folder.mkdir(parents=True)
    (folder / 'spec.json').write_text(spec.model_dump_json(), encoding='utf-8')
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='prototype' WHERE id=?", (build_id,))
    for _ in range(2):
        response = client.post(f'/api/builds/{build_id}/recipe')
        assert response.status_code == 200, response.text
        result = response.json()
        recipe_bytes = (folder / 'recipe.jsonl').read_bytes()
        assert recipe_bytes == compile_recipe(spec, 1).encode('utf-8')
        header, *ops = validate_lines(recipe_bytes.decode('utf-8'))
        assert header['datasource']['project_id'] == 'public-source'
        assert header['report_name'] == spec.title and header['version'] == 1
        assert result == {'op_count': len(ops), 'ops': [
            {'op_id': op['id'], 'line': 'dsengine ' + op['op'].replace('_', '-')} for op in ops]}
    with app.state.db.connect() as conn:
        traces = conn.execute('SELECT node,status FROM traces WHERE build_id=?', (build_id,)).fetchall()
        assert [tuple(row) for row in traces] == [('recipe', 'ok'), ('recipe', 'ok')]
