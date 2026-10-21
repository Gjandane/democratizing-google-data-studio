"""run.usage: running token totals per run on the build's stream (contracts/api.md 1.2)."""
import json
from pathlib import Path

from google.genai import types

from fakes import FakeLLM
from test_audit_style import setup as audit_setup  # noqa: F401  (fixture)
from test_thin_slice import thin, load  # noqa: F401  (fixture)
from test_research import setup as research_setup  # noqa: F401  (fixture)

FIXTURE = Path(__file__).parents[2] / "contracts/fixtures/api/events.usage.sse"


def _fixture_types():
    block = [b for b in FIXTURE.read_text().split("\n\n") if "event: run.usage" in b][0]
    return {k: type(v) for k, v in json.loads(block.split("data: ", 1)[1]).items()}


FIXTURE_TYPES = _fixture_types()


def events(app, build_id):
    with app.state.db.connect() as conn:
        return [(r[0], json.loads(r[1])) for r in conn.execute(
            "SELECT kind,payload_json FROM events WHERE build_id=? ORDER BY rowid", (build_id,))]


def trace_row(app, run_id):
    with app.state.db.connect() as conn:
        return conn.execute("SELECT input_tokens,output_tokens FROM traces WHERE run_id=?", (run_id,)).fetchone()


def check_stream(app, build_id, run_id, node):
    """One run: usage between started and finished, non-decreasing, equal to the trace."""
    stream = [(k, p) for k, p in events(app, build_id) if p.get("run_id") == run_id]
    kinds = [k for k, _ in stream]
    usage = [p for k, p in stream if k == "run.usage"]
    assert usage, kinds
    assert kinds.index("run.started") < kinds.index("run.usage") and kinds[-1] == "run.finished"
    assert max(i for i, k in enumerate(kinds) if k == "run.usage") < kinds.index("run.finished")
    assert all(p["node"] == node for p in usage)
    for p in usage:
        assert {k: type(v) for k, v in p.items()} == FIXTURE_TYPES
    pairs = [(p["input_tokens"], p["output_tokens"]) for p in usage]
    assert all(a[0] <= b[0] and a[1] <= b[1] for a, b in zip(pairs, pairs[1:]))
    row = trace_row(app, run_id)
    assert row[0] > 0 and row[1] > 0 and (row[0], row[1]) == pairs[-1]
    return usage


def test_payload_matches_fixture_keys_and_types():
    blocks = [b for b in FIXTURE.read_text().split("\n\n") if "event: run.usage" in b]
    expected = {k: type(v) for k, v in json.loads(blocks[0].split("data: ", 1)[1]).items()}
    assert expected == {"run_id": str, "node": str, "input_tokens": int, "output_tokens": int}


async def test_revise_run_emits_usage(client, app, build_id, monkeypatch):
    from test_revise import seed_revision, FakeBigQuery, RevisionModel, response, op
    app, bid, folder, spec, service, _ = seed_revision(app, build_id, monkeypatch)
    result = await app.state.harness.run("revise", bid, {"config": app.state.settings.get(),
        "factory": lambda config: service, "comments": [{"component_id": "p1_revenue", "text": "bigger"}]},
        llm=RevisionModel(delegate=FakeLLM(response=response([op("/pages/0/components/0/grid/w", 8), op("/pages/0/components/1/grid/row", 26)]))))
    check_stream(app, bid, result["run_id"], "revise")


async def test_audit_and_style_runs_emit_usage(client, app, build_id, audit_setup):
    from test_audit_style import findings, reference, style_payload
    result = await app.state.harness.run("ux_audit", build_id, {"config": app.state.settings.get()},
                                         llm=FakeLLM(response=findings(("p1_revenue", "high"))))
    check_stream(app, build_id, result["run_id"], "ux_audit")
    result = await app.state.harness.run("reference_extract", build_id, style_payload(app), llm=FakeLLM(response=reference()))
    check_stream(app, build_id, result["run_id"], "reference_extract")


def test_research_run_emits_usage(research_setup, monkeypatch):
    from test_research import run_direct, ResearchLLM
    client, app, build_id, *_ = research_setup
    original = ResearchLLM.generate_content_async

    async def with_usage(self, llm_request, stream=False):
        async for item in original(self, llm_request, stream):
            item.usage_metadata = types.GenerateContentResponseUsageMetadata(prompt_token_count=4, candidates_token_count=1)
            yield item
    monkeypatch.setattr(ResearchLLM, "generate_content_async", with_usage)
    result = run_direct(research_setup)
    usage = check_stream(app, build_id, result["run_id"], "research")
    assert len(usage) == 2


def test_recipe_run_without_model_call_emits_no_usage(thin):
    client, app, build_id, _ = thin
    from test_thin_slice import load_checked
    load_checked(client, build_id)
    assert client.post(f"/api/builds/{build_id}/recipe").status_code == 200
    stream = events(app, build_id)
    assert ("recipe" in [p.get("node") for k, p in stream if k == "run.started"])
    assert "run.usage" not in [k for k, _ in stream]
