<!-- blueprint-solution:start  (shared by Codex and Claude Code; in an existing AGENTS.md, add only this block and keep the rest) -->
# backend: agent guide
The agent harness of Democratizing Google Data Studio: an ADK 2.0 graph with three memory types,
BigQuery intake, the Dashboard Spec, deterministic renderers, the recipe compiler and the REST +
SSE API. Target: POC.

## Commands
Run from this folder (`backend/`) in bash.
- Install: `uv sync && uv run playwright install chromium`
- Run: `uv run uvicorn dss.main:app --port 8000`   (never `--reload`: it breaks subprocess and Playwright on Windows and kills running builds; Cloud Run runs `python -m dss.main`, which reads `$PORT`)
- Build agent (after task 5.3): `uv run dss-agent --server <hosted URL>` here; from the repo root `uv run --project backend dss-agent --server <hosted URL>` (plain `uv run dss-agent` outside `backend/` finds no script; reads the root `.env` incl. `DSS_AGENT_TOKEN`; `--dry-run` for rehearsals)
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
- BigQuery rejects source_column_match=POSITION with autodetect; normalize upload headers, and use an explicit positional schema for GCS loads.
- Gemini numeric Literal constraints require response_json_schema; response_schema conversion raises "Literal values must be strings".
- Gemini's generic `400 INVALID_ARGUMENT` does not identify the invalid field; isolate worker/model/schema compatibility with a minimal live request before attributing it to `Any` or unions.
- The worker rejects the revise schema's nested `maxItems` (20 changes, 40 operations); omit provider array maxima but retain Pydantic limits; title revisions need the renderer's default 28px in context.
- HTTP clients normalize literal `..` path segments before sending: use `%2e%2e` when testing the API's invalid-name guard.
- Starlette StaticFiles normalizes paths with OS separators: normalize backslashes before checking the API boundary for SPA fallback on Windows.
- Uvicorn's graceful-shutdown timeout excludes lifespan teardown; bound backup waits separately and avoid non-daemon executor threads for volume I/O.
- httpx string headers must be ASCII; use byte header values when testing non-ASCII credentials at the server boundary.
<!-- blueprint-solution:end -->
- Config does not strip root .env values and GCP_PROJECT_ID there has leading whitespace; live tests pass a stripped project through PUT /api/settings (or DSS_LIVE_GCP_PROJECT).
- Recipe JSONL is written with ensure_ascii=False, so U+2028/U+0085 can sit inside a line: split recipe text on LF only, never str.splitlines().
- POST /run recompiles recipe.jsonl from spec.json: test fixtures need spec.json, and a fixture recipe written with plain write_text on Windows is CRLF (non-canonical) and gets rewritten; pass newline="\n".
- Bash heredocs (even quoted 'EOF') in this shell can collapse backslashes in Python source (\0 became a NUL byte); write code with backslashes via the Write/Edit tools.
- Developer API count_tokens rejects system_instruction/tools/generation_config; llm.count_tokens folds them into contents, which counts ~5% under the billed prompt_token_count (live: 8245 vs 8695).
