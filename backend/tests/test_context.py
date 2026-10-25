"""Working memory assembly: per-node section order, budget drop order and trace token counts."""
import json
from pathlib import Path
import pytest
from dss.db import now
from types import SimpleNamespace
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.genai import types
from dss.harness.context import (BUDGETS, IMAGE_TOKENS, MAX_COUNTS, ORDER, SEPARATOR, Section, assemble, fit_request,
                                 request_estimate, revise_context, tokens)
from dss.harness.llm import count_tokens, counting_contents
from dss.harness.guardrails import RunError
from dss.spec.models import DashboardSpec
from fakes import FakeLLM


def kinds(context):
    return [s.kind for s in context.sections]


def names(context):
    return [s.name for s in context.sections]


def test_revise_sections_target_types_only(client, app):
    document = DashboardSpec.model_validate_json(Path("tests/data/thin_spec.json").read_text()).model_dump()
    comments = [{"component_id": "p1_revenue", "text": "bigger"}, {"component_id": "p1_title", "text": "bold"}]
    context = revise_context(document, comments, {"scorecard", "bar", "text"}, app.state.settings.get())
    assert kinds(context) == ["system", "skills", "semantic", "docs", "docs", "docs", "input"]
    assert names(context)[2] == "catalog/scorecard.md"
    assert "p1_regions" in context.sections[5].text  # a grid neighbour, but not a target
    assert "component_type: bar" not in context and "p1_note" not in context


def unordered():
    """Shuffled sections; each droppable entry is about 100 tokens."""
    entry = "x" * 396
    return [
        Section("input", "input", "Input:", "please help"),
        Section("history", "history", "History:", items=[json.dumps(f"m{i}{entry}") for i in range(4)]),
        Section("docs", "docs", "Docs:", "brief"),
        Section("semantic", "first", "First:", "a" * 400),
        Section("past", "past", "Past:", items=[json.dumps(f"h{i}{entry}") for i in range(3)]),
        Section("system", "system", body="system prompt"),
        Section("semantic", "second", "Second:", "b" * 400),
        Section("profile", "profile", "Profile:", "columns"),
        Section("skills", "skills", body="skill"),
    ]


def fit(expected):
    """Assemble with a budget equal to the expected trimmed context's own size."""
    budget = tokens(SEPARATOR.join(s.text for s in expected))
    return assemble("ux_audit", unordered(), reserve=BUDGETS["ux_audit"] - budget)


def by_name(sections, *wanted):
    return [s for s in sorted(sections, key=lambda s: ORDER.index(s.kind)) if s.name in wanted]


def test_order_without_drops():
    context = assemble("ux_audit", unordered())
    assert kinds(context) == ["system", "skills", "semantic", "semantic", "profile", "docs", "past", "history", "input"]
    assert context.dropped == {"past": 0, "history": 0, "semantic": 0}


def test_drops_least_relevant_fts_hits_first():
    expected = unordered()
    next(s for s in expected if s.name == "past").items.pop()
    context = fit(expected)
    assert context.dropped == {"past": 1, "history": 0, "semantic": 0}
    assert context.sections[6].items == [json.dumps(f"h{i}{'x' * 396}") for i in range(2)]
    assert len(context.sections[7].items) == 4


def test_then_oldest_messages():
    expected = [s for s in unordered() if s.name != "past"]
    history = next(s for s in expected if s.name == "history")
    del history.items[:2]
    context = fit(expected)
    assert context.dropped == {"past": 3, "history": 2, "semantic": 0}
    assert "past" not in names(context)
    assert context.sections[-2].items == [json.dumps(f"m{i}{'x' * 396}") for i in (2, 3)]


def test_then_semantic_beyond_the_first():
    expected = [s for s in unordered() if s.name not in ("past", "history", "second")]
    context = fit(expected)
    assert context.dropped == {"past": 3, "history": 4, "semantic": 1}
    assert names(context) == ["system", "skills", "first", "profile", "docs", "input"]


def test_never_drops_prompt_skills_first_concept_docs_or_input():
    kept = by_name(unordered(), "system", "skills", "first", "profile", "docs", "input")
    budget = tokens(SEPARATOR.join(s.text for s in kept)) - 1
    with pytest.raises(RunError, match="budget"):
        assemble("ux_audit", unordered(), reserve=BUDGETS["ux_audit"] - budget)


