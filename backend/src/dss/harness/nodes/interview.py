"""Interview agent and its bounded, explicit readiness tool."""
from google.adk.agents import LlmAgent
from dss.harness.context import fit_request, interview_context
from dss.harness.guardrails import check_reply
from dss.db import new_id


class ReplyStream:
    """Guard incremental output, withholding enough tail to catch split secrets/markers."""
    def __init__(self, harness, build_id, run_id):
        self.harness, self.build_id, self.run_id = harness, build_id, run_id
        self.message_id = new_id("m")
        self.raw, self.sent = "", 0
        self.forbidden = (harness.models.settings.get().google_api_key.get_secret_value(),
                          "mark_ready_for_plan")
        self.hold = max(len(value) for value in self.forbidden) - 1

    def guard(self, text):
        check_reply(text, self.forbidden)

    async def append(self, text):
        self.raw += text
        if not self.raw.strip():
            return
        self.guard(self.raw)
        await self.flush(max(self.sent, len(self.raw) - self.hold))

    async def flush(self, end):
        if end > self.sent:
            await self.harness.emit(self.build_id, self.run_id, "message.delta",
                                   {"message_id": self.message_id, "text": self.raw[self.sent:end]})
            self.sent = end

    async def finish(self, reply):
        if not self.raw:
            self.raw = reply
        elif not self.raw.endswith(reply):
            # A tool-only final turn may follow streamed introductory text.
            self.raw += reply
        self.guard(self.raw)
        await self.flush(len(self.raw))
        return self.raw


def make_agent(harness, build_id, payload, model, trace, model_error):
    readiness = {"ready": False, "calls": 0}
    context = None

    def mark_ready_for_plan() -> dict:
        """Mark the interview complete when audience, decisions, KPIs and scope are clear."""
        readiness["calls"] += 1
        from dss.spec import requirements as req
        from dss.spec.capabilities import Checker, load_registry
        with harness.db.connect() as conn:
            version = conn.execute('SELECT current_version FROM builds WHERE id=?', (build_id,)).fetchone()[0]
        folder = payload['config'].data_dir / 'builds' / build_id / f'v{version}'
        assessment = req.get(req.inputs(harness.db, build_id, folder), req.load(folder), Checker(load_registry()))
        readiness["ready"] = assessment.state == 'ready'
        return {"ready_for_plan": readiness["ready"]}

    async def before_model(callback_context, llm_request):
        trace.span("interview")
        # Each turn (also the one after a tool call) is counted whole: tools and contents included.
        await fit_request(context, llm_request, model, trace.spans[-1])

    # The start text is the harness's own instruction, not user terms: recency only.
    async def instruction_provider(context_object):
        nonlocal context
        if context is None:
            context = interview_context(harness.db, payload["config"], build_id, payload["text"],
                                        query="" if payload.get("start") else None)
        # Callable instructions bypass ADK's {session_state} interpolation.
        return context

    agent = LlmAgent(
        name="interview", model=model,
        instruction=instruction_provider,
        tools=[mark_ready_for_plan], before_model_callback=before_model,
        on_model_error_callback=model_error)
    return agent, readiness
