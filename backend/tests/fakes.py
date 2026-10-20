"""Offline model implementing the actual ADK BaseLlm interface."""
import asyncio
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types


class FakeLLM(BaseLlm):
    model: str = "fake-worker"
    calls: int = 0
    response: str = "Hello!"
    fail: bool = False
    started: asyncio.Event | None = None
    release: asyncio.Event | None = None

    async def generate_content_async(self, llm_request, stream=False):
        self.calls += 1
        if self.started:
            self.started.set()
        if self.release:
            await self.release.wait()
        if self.fail:
            raise RuntimeError("provider error containing sensitive content")
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=self.response)]),
                          usage_metadata=types.GenerateContentResponseUsageMetadata(
                              prompt_token_count=5, candidates_token_count=2))


async def fake_models(key):
    return ["models/gemini-3.8-flash", "models/gemini-4-argon"]


def ready_fixture(app, build_id, folder):
    """Establish real deterministic proof for directly written, intent-free fixtures."""
    from dss.spec import capabilities, requirements as req
    snapshot, ledger = req.inputs(app.state.db, build_id, folder), req.load(folder)
    checker = capabilities.Checker(capabilities.load_registry())
    assert not req.new_sources(snapshot, ledger), 'Use the assessment Workflow for new intent'
    assessment = req.evaluate(snapshot, ledger, checker)
    assert assessment.state == 'ready', assessment
    assert not req.coverage_errors(snapshot, ledger, checker)
    req.save(folder, ledger, assessment)
