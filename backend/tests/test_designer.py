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
        if behaviour == 'art':  # a globe below the cards, clear of every slot
            answer['html'] += '<i class="globe" data-art="globe-americas" style="width:240px"></i>'
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


async def test_art_names_reach_the_designer_and_the_design_keeps_the_tag_code_draws():
    from dss.render import design_page
    from dss.render.prototype import render
    llm = DesignerLLM(plan={1: ['art']})
    designed, notes = await designer.design(three_pages(), lambda: llm, Trace())
    assert notes == [] and validate_spec(designed) == []
    assert 'Art names for <i data-art="name"></i>:\n' + ', '.join(design_page.art()) in llm.seen[0][1]
    assert len(design_page.art()) == 4
    tag = '<i class="globe" data-art="globe-americas" style="width:240px"></i>'
    # The stored design and the revise prompt carry the one tag; the prototype draws the vendored globe.
    html = designed.pages[0].design.html
    assert tag in html and '<svg' not in html and tag in designer.readable(html)
    assert design_page.art()['globe-americas'] in render(designed)


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


def designed_flow(api, monkeypatch, model, *, enabled=True, reference_models=None, drain=True):
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
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: (reference_models or {}).get(node) or (
        model if node == 'designer' else llm))
    confirm(client, app, bid)
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    ratio = next(i for i in assessment['issues'] if i['requirement'] == 'q2')
    assert choose(client, bid, assessment, ratio, 'numerator_denominator').status_code == 200
    accepted = client.post(f'/api/builds/{bid}/blueprint/accept')
    assert accepted.status_code == 202, accepted.text
    if drain:
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


class ReferenceHTMLLLM(DesignerLLM):
    """Counted HTML worker with controllable counting/generation and stream-close observation."""
    model: str = 'gemini-3.8-flash'
    fixed: int = 1000
    pause_count: float = 0
    pause_generate: float = 0
    requests: list = []
    counted: list = []
    order: list = []
    closed: int = 0
    active: int = 0
    active_peak: int = 0

    async def count_request_tokens(self, request):
        self.order.append('count')
        self.counted.append(request.model_copy(deep=True))
        await asyncio.sleep(self.pause_count)
        return self.fixed

    async def generate_content_async(self, request, stream=False):
        self.order.append('generate')
        self.requests.append(request.model_copy(deep=True))
        self.active += 1
        self.active_peak = max(self.active_peak, self.active)
        try:
            if self.started:
                self.started.set()
            if self.release:
                await self.release.wait()
            await asyncio.sleep(self.pause_generate)
            async for response in super().generate_content_async(request, stream):
                yield response
        finally:
            self.closed += 1
            self.active -= 1


def reference_plan(folder, spec, *, html=None, brief=None, mode='style', count=2):
    from test_reference_brief import BriefLLM, reference_set, unit_reports
    from dss.harness.nodes import reference_brief as rb
    reference_set(folder, mode, count)
    html, brief = html or ReferenceHTMLLLM(), brief or BriefLLM()
    return designer.ReferenceDesign(rb.reference(folder), unit_reports(spec), lambda: brief, lambda: html), brief, html


