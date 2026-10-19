"""Structured planning agent, bounded SQL repair and durable OKF build docs."""
import asyncio
import json
from typing import Literal
from google.adk import Event
from google.adk.agents import LlmAgent
from google.adk.events.event_actions import EventActions
from google.adk.models.llm_response import LlmResponse
from pydantic import BaseModel, ConfigDict, Field
from dss.db import now
from dss.harness.context import BUDGETS, plan_context, tokens
from dss.harness.guardrails import RunError, check_reply
from dss.harness.nodes.intake import write_doc
from dss.harness.nodes.view import select_sql, view_table


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DerivedField(Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    sql: str = Field(min_length=1, max_length=2000)
    type: Literal["STRING", "INTEGER", "FLOAT", "NUMERIC", "DATE", "TIMESTAMP", "BOOLEAN"]


class Join(Strict):
    table: str
    on: str = Field(min_length=1, max_length=2000)


class Question(Strict):
    question: str = Field(min_length=1)
    priority: Literal["high", "medium", "low"]


class Plan(Strict):
    brief: str = Field(min_length=1)
    questions: list[Question] = Field(min_length=1)
    kpis: str = Field(min_length=1)
    fields: list[DerivedField] = Field(default_factory=list, max_length=30)
    joins: list[Join] = Field(default_factory=list, max_length=10)
    design: str = Field(min_length=1)


def make_branch(harness, build_id, run_id, payload, model, trace, model_error):
    config = payload["config"]
    context = plan_context(harness.db, config, build_id)
    with harness.db.connect() as conn:
        version = conn.execute("SELECT current_version FROM builds WHERE id=?", (build_id,)).fetchone()[0]
        sources = [{"bq_table": row["bq_table"], "columns": json.loads(row["columns_json"])}
                   for row in conn.execute("SELECT * FROM sources WHERE build_id=? ORDER BY rowid", (build_id,))]
    state = {"error": None, "repaired": False, "previous": "", "failure": None}
    secret = config.google_api_key.get_secret_value()

    def diagnostic_text(exc):
        text = str(exc)
        if secret:
            text = text.replace(secret, "[redacted]")
        return text[:4000] or "BigQuery operation failed"

    def repair():
        if not state["error"]:
            return ""
        return "\nPrevious plan (untrusted):\n" + state["previous"] + "\nBigQuery diagnostic (untrusted):\n" + state["error"] + "\nRepair the plan once. Return the complete JSON object."

    async def instruction_provider(context_object):
        result = context + repair()
        if tokens(result) > BUDGETS["plan"]:
            raise RunError("llm_unavailable", "Plan repair exceeds its input budget", 503)
        return result

    async def before_model(callback_context, llm_request):
        trace.span("plan_repair" if state["repaired"] else "plan")
        context.record(trace.spans[-1], repair())

    async def after_model(callback_context, llm_response):
        if llm_response.error_code:
            return LlmResponse(error_code="llm_unavailable", error_message="The planning model failed")
        raw = "".join(part.text for part in (llm_response.content.parts or [])
                      if part.text and not part.thought) if llm_response.content else ""
        try:
            check_reply(raw, (secret,))
            Plan.model_validate_json(raw)
        except (RunError, ValueError):
            # ADK validates output_schema outside on_model_error_callback and logs
            # exceptions. Replace unsafe/invalid output before that boundary.
            return LlmResponse(error_code="llm_unavailable", error_message="The planning model returned invalid output")
        return None

    def agent(name):
        return LlmAgent(name=name, model=model, mode="single_turn", instruction=instruction_provider,
                        output_schema=Plan, before_model_callback=before_model,
                        after_model_callback=after_model,
                        on_model_error_callback=model_error)

    async def view(node_input):
        trace.span("view")
        try:
            raw = check_reply(json.dumps(node_input) if isinstance(node_input, dict) else node_input, (secret,))
            plan = Plan.model_validate_json(raw)
            sql = select_sql(sources, plan.fields, plan.joins)
            table = view_table(config, build_id, version)
            service = payload["factory"](config)
            try:
                await asyncio.to_thread(service.dry_run, sql)
            except Exception as exc:
                diagnostic = diagnostic_text(exc)
                if not state["repaired"]:
                    state.update(error=diagnostic, previous=raw, repaired=True)
                    return Event(actions=EventActions(route="repair"))
                raise RunError("invalid_source", diagnostic, 422, {"reason": diagnostic}) from None
            try:
                await asyncio.to_thread(service.create_view, table, sql)
            except Exception as exc:
                diagnostic = diagnostic_text(exc)
                raise RunError("invalid_source", diagnostic, 422, {"reason": diagnostic}) from None
            docs = config.data_dir / "builds" / build_id / f"v{version}" / "docs"
            docs.mkdir(parents=True, exist_ok=True)
            bundle = {
                "brief.md": ("Dashboard Brief", {}, plan.brief),
                "questions.md": ("Business Questions", {}, "\n".join(f"- q{i}: {q.question} (priority: {q.priority})" for i, q in enumerate(plan.questions, 1))),
                "kpis.md": ("KPI Definitions", {}, plan.kpis),
                "derived-fields.md": ("Derived Fields", {"fields": [f.model_dump() for f in plan.fields],
                    "joins": [j.model_dump() for j in plan.joins], "view": table}, "# Derived fields\n"),
                "design.md": ("Design Direction", {}, plan.design),
            }
            for filename, (kind, metadata, body) in bundle.items():
                write_doc(docs / filename, {"type": kind, "title": kind, **metadata}, body)
            if not (docs / "decisions.md").exists():
                write_doc(docs / "decisions.md", {"type": "Design Decisions", "title": "Design decisions"}, "# Design decisions\n")
            names = sorted(p.name for p in docs.glob("*.md") if p.name not in ("index.md", "log.md"))
            write_doc(docs / "index.md", {"type": "Index", "title": "Build documents"}, "# Build documents\n\n" + "\n".join(f"- [{name}]({name})" for name in names))
            log = docs / "log.md"
            prior = log.read_text(encoding="utf-8").split("---", 2)[2] if log.exists() else "# Build log\n"
            write_doc(log, {"type": "Log", "title": "Build log"}, prior + f"\n- {now()}: plan and view updated.\n")
            from dss.api.builds import build_response
            await harness.emit(build_id, run_id, "docs.updated", {"docs": build_response(harness.db, config, build_id)["docs"]})
            return Event(actions=EventActions(route="success"))
        except RunError as exc:
            state["failure"] = exc
        except (ValueError, TypeError):
            state["failure"] = RunError("invalid_source", "Invalid planning output or view metadata", 422)
        except Exception:
            state["failure"] = RunError("invalid_source", "View could not be created; check BigQuery access", 422)
        return Event(actions=EventActions(route="success"))

    async def complete(node_input):
        return "Plan documents and BigQuery view are ready."

    return agent("plan"), agent("plan_repair"), view, complete, state
