"""Working memory assembly: per-node section order, budget drop order and trace token counts."""
import json
from pathlib import Path
import pytest
from dss.db import new_id, now
from types import SimpleNamespace
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.genai import types
from dss.harness.context import (BUDGETS, IMAGE_TOKENS, MAX_COUNTS, ORDER, SEPARATOR, Section, assemble, fit_request,
                                 interview_context, plan_context, request_estimate, revise_context, spec_context, tokens)
from dss.harness.llm import count_tokens, counting_contents
from dss.harness.guardrails import RunError
from dss.harness.nodes.intake import write_doc
from dss.memory import episodic
from dss.spec.models import DashboardSpec
from fakes import FakeLLM


def other_build(app, title="Regional sales review"):
    build_id = new_id("b")
    with app.state.db.connect() as conn:
        conn.execute("INSERT INTO builds(id,title,archetype,mode,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                     (build_id, title, "executive", "data", "done", now(), now()))
    return build_id


def profile(app, build_id):
    docs = app.state.settings.get().data_dir / "builds" / build_id / "v1/docs"
    docs.mkdir(parents=True, exist_ok=True)
    write_doc(docs / "data-profile.md", {"type": "BigQuery Table"}, "revenue, region, order_date")
    return docs


def kinds(context):
    return [s.kind for s in context.sections]


def names(context):
    return [s.name for s in context.sections]


def test_interview_sections_in_order(app, build_id):
    profile(app, build_id)
    past = other_build(app)
    episodic.save(app.state.db, past, "user", "Compare quarterly revenue by region")
    episodic.save(app.state.db, build_id, "assistant", "Who reads this dashboard?")
    episodic.save(app.state.db, build_id, "user", "Show quarterly revenue by region")
    context = interview_context(app.state.db, app.state.settings.get(), build_id, "Show quarterly revenue by region")
    assert kinds(context) == ["system", "skills", "skills", "semantic", "semantic", "profile", "past", "history", "input"]
    assert names(context) == ["prompts/v1/interview.md", "skills/interview.md", "skills/archetype-executive.md",
        "archetypes/executive.md", "catalog/index.md", "data-profile.md", "episodic/past", "episodic/recent", "input"]
    assert context == SEPARATOR.join(s.text for s in context.sections)
    past_text, history_text = context.sections[6].text, context.sections[7].text
    assert "Regional sales review" in past_text and now()[:10] in past_text and "Compare quarterly" in past_text
    assert "Who reads this dashboard?" in history_text and "Show quarterly" not in history_text
    assert context.endswith("Current request (untrusted data):\nShow quarterly revenue by region")


def test_interview_start_is_recency_only(app, build_id):
    episodic.save(app.state.db, other_build(app), "user", "Start the interview with one question grounded in the data profile.")
    context = interview_context(app.state.db, app.state.settings.get(), build_id, "Start the interview", query="")
    assert kinds(context) == ["system", "skills", "skills", "semantic", "semantic", "profile", "input"]


def test_plan_sections_in_order_with_user_facts(app, build_id):
    config = app.state.settings.get()
    profile(app, build_id)
    user = config.data_dir / "knowledge/user"
    user.mkdir(parents=True)
    write_doc(user / "index.md", {"type": "Index"}, "- [Monthly](monthly.md)\n- [Log](log.md)")
    write_doc(user / "log.md", {"type": "Log"}, "# Log")
    write_doc(user / "monthly.md", {"type": "User Preference"}, "Prefers monthly totals.")
    episodic.save(app.state.db, build_id, "user", "Help our sales director")
    episodic.save(app.state.db, build_id, "assistant", "Which decision?", "interview")
    episodic.save(app.state.db, build_id, "user", "Make the title bigger", "revise")
    context = plan_context(app.state.db, config, build_id)
    assert kinds(context) == ["system", "skills", "skills", "semantic", "semantic", "semantic", "profile", "history"]
    assert names(context)[3:6] == ["archetypes/executive.md", "catalog/index.md", "user/monthly.md"]
    assert "Prefers monthly totals." in context and "Help our sales director" in context
    assert "Make the title bigger" not in context


def spec_inputs(app, build_id, kpis):
    docs = profile(app, build_id)
    for name in ("brief", "design", "decisions", "derived-fields"):
        write_doc(docs / f"{name}.md", {"type": "Build Document"}, name)
    write_doc(docs / "kpis.md", {"type": "KPI Definitions"}, kpis)
    write_doc(docs / "questions.md", {"type": "Business Questions"}, "- q1: How is revenue changing? (priority: high)")
    build = {"id": build_id, "archetype": "executive", "spec_version": 1, "table": "project.data.view"}
    return docs.parent, build


def test_spec_sections_and_named_catalog_types(app, build_id):
    folder, build = spec_inputs(app, build_id, "Revenue as a scorecard, a monthly time series and a pie share.")
    context = spec_context(app.state.settings.get(), folder, build, [], {"scorecard", "time_series", "bar"})
    assert kinds(context) == ["system", "skills", "semantic", "semantic", "semantic"] + ["docs"] * 7
    assert names(context)[2:5] == ["catalog/scorecard.md", "catalog/time_series.md", "archetypes/executive.md"]
    assert names(context)[5:] == ["brief.md", "questions.md", "kpis.md", "derived-fields.md", "design.md",
                                  "decisions.md", "datasource"]
    assert "component_type: pie" not in context and "component_type: bar" not in context


def test_spec_without_named_types_uses_every_allowed_type(app, build_id):
    folder, build = spec_inputs(app, build_id, "Revenue: SUM(revenue).")
    context = spec_context(app.state.settings.get(), folder, build, [], {"bar", "scorecard", "time_series"})
    assert names(context)[2:6] == ["catalog/scorecard.md", "catalog/time_series.md", "catalog/bar.md",
                                   "archetypes/executive.md"]


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
    return assemble("interview", unordered(), reserve=BUDGETS["interview"] - budget)


def by_name(sections, *wanted):
    return [s for s in sorted(sections, key=lambda s: ORDER.index(s.kind)) if s.name in wanted]


def test_order_without_drops():
    context = assemble("interview", unordered())
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
        assemble("interview", unordered(), reserve=BUDGETS["interview"] - budget)


def test_interview_over_budget_drops_fts_then_oldest(app, build_id):
    profile(app, build_id)
    past = other_build(app)
    for i in range(3):
        episodic.save(app.state.db, past, "user", f"Quarterly revenue by region {i} " + "p" * 6000)
    ids = [episodic.save(app.state.db, build_id, "user", f"Turn {i} " + "h" * 2600)["id"] for i in range(12)]
    context = interview_context(app.state.db, app.state.settings.get(), build_id, "Quarterly revenue by region")
    assert context.dropped["past"] == 3 and context.dropped["history"] >= 1 and context.dropped["semantic"] == 0
    assert tokens(context) <= BUDGETS["interview"]
    assert "Turn 0 " not in context and "Turn 11 " in context
    assert kinds(context)[:5] == ["system", "skills", "skills", "semantic", "semantic"]
    assert context.endswith("Quarterly revenue by region") and len(ids) == 12


def spans(app, node):
    with app.state.db.connect() as conn:
        rows = conn.execute("SELECT spans_json FROM traces WHERE node=? ORDER BY rowid", (node,)).fetchall()
    return [span for row in rows for span in json.loads(row[0])]


def check_span(span, first_kinds):
    assert [s["kind"] for s in span["sections"]][:len(first_kinds)] == first_kinds
    assert all(s["tokens"] > 0 and s["name"] for s in span["sections"])
    assert set(span["dropped"]) == {"past", "history", "semantic"}


async def test_interview_trace_span_has_section_tokens(app, build_id):
    profile(app, build_id)
    episodic.save(app.state.db, build_id, "user", "Help our sales director")
    await app.state.harness.run("interview", build_id,
        {"config": app.state.settings.get(), "text": "Help our sales director"}, llm=FakeLLM(response="Which KPI?"))
    span = next(s for s in spans(app, "interview") if s["node"] == "interview")
    check_span(span, ["system", "skills", "skills", "semantic", "semantic", "profile", "input"])
    assert span["sections"][0]["tokens"] == tokens(Path("prompts/v1/interview.md").read_text(encoding="utf-8"))


async def test_plan_and_spec_trace_spans_have_section_tokens(app, build_id, monkeypatch):
    from test_plan import FakeLLM as PlanLLM, FakeBigQuery, PLAN, seed
    monkeypatch.setattr("dss.render.background.capture", lambda html, path, width, height: path.write_bytes(b"PNG"))
    seed(app, build_id)
    episodic.save(app.state.db, build_id, "user", "Help our sales director")
    service = FakeBigQuery()
    await app.state.harness.run("plan", build_id, {"config": app.state.settings.get(),
        "factory": lambda config: service}, llm=PlanLLM(response=json.dumps(PLAN)))
    recorded = spans(app, "plan")
    check_span(next(s for s in recorded if s["node"] == "plan"),
               ["system", "skills", "skills", "semantic", "semantic", "profile", "history"])
    check_span(next(s for s in recorded if s["node"] == "spec"), ["system", "skills", "semantic"])


async def test_revise_trace_span_has_section_tokens(app, build_id, monkeypatch):
    from test_revise import FakeBigQuery, response
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
        "comments": [{"component_id": "p1_revenue", "text": "fine as is"}]}, llm=FakeLLM(response=response([])))
    span = next(s for s in spans(app, "revise") if s["node"] == "revise")
    check_span(span, ["system", "skills", "semantic", "docs", "docs", "docs", "input"])