async def test_reference_pairs_use_exact_slots_images_and_measured_page_one(tmp_path):
    from test_reference_brief import attached, section, PAGE
    from dss.harness.context import COMPONENTS_HEADER
    from dss.spec import requirements as req
    spec, trace = three_pages(), Trace()
    ref, brief, html = reference_plan(tmp_path, spec, html=ReferenceHTMLLLM(gate=2, plan={3: ['bad', 'ok']}))
    before = spec.model_dump(mode='json')
    result, notes = await designer.design(spec, lambda: pytest.fail('ordinary designer called'), trace, reference=ref)
    assert notes == [] and all(p.design.model == html.model for p in result.pages)
    assert html.active_peak == 2 and [index for index, _ in html.seen] == [1, 2, 3, 3]
    assert len(brief.requests) == 3 and html.calls == 4
    sequence = [s['node'] for s in trace.spans if s.get('page') == 1]
    assert sequence == ['reference_brief', 'reference_html', 'validate']
    css = designer.readable(designer.STYLE.match(result.pages[0].design.html)[1])
    for request in brief.requests[1:]:
        memory = str(request.config.system_instruction)
        assert css in memory and '"canvas_width":1440' in memory
    for request in brief.requests + html.requests:
        assert attached(request)[1] == list(ref.reference.images)
        memory = str(request.config.system_instruction)
        assert ref.reference.instructions in memory and 'Navy land' in memory
        approved = json.loads(section(memory, COMPONENTS_HEADER))
        assert approved['assessment']['state'] == 'ready' and 'decisions' in approved
        assert request.config.thinking_config.thinking_level == types.ThinkingLevel.LOW
    for request in html.requests:
        memory = str(request.config.system_instruction)
        assert 'Validated visual brief' in memory and 'White card, radius 16 px' in memory
        assert request.config.max_output_tokens == 16000 and not request.config.tools
        if json.loads(section(memory, PAGE_HEADER))['index'] > 1:
            assert css in memory and '"canvas_width":1440' in memory
    for page in result.pages:
        for c, previous in zip(page.components, spec.pages[page.index - 1].components):
            assert c.model_dump(exclude={'box'}) == previous.model_dump(exclude={'box'})
    assert result.datasource == spec.datasource and spec.model_dump(mode='json') == before
    assert html.order.count('count') == html.order.count('generate') == 4
    assert all(s.get('enforced_input_bound', 0) <= 12000 for s in trace.spans)
    assert trace.input_tokens == 35 and trace.output_tokens == 14
    spans = json.dumps(trace.spans)
    assert all(value not in spans for value in (ref.reference.instructions, 'Navy land', 'White card, radius', 'data-slot='))
    assert all(s['model'] in (brief.model, html.model) and s['duration_ms'] >= 0
               for s in trace.spans if s['node'] in ('reference_brief', 'reference_html'))


@pytest.mark.parametrize('stage,behaviour,reason', [
    ('brief', 'cut', 'invalid'), ('brief', 'missing', 'invalid'), ('brief', 'secret', 'model'),
    ('html', 'cut', 'invalid'), ('html', 'bad', 'invalid'), ('html', 'empty', 'invalid'),
    ('html', 'budget', 'over_budget')])
async def test_reference_failures_keep_the_kit_or_old_design(tmp_path, stage, behaviour, reason):
    from test_reference_brief import BriefLLM
    spec = three_pages()
    spec.pages = spec.pages[:1]
    html = ReferenceHTMLLLM(fixed=9800) if behaviour == 'budget' else ReferenceHTMLLLM(
        plan={1: [behaviour, behaviour]} if stage == 'html' else {})
    brief = BriefLLM(plan=[behaviour] if stage == 'brief' else [])
    ref, _, _ = reference_plan(tmp_path, spec, html=html, brief=brief)
    trace = Trace()
    result, notes = await designer.design(spec, lambda: None, trace, reference=ref, secrets=('test-secret-key',))
    assert result is spec and notes == [ALL_FALLBACK]
    assert trace.spans[-1]['reason'] == reason
    assert len(html.requests) == (0 if stage == 'brief' or behaviour == 'budget' else 2)
    # The same failure on revise returns no replacement, so its caller can retain artifacts/comments.
    old, _ = await designer.design(spec, lambda: DesignerLLM(), Trace())
    html.requests.clear(); html.counted.clear(); html.seen.clear(); brief.requests.clear()
    result, failed = await designer.regenerate(old, {1: [{'component_id': 'p1_design', 'text': 'Darker'}]},
                                               lambda: None, Trace(), reference=ref, secrets=('test-secret-key',))
    assert result is None and failed[1].reason == reason