def spans(app, node):
    with app.state.db.connect() as conn:
        rows = conn.execute("SELECT spans_json FROM traces WHERE node=? ORDER BY rowid", (node,)).fetchall()
    return [span for row in rows for span in json.loads(row[0])]


def check_span(span, first_kinds):
    assert [s["kind"] for s in span["sections"]][:len(first_kinds)] == first_kinds
    assert all(s["tokens"] > 0 and s["name"] for s in span["sections"])
    assert set(span["dropped"]) == {"past", "history", "semantic"}


async def test_revise_trace_span_has_section_tokens(app, build_id, monkeypatch):
    from test_revise import FakeBigQuery, RevisionModel, response
    config = app.state.settings.get()
    folder = config.data_dir / "builds" / build_id / "v1"
    (folder / "docs").mkdir(parents=True)
    spec = DashboardSpec.model_validate_json(Path("tests/data/thin_spec.json").read_text())
    (folder / "spec.json").write_text(spec.model_dump_json(), encoding="utf-8")
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='prototype' WHERE id=?", (build_id,))
        conn.execute("INSERT INTO versions(build_id,n,status,spec_version,created_at) VALUES(?,1,'draft',1,?)",
                     (build_id, now()))
    await app.state.harness.run("revise", build_id, {"config": config, "factory": lambda config: FakeBigQuery(),
        "comments": [{"component_id": "p1_revenue", "text": "fine as is"}]}, llm=RevisionModel(delegate=FakeLLM(response=response([]))))
    span = next(s for s in spans(app, "revise") if s["node"] == "revise")
    check_span(span, ["system", "skills", "semantic", "docs", "docs", "docs", "docs", "input"])


class CountingLLM(FakeLLM):
    """FakeLLM with an injected provider token counter: `factor` x the offline estimate, or `fixed`."""
    factor: float = 1.0
    fixed: int | None = None
    count_error: str = ""
    counts: list = []
    seen: list = []

    async def count_request_tokens(self, llm_request):
        if self.count_error:
            raise RuntimeError(self.count_error)
        self.seen.append(str(llm_request.config.system_instruction))
        value = self.fixed if self.fixed is not None else int(request_estimate(llm_request) * self.factor)
        self.counts.append(value)
        return value


def counting(base, factor=1.5):
    """`base` (an offline fake) with an injected counter returning `factor` x the estimate."""
    class Counted(base):
        counts: list = []

        async def count_request_tokens(self, llm_request):
            self.counts.append(int(request_estimate(llm_request) * factor))
            return self.counts[-1]
    return Counted


def assert_counted(span, model):
    """The authoritative count is recorded apart from the estimates."""
    assert span["request_tokens"] in model.counts and span["count_calls"] == 1
    assert isinstance(span["input_tokens_estimate"], int) and span["request_tokens"] != span["input_tokens_estimate"]
    assert span["sections"] and all(isinstance(s["tokens"], int) for s in span["sections"])


def audit_spec(app, build_id):
    folder = app.state.settings.get().data_dir / "builds" / build_id / "v1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "spec.json").write_text(Path("tests/data/thin_spec.json").read_text(), encoding="utf-8")


@pytest.mark.parametrize("fixed, failure", [(BUDGETS["ux_audit"] + 1, ""), (None, "count failed for test-key")])
async def test_audit_never_generates_over_budget_or_uncounted(app, build_id, caplog, fixed, failure):
    audit_spec(app, build_id)
    model = CountingLLM(response='{"findings": []}', fixed=fixed, count_error=failure, counts=[], seen=[])
    with pytest.raises(RunError) as error:
        await app.state.harness.run("ux_audit", build_id, {"config": app.state.settings.get()}, llm=model)
    assert error.value.code == "llm_unavailable" and model.calls == 0
    assert "test-key" not in caplog.text and "test-key" not in json.dumps(spans(app, "ux_audit"))


async def test_audit_records_the_authoritative_count(app, build_id):
    audit_spec(app, build_id)
    model = counting(FakeLLM)(response='{"findings": []}')
    await app.state.harness.run("ux_audit", build_id, {"config": app.state.settings.get()}, llm=model)
    assert_counted(next(s for s in spans(app, "ux_audit") if s["node"] == "ux_audit"), model)
    assert model.calls == 1


