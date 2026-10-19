"""One ADK Workflow invocation and one trace for every accepted agent run."""
import asyncio
import json

from google.adk import Event, Workflow
from google.adk.agents import LlmAgent
from google.adk.events.event_actions import EventActions
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.sessions import InMemorySessionService
from google.genai import types

from dss.db import new_id, now
from dss.harness.guardrails import RunError, check_reply
from dss.harness.tracing import Trace


class AgentHarness:
    def __init__(self, db, bus, models):
        self.db, self.bus, self.models = db, bus, models
        self.active_builds = set()

    async def emit(self, build_id, run_id, kind, payload):
        with self.db.connect() as connection:
            connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?)", (
                new_id("e"), build_id, run_id, kind, json.dumps(payload), now()))
        await self.bus.publish(build_id, kind, payload)

    async def run(self, action, build_id, payload=None, *, llm=None, run_id=None, reserved=False):
        if build_id is not None and not self.db.build_exists(build_id):
            raise RunError("build_not_found", "Build not found", 404)
        if build_id in self.active_builds and not reserved:
            with self.db.connect() as connection:
                stage = connection.execute("SELECT stage FROM builds WHERE id=?", (build_id,)).fetchone()[0]
            raise RunError("wrong_stage", "An action is already running for this build", 409, {"stage": stage})
        self.active_builds.add(build_id)
        run_id = run_id or new_id("r")
        trace = Trace(self.db, run_id, build_id, action)
        status, error, reply = "error", "llm_unavailable", None
        runner = None
        code_error = None
        readiness = None
        reply_stream = None
        error_message = None
        plan_state = None
        spec_state = None
        revise_state = None
        extra_state = None
        try:
            await self.emit(build_id, run_id, "run.started", {"run_id": run_id, "node": action})

            async def router(node_input):
                trace.span("router")
                return Event(actions=EventActions(route=action if action in ("hello", "interview", "plan", "spec", "revise", "ux_audit", "style_extract", "intake", "create_build", "load_spec", "recipe", "execute", "versions", "engine_login") else "unknown"))

            async def code_node(node_input):
                nonlocal code_error
                trace.span(action)
                try:
                    if action in ("load_spec", "recipe", "execute", "versions", "engine_login"):
                        return await payload(run_id)
                    if action == "create_build":
                        return "Build created"
                    from dss.harness.nodes.intake import perform
                    sources = await asyncio.to_thread(perform, self.db, build_id, payload)
                    return json.dumps(sources)
                except RunError as exc:
                    code_error = exc
                except Exception:
                    # Never let provider errors (possibly containing source data or credentials)
                    # reach ADK's unhandled-exception logger.
                    code_error = RunError("invalid_source", "Source could not be loaded; check access and format", 422,
                                          {"reason": "Data service failed; check source access, format and location"})
                return "Source action failed"

            async def hello_function(node_input):
                trace.span("hello_function")
                return "Say hello briefly."

            async def before_llm(callback_context, llm_request):
                trace.span("hello_llm")

            async def model_error(callback_context, llm_request, error):
                # ADK logs unhandled node exceptions before the harness sees them.
                # Replace provider failures here, before they cross that boundary.
                return LlmResponse(error_code="llm_unavailable", error_message="The model call failed; check Settings")

            async def guardrail(node_input):
                trace.span("guardrail")
                key = self.models.settings.get().google_api_key.get_secret_value()
                return check_reply(node_input, (key,))

            async def reject(node_input):
                trace.span("guardrail")
                raise RunError("wrong_stage", "Unknown action", 409)

            # Unknown actions never construct a real model or call the LLM.
            if action == "hello":
                model = llm if llm is not None else self.models.llm_for("hello")
                trace.model = model.model
                agent = LlmAgent(name="hello_llm", model=model, mode="single_turn",
                                 instruction="Give a brief greeting.", before_model_callback=before_llm,
                                 on_model_error_callback=model_error)
                workflow = Workflow(name="dss_run", edges=[
                    ("START", router), (router, {"hello": hello_function, "unknown": reject}),
                    (hello_function, agent, guardrail)])
            elif action == "interview":
                from dss.harness.nodes.interview import make_agent, ReplyStream
                model = llm if llm is not None else self.models.llm_for("interview")
                trace.model = model.model
                agent, readiness = make_agent(self, build_id, payload, model, trace, model_error)
                reply_stream = ReplyStream(self, build_id, run_id)
                workflow = Workflow(name="dss_run", edges=[
                    ("START", router), (router, {"interview": agent}), (agent, guardrail)])
            elif action == "plan":
                from dss.harness.nodes.plan import make_branch
                model = llm if llm is not None else self.models.llm_for("plan")
                trace.model = model.model
                planner, repair, view, complete, plan_state = make_branch(self, build_id, run_id, payload, model, trace, model_error)
                with self.db.connect() as connection:
                    connection.execute("UPDATE builds SET stage='plan',updated_at=? WHERE id=?", (now(), build_id))
                await self.emit(build_id, run_id, "stage.changed", {"stage": "plan"})
                from dss.harness.nodes.spec import make_branch as spec_branch
                spec_model = llm if llm is not None else self.models.llm_for("spec")
                spec_agent, spec_repair, validate, spec_state = spec_branch(self, build_id, run_id, payload, spec_model, trace, model_error)
                async def after_view(node_input):
                    return Event(actions=EventActions(route="failed" if plan_state["failure"] else "spec"))
                async def render_prototype(node_input):
                    nonlocal code_error
                    if not spec_state['failure']:
                        from dss.harness.nodes.render import perform
                        try:
                            return await perform(self, build_id, run_id, payload, trace)
                        except RunError as exc:
                            code_error = exc
                    return 'Prototype rendering did not finish.'
                workflow = Workflow(name="dss_run", edges=[
                    ("START", router), (router, {"plan": planner}), (planner, view),
                    (view, {"repair": repair, "success": after_view}), (repair, view),
                    (after_view, {"failed": complete, "spec": spec_agent}), (spec_agent, validate),
                    (validate, {"repair": spec_repair, "success": render_prototype}), (spec_repair, validate),
                    (render_prototype, guardrail), (complete, guardrail)])
            elif action == "revise":
                from dss.harness.nodes.revise import make_branch as revise_branch
                model = llm if llm is not None else self.models.llm_for('revise')
                trace.model = model.model
                reviser, repair, validate_revision, complete, revise_state = revise_branch(self, build_id, run_id, payload, model, trace, model_error)
                workflow = Workflow(name='dss_run', edges=[
                    ('START', router), (router, {'revise':reviser}), (reviser, validate_revision),
                    (validate_revision, {'repair':repair, 'complete':complete}), (repair, validate_revision),
                    (complete, guardrail)])
            elif action in ("ux_audit", "style_extract"):
                if action == "ux_audit":
                    from dss.harness.nodes.ux_audit import make_branch as extra_branch
                else:
                    from dss.harness.nodes.style_extract import make_branch as extra_branch
                model = llm if llm is not None else self.models.llm_for(action)
                trace.model = model.model
                extra_agent, extra_finish, extra_state = extra_branch(self, build_id, run_id, payload, model, trace, model_error)
                workflow = Workflow(name="dss_run", edges=[
                    ("START", router), (router, {action: extra_agent}), (extra_agent, extra_finish), (extra_finish, guardrail)])
            elif action == "spec":
                from dss.harness.nodes.spec import make_branch as spec_branch
                model = llm if llm is not None else self.models.llm_for("spec")
                trace.model = model.model
                spec_agent, spec_repair, validate, spec_state = spec_branch(self, build_id, run_id, payload, model, trace, model_error)
                async def complete_spec(node_input):
                    return "Dashboard Spec validation finished."
                workflow = Workflow(name="dss_run", edges=[
                    ("START", router), (router, {"spec": spec_agent}), (spec_agent, validate),
                    (validate, {"repair": spec_repair, "success": complete_spec}), (spec_repair, validate), (complete_spec, guardrail)])
            elif action in ("intake", "create_build", "load_spec", "recipe", "execute", "versions", "engine_login"):
                workflow = Workflow(name="dss_run", edges=[
                    ("START", router), (router, {action: code_node}), (code_node, guardrail)])
            else:
                workflow = Workflow(name="dss_run", edges=[("START", router), (router, {"unknown": reject})])
            sessions = InMemorySessionService()
            await sessions.create_session(app_name="dss", user_id="local", session_id=run_id)
            runner = Runner(app_name="dss", node=workflow, session_service=sessions)
            async for event in runner.run_async(user_id="local", session_id=run_id,
                    new_message=types.Content(role="user", parts=[types.Part(text=action)]),
                    run_config=RunConfig(max_llm_calls=5 if action == "plan" else (3 if action == "spec" else 2 if action == 'revise' else 4),
                        streaming_mode=StreamingMode.SSE if action == "interview" else StreamingMode.NONE)):
                if event.error_code:
                    raise RunError("llm_unavailable", "The model call failed; check Settings", 503)
                if event.usage_metadata:
                    trace.input_tokens += event.usage_metadata.prompt_token_count or 0
                    trace.output_tokens += event.usage_metadata.candidates_token_count or 0
                if reply_stream and event.partial and event.content:
                    for part in event.content.parts or []:
                        if part.text and not part.thought:
                            await reply_stream.append(part.text)
                if event.node_info.path.split("/")[-1].split("@")[0] == "guardrail" and isinstance(event.output, str):
                    reply = event.output
            if reply is None:
                raise RunError("llm_unavailable", "The workflow produced no guarded reply", 503)
            if code_error is not None:
                raise code_error
            if plan_state and plan_state["failure"]:
                raise plan_state["failure"]
            if spec_state and spec_state["failure"]:
                raise spec_state["failure"]
            if revise_state and revise_state['failure']:
                raise revise_state['failure']
            if extra_state and extra_state['failure']:
                raise extra_state['failure']
            if action in ('revise', 'ux_audit', 'style_extract'):
                from dss.memory import episodic
                message = episodic.save(self.db, build_id, 'assistant', reply, action)
                await self.emit(build_id, run_id, 'message.done', {'message':message})
            if action == "hello":
                with self.db.connect() as connection:
                    connection.execute("INSERT INTO messages VALUES(?,?,?,?,?,?)", (
                        new_id("m"), build_id, "assistant", reply, "hello_llm", now()))
            if action == "interview":
                from dss.memory import episodic
                from dss.api.builds import build_response
                # Tool effects and client output commit only after the reply passes guardrails.
                reply = await reply_stream.finish(reply)
                with self.db.connect() as connection:
                    connection.execute("UPDATE builds SET stage='interview',ready_for_plan=MAX(ready_for_plan,?),updated_at=? WHERE id=?",
                                       (int(readiness["ready"]), now(), build_id))
                if payload.get("start"):
                    await self.emit(build_id, run_id, "stage.changed", {"stage": "interview"})
                message = episodic.save(self.db, build_id, "assistant", reply, "interview", reply_stream.message_id)
                await self.emit(build_id, run_id, "message.done", {"message": message})
                if readiness["ready"]:
                    await self.emit(build_id, run_id, "build.updated", {
                        "build": build_response(self.db, payload["config"], build_id)})
            status, error = "ok", None
            return {"run_id": run_id, "reply": reply}
        except RunError as exc:
            error = exc.code
            if action in ("plan", "spec", "revise", "ux_audit", "style_extract"):
                error_message = exc.message
            raise
        except asyncio.CancelledError:
            error = "cancelled"
            raise
        except Exception:
            # Provider exceptions may contain URLs with credentials or request text.
            raise RunError("llm_unavailable", "The model call failed; check Settings", 503) from None
        finally:
            try:
                if action in ("plan", "spec") and status != "ok":
                    with self.db.connect() as connection:
                        connection.execute("UPDATE builds SET stage='interview',updated_at=? WHERE id=?", (now(), build_id))
                    await self.emit(build_id, run_id, "stage.changed", {"stage": "interview"})
                trace.tool_calls = readiness["calls"] if readiness else 0
                trace.save(status, error)
                await self.emit(build_id, run_id, "run.finished", {
                    "run_id": run_id, "node": action, "status": status, "error": error_message or error})
            finally:
                self.active_builds.discard(build_id)
                if runner is not None:
                    await runner.close()
