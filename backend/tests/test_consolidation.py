import asyncio
import json
import logging
import time

import pytest
from fastapi.testclient import TestClient

from dss.config import Config
from dss.db import now
from dss.harness import context as working_memory
from dss.harness.nodes.intake import write_doc
from dss.harness.nodes.publish import publish
from dss.main import create_app
from dss.memory.semantic import SemanticNavigator, parse_concept
from fakes import FakeLLM, fake_models
from test_thin_slice import thin, load, wait_done

OK = {"status": "ok", "report_url": "https://datastudio.google.com/reporting/r1"}


class FactsLLM(FakeLLM):
    responses: list = []
    requests: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(str(llm_request.config.system_instruction))
        if self.responses:
            self.response = self.responses.pop(0)
        async for response in super().generate_content_async(llm_request, stream):
            yield response


def facts(*items):
    return json.dumps({"facts": [dict(zip(("slug", "type", "title", "statement"), item)) for item in items]})


@pytest.fixture
def every_one(tmp_path):
    app = create_app(Config(data_dir=tmp_path, google_api_key="test-key", consolidate_every=1), model_lister=fake_models)
    with TestClient(app) as client:
        yield client, app


def use(app, monkeypatch, fake):
    nodes = []
    monkeypatch.setattr(app.state.models, "llm_for", lambda node: nodes.append(node) or fake)
    return nodes