IDENTITY = 'You are an agent. Your internal name is "ux_audit".'


def online_request(context, extra=""):
    """An ADK-shaped request: identity line, the provider's instruction, schema and one user turn."""
    request = LlmRequest(model="gemini-test", config=types.GenerateContentConfig(
        response_mime_type="application/json", response_json_schema={"type": "object", "title": "Out"}))
    request.contents = [types.Content(role="user", parts=[types.Part(text="Go.")])]
    request.config.system_instruction = IDENTITY + SEPARATOR + context + extra
    return request


def counted_to_fit(expected):
    """A linear counter under which exactly `expected` fits, with half an entry of slack."""
    estimate = request_estimate(online_request(assemble("ux_audit", expected)))
    return CountingLLM(factor=BUDGETS["ux_audit"] / (estimate + 50), counts=[], seen=[])


async def test_online_count_over_budget_drops_in_order_and_recounts():
    expected = [s for s in unordered() if s.name != "past"]
    del next(s for s in expected if s.name == "history").items[:2]
    model = counted_to_fit(expected)
    context = assemble("ux_audit", unordered())
    request, span = online_request(context), {}
    assert context.dropped == {"past": 0, "history": 0, "semantic": 0}
    assert request_estimate(request) <= BUDGETS["ux_audit"]  # the estimate alone would send it
    fitted = await fit_request(context, request, model, span)
    assert fitted.dropped == {"past": 3, "history": 2, "semantic": 0}
    assert kinds(fitted) == ["system", "skills", "semantic", "semantic", "profile", "docs", "history", "input"]
    assert fitted.sections[-2].items == [json.dumps(f"m{i}{'x' * 396}") for i in (2, 3)]
    assert model.counts[0] > BUDGETS["ux_audit"] >= model.counts[1] and len(model.counts) == 2
    assert request.config.system_instruction == IDENTITY + SEPARATOR + fitted
    assert span["request_tokens"] == model.counts[-1] and span["count_calls"] == 2
    assert span["input_tokens_estimate"] == request_estimate(request) and span["dropped"] == fitted.dropped
    assert [s["tokens"] for s in span["sections"]] == [tokens(s.text) for s in fitted.sections]
    assert len(context.sections) == 9 and context.dropped["past"] == 0  # the assembled context is unchanged


async def test_online_count_drops_semantic_beyond_the_first_last():
    model = counted_to_fit([s for s in unordered() if s.name not in ("past", "history", "second")])
    context = assemble("ux_audit", unordered())
    fitted = await fit_request(context, online_request(context), model, {})
    assert fitted.dropped == {"past": 3, "history": 4, "semantic": 1}
    assert names(fitted) == ["system", "skills", "first", "profile", "docs", "input"]


async def test_cjk_counted_over_budget_with_only_mandatory_sections_refuses():
    # Audit sample: chars/4 estimated 225 tokens, the provider counted 501.
    text = "每月的收入按地区分布" * 3000
    context = assemble("ux_audit", [Section("system", "system", body="Audit."), Section("input", "input", "Task:", text)])
    request = online_request(context)
    model = CountingLLM(factor=501 / 225, counts=[], seen=[])
    assert request_estimate(request) <= BUDGETS["ux_audit"] < model.factor * request_estimate(request)
    span = {}
    with pytest.raises(RunError, match="exceeds its input budget") as error:
        await fit_request(context, request, model, span)
    assert error.value.code == "llm_unavailable" and len(model.counts) == 1
    assert span["request_tokens"] > BUDGETS["ux_audit"]


async def test_still_too_large_after_every_drop_refuses():
    mandatory = by_name(unordered(), "system", "skills", "first", "profile", "docs", "input")
    model = counted_to_fit(mandatory)
    model.factor *= 3  # even the mandatory sections alone are counted over budget
    context = assemble("ux_audit", unordered())
    span = {}
    with pytest.raises(RunError, match="exceeds its input budget"):
        await fit_request(context, online_request(context), model, span)
    assert len(model.counts) == 2 and span["request_tokens"] == model.counts[-1] > BUDGETS["ux_audit"]
    assert span["dropped"] == {"past": 3, "history": 4, "semantic": 1}
    assert [s["name"] for s in span["sections"]] == ["system", "skills", "first", "profile", "docs", "input"]