async def test_reference_html_repair_carries_all_context_and_refuses_instead_of_trimming(tmp_path):
    from dss.harness.context import reference_html_context, BUDGETS
    from dss.harness.guardrails import RunError
    from test_reference_brief import attached
    spec = three_pages(); spec.pages = spec.pages[:1]
    ref, brief, html = reference_plan(tmp_path, spec, html=ReferenceHTMLLLM(plan={1: ['cut', 'ok']}))
    result, notes = await designer.design(spec, lambda: None, Trace(), reference=ref)
    assert notes == [] and len(html.counted) == 2 and len(html.requests) == 2
    assert 'Your previous answer failed' in str(html.requests[1].config.system_instruction)
    assert all(attached(r)[1] == list(ref.reference.images) for r in html.counted)
    assert BUDGETS['reference_html'] == 12000
    # Each piece of a long repair/shared/previous request is mandatory, with an actual bound in the refusal.
    for field in ('shared', 'revision', 'repair'):
        kwargs = {field: {'html': 'x' * 60000, 'comments': ['Keep all slots']}}
        with pytest.raises(RunError) as caught:
            reference_html_context({}, {}, {}, {}, ref.approved[1], **kwargs)
        assert caught.value.detail['reason'] == 'over_budget'
        assert caught.value.detail['tokens'] > caught.value.detail['budget']


def quick_measure(html, slots, width, **kwargs):
    """Deadline oracle: avoid a Chromium launch dominating injected millisecond budgets."""
    from types import SimpleNamespace
    return SimpleNamespace(errors=[] if 'data-slot=' in html else [{'path': 'slots', 'message': 'Missing slots'}],
        boxes={cid: {'x': 24, 'y': 50 + n * 400, 'w': width - 48, 'h': 350} for n, cid in enumerate(slots)},
        height=100 + len(slots) * 400)


async def test_reference_html_one_deadline_covers_counting_generation_and_repair(tmp_path, monkeypatch):
    monkeypatch.setattr(designer.design_page, 'measure', quick_measure)
    spec = three_pages(); spec.pages = spec.pages[:1]
    # The ordinary worker bound is scaled to 30 ms; a 60 ms answer succeeds within 200 ms.
    monkeypatch.setattr(designer, 'HTML_STAGE_SECONDS', .2)
    html = ReferenceHTMLLLM(pause_generate=.06)
    ref, _, _ = reference_plan(tmp_path, spec, html=html)
    result, notes = await designer.design(spec, lambda: None, Trace(), reference=ref)
    assert notes == [] and result.pages[0].design and html.closed == 1
    for html in (ReferenceHTMLLLM(pause_count=5), ReferenceHTMLLLM(pause_generate=5),
                 ReferenceHTMLLLM(pause_generate=.13, plan={1: ['bad', 'ok']})):
        trace = Trace()
        ref, _, _ = reference_plan(tmp_path, spec, html=html)
        result, notes = await designer.design(spec, lambda: None, trace, reference=ref)
        assert result is spec and notes == [ALL_FALLBACK] and trace.spans[-1]['reason'] == 'timeout'
        stage = next(s for s in trace.spans if s['node'] == 'reference_html')
        assert stage['stage_duration_ms'] < 1000
        assert html.closed == len(html.requests)  # cancel closes even a blocked generation
        if html.pause_count:
            assert html.order == ['count'] and html.calls == 0
        if html.plan:
            assert html.order == ['count', 'generate', 'count', 'generate']  # repair shares remaining time


