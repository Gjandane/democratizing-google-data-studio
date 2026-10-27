"""run.usage: running token totals per run on the build's stream (contracts/api.md 1.2)."""
import json
import pytest
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


@pytest.mark.parametrize('billed,measured,enforced,input_count', [(10, 20, 30, 10), (None, 20, 30, 20),
                                                               (None, None, 30, 30), (0, 20, 30, 0)])
def test_call_cost_input_precedence_and_long_context(monkeypatch, billed, measured, enforced, input_count):
    from types import SimpleNamespace
    from dss.harness import stages
    from dss.harness.tracing import StageCall
    from google.adk.models.llm_request import LlmRequest
    monkeypatch.setitem(stages.MODELS, 'priced', {'price': {
        'input_usd_per_mtok': 2, 'output_usd_per_mtok': 5, 'long_context_over': 20,
        'long_input_usd_per_mtok': 4, 'long_output_usd_per_mtok': 10, 'checked_on': '2026-10-26'}})
    session = stages.StageSession('blueprint')
    session.attempt = 1
    session.request_counts = {'input_measured': measured, 'input_enforced': enforced, 'input_limit': 100}
    call = StageCall(session, LlmRequest(), 'priced', 1)
    call.observe(SimpleNamespace(usage_metadata=types.GenerateContentResponseUsageMetadata(
        prompt_token_count=billed, candidates_token_count=4, thoughts_token_count=6),
        finish_reason=types.FinishReason.STOP, error_code=None, partial=False,
        content=types.Content(parts=[types.Part(text='{}')])), LlmRequest())
    call.finish()
    rate = 2 if input_count <= 20 else 4
    assert call.value['cost_usd_estimate'] == (input_count * rate + 10 * rate * 2.5) / 1_000_000


@pytest.mark.parametrize('model,answer,thinking,expected', [
    ('unpriced', 4, 6, None), ('gemini-3.8-flash', None, 6, None),
    ('gemini-3.8-flash', 4, None, None), ('gemini-3.8-flash', 0, 0, 0.000075)])
def test_unknown_usage_and_prices_are_not_zero(model, answer, thinking, expected):
    from dss.harness.tracing import cost, cost_total
    assert cost(model, 100, answer, thinking) == expected
    assert cost_total([None, 0.25, 0]) == (0.25, False)
    assert cost_total([None]) == (None, False)
    assert cost_total([]) == (0, True)


async def test_call_records_do_not_change_usage_totals(client, app, build_id):
    from dss.harness import stages
    class Thinking(FakeLLM):
        model: str = stages.FLASH
        async def generate_content_async(self, req, stream=False):
            async for item in super().generate_content_async(req, stream):
                item.usage_metadata.thoughts_token_count = 17
                yield item
    result = await app.state.harness.run('hello', build_id, {}, llm=Thinking())
    usage = check_stream(app, build_id, result['run_id'], 'hello')
    assert (usage[-1]['input_tokens'], usage[-1]['output_tokens']) == (5, 2)
    call = client.get(f"/api/traces/{result['run_id']}/calls").json()['calls'][0]
    assert call['thinking_tokens'] == 17 and call['output_tokens'] == 2 and call['input_billed'] == 5
    assert call['cost_usd_estimate'] == (5 * 0.75 + 19 * 3.75) / 1_000_000


async def test_local_invalid_extraction_keeps_usage_and_marks_received_call(client, app, build_id):
    from test_references import output, item, payload, image
    from dss.harness.guardrails import RunError
    with pytest.raises(RunError) as error:
        await app.state.harness.run('reference_extract', build_id, payload(app, [image()]),
            llm=FakeLLM(response=output([item(box=(900, 0, 200, 100))])))
    assert error.value.code == 'llm_unavailable'
    with app.state.db.connect() as conn:
        run_id = conn.execute('SELECT run_id FROM traces ORDER BY rowid DESC LIMIT 1').fetchone()[0]
    usage = check_stream(app, build_id, run_id, 'reference_extract')
    assert (usage[-1]['input_tokens'], usage[-1]['output_tokens']) == (10, 4)  # both calls, repair included
    calls = client.get(f'/api/traces/{run_id}/calls').json()['calls']
    # 26.2: the stage's one validation repair is a second received, invalid call.
    assert len(calls) == 2 and [c['outcome'] for c in calls] == ['invalid', 'invalid']
    assert all(c['input_billed'] == 5 and c['output_tokens'] == 2 for c in calls)