async def test_recounts_stop_at_the_count_cap():
    # A counter that ignores drops: each recount shrinks only by the measured ratio, then refuses.
    context = assemble("ux_audit", unordered())
    model = CountingLLM(fixed=BUDGETS["ux_audit"] + 1, counts=[], seen=[])
    span = {}
    with pytest.raises(RunError, match="exceeds its input budget"):
        await fit_request(context, online_request(context), model, span)
    assert len(model.counts) == MAX_COUNTS and span["count_calls"] == MAX_COUNTS
    assert span["dropped"]["past"] >= 1 and span["dropped"]["semantic"] == 0  # FTS hits go first


async def test_count_cap_refuses_instead_of_counting_again(monkeypatch):
    monkeypatch.setattr("dss.harness.context.MAX_COUNTS", 1)
    context = assemble("ux_audit", unordered())
    model = CountingLLM(factor=100, counts=[], seen=[])
    with pytest.raises(RunError, match="exceeds its input budget"):
        await fit_request(context, online_request(context), model, {})
    assert len(model.counts) == 1


async def test_counting_failure_is_sanitized_and_refuses():
    context = assemble("ux_audit", unordered())
    model = CountingLLM(count_error="count failed for test-key: Please help", counts=[], seen=[])
    with pytest.raises(RunError) as error:
        await fit_request(context, online_request(context), model, {})
    assert error.value.code == "llm_unavailable" and "test-key" not in error.value.message
    assert error.value.__suppress_context__ and error.value.__cause__ is None


async def test_schema_tools_images_and_repair_participate():
    context = assemble("ux_audit", unordered())
    request = online_request(context)
    with_schema = request_estimate(request)
    request.config.response_json_schema = None
    assert request_estimate(request) < with_schema
    request.config.response_json_schema = {"type": "object", "title": "Out"}
    request.config.tools = [types.Tool(function_declarations=[types.FunctionDeclaration(
        name="validate_artifact", description="Validate the artifact. " * 20)])]
    with_tools = request_estimate(request)
    assert with_tools > with_schema
    request.contents[0].parts.append(types.Part.from_bytes(data=b"\x89PNG-bytes", mime_type="image/png"))
    assert request_estimate(request) == with_tools + IMAGE_TOKENS
    head, *rest = counting_contents(request)
    texts = [part.text for part in head.parts]
    assert texts[0] == request.config.system_instruction and '"title": "Out"' in texts[1]
    assert "validate_artifact" in texts[2] and rest == request.contents
    assert rest[0].parts[1].inline_data.data == b"\x89PNG-bytes"
    repair = "\nValidation errors:\n[\"overlap\"]\nReturn the complete repaired JSON object."
    model, span = CountingLLM(counts=[], seen=[]), {}
    await fit_request(context, online_request(context, repair), model, span, extra=repair)
    assert model.seen[-1].endswith(repair) and span["repair_tokens"] == tokens(repair)


async def test_gemini_counter_counts_the_folded_request_and_fakes_stay_offline():
    calls = []

    class Models:
        async def count_tokens(self, **kwargs):
            calls.append(kwargs)
            return types.CountTokensResponse(total_tokens=321)

    class Counted(Gemini):
        @property
        def api_client(self):
            return SimpleNamespace(aio=SimpleNamespace(models=Models()))

    request = online_request(assemble("ux_audit", unordered()))
    assert await count_tokens(Counted(model="gemini-test"), request) == 321
    assert calls[0]["model"] == "gemini-test"
    assert calls[0]["contents"][0].parts[0].text == request.config.system_instruction
    assert calls[0]["contents"][1:] == request.contents
    assert await count_tokens(FakeLLM(), request) is None


def designer_page(label='Revenue'):
    return {'index': 2, 'name': 'Overview', 'pages': 2, 'canvas_width': 1440,
            'components': [{'id': 'p2_revenue', 'type': 'scorecard', 'label': label, 'min_w': 200, 'min_h': 64}]}


