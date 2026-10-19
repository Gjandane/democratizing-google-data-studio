# Progress log
Append-only handoff log: one entry per session, newest at the bottom, written for someone with no
context. Task status lives in docs/plan.md, not here.

## 2026-10-18: Plan backend (POC)
- Status: done
- What changed: wrote PRD, architecture, essentials, plan (15 tasks), AGENTS.md, CLAUDE.md
- Decisions: the Dashboard Spec JSON is the single source of truth (LLM writes spec/patches only; HTML, background, view SQL and recipe are code); one BigQuery view per version holds joins and derived fields; semantic memory = OKF bundles, episodic = SQLite + FTS5, no vector store; one ADK Workflow with an action router, one trace per run; planner `gemini-4-argon` only for plan and spec nodes.
- Baseline: new project: none
- Next: Task 1.1. Start by creating the uv project and checking the installed google-adk's Workflow API against https://adk.dev/2.0/.

## 2026-10-18: Audit
- Status: done
- What changed: one reviewer audit across the program (18 findings: 2 P0, 4 P1, 9 P2, 3 P3 plus a pass note); all 18 accepted by the user and applied to contracts/ and every part's docs
- Decisions: backend thin slice 1.3 before memory depth; engine must-have ops by 21:00 with DSS_ALLOWED_TYPES as fallback; shared API fixtures in ../contracts/fixtures/api/; no uvicorn --reload on Windows; gates written into docs/program.md's roadmap
- Next: build, starting with task 1.1

