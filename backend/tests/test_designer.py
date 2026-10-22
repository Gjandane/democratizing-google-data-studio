"""Designer node (architecture.md#Designed pages): page 1 first, pages 2-n in parallel, one repair
per page, per-page and page-1 fallback, the planner model, and no model call after the prototype
action. FakeLLM only; slots are measured in real Chromium."""
import asyncio
from html import escape
import json

from google.adk.models.llm_response import LlmResponse
from google.genai import types
import pytest

from dss.harness.context import PAGE_HEADER, SEPARATOR
from dss.harness.nodes import designer
from dss.harness.nodes.designer import ALL_FALLBACK, FOOTER
from dss.render import background
from dss.spec.layout import with_synthetic_label
from dss.spec.models import SYNTHETIC_LABEL_ID, DashboardSpec
from dss.spec.validate import validate_spec
from fakes import FakeLLM
from test_blueprint import blueprint_api  # noqa: F401  (fixture)
from test_context_node import context_api  # noqa: F401  (fixture)
from test_render import three_pages

CSS = ('<style>body{padding:24px;font-family:Arial;background:#F1F5F9}.card{background:#FFFFFF;'
       'border-radius:12px;padding:16px;margin-bottom:16px}.card h2{margin:0 0 12px;font-size:16px;'
       'line-height:20px}.head h1{margin:0 0 16px;font-size:24px;line-height:30px}</style>')


def page_html(page):
    """A valid page for the request's components: a header, then one titled card per slot."""
    cards = ''.join(f'<section class="card"><h2>{escape(c["label"])}</h2>'
                    f'<div data-slot="{c["id"]}" style="height:{c["min_h"]}px"></div></section>'
                    for c in page['components'])
    return f'<header class="head"><h1>{escape(page["name"])}</h1></header>{cards}'


class DesignerLLM(FakeLLM):
    """Answers per page and attempt from `plan` (ok, bad = no slots, json = not JSON, empty, cut). Page 1
    answers at 1440 px with the stylesheet; later pages reuse it. With `gate`, a later page waits
    until that many later pages are in flight, so `peak` shows whether they ran in parallel."""
    model: str = 'gemini-4-argon'
    plan: dict = {}
    seen: list = []
    configs: list = []
    gate: int = 0
    waiting: int = 0
    peak: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        instruction = str(llm_request.config.system_instruction)
        page = json.loads(instruction.split(PAGE_HEADER + '\n', 1)[1].split(SEPARATOR, 1)[0])
        attempt = sum(index == page['index'] for index, _ in self.seen)
        self.seen.append((page['index'], instruction))
        self.configs.append(llm_request.config)
        if page['index'] > 1 and self.gate:
            self.waiting += 1
            self.peak = max(self.peak, self.waiting)
            for _ in range(300):
                if self.waiting >= self.gate:
                    break
                await asyncio.sleep(.01)
        behaviour = self.plan.get(page['index'], ['ok', 'ok'])[attempt]
        if behaviour == 'cut':  # thinking used the whole output budget: ADK's MAX_TOKENS error
            self.calls += 1
            yield LlmResponse(error_code='MAX_TOKENS', finish_reason=types.FinishReason.MAX_TOKENS,
                              usage_metadata=types.GenerateContentResponseUsageMetadata(
                                  prompt_token_count=5, candidates_token_count=16000))
            return
        answer = {'html': CSS + page_html(page) if page['index'] == 1 else page_html(page)}
        if behaviour == 'bad':
            answer['html'] = '<p class="x">No slots here</p>'
        if page['index'] == 1:
            answer['canvas_width'] = 1440
        self.response = {'json': '{"html": ', 'empty': ''}.get(behaviour, json.dumps(answer))
        async for response in super().generate_content_async(llm_request, stream):
            yield response


class Trace:
    def __init__(self):
        self.spans, self.model, self.input_tokens, self.output_tokens = [], None, 0, 0

    def span(self, node):
        self.spans.append({'node': node})


def nodes(trace, page=None):
    return [s['node'] for s in trace.spans if page is None or s.get('page') == page]