def test_designer_sections_follow_the_working_memory_row():
    from dss.harness.context import designer_context
    design = {'title': 'Sales', 'theme': {'font_family': 'Arial'}}
    context = designer_context(design, designer_page(), shared={'canvas_width': 1440, 'css': 'body{padding:24px}'},
                               repair={'errors': [{'path': 'slots.p2_revenue', 'message': 'missing'}]})
    assert kinds(context) == ['system', 'skills', 'semantic', 'semantic', 'docs', 'docs', 'input', 'input']
    assert names(context)[:6] == ['prompts/v1/designer.md', 'skills/dashboard-design.md', 'icons', 'art', 'design',
                                  'page-1']
    assert 'Exactly one empty' in context.sections[0].text and '# Dashboard design' in context.sections[1].text
    assert 'trending-up' in context.sections[2].text and 'body{padding:24px}' in context
    assert BUDGETS['designer'] == 12000 and sum(c['tokens'] for c in context.counts()) <= 12000 - 500
    first = designer_context(design, {**designer_page(), 'index': 1})
    assert names(first)[-1] == 'page' and 'page-1' not in names(first)


def test_designer_over_budget_refuses():
    from dss.harness.context import designer_context
    with pytest.raises(RunError) as refused:
        designer_context({'title': 'Sales', 'theme': {}}, designer_page('Revenue ' * 6000))
    assert refused.value.code == 'llm_unavailable' and refused.value.detail['reason'] == 'over_budget'
    # 24.3: the refusal carries its size and budget (numbers only) for a reason that names them.
    assert refused.value.detail['tokens'] > refused.value.detail['budget'] == 12000 - 500


def brief_inputs(label='Revenue', instructions='Keep the globe in the centre'):
    reference = {'mode': 'recreate', 'images': [{'image': 1, 'mime_type': 'image/png', 'width': 2048, 'height': 1191}],
                 'instructions': instructions, 'summary': 'Recreate reference: 1 chart', 'palette': 'navy', 'type': 'light',
                 'spacing': 'wide'}
    page = {'index': 2, 'name': 'Overview', 'pages': 2, 'canvas_width': 1200, 'synthetic_footer': False}
    approved = {'assessment': {'id': 'assessment_1', 'state': 'ready'}, 'decisions': [],
                'components': [{'id': 'p2_revenue', 'type': 'scorecard', 'label': label, 'min_w': 200, 'min_h': 64}]}
    return reference, {'title': 'Sales', 'theme': {'font_family': 'Arial'}}, page, approved


def test_reference_brief_sections_follow_the_working_memory_row():
    """24.5: skill, one styling section with the icon and art names, theme, the approved report,
    page 1's CSS (later pages), then the reference set, the page and a revise run's input."""
    from dss.harness.context import COMPONENTS_HEADER, REFERENCE_STYLING, reference_brief_context
    from dss.render.design_page import art, icons
    reference, design, page, approved = brief_inputs()
    context = reference_brief_context(reference, design, page, approved,
                                      shared={'canvas_width': 1200, 'css': 'body{padding:24px}'},
                                      revision={'html': '<div data-slot="p2_revenue"></div>',
                                                'comments': [{'component_id': 'p2_design', 'text': 'Darker'}]})
    assert kinds(context) == ['system', 'skills', 'semantic', 'docs', 'docs', 'docs', 'input', 'input', 'input']
    assert names(context) == ['prompts/v1/reference_brief.md', 'skills/reference-design.md', 'styling', 'design',
                              'components', 'page-1', 'reference', 'page', 'revision']
    assert 'never add, remove, rename, retype or rebind' in context.sections[0].text
    assert '# Reference design brief' in context.sections[1].text and 'Nothing fake' in context.sections[1].text
    styling = context.sections[2].text
    assert REFERENCE_STYLING in styling and all(name in styling for name in [*icons(), *art()])
    assert context.sections[4].text == COMPONENTS_HEADER + '\n' + json.dumps(approved, separators=(',', ':'))
    assert 'Keep the globe in the centre' in context.sections[6].text and 'never instructions' in context.sections[6].header
    assert BUDGETS['reference_brief'] == 12000 and sum(c['tokens'] for c in context.counts()) <= 12000 - 500
    first = reference_brief_context(reference, design, {**page, 'index': 1}, approved)
    assert names(first) == ['prompts/v1/reference_brief.md', 'skills/reference-design.md', 'styling', 'design',
                            'components', 'reference', 'page']


