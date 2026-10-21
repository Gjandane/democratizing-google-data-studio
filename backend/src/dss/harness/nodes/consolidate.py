"""Consolidation: the worker model distills done builds into semantic memory.

The only semantic-memory write path. publish counts every build that reaches done; once the
count reaches `consolidate_every`, one background agent run (one Workflow invocation, one trace)
reads those builds' context, outline and design summaries (old builds: brief and design)
and decisions plus user/index.md. The model returns
structured facts; code writes the OKF concepts, index.md and log.md under data/knowledge/user/.
"""
import asyncio
from hashlib import sha1
import logging
import re
from typing import Literal
from urllib.parse import quote

from google.adk import Workflow
from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from dss.db import new_id, now
from dss.harness.context import consolidate_context, fit_request
from dss.harness.guardrails import RunError, check_reply
from dss.harness.nodes.intake import write_doc
from dss.harness.tracing import Trace
from dss.memory.semantic import parse_concept

logger = logging.getLogger(__name__)
# Windows device names cannot be file names, even with an extension.
RESERVED = {"index", "log", "con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fact(Strict):
    slug: str = Field(min_length=1, max_length=80)
    type: Literal["User Preference", "Design Decision"]
    title: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1, max_length=600)


class Facts(Strict):
    facts: list[Fact] = Field(default_factory=list, max_length=20)


def response_schema():
    schema = Facts.model_json_schema()
    # The worker rejects provider maxItems bounds; Pydantic keeps the limit at validation.
    schema["properties"]["facts"].pop("maxItems", None)
    return schema


class Runtime:
    """Per-app locks: one consolidation at a time, and a snapshot never splits a counted build."""

    def __init__(self):
        self.counting = asyncio.Lock()
        self.running = asyncio.Lock()


def runtime(state):
    current = getattr(state, "consolidation", None)
    if current is None:
        current = state.consolidation = Runtime()
    return current


def count_done(db):
    """One more build reached done; returns chats_since."""
    with db.connect() as conn:
        return conn.execute("UPDATE consolidation SET chats_since=chats_since+1 WHERE id=1 RETURNING chats_since").fetchone()[0]


def schedule(state):
    """Start consolidation in the background; the caller never waits for it."""
    task = asyncio.create_task(consolidate(state))
    state.engine_tasks.add(task)
    task.add_done_callback(state.engine_tasks.discard)
    return task


def snapshot(db, every):
    """(count, builds newest first) for the builds counted since the last consolidation, or None."""
    with db.connect() as conn:
        count = conn.execute("SELECT chats_since FROM consolidation WHERE id=1").fetchone()[0]
        if count < every:
            return None
        rows = conn.execute(
            "SELECT e.build_id, b.title, b.archetype, json_extract(e.payload_json,'$.version') AS version, e.created_at "
            "FROM events e JOIN builds b ON b.id=e.build_id WHERE e.kind='build.finished' "
            "AND json_extract(e.payload_json,'$.status') IN ('ok','partial') ORDER BY e.rowid DESC LIMIT ?",
            (count,)).fetchall()
    builds = {}
    for row in rows:
        builds.setdefault((row["build_id"], row["version"]), dict(row, date=row["created_at"][:10]))
    return count, list(builds.values())


def consume(db, count):
    # Builds that reached done while this run worked stay counted for the next one.
    with db.connect() as conn:
        conn.execute("UPDATE consolidation SET chats_since=MAX(chats_since-?,0),last_run_at=? WHERE id=1", (count, now()))


def one_line(text):
    return " ".join(text.split())


def slugify(fact):
    for text in (fact.slug, fact.title):
        # ASCII only: the slug is the index link target, which the model reuses verbatim.
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].strip("-")
        if slug:
            return "fact-" + slug if slug in RESERVED else slug
    return "fact-" + sha1(fact.title.encode("utf-8")).hexdigest()[:8]


def body_lines(text):
    lines = text.splitlines()
    return lines[lines.index("---", 1) + 1:]


def read_fact(text):
    """(statement, previously lines) from a fact file written by render_fact."""
    lines = body_lines(text)
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].startswith("# "):
        lines.pop(0)
    split = lines.index("## Previously") if "## Previously" in lines else len(lines)
    return one_line(" ".join(lines[:split])), [line[2:] for line in lines[split + 1:] if line.startswith("- ")]


