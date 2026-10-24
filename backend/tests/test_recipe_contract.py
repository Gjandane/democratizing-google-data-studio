"""Compiler oracle and HTTP contract, entirely offline."""
import json
from pathlib import Path
import random
import subprocess

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
import pytest

from dss.config import Config
from dss.db import now
from dss.harness.guardrails import RunError
from dss.harness.nodes.compile import perform
from dss.main import create_app
from dss.recipe.compiler import compile_recipe, preview, print_line
from dss.render.prototype import aggregate_sql
from dss.spec.models import DashboardSpec, Sort, TYPES as ALL_TYPES
from dss.spec.validate import validate_spec
from fakes import fake_models

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT.parent / 'contracts/recipe.schema.json').read_text(encoding='utf-8'))
GOLDEN = ROOT / 'tests/data/golden_recipe.jsonl'
# Recorded from the engine's own `dsengine print`, not from this backend's formatter.
RECORDED = json.loads((ROOT / 'tests/data/recipe_preview.json').read_text(encoding='utf-8'))
# golden_spec.json holds one component per recipe 1.2 type; 1.3's area and fixed_size_list are
# exercised by test_render.recipe_13_spec, so the golden recipe keeps its bytes (24.1).
TYPES = tuple(t for t in ALL_TYPES if t not in ('area', 'fixed_size_list'))


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
    assert [op['op'] for op in ops[:4]] == ['open_report', 'rename_page', 'set_canvas', 'set_background_image']
    assert ops[1]['name'] == spec.pages[0].name
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
                    value = getattr(c, key)
                    assert op[key] == (value.model_dump() if key == 'sort' else value)
        elif c.type == 'text':
            assert op['op'] == 'add_text' and op['text'] == c.text
        elif c.type == 'image':
            assert op['op'] == 'add_image' and op['path'] == 'images/logo.png'
        else:
            assert op['op'] == 'add_control' and op['control_type'] == c.type
            assert op.get('field') == c.field
    styles = [op for op in ops if op['op'] == 'set_style']
    # Scorecards have no series swatch, so the engine would skip `colors` with a warning.
    assert [op['component_id'] for op in styles] == ['p1_' + kind for kind in TYPES[:8] if kind != 'scorecard']
    assert all(op['style'] == {'colors': spec.theme.palette} for op in styles)
    assert all(ops[ops.index(op) - 1]['component_id'] == op['component_id'] for op in styles)
    assert not any(op.get('component_id') == 'p1_title' for op in ops)


@pytest.mark.parametrize('kind', ['bar', 'table', 'time_series'])
@pytest.mark.parametrize('order', ['asc', 'desc'])
def test_sort_order_matches_prototype_sql(spec, kind, order):
    c = next(c for c in spec.pages[0].components if c.type == kind)
    grouping = c.date_dimension or c.dimensions[0]
    metric = 'm' + str([m.field for m in c.metrics].index('revenue'))
    for field, alias in (('revenue', metric), (grouping, grouping)):
        c.sort = Sort(field=field, order=order)
        assert not validate_spec(spec, allowed=TYPES)
        op = next(op for op in validate_lines(compile_recipe(spec, 3))[1:]
                  if op['op'] == 'add_chart' and op['component_id'] == c.id)
        assert op['sort'] == {'field': field, 'order': order}
        assert f'ORDER BY `{alias}` {order.upper()} LIMIT' in aggregate_sql(spec, c)


def test_absent_sort_is_omitted_and_keeps_defaults(spec):
    table = next(c for c in spec.pages[0].components if c.type == 'table')
    assert table.sort is None
    op = next(op for op in validate_lines(compile_recipe(spec, 3))[1:]
              if op['op'] == 'add_chart' and op['component_id'] == table.id)
    assert 'sort' not in op
    assert aggregate_sql(spec, table).endswith('ORDER BY `m0` DESC LIMIT 20')


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
    assert [op['op'] for op in ops].count('rename_page') == 1 and ops[1]['name'] == 'Overview'
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


