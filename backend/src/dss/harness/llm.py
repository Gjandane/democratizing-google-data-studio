"""Stage model routing, bounded transport and complete request counts, without credentials in logs."""
import asyncio
import json
import logging
from contextlib import aclosing, asynccontextmanager, nullcontext
from contextvars import ContextVar

from google import genai
from google.adk.models.google_llm import Gemini
from google.adk.models.base_llm import BaseLlm
from google.genai import types
from google.genai.errors import APIError
from dss.harness import stages
from dss.harness.tracing import provider_call

logger = logging.getLogger(__name__)

# 504 is our own deadline (the client timeout Google enforces): retrying would just wait again.
RETRY_CODES = frozenset({429, 500, 503})
RETRY_DELAY_S = 1.0
# The running agent run's hook for retries (one trace per run); None outside a run.
retry_listener = ContextVar("dss_llm_retry_listener", default=None)


class RetryingGemini(Gemini):
    """Gemini with profile retries (one for interview/routine), before any response only.

    A streamed call that already yielded a chunk is never retried (that would repeat output).
    Gemini's request preprocessing is idempotent, so the retry resends the same request.
    Only the status code is logged: provider messages may echo request text."""

    node: str = 'hello'

    async def generate_content_async(self, llm_request, stream=False):
        session = stages.active_session.get() or stages.session_for(self.node)
        generation = session.stage in stages.GENERATIONS
        retries = session.profile['transport_retries'] if generation else 1
        session.attempt += 1
        session.select(self.model)
        while True:
            for attempt in range(retries + 1):
                yielded = False
                try:
                    if generation:
                        session.clock.remaining(attempt=True)
                    llm_request.model = session.actual_model
                    with provider_call(session, llm_request, session.actual_model, attempt + 1) as call:
                        async with nullcontext() if generation else _request_timeout(session.profile['timeout_s']):
                            async with provider_model(self, session.actual_model) as model:
                                async with aclosing(Gemini.generate_content_async(model, llm_request, stream)) as responses:
                                    async for response in responses:
                                        yielded = True
                                        call.observe(response, llm_request)
                                        if generation:
                                            session.clock.remaining()
                                        stages.check_output(self.node, response, llm_request)
                                        yield response
                    return
                except APIError as exc:
                    if generation:
                        session.clock.remaining()
                    if yielded or exc.code not in RETRY_CODES:
                        raise
                    if attempt == retries:
                        if not generation:
                            raise
                        break
                    code = exc.code
                logger.warning('Model call failed with HTTP %s; retrying', code)
                if (listener := retry_listener.get()) is not None:
                    listener(code)
                delay = RETRY_DELAY_S * 2 ** attempt
                if generation:
                    await session.clock.wait(delay)
                else:
                    await asyncio.sleep(delay)
            if not session.fallback():
                raise session.unavailable() from None


@asynccontextmanager
async def provider_model(model, actual=None):
    """A request-local client with the remaining deadline, including token counting.

    A fresh client avoids racing the timeout of sibling pages. Disable SDK retries: the
    stage owns the retry count and waits. No per-request override can extend the client clock.
    """
    session = stages.active_session.get()
    if session is None or session.stage not in stages.GENERATIONS:
        yield model if actual is None or actual == model.model else model.model_copy(update={'model': actual})
        return
    timeout = max(1, int(session.clock.remaining(attempt=True) * 1000))
    client = genai.Client(api_key=model.api_client._api_client.api_key, http_options=types.HttpOptions(
        timeout=timeout, retry_options=types.HttpRetryOptions(attempts=1)))
    try:
        yield Gemini(model=actual or model.model, client=client)
    finally:
        await client.aio.aclose()
        client.close()