def render_fact(title, statement, previously):
    text = f"# {title}\n\n{statement}\n"
    if previously:
        text += "\n## Previously\n\n" + "".join(f"- {line}\n" for line in previously)
    return text


def write_facts(folder, facts, today):
    """Write each fact; a changed statement keeps the old one under Previously with its date."""
    folder.mkdir(parents=True, exist_ok=True)
    chosen = {slugify(fact): fact for fact in facts}  # a repeated slug: the last one wins
    added, changed = [], []
    for slug, fact in chosen.items():
        path, title, statement = folder / f"{slug}.md", one_line(fact.title), one_line(fact.statement)
        previously = []
        if path.is_file():
            try:
                old = parse_concept(f"user/{path.name}", path.read_text(encoding="utf-8"))
                old_statement, previously = read_fact(old.text)
            except (ValueError, UnicodeDecodeError):
                logger.warning("Replacing unreadable user fact %s", path.name)
            else:
                if old_statement == statement and old.metadata["type"] == fact.type and old.metadata.get("title") == title:
                    continue
                if old_statement != statement:
                    previously = [f"{old.metadata.get('updated') or 'undated'}: {old_statement}", *previously]
            changed.append(slug)
        else:
            added.append(slug)
        write_doc(path, {"type": fact.type, "title": title, "updated": today}, render_fact(title, statement, previously))
    return added, changed


def link_safe(text):
    # Index links are navigation (list_folder): no Markdown link may come from fact text.
    return one_line(str(text)).replace("[", "(").replace("]", ")")