async def test_interview_start_run_skips_fts(app, build_id):
    episodic.save(app.state.db, other_build(app), "user", "Start the interview with one question grounded in the data profile.")
    await app.state.harness.run("interview", build_id, {"config": app.state.settings.get(), "start": True,
        "text": "Start the interview with one question grounded in the data profile."}, llm=FakeLLM(response="Who decides?"))
    span = next(s for s in spans(app, "interview") if s["node"] == "interview")
    assert "past" not in [s["kind"] for s in span["sections"]]


async def test_repair_span_counts_the_repair_turn(app, build_id):
    from test_spec_node import SpecLLM, spec_seed
    spec_seed(app, build_id)
    await app.state.harness.run("spec", build_id, {"config": app.state.settings.get()}, llm=SpecLLM(invalid=1))
    recorded = spans(app, "spec")
    assert "repair_tokens" not in next(s for s in recorded if s["node"] == "spec")
    repair = next(s for s in recorded if s["node"] == "spec_repair")
    assert repair["repair_tokens"] > 0 and repair["sections"]


@pytest.mark.parametrize("index, warned", [(None, False), ("- [Gone](gone.md)", True)])
def test_user_facts_missing_or_dangling(app, build_id, caplog, index, warned):
    config = app.state.settings.get()
    profile(app, build_id)
    if index:
        (config.data_dir / "knowledge/user").mkdir(parents=True)
        write_doc(config.data_dir / "knowledge/user/index.md", {"type": "Index"}, index)
    context = plan_context(app.state.db, config, build_id)
    assert [s.kind for s in context.sections].count("semantic") == 2
    assert ("Unreadable user facts" in caplog.text) is warned


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


