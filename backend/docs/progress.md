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