@pytest.mark.parametrize('field', ['background', 'surface', 'text', 'muted', 'accent', 'palette'])
@pytest.mark.parametrize('color', ['123456', '#abc', '#GG1234'])
def test_compiler_refuses_mutated_theme_preserving_recipe(spec, tmp_path, field, color):
    perform(spec, 3, tmp_path)
    previous = (tmp_path / 'recipe.jsonl').read_bytes()
    if field == 'palette':
        spec.theme.palette[0] = color
    else:
        setattr(spec.theme, field, color)
    with pytest.raises(ValueError):
        compile_recipe(spec, 3)
    with pytest.raises(RunError) as error:
        perform(spec, 3, tmp_path)
    assert error.value.code == 'invalid_recipe'
    assert (tmp_path / 'recipe.jsonl').read_bytes() == previous
    assert not (tmp_path / 'recipe.jsonl.tmp').exists()


@pytest.mark.parametrize('corruption', ['header', 'text', 'geometry', 'dimension'])
def test_compiler_checks_emitted_recipe_contract(spec, tmp_path, corruption):
    perform(spec, 3, tmp_path)
    previous = (tmp_path / 'recipe.jsonl').read_bytes()
    version = 3
    if corruption == 'header':
        version = 0
    elif corruption == 'text':
        next(c for c in spec.pages[0].components if c.type == 'text').text = None
        next(c for c in spec.pages[0].components if c.type == 'text').label = ''
    elif corruption == 'geometry':
        spec.canvas.width = 0
    else:
        next(c for c in spec.pages[0].components if c.type == 'bar').dimensions = ['']
    with pytest.raises(RunError) as error:
        perform(spec, version, tmp_path)
    assert error.value.code == 'invalid_recipe'
    assert (tmp_path / 'recipe.jsonl').read_bytes() == previous
    assert not (tmp_path / 'recipe.jsonl.tmp').exists()


@pytest.mark.parametrize('count', [993, 994])  # 19.2: rename_page takes one id
def test_op_id_capacity(spec, count):
    note = next(c for c in spec.pages[0].components if c.type == 'text')
    spec.pages[0].components = [note.model_copy(update={'id': f'p1_note_{i}'}) for i in range(count)]
    if count == 994:
        with pytest.raises(ValueError, match='three-digit op id capacity'):
            compile_recipe(spec, 3)
    else:
        ops = [json.loads(line) for line in compile_recipe(spec, 3).splitlines()[1:]]
        assert ops[-1]['id'] == 's999'