def new_build(app, n, *, docs=True):
    bid = f"b_{n:012x}"
    with app.state.db.connect() as conn:
        conn.execute("INSERT INTO builds(id,title,archetype,mode,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                     (bid, f"Build {n}", "executive", "data", "build", now(), now()))
        conn.execute("INSERT INTO versions VALUES(?,?,?,?,?,?)", (bid, 1, "building", 1, None, now()))
    if docs:
        folder = app.state.settings.get().data_dir / "builds" / bid / "v1/docs"
        folder.mkdir(parents=True)
        write_doc(folder / "brief.md", {"type": "Dashboard Brief", "title": "Dashboard Brief"}, f"Brief {n}: weekly revenue for the CFO.")
        write_doc(folder / "design.md", {"type": "Design Direction", "title": "Design Direction"}, f"Design {n}: dark theme, few charts.")
        write_doc(folder / "decisions.md", {"type": "Design Decisions", "title": "Design decisions"}, f"# Design decisions\n- Decision {n}: bars over pies.\n")
    return bid


async def finish(app, n, *, docs=True, result=OK):
    bid = new_build(app, n, docs=docs)
    await publish(app.state, bid, f"r_{n:012x}", 1, result)
    await settle(app)
    return bid


async def settle(app):
    while app.state.engine_tasks:
        await asyncio.gather(*app.state.engine_tasks)


def counter(app):
    with app.state.db.connect() as conn:
        return dict(conn.execute("SELECT chats_since,last_run_at FROM consolidation").fetchone())


def traces(app):
    with app.state.db.connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM traces WHERE node='consolidate' ORDER BY rowid")]


def user_dir(app):
    return app.state.settings.get().data_dir / "knowledge/user"


def log_entries(app):
    lines = parse_concept("user/log.md", (user_dir(app) / "log.md").read_text(encoding="utf-8")).text.splitlines()
    return [line for line in lines if line.startswith("- ")]


def test_env_name_and_default(monkeypatch):
    monkeypatch.setenv("DSS_CONSOLIDATE_EVERY", "3")
    assert Config.from_env().consolidate_every == 3
    assert Config().consolidate_every == 5
    with pytest.raises(ValueError):
        Config(consolidate_every=0)


async def test_every_five_done_builds(client, app, monkeypatch):
    fake = FactsLLM(responses=[facts(
        ("dark-theme", "User Preference", "Prefers a dark theme", "The user prefers dark dashboards with few charts."),
        ("bars-over-pies", "Design Decision", "Bars over pies", "Use bar charts instead of pie charts."))])
    nodes = use(app, monkeypatch, fake)
    for n in range(1, 5):
        await finish(app, n)
        assert counter(app)["chats_since"] == n and fake.calls == 0
        assert not (app.state.settings.get().data_dir / "knowledge").exists() and not traces(app)
    # A failed build never counts.
    await finish(app, 9, result={"status": "failed", "report_url": None})
    assert counter(app)["chats_since"] == 4 and fake.calls == 0
    await finish(app, 5)
    assert fake.calls == 1 and nodes == ["consolidate"]
    prompt = fake.requests[0]
    assert all(f"Brief {n}" in prompt and f"Decision {n}" in prompt and f"Design {n}" in prompt for n in range(1, 6))
    assert "Brief 9" not in prompt and "Current user facts" in prompt
    assert prompt.index("Brief 5") < prompt.index("Brief 1")  # newest first: the budget drops the oldest
    files = sorted(path.name for path in user_dir(app).glob("*.md"))
    assert files == ["bars-over-pies.md", "dark-theme.md", "index.md", "log.md"]
    for name in files:
        concept = parse_concept(f"user/{name}", (user_dir(app) / name).read_text(encoding="utf-8"))
        assert concept.metadata["type"].strip()
    navigator = SemanticNavigator(runtime_root=app.state.settings.get().data_dir / "knowledge")
    listed = navigator.list_folder("user")
    assert [c.path for c in listed] == ["user/bars-over-pies.md", "user/dark-theme.md"]
    assert {c.metadata["type"] for c in listed} == {"User Preference", "Design Decision"}
    index = navigator.read("user/index.md").text
    assert "dark dashboards with few charts" in index
    entries = log_entries(app)
    assert len(entries) == 1 and "consolidated 5 done builds" in entries[0] and "added: dark-theme, bars-over-pies; changed: none" in entries[0]
    state = counter(app)
    assert state["chats_since"] == 0 and state["last_run_at"]
    [trace] = traces(app)
    assert trace["status"] == "ok" and trace["build_id"] is None and trace["model"] == "fake-worker"
    spans = json.loads(trace["spans_json"])
    assert [s["node"] for s in spans] == ["consolidate", "consolidate_write", "guardrail"]
    assert [s["kind"] for s in spans[0]["sections"]] == ["system", "semantic", "past", "input"]
    # The next plan's working memory reads the consolidated facts.
    user_facts = working_memory._user_facts(working_memory._navigator(app.state.settings.get()))
    assert [s.name for s in user_facts] == ["user/bars-over-pies.md", "user/dark-theme.md"]


async def test_every_done_build_with_one(every_one, monkeypatch):
    client, app = every_one
    fake = FactsLLM(responses=[facts((f"fact-{n}", "User Preference", f"Fact {n}", f"Statement {n}.")) for n in range(3)])
    use(app, monkeypatch, fake)
    for n in range(3):
        await finish(app, n + 1)
        assert fake.calls == n + 1 and counter(app)["chats_since"] == 0
        assert f"Brief {n + 1}" in fake.requests[n] and f"Brief {n}:" not in fake.requests[n]
    entries = log_entries(app)
    assert len(entries) == 3 and "fact-2" in entries[0] and "fact-0" in entries[2]  # prepended
    index = (user_dir(app) / "index.md").read_text(encoding="utf-8")
    assert all(f"[Fact {n}](fact-{n}.md)" in index for n in range(3))
    assert "Statement 0" in fake.requests[1]  # current facts reach the next consolidation
    assert [t["status"] for t in traces(app)] == ["ok"] * 3


async def test_changed_fact_keeps_previously_with_date(every_one, monkeypatch):
    client, app = every_one
    fake = FactsLLM(responses=[
        facts(("chart-style", "User Preference", "Chart style", "Prefers pie charts.")),
        facts(("chart-style", "User Preference", "Chart style", "Prefers bar charts.")),
        facts(("chart-style", "User Preference", "Chart style", "Prefers bar charts.")),
        facts(("chart-style", "User Preference", "Chart style", "Prefers line charts."))])
    use(app, monkeypatch, fake)
    await finish(app, 1)
    path = user_dir(app) / "chart-style.md"
    concept = parse_concept("user/chart-style.md", path.read_text(encoding="utf-8"))
    assert concept.metadata["updated"] == now()[:10] and "Previously" not in concept.text
    path.write_text(path.read_text(encoding="utf-8").replace(now()[:10], "2026-10-01"), encoding="utf-8")
    await finish(app, 2)
    text = path.read_text(encoding="utf-8")
    assert "\n\nPrefers bar charts.\n" in text and "## Previously\n\n- 2026-10-01: Prefers pie charts.\n" in text
    assert parse_concept("user/chart-style.md", text).metadata["updated"] == now()[:10]
    await finish(app, 3)
    assert path.read_text(encoding="utf-8") == text  # an unchanged fact is not rewritten
    assert "changed: none" in log_entries(app)[0]
    await finish(app, 4)
    text = path.read_text(encoding="utf-8")
    assert "\n\nPrefers line charts.\n" in text
    assert f"- {now()[:10]}: Prefers bar charts.\n- 2026-10-01: Prefers pie charts.\n" in text
    assert "changed: chart-style" in log_entries(app)[0]
    assert "Prefers line charts." in (user_dir(app) / "index.md").read_text(encoding="utf-8")


async def test_publish_does_not_wait(every_one, monkeypatch):
    client, app = every_one
    started, release = asyncio.Event(), asyncio.Event()
    fake = FactsLLM(responses=[facts(("wait", "Design Decision", "Waited", "Consolidated later."))],
                    started=started, release=release)
    use(app, monkeypatch, fake)
    bid = new_build(app, 1)
    await asyncio.wait_for(publish(app.state, bid, "r_000000000001", 1, OK), 2)
    await asyncio.wait_for(started.wait(), 3)
    assert client.get(f"/api/builds/{bid}").json()["stage"] == "done"
    with app.state.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM events WHERE kind='build.finished' AND build_id=?", (bid,)).fetchone()[0] == 1
    assert app.state.engine_tasks and not user_dir(app).exists() and counter(app)["chats_since"] == 1
    release.set()
    await settle(app)
    assert (user_dir(app) / "wait.md").is_file() and counter(app)["chats_since"] == 0


async def test_build_done_during_a_run_stays_counted(every_one, monkeypatch):
    client, app = every_one
    started, release = asyncio.Event(), asyncio.Event()
    fake = FactsLLM(responses=[facts(("first", "User Preference", "First", "One.")),
                               facts(("second", "User Preference", "Second", "Two."))], started=started, release=release)
    use(app, monkeypatch, fake)
    await publish(app.state, new_build(app, 1), "r_000000000001", 1, OK)
    await asyncio.wait_for(started.wait(), 3)
    await publish(app.state, new_build(app, 2), "r_000000000002", 1, OK)
    assert counter(app)["chats_since"] == 2
    release.set()
    await settle(app)
    assert fake.calls == 2 and "Brief 1:" in fake.requests[0] and "Brief 2:" not in fake.requests[0]
    assert "Brief 2:" in fake.requests[1] and "Brief 1:" not in fake.requests[1]
    assert counter(app)["chats_since"] == 0 and len(log_entries(app)) == 2


def test_budget_drops_the_oldest_builds_first(app, client):
    config = app.state.settings.get()
    builds = []
    for n in range(12, 0, -1):  # newest first
        bid = new_build(app, n)
        for name in ("brief", "design", "decisions"):
            write_doc(config.data_dir / "builds" / bid / f"v1/docs/{name}.md", {"type": name}, f"{name} {n}: " + "b" * 5000)
        builds.append({"build_id": bid, "title": f"Build {n}", "archetype": "executive", "version": 1, "date": "2026-10-19"})
    context = working_memory.consolidate_context(config, builds)
    budget = working_memory.BUDGETS["consolidate"] - working_memory.RESERVES["consolidate"]
    assert working_memory.tokens(context) <= budget and context.dropped["past"] >= 1
    kept = context.sections[2].items
    assert len(kept) + context.dropped["past"] == 12 and '"Build 12"' in kept[0]
    assert all(f'"Build {n}"' not in context for n in range(1, context.dropped["past"] + 1))
    assert "brief 12: " + "b" * 2900 in context and "b" * 5000 not in context and "[truncated]" in context


async def test_failures_keep_the_counter_and_retry(every_one, monkeypatch, caplog):
    client, app = every_one
    caplog.set_level(logging.WARNING)
    failing = (FakeLLM(fail=True), FakeLLM(response="not json"), FakeLLM(response=facts(("x", "Opinion", "X", "Y."))),
               FakeLLM(response=facts(("x", "User Preference", "Leak", "Key test-key."))))
    for n, fake in enumerate(failing, 1):
        use(app, monkeypatch, fake)
        await finish(app, n)
        assert fake.calls == 1 and not user_dir(app).exists()
    assert counter(app)["chats_since"] == 4 and [t["error"] for t in traces(app)] == ["llm_unavailable"] * 4
    assert "sensitive content" not in caplog.text and "test-key" not in caplog.text and "not json" not in caplog.text
    fake = FactsLLM(responses=[facts(("retry", "User Preference", "Retry", "Consolidated after retries."))])
    use(app, monkeypatch, fake)
    await finish(app, 10)
    assert counter(app)["chats_since"] == 0
    assert all(f"Brief {n}:" in fake.requests[0] for n in (1, 2, 3, 4, 10))
    assert "consolidated 5 done builds" in log_entries(app)[0]


async def test_builds_without_documents_are_skipped(every_one, monkeypatch):
    client, app = every_one
    fake = FactsLLM()
    use(app, monkeypatch, fake)
    await finish(app, 1, docs=False)
    assert fake.calls == 0 and counter(app)["chats_since"] == 0 and not user_dir(app).exists()
    [trace] = traces(app)
    assert trace["status"] == "ok" and json.loads(trace["spans_json"])[0]["skipped"] == "no build documents"


async def test_fact_text_cannot_escape_or_inject_links(every_one, monkeypatch):
    client, app = every_one
    use(app, monkeypatch, FactsLLM(responses=[facts(
        ("../../../evil", "User Preference", "[Evil](../catalog/bar.md)", "See [catalog](../catalog/bar.md) and [x](missing.md)."),
        ("index", "Design Decision", "Index", "Not the index."),
        ("con", "Design Decision", "Con", "Not a device."),
        ("Regional  Sales!", "User Preference", "Regional", "Line one.\n## Previously\n- fake"),
        ("préférence", "User Preference", "Préférence", "Accents stay in the text."),
        ("売上", "User Preference", "売上", "Only the slug is ASCII."))]))
    await finish(app, 1)
    names = sorted(path.name for path in user_dir(app).glob("*.md"))
    hashed = "fact-" + __import__("hashlib").sha1("売上".encode("utf-8")).hexdigest()[:8] + ".md"
    assert names == sorted(["evil.md", "fact-con.md", "fact-index.md", "index.md", "log.md", "pr-f-rence.md",
                            "regional-sales.md", hashed])
    index = (user_dir(app) / "index.md").read_text(encoding="utf-8")
    assert f"]({hashed})" in index and "%" not in index
    assert not (app.state.settings.get().data_dir / "catalog").exists()
    listed = SemanticNavigator(runtime_root=app.state.settings.get().data_dir / "knowledge").list_folder("user")
    assert [c.path for c in listed] == ["user/" + name for name in names if name not in ("index.md", "log.md")]
    regional = (user_dir(app) / "regional-sales.md").read_text(encoding="utf-8")
    assert "Line one. ## Previously - fake" in regional and "\n## Previously" not in regional


def test_engine_run_consolidates_in_the_background(thin, monkeypatch):
    client, app, bid, folder = thin
    monkeypatch.setattr(app.state.settings, "defaults", app.state.settings.defaults.model_copy(update={"consolidate_every": 1}))
    fake = FactsLLM(responses=[facts(("from-run", "User Preference", "From a run", "Consolidated after an engine run."))])
    use(app, monkeypatch, fake)
    load(client, bid)
    (folder / "docs").mkdir(exist_ok=True)
    write_doc(folder / "docs/brief.md", {"type": "Dashboard Brief", "title": "Dashboard Brief"}, "Brief from the run.")
    assert client.post(f"/api/builds/{bid}/recipe").status_code == 200
    assert client.post(f"/api/builds/{bid}/run").status_code == 202
    assert wait_done(client, bid)["stage"] == "done"
    for _ in range(300):
        if app.state.settings.get().data_dir.joinpath("knowledge/user/from-run.md").is_file() and not app.state.engine_tasks:
            break
        time.sleep(.02)
    assert "Brief from the run." in fake.requests[0] and counter(app)["chats_since"] == 0
    assert [t["status"] for t in traces(app)] == ["ok"]


async def test_consolidation_counts_the_whole_request(every_one, monkeypatch):
    from test_context import assert_counted, counting
    _, app = every_one
    fake = counting(FactsLLM)(responses=[facts(("dark-theme", "User Preference", "Dark", "Prefers dark dashboards."))], requests=[])
    use(app, monkeypatch, fake)
    await finish(app, 1)
    [trace] = traces(app)
    assert trace["status"] == "ok" and fake.calls == 1
    assert_counted(json.loads(trace["spans_json"])[0], fake)
