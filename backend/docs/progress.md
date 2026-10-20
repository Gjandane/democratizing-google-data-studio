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