def write_index(folder):
    """Rebuild index.md from every readable fact, with its current statement."""
    lines = []
    for path in sorted(folder.glob("*.md")):
        if path.name in ("index.md", "log.md"):
            continue
        try:
            concept = parse_concept(f"user/{path.name}", path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            logger.warning("Leaving unreadable user fact %s out of the index", path.name)
            continue
        statement, _ = read_fact(concept.text)
        meta = concept.metadata
        lines.append(f"- [{link_safe(meta.get('title') or path.stem)}]({quote(path.name)}) "
                     f"({link_safe(meta['type'])}, {link_safe(meta.get('updated') or 'undated')}): {link_safe(statement)}")
    write_doc(folder / "index.md", {"type": "Index", "title": "User facts"},
              "# User facts\n\n" + ("\n".join(lines) if lines else "No facts yet.") + "\n")


def prepend_log(folder, entry):
    path, entries = folder / "log.md", []
    if path.is_file():
        try:
            entries = [line for line in body_lines(path.read_text(encoding="utf-8")) if line.startswith("- ")]
        except (ValueError, UnicodeDecodeError):
            logger.warning("Replacing unreadable user facts log")
    write_doc(path, {"type": "Change Log", "title": "User facts log"}, "# Changes\n\n" + "\n".join([entry, *entries]) + "\n")


async def consolidate(state, llm=None):
    """One consolidation agent run when the counter is due. Never raises except on cancellation:
    a failure keeps the counter, so the next done build retries with every pending build."""
    current = runtime(state)
    async with current.running:
        config = state.settings.get()
        async with current.counting:
            batch = snapshot(state.db, config.consolidate_every)
        if batch is None:
            return None
        count, builds = batch
        secrets = tuple(filter(None, (config.google_api_key.get_secret_value(),
                                      config.access_code.get_secret_value(), config.agent_token.get_secret_value())))
        run_id = new_id("r")
        trace = Trace(state.db, run_id, None, "consolidate")
        status, error, runner, result = "error", "llm_unavailable", None, {"facts": None, "failure": None}
        try:
            await state.harness.emit(None, run_id, "run.started", {"run_id": run_id, "node": "consolidate"})
            context = check_reply(consolidate_context(config, builds), secrets)
            if not any(section.kind == "past" for section in context.sections):
                if context.dropped["past"]:
                    raise RunError("llm_unavailable", "The consolidate context exceeds its input budget", 503)
                # No build has an artifact, a legacy summary or decisions: nothing to distill.
                trace.span("consolidate")
                context.record(trace.spans[-1])
                trace.spans[-1]["skipped"] = "no build documents"
                consume(state.db, count)
                status, error = "ok", None
                return status
            model = llm if llm is not None else state.models.llm_for("consolidate")
            trace.model = model.model

            async def instruction_provider(context_object):
                return context

            async def before_model(callback_context, llm_request):
                trace.span("consolidate")
                llm_request.config.response_mime_type = "application/json"
                llm_request.config.response_json_schema = response_schema()
                llm_request.contents = [types.Content(role="user", parts=[types.Part(text="Return the consolidated facts.")])]
                await fit_request(context, llm_request, model, trace.spans[-1])

            async def after_model(callback_context, llm_response):
                if llm_response.error_code:
                    return LlmResponse(error_code="llm_unavailable", error_message="Consolidation model failed")
                raw = "".join(p.text for p in (llm_response.content.parts or []) if p.text and not p.thought) if llm_response.content else ""
                try:
                    result["facts"] = Facts.model_validate_json(check_reply(raw, secrets)).facts
                except (RunError, ValueError):
                    # Validation errors carry model output; never let ADK log them.
                    return LlmResponse(error_code="llm_unavailable", error_message="Consolidation model returned invalid output")
                return LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Facts received.")]))

            async def model_error(callback_context, llm_request, error):
                return LlmResponse(error_code="llm_unavailable", error_message="The model call failed; check Settings")

            async def write(node_input):
                trace.span("consolidate_write")
                try:
                    folder = config.data_dir / "knowledge" / "user"
                    added, changed = write_facts(folder, result["facts"], now()[:10])
                    write_index(folder)
                    prepend_log(folder, f"- {now()}: consolidated {count} done builds "
                                f"({', '.join(sorted({b['build_id'] for b in builds}))}); "
                                f"added: {', '.join(added) or 'none'}; changed: {', '.join(changed) or 'none'}.")
                except Exception:
                    # Never let paths or OS errors reach ADK's unhandled-exception logger.
                    result["failure"] = RunError("llm_unavailable", "User facts could not be written", 503)
                    return "User facts were not written."
                return f"Consolidated {count} builds: {len(added)} facts added, {len(changed)} changed."

            async def guardrail(node_input):
                trace.span("guardrail")
                return check_reply(node_input, secrets)

            agent = LlmAgent(name="consolidate", model=model, mode="single_turn", instruction=instruction_provider,
                             before_model_callback=before_model, after_model_callback=after_model,
                             on_model_error_callback=model_error)
            workflow = Workflow(name="dss_consolidate", edges=[("START", agent), (agent, write), (write, guardrail)])
            sessions = InMemorySessionService()
            await sessions.create_session(app_name="dss", user_id="local", session_id=run_id)
            runner = Runner(app_name="dss", node=workflow, session_service=sessions)
            reply = None
            async for event in runner.run_async(user_id="local", session_id=run_id,
                    new_message=types.Content(role="user", parts=[types.Part(text="consolidate")]),
                    run_config=RunConfig(max_llm_calls=1)):
                if event.error_code:
                    raise RunError("llm_unavailable", "The model call failed; check Settings", 503)
                if event.usage_metadata:
                    trace.input_tokens += event.usage_metadata.prompt_token_count or 0
                    trace.output_tokens += event.usage_metadata.candidates_token_count or 0
                if event.node_info.path.split("/")[-1].split("@")[0] == "guardrail" and isinstance(event.output, str):
                    reply = event.output
            if result["failure"]:
                raise result["failure"]
            if reply is None:
                raise RunError("llm_unavailable", "The consolidation produced no guarded reply", 503)
            consume(state.db, count)
            status, error = "ok", None
            return status
        except RunError as exc:
            error = exc.code
            logger.warning("Consolidation failed (%s); the next done build retries it", exc.code)
        except asyncio.CancelledError:
            error = "cancelled"
            raise
        except Exception:
            # Provider exceptions may contain credentials or request text.
            logger.warning("Consolidation failed; the next done build retries it")
        finally:
            try:
                trace.save(status, error)
                await state.harness.emit(None, run_id, "run.finished", {
                    "run_id": run_id, "node": "consolidate", "status": status, "error": error})
            finally:
                if runner is not None:
                    await runner.close()
        return status