async def test_page_one_first_then_later_pages_in_parallel_with_its_width_and_css():
    spec, llm, trace = three_pages(), DesignerLLM(gate=2), Trace()
    designed, notes = await designer.design(spec, lambda: llm, trace)
    assert notes == [] and validate_spec(designed) == []
    assert [index for index, _ in llm.seen][0] == 1 and llm.calls == 3 and llm.peak == 2
    assert designed.canvas.width == 1440 and designed.canvas.height == designed.pages[0].height
    for page in designed.pages:
        assert page.design.source == 'designer' and page.design.model == 'gemini-4-argon'
        assert [d.id for d in page.decorations] == [f'p{page.index}_design']
        assert all(c.box is not None for c in page.components)
        assert f'dss-design-p{page.index}' in page.design.html  # stored sanitized for its page
    shared = designer.readable(designer.STYLE.match(designed.pages[0].design.html).group(1))
    for index, instruction in llm.seen[1:]:
        assert '"canvas_width":1440' in instruction and shared in instruction and 'border-radius:12px' in shared
        # Code puts page 1's stylesheet before the later page's markup.
        assert 'border-radius:12px' in designed.pages[index - 1].design.html
    assert nodes(trace, 1) == ['designer', 'validate'] and trace.model == 'gemini-4-argon'
    assert trace.input_tokens == 15 and trace.output_tokens == 6  # FakeLLM usage, three calls
    assert spec.canvas.width == 1200 and all(p.design is None for p in spec.pages)  # input untouched


async def test_invalid_page_then_valid_repair_passes():
    spec, llm, trace = three_pages(), DesignerLLM(plan={2: ['json', 'ok'], 3: ['bad', 'ok']}), Trace()
    designed, notes = await designer.design(spec, lambda: llm, trace)
    assert notes == [] and llm.calls == 5 and all(p.design for p in designed.pages)
    repairs = [instruction for index, instruction in llm.seen if 'Your previous answer failed' in instruction]
    assert len(repairs) == 2 and any('has no slot' in r for r in repairs) and any('answer' in r for r in repairs)
    assert nodes(trace, 3) == ['designer', 'validate', 'designer', 'validate']
    assert 'designer_fallback' not in nodes(trace)


async def test_two_invalid_answers_fall_back_for_that_page_only():
    spec, llm, trace = three_pages(), DesignerLLM(plan={3: ['bad', 'json']}), Trace()
    designed, notes = await designer.design(spec, lambda: llm, trace)
    assert notes == ['Page 3 uses the standard layout: its design did not pass its checks.']
    assert [p.design is not None for p in designed.pages] == [True, True, False]
    # The fallback page is the code layout and kit, unchanged (at page 1's canvas width).
    assert designed.pages[2].model_dump() == spec.pages[2].model_dump() and designed.canvas.width == 1440
    assert validate_spec(designed) == [] and llm.calls == 4
    assert {'node': 'designer_fallback', 'page': 3, 'reason': 'invalid', 'errors': 1} in trace.spans
    from dss.render.prototype import render
    from dss.recipe.compiler import compile_recipe
    assert 'dss-design-p3' not in render(designed) and compile_recipe(designed, 1)


async def test_page_one_double_failure_keeps_the_code_path_with_no_further_calls():
    spec, llm, trace = three_pages(), DesignerLLM(plan={1: ['bad', 'bad']}), Trace()
    result, notes = await designer.design(spec, lambda: llm, trace)
    assert result is spec and notes == [ALL_FALLBACK] and llm.calls == 2 and result.canvas.width == 1200
    assert nodes(trace) == ['designer', 'validate', 'designer', 'validate', 'designer_fallback']


async def test_over_budget_and_unavailable_models_fall_back_without_a_call():
    spec, llm, trace = three_pages(), DesignerLLM(), Trace()
    spec.pages[0].components[0].label = 'Revenue ' * 7000  # untrusted input alone exceeds 12k tokens
    result, notes = await designer.design(spec, lambda: llm, trace)
    assert result is spec and notes == [ALL_FALLBACK] and llm.calls == 0
    assert trace.spans[-1] == {'node': 'designer_fallback', 'page': 1, 'reason': 'over_budget', 'errors': 0}
    from dss.harness.guardrails import RunError
    def missing():
        raise RunError('llm_unavailable', 'Set the Google API key in Settings', 503)
    trace = Trace()
    result, notes = await designer.design(spec := three_pages(), missing, trace)
    assert result is spec and notes == [ALL_FALLBACK]
    assert trace.spans == [{'node': 'designer_fallback', 'page': 1, 'reason': 'model', 'errors': 0}]
    failing = FakeLLM(fail=True)
    result, notes = await designer.design(spec := three_pages(), lambda: failing, Trace())
    assert result is spec and failing.calls == 1  # a provider error is not repaired


async def test_synthetic_page_one_keeps_the_footer_below_the_design():
    spec = with_synthetic_label(three_pages(per_page=4), True)
    spec.pages = spec.pages[:1]
    assert validate_spec(spec) == []
    designed, notes = await designer.design(spec, lambda: DesignerLLM(), Trace())
    page = designed.pages[0]
    assert notes == [] and validate_spec(designed) == []
    assert [d.id for d in page.decorations] == ['p1_design', SYNTHETIC_LABEL_ID]
    footer = page.decorations[1].grid
    assert 24 + (footer.row - 1) * 20 + FOOTER + 24 == page.height
    assert max(c.box.y + c.box.h for c in page.components) <= page.height - FOOTER - 24