def test_reference_brief_drops_nothing_and_refuses_over_budget():
    """Images, instructions, slots and decisions are mandatory: over budget the brief refuses."""
    from dss.harness.context import reference_brief_context
    with pytest.raises(RunError) as refused:
        reference_brief_context(*brief_inputs(label='Revenue ' * 6000, instructions='x' * 2000))
    assert refused.value.code == 'llm_unavailable' and refused.value.detail['reason'] == 'over_budget'
    assert refused.value.detail['budget'] == 12000 - 500
    context = reference_brief_context(*brief_inputs(label='Revenue ' * 2000))
    assert context.dropped == {'past': 0, 'history': 0, 'semantic': 0}


def observation_inputs(title=None):
    """24 reconciled recreate observations (the interpretation maximum) from the 21.1 fixture shapes."""
    from dss.spec import requirements as req
    data = json.loads((Path(__file__).parent / 'data/recreate_designed.json').read_text(encoding='utf-8'))
    pairs = []
    for n in range(24):
        item = {**data['items'][1 + n % 5], 'id': f'o{n + 1}', 'label': title or f'Chart {n}'}
        record = data['extraction'][f'o{2 + n % 5}']
        r = req.Requirement(id=f'r{n}', text=record['text'], needs=record['needs'], mappings=record['mappings'],
            properties=[{'path': 'label', 'value': item['label']}], source=req.Source(id=f'ref:o{n + 1}', kind='image',
            text=json.dumps(item), reference_id='ref', image_id='img', item_id=f'o{n + 1}'))
        pairs.append((req.observation_meaning(r, r.needs, r.properties), req.observation_meaning(r, r.needs, r.properties, labels=False)))
    return pairs


def blueprint_memory(observations):
    from dss.artifacts.models import Context
    from dss.harness.context import blueprint_context
    from dss.harness.nodes import blueprint as node
    context = Context.model_validate_json((Path(__file__).resolve().parents[2] / 'contracts/fixtures/api/context.json').read_text(encoding='utf-8'))
    fields = [{'source_id': 's', 'fields': [{'name': n, 'type': t, 'role': r} for n, t, r in (
        ('order_id', 'STRING', 'dimension'), ('order_date', 'DATE', 'dimension'), ('region', 'STRING', 'dimension'),
        ('revenue', 'FLOAT64', 'metric'), ('quantity', 'INT64', 'metric'))]}]
    return blueprint_context(context, fields, [], {'s1': 1}, node.catalog_summary(), [], observations=observations)


def test_blueprint_observations_section_fits_without_boxes_bytes_or_rows():
    """22.1: the planner sees each recreate observation's reconciled meaning, within the blueprint's 14k input."""
    memory = blueprint_memory(observation_inputs())
    from dss.harness.nodes import blueprint
    assert BUDGETS['blueprint'] == 14000 and blueprint.MAX_OUTPUT_TOKENS == 6000
    [section] = [s for s in memory.sections if s.name == 'observations']
    observed = json.loads(section.body)
    assert section.kind == 'reference' and len(observed) == 24 and memory.dropped == {'past': 0, 'history': 0, 'semantic': 0}
    assert observed[3] == {'id': 'o4', 'kind': 'chart', 'type': 'time_series', 'date_field': 'order_date', 'title': 'Chart 3',
                           'metrics': [{'label': 'Revenue', 'field': 'revenue', 'unit': 'USD', 'aggregation': 'sum', 'date_grain': 'month'}]}
    assert not any(word in section.body for word in ('box', 'confidence', 'image', 'img', 'rows', 'chart_candidate'))
    assert tokens(str(memory)) <= BUDGETS['blueprint'] - 2000
    # Over budget, the observation labels go first; the observed fields stay.
    memory = blueprint_memory(observation_inputs(title='T' * 1600))
    [section] = [s for s in memory.sections if s.name == 'observations']
    assert 'TTT' not in section.body and 'Revenue' not in section.body and memory.dropped['profile'] == 1
    assert [o['metrics'][0]['field'] for o in json.loads(section.body)] == ['revenue', 'order_id', 'quantity', 'revenue', 'revenue'] * 4 + ['revenue', 'order_id', 'quantity', 'revenue']