## 2026-10-19: Change Cloud Run deployment (program root)
- Status: done
- What changed: the architect, at the program root, lifted Cloud Run from non-goal to goal and moved the deadline to 2026-10-20 01:05 MPST; contracts/api.md and contracts/conventions.md are now 1.1 (access code, agent mode, agent endpoints, Cloud deployment, Build agent); a reviewer delta audit (33 findings) was applied.
- Affects: new Phase 5 (5.1 cloud mode, Depends 1.3 so a second session can build it in parallel; 5.2 agent server; 5.3 `dss-agent` client); memory depth renumbered 5.x -> 6.x, stretch 6.x -> 7.x; architecture.md#Cloud mode (stamped).
- Next: task 1.1 (still the program's critical path).

## 2026-10-19: Task 1.1 API, database, event bus and a one-node graph
- Status: partial
- Plan check: off
- What changed: added uv project/lock, SQLite schema and FTS5 triggers, write-only settings, health/SSE API, ADK Workflow hello branch, model fallback, guardrails and traces; installed dependencies and Chromium.
- Checks: `uv run pytest tests/test_skeleton.py` PASS (7); `uv run pytest` PASS (7, 1 live deselected); uvicorn on port 8000 and `curl.exe --fail --silent localhost:8000/api/health` returned `{"status":"ok"}`. `uv run pytest -m live tests/live/test_models.py` FAIL (1): Google 403 API_KEY_SERVICE_BLOCKED on ListModels.
- Decisions: installed ADK 2.12 supports Workflow; no fallback. Public app factory `create_app`, dependencies on app.state, `AgentHarness.run(action, build_id, payload, llm=...)`; spans router/hello_function/hello_llm/guardrail. Added generated uv.lock outside Files for reproducibility. AGENTS.md records ADK event identity and exception logging traps.
- Tried and failed: initially matched function event author instead of node_info.path; then corrected a messages INSERT placeholder count. Reviewer P1 provider-log exposure fixed with on_model_error_callback; captured-log regression passes.
- Gotchas: none beyond Known gotchas.
- Left open: P2 unverified setuptools build dependency in pyproject.toml; user approval requested, pending.
- Next: resume 1.1 after user permits setuptools and fixes API-key restrictions; record approved dependency through the blueprint workflow, rerun live check, then mark done. Never print the key.

## 2026-10-19: Task 1.1 completed after credential update
- Status: done
- Plan check: off
- What changed: user replaced the API key and approved setuptools; added its dependency-table entry and ran `blueprint.py deps --write`, which verified setuptools 84.0.0 and refreshed all dependency verification dates. Source implementation unchanged from the reviewed skeleton.
- Checks: `uv run pytest tests/test_skeleton.py` PASS (7); `uv run pytest` PASS (7, 1 live deselected); `uv run pytest -m live tests/live/test_models.py` PASS (1), printing both gemini-4-argon and gemini-3.8-flash available. `uv sync` PASS. Uvicorn started on port 8000 with the new key; `curl.exe --fail --silent localhost:8000/api/health` returned `{"status":"ok"}`. One upstream Starlette/httpx deprecation warning remains.
- Decisions: retain user-approved setuptools as the build backend; dependency registry verification recorded in essentials. Existing model defaults remain because both are available.
- Tried and failed: previous API_KEY_SERVICE_BLOCKED resolved by the user's new key.
- Gotchas: none beyond Known gotchas.
- Left open: none; reviewer confirmed P1 and P2 resolved and no findings remain.
- Next: Task 1.2 Builds and data intake to BigQuery. Start a new chat and invoke blueprint-solution-builder.

## 2026-10-19: Recheck latest API key
- Status: done
- What changed: no implementation changes; retried the live check at the user's request with the current root .env.
- Checks: `uv run pytest -m live tests/live/test_models.py` PASS (1); gemini-4-argon and gemini-3.8-flash both available. One upstream Starlette/httpx deprecation warning.
- Decisions: none.
- Next: Task 1.2 remains next.

## 2026-10-19: Task 1.2 preflight stopped on BigQuery access
- Status: partial
- Plan check: off
- What changed: started task 1.2 and saved folder checkpoint `.blueprint/snapshots/task-1.2-1.zip`; no implementation changes.
- Checks: `uv run python -` preflight confirmed GCP project configured and ADC available; BigQuery `get_dataset` on the configured dataset returned HTTP 403, reason `forbidden`. Caller lacks `serviceusage.services.use` on ADC quota project `ai-projects-250716` (configured BigQuery project is `wti-bigquery-poc`). No CSV uploaded. Done-when and full pytest checks not run because the skill requires verifying live-check prerequisites before code.
- Decisions: leave task started and pause before implementation under the builder Stop early rule; do not alter IAM or ADC configuration without resolving the intended quota project with the user.
- Tried and failed: read-only BigQuery dataset preflight failed with the permission error above.
- Gotchas: none.
- Left open: required live BigQuery access.
- Next: user fixes ADC quota-project access (grant Service Usage Consumer on the intended quota project or configure an accessible quota project), then resume task 1.2 with blueprint-solution-builder and rerun preflight before implementation.

## 2026-10-19: Task 1.2 GCP project changed by user
- Status: partial
- Plan check: off
- What changed: user explicitly selected `ai-projects-250716`; updated only GCP_PROJECT_ID in root .env (authorized configuration exception outside backend). No secret values printed.
- Checks: configuration edit succeeded; BigQuery preflight and tests pending the user's ADC account change.
- Decisions: use ai-projects-250716 as the BigQuery project and intended ADC quota project. User will perform interactive ADC login with a different account.
- Left open: new ADC login and successful BigQuery access preflight.
- Next: after user completes login and sets ADC quota project to ai-projects-250716, rerun preflight and resume task 1.2.

## 2026-10-19: Task 1.2 Builds and data intake to BigQuery
- Status: done
- Plan check: off
- What changed: build create/list/get; CSV, GCS and existing BigQuery intake; aggregate profiles and OKF docs; traced ADK code nodes. Added main.py/graph.py wiring outside Files as announced. Created configured dss_demo dataset in ai-projects-250716 (US).
- Checks: `uv run pytest tests/test_intake.py` PASS (23); `uv run pytest` PASS (30, 1 live deselected). Manual live API create/upload both 201; BigQuery and API row counts both 3; normalized columns confirmed. Read-only reviewer: no findings after fixes. One upstream Starlette/httpx warning.
- Decisions: API columns expose only name/type/sample; detailed statistics and date_like remain in columns_json and data-profile.md frontmatter sources. Tables append source identity for safe retries. GCS uses full-file inferred positional schema and generation checks before/after load; uploads enable autodetect with normalized headers. No new dependencies. Recorded BigQuery load-option constraint in AGENTS.md.
- Tried and failed: live load initially rejected POSITION with autodetect; corrected and live check passed. Earlier quota permission resolved by user.
- Gotchas: none beyond Known gotchas.
- Left open: none.
- Next: Task 1.3 Thin slice: fixed spec to prototype, recipe and dry-run build. Start a new chat and invoke blueprint-solution-builder.

## 2026-10-19: Task 1.3 Thin slice implementation; review pending
- Status: partial
- Plan check: off
- What changed: typed fixture spec, shared integer layout, basic commentable prototype, deterministic recipe compiler, dev-only load-spec, recipe/run APIs and threaded local engine execution. Wired main.py and harness/graph.py outside Files as announced; config.py needed no change.
- Checks: `uv run pytest tests/test_thin_slice.py` PASS (7); `uv run pytest` PASS (37, 1 live deselected). Real engine via default command with DSS_ENGINE_DRY_RUN=1: load-spec 200, recipe 200 (10 ops), run 202, final stage done/version ok. One upstream Starlette/httpx warning. Independent reviewer failed before findings due to account usage limit.
- Decisions: basic boxes/labels only; full chart/background rendering remains task 4.1. Recipe preview uses engine print. Engine env resolves root dotenv plus process overrides; Popen executes from backend in a worker thread, holds one application engine lock, redacts credential strings recursively, and drops stderr. Failed runs return to prototype; partial runs reach done. No new dependencies.
- Tried and failed: first check caught renderer quoting syntax; fixed, subsequent checks pass.
- Gotchas: none.
- Left open: required independent review; no findings received.
- Next: resume task 1.3 with blueprint-solution-builder after reviewer usage is available. Run read-only review per assets/review-brief.md against blueprint.py diff and Layout/Recipe compiler Specs; fix findings, rerun checks, record done and run blueprint.py done 1.3. Implementation retained; do not start task 2.1 yet.

## 2026-10-19: Task 1.3 Thin slice: fixed spec to prototype, recipe and dry-run build
- Status: done
- Plan check: off
- What changed: completed independent review; fixed explicit layer=all support and process-tree cleanup on timeout/cancellation. Added regressions for a hanging child through uv and cancellation. Preserved the typed fixture, shared layout, basic prototype, compiler, routes and traced execution from the earlier session.
- Checks: `uv run pytest tests/test_thin_slice.py` PASS (9); `uv run pytest` PASS (39, 1 live deselected). Real engine with DSS_ENGINE_DRY_RUN=1: load-spec 200, recipe 200 (10 ops), run 202, final done/version ok. Reviewer: no findings after fixes. One upstream Starlette/httpx warning.
- Decisions: thin-slice boxes/labels and engine-print preview remain; full data renderer/background is task 4.1. Windows cleanup uses taskkill /T /F; POSIX uses a dedicated process group. Cancellation waits for worker cleanup and restores prototype before propagating. Added process-tree gotcha to AGENTS.md. No new dependencies.
- Tried and failed: none; both review fixes passed their first checks.
- Gotchas: none beyond Known gotchas.
- Left open: none.
- Next: Task 2.1 Procedural and semantic memory, knowledge seed. Start a new chat and invoke blueprint-solution-builder.

## 2026-10-19: Task 2.1 Procedural and semantic memory, knowledge seed
- Status: done
- Plan check: off
- What changed: added read-only SkillLoader and SemanticNavigator, 12 catalog concepts, four contract archetypes, and sourced Data Studio limits. Added each knowledge folder's index/log to satisfy the OKF convention.
- Checks: `uv run pytest tests/test_memory_semantic.py` PASS (11); `uv run pytest` PASS (50, 1 live deselected). Read-only blueprint reviewer: no findings. Existing Starlette/httpx deprecation warning remains.
- Decisions: SkillLoader.load(name) returns full UTF-8 Markdown, unknown names raise FileNotFoundError. Navigator read(path) returns Concept(path, metadata, text); list_folder follows index links; search combines exact type, all requested tags, and case-insensitive substring text. Runtime concepts override seed paths; reads refresh without caching. Catalog sizes are grid units; counts are conservative POC limits, separate from sourced product maxima. date_dimension/breakdown/field are separate slots. No new dependencies or runtime semantic writes. Skill authoring remains with later node tasks.
- Tried and failed: none.
- Gotchas: none.
- Left open: none.
- Next: Task 3.1 Interview node and chat API. Start a new chat and invoke blueprint-solution-builder.

## 2026-10-19: Task 3.1 Interview node and chat API
- Status: done
- Plan check: off
- What changed: interview Workflow branch, REST start/turn/history, guarded incremental SSE, explicit readiness tool, episodic persistence, interview/archetype skills and versioned prompt. Added main.py routing, initial context.py assembler and tracing.py tool counts outside Files as announced.
- Checks: `uv run pytest tests/test_interview.py` PASS (12); `uv run pytest` PASS (62, 1 live deselected). Live sample CSV upload 201, interview start 202, Gemini: "Who is the primary audience that will be reviewing the `revenue` figures in this dashboard?" Two deltas; successful trace. Read-only reviewer: no findings after fixes. Upstream Starlette deprecation and ADK experimental warnings.
- Decisions: context order is prompt, skills, aggregate profile, last 12 messages, current input; chars/4 budget, oldest history dropped first. Callable instructions preserve braces. Reserve the build before background dispatch; readiness remains true across refinements. Four model calls maximum. Stream guards withhold a secret/marker-sized tail; successful replies persist once, readiness effects follow final guardrail. Added ADK interpolation gotcha to AGENTS.md. No new dependencies.
- Tried and failed: review found buffered delivery and string-instruction interpolation; fixed with incremental streaming and callable instructions, regressions passed.
- Gotchas: none beyond Known gotchas.
- Left open: none.
- Next: Task 3.2 Plan node, build docs and BigQuery view. Start a new chat and invoke blueprint-solution-builder.

## 2026-10-19: Task 3.2 Plan node, build docs and BigQuery view
- Status: done
- Plan check: off
- What changed: structured planner, OKF bundle, deterministic per-version view, one dry-run repair, /plan dispatch and failure recovery. Wired graph.py/context.py outside Files as announced.
- Checks: `uv run pytest tests/test_plan.py tests/test_view_sql.py` PASS (23); `uv run pytest` PASS (85, 1 live deselected). Live sample CSV upload, dry-run, view creation and SELECT * PASS (2 rows, derived net sum 270), repeated on final code. Read-only reviewer: no findings after fixes. Existing upstream warnings remain.
- Decisions: derived-fields.md records fields, joins and view (fully qualified table). Success remains at plan until spec/render tasks. Original source identifiers are quoted; exposed names use snake_names; common joined names expose the first occurrence. Initial context uses full transcript with oldest-first budget trimming, reserving 4k tokens for repair. No new dependencies. Added ADK output_schema logging gotcha to AGENTS.md.
- Tried and failed: corrected incomplete test fixtures, ADK dictionary output and wrapped-error propagation; review fixes cover source names, SQL literal/type syntax and pre-schema secret guarding.
- Gotchas: none beyond Known gotchas.
- Left open: none.
- Next: Task 3.3 Spec node and validator. Start a new chat and invoke blueprint-solution-builder.

## 2026-10-19: Task 3.3 Spec node and validator
- Status: partial
- Plan check: off
- What changed: catalog-backed validation, typed datasource fields, shared layout checks, plan/spec/validate graph with two spec repairs, safe persistence and GET /spec. Added prompt/skill and regression/property tests; context.py and test_plan.py changes were announced.
- Checks: `uv run pytest tests/test_spec_validate.py tests/test_layout.py tests/test_spec_node.py -q` PASS (26); `uv run pytest -q` PASS (111, 1 live deselected). Read-only reviewer: no findings. Earlier real Gemini sample spec validated; its exact pass count was not captured. Final live repeats FAIL with provider ConnectError: All connection attempts failed; credential-free endpoint request also stalled.
- Decisions: catalog frontmatter owns limits/roles. Code fixes datasource identity to the actual view projection. Full spec request is capped at 16k estimated input tokens including schema, with workflow history excluded. Initial plus two spec repairs; plan allows five total calls including SQL repair. Success stays at plan until task 4.1. No dependencies added. Recorded Gemini schema gotcha in AGENTS.md.
- Tried and failed: response_schema numeric literals rejected; response_json_schema resolved it. Plan mocks needed schema-aware responses. Final live verification awaits connectivity.
- Gotchas: none beyond Known gotchas.
- Left open: required final live first/second-pass verification.
- Next: Resume 3.3; rerun real Gemini sample and query the trace WHERE node='spec' to confirm <=2 spec calls, then run done and commit. Network clarification is pending; task remains [~].

## 2026-10-19: Task 3.3 Spec node and validator
- Status: done
- Plan check: off
- What changed: completed catalog-backed spec validation, bounded repair routing, persistence and GET /spec; finished final verification after connectivity recovered.
- Checks: `uv run pytest tests/test_spec_validate.py tests/test_layout.py tests/test_spec_node.py -q` PASS (26); `uv run pytest -q` PASS (111, 1 live deselected). Real Gemini sample spec validates on its first call, confirmed from the spec trace. Read-only reviewer: no findings. Existing upstream warnings remain.
- Decisions: catalog frontmatter owns limits and slot roles. Datasource matches the view projection. Full request capped at 16k estimated input tokens, including schema; unrelated workflow history excluded. Initial spec plus two repairs; plan allows five calls including SQL repair. Success stays at plan until task 4.1. No new dependencies. Gemini schema gotcha is recorded in AGENTS.md.
- Tried and failed: initial response_schema rejected numeric literals; response_json_schema resolved it. Earlier final live repeats hit connectivity failures; the resumed live check passed.
- Gotchas: none beyond Known gotchas.
- Left open: none.
- Next: Task 4.1 Prototype renderer and background. Start a new chat and invoke blueprint-solution-builder.

## 2026-10-19: Task 4.1 Prototype renderer and background
- Status: done
- Plan check: off
- What changed: full themed ECharts/HTML renderer, parallel aggregate queries/cache, decoration screenshots, prototype API data and plan-to-render graph wiring.
- Checks: `uv run pytest tests/test_render.py` PASS (15); `uv run pytest` PASS (126, 3 live deselected); `uv run pytest tests/test_render.py -m live -s` PASS (2). Twelve queries plus actual capture: 1.01 s; repeat: zero new queries. Real BigQuery sample render: 3.42 s, browser total 224.48. All 12 types inspected; seven ECharts SVGs, no errors/fallbacks. Screenshots: `.blueprint/qa/{prototype,decoration,catalog}.png`. Reviewer: no findings.
- Decisions: version-folder `aggregate-cache.json` keyed by SQL SHA256 survives layout-only revisions; API reads cached data without queries. Geography groups centroid GeoJSON and plots coordinates. Only time_series groups date_dimension. Worker finishes before cancellation releases build. Included graph/test doubles and anchored runtime ignore rule; previously ignored BigQuery module and sample fixtures now tracked. User supplied ai-projects-250716, saved through Settings; no dependencies added.
- Tried and failed: invalid configured project blocked live upload; corrected setting resolved it. Review caught date grouping, geography and compact-layout defects; fixed and reverified.
- Gotchas: none.
- Left open: none.
- Next: Task 4.2 Revise from comments. Start a new chat and invoke blueprint-solution-builder.