async def test_reference_html_retry_and_repair_cannot_multiply_deadline(tmp_path, monkeypatch):
    from google.adk.models.google_llm import Gemini
    from google.genai.errors import APIError
    from dss.harness import llm as routing
    monkeypatch.setattr(designer.design_page, 'measure', quick_measure)
    monkeypatch.setattr(designer, 'HTML_STAGE_SECONDS', .25)
    monkeypatch.setattr(routing, 'RETRY_DELAY_S', .01)
    calls, closed = [], []
    async def provider(self, request, stream=False):
        calls.append(request)
        try:
            await asyncio.sleep(.09)
            if len(calls) == 1:
                raise APIError(503, {'error': {'code': 503, 'message': 'private provider content'}})
            # An invalid response after retry must leave only the remaining time for repair.
            yield LlmResponse(content=types.Content(role='model', parts=[types.Part(text='{"html":"<p>Missing</p>","canvas_width":1200}')]))
        finally:
            closed.append(True)
    class Retrying(routing.RetryingGemini):
        async def count_request_tokens(self, request):
            return 1000
    monkeypatch.setattr(Gemini, 'generate_content_async', provider)
    spec = three_pages(); spec.pages = spec.pages[:1]
    ref, _, _ = reference_plan(tmp_path, spec, html=Retrying(model='worker'))
    trace = Trace()
    result, notes = await designer.design(spec, lambda: None, trace, reference=ref)
    assert result is spec and notes == [ALL_FALLBACK]
    assert len(calls) == len(closed) == 3 and trace.spans[-1]['reason'] == 'timeout'
    assert next(s for s in trace.spans if s['node'] == 'reference_html')['stage_duration_ms'] < 1000


