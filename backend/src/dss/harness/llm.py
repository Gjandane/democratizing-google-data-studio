"""Model availability, planner/worker routing and request token counts, without logging credentials."""
import asyncio
import json
import logging
from contextlib import aclosing
from contextvars import ContextVar

from google import genai
from google.adk.models.google_llm import Gemini
from google.genai import types
from google.genai.errors import APIError

logger = logging.getLogger(__name__)

PLANNER_NODES = frozenset({"plan", "spec"})
PLANNER_TIMEOUT_MS, WORKER_TIMEOUT_MS = 120_000, 30_000
# 504 is our own deadline (the client timeout Google enforces): retrying would just wait again.
RETRY_CODES = frozenset({429, 500, 503})
RETRY_DELAY_S = 1.0
# The running agent run's hook for retries (one trace per run); None outside a run.
retry_listener = ContextVar("dss_llm_retry_listener", default=None)


class RetryingGemini(Gemini):
    """Gemini with one retry when a call fails with 429, 500 or 503 before any response.

    A streamed call that already yielded a chunk is never retried (that would repeat output).
    Gemini's request preprocessing is idempotent, so the retry resends the same request.
    Only the status code is logged: provider messages may echo request text."""

    async def generate_content_async(self, llm_request, stream=False):
        try:
            yielded = False
            # aclosing: an early close (a cancelled stream) closes the provider stream now.
            async with aclosing(super().generate_content_async(llm_request, stream)) as responses:
                async for response in responses:
                    yielded = True
                    yield response
            return
        except APIError as exc:
            if yielded or exc.code not in RETRY_CODES:
                raise
            code = exc.code
        logger.warning("Model call failed with HTTP %s; retrying once", code)
        if (listener := retry_listener.get()) is not None:
            listener(code)
        await asyncio.sleep(RETRY_DELAY_S)
        async with aclosing(super().generate_content_async(llm_request, stream)) as responses:
            async for response in responses:
                yield response


async def list_models(key):
    def fetch():
        with genai.Client(api_key=key, http_options=types.HttpOptions(timeout=10000)) as client:
            return [model.name.removeprefix("models/") for model in client.models.list()]
    return await asyncio.to_thread(fetch)


def counting_contents(llm_request):
    """The whole effective request as countable contents. The Developer API's count_tokens
    takes contents only, so the system instruction (with any repair text), response schemas
    and tool declarations go first as text parts; images stay as their own parts."""
    config = llm_request.config
    folded = [str(config.system_instruction or "")]
    for schema in (config.response_json_schema, config.response_schema):
        if schema is not None:
            folded.append(json.dumps(schema, default=str) if isinstance(schema, dict) else schema.model_dump_json(exclude_none=True))
    folded += [tool.model_dump_json(exclude_none=True) for tool in config.tools or []]
    head = types.Content(role="user", parts=[types.Part(text=text) for text in folded if text])
    return [head, *(llm_request.contents or [])]


async def count_tokens(model, llm_request):
    """Input tokens of the complete request from the configured model's token counter.

    A model may inject its own async `count_request_tokens(llm_request)` (tests). Other
    non-Gemini models (FakeLLM) have no counter: None, so callers use the offline estimate.
    Counting is not generation: it adds no model call and no tool use.
    """
    counter = getattr(model, "count_request_tokens", None)
    if counter is not None:
        count = await counter(llm_request)
    elif isinstance(model, Gemini):
        response = await model.api_client.aio.models.count_tokens(
            model=llm_request.model or model.model, contents=counting_contents(llm_request))
        count = response.total_tokens
    else:
        return None
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError("The token counter returned no count")
    return count


class ModelRouter:
    def __init__(self, settings, model_lister=None):
        self.settings = settings
        self.model_lister = model_lister or list_models
        self.planner_model = settings.get().planner_model
        self.worker_model = settings.get().worker_model

    async def refresh(self):
        config = self.settings.get()
        self.planner_model, self.worker_model = config.planner_model, config.worker_model
        key = config.google_api_key.get_secret_value()
        if not key:
            return
        try:
            available = {name.removeprefix("models/") for name in await self.model_lister(key)}
        except Exception:
            logger.warning("Could not list models; check API credentials and connectivity")
            return
        if self.planner_model not in available:
            logger.warning("Planner model unavailable; using worker model for plan and spec")
            self.planner_model = self.worker_model

    def model_for(self, node):
        return self.planner_model if node in PLANNER_NODES else self.worker_model

    @staticmethod
    def timeout_ms(node):
        """google-genai sends the client timeout to Google as the server deadline (a 504 when
        exceeded), and a per-request timeout does not override it: set it on the client."""
        return PLANNER_TIMEOUT_MS if node in PLANNER_NODES else WORKER_TIMEOUT_MS

    def llm_for(self, node):
        key = self.settings.get().google_api_key.get_secret_value()
        if not key:
            from dss.harness.guardrails import RunError
            raise RunError("llm_unavailable", "Set the Google API key in Settings", 503)
        return RetryingGemini(model=self.model_for(node), client=genai.Client(
            api_key=key, http_options=types.HttpOptions(timeout=self.timeout_ms(node))))