@pytest.fixture
def no_engine(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('recipe preview invoked a process')
    monkeypatch.setenv('DSS_ENGINE_CMD', str(ROOT / 'missing-dsengine'))
    for name in ('run', 'Popen', 'check_output'):
        monkeypatch.setattr(subprocess, name, refuse)


@pytest.fixture
def agent_client(tmp_path, no_engine):
    """Hosted agent mode: no installed engine and no agent heartbeat."""
    app = create_app(Config(data_dir=tmp_path, engine_mode='agent', agent_token='t' * 24), model_lister=fake_models)
    with TestClient(app) as client:
        with app.state.db.connect() as conn:
            conn.execute("INSERT INTO builds(id,title,archetype,mode,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                         ('b_123456789abc', 'Golden', 'executive', 'data', 'prototype', now(), now()))
        folder = tmp_path / 'builds' / 'b_123456789abc' / 'v1'
        folder.mkdir(parents=True)
        assert not app.state.agent_jobs.connected
        yield client, app, folder


def test_preview_matches_recorded_engine_print():
    golden = preview(GOLDEN.read_bytes().decode('utf-8'))
    assert [op['op_id'] for op in golden] == [f's{i:03d}' for i in range(1, 26)]
    assert [op['line'] for op in golden] == RECORDED['golden']['lines']
    # Quoting, nulls, renamed and repeated flags, non-ASCII and U+2028 inside one line.
    header, *ops = RECORDED['edge']['recipe']
    assert [print_line(op) for op in ops] == RECORDED['edge']['lines']
    text = ''.join(json.dumps(line, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n'
                   for line in RECORDED['edge']['recipe'])
    assert [op['line'] for op in preview(text)] == RECORDED['edge']['lines']


@pytest.mark.parametrize('value', [True, 1.5, [1], [{'field': 'x'}]])
def test_preview_rejects_unrecorded_argument_forms(value):
    with pytest.raises(ValueError):
        print_line({'id': 's001', 'op': 'add_text', 'bold': value})


def test_recipe_api_uses_current_spec(agent_client, spec):
    client, app, folder = agent_client
    (folder / 'spec.json').write_text(spec.model_dump_json(), encoding='utf-8')
    from fakes import ready_fixture
    ready_fixture(app, spec.build_id, folder)
    for _ in range(2):
        response = client.post('/api/builds/b_123456789abc/recipe')
        assert response.status_code == 200, response.text
        result = response.json()
        recipe_bytes = (folder / 'recipe.jsonl').read_bytes()
        assert recipe_bytes == compile_recipe(spec, 1).encode('utf-8')
        header, *ops = validate_lines(recipe_bytes.decode('utf-8'))
        assert header['datasource']['project_id'] == 'public-source'
        assert header['report_name'] == spec.title and header['version'] == 1
        assert result == {'op_count': 25, 'ops': [
            {'op_id': f's{i:03d}', 'line': line} for i, line in enumerate(RECORDED['golden']['lines'], 1)]}
        assert {op['op'] for op in ops} >= {'add_chart', 'add_text', 'add_image', 'add_control'}
    assert GOLDEN.read_bytes() == compile_recipe(spec, 3).encode('utf-8')
    with app.state.db.connect() as conn:
        traces = conn.execute('SELECT node,status FROM traces WHERE build_id=?', ('b_123456789abc',)).fetchall()
        assert [tuple(row) for row in traces] == [('recipe', 'ok'), ('recipe', 'ok')]
    assert not app.state.agent_jobs.jobs and not app.state.agent_jobs.queue


@pytest.mark.parametrize('failure', ['compile', 'preview', 'sort', 'direction'])
def test_recipe_api_failure_publishes_nothing(agent_client, spec, failure, monkeypatch):
    client, app, folder = agent_client
    previous = b'previous complete recipe\n'
    (folder / 'recipe.jsonl').write_bytes(previous)
    # Start with an authorized prototype, then inject the compiler/preview failure.
    (folder / 'spec.json').write_text(spec.model_dump_json(), encoding='utf-8')
    from fakes import ready_fixture
    ready_fixture(app, spec.build_id, folder)
    if failure in ('sort', 'direction'):
        # A spec.json that bypassed the validator: a malformed order or a legacy direction key.
        document = json.loads(spec.model_dump_json())
        bar = next(c for c in document['pages'][0]['components'] if c['type'] == 'bar')
        bar['sort'] = {'field': 'revenue', 'order': 'up'} if failure == 'sort' else {'field': 'revenue', 'direction': 'asc'}
        (folder / 'spec.json').write_text(json.dumps(document), encoding='utf-8')
    elif failure == 'compile':
        next(c for c in spec.pages[0].components if c.type == 'image').image_path = None
    else:
        from dss.api import run
        def broken(text):
            raise KeyError('C:/secret/raw-detail')
        monkeypatch.setattr(run, 'preview', broken)
    if failure not in ('sort', 'direction'):
        (folder / 'spec.json').write_text(spec.model_dump_json(), encoding='utf-8')
    response = client.post('/api/builds/b_123456789abc/recipe')
    expected = 'feasibility_blocked' if failure == 'compile' else 'invalid_recipe'
    assert response.status_code == (409 if failure == 'compile' else 422)
    assert response.json()['error']['code'] == expected
    assert 'secret' not in response.text and 'Traceback' not in response.text
    assert (folder / 'recipe.jsonl').read_bytes() == previous
    assert not (folder / 'recipe.jsonl.tmp').exists()
    with app.state.db.connect() as conn:
        assert [tuple(row) for row in conn.execute('SELECT node,status FROM traces')] == ([('recipe', 'error')] if failure == 'preview' else [])