def test_blueprint_context_without_observations_is_unchanged():
    memory = blueprint_memory(())
    assert 'observations' not in names(memory) and 'Recreate observations:' not in str(memory)


def test_capability_context_trims_only_a_comment_batch_and_outline_other_keeps_the_ledger():
    """24.3: a comment batch sends its targets' rows plus unbound rows; Other and references send all."""
    from dss.harness.context import capability_context, outline_context
    from dss.spec.capabilities import Checker, load_registry
    from test_feasibility import long_ledger
    ledger, checker = long_ledger(), Checker(load_registry())
    snapshot = {'sources': [], 'reference': None, 'definitions': {}, 'spec': None, 'incoming': []}
    comment = {'id': 'b:0', 'kind': 'comment', 'text': 'Bigger', 'component_id': 'p1_regions'}
    image = {'id': 'ref:o1', 'kind': 'image', 'text': '{}', 'reference_id': 'ref', 'item_id': 'o1'}
    def ids(memory):
        [section] = [s for s in memory.sections if s.name == 'requirements.json']
        return [r['id'] for r in json.loads(section.body)['requirements']]
    assert ids(capability_context(snapshot, ledger, checker, [comment])) == [r.id for r in ledger.requirements[:10]]
    assert ids(capability_context(snapshot, ledger, checker, [image])) == [r.id for r in ledger.requirements]
    other = outline_context(None, SimpleNamespace(model_dump_json=lambda: '{}'), [], 'executive', 'outline_other',
                            source={'id': 'm', 'text': 'Add a map'}, ledger=ledger, checker=checker)
    [section] = [s for s in other.sections if s.name == 'ledger']
    assert [r['id'] for r in json.loads(section.body)['requirements']] == [r.id for r in ledger.requirements]
    assert BUDGETS['outline_other'] == 6000 and BUDGETS['reference_extract'] == 12000


@pytest.mark.parametrize('draft', [None, '<section>current draft</section>'])
def test_reference_repair_keeps_one_projection_and_one_current_html(draft):
    from dss.harness.context import reference_html_context
    approved = {'assessment': {'state': 'ready'}, 'components': [
        {'id': 'c1', 'type': 'bar', 'label': 'Revenue', 'metrics': [{'field': 'amount', 'agg': 'sum'}],
         'bindings': [{'requirement': 'r1'}]}], 'decisions': [{'action': 'accept_alternative', 'choice': 'Native bar'}]}
    page = {'index': 1, 'components': [{'id': 'c1', 'min_w': {'1200': 400}, 'min_h': 240}]}
    revision = {'html': '<main>original baseline</main>', 'comments': [{'text': 'Preserve this comment'}]}
    repair = {'errors': [{'path': 'slot', 'message': 'too small'}]}
    if draft:
        repair.update(html=draft, canvas_width=1440)
    memory = reference_html_context({'instructions': 'Keep globe', 'images': [1, 2], 'notes': 'Navy'},
        {'overall': 'Full validated brief'}, {'theme': 'dark'}, page, approved,
        shared={'css': 'body{color:red}', 'canvas_width': 1440}, revision=revision, repair=repair, attempt=2)
    sections = {s.name: json.loads(s.body) for s in memory.sections if s.kind in ('docs', 'input')}
    assert memory.budget == 24000 and 'components' not in sections['page']
    assert sections['components']['components'] == [{**approved['components'][0], 'min_w': {'1200': 400}, 'min_h': 240}]
    assert sections['components']['decisions'] == approved['decisions']
    assert sections['revision'] == {**revision, 'html': draft or revision['html']}
    assert sections['repair'] == {'errors': repair['errors']}
    assert str(memory).count('current draft' if draft else 'original baseline') == 1
    assert ('original baseline' in str(memory)) == (draft is None)
    assert sections['brief'] == {'overall': 'Full validated brief'}
    assert sections['reference']['images'] == [1, 2] and sections['page-1']['css'] == 'body{color:red}'
    assert revision['html'] == '<main>original baseline</main>' and 'components' in page  # inputs untouched
