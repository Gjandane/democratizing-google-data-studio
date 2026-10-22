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
- BigQuery rejects source_column_match=POSITION with autodetect; normalize upload headers, and use an explicit positional schema for GCS loads.
- Gemini's generic `400 INVALID_ARGUMENT` does not identify the invalid field; isolate worker/model/schema compatibility with a minimal live request before attributing it to `Any` or unions.
- HTTP clients normalize literal `..` path segments before sending: use `%2e%2e` when testing the API's invalid-name guard.
- Starlette StaticFiles normalizes paths with OS separators: normalize backslashes before checking the API boundary for SPA fallback on Windows.
- Uvicorn's graceful-shutdown timeout excludes lifespan teardown; backup I/O has a separate deadline (architecture.md#Implementation conventions).
- httpx string headers must be ASCII; use byte header values when testing non-ASCII credentials at the server boundary.
<!-- blueprint-solution:end -->
- Config does not strip root .env values and GCP_PROJECT_ID there has leading whitespace; live tests pass a stripped project through PUT /api/settings (or DSS_LIVE_GCP_PROJECT).
- Bash heredocs (even quoted 'EOF') in this shell can collapse backslashes in Python source (\0 became a NUL byte); write code with backslashes via the Write/Edit tools.
- Developer API count_tokens rejects system_instruction/tools/generation_config; llm.count_tokens folds them into contents, which counts ~5% under the billed prompt_token_count (live: 8245 vs 8695).
- google-genai sends the client `HttpOptions(timeout)` to Google as the server deadline (504 when exceeded); a per-request timeout does not override it, so set it per node on the client.
- Gemini max_output_tokens includes thinking; ADK may expose MAX_TOKENS as an error before scope handling. Bounded extraction needs a low thinking level and truncation-first handling.
- Live worker calls sometimes hit the 30 s deadline (llm_unavailable): rerun once before diagnosing; extraction shapes also vary between runs.
- SQLite's connection context manager does not close the handle: use `contextlib.closing` when inspecting backup snapshots, or Windows can block temporary-file cleanup.
- Windows system Python defaults text I/O to cp1252: pass `encoding="utf-8"` when reading and writing source/tests, or Unicode fixtures become mojibake.
- The 100 ms feasibility timing oracle hit 104.9 ms in a full run, then passed unchanged in isolation and a serial full rerun; avoid overlapping check runs before diagnosing a timing failure.
- Bold Georgia's W measures about 1.126em in Chromium; a 1em-per-character header estimate can clip an allowed 80-character title.
- The periodic-backup test once saw `backups=[]` in a full run, then passed unchanged in isolation and a serial rerun; retry before diagnosing this timing assertion.
- The shape-only `api/design.json` contract fixture uses a font outside the current theme presets; use a preset font when exercising Design confirmation.
- The live outline_other/comment extractor varies its record shape per run (breakdown as field key or value, dimension mapping agg "none", needs-less record, decoration hex as need or property): normalize in code and confirm a staged live flow with 2+ consecutive passing runs.
- tests/test_blueprint.artifact() calls asyncio.run: staged API tests that use it (or recreate_build in test_render) must be plain `def`, not `async def`.
- The engine's `run_finished.report_url` opens the report's last page; open `https://datastudio.google.com/reporting/<id>` (no `/page/...`) to inspect page 1.
- requirements.coverage_errors verifies needs against compiled recipe ops: a compiler op change also moves revise/thin_slice/agent_server tests that index recipe lines or expect set_style per chart (19.2 touched 5 such files).
- The b_a8ace098d03b live replay can stall after the s021 time_series timeout on a leftover Custom color dialog and never save (failed 22, report_url null): rerun once; find a report's full id in engine Chrome at datastudio.google.com/navigation/reporting.
- tests/live/test_staged_flow.observe_revisions wraps revise.revised(document, comments, batch, allowed) positionally and default runs skip it: keep that signature (a new kwarg breaks every live revise).
- designed_pages is on by default: test flows whose fake answers every node with one reply (ContextLLM) send it to the designer too, fall back on page 1 and add designer/validate/designer_fallback spans and +2 model calls to the prototype run.