class ProfiledModel(BaseLlm):
    """ADK and direct generation share explicit profile configuration and hard cutoff stops."""
    wrapped: BaseLlm
    node: str

    @property
    def capabilities(self):
        return self.wrapped.capabilities

    async def count_request_tokens(self, request):
        return await count_tokens(self.wrapped, request)

    async def generate_content_async(self, llm_request, stream=False):
        session = stages.configure(self.node, llm_request)
        generation = session.stage in stages.GENERATIONS
        try:
            # Generation clocks also cover validation/repairs in the enclosing action/page.
            with session.activate():
                scope = session.clock.scope() if generation else nullcontext() if isinstance(
                    self.wrapped, RetryingGemini) else _request_timeout(session.profile['timeout_s'])
                async with scope:
                    if generation:
                        session.clock.remaining(attempt=True)
                    real = isinstance(self.wrapped, RetryingGemini)
                    if not real:
                        session.attempt += 1
                        session.actual_model = self.wrapped.model
                    with nullcontext() if real else provider_call(session, llm_request, self.wrapped.model) as call:
                        async with aclosing(self.wrapped.generate_content_async(llm_request, stream)) as responses:
                            async for response in responses:
                                if call is not None:
                                    call.observe(response, llm_request)
                                if generation:
                                    session.clock.remaining()
                                stages.check_output(self.node, response, llm_request)
                                yield response
        except Exception as exc:
            stages.remember_failure(exc)
            raise


@asynccontextmanager
async def _request_timeout(seconds):
    async with asyncio.timeout(seconds):
        yield


def bind_model(node, model):
    return model if isinstance(model, ProfiledModel) and model.node == node else ProfiledModel(
        model=model.model, wrapped=model, node=node)


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
        session = stages.active_session.get()
        actual = session.select(model.model) if session else model.model
        llm_request.model = actual
        async with provider_model(model, actual) as bounded:
            response = await bounded.api_client.aio.models.count_tokens(
                model=actual, contents=counting_contents(llm_request))
        count = response.total_tokens
    else:
        return None
    if count is None and isinstance(model, ProfiledModel):
        return None
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError("The token counter returned no count")
    return count


class ModelRouter:
    def __init__(self, settings, model_lister=None):
        self.settings = settings
        self.model_lister = model_lister or list_models
        config = settings.get()
        self.planner_model = config.stages['native_planning']['model']
        self.worker_model = config.stages['routine']['model']
        self.available = None

    async def refresh(self):
        config = self.settings.get()
        self.planner_model = config.stages['native_planning']['model']
        self.worker_model = config.stages['routine']['model']
        self.available = None
        key = config.google_api_key.get_secret_value()
        if not key:
            return
        try:
            available = {name.removeprefix("models/") for name in await self.model_lister(key)}
        except Exception:
            logger.warning("Could not list models; check API credentials and connectivity")
            return
        self.available = available
        if self.planner_model not in available:
            logger.warning("Planner model unavailable; using worker model for plan and spec")
            self.planner_model = self.worker_model

    def model_for(self, node):
        config = self.config()
        selected = stages.snapshot(config)['stages'][stages.stage_for(node)]['model']
        fallback = stages.snapshot(config)['fallback_model']
        run = stages.execution.get()
        available = run.available if run else self.available
        if run and selected not in stages.MODELS:
            raise stages.session_for(node).unavailable()
        if available is not None and selected not in available and fallback in available:
            return fallback
        if available is not None and selected not in available:
            raise stages.session_for(node).unavailable()
        return selected

    def config(self):
        run = stages.execution.get()
        return run.config if run else self.settings.get()

    def timeout_ms(self, node):
        """google-genai sends the client timeout to Google as the server deadline (a 504 when
        exceeded), and a per-request timeout does not override it: set it on the client."""
        return stages.snapshot(self.config())['stages'][stages.stage_for(node)]['timeout_s'] * 1000

    def llm_for(self, node):
        key = self.config().google_api_key.get_secret_value()
        if not key:
            from dss.harness.guardrails import RunError
            raise RunError("llm_unavailable", "Set the Google API key in Settings", 503)
        return RetryingGemini(model=self.model_for(node), node=node, client=genai.Client(
            api_key=key, http_options=types.HttpOptions(timeout=self.timeout_ms(node),
                retry_options=types.HttpRetryOptions(attempts=1))))
