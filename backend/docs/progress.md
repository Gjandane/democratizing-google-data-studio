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

## 2026-10-19: Task 4.2 Revise from comments
- Status: partial
- Plan check: off
- What changed: attempted comments API, ADK revision branch, scoped RFC 6902 patches, one repair, staged render/persistence, decisions and regression tests. Two live failures triggered skill-required restore; implementation is recoverable in stash `blueprint: task 4.2 failed attempt 2026-10-19 09:37`.
- Checks: before restore, `uv run pytest tests/test_revise.py` PASS (24); `uv run pytest` PASS (150, 3 live deselected). Manual live FAIL: comment accepted (202), worker returned `400 INVALID_ARGUMENT`; sample spec remains version 1. No final review performed.
- Decisions: no plan/design changes. Added AGENTS.md diagnostic gotcha. Attempt used per-comment indexed patches, deterministic application order, identity-based scope with collision-justified neighbour moves, 6k input budget, and staging/rollback before publication. These choices remain unshipped.
- Tried and failed: original Revision schema with Any value rejected live; explicit scalar/object/array anyOf value schema also rejected by minimal worker call. Provider gave no field-level diagnostic. Initial move test collided with source note; corrected fixture passed. Manual trace polling found /api/traces unavailable; query SQLite traces instead.
- Gotchas: model/schema cause remains unisolated; API key was sanitized in diagnostics.
- Left open: required live title-only revision and review.
- Next: Restore the named stash, isolate the smallest accepted worker schema (including a plain-model control), then fix/retest and complete 4.2. Start a new chat and invoke blueprint-solution-builder.

## 2026-10-19: Task 4.2 Revise from comments
- Status: done
- Plan check: off
- What changed: recovered comments API, scoped RFC6902 revision branch, one repair, staged rendering/publication and decisions; fixed provider schema compatibility.
- Checks: `uv run pytest tests/test_revise.py` PASS (27); `uv run pytest` PASS (153, 3 live deselected). Final real Gemini sample: only title grows 28px to 36px, spec_version increments. Browser screenshots inspected: `.blueprint/qa/revise-before.png`, `.blueprint/qa/revise-after.png`. Reviewer no-op finding fixed/rechecked; no remaining findings.
- Decisions: sequential per-comment patches; collision-justified neighbour moves; canonicalize before detecting changes. Stage artifacts with rollback, reuse aggregates. Graph/context edits provide required wiring. Provider omits array maxima; Pydantic retains 20 comments/40 operations. Added AGENTS.md gotcha; no dependencies added.
- Tried and failed: controls isolated provider rejection to nested maxItems. Initial live font patch matched renderer default; supplying defaults fixed visible growth. Removing a default key falsely incremented version; canonicalization fixed it.
- Gotchas: none beyond Known gotchas.
- Left open: none.
- Next: Task 4.3 Recipe compiler (full), deep work. New chat, gpt-6.1-sol at high, invoke blueprint-solution-builder.

## 2026-10-19: Task 4.3 Recipe compiler (full)
- Status: done
- Plan check: off
- What changed: wired the compile node into POST /recipe with atomic UTF-8/LF publication; compute Layout boxes once, preserve reading order, and fix add_page's name argument collision. Added all-12-type golden spec/recipe and contract tests.
- Checks: `uv run pytest tests/test_recipe_contract.py` PASS (8); `uv run pytest` PASS (161, 3 live deselected, existing upstream warnings). Schema, byte equality on two writes, shuffled ordering, all aggregations/options, extra-page ops, op-id capacity and API ids/traces checked. Read-only reviewer: no findings. Git attributes confirm golden recipe eol=lf.
- Decisions: compile node returns the recipe string; compilation ValueError maps to invalid_recipe without replacing the existing recipe. No new dependencies. Added backend .gitattributes outside task Files to preserve golden bytes with core.autocrlf=true; the POC's one-page spec restriction stays in place.
- Tried and failed: first extra-page test exposed the existing helper's name collision; a positional-only op name fixed it.
- Gotchas: none.
- Left open: none.
- Next: Task 4.4 Execute, publish, versions and engine endpoints, routine work. New chat, gpt-6.1-sol at Light (low), invoke blueprint-solution-builder.

## 2026-10-19: Task 4.4 Execute, publish, versions and engine endpoints
- Status: done
- Plan check: off
- What changed: extracted publish, fixed published/building version statuses and sign-in errors; added version creation, engine status/login, document/file reads and traces. Added fixture relay and endpoint contract checks.
- Checks: `uv run pytest tests/test_execute.py tests/test_api_contract.py` PASS (7); `uv run pytest` PASS (168, 3 live deselected, 2 upstream warnings). Installed engine dry-run through API reached done/published. Read-only review: two P2 lock/cleanup findings fixed; follow-up no findings.
- Decisions: versions copy spec/render inputs/docs, omit recipe/events/screens, and retain the datasource view. Login has a build-less Workflow/trace; check/login reserve the engine lock and await process-tree cleanup on cancellation. Main/graph wiring and the earlier thin-slice status assertion needed changes outside Files. No dependencies added. Added HTTP path-normalization gotcha to AGENTS.md.
- Tried and failed: initial shape helper confused error objects with nullable trace errors; literal dot-dot test was normalized by the HTTP client. Corrected helper and used encoded path.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: Task 5.1 Cloud mode: static frontend, PORT, access code, DB backup; deep work due to its Spec. New chat, gpt-6.1-sol at high, invoke blueprint-solution-builder.

## 2026-10-19: Task 5.1 Cloud mode: static frontend, PORT, access code, DB backup
- Status: done
- Plan check: off
- What changed: added shared-code/header and HMAC-cookie access, cloud startup guards, SPA serving, module server options, SQLite restore and serialized periodic/shutdown snapshots.
- Checks: `uv run pytest tests/test_cloud_mode.py` PASS (22); `uv run pytest` PASS (190, 3 live deselected, 2 upstream warnings); `git diff --check -- .` PASS. Read-only review: P2 unbounded backup teardown fixed; follow-up no findings.
- Decisions: runtime secrets are SecretStr and public settings use an allowlist. Agent namespace reserves its independent token gate for 5.2; settings locking stays there too. Cloud DB defaults to local temp and rejects a path inside the data directory. Committed-write generations preserve writes during snapshots. Unique local temp folders hold dss.bak; volume receives only copy/rename. Backup teardown shares a 3-second deadline and daemon workers avoid executor shutdown hangs. No dependencies added. Recorded Windows static-path and lifespan-timeout gotchas in AGENTS.md.
- Tried and failed: first check exposed Windows backslashes bypassing the SPA API exclusion; normalized separators and reran successfully.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: Task 5.2 Agent mode: job queue and agent endpoints; deep work due to its Spec. New chat, gpt-6.1-sol at high, invoke blueprint-solution-builder.

## 2026-10-19: Task 5.2 Agent mode: job queue and agent endpoints
- Status: done
- Plan check: off
- What changed: added the authenticated agent API, asynchronous FIFO, heartbeat status, job downloads/screenshots, inactivity expiry and restart recovery. Agent runs retain the Workflow, publish and trace lifecycle; local and remote events share EngineEvents.
- Checks: `uv run pytest tests/test_agent_server.py` PASS (35); `uv run pytest` PASS (225, 3 live deselected, 2 upstream warnings); `git diff --check -- .` PASS. Independent read-only review: no findings.
- Decisions: one-time polling uses an asyncio condition and FIFO; per-job locks serialize events, finish and expiry. Finished responses wait for publish/trace cleanup. Job files follow recipe path order, deduplicated after recipe.jsonl. Bad report URLs fail before persistence. Agent settings ignore saved deployment overrides; only models remain mutable. Shutdown wakes polls and cancels remote waits. Recovery finalizes interrupted runs without reissuing jobs. No dependencies added. Added the httpx header gotcha to AGENTS.md.
- Tried and failed: non-ASCII string headers failed in the client before reaching authentication; used an ASCII wrong token. A deliberately tiny timeout also expired a retry before collection; restored its normal timeout.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: Task 5.3 The dss-agent build agent; deep work because it implements the remote execution Spec. New chat, gpt-6.1-sol at high, invoke blueprint-solution-builder.

## 2026-10-19: Task 5.3 The `dss-agent` build agent
- Status: done
- Plan check: off
- What changed: added the `dss-agent` console script (src/dss/agent/client.py): heartbeat thread, idle-only `dsengine check`, long-poll loop, job download into `<data>/agent/<build_id>/v<n>/`, engine run with 1 s event batches, screenshot PUTs, finished report, 404 cleanup, retry/backoff exit. Live-uvicorn tests in tests/test_agent_client.py.
- Checks: `uv run pytest tests/test_agent_client.py` PASS (12; stable over 3 runs); `uv run pytest` PASS (237, 3 live deselected, 2 upstream warnings); `git diff --check` PASS. Mutation check: dropping the engine `cwd` fails the screenshot test. Manual: port 8000 held by an unrelated user process, so ran the same command on 8765: real engine `--dry-run` via `uv run --project backend dss-agent` from the repo root took the dev sample build (placeholder background_p1.png; dev load-spec renders none) to done/published; token absent from logs. Reviewer: no P0/P1; P2 tests and four P3s fixed.
- Decisions: reuses Config.from_env, engine_command, terminate_tree. Constants: heartbeat 10 s, check 60 s (poll wait shortened so checks land on time), poll 25 s, HTTP 40 s read/10 s connect, flush 1 s, retry budget 60 s from first failure, backoff 1-10 s doubling; transport errors, 429 and 5xx retry; 401/agent_mode_off/non-JSON poll exit 2/2/1. Jobs validated (ids, ints, plain file names) before any path use; existing version folder replaced; screenshots PUT before their batch; tokens redacted from events and stderr tail. http only for loopback; server URL without a path; hidden `--token` rejected without echo. Ctrl+C reports a best-effort failed finish. Fixed AGENTS.md agent command, added a gotcha. No dependencies added.
- Tried and failed: first test run nested the agent data dir (test bug); fixed.
- Gotchas: none beyond AGENTS.md.
- Left open: P3 retry budget can stretch by one hung attempt (up to ~40 s) - src/dss/agent/client.py; P3 Ctrl+C on Windows may lag until an idle long poll returns (≤25 s), unverified - src/dss/agent/client.py.
- Next: Task 6.1 Episodic retrieval and working memory assembly.

## 2026-10-19: Task 6.1 Episodic retrieval and working memory assembly
- Status: done
- Plan check: off
- What changed: episodic.py gained FTS5 relevance (`relevant`, `fts_query`), `merge` and `recall`; context.py is now one assembler (`Section`, `Context` str subclass with `sections`/`counts()`/`record()`, `assemble`, ORDER, BUDGETS) with interview/plan/spec/revise recipes; nodes record section tokens (plus `dropped`, `repair_tokens`) in their trace spans; db.py indexes messages(build_id).
- Checks: `uv run pytest tests/test_episodic.py tests/test_context.py` PASS (45); `uv run pytest` PASS (282, 3 live deselected, 2 upstream warnings); `git diff --check` PASS. Mutations (drop order swapped, most-relevant hit dropped first, no sort, first concept droppable, start query restored) each fail tests. Reviewer: no P0/P1; four P3s fixed.
- Decisions: tokens = chars/4 always. RESERVES outside context: plan 4k, spec 4k, revise 1.5k (old char limits kept). FTS = OR of quoted distinct lowercased non-stopword letter/digit terms (≤32), bm25 then newest; history = 12 messages before the saved input; interview start = recency only. Drops one entry at a time: past least-relevant first, history oldest first, semantic last first keeping the first; empty list sections omitted. Plan transcript = node None/interview. Spec catalog = allowed types named in kpis/questions (spaces, plurals), else all allowed, index order. Revise catalog = targeted components' types only. User facts = `user/` concepts minus index/log; unreadable ones skipped with a warning. Added an AGENTS.md gotcha. No dependencies added.
- Tried and failed: revise-order test used `app` without `client` (lifespan not started); fixed.
- Gotchas: none beyond AGENTS.md.
- Left open: P2 budgets use chars/4, not the API token counter (undercounts JSON/CJK) - src/dss/harness/context.py.
- Next: Task 6.2 Consolidation. Start by reading docs/architecture.md#Consolidation; user facts are read by plan_context from `data/knowledge/user/` via list_folder("user").