IDENTITY = 'You are an agent. Your internal name is "interview".'


def online_request(context, extra=""):
    """An ADK-shaped request: identity line, the provider's instruction, schema and one user turn."""
    request = LlmRequest(model="gemini-test", config=types.GenerateContentConfig(
        response_mime_type="application/json", response_json_schema={"type": "object", "title": "Out"}))
    request.contents = [types.Content(role="user", parts=[types.Part(text="Go.")])]
    request.config.system_instruction = IDENTITY + SEPARATOR + context + extra
    return request


def counted_to_fit(expected):
    """A linear counter under which exactly `expected` fits, with half an entry of slack."""
    estimate = request_estimate(online_request(assemble("interview", expected)))
    return CountingLLM(factor=BUDGETS["interview"] / (estimate + 50), counts=[], seen=[])


async def test_online_count_over_budget_drops_in_order_and_recounts():
    expected = [s for s in unordered() if s.name != "past"]
    del next(s for s in expected if s.name == "history").items[:2]
    model = counted_to_fit(expected)
    context = assemble("interview", unordered())
    request, span = online_request(context), {}
    assert context.dropped == {"past": 0, "history": 0, "semantic": 0}
    assert request_estimate(request) <= BUDGETS["interview"]  # the estimate alone would send it
    fitted = await fit_request(context, request, model, span)
    assert fitted.dropped == {"past": 3, "history": 2, "semantic": 0}
    assert kinds(fitted) == ["system", "skills", "semantic", "semantic", "profile", "docs", "history", "input"]
    assert fitted.sections[-2].items == [json.dumps(f"m{i}{'x' * 396}") for i in (2, 3)]
    assert model.counts[0] > BUDGETS["interview"] >= model.counts[1] and len(model.counts) == 2
    assert request.config.system_instruction == IDENTITY + SEPARATOR + fitted
    assert span["request_tokens"] == model.counts[-1] and span["count_calls"] == 2
    assert span["input_tokens_estimate"] == request_estimate(request) and span["dropped"] == fitted.dropped
    assert [s["tokens"] for s in span["sections"]] == [tokens(s.text) for s in fitted.sections]
    assert len(context.sections) == 9 and context.dropped["past"] == 0  # the assembled context is unchanged