async def test_requests_use_the_strict_schema_low_thinking_and_the_output_budget():
    llm = DesignerLLM()
    await designer.design(three_pages(), lambda: llm, Trace())
    first, later = llm.configs[0], llm.configs[1]
    assert first.response_json_schema['required'] == ['canvas_width', 'html']
    assert first.response_json_schema['additionalProperties'] is False
    assert later.response_json_schema['required'] == ['html'] and 'canvas_width' not in later.response_json_schema['properties']
    assert later.response_json_schema['additionalProperties'] is False
    for config in llm.configs:
        assert config.thinking_config.thinking_level == types.ThinkingLevel.LOW
        assert config.max_output_tokens == 16000 and config.response_mime_type == 'application/json'


async def test_cut_off_or_empty_answers_get_the_repair_turn():
    for behaviour in ('cut', 'empty'):
        llm, trace = DesignerLLM(plan={1: [behaviour, 'ok']}), Trace()
        designed, notes = await designer.design(three_pages(), lambda: llm, trace)
        assert notes == [] and all(p.design for p in designed.pages) and llm.calls == 4, behaviour
        assert 'Your previous answer failed' in llm.seen[1][1] and 'designer_fallback' not in nodes(trace)


async def test_pages_with_requirement_bound_decorations_keep_their_kit():
    spec, llm, trace = three_pages(), DesignerLLM(), Trace()
    designed, notes = await designer.design(spec, lambda: llm, trace, keep={2})
    assert [p.design is not None for p in designed.pages] == [True, False, True] and llm.calls == 2
    assert designed.pages[1].model_dump() == spec.pages[1].model_dump()
    assert notes == ['Page 2 uses the standard layout: its design did not pass its checks.']
    llm = DesignerLLM()
    result, notes = await designer.design(spec, lambda: llm, Trace(), keep={1})
    assert result is spec and notes == [ALL_FALLBACK] and llm.calls == 0


def test_readable_html_names_vendored_icons_again():
    from dss.render import design_page
    name = next(iter(design_page.icons()))
    clean = design_page.sanitize(f'<div><i data-icon="{name}" class="k"></i><i data-icon="mine">'
                                 '<svg viewBox="0 0 2 2"><circle cx="1" cy="1" r="1"></circle></svg></i></div>', page=2)
    assert clean.count('<svg') == 2
    text = designer.readable(clean)
    # The vendored icon is its name again; the model's own drawing stays.
    assert f'<i data-icon="{name}" class="k"></i>' in text and text.count('<svg') == 1 and 'dss-design' not in text


async def test_regenerate_redesigns_only_the_named_page_from_its_previous_html():
    spec, _ = await designer.design(three_pages(), lambda: DesignerLLM(), Trace())
    comment = {'component_id': 'p2_design', 'text': 'Make the header darker'}
    llm, trace = DesignerLLM(), Trace()
    revised, failed = await designer.regenerate(spec, {2: [comment]}, lambda: llm, trace)
    assert failed == {} and llm.calls == 1 and [index for index, _ in llm.seen] == [2]
    instruction = llm.seen[0][1]
    assert 'Make the header darker' in instruction and 'Revise your previous design' in instruction
    assert 'border-radius:12px' in instruction and '"canvas_width":1440' in instruction  # previous html, fixed width
    assert llm.configs[0].response_json_schema['required'] == ['html']
    assert revised.pages[1].design.source == 'revise' and revised.pages[1].design.model == 'gemini-4-argon'
    assert revised.pages[0] == spec.pages[0] and revised.pages[2] == spec.pages[2] and validate_spec(revised) == []
    assert nodes(trace) == ['designer', 'validate'] and trace.model is None  # the reviser's trace keeps its model
    llm, trace = DesignerLLM(plan={2: ['bad', 'json']}), Trace()
    result, failed = await designer.regenerate(spec, {2: [comment]}, lambda: llm, trace)
    assert result is None and llm.calls == 2 and failed[2].reason == 'invalid' and failed[2].errors
    assert trace.spans[-1] == {'node': 'redesign_failed', 'page': 2, 'reason': 'invalid', 'errors': len(failed[2].errors)}


def test_designer_uses_the_planner_model(client, app):
    from dss.harness.llm import PLANNER_TIMEOUT_MS
    models = app.state.models
    assert models.model_for('designer') == models.planner_model == 'gemini-4-argon'
    assert models.timeout_ms('designer') == PLANNER_TIMEOUT_MS == 120_000
    assert models.llm_for('designer').model == 'gemini-4-argon'


