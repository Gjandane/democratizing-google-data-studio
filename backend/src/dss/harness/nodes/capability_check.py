"""One optional, fully counted extraction followed by a code-owned assessment."""
import json

from google.adk.agents import LlmAgent
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import ValidationError

from dss.harness.context import capability_context, fit_request, tokens
from dss.harness.guardrails import RunError, check_reply
from dss.harness.nodes.style_extract import provider_schema
from dss.spec import requirements as req
from dss.spec.capabilities import Checker, load_registry

MAX_OUTPUT_TOKENS = 4000
SCOPE_MESSAGE = "Reduce the request scope (at most 40 requirements, 12k input and 4k output tokens), then check again"


def make_branch(harness, build_id, run_id, payload, model, trace, model_error):
    config = payload["config"]
    with harness.db.connect() as conn:
        version = conn.execute("SELECT current_version FROM builds WHERE id=?", (build_id,)).fetchone()[0]
    folder = config.data_dir / "builds" / build_id / f"v{version}"
    ledger, snapshot, checker = req.load(folder), req.inputs(harness.db, build_id, folder), Checker(load_registry())
    pending = req.new_sources(snapshot, ledger)
    secrets = tuple(getattr(config, key).get_secret_value() for key in ("google_api_key", "access_code", "agent_token"))
    state = {"raw": "", "failure": None, "scope": False}

    async def instruction_provider(context_object):
        # Build the full context in before_model so an over-budget context can be
        # recorded as a blocked assessment without an unhandled ADK exception.
        return "Extract explicit requirements for deterministic capability verification."

    def response(text):
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))

    async def before_model(callback_context, llm_request):
        trace.span("capability_check")
        if not pending:
            trace.spans[-1]["skipped"] = "deterministic_recomputation"
            state["raw"] = '{"requirements":[]}'
            return response("No new intent to extract.")
        llm_request.config.response_mime_type = "application/json"
        llm_request.config.response_json_schema = provider_schema(req.Extraction)
        llm_request.config.max_output_tokens = MAX_OUTPUT_TOKENS
        llm_request.contents = [types.Content(role="user", parts=[types.Part(text="Extract requirements from the supplied sources. Return JSON.")])]
        try:
            context = capability_context(snapshot, ledger, checker, pending)
            check_reply(context, secrets)
            llm_request.config.system_instruction = str(context)
            await fit_request(context, llm_request, model, trace.spans[-1])
        except RunError as exc:
            if "exceeds" not in exc.message:
                # Never let ADK log unsafe inputs or provider diagnostics.
                state["failure"] = exc
            else:
                state["scope"] = True
            return response("Requirement extraction could not proceed.")

    async def after_model(callback_context, llm_response):
        if llm_response.error_code:
            return LlmResponse(error_code="llm_unavailable", error_message="Requirement extraction failed")
        # ADK also invokes this for before_model's short-circuit response.
        if state["scope"] or state["failure"] or not pending:
            return llm_response
        raw = "".join(p.text for p in (llm_response.content.parts or []) if p.text and not p.thought) if llm_response.content else ""
        usage = llm_response.usage_metadata
        state["scope"] = (getattr(llm_response, "finish_reason", None) == types.FinishReason.MAX_TOKENS or
                          ((usage.candidates_token_count or 0) > MAX_OUTPUT_TOKENS if usage else tokens(raw) > MAX_OUTPUT_TOKENS))
        try:
            state["raw"] = check_reply(raw, secrets)
        except RunError:
            state["failure"] = RunError("llm_unavailable", "Requirement extraction returned unsafe output", 503)
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Requirements received for validation.")]), usage_metadata=usage)

    async def complete(node_input):
        trace.span("assess_capabilities")
        if state["failure"]:
            return "Requirement extraction did not finish."
        candidate = ledger.model_copy(deep=True)
        if not state["scope"]:
            try:
                candidate = req.merge(ledger, snapshot, req.Extraction.model_validate_json(state["raw"]))
            except (ValueError, ValidationError) as exc:
                # Count overflow is a scope refusal; malformed/spoofed output leaves
                # the previous ledger and artifacts byte-for-byte intact.
                try:
                    raw = json.loads(state["raw"])
                    oversized = (isinstance(raw, dict) and isinstance(raw.get("requirements"), list) and len(raw["requirements"]) > req.MAX_REQUIREMENTS) or str(exc) == "Requirement scope exceeded"
                except ValueError:
                    oversized = False
                if oversized:
                    state["scope"] = True
                else:
                    state["failure"] = RunError("llm_unavailable", "Requirement extraction returned invalid requirements", 503)
                    return "Requirement extraction did not finish."
        if state["scope"]:
            candidate.scope_error = SCOPE_MESSAGE
        candidate.prototype_stale |= req.artifact_stale(snapshot, ledger, checker)
        candidate = req.revalidate_decisions(snapshot, candidate, checker)
        # Source changes occurring during the counted call cannot publish a fresh ID.
        fresh = req.inputs(harness.db, build_id, folder)
        if req.digest(fresh) != req.digest(snapshot) or Checker(load_registry()).digest() != checker.digest():
            state["failure"] = RunError("feasibility_stale", "Inputs changed during assessment; check again", 409)
            return "Feasibility inputs changed."
        candidate.verification = req.verification(snapshot, candidate, checker)
        assessment = req.evaluate(snapshot, candidate, checker)
        req.save(folder, candidate, assessment)
        from dss.api.builds import build_response
        await harness.emit(build_id, run_id, "docs.updated", {"docs": build_response(harness.db, config, build_id)["docs"]})
        if assessment.state == "blocked":
            return "Feasibility needs attention: " + " ".join(i.reason for i in assessment.issues)
        return "Feasibility is ready." + (" Replan to update the stale prototype." if assessment.prototype_stale else "")

    agent = LlmAgent(name="capability_check", model=model, mode="single_turn", instruction=instruction_provider,
        before_model_callback=before_model, after_model_callback=after_model, on_model_error_callback=model_error)
    return agent, complete, state