async def test_reference_html_cancellation_propagates_and_closes_stream(tmp_path):
    html = ReferenceHTMLLLM(started=asyncio.Event(), release=asyncio.Event())
    spec = three_pages()
    ref, _, _ = reference_plan(tmp_path, spec, html=html)
    task = asyncio.create_task(designer.design(spec, lambda: None, Trace(), reference=ref))
    await asyncio.wait_for(html.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert html.closed == 1 and all(p.design is None for p in spec.pages)


async def test_repeated_output_cap_hits_are_traced_even_without_usage_metadata(tmp_path):
    class CutWithoutUsage(ReferenceHTMLLLM):
        async def generate_content_async(self, request, stream=False):
            yield LlmResponse(error_code='MAX_TOKENS', finish_reason=types.FinishReason.MAX_TOKENS)
    spec = three_pages(); spec.pages = spec.pages[:1]
    ref, _, _ = reference_plan(tmp_path, spec, html=CutWithoutUsage())
    trace = Trace()
    result, notes = await designer.design(spec, lambda: None, trace, reference=ref)
    assert result is spec and notes == [ALL_FALLBACK]
    attempts = [s for s in trace.spans if s['node'] == 'reference_html']
    assert len(attempts) == 2 and all(s['truncated'] is True for s in attempts)
    assert all(s.get('output_tokens', 0) == 0 and s['output_budget'] == 16000 for s in attempts)
    assert attempts[-1]['reason'] == 'invalid'


def test_staged_style_accept_uses_pairs_in_one_run_and_stale_gate_calls_neither_stage(blueprint_api, monkeypatch):
    from test_reference_brief import BriefLLM, reference_set, attached
    from dss.spec import references
    from test_render import spans
    folder = blueprint_api[4]
    images = reference_set(folder, 'style', 3)
    record = references.load(folder)
    record['instructions'] = ''  # style evidence without new semantic intent
    (folder / references.SET_FILE).write_text(json.dumps(record), encoding='utf-8')
    brief, html = BriefLLM(), ReferenceHTMLLLM()
    client, app, bid, folder, run_id = designed_flow(blueprint_api, monkeypatch, DesignerLLM(), reference_models={
        'reference_brief': brief, 'reference_html': html})
    spec = DashboardSpec.model_validate_json((folder / 'spec.json').read_text(encoding='utf-8'))
    trace, recorded = spans(app, run_id)
    assert trace['status'] == 'ok' and len(brief.requests) == html.calls == len(spec.pages) == 2
    assert [s['node'] for s in recorded if s['node'].startswith('reference_')] == [
        'reference_brief', 'reference_html', 'reference_brief', 'reference_html']
    assert all(p.design.model == 'gemini-3.8-flash' for p in spec.pages)
    assert all(attached(r)[1] == images for r in brief.requests + html.requests)
    assert '"canvas_width":1440' in str(brief.requests[1].config.system_instruction)
    assert trace['input_tokens'] >= 20 and trace['output_tokens'] >= 8
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM traces WHERE run_id=?', (run_id,)).fetchone()[0] == 1
    before = len(brief.requests), html.calls
    # New reference intent invalidates proof; accept may not invoke either stage.
    record['instructions'] = 'Add an unsupported animated slider'
    (folder / references.SET_FILE).write_text(json.dumps(record), encoding='utf-8')
    rejected = client.post(f'/api/builds/{bid}/blueprint/accept')
    assert rejected.status_code == 409 and (len(brief.requests), html.calls) == before


@pytest.mark.parametrize('failure', ['cancel', 'timeout', 'missing', 'invalid', 'cut', 'budget'])
def test_staged_reference_failure_cleans_candidate_and_releases_ownership(blueprint_api, monkeypatch, failure):
    from test_reference_brief import BriefLLM, reference_set
    from dss.spec import references
    from test_context_node import wait
    from test_render import spans
    client, app, bid, _, folder, bq, *_ = blueprint_api
    reference_set(folder, 'style', 1)
    record = references.load(folder); record['instructions'] = ''
    (folder / references.SET_FILE).write_text(json.dumps(record), encoding='utf-8')
    if failure == 'missing':
        (folder / record['images'][0]['file']).unlink()  # damaged retained file, no intent edit
    html = ReferenceHTMLLLM(started=asyncio.Event(), release=asyncio.Event() if failure in ('cancel', 'timeout') else None,
        plan={1: ['cut' if failure == 'cut' else 'bad'] * 2},
        fixed=9800 if failure == 'budget' else 1000)
    if failure == 'timeout':
        monkeypatch.setattr(designer, 'HTML_STAGE_SECONDS', .1)
    deleted = []
    _, _, _, _, run_id = designed_flow(blueprint_api, monkeypatch, DesignerLLM(), reference_models={
        'reference_brief': BriefLLM(), 'reference_html': html}, drain=False)
    bq.delete_view = lambda table: deleted.append(table) or True
    if failure == 'cancel':
        client.portal.call(asyncio.wait_for, html.started.wait(), 5)
        async def cancel():
            task = next(iter(app.state.engine_tasks))
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        client.portal.call(cancel)
    else:
        wait(app)
    assert not app.state.harness.active_builds and not app.state.engine_tasks
    publications = app.state.settings.get().data_dir / '.publications'
    assert not [p for p in publications.glob('r_*') if p.is_dir()]
    journal = json.loads((publications / f'{run_id}.json').read_text(encoding='utf-8'))
    assert journal['committed'] or (journal['restored'] and not journal['creating'])
    trace, recorded = spans(app, run_id)
    if failure == 'cancel':
        assert trace['error'] == 'cancelled' and html.closed == 1 and deleted
        assert not (folder / 'spec.json').exists() and not (folder / 'prototype.html').exists()
        assert client.get(f'/api/builds/{bid}').json()['stage'] == 'blueprint'
    else:
        assert trace['status'] == 'ok'  # accept keeps its documented kit fallback
        reason = {'missing': 'reference', 'budget': 'over_budget', 'timeout': 'timeout'}.get(failure, 'invalid')
        assert any(s.get('reason') == reason for s in recorded)
        spec = DashboardSpec.model_validate_json((folder / 'spec.json').read_text(encoding='utf-8'))
        assert all(p.design is None for p in spec.pages)
        assert html.closed == (0 if failure in ('missing', 'budget') else 1 if failure == 'timeout' else 2)
