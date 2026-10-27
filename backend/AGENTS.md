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
- Persisted stage Settings override `SettingsStore.defaults`: API tests must PUT stage changes before starting a run; no-reference fakes need separate valid `reference_brief` and `designer` replies.
- Codex's Windows sandbox can deny uv's default cache and pytest temp directories or stall TestClient: a workspace `UV_CACHE_DIR=.blueprint/uv-cache` fixes uv; run local TestClient/network checks with normal process access.
- BigQuery rejects source_column_match=POSITION with autodetect; normalize upload headers, and use an explicit positional schema for GCS loads.
- Gemini's generic `400 INVALID_ARGUMENT` does not identify the invalid field; isolate worker/model/schema compatibility with a minimal live request before attributing it to `Any` or unions.
- HTTP clients normalize literal `..` path segments before sending: use `%2e%2e` when testing the API's invalid-name guard.
- Starlette StaticFiles normalizes paths with OS separators: normalize backslashes before checking the API boundary for SPA fallback on Windows.
- httpx string headers must be ASCII; use byte header values when testing non-ASCII credentials at the server boundary.
- Config does not strip root .env values and GCP_PROJECT_ID there has leading whitespace; live tests pass a stripped project through PUT /api/settings (or DSS_LIVE_GCP_PROJECT).
- Bash heredocs (even quoted 'EOF') in this shell can collapse backslashes in Python source (\0 became a NUL byte); write code with backslashes via the Write/Edit tools.
- Developer API count_tokens rejects system_instruction/tools/generation_config; llm.count_tokens folds them into contents, which counts ~5% under the billed prompt_token_count (live: 8245 vs 8695).
- google-genai sends the client `HttpOptions(timeout)` to Google as the server deadline (504 when exceeded); a per-request timeout does not override it, so set it per node on the client.
- Gemini max_output_tokens includes thinking; ADK may expose MAX_TOKENS as an error before scope handling. Bounded extraction needs a low thinking level and truncation-first handling.
- Live worker calls sometimes hit the 30 s deadline (llm_unavailable): rerun once before diagnosing; extraction shapes also vary between runs.
- SQLite's connection context manager does not close the handle: use `contextlib.closing` when inspecting backup snapshots, or Windows can block temporary-file cleanup.
- Windows system Python defaults text I/O to cp1252: pass `encoding="utf-8"` when reading and writing source/tests, or Unicode fixtures become mojibake.
- Timing flakes (100 ms feasibility oracle at 104.9 ms; periodic-backup test saw `backups=[]`) passed unchanged in isolation and serial reruns: avoid overlapping runs and retry before diagnosing.
- Bold Georgia's W measures about 1.126em in Chromium; a 1em-per-character header estimate can clip an allowed 80-character title.
- The shape-only `api/design.json` contract fixture uses a font outside the current theme presets; use a preset font when exercising Design confirmation.
- The live outline_other/comment extractor varies its record shape per run (breakdown as field key or value, dimension mapping agg "none", needs-less record, decoration hex as need or property): normalize in code and confirm a staged live flow with 2+ consecutive passing runs.
- tests/test_blueprint.artifact() calls asyncio.run: staged API tests that use it (or recreate_build in test_render) must be plain `def`, not `async def`.
- The engine's `run_finished.report_url` opens the report's last page; open `https://datastudio.google.com/reporting/<id>` (no `/page/...`) to inspect page 1. Find a report's full id in engine Chrome at datastudio.google.com/navigation/reporting.
- coverage_errors checks needs against compiled recipe ops: a compiler op change also breaks tests that index recipe lines or expect set_style per chart (19.2: 5 files).
- tests/live/test_staged_flow.observe_revisions wraps revise.revised(document, comments, batch, allowed) positionally and default runs skip it: keep that signature (a new kwarg breaks every live revise).
- To replay a live test build with `dsengine run`, run the live test with DSS_LIVE_KEEP=1 (test_designed_dashboard_sample_csv) so its BigQuery source/view survive; delete them afterwards.
- One-reply fakes (ContextLLM) also answer the designer (default designed_pages: page-1 fallback, +2 model calls, designer/validate/designer_fallback spans) and a recreate observation gap's row repair (needs a second `{"rows": [...]}` reply, or llm_unavailable).
- Reference builds need valid separate `reference_brief`/`reference_html` fake routing: reusing a finite Blueprint reply or `{}` HTML now fails the candidate; a designed-background capture fake must accept `scale`.
- A publish 422 "Candidate no longer fulfills": its `publish` trace span lists `coverage_errors`; to diagnose a release build, copy it (sqlite backup API, `?mode=ro`), lay out its Blueprint, call `requirements.coverage_errors`.
- Reference interpretation item ids are positional (o1, o2, ...): omitting an item from a vision fixture renumbers the rest.
- The root .env sets DSS_ALLOWED_TYPES to the pre-1.3 list and allowed_types() reads it in tests too: a test of the catalog default must delenv and monkeypatch `dss.spec.validate.dotenv_values`, and a test passing only because .env narrows types is environment-dependent.
<!-- blueprint-solution:end -->
- A reference's instructions are new intent: after `/design/confirm` its `bp_intent_` issue can't be decided; run `POST /feasibility/check` first. Live comments need app-supported kinds (title, move, series colors): title font size is unsupported_app, vague layout asks are unknown.
- A recreate fixture's vision reply (`items`) must use thousandths boxes and no `id` (code normalizes boxes and assigns o1, o2, ...); stored interpretation items fail reference_extract validation as llm_unavailable.
- `validate.catalog()` re-parses the catalog YAML on every call (~35 ms): never call it per observation in recomputation paths (requirements caches it as `_surface_catalog`).
- Style mode imports no charts or controls from a reference: its slider, split bar and small multiples get no slots, and a designer shown the image drew them as fakes in the background until the skill forbade it (24.5 live run 1).
- Definition-only reference instructions (`Label = AGG(field)`) stay blocking `unknown` rows unless an observation's mapping absorbs them exactly; to see every issue behind a 20-issue scope refusal, re-run requirements.evaluate with MAX_ISSUES patched (tests/live/test_reference_design.all_issues).
- Reference HTML enforces `max(chars/4, folded*1.2+512)` on the complete request: 12k initially, 24k for its sole repair (until 25.2; then the stage profile's input_tokens and margin); exceeding either cap fails the candidate even when billed input would fit.
- Sanitized ledger fixtures must preserve semantic `Property.path` keys; pseudonymized source identities require fresh processed-source hashes and replay of recorded decisions through the normal gate.
- Blueprint date normalization retains raw year intent in private `blueprint-inputs.json.native_dates`; repair re-entry needs raw rows with the raw view and must preserve code label fallbacks.
- Recreate image observations count only on page 1 (requirements.reference_page/placed_fulfills): a fixture whose observed chart sits on a later page now gets a code-added page-1 row, or a metric-less observation retitles a page-1 chart (24.7/24.9 fixtures).
- Observed titles come from the extraction's `label` property (the 18.2 RECREATE extraction has none); pass `kpis=snapshot['confirmed_kpis']` to observation_meaning/observed_title, or a KPI-only unit stays unproven and the title differs from publish.
- One reference observation can emit several feasibility issues (geo data missing plus country aggregation clarification): an approved observation drop covers every issue for that observation, not just one status.
- Fake models without a token counter expose `input_tokens_estimate`, not `enforced_input_bound`; request regressions must check the bound the fake actually supplies.
- `test_render` replaces `feasibility.observation_errors` with `lambda *args: []` to exercise publish coverage: forward new optional inputs positionally so those hooks still run.
- Windows sandbox can hide Git from blueprint.py and reject plan.md writes: run its state-changing commands with normal process access; preserve pre-existing work before using start --force.
- Profile compile_recipe when a recomputation speed oracle fails: recipe JSON Schema oneOf scanning dominated the design-HTML fixture; keep full wrapper/branch validation when optimizing dispatch.
- `uv run pytest -x` retains the full test set and reports a timing failure immediately; agent heartbeat/transport cases can pass unchanged in isolation, so capture the traceback and preserve their limits before diagnosing.
- ADK Workflow wraps exceptions from `before_model`; retain sanitized stage failures in the action context so overflow and deadline codes survive that boundary.
- Fake-clock retry tests must assert fake elapsed time: constructing fresh genai clients can take seconds even with a fully mocked provider.
- Several nodes alias `dss.artifacts.state` as `stages`: import `dss.harness.stages` as `execution_stages` there when adding execution hooks.
- A redraw can use a new brief yet return identical HTML and boxes: include collected briefs in the revision change check so their files and provenance still publish.
- FastAPI 0.159 keeps included-router wrappers in `app.routes`: recurse `effective_candidates()` when inventorying write routes; OpenAPI omits hidden routes.
- Brief review guards must run both before body intake and at mutation/reservation after body or decode awaits (`episodic.require_no_brief_review`, `prototype.mutation_current`); an early middleware check alone races a newly paused run.
- Publication recovery retains a pending brief candidate only while its journal is neither committed nor restored; terminal journals retire stale review ownership restored from older SQLite backups.
- Argon high on the recreate Blueprint (native_planning defaults) can exceed its 600 s clock with no response; with 3,600 s it took 239 s and 25,240 thinking tokens of the 32,768 cap (25.7). Re-running the live acceptance costs ~25 min; benchmark one stage with `.blueprint/qa/task-25.7/blueprint-benchmark/` first.
- Reference extraction can return a null-label control despite a named instruction definition; its field binding can stay unresolved, and neither its screenshot position nor a missing label authorizes an inferred binding or legend drop.
- tests/test_feasibility.py already has an API `choose(client, bid, assessment, *items)` helper: a same-named module-level helper appended later silently shadows it and breaks dozens of older tests; grep names before adding helpers to large test modules.
