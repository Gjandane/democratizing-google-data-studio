<!-- blueprint-solution:start  (shared by Codex and Claude Code; in an existing AGENTS.md, add only this block and keep the rest) -->
# backend: agent guide
The agent harness of Democratizing Google Data Studio: an ADK 2.0 graph with three memory types,
BigQuery intake, the Dashboard Spec, deterministic renderers, the recipe compiler and the REST +
SSE API. Target: POC.

## Commands
Run from this folder (`backend/`) in bash.
- Install: `uv sync && uv run playwright install chromium`
- Run: `uv run uvicorn dss.main:app --port 8000`   (never `--reload`: it breaks subprocess and Playwright on Windows and kills running builds; Cloud Run runs `python -m dss.main`, which reads `$PORT`)
- Build agent (after task 5.3): `uv run dss-agent --server <hosted URL>`   (any folder works; reads the root `.env` incl. `DSS_AGENT_TOKEN`; `--dry-run` for rehearsals)
- Test (all): `uv run pytest`   (each task's own check is its "Done when" in docs/plan.md; live tests run only with `-m live`)
- Lint: none

## Read before editing
- docs/architecture-essentials.md: always.
- docs/plan.md: find your task. Change task status only through the blueprint script.
- docs/progress.md: the latest entry, plus the entries of tasks yours depends on.
- The doc sections your task's `Spec:` names (`status` prints them): what your code must do, in full.
- docs/architecture.md: otherwise only if your task changes the design.
- docs/PRD.md: goals and non-goals; open it when a requirement is unclear.
- ../contracts/api.md, ../contracts/fixtures/, ../contracts/recipe.md, ../contracts/recipe.schema.json, ../contracts/conventions.md (read-only): the interfaces this part provides or consumes; read the one your task touches.
- ../harness-architecture.md (read-only): the harness vocabulary and invariants.

## Rules
- This folder is the backend part of Democratizing Google Data Studio. The other parts (engine `../engine/`, frontend `../frontend/`, release at `..`) are separate projects: their docs, rules and commits don't apply here; never read, edit or report on their files. From the program root's AGENTS.md, only the program block applies. The exception is the contracts above: read them, never edit them.
- Build only what the current task asks. Stay inside its Files, or say why before editing others.
- Never build anything listed under Non-goals in docs/PRD.md.
- Use only dependencies with a date in the Verified column of docs/architecture-essentials.md. Ask before adding any other.
- Never print, log or commit secret values. `.env` stays out of version control and shared copies; `.env.example` lists names only.
- A task is done only when its "Done when" command and Test (all) pass. Report real output; never describe a run you didn't do.
- Latitude: anything these docs don't fix is yours to decide. Pick the smallest change that passes the check and record it under Decisions in your progress entry. Smallest never means naive: code under a Spec meets all of it (rules, edge cases, budget), not just the tests.
- Before ending a session, add an entry to docs/progress.md.
- Decisions and task status live in docs/, never in a tool's memory. If a saved memory disagrees with these docs, the docs win.

## Known gotchas
Traps that cost an earlier session time and that the other docs don't cover, one line each. Builders add lines; the architect sorts them into the docs at the final audit.
- ADK 2.12 Workflow function events use the workflow as author; identify the node via node_info.path (e.g. dss_run@1/guardrail@1).
- ADK logs unhandled model exceptions before the harness sees them; sanitize them in on_model_error_callback and test captured logs.
- BigQuery rejects source_column_match=POSITION with autodetect; normalize upload headers, and use an explicit positional schema for GCS loads.
- Engine commands launched through uv can leave children holding stdout open; timeout and cancellation must terminate the process tree, then reap the wrapper.
- ADK interpolates braces in string instructions as session state; use callable instruction providers for assembled context containing user text.
- ADK output_schema validation bypasses on_model_error_callback; guard and validate raw output in after_model_callback before ADK can log validation inputs.
<!-- blueprint-solution:end -->