def designed_flow(api, monkeypatch, model, *, enabled=True):
    """Design confirm -> blueprint (ratio choice) -> accept, with `model` as the designer."""
    from test_blueprint import choose, confirm
    from test_context_node import wait
    client, app, bid, sid, folder, bq, llm, value = api
    bq.create_view = lambda table, sql: None
    bq.delete_view = lambda table: True
    bq.aggregate = lambda sql: [{'region': 'West', 'product_category': 'A', 'm0': 10, 'm1': 2}]
    monkeypatch.setattr(background, 'capture', lambda html, path, width, height, scale=3: path.write_bytes(b'PNG'))
    if not enabled:
        monkeypatch.setattr(app.state.settings, 'defaults',
                            app.state.settings.defaults.model_copy(update={'designed_pages': False}))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: model if node == 'designer' else llm)
    confirm(client, app, bid)
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    ratio = next(i for i in assessment['issues'] if i['requirement'] == 'q2')
    assert choose(client, bid, assessment, ratio, 'numerator_denominator').status_code == 200
    accepted = client.post(f'/api/builds/{bid}/blueprint/accept')
    assert accepted.status_code == 202, accepted.text
    wait(app)
    return client, app, bid, folder, accepted.json()['run_id']


def run_record(app, run_id):
    with app.state.db.connect() as conn:
        trace = conn.execute('SELECT * FROM traces WHERE run_id=?', (run_id,)).fetchone()
        message = conn.execute("SELECT text FROM messages WHERE node='prototype' ORDER BY rowid DESC").fetchone()
    return trace, [s['node'] for s in json.loads(trace['spans_json'])], message['text']


def test_prototype_action_saves_designed_pages_and_later_actions_call_no_model(blueprint_api, monkeypatch):
    model = DesignerLLM()
    client, app, bid, folder, run_id = designed_flow(blueprint_api, monkeypatch, model)
    trace, spans, message = run_record(app, run_id)
    assert trace['status'] == 'ok' and message == 'Prototype is ready.' and trace['model'] == 'gemini-4-argon'
    assert spans == ['router', 'prototype', 'view', 'layout', 'designer', 'validate', 'designer', 'validate',
                     'render', 'publish', 'guardrail']
    spec = DashboardSpec.model_validate_json((folder / 'spec.json').read_text(encoding='utf-8'))
    assert spec.canvas.width == 1440 and all(p.design and p.design.model == 'gemini-4-argon' for p in spec.pages)
    assert model.calls == len(spec.pages) == 2
    calls, before = model.calls, (folder / 'spec.json').read_bytes()
    prototype = client.get(f'/api/builds/{bid}/prototype')
    assert prototype.status_code == 200 and 'dss-design-p2' in prototype.text
    recipe = client.post(f'/api/builds/{bid}/recipe')
    assert recipe.status_code == 200, recipe.text
    canvases = [o['line'] for o in recipe.json()['ops'] if 'canvas' in o['line'].split()[1]]
    assert len(canvases) == 2 and all('1440' in line for line in canvases), canvases
    assert client.post(f'/api/builds/{bid}/versions').status_code == 201
    assert (folder.parent / 'v2/spec.json').read_bytes() == before
    assert client.get(f'/api/builds/{bid}/prototype').status_code == 200
    assert model.calls == calls and (folder / 'spec.json').read_bytes() == before


@pytest.mark.parametrize('enabled', [False, True])
def test_off_and_page_one_fallback_save_the_code_laid_spec(blueprint_api, monkeypatch, enabled):
    laid = []
    real = designer.design
    async def recording(spec, *args, **kwargs):
        laid.append(spec.model_dump_json(indent=2))
        return await real(spec, *args, **kwargs)
    monkeypatch.setattr(designer, 'design', recording)
    model = DesignerLLM(plan={1: ['bad', 'json']})
    client, app, bid, folder, run_id = designed_flow(blueprint_api, monkeypatch, model, enabled=enabled)
    trace, spans, message = run_record(app, run_id)
    text = (folder / 'spec.json').read_text(encoding='utf-8')
    assert trace['status'] == 'ok' and '"design"' not in text and '"box"' not in text
    assert DashboardSpec.model_validate_json(text).canvas.width == 1200
    if enabled:
        # The fallback writes the code layout's spec byte for byte, so prototype and recipe match too.
        assert laid == [text] and model.calls == 2 and message == f'Prototype is ready. {ALL_FALLBACK}'
        assert spans[3:-3] == ['layout', 'designer', 'validate', 'designer', 'validate', 'designer_fallback']
    else:
        assert laid == [] and model.calls == 0 and message == 'Prototype is ready.'
        assert spans == ['router', 'prototype', 'view', 'layout', 'render', 'publish', 'guardrail']
