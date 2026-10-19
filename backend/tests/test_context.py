"""Working memory assembly: per-node section order, budget drop order and trace token counts."""
import json
from pathlib import Path
import pytest
from dss.db import new_id, now
from dss.harness.context import (BUDGETS, ORDER, SEPARATOR, Section, assemble, interview_context, plan_context,
                                 revise_context, spec_context, tokens)
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