## 2026-10-19: Task 6.2 Consolidation
- Status: done
- Plan check: off
- What changed: new consolidate node (consolidate.py, prompts/v1/consolidate.md); publish counts each done build and schedules consolidation in the background; config.py gains `consolidate_every` (DSS_CONSOLIDATE_EVERY, default 5); context.py gains the consolidate recipe.
- Checks: `uv run pytest tests/test_consolidation.py` PASS (11); `uv run pytest` PASS (293, 3 live deselected, 2 upstream warnings); `git diff --check` PASS. Mutations (publish awaits consolidation; Previously dropped; reset to 0) each fail tests. Reviewer: no P0-P2; four P3s fixed.
- Decisions: Outside Files: config.py (tests building Config(...) ignore the root .env's demo value 1) and context.py (context only from there). Own Workflow START -> LlmAgent -> write -> guardrail, one trace (node consolidate, build_id NULL), run events with build_id None; not graph.py's router. Counter incremented after build.finished under a lock shared with the snapshot (latest chats_since ok/partial build.finished events); reset subtracts the consumed count; failures keep it, so the next done build retries all. Builds without docs: no LLM call, counter consumed, trace span `skipped`. Inputs: brief.md + design.md + decisions.md (3000 chars each), newest first as droppable `past`; budget 16k, reserve 1k. Model returns {slug,type,title,statement}; code writes files: ASCII slugs, `updated` date, old statement under "## Previously" as `- <old updated>: <text>`; index.md lists `[title](slug.md) (type, updated): statement` with brackets stripped; log.md (`Change Log`) newest first. No dependencies added.
- Tried and failed: none.
- Gotchas: none beyond AGENTS.md.
- Left open: P3 user/index.md grows without bound; past ~12k tokens every consolidation fails over budget - src/dss/harness/context.py. Not run: live Gemini check of the Facts schema.
- Next: Task 7.1 UX audit and style from picture. Start with the spec_context in src/dss/harness/context.py (style.md goes there) and the revise node's structured-output pattern.

## 2026-10-19: Task 7.1 UX audit and style from picture
- Status: done
- Plan check: off
- What changed: new ux_audit and style_extract nodes (+ skills, prompts); `POST /audit` (prototype.py) and `POST /style-images` (builds.py), both 202 + background run; context.py gains ux_audit_context, style_context and optional style.md in spec_context; graph.py routes both actions.
- Checks: `uv run pytest tests/test_audit_style.py` PASS (17); `uv run pytest` PASS (310, 3 live deselected). Reviewer: P2 (filenames in frontmatter could break build_response) and P3 (dead assertion) fixed and rechecked.
- Decisions: Outside Files: context.py, graph.py (required wiring). Built by a Sonnet worker from build notes. Audit: one LLM call, no repair; findings {component_id, severity high/medium/low, issue, suggestion} max 20; unknown ids dropped; code formats one assistant message, high first; none -> "UX audit: no issues found."; no user message saved. Style: 1-3 PNG/JPEG, 5 MB each, suffix must match magic bytes, else 422 invalid_source; file checks run before stage/busy checks (409 wrong_stage in plan/build or active). StyleProfile {palette 2-8 hex, background, surface, text, accent, font_family, radius 0-32, notes}; hex uppercased; style.md frontmatter holds profile + sanitized source names (`[A-Za-z0-9._-]`, dash runs collapsed); notes body only. Images not persisted; budget text-only 6000, 1500/image recorded in span. Provider schemas strip maxItems. No dependencies added.
- Tried and failed: none.
- Gotchas: none beyond AGENTS.md.
- Left open: Not run: live Gemini check of the audit and style schemas (hex pattern in provider schema untested live).
- Next: Task 7.2 LLM-judge eval script. Start with the ux_audit node's structured-output pattern and the traces table.

## 2026-10-19: Task 7.2 LLM-judge eval script
- Status: done
- Plan check: off
- What changed: added `python -m dss.ops.eval <build_id>`, a worker-model ADK Workflow scoring the current spec against questions and catalog guidance; prints score JSON and persists scores/version on one trace, including failed-run traces.
- Checks: `uv run pytest tests/test_eval.py` PASS (13); `uv run pytest` PASS (321, 3 live deselected, 2 upstream warnings; collected before the final two added tests, which passed in the targeted run). CLI `--help` PASS. Read-only reviewer: no findings.
- Decisions: context.py outside Files is required by the context-only assembly convention. Judge context budget 16000 estimated tokens, 1000 reserved; oversized/missing context fails before the model call. Strict integer question_coverage/catalog_fit/layout_balance scores 1-5; code computes pass iff all >=3. Current version is captured before evaluation and stored in the trace span. One call, no repair; no new dependencies or API changes.
- Tried and failed: none.
- Gotchas: none.
- Left open: live Gemini evaluation not run.
- Next: Task 7.3 Research mode, routine work. Start a new chat with gpt-6.1-sol at Light (low) and invoke blueprint-solution-builder.

## 2026-10-19: Task 7.3 Research mode
- Status: partial
- Plan check: off
- What changed: started task 7.3; no application code changed. Prerequisite inspection found the prescribed search tool cannot enforce the required fetch cap.
- Checks: inspected installed ADK GoogleSearchTool: process_llm_request delegates to provider-native types.GoogleSearch; no local execution. GoogleSearch fields are search_types, blocking_confidence, exclude_domains and time_range_filter; no fetch limit. Done-when and Test (all) not run; implementation has not begun.
- Decisions: do not substitute a model-call count or truncate citations and claim that enforces 20 fetches. Await user direction before changing the planned budget or search mechanism.
- Tried and failed: none.
- Gotchas: provider-native Google Search hides its individual fetches from the application.
- Left open: enforceable research fetch budget and live check.
- Next: resolve whether the architect should revise task 7.3 to use an application-controlled retrieval mechanism, or explicitly replace the fetch cap with a different measurable budget; then resume implementation.

## 2026-10-19: Task 7.3 Research mode
- Status: done
- Plan check: off
- What changed: research API/Workflow, procedural skill, versioned prompt, reusable `python -m dss.data.research` scraper, CSV/provenance output and research-source intake.
- Checks: `uv run pytest tests/test_research.py -q` PASS (27); `uv run pytest` PASS (350, 3 live deselected, 2 upstream warnings). Live API prompt "NBA players 2025-26 season stats": 202, successful trace, 734 rows/32 columns loaded in BigQuery after 5 HTTP requests. Current scraper CLI independently confirmed 734 rows. Read-only reviewer: no findings after fixes. `git diff --check -- .` PASS.
- Decisions: user approved budget refinement: one search-enabled model call, 20 application HTTP attempts including redirects/failures, one metadata-only selector. Provider-internal search fetches excluded. Updated plan/architecture/essentials and stamped; added graph/context/scraper files. Stdlib scraper pins public DNS, bounds responses and rejects headerless/ragged tables. No dependencies added. AGENTS records native-search and project-ID gotchas.
- Tried and failed: corrected test event column; review fixes prevent raw-row metadata and preserve provenance on selection failure. First live load rejected configured project ID; isolated rerun used previously verified ai-projects-250716.
- Gotchas: recorded in AGENTS.md.
- Left open: configured GCP_PROJECT_ID hackaton_aicup26 is invalid; configuration unchanged. Live artifacts: data/research-live/builds/b_fd93e999922d/v1/.
- Next: all 19 backend tasks complete; final audit with blueprint-solution-architect in a new chat.

## 2026-10-19: Audit (final)
- Status: DEFECTS. First final audit of this version; all 19 original task suites rerun. The
  passing offline suite does not establish live or cross-node correctness. Seven fix tasks
  (9.1-9.7) appended; original task markers unchanged. No product source or tests changed.
- What changed: docs/plan.md adds Phase 9; architecture.md specifies the corrections and folds
  durable task decisions into implementation conventions; essentials summarize them and stay
  below the one-page limit; AGENTS.md moves code/testing conventions out of Known gotchas;
  PRD clarifies the shared-code non-goal and records limitations. Contracts and other parts untouched.
- Independent review: blueprint_reviewer read the finished backend against all task Specs and
  Review focus fields, PRD, contracts, and progress Decisions. Four integration findings accepted
  after parent reproductions. No built non-goal or unverified declared dependency. Metadata-only
  backend history scan: 18 commits, 227 blobs, no tracked .env or Google-key/GitHub-token/private-key
  pattern hit; this is a scoped pattern check, not a whole-program security audit.

### Current runs
- Test (all): `uv run pytest` PASS: 350 passed, 3 live deselected, 2 upstream warnings,
  155.95 s. Warnings: Starlette/httpx deprecation and ADK experimental function-schema feature.
- Every original Done-when pytest command passed in this session (same file arguments as plan;
  quiet output only). No original automated task command skipped or superseded:

| Task | Passed | Task | Passed | Task | Passed |
|---|---:|---|---:|---|---:|
| 1.1 | 7 | 1.2 | 23 | 1.3 | 9 |
| 2.1 | 11 | 3.1 | 12 | 3.2 | 23 |
| 3.3 | 26 | 4.1 | 15 | 4.2 | 27 |
| 4.3 | 8 | 4.4 | 7 | 5.1 | 22 |
| 5.2 | 35 | 5.3 | 12 | 6.1 | 45 |
| 6.2 | 11 | 7.1 | 17 | 7.2 | 13 |
| 7.3 | 27 | | | | |

- Contract conformance: test_api_contract.py PASS as part of 4.4; test_recipe_contract.py
  PASS as 4.3. Manual conventions check: ports/env names, root-relative runtime paths, IDs,
  independent access/agent credentials and UTC times match; sorting, image packaging and
  cloud engine absence have the defects below. No shared contract changes are needed.
- `uv run pytest -m live tests/live/test_models.py -q`: PASS (1): both configured model names
  available. `uv run pytest tests/test_render.py -m live -q`: PASS (2), actual Chromium capture
  and 12-component render budget. A fresh process using the documented `uv run uvicorn
  dss.main:app --port <free port>` returned health `{status:ok}`; isolated runtime, no reload.
- Live API upload: PASS (3 rows, order_date/region/revenue), actual BigQuery project
  ai-projects-250716 in isolated Config only. Interview start/answer: PASS; first question names
  real columns and contains one question. Real /plan: FAIL, trace r_75cdb09c63da stops in plan
  before view/spec. Therefore 3.2/3.3's current full live acceptance remains failed/unverified.
- Minimal provider isolation: Plan via converted response_schema -> 400 INVALID_ARGUMENT on
  both configured models, unknown additional_properties; the same Plan via response_json_schema
  on the planner -> PASS. Generation output/credentials were not logged.
- To test remaining paths independently, injected the existing thin-spec fixture after the
  demonstrated plan failure, created a real BigQuery view and rendered its aggregates. PASS:
  scorecard 224.48, one ECharts SVG; 1200x900 screenshot inspected, background title visible in
  a fresh capture. Real Gemini title-only comment -> spec_version 2, components unchanged,
  only p1_title changed. Real engine recipe/dry-run -> 200/202 then stage done. This fixture
  continuation does not count as a successful live interview-to-prototype flow.
- Real build agent manual command from the repo root (`uv run --project backend dss-agent
  --server <isolated local server> --dry-run`) with the installed engine -> stage done. Server
  teardown logged cancellation of its idle poll after the 2 s test shutdown timeout; no failing
  build or leaked task was observed.
- Real research API prompt "NBA players 2025-26 season stats" -> successful trace, one research
  source, 734 BigQuery rows. Local QA scripts/results/screenshots are ignored under
  .blueprint/qa/final-audit/ (prototype.png and decoration-fresh.png). Runtime test tables remain
  in the authorized demo dataset; no deployment configuration changed.
- Live token counter: 900 CJK characters estimated as 225 tokens by current chars/4 helper;
  provider counted 501. Deterministic agent retry-clock check starts another request exactly
  60 s after first failure, which can add an ordinary HTTP timeout beyond the budget.
- `blueprint.py deps`: all 17 rows FOUND; no dependencies added. Stamp PASS; lint: 0 errors,
  one advisory for 27 cumulative tasks (19 original plus 1 concurrent change plus 7 fixes in this already-split program).
  Scoped `git diff --check -- .` PASS; only six backend planning/instruction files changed.
  Independent follow-up review of Phase 9 and its Specs: no findings; reviewer inspected the
  current prototype and fresh decoration screenshots with no clipping/overlap issue.

### Findings and disposition
| Priority | Finding (current source) | Disposition |
|---|---|---|
| P1 | Plan output_schema transport rejected live; nodes/plan.py:92 | 9.1 M: response_json_schema with strict local guards; real core-flow regression |
| P1 | Hosted preview subprocesses absent engine; api/run.py:28 | 9.2 S: deterministic engine-free preview |
| P2 | Revise leaves recipe stale; nodes/revise.py:124 and api/run.py:50 | 9.3 S: refresh from current spec at execution boundary |
| P2 | Renderer reads direction, contract uses order; render/prototype.py:73 | 9.4 S: one validated sort shape |
| P2 | Valid nested image rejected by plain filename guard; agent/jobs.py:22,75 | 9.5 M: private flat-name job packaging |
| P2 | Live budgets always chars/4; harness/context.py:34 | 9.6 M: authoritative complete-request token counts |
| P3 | Retry starts an attempt at/after deadline; agent/client.py:102,112 | 9.7 S: whole-attempt remaining deadline |

- Reproductions: missing engine in agent mode makes /recipe 422 invalid_source; compile ->
  persist a revision -> /run is accepted 202 and the downloaded job contains the old recipe;
  an order:asc bar emits DESC aggregate SQL; the valid golden image spec passes validation
  then Job.prepare raises 400 invalid_name. These are defects even though current unit tests pass.
- Existing Left open items: old partial-task blockers were resolved in later task entries;
  budget and retry items become fixes. Unbounded consolidation index and unmeasured idle Ctrl+C
  latency are POC limitations in PRD Later. Optional live schema checks remain unrun and are
  also retained there. No prior open item silently treated as passing.
- Release checklist: documented backend startup PASS; live core flow FAIL at planning; known
  limitations documented; generated prototype screenshot PASS at the default canvas. Frontend,
  deployment, whole-program history and integration release checks belong to the root audit.
- Decisions: preserve the original requirements instead of waiving measured budget defects;
  no contracts/dependencies change; use an isolated previously authorized valid GCP project for
  live QA because the configured project ID has invalid syntax. The configured value and root
  .env remain unchanged. Do not move to the program integration audit until backend is ACCEPTED.
- Next: retain the program-prioritized activity task 8.1 first (gpt-6.1-sol at low/Light), then
  task 9.1 (gpt-6.1-sol at high). After both phases finish, rerun final audit, affected earlier
  suites, current API conformance and the full live core flow.

## 2026-10-19: Change activity transparency (program root)
- Status: done
- What changed: the user asked for UI transparency (what the agent is doing, elapsed time, tokens). contracts/api.md is now 1.2: new event `run.usage {run_id, node, input_tokens, output_tokens}` (running totals per run) and the list of `node` values; new fixture contracts/fixtures/api/events.usage.sse. PRD Features, architecture.md (Agent run flow, decision row) and the essentials' Contracts row updated.
- Affects: new task 10.1 (emit `run.usage` in graph.py), after the final audit's fix tasks (Depends on 9.6). No gate: frontend 6.1 builds against the fixture in parallel. First in the program's cut order. 10.1 and fix task 9.6 both edit src/dss/harness/graph.py, and 9.6 reworks token counting, so 10.1 comes after it.
- Next: the final audit's fix tasks 9.1-9.7, then 10.1.

### Final-audit reconciliation
- A concurrent program-root change added activity task 8.1 and API 1.2 after the baseline
  checks. Preserved that task and all its doc/contract updates; moved audit fixes to Phase 9
  (9.1-9.7), with unchanged task markers. The activity change remains first in plan order.
- Current audit does not certify the unimplemented run.usage extension. Its own task check and
  API 1.2 conformance must pass before the next final acceptance. Both phases remain pending.

## 2026-10-19: Task 9.1 Restore live planner schema compatibility
- Status: done
- Plan check: off
- What changed: plan/plan_repair drop ADK output_schema; before_model sends Plan's strict JSON schema as response_json_schema (response_schema cleared), replaces history with one fixed user turn and checks the whole request (schema included) against the plan budget. after_model guards and strictly validates raw output, keeps it in state for the view node and returns a placeholder with usage. New provider-request/strict-validation tests; new live interview-to-prototype test.
- Checks: `uv run pytest tests/test_plan.py tests/test_spec_node.py` PASS (24; new request test fails on old plan.py); `uv run pytest -m live tests/live/test_backend_flow.py` PASS (88 s, small_sales.csv, build b_26225492be89, runs r_b4950af59fe4/r_f0d0814bd138/r_591ca8f69634, one spec call, view 3 rows, 1200px background); `uv run pytest` PASS (354, 4 deselected). Evidence: `.blueprint/qa/final-audit/task-9.1/`. Reviewer: no findings.
- Decisions: live test uses temp data_dir/db, clears access code, sets project via PUT /api/settings from DSS_LIVE_GCP_PROJECT or stripped GCP_PROJECT_ID. No new dependencies.
- Tried and failed: none.
- Gotchas: root .env GCP_PROJECT_ID has leading whitespace (added to Known gotchas).
- Left open: renderer seen in screenshot: header title clipped/subtitle spills; table repeats `revenue` column. Not 9.1 scope.
- Next: Task 9.2 Compile and preview recipes without a server-side engine.

## 2026-10-19: Task 9.2 Compile and preview recipes without a server-side engine
- Status: done
- Plan check: off
- What changed: compiler.py adds print_line/preview, a code formatter for the `dsengine print` convention. POST /recipe previews before publishing via the compile node and never launches the engine; any compile/preview failure becomes 422 invalid_recipe and leaves the previous recipe. New fixture tests/data/recipe_preview.json; agent-mode no-engine/no-heartbeat API tests.
- Checks: `uv run pytest tests/test_recipe_contract.py tests/test_api_contract.py` PASS (18; 3 new fail on old run.py); `uv run pytest` PASS (362, 4 deselected). Reviewer: no findings.
- Decisions: fixture recorded by running `dsengine print` black-box on the golden recipe plus a crafted edge recipe. Rules inferred: sorted keys minus id/op; component_id/chart_type/control_type/dimensions/metrics -> id/type/type/dim/metric; other `_` -> `-`; lists repeat the flag, metrics `field:agg`, empty lists dropped; dicts ASCII-escaped compact sorted JSON; null/int via JSON; strings shlex.quote, or `$'..'` (escaping backslash, quote, LF, CR, TAB) when LF/CR/TAB present. Top-level bool/float raise ValueError (unrecorded). Double deterministic compile keeps compile.py unchanged. No new dependencies. Added a splitlines gotcha to AGENTS.md.
- Tried and failed: none.
- Gotchas: re-recording needs PYTHONIOENCODING=utf-8 (Windows stdout otherwise cp1252).
- Left open: none.
- Next: Task 9.3 Execute the current spec after revision or replanning.

## 2026-10-19: Task 9.3 Execute the current spec after revision or replanning
- Status: done
- Plan check: off
- What changed: POST /run recompiles recipe.jsonl from the current spec.json before job prep/reservation (compile node writes only when bytes differ); POST /recipe refuses 409 wrong_stage while an agent job for the build is still registered. Tests: real revision then run (local engine input, agent job download), replan then run, refresh failure (uncompilable, invalid JSON) in both modes, unreleased-job guard, no-op determinism.
- Checks: `uv run pytest tests/test_execute.py tests/test_agent_server.py tests/test_revise.py` PASS (75; 8 new/changed fail on old src); `uv run pytest` PASS (370, 4 deselected). Reviewer: no findings.
- Decisions: refresh runs synchronously between run's checks and its reservation (no await, so atomic); missing spec stays 409 wrong_stage, invalid/uncompilable spec 422 invalid_recipe; run still needs a prior compile (409 if no recipe.jsonl). Guard reads agent_jobs.running because harness.run drops active_builds before the request releases the job. Edited tests/test_agent_client.py (outside Files): its fixture lacked spec.json. test_revise exposes seed_revision/revise_through_api for reuse. AGENTS.md gotcha added. No new dependencies.
- Tried and failed: none.
- Gotchas: test_timeout_and_late_agent_then_retry (0.12 s grace) failed once under load on old src; passed 3/3 reruns.
- Left open: none.
- Next: Task 9.4 Align sort validation, prototype SQL and recipe order.

## 2026-10-19: Task 9.4 Align sort validation, prototype SQL and recipe order
- Status: done
- Plan check: off
- What changed: typed `Sort{field, order: asc|desc}` (extra forbidden) replaces `sort: dict`; validator reads `sort.field`; renderer orders by `sort.order` (was reading a nonexistent `direction`, so explicit asc rendered desc); compiler emits `sort.model_dump()`. POST /recipe now maps a model-invalid spec.json to 422 invalid_recipe. Tests: valid/malformed sort matrix, provider schema shape, asc/desc SQL+recipe match on golden bar/table/time_series, absent-sort defaults, API publishes nothing on malformed/legacy sort.
- Checks: `uv run pytest tests/test_spec_validate.py tests/test_render.py tests/test_recipe_contract.py` PASS (81, 2 deselected); `uv run pytest` PASS (409, 4 deselected). Golden recipe bytes unchanged. Reviewer: one P2, no P0/P1.
- Decisions: `order` required (contract requires it); absent sort keeps time_series date ASC, others m0 DESC. Renderer keeps a defensive order check for model_construct'ed values. Edited src/dss/api/run.py (outside Files): read_spec moved inside /recipe's try (RunError re-raised), else invalid spec surfaced as invalid_source. Legacy spec.json with `direction` now fails validation (intended). No new dependencies.
- Tried and failed: none.
- Gotchas: none.
- Left open: P2 revise LLM context/prompt never shows the Sort shape, so a sort comment may guess `direction` and fail validation - src/dss/harness/context.py, skills/prompts. Live check not run: spec provider schema now has `anyOf[$ref Sort, null]`; confirm with `uv run pytest -m live tests/live/test_backend_flow.py`.
- Next: Task 9.5 Package nested image assets for plain-name agent jobs.

## 2026-10-19: Task 9.5 Package nested image assets for plain-name agent jobs
- Status: done
- Plan check: off
- What changed: `jobs.package(folder)` maps every recipe `path` to a plain transport name and builds a private recipe copy (bytes, snapshotted at prepare) with only renamed paths rewritten; `Job.inputs` holds name -> source Path or the recipe bytes; `Job.files == list(inputs)`. Download endpoint serves from `Job.inputs` after the unchanged `safe_file` guard. Tests: nested/same-basename/repeated/spaced images through the fake agent (server + real dss-agent client), 14 bad-path cases.
- Checks: `uv run pytest tests/test_agent_server.py tests/test_agent_client.py` PASS (66; 3 new fail on old src); `uv run pytest` PASS (425, 4 deselected). Reviewer: two P3, no P0-P2.
- Decisions: plain names travel unchanged; nested or case-colliding ones become `asset-<sha256(resolved version-relative posix path)[:16]>-<sanitized basename, last 64 chars>`; dedup by resolved source; casefold collision of a generated name -> 422. Bad path (absolute, `:`, NUL, empty/`.`/`..` part, either slash, resolves outside) -> 400 invalid_name; missing/non-file -> 422 invalid_recipe (both before reservation). Rewritten lines use the compiler's json.dumps options. Edited src/dss/api/agent.py (outside Files): download had to serve packaged bytes/source paths. Symlink-loop RuntimeError -> 422 (review P3). No new dependencies. AGENTS.md gotcha added.
- Tried and failed: none.
- Gotchas: Bash heredoc here mangled backslashes in Python code (NUL byte written into jobs.py); see Known gotchas.
- Left open: P3 case-collision renaming untested (Windows test FS ignores case) - src/dss/agent/jobs.py.
- Next: Task 9.6 Enforce live input budgets using authoritative token counts.

## 2026-10-19: Task 9.6 Enforce live input budgets using authoritative token counts
- Status: done
- Plan check: off
- What changed: context.py gains `fit_request` (one guard every LLM node calls last in before_model), `request_estimate`, `Context.refit` and shared `_drop`; llm.py gains `count_tokens`/`counting_contents`. Interview, plan, spec, revise, ux_audit, style_extract, research (both phases), consolidate and judge use it; old per-node chars/4 checks removed.
- Checks: Done-when offline command PASS (145); `uv run pytest -m live tests/live/test_backend_flow.py` PASS (100 s; plan counted 1884 vs est 1584, spec 6361 vs 5681; evidence `.blueprint/qa/final-audit/task-9.6/runs.json`); `uv run pytest` PASS (443, 4 deselected). Reviewer: one P2, no P0/P1.
- Decisions: interview.py edited outside Files (real LLM node with a budget). Counter: injectable async `model.count_request_tokens(llm_request)`; ADK Gemini -> `aio.models.count_tokens` on contents with instruction/schema/tools folded first; other models -> None (offline estimate). Full BUDGETS apply to the counted request (RESERVES only shape assembly). Over budget: drop in assembly order scaled by count/estimate, recount, MAX_COUNTS=4 counts; refuse `llm_unavailable` when still over, nothing droppable or cap hit; count errors sanitized (`from None`). ADK's text around the provider instruction (identity line) kept. Span: sections/dropped (estimates), input_tokens_estimate, request_tokens (None offline), count_calls. IMAGE_TOKENS=1500 moved to context.py. Live evidence moved to task-9.6. No dependencies added; gotcha added to AGENTS.md.
- Tried and failed: refusal test with a fixed counter expected all drops; ratio scaling drops gradually, so it hits the count cap instead (test split in two).
- Gotchas: none beyond AGENTS.md.
- Left open: P2 folded count is ~5% under billed prompt_token_count (8245 vs 8695); live test does not compare them; no safety margin - src/dss/harness/llm.py.
- Next: Task 9.7 Bound retry attempts by the remaining 60-second deadline.

## 2026-10-19: Change reference images and capability verification (backend)
- Status: planned; scope confirmed, final plan review pending.
- User decisions: both features required this hackathon; closest supported recreation of layout/chart choices/style using connected data, with explained substitutions.
- What changed: API 1.3, dashboard-intent 1.0 and isolated shared fixtures; program/part PRDs, architecture/essentials and plans. Seven M tasks: backend 11.1-11.5, frontend 10.1, release 3.3. Existing task markers preserved. No product code changed in this planning session.
- Audit: five original gaps and five delta integration findings addressed; focused recheck found no remaining P1 contradictions, then requested task split (applied as 11.3-11.5). Full report: program-root docs/reference-capability-audit.md. Draft remains pending user review per architect skill.
- Decisions: dated product/app/data evidence; unknowns block; explicit durable substitutions; private replaceable reference sets per version; pending-comment recovery; distinct candidate views preserve old reports; required hosted acceptance redeploys tested source. No engine expansion or added dependency. New fixture folder avoids breaking legacy exhaustive API fixture inventories. Frontend full conventions/UI details moved into implementation-notes.md/reference-ui.md, essentials summarize.
- Checks: root check_contracts.py 9/9 PASS; frontend npm test -- contract 31/31 PASS. Planning lint/stamp run; final counts recorded in scope audit. No new behavior claimed tested; its acceptance commands belong to builders.
- Left open: seven sessions of M work may conflict with deadline; both remain required until user explicitly changes scope. Existing unrelated dirty source/deck files and historical progress entries preserved; no commit while draft review pending.
- Next: complete existing in-progress backend 9.7 and existing 10.1, then backend 11.1-11.5; frontend 10.1; release 3.3. Existing release infrastructure may proceed independently.

## 2026-10-20: Task 9.7 Bound retry attempts by the remaining 60-second deadline
- Status: done
- Plan check: off
- What changed: src/dss/agent/client.py: `call` sets one deadline at the first failure; every retry goes through new `attempt` (own daemon thread, refuses to start at/after the deadline, per-phase timeouts capped at the remainder, closes the client and raises AgentExit at the deadline). Injectable `Agent.clock`. Tests: fake-clock retry tests and a real trickling-header server test.
- Checks: `uv run pytest tests/test_agent_client.py` PASS (17); `uv run pytest` PASS (447, 4 deselected); `git diff --check` PASS. Mutation: with the HEAD client the stall test hung >90 s (killed). Reviewer: no P0/P1; two P3s (stall-test timestamp race, unbounded hang on regression) fixed.
- Decisions: first attempt stays inline with the 40 s timeout (long poll >35 s). A retried long poll probes with `wait=0` so a healthy 25 s poll can't overrun the remainder. Waits in <=0.5 s slices (Ctrl+C, stop). At expiry the shared client is closed (agent exits anyway); the abandoned worker ends on its capped timeouts or socket close. Heartbeat (retry=False) unchanged. No dependencies added.
- Tried and failed: none.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: Task 10.1 Live token usage on the event stream.

## 2026-10-20: Change synthetic data and audit of phases 10-12 (backend)
- Status: done
- What changed: user asked to continue the required sequence; deadline moved by the user to about 3 days from 2026-10-20 (program.md still says 01:05, to update at the root). Logged the synthetic-data addition (Phase 12, API 1.4, synthetic-data.md 1.0, dashboard-intent 1.1), which had no entry. Essentials regenerated (were stale), header encoding fixed, PRD scope cell filled.
- Affects: 10.1 (5 more node files); 11.3 split into 11.3 assessment + 11.4 decisions/pending batches; old 11.4 -> 11.5; old 11.5 split into 11.6 interview/plan gate, 11.7 comments/revise gate, 11.8 recipe/run/versions + live; 12.2 split into 12.2 API/typed intake, 12.3 proposal, 12.4 manifests/reconciliation, 12.5 label + live.
- Change request (program root): (a) cross-part gates now point at old IDs: frontend 10.1 `Needs: backend 11.5` should become 11.8; frontend 11.1 (after backend 12.2 in program.md) should become 12.3 (API complete) or 12.5; release 3.3 and program.md's required-sequence paragraph list the new IDs; (b) simplify synthetic-data.md manifests/startup reconciliation to the generation table plus an immediate backup after reservation and registration (accepted finding 4); task 12.4 stops if this lands first; (c) record the new deadline in program.md.
- Next: Task 10.1 Live token usage on the event stream.

## 2026-10-20: Audit
- Delta audit (blueprint-reviewer, opus/high) of phases 10-12 and their architecture/PRD/essentials sections. 11 findings, all accepted and applied: P1 10.1 misses nodes that drop usage_metadata (verified in spec/revise/style_extract/ux_audit/research); P1 11.3/11.5/12.2 too big (split); P1 11.1 evidence unreadable from this part (now contracts + schema-derived coverage); P2 manifests heavy (change request, task isolated as 12.4); P2 extraction as second run (now a node in the action's trace); P2 11.2 tested staleness before 11.3 (moved); P2 Files gaps (chat.py, background.py, models.py, patch.py); P2 header-first image checks + APNG; P2 explicit CSV null marker + live case; P3 graph/data model/version citations; P3 12.1 contract fixtures and CLI input.
- Left open: plan has 40 tasks (lint warning; user kept all scope); 12.2 Spec prints 8.5k chars (contract section is the source).

## 2026-10-20: Change cross-part gates, synthetic durability and deadline (program root)
- Status: done
- What changed: contracts/synthetic-data.md 1.1 (generation table plus immediate best-effort DB backups after reservation and after registration; startup fails in-flight jobs `generation_interrupted`, cleans only their own prefix/table, sets retry_ready; idempotent replay kept; no manifests or reconciliation; HTTP shapes unchanged). architecture.md#Synthetic data and Data model (bq_table in synthetic_generations) plus a decision-log row; essentials contract row 1.1 (check `uv run pytest tests -k synthetic`); stamp. PRD deadline 2026-10-23 01:05 MPST.
- Affects: 12.4 rewritten as "Immediate backups and interrupted-job recovery", Size M -> S, its stop-`If:` removed. Gates elsewhere now name 11.8, 12.3, 12.4, 12.5.
- Change requests settled (entry "2026-10-20: Change synthetic data and audit of phases 10-12"): (a) planned: frontend 10.1 needs backend 11.8, frontend 11.1 needs backend 12.3 (user choice; backend prototype label checked in release 3.3 if 12.5 is later), release 3.3 needs backend 11.8, 12.4, 12.5 and frontend 11.1, program.md sequence updated; (b) planned: accepted best-effort (user choice), task 12.4; (c) planned: deadline 2026-10-23 01:05 MPST confirmed by the user, in program.md.
- Checks: `lint` backend 0 errors (2 warnings: 40 tasks; 12.2 Spec size); `program` 0 problems.
- Next: Task 10.1 Live token usage on the event stream.

## 2026-10-20: Task 10.1 Live token usage on the event stream
- Status: done
- Plan check: off
- What changed: graph.py emits `run.usage` (running trace totals) after each non-partial model response with usage, build runs only; spec/revise/style_extract/ux_audit/research after_model callbacks now pass `usage_metadata` through. New tests/test_usage_events.py; tests/test_skeleton.py hello event list now includes run.usage.
- Checks: `uv run pytest tests/test_usage_events.py` PASS (7); Test (all) `uv run pytest` PASS before final test tweak (453 + skeleton fix, rerun skeleton+usage 14 PASS). Reviewer: no P0/P1.
- Decisions: partial (streamed chunk) events are skipped, so a streamed reply counts once. test_skeleton.py edited outside Files (hello is a model call). Consolidate has its own Workflow with no build stream, untouched.
- Tried and failed: none
- Gotchas: none beyond AGENTS.md.
- Left open: P2 consolidate/eval after_model drop usage_metadata, so their traces read 0 (plan's "already counts usage" is wrong) - src/dss/harness/nodes/consolidate.py:257, src/dss/ops/eval.py:66; P3 tokens of model calls returning invalid output are not counted - src/dss/harness/graph.py:193.
- Next: Task 11.1 Evidence-backed capability registry and deterministic checks.

## 2026-10-20: Task 11.1 Evidence-backed capability registry and deterministic checks
- Status: done
- Plan check: off
- What changed: new src/dss/spec/capabilities.py (Pydantic Registry, evidence rules, Checker), knowledge/datastudio/capabilities.json (v1.0, 48 records), tests/test_capabilities.py; product-limits.md gains dated official sources and a registry section; datastudio index/log updated.
- Checks: `uv run pytest tests/test_capabilities.py` PASS (32); Test (all) `uv run pytest` PASS (486, 4 deselected). Reviewer: no P0/P1; three P2 fixed (raw-dict shape keys, null option values, inherited data prerequisites), two P3 fixed.
- Decisions: record = id, kind, label, recipe locators (e.g. `add_chart.options.geo_map.geo_type`), component_type, requires, values/value_type, separate `native_product` and `app` layers {status supported|unsupported|unknown, evidence, verified, limits, note}, `data` prerequisites {name, types}. Evidence: product = official docs URLs only; app supported must cite ../contracts/recipe.md, recipe.schema.json or fixtures; app exclusions may cite src/, knowledge/, tests/. Loader checks evidence format only (contracts may not ship in Cloud Run); the test checks existence. Classification order: product unsupported -> unsupported_product; DSS_ALLOWED_TYPES -> unsupported_app; app not supported -> unsupported_app; product not supported -> unknown; then requires, value, data (needs_data; unbound field with candidates -> needs_clarification). Interface for 11.3+: `Checker(registry, allowed=None)`, `.need/.requirement/.component/.assess`, `Need{capability,value,fields}`, `Requirement{id,needs}`, `Checker.digest()` (registry + allowlist). add_text args and set_style keys other than colors are app-unsupported (compiler never emits them). Plumbing ops open/save/get_link unclassified. Budget: 40 req/24 components best of 5 well under 100ms. No new dependencies. AGENTS.md: added the knowledge-index .json gotcha.
- Tried and failed: none.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: Task 11.2 Versioned references and structured image interpretation.

## 2026-10-20: Task 11.2 Versioned references and structured image interpretation
- Status: done
- Plan check: off
- What changed: GET/POST/DELETE `reference-images` and legacy `style-images` (builds.py, streamed multipart); new spec/references.py (image checks, models, grid mapping, atomic storage), nodes/reference_extract.py (+ prompt, skill); style_extract.py now only StyleProfile/provider_schema/style_doc (old branch removed); context.py `reference_context`, budget 12k, recreate reference.md in spec context; graph routes reference_extract/reference_delete.
- Checks: `uv run pytest tests/test_references.py tests/test_api_contract.py` PASS (45); live `uv run pytest -m live tests/live/test_references.py` PASS (gemini-3.8-flash, 3011 counted, 1075 out, 7 accurate boxes; evidence .blueprint/qa/final-audit/task-11.2/); `uv run pytest` PASS (528, 5 deselected). Reviewer: no P0-P2; 2 of 4 P3 fixed.
- Decisions: Interfaces for 11.3+: version folder `references.json` = {id ref_*, mode, instructions, images[{id img_*, name, file reference_<img id>.png|jpg, mime_type, width, height, bytes, sha256}], summary (code-made), style (StyleProfile), interpretation {mode, aspect_ratio (header w/h), palette/type/spacing_notes, items[{id o1.., kind, label, box 0..1, chart_candidate (snake token, may be non-catalog), metric_label, unit, aggregation, date_grain, confidence}]}, created_at}; `references.load/public/grid_cell/structural_changes`. Model boxes in thousandths, code normalizes; style mode nulls chart/data fields; >24 (element_count or items) -> run error asking to crop. 413 uses existing `invalid_source`; decode crash 503 invalid_source. Checks order: stage, streamed bytes, count/mode/instructions (no secrets), signature/ext/MIME, header pixels, PNG CRC/acTL/IEND or JPEG SOF/EOI, stage, Chromium decode (sides may swap: EXIF), re-check, reserve. Commit point references.json; rollback restores docs/bytes. style.md marked `reference_set`; DELETE keeps an unmarked style.md. DELETE = harness code action (one trace). Versions copy via existing folder copy. max_llm_calls 1, max_output_tokens 4096. Outside Files: test_audit_style.py, test_usage_events.py (alias now reference_extract; oversize 413), tests/live/__init__.py, tests/data/reference.jpg. No new dependencies; AGENTS.md gotcha added.
- Tried and failed: hand-embedded base64 JPEG corrupted in transcription; replaced by Chromium-generated fixture file.
- Gotchas: none beyond AGENTS.md.
- Left open: P3 over-budget vision request reports llm_unavailable ("check Settings") - src/dss/harness/context.py:183; P3 live check stops at spec context, no generated spec compared with placement - tests/live/test_references.py; prompts/v1/style_extract.md now unused.
- Next: Task 11.3 Requirement ledger, capability check and assessment API.

## 2026-10-20: Task 11.3 Requirement ledger, capability check and assessment API
- Status: done
- Plan check: off
- What changed: requirement ledger, capability_check Workflow, feasibility APIs, invalidation and protected contexts.
- Checks: `uv run pytest tests/test_feasibility.py tests/test_api_contract.py` PASS (51); Test (all) `uv run pytest` PASS (575, 5 live deselected, 2 warnings). Bounded recomputation test passes <=100ms for 40 requirements/24 components. Read-only review: no remaining findings.
- Decisions: requirements.json stores requirements (code IDs, original message/comment/image provenance, needs, mappings, component_ids), processed_sources hashes, decisions placeholder, verification, assessment and sticky prototype_stale/invalidated flags. GET compares input digests without writes/model calls; stale IDs become null. Check merges new sources, preserves prior intent, retires replaced reference requirements and recomputes. Extraction uses one counted 12k-input/4k-output call, no repairs, 40 requirements/20 issues; scope overflow blocks. Explicit assignment clauses and source-defined aggregation/unit/grain prevent inferred mappings. Save rolls back docs/ledger together. Outside Files: nodes/revise.py passes folder for mandatory ledger context. AGENTS records physical schema/projection gotcha. No dependencies added.
- Tried and failed: test assumed a native exclusion; review exposed incidental field mentions, stale schema fallback and exact-cap truncation; corrected with regressions.
- Gotchas: recorded in AGENTS.md.
- Left open: none.
- Next: Task 11.4 Explicit decisions and pending comment batches.

## 2026-10-20: Task 11.4 Explicit decisions and pending comment batches
- Status: done
- Plan check: off
- What changed: atomic decision API, validated alternatives and durable choices; ordered pending-batch persistence, replacement, selective abandonment and reapply guards.
- Checks: `uv run pytest tests/test_feasibility.py tests/test_api_contract.py` PASS (71); Test (all) `uv run pytest` PASS (595, 5 live deselected, 2 warnings); `git diff --check` PASS. Decision-bearing 40-requirement/24-component recomputation passes <100ms. Final read-only review: no findings.
- Decisions: choices bind requirement meaning/slot, selected needs/evidence/prerequisites, baseline bindings and applied flag. `revalidate_decisions` seals fulfilled bindings before refreshed assessment publication. `stage_comments` creates ordered `batch_id:index` sources; `abandon_pending` retires only that batch. Successful reapply and comment-route wiring remain 11.7; avoid duplicate extraction from episodic comments. Outside Files: capability_check.py propagates only `artifact_stale` and seals choices. AGENTS.md adds the pending-staleness gotcha. No dependencies added.
- Tried and failed: review exposed old-prototype acceptance deadlock, missing legacy data origin and batch staleness leaking into the general flag; fixed with regressions.
- Gotchas: recorded in AGENTS.md.
- Left open: none.
- Next: Task 11.5 Stage candidate views and recover failed publication.

## 2026-10-20: Task 11.5 Stage candidate views and recover failed publication
- Status: done
- Plan check: off
- What changed: run-specific CREATE VIEW candidates; staged docs/spec/render bundle; serialized publication and HTTP reads; durable rollback and startup reconciliation.
- Checks: `uv run pytest tests/test_publication.py tests/test_view_sql.py tests/test_plan.py tests/test_render.py` PASS (83, 2 live deselected); Test (all) `uv run pytest` PASS (626, 5 live deselected, 2 existing warnings); `git diff --check` PASS. Final read-only review: no findings.
- Decisions: `payload['_publication']` carries Candidate; `.folder` supplies private spec/render inputs. Volume `.publications/r_*.json` records precede creation/promotion and commit; retained committed/restored records reconcile stale cloud SQLite backups. Build read locks span file streaming. Deterministic BigQuery job IDs retain ownership until CREATE is terminal. Outside Files: graph.py wires cleanup/cancellation and preserves prior stage. AGENTS.md records cloud-backup and QueryJob timeout traps. No dependencies added.
- Tried and failed: review found SQLite-only durability, late CREATE and staging-registration gaps; fixed with regressions. Interim metadata-variable shadowing and invalid fixture ID corrected.
- Gotchas: recorded in AGENTS.md.
- Left open: none.
- Next: Task 11.6 Gate interview and plan; use Candidate staging for preflight-approved plans.

## 2026-10-20: Task 11.6 Gate interview and plan
- Status: done
- Plan check: off
- What changed: same-Workflow intent extraction; interview/readiness and direct-plan gates; candidate requirement/option coverage and atomic proof publication.
- Checks: `uv run pytest tests/test_feasibility.py tests/test_plan.py tests/test_interview.py` PASS (113); Test (all) `uv run pytest` PASS (649, 5 live deselected, 2 existing warnings); `git diff --check` PASS. Final read-only review: no findings. Coverage benchmark: 40 requirements/24 components, 7.21 ms.
- Decisions: reuse capability_check with `_intent_only`/`_defer_assessment`; unchanged preflight is read-only. `coverage_errors(..., bindings={})` checks original intent and compiled ops; verification stores `fulfilled_by`. Grain requires view truncation; units remain ledger meaning. Clarifications preserve provenance/legacy hashes; audience matches whole-source role grammar. Outside Files: capability_check.py reuses extraction; validate.py preserves repairs; render.py gates commit; publication.py publishes requirements.json; test_context.py handles extraction. AGENTS.md records rollback ordering. No dependencies.
- Tried and failed: review caught mixed-intent deletion, late gate/error handling and audience blocking; fixed with regressions. Fixture and context fakes corrected.
- Gotchas: recorded in AGENTS.md.
- Left open: none.
- Next: Task 11.7 Gate comments and revise; reuse extraction and coverage without increasing revise repairs.

## 2026-10-20: Task 11.7 Gate comments and revise
- Status: done
- Plan check: off
- What changed: same-Workflow comment assessment, persisted whole-batch refusal, validated reapply, requirement/registry checks and atomic revision/proof publication. Empty patches require fulfillment; unsupported partial batches fail.
- Checks: `uv run pytest tests/test_feasibility.py tests/test_revise.py -q --tb=short` PASS (114); Test (all) `uv run pytest --tb=short` PASS (664, 5 live deselected, 2 existing warnings); `git diff --check -- .` PASS. Final read-only review: no findings.
- Decisions: `comment_batch` history is excluded from intent extraction; batch sources own provenance. Typed `properties` prove exact item values; slot-level `superseded` chains preserve original requests and last-wins assignments, with abandon restoring predecessors. `scope_batch_id` owns removable scope failures. Publication includes requirements/feasibility and checks input/registry freshness. Outside Files: capability_check.py reuses bounded extraction; test_context.py/test_usage_events.py adapt fakes. AGENTS.md records history/chain gotchas. No dependencies.
- Tried and failed: corrected fake token-count forwarding and legacy fingerprint fixture; review exposed unproven decoration edits and overwritten supersession chains, fixed with regressions.
- Gotchas: recorded in AGENTS.md.
- Left open: none.
- Next: Task 11.8 Gate recipe, run and new versions; live flow. Reuse committed proof and preserve pending/reference staleness at every run gate.

## 2026-10-20: Task 11.8 Gate recipe, run and new versions; live flow
- Status: partial
- Plan check: off
- What changed: attempted execution gates, unchecked version copies, screenshot compiler guard, streaming-extraction fix and explicit fixture assessments. Set aside recoverably with `restore 11.8` after repeated live failure.
- Checks: before restore, `uv run pytest tests/test_feasibility.py tests/test_api_contract.py -q --tb=short` PASS (96); `uv run pytest --tb=short -q` PASS (682, 7 live deselected; newest case also covered by focused check). Live flow FAIL twice: initially 3 failed; finally 1 passed, 2 failed. GPS refusal passed. `git diff --check -- .` PASS. Review not reached.
- Decisions: recover implementation using `git stash apply 045be7caaaf2bd6df09059f84ae27021a5916c80`. No dependencies. AGENTS.md records streaming and assignment traps.
- Tried and failed: original live interview fails during extraction after counting, with zero generation tokens and generic `llm_unavailable`; ignoring partial responses fixed GPS but not that failure. Image clarification remains blocked: sentence-start assignment grammar rejects the audience-prefixed definition.
- Gotchas: sanitized traces/ledgers and live logs remain in `.blueprint/qa/task-11.8/failures/` and `.blueprint/task-11.8-live*.log`.
- Left open: both live failures; task unreviewed.
- Next: resume 11.8 by recovering the stash; isolate the original interview's provider/streaming failure with a minimal diagnostic, repair clarification recognition, rerun required checks, then review.

## 2026-10-20: Task 11.8 Gate recipe, run and new versions; live flow
- Status: blocked
- Plan check: off
- What changed: gates/version copies/screenshot protection; streaming, thinking/truncation, audience definitions, daily grain and prompt fixes. Saved recoverably.
- Checks: `uv run pytest tests/test_feasibility.py tests/test_api_contract.py -q --tb=short` PASS (105); Test (all) `uv run pytest --tb=short -q` PASS (692, 7 deselected). Live: intermediate 2 passed/1 failed; final 1 passed/2 failed. Review: no findings; diff check PASS.
- Decisions: recover `git stash apply 1cc46e15b6588fae711b32769e724be38c9e7045`. Extraction/prompt/fixture edits outside Files enable live flow. No dependencies. AGENTS.md records traps.
- Tried and failed: extraction fixed; image prototype passed once. Unsupported-option prompt fix unproven: final plan/spec calls fail llm_unavailable after counting.
- Gotchas: logs `.blueprint/task-11.8-*.log`; evidence `.blueprint/qa/task-11.8/failures-resume/`; diagnostics `.blueprint/`.
- Left open: required live flow.
- Blocked because: (d) second-session repeated failures; unidentified provider cause.
- Question: how should planner/provider compatibility be restored?
- Options: A isolate minimal counted request / B verify another planner / Recommend: A.
- Next: architect recovers stash, isolates SDK/callback failure, authorizes fix, reruns checks.

## 2026-10-20: Change conventions 1.2 (program)
- What changed: contracts/conventions.md 1.1 -> 1.2 renames the Cloud Run service `dss` -> `dss-frontend` (keeps the submitted URL); this part's essentials Contracts row now says 1.2. Nothing this part reads or provides changed; no task affected.

## 2026-10-20: Change Gemini timeout unblocks 11.8; retry task 11.9
- What changed: architect diagnosis of 11.8's `llm_unavailable` (`.blueprint/task-11.8-architect-*.log`): every remaining live failure is the `gemini-4-argon` spec call returning `504 DEADLINE_EXCEEDED` at ~29.6 s, caused by `llm.py` `llm_for`'s fixed `HttpOptions(timeout=30000)`, which google-genai sends to Google as `X-Server-Timeout`. Changing the timeout on each request didn't help: the client's 30 s still applied. Plan, extraction and the prompt fixes all succeed. Also found: architecture promised one retry on 429/5xx, but none was built. Edited architecture.md (External APIs row, decision log), essentials (Conventions), plan.md (two If: lines on 11.8; new task 11.9).
- Why: user chose planner 120 s / worker 30 s, and a separate retry task with no retry on 504.
- Tasks affected: 11.8 reopened (may edit llm.py; the stash@{0} attempt is already in the working tree); new 11.9 (S), depends on 11.8.
- Change requests: none outstanding.

## 2026-10-20: Task 11.8 Gate recipe, run and new versions; live flow
- Status: done
- Plan check: off
- What changed: built on the stash@{0} attempt (execution gate in recipe/run, `copy_version`, extraction/prompt fixes). llm.py sets the client timeout per node (plan/spec 120 s, others 30 s). Review P1 fix: reference screenshots are refused as image components and logo decorations in validate_spec, compiler and prototype image_url (shared `models.reference_image`/`image_paths`).
- Checks: `uv run pytest tests/test_feasibility.py tests/test_api_contract.py` PASS (112); `uv run pytest -m live tests/live/test_backend_flow.py` PASS (3); Test (all) `uv run pytest` PASS (711, 7 deselected); tests/test_llm_timeouts.py PASS (12); `git diff --check` PASS. Reviewer: 1 P1 (fixed), 1 P2, 2 P3 (fixed).
- Decisions: timeout chosen by node (`PLANNER_NODES`), so a planner falling back to the worker model keeps 120 s. Screenshot rule = basename starts with `reference_` (casefold, either separator). Audience prefix allows one qualifier word. Outside Files: llm.py (plan If:), models.py, validate.py, prototype.py (screenshot guard), new tests/test_llm_timeouts.py, plus the earlier attempts' prompts/capability_check.py/fakes/tests. AGENTS.md gotchas updated. No dependencies.
- Tried and failed: two earlier sessions (see above); the 30 s client deadline was the cause.
- Gotchas: live logs `.blueprint/task-11.8-live-timeout.log`, `-live-final2.log`.
- Left open: P2 execution-gate fulfillment block not durable (check re-reports ready; no test hits `coverage_errors` branch) - src/dss/spec/requirements.py:658. P3 Windows 8.3 short names could alias a reference file past the basename rule - src/dss/spec/models.py.
- Next: Task 11.9 One model-call retry on transient errors.

## 2026-10-20: Task 11.9 One model-call retry on transient errors
- Status: done
- Plan check: off
- What changed: llm.py adds `RetryingGemini(Gemini)` (returned by `llm_for`): a call failing with APIError 429/500/503 before any response retries once after `RETRY_DELAY_S` (1 s); 504, other 4xx and a stream that already yielded a chunk never retry. graph.py sets the `retry_listener` ContextVar per run, so a retry adds a `{"node": "model_retry", "status": code}` span to that run's single trace. New tests/test_llm_retry.py fakes the provider at the router's genai client (real ADK Gemini path).
- Checks: `uv run pytest tests/test_llm_retry.py` PASS (with test_llm_timeouts: 30); Test (all) `uv run pytest` PASS (729, 7 deselected); `git diff --check` PASS. Reviewer: 1 P2 (open), 1 P3 (fixed: aclosing on inner generators, plus test).
- Decisions: retry at the model, not google-genai `HttpRetryOptions` (offline-testable, visible in the trace; ADK ignores `Gemini.retry_options` when `client=` is passed). Same LlmRequest resent (ADK preprocessing is idempotent). Only the status code is logged. "Both attempts counted in usage": trace tokens sum every reported usage; a failed attempt reports none. Injected fakes (`llm=`) are not wrapped. No dependencies; AGENTS.md unchanged.
- Tried and failed: none.
- Gotchas: none.
- Left open: P2 consolidate (background task inherits the execute run's listener) and eval judge retries are not recorded in their own traces - src/dss/harness/nodes/consolidate.py, src/dss/ops/eval.py.
- Next: Task 12.1 Parameterized deterministic CSV generator and CLI.

## 2026-10-20: Task 12.1 Parameterized deterministic CSV generator and CLI
- Status: done
- Plan check: off
- What changed: new src/dss/data/synthetic.py: strict Pydantic GenerationSpec (8 generator kinds), `parse_spec`, `canonical_json`, `generate_csv(spec, output_path) -> GenerationResult`, `SyntheticError(field, message)` and CLI `python -m dss.data.synthetic` (exit 2 on SyntheticError, 1 on OSError, JSON result on stdout). tests/test_synthetic.py (115) + tests/data/synthetic-spec.json (14 columns, every kind).
- Checks: `uv run pytest tests/test_synthetic.py` PASS (115); CLI golden PASS (sha256 b70c89f0..., 1529 bytes); 100,000x10: 8.2 s under tracemalloc (0.9 s without), peak 0.2 MiB traced; Test (all) `uv run pytest` PASS (844, 7 deselected). Reviewer: 1 P2 fixed (product corner bounds raised decimal.InvalidOperation: now localcontext(prec=60)), 3 P3 partly fixed (deep-nesting/lone-surrogate/model-size errors, second-operand null and range-end tests).
- Decisions: GENERATOR_VERSION `dss-synthetic/1`; per-column `random.Random` seeded by sha256(version, seed, column index, name, stream) with own getrandbits rejection sampling (no stdlib randrange internals). Probabilities compare 53 random bits. Products: integer ticks, round half away from zero. Empty strings rejected (empty = null); number values <=6 decimals and distinct by numeric value; product fields must differ. generate_csv accepts JSON text/bytes, mapping or model, refuses an existing output (also for the function), writes a `.partial` temp beside it, publishes via os.link (no-replace). Single-column null rows are written `""` by csv.writer.
- Tried and failed: none.
- Gotchas: added the `""` single-column null row to Known gotchas (12.2 loader).
- Left open: P3 duplicate-JSON-key error names the bare key, not its path; P3 no-hard-link fallback uses lexists+os.replace (race) and leaves an empty created parent dir on failure - src/dss/data/synthetic.py.
- Next: Task 12.2 Synthetic generation API, typed intake and download.

## 2026-10-20: Change api.md 1.5 and example fixtures (program root)
- What changed: contracts/api.md 1.4 -> 1.5, consistency only (no shape or route change; a 1.4 implementation conforms): cross-refs to dashboard-intent/synthetic-data 1.1, the `node` list adds reference_extract, reference_delete, capability_check, synthetic_schema, synthetic_generate. New example fixtures dashboard-intent/feasibility.{alternatives,pending,stale}.json and synthetic-data/{dataset,job.succeeded}.json (dataset sha256/bytes from `dss.data.synthetic` on request.json's spec, generator `dss-synthetic/1`). Essentials Contracts row says api 1.5.
- Affects: no task; existing contract tests load fixtures by name, so the new files change nothing they check.

## 2026-10-20: Task 12.2 Synthetic generation API, typed intake and download
- Status: done
- Plan check: off
- What changed: new api/synthetic_data.py (POST /synthetic-data, GET datasets, jobs, jobs/{key}, {source_id}/csv) and harness/nodes/synthetic_generate.py (run node `synthetic_generate`: generate -> store -> typed BQ load -> exact row count -> register). db.py adds `synthetic_generations`; bigquery.py adds SYNTHETIC_TYPES, load_typed_csv, delete_loaded_table; intake.py exposes register(); graph.py/main.py wiring. Tests: test_synthetic_api.py (11), contract test, tests/live/test_synthetic_flow.py.
- Checks: `uv run pytest tests/test_synthetic_api.py tests/test_api_contract.py` PASS (18); `uv run pytest -m live tests/live/test_synthetic_flow.py` PASS (1, real BigQuery, 45 s); Test (all) `uv run pytest` PASS (856, 8 deselected). Reviewer: 1 P2 fixed, 1 of 2 P3 fixed.
- Decisions: table PK (build_id, generation_key); extra columns spec_json (accepted spec as sent), assumptions_json, generator_version, sha256, bytes. Request hash = sha256(proposal_id + canonical spec). Types integer/number/string/boolean/date -> INTEGER/NUMERIC/STRING/BOOLEAN/DATE; load job id `dss_load_`+sha256(table), null_marker "", WRITE_EMPTY, max_bad_records 0. Table `src_<build>_synthetic_<source hex>`. Non-null proposal_id -> 409 synthetic_proposal_stale until 12.3. Manual assumption text fixed in MANUAL_ASSUMPTIONS. Errors: synthetic_generation_failed / synthetic_load_failed; retry_ready only when own prefix and table cleanup succeeded (no BQ cleanup when no client was created); 413 code `request_too_large`; missing job/file `404 not_found`. Download re-verifies size+sha256. Hosted (K_SERVICE set): generate in temp, copy, verify checksum, metadata.json last. No immediate backup yet (12.4).
- Tried and failed: none.
- Gotchas: added shape() heterogeneous-list line; `""` null row now live-verified.
- Left open: P3 cleanup ignores delete_loaded_table's False (load job never observed): retry_ready may be true while a late load creates an orphan table - src/dss/harness/nodes/synthetic_generate.py.
- Next: Task 12.3 Screenshot schema proposal (or 12.4, also unblocked).

## 2026-10-20: Task 12.3 Screenshot schema proposal
- Status: done
- Plan check: off
- What changed: proposal GET/POST routes, synthetic_schema Workflow branch, bounded observation-only context, prompt/skill, and current-proposal validation during generation. Added FakeLLM and shared-fixture contract coverage.
- Checks: `uv run pytest tests/test_synthetic_api.py tests/test_api_contract.py` PASS (29); Test (all) `uv run pytest` PASS (867, 8 live deselected, 3 dependency warnings). Read-only blueprint_reviewer: no findings. No live provider call required or run.
- Decisions: version folder `synthetic-proposal.json` stores Proposal; GET returns null after reference replacement/deletion/style mode. Model returns spec/assumptions; code adds proposal/reference IDs and validates with the generator compiler. Input uses existing reference interpretation only, counted budget 12k, output cap 6k, low thinking, one call/no repair. Supplied proposal must match the stored proposal and current recreate reference; replay still precedes freshness checks. Edited specs retain all original assumptions plus EDITED_NOTE; exact submitted spec persists in the generation row.
- Tried and failed: PowerShell rejected an inline Python edit command; applied the graph edit with apply_patch instead. No implementation/check failures.
- Gotchas: none.
- Left open: none.
- Next: Task 12.4 Immediate backups and interrupted-job recovery.

## 2026-10-20: Task 12.4 Immediate backups and interrupted-job recovery
- Status: done
- Plan check: off
- What changed: reservation/registration backups, startup interruption cleanup and checksum validation, durable failure/readiness, cancellation handling and bounded shutdown. Added tests/test_synthetic_recovery.py.
- Checks: `uv run pytest tests/test_synthetic_recovery.py` PASS (21); recovery plus cloud tests PASS (43); Test (all) `uv run pytest` PASS (888, 8 live deselected, 3 dependency warnings). Read-only blueprint_reviewer: no remaining findings. `git diff --check -- .` PASS.
- Decisions: reuse the existing backup routine/lock with a 3-second immediate budget; shutdown shares its remaining deadline. Reservation stores bq_location; recovery restores project/location. Extended bigquery.py outside Files because a missing load needs a same-job-ID SELECT 1 fence before retiring ownership; unresolved conflicts remain pending. Corrupt completed CSV/completion metadata stops startup. Failed cleanup retries on startup. Added the SQLite handle-closing gotcha to AGENTS.md.
- Tried and failed: initial fixtures assumed dataclass Config, incomplete completion payload and automatic SQLite handle closure; corrected. Review exposed missing-job and cancellation boundaries; fixed and covered.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: Task 12.5 Synthetic label through prototype and report; live flow.

## 2026-10-20: Task 12.5 Synthetic label through prototype and report; live flow
- Status: done
- Plan check: off
- What changed: source-authoritative sample-data footer across spec, prototype, background, recipe, revision and copied versions; screenshot-only live acceptance.
- Checks: `uv run pytest tests/test_synthetic_label.py tests/test_render.py` PASS (47); `uv run pytest -m live tests/live/test_synthetic_flow.py` PASS (2); Test (all) `uv run pytest` PASS (911, 9 live deselected, 3 dependency warnings). `git diff --check -- .` PASS. Read-only blueprint_reviewer: no findings. Visually inspected prototype and compared live background label pixels exactly; evidence `.blueprint/qa/task-12.5/`.
- Decisions: `datasource.synthetic` is code-owned; participation matches base source plus joins. Immutable `p1_synthetic_sample_data` gets a reserved 64px footer, fixed contrast/font and native recipe text. Legacy reads restore provenance without mutating feasibility inputs; revisions (including no-ops) and versions publish restored artifacts. Outside Files: api/prototype.py, api/run.py, harness/nodes/compile.py and render.py wire authoritative loads/recompilation. AGENTS.md records preview boolean limitation. No dependencies.
- Tried and failed: incomplete source fixtures; unsupported preview bold argument; live test import corrected. Initial live spec repair returned llm_unavailable; rerun passed. Background preview appeared blank; exact pixel comparison confirmed correct PNG.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: backend plan complete; final architect audit.

## 2026-10-20: Audit (final)
- Status: DEFECTS. Re-audit after the 2026-10-19 final audit and completed tasks 9.1–12.5.
  Eight repair tasks (13.1–13.8) appended; original task markers untouched. Full evidence and
  per-command task ledger: docs/audit-final-2026-10-20.md.
- What changed: plan.md adds color/recipe validation (P1), bounded Windows retry teardown,
  heading sizing, accepted chart-option rendering, version-publication recovery, huge-number
  validation, durable fulfillment refusal and conservative token enforcement. Architecture
  specifies their invariants; essentials regenerated; AGENTS gotchas sorted into conventions;
  PRD Later reconciles remaining optional limitations. Product source/tests and contracts unchanged.
- Checks: Test (all) `uv run pytest` FAIL: 910 passed, 1 failed, 9 live deselected, 500.63s.
  Stalled-retry timing: 2.031s vs 2.0s allowed; isolated rerun FAIL at 2.015s. All 37 distinct
  Done-when task pytest commands PASS, representing all 41 completed tasks (identical commands
  shared; original suites rerun too). Synthetic contract subset PASS: 182, 738 deselected.
  Combined live check: 8 passed/1 failed; reference invalid-observations failure passed its
  isolated rerun. Core, GPS refusal, explicit image mapping, synthetic typed intake/proposal/
  label and real Chromium checks passed. Fresh uvicorn health PASS in 3.22s, no reload.
- Live core-to-engine check: FAIL after successful real interview/plan/prototype. Generated
  palette colors lack #; compiler emits them, real engine dry-run exits 2 at line 6 with
  style.colors.items.pattern. No fixture spec substituted. Parent independently reproduced
  huge integers -> OverflowError/API 500, version failure -> stranded v2/retry 422, ignored
  horizontal/donut options, and fulfillment blocked -> check -> false ready/non-stale.
- Synthetic generator: CLI PASS, 20 rows/1,529 bytes, checksum b70c89f0…; 100,000x10 measured
  13.81s under tracemalloc, peak 0.2MiB traced, 6.3MiB output (30s/128MiB budgets pass).
- Review: independent blueprint_reviewer confirmed findings and repair plan; applied table
  rows_per_page coverage and version-recovery size M. Valid judge FakeLLM actually preserves
  5/2 usage through ADK, disproving earlier blanket zero-usage claim; SDK extra-retry suspicion
  also disproved. No built Non-goal/Decision contradiction found. All 17 dependency rows
  FOUND/dated; installed direct ranges satisfied. Backend-scoped metadata-only tracked/history
  scans found no .env or scanned credential/private-key pattern; not a whole-program audit.
- Visual/release check: viewed fresh core/image/synthetic screenshots at spec canvases; core
  heading clips, synthetic footer is visible. Documented startup PASS; real engine core flow
  and heading visual acceptance FAIL, so no integration acceptance. Original manual research/
  standalone agent demo and optional live consolidation/audit/judge checks not repeated; scope
  and earlier evidence limits are explicit in the audit report. No actual report creation claimed.
- Decisions: repair existing requirements rather than relax budgets, silently downgrade supported
  options or increase timing tolerance. 13.1 first (P1), then the other seven repairs. No new
  dependency or cross-part change. Durable task decisions now live in architecture conventions;
  remaining environment quirks stay in AGENTS. Scoped docs commit only; unrelated changes untouched.
- Mechanical: stamp PASS; lint 0 errors, 4 warnings (49 cumulative tasks, historical Spec sizes
  11.3/11.4/12.2). AGENTS/essentials size warnings resolved. Diff whitespace checked before commit.
- Left open: eight Phase 13 defects. Optional/deferred POC limits in PRD Later; no pending
  user scope decision or unverified dependency. Ignored QA evidence in
  .blueprint/qa/final-audit-2026-10-20/ and the live tests' documented evidence directories.
  Test-created BigQuery tables/views remain in the previously authorized demo project for
  diagnosis; root configuration and real user runtime were not edited.
- Next: builder task 13.1 (M, deep: provider schema/local validation/real recipe boundary),
  gpt-6.1-sol at high, in backend/. After Phase 13, rerun final audit; root integration follows
  backend ACCEPTED and the other parts' gates, not this DEFECTS verdict.

## 2026-10-20: Task 13.1 Keep generated theme colors and recipes contract-valid
- Status: done
- Plan check: off
- What changed: strict #RRGGBB Theme fields/palette, provider schema and prompt guidance; mutable specs revalidate locally. Compiler validates emitted headers/ops against recipe 1.0 before publication. Regression tests cover bounded repair, legacy rejection, artifact preservation and no engine/job side effects.
- Checks: `uv run pytest tests/test_spec_validate.py tests/test_spec_node.py tests/test_recipe_contract.py tests/test_api_contract.py -q` PASS (234); `uv run pytest -m live tests/live/test_backend_flow.py -q` PASS (3, 286.81s); Test (all) `uv run pytest` PASS (1068, 9 deselected, 424.65s); `git diff --check` PASS. Reviewer: no findings. Golden bytes unchanged.
- Decisions: cache shared-schema validators; compilation also revalidates Theme instances to catch mutations. Release integration must ship `contracts/recipe.schema.json` beside backend at runtime. No dependencies, contracts, engine or repair budgets changed.
- Tried and failed: new test setup initially used malformed prior JSON and omitted explicit datasource.synthetic; corrected fixtures and error-detail assertions.
- Gotchas: evidence/logs in `.blueprint/qa/task-13.1/` and `.blueprint/task-13.1-*.log`; isolated live core reached done (12 validated lines, real engine dry-run: 11 skipped, zero failed). Viewed prototype PNG; existing heading clipping belongs to 13.3.
- Left open: none in this task.
- Next: Task 13.2 Bound retry expiry cleanup on Windows (deep; gpt-6.1-sol at high).

## 2026-10-20: Task 13.2 Bound retry expiry cleanup on Windows
- Status: done
- Plan check: off
- What changed: agent engines enter a Windows Job Object before running. Expiry closes HTTP off-thread; process waits, readers, pipe closure and main-loop exit share a bounded allowance. Retry workers recheck expiry before sending.
- Checks: `uv run pytest tests/test_agent_client.py tests/test_execute.py -q` PASS (33); original stalled-server test PASS in five fresh Windows processes (1.531, 1.515, 1.500, 1.516, 1.500 s, each within the unchanged 2.0 s ceiling, client closed and engine/child stopped). Test (all) `uv run pytest` PASS (1075, 9 deselected, 466.62 s); `git diff --check` PASS. Independent reviewer: no findings.
- Decisions: 0.4 s total cleanup allowance within the existing 0.5 s tolerance. Job handles own descendants after wrapper exit. Controlled stalls cover HTTP close, process wait, pipe close and heartbeat join. Budgets, dependencies and contracts unchanged.
- Tried and failed: none.
- Gotchas: logs, five timing XML files and reviewed diff in `.blueprint/task-13.2-*`.
- Left open: none.
- Next: Task 13.3 Fit heading text in prototype and background (deep; gpt-6.1-sol at high).

## 2026-10-20: Change triage phase 13 to the severity bar
- What changed: Phase 13's open tasks graded against the architect's new severity bar (POC: only P0/P1 stay as tasks; fix budget 2, already spent by 13.1 and 13.2). Kept 13.3 (P1, borderline: `.item` 16px padding with overflow hidden clips every default 2-row title, and the clip is baked into the real report's background; the audit's POC checklist walk marked the visual heading FAIL). Removed unstarted 13.4, 13.5, 13.6, 13.7 and 13.8 (all P2: preview-only option drift, failure-only version recovery, a 500 on absurd synthetic input, false readiness with execution still refusing, near-limit token overshoot); each is one line in PRD `## Later` (source `change 2026-10-20`). Plan header notes the deferral.
- Why: retro 2026-10-20 found audits kept adding fix tasks; user picked 13.3 only (over the 2-task budget by one) and all P2s to Later.
- Tasks affected: 13.3 stays (already in progress); 13.4-13.8 removed; no [x] task touched.
- Change requests: none outstanding.

## 2026-10-20: Task 13.3 Fit heading text in prototype and background
- Status: done
- Plan check: off
- What changed: shared styles and cached Chromium measurements reject clipped headings; prototype/background use identical wrapping, fonts and padding. Prompts explain required heading space.
- Checks: `uv run pytest tests/test_render.py tests/test_spec_validate.py tests/test_synthetic_label.py` PASS (208); `uv run pytest -m live tests/live/test_backend_flow.py` PASS (3, retry); Test (all) `uv run pytest` PASS (1106, 9 deselected, 418.91s). Real 12-component render/background PASS (1.59s). Chromium bounds and identical background pixels checked; prototype, background and live title/subtitle crops visually inspected. Independent reviewer: no findings. `git diff --check -- .` PASS.
- Decisions: one cached measurement batch per content/style/geometry, on a worker thread. Heading padding 0, line height 1.25; default title needs 3 rows. Boxes never grow automatically; synthetic footer and repair budgets unchanged. Rounded backgrounds cannot clip fitted text. Added context-section ordering gotcha to AGENTS.md. No dependencies.
- Tried and failed: extra context section broke ordering assertions; merged guidance into existing sections. Fixed reviewer-found empty-decoration font handling. Initial live interview failed before spec; retry passed.
- Gotchas: evidence/logs in `.blueprint/qa/task-13.3/` and `.blueprint/task-13.3-*`.
- Left open: none.
- Next: final architect audit of the completed backend plan.

## 2026-10-20: Audit (final)
- Status: ACCEPTED. Re-audit of completed fixes 13.1-13.3 and affected earlier behavior;
  all 44 planned tasks complete. Independent reviewer found no remaining demonstrated P0/P1.
  Full evidence, scope, skips and per-command ledger: docs/audit-reaudit-2026-10-20.md.
- What changed: architecture conventions/decision log absorb the fixes; previously deferred
  design paragraphs explicitly identify future hardening. Essentials updated and stamped;
  duplicate convention gotchas removed from AGENTS. PRD Later retains approved P2 deferrals
  and now records intermittent live planning/reference failures plus label/font polish.
  Plan audit header records ACCEPTED. Product source, tests, dependencies and contracts unchanged.
- Checks: Test (all) PASS, 1106 passed/9 live deselected/3 warnings, 387.27s. Re-ran 33 distinct
  focused commands for 29 affected tasks and contract/render acceptance: 31 initially PASS;
  2 live commands initially failed and passed unchanged isolated reruns. All offline commands
  PASS. Fix suites 13.1/13.2/13.3 PASS (260/33/208). Original Windows stalled-server oracle
  PASS in five fresh processes with unchanged 1.5s + 0.5s limit and cleanup assertions.
- Live: core/GPS/image mapping PASS (3, 384.74s), real engine dry-run done with 12 valid recipe
  lines/11 skipped/0 failed. Reference smoke initially invalid observations (19.19s), isolated
  rerun PASS (20.34s). Synthetic suite 1 PASS / 1 FAIL (244.05s): heading-fit rejection exhausted
  two repairs before publication; isolated screenshot-only rerun PASS (132.56s), labeled
  prototype/recipe. Reviewer grades both intermittent failures P2, not remaining blockers.
  Failed heading inputs were lost to pytest temp cleanup; cause remains unconfirmed, and
  the retained observation excerpt is explicitly not a raw DB backup. No reliability rate
  or uniformly first-pass-green claim. No prompt/config/code or repair-budget change for reruns.
- Visual/release: parent and reviewer inspected fresh 1200px core/heading/synthetic images;
  headings fit, background crops match, sample-data footer visible. Real Chromium 12-component
  15s oracle PASS. Isolated documented uvicorn health 200 in 4.25s, no reload. Contract checks
  PASS, including synthetic 185 passed/930 deselected; manual conventions review PASS.
  No actual report creation, hosted deployment or whole-program integration acceptance claimed.
- Decisions: no additional fix phase; POC blockers resolved, known limitations stay in Later.
  Preserve shared schema shipping, Windows Job ownership/0.4s cleanup, shared cached text
  fitting and stable context section ordering as lasting conventions. Test-created cloud
  resources may remain in the demo project; user runtime/configuration untouched.
- Mechanical: all 17 dependency rows FOUND; no new direct dependency. Backend-scoped secret
  metadata/pattern review found no matches (not a whole-program certification). Stamp PASS;
  lint 0 errors/4 historical warnings; scoped diff whitespace PASS. Commit backend docs only.
- Left open: no blocker or unverified dependency. Known P2/P3 limitations in PRD Later.
- Next: nothing left to build in backend; root integration audit after other parts are accepted.

## 2026-10-21: Change interview feasibility recovery (program root)
- Status: planned; backend 14.1 is ready, not implemented.
- Source: release task 2.2 failed on its first ordinary audience/metrics answer. Its trace
  reported feasibility_blocked for "The audience is sales executives." and incomplete mappings.
- Evidence: read-only explorer traced the bounded audience recognizer and original-source
  match in src/dss/spec/requirements.py, plus the blocked-assessment route in harness/graph.py
  that bypasses the interviewer. Existing tests require that bypass; readiness already has
  independent assessment checks. Persisted source digests mean a prompt-only repair would
  not recover old misclassified rows. No new live run or code fix is claimed.
- Ruling: context remains context with source coverage; actual requirements still require
  capability/data evidence. Continue valid conversational turns to clarify missing definitions,
  with readiness and all dependent side effects gated. Preserve extraction/provider/guardrail
  error handling, provenance, budgets and genuine unknown/unsupported behavior.
- What changed: architecture.md new Interview feasibility recovery spec and decision row,
  essentials summary/stamp, PRD default, and plan task 14.1 (M). Contracts remain unchanged:
  dashboard-intent 1.1 already requires interview clarification and gates ready_for_plan.
- Decisions: one blocker repair, not another general audit-fix phase; no new dependency,
  API shape or product feature. No delta audit required for this narrow POC change.
  Historical ACCEPTED final audit predates 14.1 and does not verify the repair.
- Checks: backend stamp PASS; lint 0 errors/4 pre-existing size warnings; program 0 problems;
  root check_contracts.py 9/9 PASS; scoped git diff --check PASS. Backend tests not run in this
  documentation-only session; the focused, live and full commands are task 14.1's Done when.
- Change requests settled: release 2.2's interview-feasibility question is planned as 14.1;
  no other new request in the latest backend entry.
- Next: builder in backend/ completes 14.1; then release 2.2 recovers its saved driver and
  verifies both dry-run versions at the program root.

## 2026-10-21: Task 14.1 Preserve audience context and continue feasibility clarification
- Status: done
- Plan check: off
- What changed: requirements.py recognizes audience rows by code (exact audience clause of the source, needs empty or only the unknown.unclassified sentinel, remainder covered by sibling rows) for issues, coverage and verification; merge reads SUM()/COUNT(DISTINCT)/grain definitions, absorbs definition-only answers anywhere in a message and fails closed on uncovered clauses. graph.py routes blocked interview assessments to the interviewer (new feasibility context section); prompts/skill updated. New offline API/graph tests, live three-turn test and tests/data/interview_sales.csv.
- Checks: Done-when focused suite PASS (227); `uv run pytest -m live tests/live/test_backend_flow.py -k interview` PASS (2, 202.62s); Test (all) `uv run pytest` PASS (1140, 10 deselected); `git diff --check` PASS. Reviewer: 0 P0/P1; 2 P2 + 1 P3 fixed.
- Decisions: count vs count_distinct needs an explicit COUNT(...)/COUNT(DISTINCT ...)/distinct-count clause; DISTINCT only with COUNT. Bounded courtesy clauses ("thanks", "that is everything", "please plan it") need no row. Audience qualifiers are a fixed list. Live answer 4 uses single-page canvas + hex series colors. Old interview-bypass tests updated to assert the reply, ok trace and gated plan. AGENTS.md gotcha added. No dependencies, contracts or budgets changed.
- Tried and failed: "default theme / all orders" answer and a prompt that split cadence sentences both produced unknown rows (evidence `.blueprint/qa/task-14.1/interview/*`, logs `.blueprint/task-14.1-*.log`); one transient first-turn llm_unavailable.
- Gotchas: none beyond AGENTS.md.
- Left open: P2 partial omission in a mixed message (extractor drops one clause but keeps a sibling) is not detected; pre-existing extraction trust - src/dss/spec/requirements.py. P3 non-aggregate distinct wording ("use customer_id for unique customers") now always asks - src/dss/spec/requirements.py. P3 bare roles ("Sales team.") count as context - src/dss/spec/requirements.py.
- Next: release 2.2 at the program root recovers its saved driver and verifies both dry-run versions.

## 2026-10-21: Change conversational definitions and styling (program root)
- Status: planned; task 14.2 is ready, not implemented.
- Source: release 2.2 retry b_04db6ec42f78 completed all three interview turns but POST /plan
  returned feasibility_blocked for explicit formulas and ordinary theme wording.
- Evidence: read-only explorer checked the persisted ledger and requirements.py assignment,
  merge and mapping-verdict paths. Comma/conjunction boundaries miss order count/quantity;
  later revenue charts do not inherit earlier explicit SUM provenance; blue styling remains
  unclassified. Monthly date grain is present. The 14.1 live regression used different wording.
- What changed: architecture.md adds Conversational definitions and supported styling and a
  decision row; essentials summarized/stamped; PRD default records compatible definition reuse
  and choice of a supported blue shade. Task 14.2 (M) carries the exact release interview/comment,
  offline positive/negative/persisted-ledger checks and real live prototype/revision acceptance.
- Decisions: one existing-goal blocker repair; no API, contract, dependency, token/repair budget
  or unrelated deferred-hardening change. Do not replace ordinary prose with special test wording.
  No delta audit required at POC; previous final audit does not verify 14.1/14.2.
- Change requests settled: latest release 2.2 question planned as 14.2; release waits on it.
- Checks: backend stamp PASS; lint 0 errors/4 existing size warnings; root Test (all) 9/9 PASS;
  root lint 0 errors/0 warnings; program 0 problems; git diff --check PASS. No backend tests
  or live runs performed in this planning-only session.
- Next: build 14.2 here, then resume release 2.2 at the root using its latest 02:11 stash.

## 2026-10-21: Task 14.2 Resolve coordinated metric definitions and ordinary blue styling
- Status: done
- Plan check: off
- What changed: requirements.py reconciles coordinated affirmative formulas (commas/"and"), reuses same-label definitions forward with provenance/conflict blocking, normalizes single-page scope and blue styling to style.colors, drops bogus message component_ids and redundant unregistered need inputs; per-chart `colors` (user-approved) in models/capabilities/compiler/prototype; compact requirements.json context; prompts/skills; offline + live release tests.
- Checks: Done-when offline 5 files PASS (314); `uv run pytest -m live tests/live/test_backend_flow.py -k interview` PASS (3 passed, final code; evidence .blueprint/qa/task-14.2/interview/20261021-033337-8fb6fb92 and 030329-97fef945 with before/after spec+png: palette ['#1E40AF'], only target trend gets ['#172554'], geometry/bindings unchanged); `uv run pytest` PASS (1185 passed, 11 deselected).
- Decisions: clean blue -> ['#1E40AF'], dark blue accent -> ['#172554'] (exact palette; coverage error names it for repair). Label identity is exact; "average/avg" prefix no longer optional. Polite "could you/would like" is affirmative; hypothetical/assuming/perhaps/e.g. are not. Ledger context lists each source once, rows cite ids, mapping_origins omitted (no budget change). Regex cache + literal prefilter: recompute ~60 ms on 40 rows/24 components (test added). AGENTS.md: two gotchas.
- Digest: Component.colors: list[Color]|None (1-20, charts only) overrides theme.palette in prototype/recipe set_style. Requirement gains mapping_origins/mapping_conflicts. requirement_sections -> {sources:{id:...}, requirements:[{source_id, clarification_source_ids,...}], decisions}.
- Tried and failed: live plan failed on bogus component_ids + vague palette error; revise context over 6000 budget from repeated source texts; transient 30 s worker timeout once.
- Gotchas: none beyond AGENTS.md.
- Left open: P2 "preserve its position and data" baseline freezes the component against later edits/replans - src/dss/spec/requirements.py; P2 derived mapping_origins/clarifications in meaning() may reopen legacy decisions on defined rows - requirements.py meaning(); P2 sentence-level "Do not use these definitions." before a separate sentence still authorizes - requirements.py _affirmative; P2 _effective_text "Actually," cuts earlier row text; P3 colors on non-chart reported as invalid JSON in repair; P3 unit regex `in [a-z]{3}` matches months; P3 failed-ledger fixture built from fake script; P3 two message-level blue preferences unsatisfiable; core live test_interview_to_prototype failed once with invalid_request (no evidence saved), passed twice after.
- Next: resume release 2.2 at the program root using its latest stash.

## 2026-10-21: Change staged workflow (program root)
- What changed: architecture.md: new sections Staged workflow, Data profile, Context, Outline, Design and theme kit, Blueprint, Spec layout; Graph, Working memory assembly, Key flows, Build docs, BigQuery view, Dashboard Spec (1-5 pages), Prototype renderer, Revise (decoration color comments), Capability verification, Consolidation and folder structure updated; Interview feasibility recovery and Conversational definitions marked superseded; two decision-log rows. Essentials restamped; PRD goals, flows, features, success criteria, defaults and Later updated. Phase 15 tasks 15.1-15.11 added.
- Why: per-message requirement extraction in the free-text interview kept failing (backend 14.1, 14.2; release 2.3 `llm_unavailable`), and the one large plan run failed about 1 in 3 live runs, sending users back to the interview. The user asked for a context-engineered, node-per-artifact workflow where the model gets only enough context and code generates the files.
- Contracts: api.md 2.0, dashboard-intent.md 1.2, synthetic-data.md 1.2 (provider).
- Tasks affected: none reopened; 15.1 is next.

## 2026-10-21: Audit (delta, staged workflow, program root)
- 16 findings (1 P1, 10 P2, 5 P3), all accepted and applied; details in ../docs/progress.md (same date).

## 2026-10-21: Task 15.1 Switch to the 2.0 build shape and remove the interview and plan path
- Status: done
- Plan check: off
- What changed: 2.0 Build fields, migration and artifact state machine; removed POST interview/start, messages, plan and their nodes/prompts/skills. Deleted tests/test_interview.py, tests/test_plan.py, tests/test_spec_node.py and obsolete shared/live cases; independent coverage retained.
- Checks: Done-when and Test (all): uv run pytest PASS, 1167 passed, 6 deselected, 2 warnings (449.82s). Publication: 39 passed. Review: no findings.
- Decisions: state.py supplies reservations and pure transitions; blueprint stays blueprint until publication. SQL input types moved to view.py. Extra guards/routing/journal/shared-test edits were necessary dependencies. Bounded _affirmative cache (1024) preserves the existing 100ms recompute check. AGENTS.md records UTF-8 I/O.
- Digest: artifacts/state.py: Stage, ArtifactStates, action, edited/confirmed -> transition, save, require_confirmed. builds.notes/artifacts_json migrate additively; missing+saved-spec exempts recipe/run/versions. Blueprint confirmation awaits publication.
- Tried and failed: old helper/nullable assertions, Unicode editing, journal test method name; corrected. Uncached recomputation exceeded 100ms; caching passed.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: Task 15.2 Artifact models, OKF writer and profile script.

## 2026-10-21: Task 15.2 Artifact models, OKF writer and the profile script
- Status: done
- Plan check: off
- What changed: Added contract-shaped artifact models, readable atomic OKF persistence with update events, and aggregate-only profiling shared by BigQuery intake and the CLI.
- Checks: `uv run pytest tests/test_artifacts.py tests/test_profile.py tests/test_intake.py` PASS (40); `uv run pytest` PASS (1184, 6 live deselected, 2 upstream warnings); live sample CLI PASS (2000 rows, 10 columns, 7.458 s); `git diff --check -- .` PASS. Independent review: no findings.
- Decisions: One aggregate query per source. Profiles add values/counts and values_complete; sample remains public. prompt_text uses deterministic ordering, samples-first trimming, top-five reduction and conservative UTF-8 sizing; columns after 40 retain only name/type. write_artifact requires an async build/run-bound emit callback and maintains index/log.
- Digest: artifacts.models defines Context/Outline/Design/Blueprint; okf.read_artifact(path), async write_artifact(path, artifact, emit=...). profile_table(service, table), prompt_text(profile); columns add values[{value,count}] and values_complete. BigQuery.profile delegates.
- Tried and failed: none.
- Gotchas: none.
- Left open: none.
- Next: Task 15.3 Context node and endpoints; consume these models, OKF helpers and compact profiles.

## 2026-10-21: Task 15.3 Context node and endpoints
- Status: done
- Plan check: off
- What changed: Bounded Context drafting/repair, deterministic validation, OKF persistence, endpoints, events and state invalidation.
- Checks: `uv run pytest tests/test_context_node.py tests/test_api_contract.py` PASS 77; Test (all) `uv run pytest` PASS 1214 (9 deselected); `uv run pytest -m live tests/live/test_staged_flow.py -k context -s` PASS 3. Sample: zero issues, one generation. Boundary billed 6300/6301 < bounds 9486/9487. Review P1 fixed; re-review clear.
- Decisions: Combined dry run rejects aggregates and checks types. Outside Files: schema-returning BigQuery helper and named live tests. Added AGENTS.md gotcha. Structural errors: 422; semantic issues: editable. Confirm proposal/revalidation belongs to 15.4. Bound=max(chars/4,folded*1.20+512).
- Digest: nodes/context.py: validate(draft, connected, service) -> Context; context.md OKF. api/workflow.py: GET/POST/PUT/context + confirm. BigQuery.dry_run returns schema. Confirm traces outline_propose; 15.4 adds proposal/revalidation.
- Tried and failed: Fixed incomplete fixture and review's declared-type trust finding.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: Task 15.4 Outline nodes/endpoints; replace confirm's callback with the Outline branch.

## 2026-10-21: Task 15.4 Outline nodes and endpoints
- Status: done
- Plan check: off
- What changed: Outline proposal, code revalidation, selection, suggest, other-text extraction, confirmation, persistence and events.
- Checks: `uv run pytest tests/test_outline.py tests/test_api_contract.py -q` PASS 62; `uv run pytest` PASS 1229 (10 live deselected); `uv run pytest -m live tests/live/test_staged_flow.py -k outline -s` PASS 1: 3 sections, 9 questions, one generation, valid refs, billed input 1021 <= bound 2147 <= 8000. `git diff --check -- .` PASS. Independent re-review: no findings.
- Decisions: Build-level counters never recycle IDs. Other publication rolls back its bundle; scope overflow remains blocked. Outside Files: Context-confirm fixture and named live oracle. Design prefill belongs to 15.5. Added AGENTS.md timing gotcha.
- Digest: nodes/outline.py: load/revalidate/compose/persist; Outline endpoints and one-shot propose/suggest/other. Context re-confirm is code-only. IDs: build-level outline_ids.json. Other refreshes requirements/feasibility; confirm enters design (15.5 adds prefill).
- Tried and failed: Corrected connect-stage fixture, expanded ledger budgeting, and review's duplicate/overflow cases. Full run timing check failed at 104.9 ms; unchanged isolated and serial full reruns passed.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: Task 15.5 Theme kit and design endpoints; add prefill/revalidation at Outline confirmation.

## 2026-10-21: Task 15.5 Theme kit and design endpoints
- Status: partial
- Plan check: off
- What changed: Six OKF presets, checked Data Studio font inventory, deterministic kits, code-only Design prefill/edit/revalidation endpoints and approval-sheet renderer. Outline confirmation preserves existing Design preferences.
- Checks: `uv run pytest tests/test_design.py tests/test_api_contract.py` PASS (82); `uv run pytest` PASS (1264, 10 live deselected). `uv run python scripts/render_presets.py` produced six PNGs plus preset_sheet.png in data/preset_sheets; all opened and visually checked; browser gallery opened. Reviewer: no findings after fixing persistence P2. User approval pending.
- Decisions: Reference background snaps by nearest accessible black/white blend; preset surface/text/font stay. Design confirmation dispatch belongs to 15.6 with its Blueprint node. Outside Files: prototype.py resets empty-shape padding; browser regression verifies 4px rules. AGENTS.md records Georgia width and backup timing traps.
- Digest: artifacts/design.py: presets/prefill/validate/load/persist; render/kits.py: decorations/content_row. GET/PUT design, GET design/presets, POST design/prefill; Outline confirm keeps/revalidates Design. Wire design/confirm in 15.6.
- Tried and failed: 1em heading estimate clipped bold Georgia; corrected. First complete suite: 1263 passed, one backup-spy timing failure; unchanged isolated test and serial full rerun passed.
- Gotchas: see AGENTS.md.
- Left open: none in review; required preset approval remains.
- Next: Obtain approval or changes for all six sheets, then mark 15.5 done and commit. Do not begin 15.6 in this session.

## 2026-10-21: Task 15.5 Theme kit and design endpoints
- Status: done
- Plan check: off
- What changed: Six approved OKF presets, checked Data Studio font catalog, deterministic decoration kits, Design prefill/edit/revalidation endpoints, and preset-sheet renderer. Outline confirmation preserves existing Design preferences.
- Checks: Verified before approval: `uv run pytest tests/test_design.py tests/test_api_contract.py` PASS (82); `uv run pytest` PASS (1264, 10 live deselected). `uv run python scripts/render_presets.py` generated all six sheets and the combined PNG; visually checked and user explicitly approved all six on 2026-10-21. Reviewer: no findings after persistence fix. Approval follow-up changes documentation only.
- Decisions: Reference background uses the nearest accessible black/white blend; preset surface/text/font stay. Design confirmation dispatch belongs to 15.6 with its Blueprint node. Outside Files: prototype.py resets empty-shape padding, covered by a browser regression. AGENTS.md records Georgia width and backup timing gotchas. No dependencies added.
- Digest: artifacts/design.py: presets/prefill/validate/load/persist; render/kits.py: decorations/content_row. GET/PUT design, GET design/presets, POST design/prefill; Outline confirm keeps/revalidates Design. Wire design/confirm in 15.6.
- Tried and failed: Prior entry records the corrected heading estimate and transient backup-test failure; final serial suite passed unchanged.
- Gotchas: see AGENTS.md.
- Left open: none.
- Next: Task 15.6 Blueprint node, view sources and union view; wire Design confirmation to the Blueprint run.

## 2026-10-21: Task 15.6 Blueprint node, view sources and union view
- Status: done
- Plan check: off
- What changed: Blueprint generation/redrafts, coverage repair, join/union SQL validation, endpoints, bounded catalog prompts and GPS fixtures.
- Checks: `uv run pytest tests/test_blueprint.py tests/test_view_sql.py` PASS (49); `uv run pytest` PASS (1298, 10 live deselected, 340.88s); read-only review: no remaining findings; `git diff --check -- .` PASS.
- Decisions: Context expressions retain raw scope; extras use normalized projection. Budgets: 14k/6k, one generation/coverage repair/SQL repair. Full feasibility remains 15.7; coverage alone leaves Assessment unchecked. Outside Files: profile.py preserves array mode. Added AGENTS.md font gotcha. No dependencies.
- Digest: nodes/blueprint.py load/make_branch; view.blueprint_sql(..., context_fields=()) and blueprint_fields(...); design/confirm and blueprint/regenerate dispatch one run. blueprint-inputs.json stores question hashes, Context field names and diagnostics; 15.7 adds full feasibility.
- Tried and failed: Fixed fixture-font setup and reviewed raw-expression/nested/array gaps. Interrupted one redundant full run before final checks.
- Gotchas: see AGENTS.md.
- Left open: none.
- Next: Task 15.7; extend row_errors and Assessment with full feasibility, alternatives and decisions.

## 2026-10-21: Task 15.7 Blueprint feasibility, repair, issues and decisions
- Status: done
- Plan check: off
- What changed: Structured row/KPI/source/page checks, one row repair, code-built alternatives and decisions, atomic artifact writes, and acceptance preflight. Assessment/Issue transport is unchanged.
- Checks: `uv run pytest tests/test_blueprint.py tests/test_feasibility.py tests/test_api_contract.py -q -x` PASS (207); Test (all) `uv run pytest -q` PASS (1312, 10 live deselected); `git diff --check` PASS. Read-only review: no remaining findings.
- Decisions: Rows stay structured; choices retain resolved issues and recheck evidence. Acceptance requires current intent/proof; derived types require BigQuery schema. Publication remains 15.9. Oracle bindings use actual CSV columns; removed derivations require repair. No dependencies or outside-Files edits.
- Digest: spec/feasibility.py: diagnostics, issue_rows, decide; Ledger.blueprint_decisions; nodes/blueprint.preflight(db, build_id, folder) gates before view writes. req.inputs includes artifacts. Task 15.9 must wire the prototype dispatch to candidate publication.
- Tried and failed: Canonicalized issue IDs; fixed and rechecked all review findings.
- Gotchas: see AGENTS.md for BigQuery dry-run schema validation.
- Left open: none.
- Next: 15.8 Code layout: blueprint and design to a multi-page spec.

## 2026-10-21: Task 15.8 Code layout: blueprint and design to a multi-page spec
- Status: done
- Plan check: off
- What changed: New spec/auto_layout.py lays out an accepted Blueprint + Design into a validated 1-5 page spec with no model call. Validator and model accept 1-5 pages (per-page index, prefix, height, overlaps) and a layout-only question_ref coverage rule.
- Checks: `uv run pytest tests/test_layout_auto.py tests/test_spec_validate.py` PASS (173); Test (all) `uv run pytest` PASS (1329, 10 live deselected). Review: no P0/P1.
- Decisions: Layout golden is tests/data/golden_layout_spec.json (golden_spec.json stays the recipe golden). Canvas height = page 1; later pages own height; height fits content. Synthetic footer page 1 only. Section heading = subtitle decoration, per_section only. text component text = label; dropdown dimension -> field. Heights: controls 3, scorecards 5/4 (<=4 per row, balanced), charts per type x density, half width 6. IDs p<n>_<label slug>. AGENTS.md gotcha added.
- Digest: spec/auto_layout.py: layout(blueprint, design, outline, fields[{name,type,role}], *, build_id, archetype, spec_version=1, synthetic=False, allowed=None) -> DashboardSpec; raises LayoutError(.errors). validate_spec(..., question_refs=()) for layout only.
- Tried and failed: Soft-wrapped headings failed the Chromium fit check (hanging space); explicit breaks fixed it.
- Gotchas: Property test batches text checks: monkeypatch layout._text_fits, then measure all cases once.
- Left open: P2 compiler expects synthetic label on every page - src/dss/recipe/compiler.py; P2 render/compile write only background_p1.png - harness/nodes/render.py, compile.py (15.9); P2 ok image rows always fail layout (no image_path in Blueprint) - feasibility/catalog_summary; P3 TITLE_WIDTH duplicates kits widths; P3 _wrap breaks early (1.3em); P3 coverage ignores control rows.
- Next: Task 15.9. Start by wiring layout() into blueprint accept and rendering every page.

## 2026-10-21: Task 15.9 Multi-page render, backgrounds, compile and decoration comments
- Status: done
- Plan check: off
- What changed: Prototype HTML is one `#dss-canvas` with a `section[data-page][data-page-name]` per page; one background PNG per page (accept, revise, compile, versions); new `prototype` action (blueprint/accept): candidate view -> auto_layout -> render -> publish, blueprint confirmed with the commit. Revise works on every page, fulfils decoration accent comments and "Remove this chart".
- Checks: `uv run pytest tests/test_render.py tests/test_compiler.py tests/test_revise.py` PASS (101, later 166 with publication/synthetic_label); Test (all) `uv run pytest -q` PASS (1350, 10 live deselected); 3x8 render+Chromium backgrounds 2.12 s; (../engine) `uv run dsengine validate` exit 0, `--dry-run` ok 59 ops; prototype_p1..3.png and background_p1..3.png in .blueprint/qa/task-15.9 viewed. Review: P1+P2+1 P3 fixed.
- Decisions: Backgrounds = one Chromium launch per page via `render(page=n)`. Decoration accent -> property `style.<kits.accent_key(kind)>` + need layout.background_image. Removal = comment text exactly "remove/delete this chart|component|..." -> `mapping_origins['remove']` (+`removed_item`), no new Requirement field (digests stable); retires rows bound to/only fulfilled by it. Blueprint confirmation saved before commit; Candidate.restore rolls back artifacts_json. derived-fields.md gains `union`. Outside Files: patch.py, context.py (all pages), requirements.py, publication.py, validate.py, auto_layout.py (pivot dims from row/column options), compile.py, api/builds.py (per-page backgrounds). AGENTS.md gotcha added.
- Digest: render(spec, page=n); background.names(spec), write_pages(spec, folder); nodes/render.accept(harness, build_id, run_id, payload, trace) = action `prototype`; patch paths /pages/<p>/...; requirements.removal(row); kits.accent_key(kind).
- Tried and failed: none.
- Gotchas: Bash heredoc append with quotes failed silently (nothing written); use Edit.
- Left open: P3 stale background_p<n>.png from an earlier, longer plan stay in the version folder - spec/publication.py; P3 removal recognised only for the narrow phrasing (live check in 15.11) - spec/requirements.py; P3 a removal row would block a re-plan that recreates the same id - spec/requirements.py; P3 a row bound to removed and kept ids still fails coverage - spec/requirements.py.
- Next: Task 15.10. Start by routing references/synthetic/research/versions through the staged flow (graph.py).

## 2026-10-21: Task 15.10 Wire references, synthetic data, research, versions and consolidation into the staged flow
- Status: done
- Plan check: off
- What changed: Synthetic writes only at `connect` (synthetic-data.md 1.2); consolidation reads context/outline/design/decisions (legacy brief kept); unknown-action reject span is `reject`; prototype trace adds `publish`, revise adds `render`; reference reply names outline proposal/design prefill. New tests/test_graph.py asserts every branch's span order.
- Checks: `uv run pytest` PASS (1362, 10 live deselected); `uv run pytest tests/test_api_contract.py` PASS (47); review: no P0/P1, P2 tolerant capability_check span order fixed (exact, 3/3 stable), P3 engine_login trace added.
- Decisions: Trace = one span per node in order, e.g. prototype router,prototype,view,layout,render,publish,guardrail; revise router,capability_check,assess_capabilities,revise,validate_revision,render,guardrail. CONSOLIDATE_DOCS = context, outline, brief, design, decisions (raw file, 3000 chars each). Outside Files: harness/context.py, nodes/render.py, nodes/revise.py (one span each).
- Digest: Trace spans per branch fixed in tests/test_graph.py (reject span `reject`; prototype adds `publish`, revise `render`). context.CONSOLIDATE_DOCS adds context/outline. Synthetic writes: STAGES=("connect",).
- Tried and failed: none.
- Gotchas: outline Proposal needs 3-5 sections of 3-6 questions; a 1-section FakeLLM reply fails as "invalid draft".
- Left open: P3 five full-size staged builds (4 docs x 3000 chars) can exceed the consolidate budget and drop the oldest build - harness/context.py
- Next: Task 15.11. Start by running the live staged flow on the sample and the GPS-style fixture.

## 2026-10-21: Task 15.11 Live staged flow on the sample and the GPS-style fixture
- Status: done
- Plan check: off
- What changed: tests/live/test_staged_flow.py adds the full sample flow (Flow driver, per-run tokens/bounds/budgets, stage timings, page PNGs, evidence kept on failure) and the GPS union flow; test_backend_flow.py gains evidence_dir, validate_recipe, usage/check_usage, page_shots. Live defects fixed outside Files with user approval (cards): requirements.py, nodes/blueprint.py, context.py, skills/outline.md, prompts/v1/outline.md (+ offline tests in test_outline/render/revise/blueprint/capabilities).
- Checks: `uv run pytest -m live tests/live/test_staged_flow.py` PASS (6, 277 s, final code; also 6 passed before the review fixes; final evidence .blueprint/qa/task-15.11/sample/20261021-180420-18c06021, gps/20261021-180633-6b02d351; 14 earlier failed runs kept beside them); Test (all) `uv run pytest` PASS (1376, 12 deselected). revised_p1..3.png viewed: only the trend line red, only the p1 band #1E3A8A. Reviewer: 0 P0/P1; P2 x2 + P3 x2 fixed.
- Decisions: Approved rules: outline_other records tagged mapping_origins origin=outline_other; empty extraction adds no blocking row; their needs_clarification verdicts don't block; publish coverage skips them (question rows fulfil them). outline_other only: Context KPI restatement -> mapping_origins kpi:<label>=<id>:<field>:<agg>:<unit> (defined); bare argument field/value restatement dropped (_restated_arguments). Ratio questions cite the ratio KPI id (skill/prompt). Dropdown summary = exactly 1 dimension. capability_context drops outline/design/blueprint, compacts context. Decoration comment with one hex in its words (need or property) -> layout.background_image + style.<accent_key>.
- Digest: Live helpers in tests/live/test_backend_flow.py: evidence_dir(task, flow), validate_recipe(text), usage(app, run_id), check_usage(run), page_shots(html, spec, folder, prefix). requirements: outline_other records carry mapping_origins['origin']='outline_other'.
- Tried and failed: test-only workarounds rejected by user in favour of code fixes (6 live defects, one per run).
- Gotchas: see AGENTS.md (extractor shape variance). Pre-existing test_only_mapped_unregistered_inputs_are_redundant guards _redundant_inputs: keep it narrow.
- Left open: P2 Other text is fail-open (empty extraction / skipped coverage) vs ../contracts/dashboard-intent.md "preserve requested behavior" - spec/requirements.py (user-approved; architect to record); P3 check_usage asserts input budgets and no history only, not output budgets or row literals - tests/live/test_backend_flow.py; P3 count scorecards render "10.00" and the ratio alternative duplicates existing KPI tiles - render/spec.
- Next: release part takes the staged workflow (no backend task left in plan).

## 2026-10-21: Audit (final)
- Verdict: DEFECTS — one P1. Independent read-only reviewer confirmed the shared feasibility evaluator still blocks totals above 24 components, contrary to the staged 1-5-page/12-row-per-page scope. No other demonstrated P0/P1; repair plan and fresh fixture/live visuals reviewed without findings.
- What changed: docs/audit-reaudit-2026-10-21.md records scope, evidence and the complete check ledger; plan.md adds only task 16.1 (M); architecture.md and essentials fold durable staged decisions and specify the repair; PRD Later records approved/deferred limits; AGENTS.md removes obsolete/redundant gotchas. No product code, tests, dependencies, contracts, runtime settings or other parts changed.
- Checks: Test (all) uv run pytest PASS (1376, 12 live deselected, 773.53s); 44 distinct focused commands, 42 initially PASS and 2 initial failures, both unchanged isolated reruns PASS (definition timing 0.62s; screenshot capture 2.29s). All 12 live checks PASS first run (1376 deselected, 528.17s), including staged sample to three pages/22 components, two targeted revisions, valid recipe and configured-engine dry-run done (49 skipped/0 failed), GPS union, Context/Outline bounds, references and synthetic intake. Profile CLI: 2000 rows/10 columns, 6.31s; isolated uvicorn health 200 in 4.12s; engine validate exit 0; six preset sheets regenerated and visually checked. Parent/reviewer viewed fresh fixture/live pages and backgrounds. All 17 deps FOUND; scoped reviewer credential/history scans found no matches, no values printed.
- Decisions: one POC repair task in the fix budget, targeting the shared count ceiling with 27/60-component regressions and unchanged gates/budgets. The full suite misses this defect: a real auto_layout probe with nine questions x three rows passes Blueprint/spec validation but becomes blocked only after layout. Initial focused failures are retained: definition recompute best 105.47ms versus 100ms and one 20s document-load timeout; both also passed other serial suites. No limits were relaxed and no tests were weakened.
- Limitations: user-approved 15.11 Other bypass is recorded explicitly as a contract preservation gap, not claimed full dashboard-intent conformance; only the program root may reconcile the contract. Other open P2/P3 items are in PRD Later, with no extra build tasks. Fresh synthetic live checks cover proposal/generation/typed intake; the complete staged prototype/build smoke uses the uploaded CSV.
- Left open: P1 obsolete component ceiling — task 16.1. The previous final ACCEPTED verdict does not cover this staged change set. Current state: 57/58 tasks done, one ready; backend acceptance and the root integration gate await repair/re-audit.
- Mechanical checks: architecture/essentials stamp PASS; blueprint lint 0 errors/4 historical warnings; scoped git diff --check PASS. Essentials and AGENTS.md fit their size limits. Product/test/dependency paths remain at backend build commit 64d4da9.
- Next: build 16.1 here in a fresh builder session, then re-audit the backend; after ACCEPTED, resume release integration from the program root.

## 2026-10-21: Task 16.1 Align feasibility with the staged multi-page component scope
- Status: done
- Plan check: off
- What changed: requirements.evaluate no longer adds the global ">24 components" scope issue; MAX_COMPONENTS = 60 and Extracted.component_ids max 60. Tests: test_render staged_rows/staged_flow (3x9 and 5x12 accept -> prototype -> recheck ready), test_compiler 27-component recipe + fake-engine done, test_feasibility staged ready before/after layout + 5 negative cases.
- Checks: `uv run pytest tests/test_feasibility.py tests/test_render.py tests/test_compiler.py tests/test_api_contract.py` PASS (228 passed, 2 deselected); Test (all) `uv run pytest` PASS (1386 passed, 12 deselected). New staged tests fail on HEAD's requirements.py (4 failed: feasibility_blocked after layout).
- Decisions: no per-page spec component check added to evaluate (the 100 ms oracle evaluates 24 components on one page as ready; page count/12-row capacity stay Blueprint checks in spec/feasibility.py); revise patches cannot add components (patch.py). component_ids raised to the 60 scope so revision extraction can target any component.
- Digest: requirements.MAX_COMPONENTS=60 (1-5 pages x 12 rows); evaluate has no total-component ceiling. Tests: test_render.staged_rows(pages, questions)->(outline, rows), staged_flow fixture (param (pages, questions)); test_feasibility.staged_snapshot/laid_out.
- Tried and failed: none
- Gotchas: none
- Left open: P3 Extracted.component_ids >24 untested and not live-checked against Gemini schema - src/dss/spec/requirements.py; P3 staged 13-row/6-page negatives stop at evaluate, no staged accept-rejection view-write test - tests/test_feasibility.py
- Next: backend re-audit (architect), then release integration from the program root.

## 2026-10-22: Change manual acceptance fixes (program)
- What changed: plan.md Phase 17, task 17.1 (clean blueprint labels; research aggregate rows left out and listed in sources.md; numeric cells with footnote markers).
- Why: release 2.4 blocked: research build b_568901c19819 loaded Wikipedia's "ASEAN" aggregate row as a 12th country and wrote list-fragment scorecard titles. User chose engine + backend fixes, rerun rows 2-3 only.
- Affected: backend 17.1 (new); release 2.4 `Needs: backend 17.1`. No contract change.

## 2026-10-22: Change reference recovery (program)
- What changed: architecture.md adds Replan freshness recovery and Recreate definition reconciliation plus a decision row; essentials summarize them. Plan adds 18.1 (M, valid candidate publication clears artifact staleness) and 18.2 (M, confirmed KPI/reference instruction evidence resolves matching image observations), after 17.1. No product code, dependency, contract or API shape changed.
- Why: release 2.5 reports ready-but-stale after reference deletion/replan (b_24747c71b7e3) and unresolved image metrics despite explicit definitions (b_b4319fb6113d). User chose both fixes over weakening recreation acceptance. They repair required behavior before the 2026-10-23 01:05 MPST deadline.
- Decisions: publication must retain rollback and pending-comment safeguards; mapping reconciliation preserves all observations, active provenance and ambiguity checks. Deterministic offline staged API regressions prove both positive and negative paths; release 2.5 owns the full real-model/engine replay. No new model call or repair budget. POC change: no separate delta audit required.
- Affected: 17.1 remains first; 18.1 -> 18.2 follow. Release 2.5 is reopened with Needs on both fixes; hosted 4.3 keeps its existing dependency/acceptance. Existing deferred hardening and other limitations are not promoted into this change.
- Checks: backend stamp and lint, release lint/program and root contract check recorded in the matching root Change entry. Product tests are the builders' Done-when checks, not claimed as run here.
- Next: backend builder 17.1, then 18.1 and 18.2 in fresh sessions; release reruns 2.5 after both fixes land.

## 2026-10-22: Task 17.1 Clean component labels and research aggregate rows
- Status: done
- Plan check: off
- What changed: research.make_table normalizes marked numbers (`1,440,000 2025e)[5]` -> 1440000) and drops aggregate rows (Table.excluded/possible -> sources.md). validate.label_text repairs leaked list/quote label syntax; blueprint applies it, sends unrepairable labels through the one row repair, then a code fallback; validate_spec rejects dirty labels.
- Checks: `uv run pytest tests/test_research.py tests/test_blueprint.py tests/test_spec_validate.py tests/test_recipe_contract.py` PASS 298; Test (all) `uv run pytest` PASS 1411 (12 deselected). New tests fail on old code (23 checked).
- Decisions: aggregate signals: bare total name, unranked row in a ranked (1..n) column, label in table title, equals sum of other rows (1%). Drop only on a bare total name in an unranked table/row, or unranked + another signal; ranked rows are never dropped; one signal or no-rank pairs -> "possible aggregate" (kept, per If). Placeholder dashes in numeric columns load empty. Label error is diagnostics-shaped, never persisted; fallback "<metrics> by <dimension>". Old persisted dirty blueprints now fail layout until redrafted.
- Digest: research.Table.excluded/possible [{label, reason}] (sources.md lists both); research.normalize_numbers(rows)->numeric cols. validate.label_text(label)->str|None; validate_spec errors `<path>.label` on list/quote syntax or newlines; blueprint.fallback_label(component).
- Tried and failed: none
- Gotchas: none
- Left open: P3 a legit quoted list label (`Orders 'open', 'closed'`) is cut to its first fragment and trailing possessives fail validation - src/dss/spec/validate.py
- Next: Task 18.1. Start with `status`.

## 2026-10-22: Task 18.1 Recover prototype freshness after validated replan publication
- Status: done
- Plan check: off
- What changed: render.perform (candidate branch, under build_lock, after new_sources/blocked/coverage/revalidate) sets ledger.prototype_stale=False before saving the candidate ledger, so freshness+proof publish with the bundle and roll back with it. Staged-API regressions in test_render/test_feasibility/test_publication.
- Checks: `uv run pytest tests/test_feasibility.py tests/test_render.py tests/test_publication.py tests/test_api_contract.py` PASS 271 (2 deselected); Test (all) `uv run pytest` PASS 1419 (12 deselected); with render.py reverted 7 of 8 new tests fail (intent-change guard already held); strengthened pending test then rerun: test_feasibility.py PASS 141.
- Decisions: root cause: sticky ledger.prototype_stale was never cleared by any path. Pending batches stay gated through evaluate/get `or bool(pending_comments)`; GET/check/decide/preflight/revise/copy_version unchanged. Outline trigger = selection change (recipe blocked by wrong_stage until replan). No model call added.
- Digest: render.perform clears Ledger.prototype_stale only after candidate coverage, under build_lock. Helpers in tests/test_render.py: use_reference_model, upload_style, feasibility_check, execution_blocked(client,bid,code), replan->trace, executes, reloaded, published_proof(folder).
- Tried and failed: none
- Gotchas: after a failed accept the stage rolls back to blueprint, so recipe/run return wrong_stage (require_confirmed), not feasibility_blocked.
- Left open: none
- Next: Task 18.2. Start with `status`.

## 2026-10-22: Task 18.2 Reconcile recreate observations with explicit metric definitions
- Status: done
- Plan check: off
- What changed: requirements.py only. inputs() adds snapshot['confirmed_kpis'] (recreate mode; [] unless Context state is confirmed). New _reconcile_observation (in merge, after _reconcile_definitions) binds each recreate image/instruction metric mapping to a unique matching confirmed KPI and/or parsed reference instructions, or records a conflict; mapping_verdict accepts mapping_origins['observed:i'] keys; evaluate adds non-decidable obs_stale_ issues when stored reconciliation differs from current evidence; _flattened_chart blocks charts extracted as layout/style/element only; verification adds definition_evidence. Assignment regex accepts a "Definitions:" heading; image rows skip the model-mapping transplant and _reconcile_grains; replaced-reference clarifications are dropped. Tests: test_feasibility (unit conflicts/timing), test_render (staged API flows), test_references, tests/data/recreate_definitions.json.
- Checks: Done-when `uv run pytest tests/test_feasibility.py tests/test_references.py tests/test_blueprint.py tests/test_render.py tests/test_api_contract.py tests/test_recipe_contract.py` PASS 370 (2 deselected); Test (all) `uv run pytest` PASS 1443 (12 deselected). With requirements.py stashed 20/23 new tests failed (then 2/3 review regressions). Replay of b_b4319fb6113d's ledger: all observation issues cleared (KPI-only and instructions), only its own Blueprint SQL issue remains.
- Decisions: each pass restarts from the original extraction (mapping_origins['requested:i']). KPI match: same name/id words, else label words ⊆ KPI words; >1 distinct definitions = ambiguous. Dimensions (no aggregation, not the observed metric) are never redefined. Instructions clarify screenshot guesses; a KPI alone must match observed aggregation/unit; KPI vs instructions mismatch blocks; unit comes only from definitions. Message-derived conflicts win. Clarification = Context KPI edit+confirm or reference re-upload with instructions, then Check feasibility. No model call added; 24-observation recompute <100 ms tested.
- Digest: requirements._reconcile_observation(r, snapshot), observation_stale(snapshot, r); snapshot['confirmed_kpis'] (recreate only); mapping_origins 'requested:i'/'observed:i'={evidence,key}; verification mapping rows 'definition_evidence'; test_render.recreate_build/upload_recreate.
- Tried and failed: none
- Gotchas: legacy recreate ledgers show obs_stale_ until one Check feasibility re-reconciles them; this changes meaning() so earlier drops on observations need re-choosing.
- Left open: P3 instruction naming a missing field reports needs_clarification, not needs_data - src/dss/spec/requirements.py; P3 two KPIs with identical measure count as one match, evidence names the first - src/dss/spec/requirements.py
- Next: none in backend plan (61/61). Release 2.5 supplies the live proof.

## 2026-10-22: Change report quality (program)
- What changed: plan.md Phase 19: 19.1 (S, STOP, HD background images at device scale 2), 19.2 (S, `Needs: engine 11.2`, page 1 `rename_page`, no scorecard palette op); architecture.md Prototype renderer, Recipe compiler and decision log; essentials recipe 1.1 and the background line. Contract recipe.md 1.1 and recipe.schema.json changed at the root.
- Why: user flagged soft backgrounds and scorecard text on release 2.4 row 2; "Untitled Page" on every report; the engine skips every scorecard palette op. User chose all four fixes (card); engine takes 11.1-11.3.
- Affected: backend 19.1, 19.2 (new). No release gate.

## 2026-10-22: Task 19.1 HD background images
- Status: done
- Plan check: off
- What changed: background.py captures at `SCALE = 2` (device_scale_factor), so background_p<n>.png is 2x canvas pixels; recipe box unchanged. Tests: 2x asserts in test_render (pixel tests now compare at DPR 2, img shown at 1200 CSS px); test_compiler golden-spec 2x + golden bytes + box test. capabilities.json: `rename_page` in layout.multi_page (user-approved, outside Files: recipe 1.1 broke test_capabilities on HEAD).
- Checks: `uv run pytest tests/test_render.py tests/test_compiler.py tests/test_recipe_contract.py` (+test_capabilities) PASS 131; with SCALE=1 the 4 changed tests FAIL; live budget `-m live -k "real_background_dimensions or twelve_component"` PASS 2; Test (all) `uv run pytest` PASS 1444. Live: replay of b_a8ace098d03b with 2x backgrounds (p1 2400x1064, 42 KB vs 15 KB): every set_background_image ok, `failed: 9` (s025 add_chart p2 timeout, cascade); control run with original 1x copy fails identically at s025, so user accepted it as independent. Report 89ec3c16… page-1 img naturalWidth 2400, box 1200x532 (before 1200). Crop ../data/report-quality/backend-19.1-background.png; user approved sharpness (STOP).
- Decisions: SCALE module constant in background.py; Done-when `failed: 0` waived by user given the 1x control.
- Digest: background.SCALE=2: background_p<n>.png is (2*canvas.width)x(2*page.height) px; set_background_image box stays x0 y0 canvas width x page height; compiler bytes unchanged.
- Tried and failed: none
- Gotchas: b_a8ace098d03b replay now fails at s025 (p2 time_series "Average Item Sale Price Over Time", y=884; editor shows "Too Many Rows", View menu open) even with original files: 19.2's live check will hit it.
- Left open: engine/root follow-up for s025 timeout.
- Next: Task 19.2 (Needs engine 11.2). Expect the s025 replay failure in its live run.

## 2026-10-22: Task 19.2 Page 1 named in the recipe; no scorecard palette op
- Status: done
- Plan check: off
- What changed: compiler.py emits `rename_page` (page 1 name) at s002 and no `set_style` for scorecards. Golden recipe + preview re-recorded from real `dsengine print`. User-approved edits outside Files: test_thin_slice, test_revise (accent test retargeted to bar p1_regions; scoped_overrides scorecard→bar h8; new test_scorecard_color_comment_stays_pending), test_agent_server, test_synthetic_label (line-index shifts).
- Checks: `uv run pytest tests/test_compiler.py tests/test_recipe_contract.py` PASS 51 (old compiler: 8 FAIL); `dsengine validate` golden + live recipe exit 0; Test (all) `uv run pytest` PASS 1445. Live b_a8ace098d03b recompile (45 ops): rename_page ok, 0 colors warnings for 8 scorecards, report d4af98f7… page 1 "Executive Summary & Headline KPIs", page 2 correct; `failed: 17` from known s021 p2 time_series timeout cascade (pages 3-4 not added); user waived.
- Decisions: op-capacity test params 993/994 (rename_page uses an id). Scorecard color comments now stay pending (coverage sees no set_style), user chose honest pending. AGENTS.md: gotcha on coverage_errors.
- Digest: compile_recipe ops: s001 open_report, s002 rename_page{name=pages[0].name}, then per page; set_style only for non-scorecard charts; header recipe_version "1.0". Scorecard style.colors comments stay pending.
- Tried and failed: scorecard→bar at h7 in scoped test (bar min h is 8).
- Gotchas: none beyond AGENTS.md.
- Left open: P2 feasibility still accepts style.colors on scorecards (should be unsupported_app, fail fast) - src/dss/spec/capabilities.py; P3 empty page-1 name now fails compile (Page.name has no min_length) - src/dss/spec/models.py; engine s021 time_series timeout.
- Next: plan complete (63/63); follow-up for scorecard colors feasibility.
- Change request: feasibility rejects `style.colors` on scorecards (unsupported_app, src/dss/spec/capabilities.py) so a scorecard color comment fails fast instead of staying pending after 19.2 (user, 2026-10-22).
- Change request: backgrounds still not sharp enough in Data Studio; user's target: >= 1920x1080 px PNG, ~200 KB-1 MB, under 2 MB (user, 2026-10-22). Facts: 19.1 SCALE=2 gives 2400 px wide (p1 2400x1064, 42 KB); the 19.2 live replay used b_a8ace098d03b/v1's pre-19.1 1x files (1200x532, 15 KB), so report d4af98f7 shows 1x backgrounds. Decide scale (e.g. 3x) and whether file size is a target.

## 2026-10-22: Change backgrounds 3x and scorecard colors
- What changed: plan.md 19.3 (S, STOP, backgrounds at device scale 3, each PNG < 2 MB) and 19.4 (S, feasibility rejects colors on scorecards as unsupported_app); architecture.md Prototype renderer (3x, size cap, oracle), Dashboard Spec (no scorecard colors) and decision log; essentials background and colors lines.
- Why: user's HD target >= 1920 x 1080 px under 2 MB (2x page 1 is 2400 x 1064); the "soft" report d4af98f7 used pre-19.1 1x files. No minimum file size: bytes don't add sharpness. Scorecard colors were accepted by feasibility but never sent since 19.2, so comments stayed pending. User chose both on cards; deadline scope gate shown (0 tasks left, both S).
- Affected: backend 19.3, 19.4 (new; independent, both depend on 19.2). No contract or engine change.
- Change requests settled: "feasibility rejects style.colors on scorecards" (19.2 entry) -> planned 19.4; "backgrounds still not sharp enough; target >= 1920x1080, ~200 KB-1 MB, under 2 MB" (19.2 entry) -> planned 19.3 (3x scale, < 2 MB cap; the 200 KB-1 MB range is not a target).

## 2026-10-22: Task 19.3 Backgrounds at 3x scale
- Status: done
- Plan check: off
- What changed: background.py `SCALE = 3`: background_p<n>.png is 3x canvas pixels; recipe box and compiler bytes unchanged. Tests: 2x asserts -> 3x (pixel tests at DPR 3), < 2 MiB asserted for the golden spec (every page) and the 12-component budget spec, `SCALE == 3`.
- Checks: `uv run pytest tests/test_render.py tests/test_compiler.py tests/test_recipe_contract.py` PASS 98; with SCALE=2 the 4 changed offline + 2 live tests FAIL; live budget `-m live -k "real_background_dimensions or twelve_component"` PASS 2 (1.03 s); Test (all) `uv run pytest` PASS 1445. Live b_a8ace098d03b recompile (46 lines, dsengine validate ok): p1 3600x1596 73 KB, p2-p4 84-94 KB. Run 1 failed 22, no save; run 2 partial, failed 9: s004/s014/s035 set_background_image ok, s025 timed out in the s021 cascade (user accepted as engine-side). Report e24616ea… page-1 img naturalWidth 3600, box 1200x532 (19.1's 89ec3c16: 2400). Crop ../data/report-quality/backend-19.3-background.png; user approved 3x (STOP) after seeing 200% and 300% crops.
- Decisions: Data Studio never stretches the image (box 1200x532, identity transform at 1920/1366 wide); at 1920 wide the canvas sits at x=488.5 (half pixel). AGENTS.md: gotcha on the replay stall.
- Digest: background.SCALE=3: background_p<n>.png is (3*canvas.width)x(3*page.height) px, < 2 MB; set_background_image box stays x0 y0 canvas width x page height; compiler bytes unchanged.
- Tried and failed: none
- Gotchas: none beyond AGENTS.md.
- Left open: engine s021 time_series timeout cascade (fails s025 set_background_image).
- Next: Task 19.4 Feasibility rejects colors on scorecards.

## 2026-10-22: Change request: AI-designed page backgrounds (user, after 19.3)
- What changed: docs/change-2026-10-22-designed-backgrounds.md (the user's request, the facts 19.3 measured, the conflicts, the constraints and open questions) and docs/change-2026-10-22-reference.webp (the target look). The 19.3 entry's native-text change request was removed: the user rejected it and wants titles kept in the background.
- Change request: `gemini-4-argon` generates rich decoration-layer HTML backgrounds: headers, titles, card frames, custom icons, in the reference image's style. Improve its prompt and add a design skill the agent loads. Today's kit look is too simple. This conflicts with the PRD non-goal "No LLM-generated HTML" and the essentials' never-do rule, so the user must approve the rule change (user, 2026-10-22; see the brief).
- Change request: the user asks whether the background can be made "the same size in the first place" to avoid stretching. Data Studio doesn't stretch it (box = canvas; the viewer's display scaling does the scaling). Clarify whether they mean a larger canvas (e.g. 1920 wide) (user, 2026-10-22; see the brief).

## 2026-10-22: Change designed backgrounds (planned as phase 20)
- What changed: PRD (goal 9 designed pages; goal 4 routes `gemini-4-argon` to blueprint and designer; non-goal narrowed to "no LLM recipe text, no LLM HTML outside the sanitized designed page layer"; Decided by default), architecture.md (new Core logic section Designed pages; Dashboard Spec adds width 1200-1920, page `design`, `design` decoration kind, component `box`; Layout box precedence; Prototype renderer design root and the 2x fallback over 2 MB; Graph designer node and repair edge; Working memory designer row and 12k budget; Revise and Recipe compiler pointers; Stack, folder map, decision log), essentials (stack, folder map, convention, never-do, lucide-static row verified 2026-10-22 at 1.61.0), plan.md phase 20 (tasks 20.1-20.5, after 19.4).
- Why: the user wants the planner to design stunning page backgrounds and layouts (reference docs/change-2026-10-22-reference.webp) with native Data Studio charts placed in them. User choices on cards: plan now (deadline not a concern); planner writes each page's HTML with one measured slot per component (chart types stay the blueprint's Data Studio types); regenerate the page on geometry/heading comments; width 1200-1920 picked by the designer and set through recipe 1.1's existing `set_canvas` (no engine or contract change); vendored Lucide icons, LLM-drawn SVG as fallback.
- Decided by the architect: the design HTML is stored in the spec; page 1 first sets the width and shared CSS, pages 2-n run in parallel; one repair per page then the code layout and kit for that page (page 1 failing -> whole build on the code path at 1200); the off switch is a Config attribute, not an env name or API setting, so contracts/conventions.md and api.md stay unchanged; the design is one `p<n>_design` decoration so the api.md Prototype HTML rules (no nested `data-cid`) hold.
- Tasks affected: 19.4 unchanged and still first; new 20.1 (M), 20.2 (M), 20.3 (M), 20.4 (M), 20.5 (M, STOP: the user approves the look against the reference).
- Change requests settled: AI-designed decoration-layer HTML with a design skill (planned: 20.1-20.5); "the same size in the first place" (planned: the canvas follows the designed width via `set_canvas`, 20.2 and 20.5; the 1200 code path and 3x scale stay). No delta audit: target POC.

## 2026-10-22: Task 19.4 Feasibility rejects colors on scorecards
- Status: done
- Plan check: off
- What changed: capabilities.py: `Checker.component` rejects `colors` on a scorecard (unsupported_app, `SCORECARD_COLORS`); other charts keep 1-20, non-charts keep "Only chart components support colors". requirements.py `_requirement_issues`: a `style.colors` need bound to a scorecard component becomes the same unsupported_app issue (fail fast, ledger/pending batch persist, spec.json untouched). Tests: test_capabilities, test_feasibility (per-type), test_revise (pending test became fail-fast; palette test retargeted to the bar).
- Checks: `uv run pytest tests/test_capabilities.py tests/test_feasibility.py tests/test_revise.py` PASS (265); Test (all) `uv run pytest` PASS (1448 passed, 12 deselected, before a message-text-only edit; the 3 files rerun after it). New tests fail on the old code (3 failed).
- Decisions: requirements.py is outside Files: `checker.need` has no component types, so the rejection lives where bindings are known (plan "If" path). Message: "Scorecards take no colors (no series swatch in Data Studio): use another chart type to set colors"; no theme-palette advice since nothing colors a scorecard from the theme. No accept-alternative offers exist for style.colors, so only drop resolves the issue.
- Digest: capabilities.SCORECARD_COLORS; Checker.component rejects scorecard `colors`; requirements._requirement_issues turns scorecard-bound `style.colors` needs into unsupported_app (slot need:i).
- Tried and failed: none
- Gotchas: none
- Left open: P3 prototype still renders scorecard colors (dead path, test_revise scorecard_palette test) - src/dss/render/prototype.py:295
- Next: Task 20.1. Start by reading docs/architecture.md#Designed pages.

## 2026-10-22: Task 20.1 Sanitize, icons and slot measurement for designed pages
- Status: done
- Plan check: off
- What changed: new src/dss/render/design_page.py (stdlib-HTMLParser allowlist sanitizer with page-scoped CSS, Lucide inlining, two-pass Chromium measure with JS off and requests aborted); 40 lucide-static 1.61.0 SVGs + LICENSE (ISC, tarball sha512 matched npm) in render/icons/; tests/test_design_page.py; tests/data/designed_page.html (expected boxes in its leading comment).
- Checks: `uv run pytest tests/test_design_page.py` PASS (35); Test (all) `uv run pytest` PASS (1483 passed, 12 deselected). Fixture measure ~0.9 s.
- Decisions: sanitized HTML = one `<style>` prefixed `.dss-design-p<page>` (:root/html/body = root; +/~ from root rejected; all at-rules and viewport units dropped) + markup; idempotent. Code CSS (root absolute at 0,0, border-box, height:auto in pass 1, transparent slots) lives in `wrap()`: 20.2 must draw designs through it. Footer: next 20 px row below the natural height (with_synthetic_label rule), height = footer_y+footer+24. Slot minimum = Layout at the page width. MAX_HEIGHT=4000 (no validator limit existed). Unknown icon/slot names survive sanitize so measure can name them.
- Digest: render/design_page.py: sanitize(html,*,page=1,fonts=())->str; wrap(html,w,h=None,*,page=1); measure(html,{cid:type},w,*,footer=None,fonts=())->Measurement(boxes{cid:{x,y,w,h}},height,errors[{path,message}],requests); icons(); minimum(type,w); footer_top(h); MAX_HEIGHT
- Tried and failed: none
- Gotchas: page.on('request') logs a URL once per measure pass; setuptools won't ship render/icons/*.svg in a non-editable wheel without package-data (editable uv install is fine).
- Left open: P3 non-slot, non-text elements outside the page give no error - design_page.py; P3 root `display:none/contents` gives 0x0 slot errors without naming the cause - design_page.py; P3 (for 20.2) designer CSS reaches root descendants, so draw components and the footer outside the root - design_page.py
- Next: Task 20.2. Start by `status`; reuse design_page.wrap/sanitize for the designed prototype root.

## 2026-10-22: Task 20.2 Designed pages in the spec, layout, prototype, background and recipe
- Status: done
- Plan check: off
- What changed: models (Canvas.width int 1200-1920, Box, Design, decoration kind `design`), layout.layout_box/minimum_box/design_decoration, validator box rules, prototype design root, background 2x fallback, compiler via Layout; tests/data/designed_spec.json (1440 x 1312, synthetic footer) + tests.
- Checks: Done-when pytest set PASS (354; review-fix tests rerun PASS); live 12-component budget PASS (1.22 s); `uv run dsengine validate` (../engine) on the designed recipe exit 0; Test (all) `uv run pytest` PASS (1507 passed, 12 deselected; one earlier run hit the known 100 ms feasibility timing flake, passed 3/3 isolated and in the serial rerun).
- Decisions: None box/design omitted on dump (code-laid spec.json bytes unchanged). Designed page: component grid ignored (fallback), boxes checked (inside page, no overlap, catalog min px at canvas width, footer via synthetic_errors). Design.source free string ("designer"/"revise"). Prototype: code CSS in `@scope (#dss-canvas) to (.dss-design)` only when a rendered page is designed; design root div `all:initial;isolation:isolate` at page rect holding design_page.wrap(sanitize(html, page=n, fonts=(theme font,))), drawn before other decorations. write_pages returns {name: scale}; trace recording of a 2x drop left to 20.3 (nodes/render.py). No test pinned width 1200 for the If.
- Digest: spec.models Box{x,y,w,h}, Design{html,source,model}, Page.design, Component.box, Canvas.width 1200-1920; layout.layout_box(spec,page,item), design_decoration(n,height); background.write_pages->{name:scale}, LIMIT; fixture tests/data/designed_spec.json
- Tried and failed: none
- Gotchas: designer z-index escaped the design root until `isolation:isolate`; revise context dumps spec incl. design.html (20.4 budget).
- Left open: P3 layout.minimum_box duplicates design_page.minimum - src/dss/spec/layout.py; P3 2x fallback file not re-checked against LIMIT - src/dss/render/background.py; P3 code-laid specs may validate at widths 1201-1920 - src/dss/spec/models.py
- Next: Task 20.3. Start by `status`; build designed specs with design_decoration + measured boxes, record write_pages scales in the trace.

## 2026-10-22: Task 20.3 Designer node in the prototype action
- Status: done
- Plan check: off
- What changed: nodes/designer.py (design(): page 1, then pages 2-n via gather; one repair; per-page and page-1 fallback; re-validate), accept calls it after layout when Config.designed_pages; context.designer_context + designer budget 12k; PLANNER_NODES adds designer; render span records background_2x; prompts/v1/designer.md, skills/dashboard-design.md; tests.
- Checks: `uv run pytest tests/test_designer.py tests/test_graph.py tests/test_context.py tests/test_render.py` PASS (98); Test (all) `uv run pytest` PASS (1523 passed, 12 deselected); one live gemini-4-argon page-1 call: schema + LOW thinking accepted, 1 repair then designed at 1440, 57 s, 6476 in / 2175 out tokens.
- Decisions: designer calls BaseLlm.generate_content_async directly inside the prototype code node (one Workflow/trace), adds usage to trace + run.usage, sets trace.model. Schemas FirstPage{canvas_width 1200-1920, html} / LaterPage{html}, extra forbidden. Code prepends page 1's sanitized CSS (root written `body`) to later pages. Provider error, missing key, over_budget, unsafe -> immediate fallback (no repair); empty or MAX_TOKENS-cut answers get the repair. Repair sends the model's own html + up to 20 errors. Spans carry counts only: designer{page,attempt,tokens}, validate{page,attempt,errors}, designer_fallback{page,reason,errors}. Pages whose decorations a ledger requirement names stay code-laid (keep) until 20.4 checks design.html. Fallback message: "Page n uses the standard layout..." / ALL_FALLBACK.
- Digest: nodes/designer.design(spec, get_model, trace, *, secrets, report, keep)->(spec, notes); FirstPage/LaterPage; assemble(spec, results, model); context.designer_context(design, page, *, shared, repair), PAGE_HEADER; Config.designed_pages; test_designer.DesignerLLM, designed_flow
- Tried and failed: none
- Gotchas: added the designed_pages default-on test-flow note to AGENTS.md.
- Left open: none
- Next: Task 20.4. Start by `status`; regenerate a page with designer_context(..., repair-like previous html + comments) and drop the `keep` gate once design.html verifies decoration requirements.

## 2026-10-22: Task 20.4 Revise regenerates designed pages
- Status: done
- Plan check: off
- What changed: revise routes comments on designed pages per class (redesign vs patch); designer.regenerate redesigns pages from previous HTML + comments; coverage proves `p<n>_design` rows by text/hex presence in design.html; context.designer_context gains `revision=` (outside Files: the designer context and its 12k budget live there); tests.
- Checks: `uv run pytest tests/test_revise.py tests/test_designer.py tests/test_feasibility.py` PASS (263); Test (all) `uv run pytest` PASS (1542 passed, 12 deselected); new budget test: 40 design-bound rows coverage on the designed 3-page spec < 100 ms.
- Decisions: Class from the reviser's patch ops on a designed page: grid/box ops dropped + redesign; root remove/replace and label ops kept + redesign; other ops = data patch; type change whose new design_page.minimum exceeds the box redesigns. Comments on `p<n>_design` skip the reviser (all-design batch: no reviser call). Patch phase (with its one repair) runs first, excusing box errors and rows bound only to waiting `p<n>_design`; then one regenerate per page (gather, LaterPage schema, spec width), then full validate + coverage; failure = RunError invalid_request "...comments stay pending (page n: errors)", spans redesign_failed{page,reason,errors}. Design.source "revise"; decisions record redesigned_page. Non-string decoration values (sizes) are not provable in design.html. render.accept `keep` gate kept (kit-decoration rows still need it).
- Digest: designer.regenerate(spec, {page: [comment]}, get_model, trace, *, secrets, report)->(spec|None, {page: Fallback(reason, errors)}); designer.readable collapses icons; revise.redesigns(records); requirements.design_html(snapshot); payload['_designer'] getter
- Tried and failed: passing `redesign=` into revise.revised broke the live observe_revisions wrapper (reviewer P2); records carry it instead.
- Gotchas: added the observe_revisions signature line to AGENTS.md.
- Left open: P2 icon/card-color comments on a component (not on p<n>_design) get no redesign route - src/dss/harness/nodes/revise.py; P3 stale keep comment - src/dss/harness/nodes/render.py; P3 revision repair turn carries two HTML copies (budget) - src/dss/harness/context.py
- Next: Task 20.5. Start by `status`; live designed dashboard (STOP: user approves pages vs the reference).

## 2026-10-23: Task 20.5 Live designed dashboard
- Status: done
- Plan check: off
- What changed: live test_designed_dashboard_sample_csv (tests/live/test_backend_flow.py); designer prompt/skill: canvas_width 1200, no repeated component labels (cards hold the slot only, filters in slim header cards). Outside Files (reasons below): context.capability_context drops pages[].design; capability_check.md geometry-comment rule; revise LOW thinking; tests.
- Checks: `uv run pytest -m live tests/live/test_backend_flow.py -k designed` runs 10+11 PASS consecutively (1200 wide; no fallback; designer calls 6.5-44.4 s, in <= 3.7k, out <= 1.2k, thinking 0; move comment redesigned page 2, chart y 811->175 / 510->116). Real engine on run 10 recipe: ok 37/0 failed, every set_canvas/set_background_image ok; report 7e88e3a5…, charts inside cards. Crops ../data/report-quality/backend-20.5-{p,report-p}<1-3>.png; user approved look (STOP). Test (all) `uv run pytest` PASS 1544.
- Decisions: Engine limit: canvases > ~1380 px get editor zoom-to-fit, engine misplaces all components (run 4 at 1560: 23 failed) -> user chose prompt "use 1200" over blocking; test asserts width <= 1380. capability_context omitted design.html (15.5k > 12k blocked every comment). Live extractor gave move comments no need -> capability_check.md rule (target's own capability + existing fields). Reviser default thinking overran the 30 s worker deadline 3/7 runs -> LOW (user chose). Test drops unresolved issues with no alternative.
- Digest: tests/live/test_backend_flow.py: test_designed_dashboard_sample_csv (DSS_LIVE_KEEP=1 keeps BQ tables), time_designer(monkeypatch, calls), designed_trace(app, run_id), ENGINE_WIDTH=1380. Designer prompt asks canvas_width 1200; capability_context omits pages[].design.
- Tried and failed: 1440/1560 canvases with the real engine (editor zoom); "no new fields" wording made time_series moves needs_clarification.
- Gotchas: added engine canvas-width and DSS_LIVE_KEEP lines to AGENTS.md. Run 10's BigQuery source/view kept so the approved report renders.
- Left open: engine placement on canvases > 1380 px (program root question; architecture still says 1200-1920).
- Next: none in plan.md (70/70); final audit by the architect.

## 2026-10-23: Change recreate publication
- What changed: the architect, at the program root, added Phase 21 task 21.1 (coverage errors in the publish span; recreate and screenshot-only accepts publish with designed pages on and off) and a Designed pages coverage-fallback rule in architecture.md (+ decision row, essentials, stamp).
- Why: release 2.5 (2026-10-23): recreate and synthetic accepts fail publish coverage on 4 builds (b_7ca302e800cc, b_48ef72ff1bff, b_52b7b7be7e02, b_dfb67c24f176) with the `errors` list not visible; style mode publishes; 18.1 and 18.2 confirmed working live. User chose this fix (card); deadline no longer binding (program.md).
- Tasks affected: 21.1 (new); release 2.5 and 2.6 `Needs: backend 21.1`.

## 2026-10-23: Task 21.1 Recreate and screenshot-only builds publish with designed pages
- Status: done
- Plan check: off
- What changed: requirements.observed_labels (code titles an observed chart with its screenshot title), applied in render.accept before the designer; _date_bucket strips SQL; non-comment sources drop non-spec component_ids; publish span `coverage_errors`. Fixture tests/data/recreate_designed.json + 4 tests in test_render.py.
- Checks: `uv run pytest tests/test_render.py tests/test_feasibility.py tests/test_designer.py tests/test_references.py tests/test_api_contract.py` PASS 319; Test (all) `uv run pytest` PASS 1548. New tests fail 4/4 with src/ stashed.
- Decisions: Cause (replay of copies of the 4 builds; designed pages off failed the same): extractor `label` properties vs planner titles ("Total Revenue"), `DATE_TRUNC(order_date, MONTH) ` trailing space, image rows citing `o2` as component id. Not designer, so the Designed-pages coverage fallback (`designer_fallback` reason coverage) is NOT built. Titling applies only if the titled spec's coverage errors are a strict subset and validate_spec passes; layout span `observed_titles: n`. Span errors: secret-filtered, cap 20, same list as RunError. AGENTS.md: diagnosis gotcha.
- Digest: requirements.observed_labels(snapshot, ledger, checker)->{cid: label}; coverage_errors(..., titles=None); publish span coverage_errors [{path,message}]<=20; layout span observed_titles; test_render.recreate_build(..., data, synthetic, designer, designed)
- Tried and failed: none
- Gotchas: b_48ef72ff1bff and b_dfb67c24f176 still fail publish after the fix: genuine plan gaps (Blueprint has no month bucket field; bar where the screenshot shows a table). Feasibility says ready because nothing checks Blueprint rows against observations before accept, and the blueprint planner doesn't see the observations.
- Left open: P3 Blueprint doc keeps planner titles while the prototype shows observed ones, no note - render.py; P3 observed_labels guards (strict subset, claimed, validate fail) untested - requirements.py; P3 same-metric observations titled first come first served - requirements.py.
- Next: release 2.6 (program root) re-runs the live recreate flows.

## 2026-10-23: Audit (final)
- Verdict: DEFECTS - one P1 (graded by the architect, user agreed on a card). Re-audit of 16.1, 17.1, 18.1, 18.2, 19.1-19.4, 20.1-20.5, 21.1 since the 2026-10-21 final audit. Read-only reviewer (opus, high): no P0/P1; sanitizer allowlist, JS-off/no-network measure, re-sanitize at render, 21.1 strict-subset titling, 18.1/18.2 gates, dependencies, ISC licence and secrets clean.
- P1: recreate observations never reach the Blueprint planner (context.blueprint_context has no observations section) and Blueprint feasibility never checks rows against them, so b_48ef72ff1bff (monthly series, no month bucket) and b_dfb67c24f176 (table observed, bar row) show ready and then fail accept with 422 and no recovery (21.1 Gotchas; PRD goal 6 gate at blueprint) -> task 22.1 (M). Second audit-fix phase in a row: the user accepted the cost (one build session + re-audit).
- Checks: Test (all) `uv run pytest` PASS (1548 passed, 13 deselected, 690.8 s). Done-when files of every task since the last audit in one serial run (17 files: feasibility, render, compiler, api_contract, research, blueprint, spec_validate, recipe_contract, publication, references, capabilities, revise, design_page, layout, designer, graph, context) PASS 874 (53 ERROR log lines are expected-failure node logs). `dsengine validate` (../engine) on the designed_spec recipe and the golden recipe: exit 0. Live `-m live`: 12/13 PASS incl. 20.5 designed dashboard, 19.3 background budget (real_background_dimensions, twelve_component), GPS union, context/outline, synthetic; FAIL test_staged_flow_sample_csv StopIteration at tests/live/test_staged_flow.py:250: superseded by 20.3/20.5 (designed pages default: page 1 has a `design` decoration, not band/panel/title; the flow reached prototype), stale test listed in PRD Later. Secrets: `git log --all` of *.env and tracked .env: none.
- Skipped: real-engine Data Studio runs of 19.1-19.3 and 20.5 (signed-in engine Chrome; user approved those STOPs; release 2.6 replays live), isolated uvicorn health (startup path covered by TestClient; unchanged commands).
- Docs: architecture.md adds Core logic "Blueprint observation coverage" (22.1's spec) and the Blueprint input line; Designed pages states the prompt asks width 1200 (engine misplaces > ~1380 px) and that the coverage fallback is specified but not built (21.1 found titles/SQL/ids, not designs); Recreate definition reconciliation records 21.1's observed_labels rule; three decision rows. Essentials updated and trimmed to one page; stamp PASS. PRD goal 9 width note; Later gets the width clamp (P2), stale live test, 20.4 icon/card-color redesign route (P2), and the grouped P3/left-open items of 16.1-21.1 plus the engine s021/canvas items. AGENTS.md: engine-zoom gotcha moved into the docs, b_a8ace098d03b replay stall dropped (engine-side, in Later), timing flakes merged, block end marker moved below the gotchas it had left outside. plan.md: Phase 22, task 22.1.
- Decisions: P2 width and P3s are known limitations (POC bar), not tasks. 22.1 Spec points at the new section plus Recreate definition reconciliation (Blueprint section reachable by recall).
- Mechanical checks: lint 0 errors, 10 historical warnings (task count, older Spec sizes, PRD size); essentials <= 6,000 chars; AGENTS.md < 8,000.
- Next: build 22.1 in a fresh builder session, then backend re-audit; release 2.6 from the program root after ACCEPTED.

## 2026-10-23: Task 22.1 Blueprint feasibility covers recreate observations
- Status: done
- Plan check: off
- What changed: feasibility.diagnostics checks every recreate observation (image and instruction records) against Blueprint rows with publish coverage's own checks; gaps become `code: observation` Issues on the nearest row (joined to the one row repair) with code-built `observed_type` / `date_bucket` alternatives; blueprint context gets an `observations` section. Fixture tests/data/recreate_blueprint_gaps.json (+8 tests across render/feasibility/context).
- Checks: Done-when pytest set PASS 372 passed; Test (all) `uv run pytest` PASS 1562 passed, 13 deselected. New gap tests fail on pre-fix src (git stash). 24 observations: ready ~37 ms, all-gaps ~40 ms at normal load (74 ms min under 2x machine load).
- Decisions: Observations = current recreate reference's image + instruction records (coverage checks both), minus dropped/retired/layout-only/own-unresolved-issue; stale ones stay (evaluate blocks them). Rows laid out by auto_layout._component, emulated compiler ops, Blueprint derived fields for buckets (`_date_bucket(..., derived=)`), observed_labels titling mirrored (first free row, all-or-none label validity). component_ids or non-label properties -> needs_clarification "cannot be checked against Blueprint rows" (If-clause case). Alternatives only when recomputed coverage fulfils it and keeps all others; bucket `<date>_<grain>` = DATE_TRUNC/DATETIME_TRUNC/TIMESTAMP_TRUNC, view_table reset for the accept dry run; no view-builder change. Drop = requirement-level `slot: unknown` drop in ledger.decisions (`source_id`, `issue_id`), rows kept, `drop_questions: []`. Rows replaced in place (`replace`), derived deduped by name. Prompt v1 unchanged (instruction in the section header, so data-mode prompt bytes unchanged). Section kind `reference`, compact form drops labels. Catalog read once per diagnostics pass (85 -> 37 ms). 21.1 publish-span test now patches observation_errors out to reach the 2.5 path. AGENTS.md: 3 gotchas.
- Digest: req.blueprint_observations(snap,ledger,checker)->[(r,needs,props)]; req.observation_coverage(..,components,derived,palette); feasibility.coverage; bp issue code 'observation' (requirement_id; offers observed_type/date_bucket); tests/data/recreate_blueprint_gaps.json
- Tried and failed: omitting user-dropped items from the fixture renumbered item ids; replaying the user's drops through the API instead.
- Gotchas: none beyond AGENTS.md.
- Left open: P3 titling mirror lacks observed_labels' `after < before` recheck and uses row order, not spec page order - src/dss/spec/requirements.py; P3 fallback gap text names a title claim when the cause is an op/option/label failure - src/dss/spec/feasibility.py
- Next: backend re-audit (architect), then release 2.6 from the program root.

## 2026-10-23: Audit (final) re-audit of 22.1
- Verdict: ACCEPTED - no P0/P1. Re-audit of task 22.1 only (the one audit-fix task since the earlier 2026-10-23 final audit). Read-only reviewer (opus, high): invariant "Blueprint ready => accept coverage passes" holds on every traced path (same checks, layout and skips as publish coverage; uncheckable observations -> needs_clarification); no automatic drop/rebind, publish coverage not relaxed, 18.1 freshness intact, no added model call or repair, only reconciled meaning in an untrusted context section; every Done-when clause has a test; no Non-goal built, no API/contract change, no dependency change.
- Checks: 22.1 Done-when set (blueprint, feasibility, render, context, references, api_contract) PASS 372 passed. Test (all) `uv run pytest`: first run 1 failed / 1561 passed (812 s; test_recreate_blueprint_recompute_speed_with_24_observations, min of 3 > 100 ms under load while the reviewer ran); the test passed 3/3 in isolation; serial rerun with nothing else running PASS 1562 passed, 13 deselected (619 s). Timing flake per AGENTS.md, not a defect. Secrets: `git log --all` of *.env / *.env.*: none; no tracked .env. 22.1's commit stays inside its Files.
- Skipped: live `-m live` (22.1's Done when is offline; the earlier final audit ran the live set; release 2.6 replays recreate live from the program root); earlier tasks' Done-when files beyond the 22.1 set (Test (all) covers them, 22.1 touched only the listed modules).
- Docs: architecture.md Blueprint observation coverage gains a "Built (task 22.1)" line (instruction records too, uncheckable -> needs_clarification, alternatives only when recomputed coverage keeps every observation, drop as a requirement-level ledger decision); Implementation conventions: read the catalog once per feasibility pass. AGENTS.md: 22.1's three gotchas moved inside the block (they were after the end marker), the catalog one moved to architecture.md, the ContextLLM lines merged, the Uvicorn line dropped (already in architecture.md); 7,994 chars. PRD Later: 22.1's P3s (titling mirror order, fallback gap text, gap with no nearest row). Essentials unchanged; stamp PASS.
- Decisions: the reviewer's three P3s and 22.1's two Left open items are known limitations (POC bar), not tasks.
- Mechanical checks: lint 0 errors, 10 historical warnings.
- Next: backend done for v2.6; release 2.6 from the program root (open a session at the repo root).

## 2026-10-23: Change live report defects (program)
- What changed: plan.md Phase 23: 23.1 (S, time series on date buckets carry `date_granularity`), 23.2 (S, synthetic label drawn once, by the background); architecture.md#Recipe compiler and #Synthetic data + two decision rows; essentials recipe 1.2. Contract recipe.md 1.2 changed at the root.
- Why: release 2.5's approved comparison: `order_date_month` drawn per day in the live report (b_36f20b42159c s015, b_91869163c217 s016); "Synthetic sample data" drawn twice on b_91869163c217 page 1 (background label + compiler `add_text` s010).
- Side effect: tests/test_capabilities.py fails 2 tests (registry surface, option values) until 23.1 adds `option.time_series.date_granularity`.
- Affected: backend 23.1, 23.2 (new); release 2.6 `Needs:` both; release 2.7 flips its e2e recipe-label check after 23.2. The final audit's ACCEPTED verdict covers tasks to 22.1 only.

## 2026-10-23: Task 23.1 Time series on date buckets carry their granularity
- Status: done
- Plan check: off
- What changed: spec DataField.date_granularity (optional, omitted when None); auto_layout.bucket_grain parses a Blueprint derived field's whole DATE/DATETIME/TIMESTAMP_TRUNC call and spec_value sets the grain on date-typed view fields; compile_recipe drops model `date_granularity` options and sets it only on a time_series whose date_dimension field has a grain. capabilities.json `option.time_series.date_granularity`. +27 tests (compiler, layout).
- Checks: `uv run pytest tests/test_compiler.py tests/test_capabilities.py tests/test_recipe_contract.py tests/test_layout_auto.py tests/test_feasibility.py` PASS 292; Test (all) `uv run pytest` PASS 1599 (13 deselected); test_compiler + test_layout_auto rerun after review test edits PASS 47.
- Decisions: grain set in auto_layout (no If-clause case: revise is component-scoped, New version copies the spec). Parser: balanced tokenizer, plain grain only (WEEK(MONDAY)/ISOWEEK/HOUR -> none), 3rd arg only for TIMESTAMP_TRUNC; view type must be DATE/DATETIME/TIMESTAMP. Product evidence: time-series-reference. Golden spec has no bucket: golden_recipe.jsonl unchanged.
- Digest: spec.models.DataField.date_granularity day..year|None (absent in JSON when None); auto_layout.bucket_grain(sql)->grain|None; compiler emits add_chart.options.date_granularity only for time_series on such a field, drops model ones.
- Tried and failed: none
- Gotchas: existing builds (b_36f20b42159c, b_91869163c217) keep grain-less specs until their Blueprint is re-accepted: "Run recompiles the current spec".
- Left open: P2 registry offers/accepts code-owned date_granularity; requirements._row_ops/_component_fulfills read component options, not the spec field grain, so feasibility can disagree with the compiler - src/dss/spec/requirements.py; P3 second TRUNC parser beside requirements._date_bucket - src/dss/spec/auto_layout.py
- Next: Task 23.2. Start by `status --task 23.2`.

## 2026-10-23: Task 23.2 Synthetic label drawn once
- Status: done
- Plan check: off
- What changed: compiler.compile_recipe no longer emits the page-1 `add_text` for `p1_synthetic_sample_data`; background_p1.png (decoration layer) is the report's one copy of "Synthetic sample data". require_synthetic_label still guards compile. Tests: test_synthetic_label.py (recipe has no label op, page-1 set_background_image kept; real Chromium PNG footer pixels == decoration-layer label for code and designed layouts; golden real-data recipe unchanged), test_render.py recreate accept, test_compiler.py.
- Checks: `uv run pytest tests/test_synthetic_label.py tests/test_render.py tests/test_compiler.py` PASS (114 passed, 2 deselected; new tests failed before the change); Test (all) `uv run pytest` PASS (1601 passed, 13 deselected).
- Decisions: edited tests/test_compiler.py (outside Files): its two label tests asserted the removed op; now assert no label op. No If-path fix needed: designed, revision and copied-version paths already draw the label in the background (existing tests assert it).
- Digest: compile_recipe emits no op for SYNTHETIC_LABEL_ID; background_p1.png is the label's only report copy. test_synthetic_label.assert_background_only_label(recipe_lines, spec), designed() fixture loader.
- Tried and failed: none
- Gotchas: golden_recipe.jsonl is version 3 (compile_recipe(golden, 3)); golden_spec has a logo, so write_pages needs its asset folder.
- Left open: P3 real-data background check restates write_pages - tests/test_synthetic_label.py; P3 recreate test compiles a fresh recipe rather than reading a published one - tests/test_render.py
- Next: release 2.7 updates e2e_references.py recipe-label check; backend plan complete.

## 2026-10-24: Change reference fidelity (program root)
- What changed: contracts/recipe.md 1.3, conventions.md 1.3 (DSS_ALLOWED_TYPES default adds area, fixed_size_list); docs/architecture.md Designed pages (Reference, Art, budget note), Capability verification (24k in / 8k out, trimmed comment ledger, active-issue count, named refusals), Recipe compiler (base DATE grain, recipe 1.3 types), Prototype renderer (new types), Dependencies (Natural Earth 5.1.2, public domain, verified 2026-10-24), four decision rows; essentials restamped; plan Phase 24: 24.1 recipe 1.3 types (M), 24.2 base DATE grain (S), 24.3 comment check limits (M), 24.4 static globe art (M), 24.5 designer sees the reference (M, STOP).
- Why: user audit of release 2.6 (b_697880743b4f, b_7beb08e5076c traces): the screenshot reached only reference_extract on the worker model (gemini-3.8-flash; 4,096 output, <= 24 items); the designer (gemini-4-argon) got title, theme and slot ids only (~3-4k in, 769-3,002 of 16k out) under a skill that forces a light KPI-row page, so the globe came out as blobs while Argon shown the image directly recreated it (electricity-dashboard.html, 135 KB, 122 KB of it inline script/world data the sanitizer strips); capability_check refused at 12.7k of its 12k input budget (one output 3,839 of 4,000), blocking "enlarge the globe"; Data Studio has a fixed-size list, area chart and 100% stacked bar natively but recipe 1.2 had none; s011 breakdown colors timed out and yearly DATE charts spiked. User chose on cards: image to Argon, reference wins, static globe art, recipe 1.3 (fixed-size list, area, 100% stacked), trim + 24k comment check, plan both 2.6 block fixes; the cap warning was not chosen.
- Tasks affected: 24.1-24.5 new. tests/test_capabilities.py now fails 2 tests (registry surface, option values) on the 1.3 schema until 24.1 adds the records, so 24.1 goes first.
- Next: build 24.1 in backend/.

## 2026-10-24: Task 24.1 Recipe 1.3 types: area, 100% stacked bar, fixed-size list
- Status: done
- Plan check: off
- What changed: area and fixed_size_list in models, catalog, registry (6 records app-supported) and compiler; area shares the time-series date grain; prototype draws filled/100 % areas, 100 % bars, an unchecked checkbox list.
- Checks: `uv run pytest tests/test_capabilities.py tests/test_compiler.py tests/test_render.py tests/test_spec_validate.py tests/test_recipe_contract.py` PASS 402; Test (all) `uv run pytest` PASS 1633; screenshots .blueprint/qa/task-24.1/{percent,stacked,plain}.png checked.
- Decisions: outside Files for Blueprint rows: capabilities, feasibility, nodes/blueprint, requirements use FIELD_CONTROLS/DATE_AXIS_TYPES; 4 tests retargeted (TYPES != golden's 12; fixed_size_list no longer app-unsupported). Minimums: area = time_series, list = dropdown width x 4 rows. 100 % = value / sum(abs) per x, non-numeric -> gap; list sorted ascending; LIST_CSS only with a list. AGENTS.md: .env gotcha.
- Digest: models.CHART_TYPES/CONTROL_TYPES/TYPES +area,fixed_size_list; FIELD_CONTROLS (field=one Blueprint dim); DATE_AXIS_TYPES share options.date_granularity; option stacked_percent bar/area; test_render.recipe_13_spec(area_options,bucket); test_compiler.RECIPE_12_BYTES
- Tried and failed: none
- Gotchas: root .env DSS_ALLOWED_TYPES is pre-1.3: the app rejects the new types until .env adds them.
- Left open: P3 KPI grain inheritance only for chart.time_series - src/dss/spec/requirements.py:870; P3 slim designer filter slots fit no list - skills/dashboard-design.md:25; P3 list shows null as 'null', dropdown 'None' - src/dss/render/prototype.py; skills/reference-extract.md candidates lack the new types.
- Next: Task 24.2. Start with `status`.

## 2026-10-24: Task 24.2 Base DATE columns on bucket starts carry their grain
- Status: done
- Plan check: off
- What changed: profile_table adds one `MIN(CASE ...)` aggregate per non-REPEATED DATE column -> column `bucket_start` month|quarter|year|None; auto_layout.base_grains maps view fields to profiled source columns and spec_value records the grain on DATE fields; accept passes `sources=connected`. +10 tests, release 2.6 spec/recipe fixtures.
- Checks: `uv run pytest tests/test_profile.py tests/test_compiler.py tests/test_layout_auto.py` PASS 70; new tests failed before (9/9 with src stashed; wiring test fails without render.py kwarg); Test (all) `uv run pytest` PASS 1642 (13 deselected) before review fixes; rerun after: 1642 passed, 1 failed = test_recreate_blueprint_recompute_speed_with_24_observations timing flake (109 ms vs 100), PASS alone. Live read-only profile of release 2.6 source: `year` -> year.
- Decisions: outside Files: render.py (accept passes sources; the only layout caller), models.py comment. Join = first source's column, union = finest common grain. Fixtures tests/data/release_2_6_{spec.json,recipe.jsonl} with project renamed `sample-project`. prompt_text unchanged.
- Digest: profile column `bucket_start` ('month'|'quarter'|'year'|None, DATE only, absent on old profiles); auto_layout.base_grains(sources, view_sources)->{field: grain}; layout/spec_value(..., sources=()) set DataField.date_granularity on base DATE fields.
- Tried and failed: none
- Gotchas: existing builds keep grain-less specs until re-intake and re-accept (old profiles lack the fact).
- Left open: none
- Next: Task 24.3. Start by `status --task 24.3`.

## 2026-10-24: Task 24.3 Comment checks fit a long build
- Status: done
- Plan check: off
- What changed: capability_check budget 24k input / 8k output; a pure comment batch sends rows bound to its targets + unbound rows, merges only those, keep_unsent restores the rest; issue cap counts active issues only; refusals name limit + size. New live test tests/live/test_comment_checks.py (outside Files: Done-when live check).
- Diagnosis (backup copy, mode=ro): b_697880743b4f's last batch m_cd05a55f0af1 (p1_design globe) hit the input budget: request_tokens 12,728 > 12,000 (estimate 10,290; model never called). Sections: prompt 1381, skill 150, registry 1755, requirements.json 2272 (6 rows; trimming sends 4), metadata 3938, sources 93. Output/issue limits didn't fire.
- Checks: `uv run pytest tests/test_capabilities.py tests/test_feasibility.py tests/test_context.py` PASS 235 (one earlier run 1 failed/234, unreproduced, likely timing flake); 16 new/updated tests fail on old src; Test (all) `uv run pytest` PASS 1649; live `-m live tests/live/test_comment_checks.py` PASS (5m28s): 8 comments all ready, ledger 2->9 rows, capability_check request_tokens 10478, 10883, 11254, 10863, 10980, 11348, 11725, 12059 (sent/kept rows 1/0..4/4); evidence .blueprint/qa/task-24.3/comments/20261024-215826-bbbc0687.
- Decisions: labels "Comment check"/"Requirement check"; messages e.g. "Comment check input 26,140 tokens, over its 24,000 budget", "... output reached its 8,000-token limit (N tokens reported)", "21 active issues, over the 20-issue limit; drop or clarify some requests, then check again". assemble/fit_request RunError detail adds tokens/budget. Assessment.issues lost max_length (no contract cap). Merge on trimmed ledger (review P2: full merge could absorb a definition into an unsent row, then lose it). Span keys ledger_rows_sent/kept. AGENTS.md gotcha added.
- Digest: BUDGETS['capability_check']=24000, capability_check.MAX_OUTPUT_TOKENS=8000; req.sent_requirements(ledger, incoming)->rows; req.keep_unsent(before, after, sent)->Ledger; evaluate caps unresolved issues only; capability_check span ledger_rows_sent/kept.
- Tried and failed: live comment sets with vague design / title-font-size comments (correctly refused, not scope).
- Gotchas: none beyond AGENTS.md.
- Left open: P3 count refusal's "existing + extracted" may not sum past 40 after merges - src/dss/harness/nodes/capability_check.py
- Next: Task 24.4 Static globe and world art.

## 2026-10-24: Task 24.4 Static globe and world art
- Status: done
- Plan check: off
- What changed: scripts/make_art.py (stdlib orthographic + Equal Earth) writes src/dss/render/art/ (3 globes, world, NOTICE) from Natural Earth 110m v5.1.2 (user-approved download, kept outside git). design_page: `<i data-art>` allowlist, art(), wrap() inlines art, measure errors; designer context lists art; skill Art section.
- Checks: make_art on the real GeoJSON: 58,029 / 40,397 / 43,559 / 73,029 bytes, sha256-identical rerun; `uv run pytest tests/test_design_page.py tests/test_designer.py` 57 passed (6 new art tests failed before); `uv run pytest` 1656 passed (an earlier overlapped run had 1 timing flake in test_feasibility, passed alone). Globe fixture 3x PNG 355,260 B; sanitize+measure+background 2.86 s.
- Decisions: art stays an empty `<i data-art="name">` in sanitized/stored HTML (children, data-icon dropped; name normalized to [A-Za-z0-9_-], max 80); wrap() inlines it, adding ART_CSS only when art is present (other designed prototypes keep their bytes), so design.html, readable(), coverage and comment metadata stay art-free. Art inside a slot: the sanitizer records it, measure reports it at `slots.<cid>`; over a slot: graphics overlap with an art message. Codes: ISO_A3, else ISO_A3_EH, else ADM0_A3 (France/Norway are -99). Continent class = CONTINENT slug (Seven seas -> seven-seas). Centres 15E 20N, 75W 10N, 115E 10N; viewBox 500, r 249; hidden runs become rim arcs (<=90 degrees each) that follow the hidden path's sweep. world.svg: Equal Earth without Antarctica, viewBox 0 0 1000 442. Default fills #CBD5E1 land, #F1F5F9 ocean. tests/test_context.py (outside Files) updated: it pins the designer section list. Review P2 fixed: a Chromium isPointInFill probe test that fails on a flipped sweep flag or reversed rim step.
- Digest: design_page.art()->{name: svg}: globe-europe-africa, globe-americas, globe-asia-pacific, world; sanitize keeps empty `<i data-art>`, wrap() inlines it; paths `land <continent> c-<ISO3>`; context section 'art'; scripts/make_art.py; tests/data/designed_globe.html
- Tried and failed: none
- Gotchas: none beyond AGENTS.md
- Left open: P3 no limit on the number of art tags per page (each inlines 40-73 KB) - src/dss/render/design_page.py
- Next: Task 24.5 The designer sees the reference. Start by reading designer.design/regenerate and context.designer_context for where image parts and the reference summary go.

## 2026-10-25: Task 24.5 The designer sees the reference
- Status: partial (STOP pending; uncommitted work in the tree)
- Plan check: off
- What changed: designer.reference(folder)->Reference(images ((mime, bytes),...), notes {mode, summary, palette, type, spacing}); design()/regenerate() take reference=; every request: REFERENCE_TASK text, then inline images; span images: n. context.designer_context(reference=notes): droppable 'reference' section; prompt + skill end with a `## Reference` part, stripped without a reference. render.py accept and revise.py redesign pass designer.reference(folder) (outside Files: designer has no folder).
- Checks: 8 new tests in test_designer/test_context fail on old code, pass; `uv run pytest` 1662 passed, 2 failed (revise 100 ms timing, agent_client) both pass alone and on file rerun. Live (.blueprint/qa/task-24.5/live_245.py, style, CSV eb6e5770): run 1 faked a split bar/slider; skill tightened ("Nothing fake", match slots by meaning); run 2: 3 pages, images: 1, no fallback, p1 out 1,974/16k; ../data/report-quality/backend-24.5-reference.png.
- Decisions: no-reference requests byte-identical (test pins sha256 c42eceff...); notes exclude observation items and instructions; unreadable/unnamed image files skipped.
- Tried and failed: none
- Gotchas: style mode imports no charts, so the reference's slider/split bar/list have no slots.
- Left open: review not run.
- Next: show the user .blueprint/qa/task-24.5/reference/20261025-001939-30a57d57/side-by-side.png for the STOP; optionally `DSS_245_MODE=recreate uv run python .blueprint/qa/task-24.5/live_245.py`; then review, record, done, commit.

## 2026-10-25: Task 24.5 The designer sees the reference
- Status: blocked
- Plan check: off
- What changed: nothing committed. The built work (reference images and notes in every designer request, a Reference section in the skill and prompt, render.py/revise.py passing designer.reference(folder)) is set aside: `git stash apply 75157888f8d9a04a22ea136e00aa018cdb21a6cd`.
- Checks: before the restore: 8 new tests PASS; `uv run pytest` 1662 passed, 2 timing flakes that pass on rerun. Live style run 2: 3 pages, images: 1, no fallback, p1 out 1,974/16k; .blueprint/qa/task-24.5/reference/20261025-001939-30a57d57/side-by-side.png. Review not run.
- Decisions: STOP not approved; the user chose block + re-plan over approve + change request.
- Tried and failed: one-stage designer with the image (style mode) follows the reference's regions, but the slider, split bar and small multiples are missing (no slots).
- Gotchas: AGENTS.md (style mode slots).
- Left open: review.
- Blocked because: (b) needs a plan/architecture change: the user wants a two-stage "perfect recreation" route.
- Question: Should a reference build first run feasibility, then send Argon the feasibility report (available charts, filters), recreate instructions and the image to write a recreation prompt (like ../electricity-dashboard-prompt.md), and have Flash 3.8 code the page HTML from that prompt?
- Options: A yes, as new tasks built on the stash (Argon still needs its image parts and no-reference guard) / B yes, replacing the stash / Recommend: A. Limits: HTML stays a sanitized static background with slots (no scripts or d3); Flash's 30 s deadline vs up to 16k of HTML; 12k input budget.
- Next: run /blueprint-solution-architect to resolve 24.5's block.

## 2026-10-25: Architect clarification for blocked 24.5
- Status: awaiting scope answers; 24.5 remains blocked.
- What changed: this planning checkpoint only; no product code, task markers or architecture changed.
- Evidence: status reports 78/79 done. Read 24.5 and its two progress entries, architecture essentials, Designed pages, PRD and dashboard-intent contract; inspected model routing and context limits. The requested Argon brief -> Flash HTML route is recorded in the block. Style mode borrows treatment and supplies no reference-owned chart slots; switching model stages cannot itself add those components. PRD excludes pixel-identical clones and custom chart engines; closest supported recreation is explicitly a user decision. Current worker deadline is 30 s; designer budget is 12k input / 16k output with a 120 s planner deadline.
- Proposed direction (not accepted): preserve reusable image transport and no-reference guards from the recorded stash when the builder resumes; use feasibility-approved component slots as the binding input to the two-stage reference path. Keep no-reference behavior unchanged. Clarify fidelity scope before specifying this path; recommend native supported recreation with explicit substitutions and a 120 s deadline only for the Flash HTML node, retaining the 16k output cap.
- Checks: blueprint status and targeted document/source inspection only; no tests run (planning checkpoint).
- Left open: whether "perfect recreation" stays within native supported components or requires broader rendering scope; whether the Flash HTML node may use a 120 s deadline. The existing visual STOP remains unapproved; the stash has not been applied or verified.
- Next: obtain these answers, then update the backend plan and architecture or route a cross-part scope change to the program root.

## 2026-10-25: Change two-stage native reference design
- Status: planning complete; implementation remains pending. The original 24.5 architectural block is resolved; its unapproved visual STOP is preserved in 24.7.
- User decisions: use native Data Studio charts and existing mode semantics; HTML generation may exceed five minutes (user reports Flash 3.8 produced HTML in about three minutes with internet access); use supplied references and bundled assets first, no new internet research.
- What changed: docs/PRD.md goals/model routing/defaults; docs/architecture.md graph, memory, Designed pages, new Reference design brief and Reference HTML composition specs and three decision rows; docs/architecture-essentials.md updated/restamped and kept under 6,000 chars; docs/plan.md reworks 24.5 into the Argon brief (M), adds 24.6 Flash composition/integration (M) and 24.7 live fidelity/approval (M). No code, dependencies or contracts changed; saved implementation stash not applied.
- Decisions: a code-owned report carries approved candidate slots and resolved bindings/substitutions, because the existing unresolved-issue summary is empty when ready. Both stages receive counted image parts and mandatory context; brief 12k input/4k output, HTML 12k/16k, LOW thinking. Default 600 s per page's complete Flash stage includes counting/transport retry/one HTML repair; Argon brief 120 s total. Deadline exceptions are node-specific; no-reference requests and existing worker/planner limits stay unchanged. Cancellation/shutdown must clean candidates and release ownership. No fake charts, imported style-mode components, new web tools or cap increases. Model-generated brief stays ephemeral; final HTML uses the existing saved spec.
- Request settlement: the blocked two-stage recreation request is planned as 24.5-24.7, reusing compatible backend-only image transport and no-reference guards from stash 75157888f8d9a04a22ea136e00aa018cdb21a6cd if reachable. It is not a required dependency or permission to apply a whole program stash. User clarification answers supersede the earlier pending questions and 120 s HTML suggestion. Existing unrelated Later items remain deferred.
- Checks: blueprint lint PASS (81 tasks, 0 errors, 15 existing size-warning categories); stamp refreshed. Read-only blueprint_explorer mapped designer/accept/revise/model routing and lifecycle. Independent blueprint_reviewer delta audit: No findings; native components, mode semantics, deadlines, cancellation, publication checks and live STOP consistent. No product tests or live models run in this planning session; task Done-when commands remain the builder's required checks. Dependency registry checks not rerun because no dependencies changed; existing dated approvals retained.
- Evidence: backend-local electricity reference .blueprint/qa/task-24.5/reference/20261025-001939-30a57d57/build/reference_img_bfc820b06597.jpg SHA256 1c30b41832d16d21fcb74827d5b13aa6bd2861a978c647761ee07200f05e32a9. The old local live driver identifies the original CSV and eb6e5770 hash prefix; 24.7 must acquire a reproducible backend fixture and record its full hash, not run the old driver unreviewed or assume old build state.
- Left open: live fidelity is unproven and requires user approval in 24.7; full native report/engine integration belongs to release. No new UNVERIFIED dependency or scope decision blocks 24.5. Folder mode: no commit made.
- Next: reopened 24.5 with blueprint.py; status confirms 78/81 done, 0 blocked, 24.5 ready. Build it in a fresh backend chat with gpt-6.1-sol at high and $blueprint-solution-builder. Then 24.6, supervised 24.7, and the backend final audit before release integration.

## 2026-10-25: Task 24.5 Argon writes a feasible reference design brief
- Status: done
- Plan check: off
- What changed: new nodes/reference_brief.py (reference loader, approved-component report, one counted planner brief per page with validation), prompts/v1/reference_brief.md, skills/reference-design.md; context.reference_brief_context + BUDGETS 12k + conservative allowance; llm PLANNER_NODES += reference_brief; designer._generate(limit=16000 default). Not wired into accept/revise (24.6).
- Checks: `uv run pytest tests/test_reference_brief.py tests/test_context.py tests/test_designer.py tests/test_llm_timeouts.py` PASS 97 passed; Test (all) `uv run pytest` PASS 1699 passed, 14 deselected.
- Decisions: report = saved ledger.assessment id/state + spec components (metrics, dims, date_dimension, field, breakdown, sort, options, grains from datasource date_granularity) + bindings from coverage_errors(bindings=) (image rows: observation_meaning, else source+text[:240]) + current ledger.decisions and feasibility.choices; every page gets all decisions. brief refuses before any call: no images ('reference'), assessment not ready ('feasibility'), report (id,type) != page ('stale'), secret in context ('model'). All sections mandatory (one semantic section holds styling+icons+art). Output checks: page index, exact slot set, prose <=12,000 chars, no code/URL/asset patterns, no other p<n>_ ids (p<n>_design allowed). Loader checks FILE_NAME, size, sha256, MIME signature; damaged record/image raises invalid_source reason 'reference'. asyncio.timeout(deadline) wraps count+generate. Stash: only fixture shape and no-reference fingerprint ported (hash unchanged: c42eceff).
- Digest: nodes/reference_brief: reference(folder)->Reference(mode,instructions,images,described,notes)|None; report(snap,ledger,checker)->{page:{assessment,components,decisions}}; brief(model,ref,approved,spec,page,trace,*,shared,revision,secrets,report,deadline)->PageBrief|Fallback
- Tried and failed: none
- Gotchas: none beyond AGENTS.md
- Left open: P3 Decisions not scoped to the page - src/dss/harness/nodes/reference_brief.py; P3 Style-mode test uses an empty ledger - tests/test_reference_brief.py
- Next: Task 24.6. Wire reference(folder)/report/brief into render.accept and revise regeneration, then the Flash reference_html stage.

## 2026-10-25: Task 24.6 Flash composes reference pages with a bounded long deadline
- Status: done
- Plan check: off
- What changed: wired ready references through planner brief then worker HTML on accept/revise; preserved native slots and ordinary designer fingerprints. Added per-page deadlines, cancellation/shutdown cleanup and truncation diagnostics.
- Checks: `uv run pytest tests/test_designer.py tests/test_reference_brief.py tests/test_context.py tests/test_llm_timeouts.py tests/test_render.py tests/test_revise.py tests/test_feasibility.py tests/test_skeleton.py tests/test_api_contract.py tests/test_recipe_contract.py` PASS (560, 2 deselected); Test (all) `uv run pytest` PASS (1730, 14 deselected, 2 dependency warnings). Checkpoint staged-routing and timeout regressions fail as expected. Read-only review: no findings after cap-hit tracing fix.
- Decisions: ephemeral ReferenceDesign carries current reports/getters; one outer 600s HTML deadline includes counting, retry, measurement and repair. Reference-only prompt overrides default card treatment, preserving ordinary prompt/skill bytes. AGENTS.md records finite-reply fake routing trap.
- Digest: `designer.reference_design(folder,snapshot,ledger,checker,models)` feeds `design/regenerate(reference=...)`; reference_html uses worker, 600s/page including count/retry/repair, 12k/16k budgets; spans record actual model, duration and truncation; shutdown cancels tasks.
- Tried and failed: legacy finite Blueprint fake answered the new brief; separate stage fakes fixed the regression.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: 24.7, live fidelity experiments and user approval STOP.

## 2026-10-25: Task 24.7 Verify and approve two-stage reference fidelity
- Status: blocked
- Plan check: off
- What changed: uncommitted (kept in tree for the resume): tests/live/test_reference_design.py (recreate/style/none live cases, fixture hash checks, per-stage evidence, uncapped issue dump `issues-uncapped.json` on block) and tests/data/reference_design/ (electricity image, synthetic CSV + generation.json, README provenance, full SHA256s). Also committed missed task 24.6 work (8e7fe2a).
- Checks: `uv run pytest tests/test_reference_brief.py tests/test_designer.py tests/test_render.py tests/test_revise.py` PASS (246, 2 deselected, 218 s). Live: style PASS (earlier session, 360 s incl. none); none FAIL (planner designer page-3 kit fallback after repair, existing behavior); recreate FAIL x3 at feasibility (blocked; 107-113 s each). Test (all) not run.
- Blocked because: (b) recreate needs feasibility/Blueprint fixes outside 24.7 Files (src/dss/spec/requirements.py, feasibility/blueprint planner).
- Question: Should a fix task make recreate reach ready for this fixture before 24.7 resumes?
- Options: A plan a fix task: absorb definition-only reference instruction rows (now blocking `unknown`), reconcile dimension observations with `X = field` instructions, make the Blueprint honor observations (yearly SUM(people_without_access) bar, region fixed_size_list) / B user drop policy in the test (drops observations the Done-when requires) / Recommend: A (user chose A).
- Tried and failed: run 104330 (7 definitions) 22 issues (scope refusal); run 104805 (+field-name definitions) 21: 12 `unknown` definition rows, Region Selector needs_clarification, geo_map needs_data, Location legend as dropdown, 4 per-country small multiples (date_field), bp_ scorecard/bar observations with no matching row and no alternatives.
- Gotchas: user-approved drops still needed after the fix: geo choropleth (country not GEO), per-country small multiples (no per-chart filter), year slider. None-mode test asserts no designer fallback; existing no-reference path can fall back: relax to record it.
- Left open: none
- Next: architect plans the fix; then resume 24.7 (rerun recreate, get drop decisions, finish live check, visual STOP).

## 2026-10-25: Change recreate observation completion (24.7 block)
- What changed: architecture.md gains #Recreate observation completion and a decision-log row. The essentials Feasibility line is extended (stamped). plan.md: 24.7 is rewritten as the fix task "Recreate reaches ready for the electricity reference" (reopened, same ID and evidence folder). The verification and visual STOP move unchanged to a new 24.8 (depends on 24.7; evidence in .blueprint/qa/task-24.8/).
- Why: 24.7 was blocked at 21 feasibility issues (run 104805): 12 definition-only instructions became `unknown` rows; `Region Selector = region` wasn't an explicit control field; `using year` didn't bind the date field; a scorecard observation was asked for a year grain; the yearly SUM(people_without_access) bar stayed missing after the repair. The user chose fix option A.
- User decisions (cards, 2026-10-25): approved drops for this fixture are geo_map (country is not GEO; the globe stays static art), the Rural/Urban legend misread as a dropdown, and any extracted year slider. The four per-country small multiples become one native urban/rural area chart, by instruction substitution. When an observed row is fully determined and still missing after the repair, code adds it (not an alternative). A `chart <type>` instruction clause is allowed (region fixed_size_list).
- Decided by default: no delta audit (POC target). The none-mode designer fallback is existing behavior: 24.8 records it rather than failing on it. The scope gate doesn't apply: the deadline has passed, and the change fixes a blocker.
- Affected tasks: 24.7 (rewritten, [ ]), 24.8 (new). The uncommitted live test and fixtures from the blocked run are 24.7 inputs and are committed with it.
- Change requests: none open.

## 2026-10-25: Task 24.7 Recreate reaches ready for the electricity reference
- Status: done
- Plan check: off
- What changed: requirements.py: definition surface (`_surface`), definition clauses are evidence (no rows, not sent to the extractor), `_observe_surface` binds label/metric-label definitions (metrics, unit, grain, `using`, `chart`, control field), scorecard grain skip, control_field/bucket-dimension coverage, `unused_definitions`. feasibility.py: `complete`/`surplus`/`added` code-added page-1 rows, pruned in mark(). blueprint.py: completion after the one repair, surplus prune in persist, leaked SQL tails dropped (view.model_expression). capability_check.py (outside Files, one line): assess_capabilities span `unused_definitions`. Fixture tests/data/recreate_electricity.json (sha256 provenance); live test commits the 24.7 inputs.
- Checks: Done-when 4 files PASS 338; `uv run pytest` PASS 1745; new tests fail on pre-change src; published spec+recipe bytes (ids masked) 134 tests, 0 changed; live recreate DSS_LIVE_STAGE=24.7: runs 25+26 consecutive PASS (also 9,19,21,23); 100 ms oracle 24x24 PASS on catalog default.
- Decisions: label definition outranks metric label; field defs bind controls only; multi-metric = substitution (title waived); completion only for observation Issues without alternatives (22.1 gaps stay user decisions; deviation from Spec wording, architect to confirm); a `using` field profiled at that grain (bucket_start) is its own bucket; control `argument.title` normalized into its label property; plain `Label = AGG(f)` keeps the old clause path; live test reconciles before drafting; DSS_LIVE_STAGE=24.7 skips 24.8's design/fidelity/revision asserts.
- Digest: req._surface(clause)->def|None; req.unused_definitions(snap,ledger)->[label]; snapshot['date_starts'] (recreate); feasibility.complete(snap,ledger,checker,bp,connected,context)->(rows,derived,added); surplus(); added(row): note `observation <ref>:<item>`; view.model_expression
- Tried and failed: completion for every gap (broke 22.1 decisions); drafting before reconciliation live (no observations seen).
- Gotchas: live reference_extract fails ~3/26 runs (validation/deadline); page-1 reference HTML repair refused over 12k budget (kit fallback) in run 20261025-123807: 24.8. Interrupted run 20261025-132150 may have left its BigQuery source/view.
- Left open: P3 code-added rows recognized by note text - feasibility.py; P3 `using <missing field>` gives needs_clarification, not needs_data - requirements.py; P3 pruned code-added bucket stays in derived_fields - feasibility.py
- Next: Task 24.8. Start by running the full live reference test without DSS_LIVE_STAGE and resolving the page-1 kit fallback.

## 2026-10-25: Task 24.8 Verify and approve two-stage reference fidelity
- Status: blocked
- Plan check: off
- What changed: live test writes .blueprint/qa/task-24.8/ and records (not fails) no-reference later-page fallback. Outside Files: blueprint.py reruns observation completion after the SQL repair (run 214425: invalid draft view, area row never added); view.LEAKED_TAIL strips `','type':'date` (run 215617). Regression tests in test_render/test_blueprint fail pre-change.
- Checks: offline Done-when files PASS 292; `uv run pytest` PASS 1747 (649 s). Live recreate FAIL x5 (110-255 s each); none/style not run.
- Decisions: fixes stay within #Recreate observation completion (user approved committing them).
- Blocked because: (b) the Spec's 12k reference_html input budget and one-repair rule aren't met reliably.
- Question: How should the reference HTML repair fit its budget and quality bar so page 1-3 design without kit fallback?
- Options: A architect revises the repair (leaner repair context, or a reference_html-specific allowance) and the post-repair failure policy / B keep retrying live (hides ~50% fallback) / Recommend: A (user chose A).
- Tried and failed: 214425 area row lost (fixed); 215617 view tail leak (fixed); 215913 ready+published, page-2 repair folded 11,337 -> bound 14,117 > 12k, over_budget fallback; 220404 retry: page-1 repair still 1 measurement error, invalid fallback.
- Gotchas: page-1 visual (215913 side-by-side.png): right panels are access_pct bars, not the urban/rural area; bottom bar y-axis labels overlap; scorecard 55.11 lacks %.
- Left open: none
- Next: architect resolves the repair budget; then rerun recreate/style/none live and take the visual STOP.

## 2026-10-25: Change bounded reference repair and publication failure (24.8 block)
- What changed: PRD.md records the user's two decisions. architecture.md#Reference HTML composition specifies deduplicated repair context, 12k initial / 24k repair input under the unchanged conservative allowance, the existing 16k output / 600 s / one-repair bounds, and reference failures that stop publication. #Working memory assembly, #Designed pages and #Reference design brief agree; the essentials are updated and stamped. plan.md rewrites blocked 24.8 as the focused implementation task and adds 24.9 for live evidence and the original visual approval STOP. Completed 24.5-24.7 remain historical.
- Why: saved recreate run 20261025-215913-0fe3bb96 refused page-2 repair at bound 14,117 >12k; 20261025-220404-ba788ef9 completed its repair under budget but still had one measurement error and fell back. Repeating live runs or enlarging the input budget alone does not prove quality.
- User decisions (this session): stop a reference build that fails after its one repair and preserve existing artifacts; allow up to 24k repair input after removing duplicate context, with initial input/output/time/retry limits unchanged. Applies to reference builds with designed pages enabled; no-reference fallback and the explicit flag-off path retain existing behavior.
- Design ruling: preserve every authoritative slot/data/decision fact, full brief, reference intent/images, fixed width/shared CSS and revision comments; only duplicate representations are removed. A usable failed draft replaces older revision HTML during repair. No usable draft retains the revision baseline. Over-budget mandatory input still refuses. Any reference page/brief or assembled-spec failure prevents candidate publication; cleanup settles sibling work, retains previous publications and releases ownership. No API/recipe contract change.
- Affected tasks: 24.8 (rewritten fix, M; reopened through blueprint.py), 24.9 (new live/visual verification, M, depends on 24.8). Status confirms 81/83 done, 0 blocked, 24.8 ready. The accepted unsupported substitutions and user's visual STOP are preserved in 24.9; no approval has been inferred from the prior screenshots or tests.
- Checks: blueprint stamp refreshed; lint PASS (83 tasks, 0 errors, 16 size warnings for the long existing plan/docs/spec sections). Read-only blueprint_explorer mapped the repair/counting/deadline/fallback path. Independent blueprint_reviewer delta plan audit: No findings. Plan Audit is done; this is not final implementation acceptance. No product code or tests changed; no product tests or live models run in this planning session. Existing dependency approvals are dated 2026-10-22; no dependency added or changed, so registry verification is not repeated.
- Change requests: the 24.8 repair-budget/failure-policy block is planned in 24.8; live confirmation moves to 24.9. No request is deferred or declined.
- Left open: implementation, recreate/style/none and revision live checks, and the user's visual approval remain outstanding. Then the backend final re-audit precedes release integration. Folder mode: no commit.

## 2026-10-25: Task 24.8 Bounded reference repair and publication failure
- Status: done
- Plan check: off
- What changed: reference HTML requests retain one component projection/current draft and enforce 12k initial / 24k repair complete bounds. Reference failures reject publication; revisions retain artifacts/comments. Added guarded local failed-draft diagnostics and regressions.
- Checks: budget regressions failed before (3), passed after (3). Required eight-file pytest command PASS 411 (490.34 s); final malformed-key regression PASS 1. Test (all) `uv run pytest -q --tb=short` PASS 1772, 17 live deselected (976.69 s). Read-only review: no remaining findings. No live model/visual acceptance claimed.
- Decisions: count mandatory reference requests only after schema/images assembly; schema diagnostics exclude raw unknown keys. Preserve existing synchronous feasibility recheck writes; assert every candidate-boundary file and pre-request published artifact remains byte-identical. No prompt changes. Updated two stale AGENTS.md gotchas and valid reference fake routing.
- Digest: reference_html_context(..., attempt=1) carries Context.budget (12k/24k), one slot projection and current draft. designer.design rejects reference fallbacks atomically; live observe_generation saves guarded local failed drafts/errors/screenshots.
- Tried and failed: legacy fixtures depended on kit fallback; page-1 revision fake returned forbidden width; preflight snapshots included assessment/log writes. Corrected fixtures/oracles without relaxing published-artifact checks.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: 24.9, live fidelity checks and user visual STOP; save evidence under its QA folder.
- Checkpoint: session started in folder mode with .blueprint/snapshots/task-24.8-1.zip; no Git commit. The verified task marker required an escalated script run after a sandbox write error.

## 2026-10-25: Task 24.9 Verify and approve two-stage reference fidelity
- Status: blocked
- Plan check: off
- What changed: no product code. Committed the uncommitted 24.8 work first (d3ea046, user-approved). Test evidence-dir rename (task-24.9) and README substitution notes are stashed (`blueprint: task 24.9 failed attempt`); reapply or redo before the next live run.
- Checks: live recreate FAIL x2 at /design/confirm (Blueprint), before any reference_brief/reference_html ran: 20261025-233319-bc455866 (135 s), 20261025-233550-34512aef (134 s). Fixture hashes matched; approved geo_map drop applied pre-Blueprint. style/none, offline Done-when files and Test (all) not run.
- Decisions: followed the task's If (one transient retry, then block); user chose block.
- Blocked because: (d)/(b) the planner's Blueprint is not reliably ready for this fixture; fixing it needs code outside 24.9's Files (Blueprint/observation completion or planner skill).
- Question: How should Blueprint handle the planner's redundant year-bucket derived fields, so recreate reaches ready reliably for the electricity fixture?
- Options: A architect plans a fix (e.g. code maps/strips a derived `DATE_TRUNC(<DATE year-start field>, YEAR)` bucket onto the base field with its profile grain, and rows naming a missing `<field>_year` resolve to it) / B accept live variance and rerun until ready / Recommend: A.
- Tried and failed: run 233319: derived `year_trunc = DATE_TRUNC(year, YEAR) - INTERVAL 0 DAY` but rows q2/q8 use `year_year` ("Field year_year is not in the view"; observations o5-o8 needs_clarification, offered date_bucket). Run 233550: derived `year_grain = DATE_TRUNC(year, YEAR) * 1` -> "The view did not pass SQL validation after one repair"; KPI q4 "Use each named KPI with exactly its confirmed field and aggregation". Blueprint in=15178/16682, bounds 6246+7451+5406 / 6481+8360+6066 (<=14k each), out 3556/3686, ~51 s.
- Gotchas: none new (live variance already in AGENTS.md).
- Left open: visual STOP, revision/later-page/style/none live checks.
- Next: architect resolves the Blueprint year-bucket instability; then rerun recreate/style/none and take the visual STOP.

## 2026-10-26: Change proven recreate dates and precise KPI repair (24.9 block)
- What changed: PRD.md records the bounded default and reason; architecture.md adds #Recreate date binding normalization and a decision-log row; architecture-essentials.md summarizes it and is stamped. plan.md rewrites blocked 24.9 as the M implementation task "Canonical recreate year bindings and precise KPI repair", reopened through blueprint.py; the original live/fidelity task and visual STOP move to new 24.10 (M, depends on 24.9), with evidence under .blueprint/qa/task-24.10/. Completed tasks and original failure evidence remain historical.
- Why: both 24.9 runs failed before reference_brief/reference_html. The source profile proves the projected DATE year already has year starts, yet drafts bind missing year_year or introduce year_trunc/year_grain with interval/type changes or invalid DATE arithmetic. Run 233550 also independently omits confirmed AVG(urban_rural_gap) from q4; fixing dates alone cannot make it ready.
- Architect ruling (Design class, existing POC goals): reconstruct only bounded planner date representations using active full-column proof tied to the actual selected-source projection. Explicit reconciled field/grain bindings qualify; selected native date-axis uses of a complete recognized DATE_TRUNC(base, YEAR) expression also qualify, with no conflicting confirmed temporal semantics. The latter is needed for saved overall time-series rows with no observation link; a metric-label match is never evidence of one. Missing aliases require the stricter explicit binding. Validate every use; preserve protected definitions, numeric metrics, non-identity expressions and confirmed KPI meanings. Completion and every draft/repair ingress share the rule; current proof governs redraft/reload/accept. Exact missing/conflicting measures go to the existing one row repair, then unresolved KPI errors still block. No new model call, query, dependency, budget, automatic substitution/drop or contract shape.
- Evidence/provenance correction: the QA trees contain persisted Blueprint artifacts and usage metadata, not captured original Blueprint model replies. 24.9 must label reconstructed FakeLLM draft/repair/view replies and all adjustments, hashing original inputs separately from the derived fixture; it cannot claim a byte-exact provider replay.
- Affected tasks: 24.9 (rewritten/reopened implementation, M); 24.10 (new live/visual verification, M). The fixture's previously approved geo/legend/slider drops and urban/rural-area substitution are unchanged. The live readiness gate requires two consecutive ready Blueprint results; a documented stage flag can stop before design in 24.9. Full reference pages/revision/style/none checks and user approval stay in 24.10.
- Checks: stamp refreshed; blueprint lint PASS (84 tasks, 0 errors, 16 existing long-plan/doc/old-Spec size warnings; new 24.9 Spec is below the warning threshold). A read-only blueprint_explorer mapped source/profile/projection, completion, model ingresses and the separate q4 omission. Independent fresh-context blueprint_reviewer delta plan audit: No findings after the date-axis scope and reconstruction-provenance clarifications. This is planning acceptance only; no product code, fixture, test or live-model run changed/executed in this session. Dependency table remains unchanged with existing dated approvals; no registry lookup repeated. Folder mode: no commit.
- Change requests: the recorded 24.9 year-bucket block is planned in rewritten 24.9, together with the independently evidenced missing-KPI repair feedback. The original verification request is retained in 24.10; none deferred or declined. Deadline is no longer binding per the program guide; this change resolves a blocker within the existing goals.
- Left open: implement/verify 24.9, then run 24.10 and obtain the user's visual approval. Backend final re-audit follows before release integration; no implementation/fidelity/final acceptance inferred here.

## 2026-10-26: Task 24.9 Canonical recreate year bindings and precise KPI repair
- Status: partial
- Plan check: off
- What changed: restored checkpoint after two failed regression attempts; recoverable implementation/tests/fixture in `.blueprint/attempts/task-24.9-20261026-002427/`. Fixture generator, original/derived hashes and diagnostic handoff remain under `.blueprint/qa/task-24.9/`.
- Checks: targeted feasibility/view/render selection twice: 32 passed, 1 failed, 290 deselected. Earlier group: 104 passed, 1 existing timing failure (114 ms); isolated retry passed. BigQuery prerequisite passed. Done-when/full suite, saved-run API checks, live readiness and review not reached.
- Decisions: source-bound projection proof; whole-expression reconstruction at every ingress; exact KPI repair feedback. Light worker transcribed sanitized fixtures and verified deterministic generation/40 unchanged original hashes. Added sandbox-access gotcha to AGENTS.md.
- Tried and failed: normalization read only eligible `blueprint_observations`; conflicting mappings disappear there, allowing native-axis fallback. Changing ledger grains, then actual instructions/reassessment, both failed the preserve-on-conflict regression. Diagnostic: instructions changed=True, mapping grains=[year], observation meanings=[].
- Gotchas: see QA handoff for unverified integration scaffolding and remaining coverage.
- Left open: task implementation and all completion gates.
- Next: reapply attempt selectively; inspect blocked observation evidence and guard native fallback against conflicting field/grain/type intent before normalization. Follow `.blueprint/qa/task-24.9/attempt-20261026.md`, then complete task 24.9.
