"""One ADK Workflow invocation and one trace for every accepted agent run."""
import asyncio
import json
from contextlib import nullcontext

from google.adk import Event, Workflow
from google.adk.agents import LlmAgent
from google.adk.events.event_actions import EventActions
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.agents.run_config import RunConfig
from google.adk.sessions import InMemorySessionService
from google.genai import types

from dss.db import new_id, now
from dss.harness.guardrails import RunError, check_reply
from dss.harness.llm import retry_listener, bind_model
from dss.harness import stages
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
        resuming = isinstance(payload, dict) and '_brief_resume' in payload
        run_id = run_id or new_id("r")
        trace = Trace(self.db, run_id, build_id, action)
        execution = stages.Execution(self.models.settings.get(), trace, available=self.models.available)
        activation = execution.activate()
        activation.__enter__()
        # A retried model call stays in this run's trace: the retry is a span, and both
        # attempts' reported usage adds to the trace's tokens.
        retry_hook = retry_listener.set(lambda code: trace.spans.append({"node": "model_retry", "status": code}))
        status, error, reply = "error", "llm_unavailable", None
        runner = None
        code_error = None
        error_message = None
        revise_state = None
        extra_state = None
        reference_before = None
        blocked_saved = False
        try:
            if action in ("reference_extract", "reference_delete"):
                from dss.spec import references, requirements
                with self.db.connect() as conn:
                    version = conn.execute("SELECT current_version FROM builds WHERE id=?", (build_id,)).fetchone()[0]
                reference_folder = execution.config.data_dir / "builds" / build_id / f"v{version}"
                reference_before = requirements.digest(references.load(reference_folder))
            await self.emit(build_id, run_id, "run.started", {"run_id": run_id, "node": action})

            async def router(node_input):
                trace.span("router")
                if action == 'blueprint':
                    return Event(actions=EventActions(route=action))
                return Event(actions=EventActions(route=action if action in ("context", "outline_propose", "outline_suggest", "outline_other", "hello", "revise", "ux_audit", "reference_extract", "synthetic_schema", "capability_check", "research", "intake", "create_build", "load_spec", "recipe", "execute", "versions", "reference_delete", "engine_login", "synthetic_generate", "prototype") else "unknown"))

            async def code_node(node_input):
                nonlocal code_error
                trace.span(action)
                try:
                    if resuming:
                        from dss.api.prototype import require_fresh_review
                        require_fresh_review(self.db, execution.config, build_id, payload['_brief_resume'])
                        if action == 'prototype':
                            from dss.harness.nodes.render import resume_accept
                            return await resume_accept(self, build_id, run_id, payload, trace)
                        from dss.harness.nodes.revise import resume
                        return await resume(self, build_id, run_id, payload, trace)
                    if action in ("outline_propose", "load_spec", "recipe", "execute", "versions", "reference_delete", "engine_login", "synthetic_generate"):
                        return await payload(run_id)
                    if action == "create_build":
                        return "Build created"
                    if action == "prototype":
                        from dss.harness.nodes.render import accept
                        if llm is not None:
                            payload['_designer'] = lambda: llm  # else accept asks for the planner model
                        return await accept(self, build_id, run_id, payload, trace)
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
                stages.configure('hello', llm_request)

            async def model_error(callback_context, llm_request, error):
                # ADK logs unhandled node exceptions before the harness sees them.
                # Replace provider failures here, before they cross that boundary.
                stopped = stages.remember_failure(error)
                if (usage := getattr(error, 'usage', None)) is not None:
                    trace.input_tokens += usage.prompt_token_count or 0
                    trace.output_tokens += usage.candidates_token_count or 0
                    await self.emit(build_id, run_id, 'run.usage', {'run_id': run_id, 'node': action,
                        'input_tokens': trace.input_tokens, 'output_tokens': trace.output_tokens})
                return LlmResponse(error_code=stopped.code if stopped else "llm_unavailable",
                                   error_message=stopped.message if stopped else "The model call failed; check Settings")

            async def guardrail(node_input):
                trace.span("guardrail")
                key = execution.config.google_api_key.get_secret_value()
                return check_reply(node_input, (key,))

            async def reject(node_input):
                nonlocal code_error
                trace.span("reject")
                code_error = RunError("wrong_stage", "Unknown action", 409)
                return 'Action unavailable'

            if action == 'revise' and not resuming:
                from dss.harness.nodes.capability_check import make_branch as intent_branch
                from dss.spec import requirements as req
                from dss.spec.capabilities import Checker, load_registry
                intent_model = bind_model('capability_check', llm if llm is not None else self.models.llm_for('capability_check'))
                payload['_intent_only'] = True
                payload['_defer_assessment'] = False
                payload['_comment_preflight'] = action == 'revise'
                if action == 'revise' and payload.get('_reapply'):
                    with self.db.connect() as conn:
                        version = conn.execute('SELECT current_version FROM builds WHERE id=?', (build_id,)).fetchone()[0]
                    folder = payload['config'].data_dir / 'builds' / build_id / f'v{version}'
                    req.validate_reapply(req.inputs(self.db, build_id, folder), req.load(folder), Checker(load_registry()), payload['_reapply'])
                intent_agent, intent_complete, extra_state = intent_branch(
                    self, build_id, run_id, payload, intent_model, trace, model_error)

                async def assess_intent(node_input):
                    await intent_complete(node_input)
                    with self.db.connect() as conn:
                        version = conn.execute('SELECT current_version FROM builds WHERE id=?', (build_id,)).fetchone()[0]
                    folder = payload['config'].data_dir / 'builds' / build_id / f'v{version}'
                    assessment = extra_state.get('assessment') or req.get(
                        req.inputs(self.db, build_id, folder), req.load(folder), Checker(load_registry()))
                    if not extra_state['failure'] and assessment.state != 'ready':
                        extra_state['failure'] = req.blocked(assessment)
                    return Event(actions=EventActions(route='blocked' if extra_state['failure'] else 'continue'))

                async def intent_blocked(node_input):
                    return extra_state['failure'].message

            # Unknown actions never construct a real model or call the LLM.
            if resuming:
                workflow = Workflow(name='dss_run', edges=[
                    ('START', router), (router, {action: code_node}), (code_node, guardrail)])
            elif action == "hello":
                model = bind_model('hello', llm if llm is not None else self.models.llm_for("hello"))
                trace.model = model.model
                agent = LlmAgent(name="hello_llm", model=model, mode="single_turn",
                                 instruction="Give a brief greeting.", before_model_callback=before_llm,
                                 on_model_error_callback=model_error)
                workflow = Workflow(name="dss_run", edges=[
                    ("START", router), (router, {"hello": hello_function, "unknown": reject}),
                    (hello_function, agent, guardrail)])
            elif action == 'outline_propose' and callable(payload):
                workflow = Workflow(name='dss_run', edges=[
                    ('START', router), (router, {action: code_node}), (code_node, guardrail)])
            elif action in ('outline_propose', 'outline_suggest', 'outline_other'):
                from dss.harness.nodes.outline import make_branch
                model = bind_model(action, llm if llm is not None else self.models.llm_for(action))
                trace.model = model.model
                drafter, complete, extra_state = make_branch(
                    self, build_id, run_id, payload, model, trace, model_error)
                workflow = Workflow(name='dss_run', edges=[
                    ('START', router), (router, {action: drafter}), (drafter, complete), (complete, guardrail)])
            elif action == 'blueprint':
                from dss.harness.nodes.blueprint import make_branch
                model = bind_model(action, llm if llm is not None else self.models.llm_for(action))
                trace.model = model.model
                entry, edges, complete, extra_state = make_branch(
                    self, build_id, run_id, payload, model, trace, model_error)
                workflow = Workflow(name='dss_run', edges=[
                    ('START', router), (router, {action: entry}), *edges, (complete, guardrail)])
            elif action == 'context':
                from dss.harness.nodes.context import make_branch
                model = bind_model(action, llm if llm is not None else self.models.llm_for(action))
                trace.model = model.model
                drafter, repair, validate_context, complete, extra_state = make_branch(
                    self, build_id, run_id, payload, model, trace, model_error)
                workflow = Workflow(name='dss_run', edges=[
                    ('START', router), (router, {'context': drafter}), (drafter, validate_context),
                    (validate_context, {'repair': repair, 'complete': complete}), (repair, validate_context),
                    (complete, guardrail)])
            elif action == "revise":
                from dss.harness.nodes.revise import make_branch as revise_branch
                model = bind_model('revise', llm if llm is not None else self.models.llm_for('revise'))
                trace.model = model.model
                reviser, repair, validate_revision, complete, revise_state = revise_branch(self, build_id, run_id, payload, model, trace, model_error)
                workflow = Workflow(name='dss_run', edges=[
                    ('START', router), (router, {'revise':intent_agent}), (intent_agent, assess_intent),
                    (assess_intent, {'continue':reviser, 'blocked':intent_blocked}),
                    (intent_blocked, guardrail), (reviser, validate_revision),
                    (validate_revision, {'repair':repair, 'complete':complete}), (repair, validate_revision),
                    (complete, guardrail)])
            elif action == 'research':
                from dss.harness.nodes.research import make_branch as research_branch
                model = bind_model(action, llm if llm is not None else self.models.llm_for(action))
                trace.model = model.model
                discover, fetch, select, finish, extra_state = research_branch(self, build_id, run_id, payload, model, trace, model_error)
                workflow = Workflow(name='dss_run', edges=[
                    ('START', router), (router, {'research': discover}), (discover, fetch),
                    (fetch, {'select': select, 'failed': finish}), (select, finish), (finish, guardrail)])
            elif action in ("ux_audit", "reference_extract", "capability_check", "synthetic_schema"):
                if action == "ux_audit":
                    from dss.harness.nodes.ux_audit import make_branch as extra_branch
                elif action == "synthetic_schema":
                    from dss.harness.nodes.synthetic_schema import make_branch as extra_branch
                elif action == "capability_check":
                    from dss.harness.nodes.capability_check import make_branch as extra_branch
                else:
                    from dss.harness.nodes.reference_extract import make_branch as extra_branch
                model = bind_model(action, llm if llm is not None else self.models.llm_for(action))
                trace.model = model.model
                extra_agent, extra_finish, extra_state = extra_branch(self, build_id, run_id, payload, model, trace, model_error)
                workflow = Workflow(name="dss_run", edges=[
                    ("START", router), (router, {action: extra_agent}), (extra_agent, extra_finish), (extra_finish, guardrail)])
            elif action in ("intake", "create_build", "load_spec", "recipe", "execute", "versions", "reference_delete", "engine_login", "synthetic_generate", "prototype"):
                workflow = Workflow(name="dss_run", edges=[
                    ("START", router), (router, {action: code_node}), (code_node, guardrail)])
            else:
                workflow = Workflow(name="dss_run", edges=[("START", router), (router, {"unknown": reject}), (reject, guardrail)])
            sessions = InMemorySessionService()
            await sessions.create_session(app_name="dss", user_id="local", session_id=run_id)
            runner = Runner(app_name="dss", node=workflow, session_service=sessions)
            # The analysis deadline encloses code validation and repairs, not just provider calls.
            scope = execution.session(action).scope() if stages.stage_for(action) in stages.GENERATIONS else nullcontext()
            async with scope:
                async for event in runner.run_async(user_id="local", session_id=run_id,
                        new_message=types.Content(role="user", parts=[types.Part(text=action)]),
                        run_config=RunConfig(max_llm_calls=3 if action in ('blueprint', "revise") else 2 if action in ('context', "research") else 1 if action in ("outline_propose", "outline_suggest", "outline_other", "reference_extract", "capability_check", "synthetic_schema") else 4)):
                    if event.error_code:
                        raise execution.failure or RunError("llm_unavailable", "The model call failed; check Settings", 503)
                    # Streamed chunks repeat usage; only the final response of a model call counts.
                    if event.usage_metadata and not event.partial:
                        trace.input_tokens += event.usage_metadata.prompt_token_count or 0
                        trace.output_tokens += event.usage_metadata.candidates_token_count or 0
                        if build_id is not None:
                            await self.emit(build_id, run_id, "run.usage", {
                                "run_id": run_id, "node": action,
                                "input_tokens": trace.input_tokens, "output_tokens": trace.output_tokens})
                    if event.node_info.path.split("/")[-1].split("@")[0] == "guardrail" and isinstance(event.output, str):
                        reply = event.output
            if execution.failure:
                raise execution.failure
            if reply is None:
                raise RunError("llm_unavailable", "The workflow produced no guarded reply", 503)
            if code_error is not None:
                raise code_error
            if revise_state and revise_state['failure']:
                raise revise_state['failure']
            if extra_state and extra_state['failure']:
                if extra_state['failure'].code == 'feasibility_blocked':
                    from dss.memory import episodic
                    message = episodic.save(self.db, build_id, 'assistant', reply, action)
                    await self.emit(build_id, run_id, 'message.done', {'message': message})
                    blocked_saved = True
                raise extra_state['failure']
            if reference_before is not None and reference_before != requirements.digest(references.load(reference_folder)):
                requirements.reference_changed(reference_folder)
            if action in ('blueprint', 'prototype', 'context', 'outline_propose', 'outline_suggest', 'outline_other', 'revise', 'ux_audit', 'reference_extract', 'capability_check', 'research', 'synthetic_schema'):
                from dss.memory import episodic
                message = episodic.save(self.db, build_id, 'assistant', reply, action)
                await self.emit(build_id, run_id, 'message.done', {'message':message})
            if action == "hello":
                with self.db.connect() as connection:
                    connection.execute("INSERT INTO messages VALUES(?,?,?,?,?,?)", (
                        new_id("m"), build_id, "assistant", reply, "hello_llm", now()))
            status, error = "ok", None
            return {"run_id": run_id, "reply": reply}
        except RunError as exc:
            error = exc.code
            if exc.code == 'feasibility_blocked' and not blocked_saved:
                from dss.memory import episodic
                message = episodic.save(self.db, build_id, 'assistant', exc.message, action)
                await self.emit(build_id, run_id, 'message.done', {'message': message})
            if action in ('blueprint', 'prototype', 'context', 'outline_propose', 'outline_suggest', 'outline_other', "revise", "ux_audit", "reference_extract", "capability_check", "research", "synthetic_schema"):
                error_message = f'{exc.code}: {exc.message}' if exc.code.startswith('stage_') else exc.message
            raise
        except asyncio.CancelledError:
            error = "cancelled"
            raise
        except Exception:
            # Provider exceptions may contain URLs with credentials or request text.
            if execution.failure:
                error = execution.failure.code
                error_message = f'{error}: {execution.failure.message}'
                raise execution.failure from None
            raise RunError("llm_unavailable", "The model call failed; check Settings", 503) from None
        finally:
            try:
                if revise_state and (gate := revise_state.get('_brief_gate')) is not None:
                    gate.cleanup_revision()
                trace.tool_calls = extra_state.get('calls', 0) if extra_state else 0
                execution.record()
                trace.save(status, error)
                await self.emit(build_id, run_id, "run.finished", {
                    "run_id": run_id, "node": action, "status": status, "error": error_message or error})
            finally:
                activation.__exit__(None, None, None)
                retry_listener.reset(retry_hook)
                self.active_builds.discard(build_id)
                if runner is not None:
                    await runner.close()