async def test_online_count_drops_semantic_beyond_the_first_last():
    model = counted_to_fit([s for s in unordered() if s.name not in ("past", "history", "second")])
    context = assemble("interview", unordered())
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
    context = assemble("interview", unordered())
    span = {}
    with pytest.raises(RunError, match="exceeds its input budget"):
        await fit_request(context, online_request(context), model, span)
    assert len(model.counts) == 2 and span["request_tokens"] == model.counts[-1] > BUDGETS["interview"]
    assert span["dropped"] == {"past": 3, "history": 4, "semantic": 1}
    assert [s["name"] for s in span["sections"]] == ["system", "skills", "first", "profile", "docs", "input"]


async def test_recounts_stop_at_the_count_cap():
    # A counter that ignores drops: each recount shrinks only by the measured ratio, then refuses.
    context = assemble("interview", unordered())
    model = CountingLLM(fixed=BUDGETS["interview"] + 1, counts=[], seen=[])
    span = {}
    with pytest.raises(RunError, match="exceeds its input budget"):
        await fit_request(context, online_request(context), model, span)
    assert len(model.counts) == MAX_COUNTS and span["count_calls"] == MAX_COUNTS
    assert span["dropped"]["past"] >= 1 and span["dropped"]["semantic"] == 0  # FTS hits go first


async def test_count_cap_refuses_instead_of_counting_again(monkeypatch):
    monkeypatch.setattr("dss.harness.context.MAX_COUNTS", 1)
    context = assemble("interview", unordered())
    model = CountingLLM(factor=100, counts=[], seen=[])
    with pytest.raises(RunError, match="exceeds its input budget"):
        await fit_request(context, online_request(context), model, {})
    assert len(model.counts) == 1


async def test_counting_failure_is_sanitized_and_refuses():
    context = assemble("interview", unordered())
    model = CountingLLM(count_error="count failed for test-key: Please help", counts=[], seen=[])
    with pytest.raises(RunError) as error:
        await fit_request(context, online_request(context), model, {})
    assert error.value.code == "llm_unavailable" and "test-key" not in error.value.message
    assert error.value.__suppress_context__ and error.value.__cause__ is None


@pytest.mark.parametrize("fixed, failure", [(BUDGETS["interview"] + 1, ""), (None, "count failed for test-key")])
async def test_interview_never_generates_over_budget_or_uncounted(app, build_id, caplog, fixed, failure):
    profile(app, build_id)
    model = CountingLLM(response="Which KPI?", fixed=fixed, count_error=failure, counts=[], seen=[])
    with pytest.raises(RunError) as error:
        await app.state.harness.run("interview", build_id,
            {"config": app.state.settings.get(), "text": "Help our sales director"}, llm=model)
    assert error.value.code == "llm_unavailable" and model.calls == 0
    assert "test-key" not in caplog.text and "test-key" not in json.dumps(spans(app, "interview"))


async def test_interview_records_the_authoritative_count(app, build_id):
    profile(app, build_id)
    model = counting(FakeLLM)(response="Which KPI?")
    await app.state.harness.run("interview", build_id,
        {"config": app.state.settings.get(), "text": "Help our sales director"}, llm=model)
    assert_counted(next(s for s in spans(app, "interview") if s["node"] == "interview"), model)
    assert model.calls == 1


async def test_schema_tools_images_and_repair_participate():
    context = assemble("interview", unordered())
    request = online_request(context)
    with_schema = request_estimate(request)
    request.config.response_json_schema = None
    assert request_estimate(request) < with_schema
    request.config.response_json_schema = {"type": "object", "title": "Out"}
    request.config.tools = [types.Tool(function_declarations=[types.FunctionDeclaration(
        name="mark_ready_for_plan", description="Mark the interview complete. " * 20)])]
    with_tools = request_estimate(request)
    assert with_tools > with_schema
    request.contents[0].parts.append(types.Part.from_bytes(data=b"\x89PNG-bytes", mime_type="image/png"))
    assert request_estimate(request) == with_tools + IMAGE_TOKENS
    head, *rest = counting_contents(request)
    texts = [part.text for part in head.parts]
    assert texts[0] == request.config.system_instruction and '"title": "Out"' in texts[1]
    assert "mark_ready_for_plan" in texts[2] and rest == request.contents
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

    request = online_request(assemble("interview", unordered()))
    assert await count_tokens(Counted(model="gemini-test"), request) == 321
    assert calls[0]["model"] == "gemini-test"
    assert calls[0]["contents"][0].parts[0].text == request.config.system_instruction
    assert calls[0]["contents"][1:] == request.contents
    assert await count_tokens(FakeLLM(), request) is None
