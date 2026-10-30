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

## 2026-10-26: Task 24.9 Canonical recreate year bindings and precise KPI repair
- Status: done
- Plan check: off
- What changed: source-bound year reconstruction across draft, repairs, completion and reload/redraft; exact missing/conflicting KPI feedback; sanitized saved-run regression fixtures.
- Checks: prescribed suite PASS 594; Test (all) `uv run pytest` PASS 1848 (17 live deselected). Both saved fixtures publish contract-valid yearly recipes and finish the fake engine. Two consecutive live recreate readiness runs PASS (112.57/119.00 s); only approved geo-map drops. No reference HTML, live engine or visual approval claimed. Seven fingerprint cases: 31 identical artifact hashes; 40 original input hashes unchanged. Evidence: `.blueprint/qa/task-24.9/`.
- Decisions: recompute actual projection proof; private `native_dates` retains typed intent, never authorization; disambiguate native bindings and scope them to recreate. Reuse one local definition scan: oracle minimum 73.61 ms (<100). Added fixture/repair gotchas to AGENTS.md.
- Digest: view.proven_date_starts(sources,selection)->{field:grain}; feasibility.canonical_dates(...); blueprint-inputs.json.native_dates retains recreate year intent (not proof); DSS_LIVE_STAGE=24.9 stops at ready /design/confirm.
- Tried and failed: fixture sanitization/rebinding, repair re-entry/freshness/scope edge cases and duplicate-scan timing failures corrected; details in QA notes.
- Gotchas: none beyond AGENTS.md.
- Left open: none; final reviewer: No findings.
- Next: 24.10 Verify and approve two-stage reference fidelity.


## 2026-10-26: Task 24.10 Verify and approve two-stage reference fidelity
- Status: blocked
- Plan check: off
- What changed: fixture inputs/provenance and diagnostic outcomes; evidence: `.blueprint/qa/task-24.10/acceptance-review.md`.
- Checks: live 1 FAIL/2 PASS (673.10s); retry FAIL (172.45s); corrected input FAIL (75.07s). Required focused suite: 284 PASS (306.29s); Test (all) `uv run pytest`: 1848 PASS (826.92s). Review: no introduced findings; secret scan clean.
- Decisions: preserve gates/caps; public inputs only; retain diagnostics. AGENTS.md adds cross-page coverage gotcha.
- Tried and failed: published table replaces right areas; scorecard percentage/2011 unclear/clipped. Retry: 272px list below 276px minimum. Corrected input: consolidation date_field clarification, no alternatives/publication.
- Gotchas: none beyond AGENTS.md.
- Left open: recreate revision/dry-engine and visual approval; native ids/substitutions/stage evidence retained.
- Blocked because: (b) needs architect disposition of feasibility/fidelity failures.
- Question: Should the architect clarify fixture date binding before another fidelity run?
- Options: A assess explicit date clause (recommended) / B plan product scope if still needed.
- Next: architect assesses `date grain year using year` in consolidation clause; unverified, not proof area is unsupported.

## 2026-10-26: Change recreate page placement and truthful observed titles (24.10 block)
- What changed: architecture.md adds #Recreate page placement and truthful observed titles, a decision-log row and fixes the stale 24.9/24.10 gate reference; architecture-essentials.md summarizes it and is stamped. plan.md rewrites blocked 24.10 as the M implementation task "Recreate page placement and truthful observed titles" (reopened through blueprint.py); the live/fidelity verification and visual STOP move to new 24.11 (M, depends on 24.10, evidence under .blueprint/qa/task-24.11/).
- Why: run 045323 published every binding but put the approved urban/rural area on page 3 (page 1 got a country table), because coverage accepts any page; its scorecard showed an all-years AVG as "...worldwide in 2011" with no %. Run 050449 failed the 276 px list minimum (variance; gate held). Run 052835's corrected input blocked at reconcile: a prose instruction sentence became its own area-chart requirement with no date field.
- User rulings (Design class, existing POC goals): (1) recreate INSTRUCTIONS stay definition clauses only; substitution/composition prose moves to RECREATE_NOTES (24.11 If); (2) observations count only on their reference page via one page-aware predicate; the existing one row repair targets page-1 questions, then existing completion adds the row; (3) one observed-title normalizer drops unenforced trailing period phrases and appends a definition/KPI unit. No contract, cap, model call or dependency change.
- Delta audit (blueprint-reviewer, fresh context): 1 major (repair could not place a row on page 1: rows take their question's section page and repair targets the nearest, possibly off-page, row) and 5 minor (named predicate path, title normalizer reach, unit source/alias matching, period grammar, text-fit edge/stale ref/test_revise Files/no-effect fixture clause). All applied per user choice; the proposed extra `Urban vs rural` clause was dropped because it matches no observation.
- Checks: stamp refreshed; blueprint lint 0 errors (16 existing size warnings). No product code, test or live run changed or executed in this session.
- Change requests: the 24.10 block (date-field clarification and fidelity failures) is planned in 24.10 (implementation) and 24.11 (verification); none deferred or declined.
- Left open: implement 24.10, then run 24.11 and obtain the user's visual approval. Builder should show scorecard value clipping and full-date bar axis labels at the STOP.

## 2026-10-26: Task 24.10 Recreate page placement and truthful observed titles
- Status: done
- Plan check: off
- What changed: recreate image observations count only on page 1 through one predicate (`requirements.placed_fulfills`) in the Blueprint check, completion, accept/publish and revise coverage; page-1 repair targeting (`repair_qids`); `requirements.observed_title` strips unenforced trailing periods and appends evidenced units. Fixture tests/data/recreate_page_placement.json (run 045323, generator/hashes in .blueprint/qa/task-24.10/).
- Checks: Done-when focused suite PASS 634 (359 s); Test (all) `uv run pytest` PASS 1889, 17 deselected (795 s). 39 new regression tests fail on 848749c, pass now. Recompute oracle min 31-33 ms (<100). Fingerprints (9 cases): 18.2/style/data/none byte-identical; title diffs: 21.1 Revenue, Revenue by month, Revenue by region +" (USD)"; 22.1-monthly Revenue, Revenue by month, Revenue by category +" (USD)"; 22.1-table those plus Top products by revenue +" (USD)"; 24.9 both "have access to electricity worldwide in 2011"->"... (%)". User-accepted beyond titles: 24.9 both gain a code-added page-1 area; 233550's page-1 bar takes o7's title. Review: no P0/P1.
- Decisions: reference page = 1 (one recreate image, items carry no page). observed_title(label, r, kpis): units only from instruction/KPI evidence, conservative without KPIs; "text fit" = validate_spec label rule (component titles have no Chromium check). No-nearest page error: `repair_qids`, not `qids` (decide overlap). User-approved: live INSTRUCTIONS prose moved to RECREATE_NOTES (pre-existing HEAD failure); 22.1 title expectations in test_compiler/test_reference_brief; stale cross-page AGENTS gotcha replaced.
- Digest: req.placed_fulfills(c,page,r,needs,checker,snap); req.reference_page(snap,r)->1|None; req.observed_title(label,r,kpis); observation_meaning(...,kpis=); observation_coverage(...,pages=); feasibility.page_questions; error key repair_qids
- Tried and failed: none.
- Gotchas: in AGENTS.md.
- Left open: P2 builds published before 24.10 keep raw/off-page titles and fail coverage at run preflight/revise until re-accepted - src/dss/spec/requirements.py; P3 reference_brief.report passes no KPIs to observation_meaning - src/dss/harness/nodes/reference_brief.py:115
- Next: 24.11 Verify and approve two-stage reference fidelity.

## 2026-10-26: Task 24.11 Verify and approve two-stage reference fidelity
- Status: blocked
- Plan check: off
- What changed: fixture hashes/evidence, placement/title/area oracles and approved multi-issue geo-map drops. Evidence: .blueprint/qa/task-24.11/README.md.
- Checks: `uv run pytest -m live tests/live/test_reference_design.py` FAIL (1 passed, 2 failed; 508.59s); retry FAIL (2; 315.18s). `uv run pytest tests/test_reference_brief.py tests/test_designer.py tests/test_render.py tests/test_revise.py` PASS (290; 334.35s). `uv run pytest` PASS (1889; 781.28s). Review: P2 source-provenance wording fixed; no open findings; four style screenshots inspected.
- Decisions: preserved earlier evidence; AGENTS.md records multi-issue drops; no runtime/cap changes.
- Tried and failed: geo-map classifier; then recreate/none synthetic_load_failed before models (none twice). Corrected decision/oracle paths remain unexercised live.
- Gotchas: in AGENTS.md.
- Left open: recreate/later-page/revision fidelity, none acceptance, visual STOP. Style passed without fallback/imported observations.
- Blocked because: (d) repeated synthetic-load failure; sanitized evidence omits provider cause.
- Question: How should repeated typed synthetic-load failures be diagnosed?
- Options: A plan intake diagnosis / B defer until recovery / Recommend: A.
- Next: new chat, gpt-6.1-sol high, $blueprint-solution-architect; diagnose intake, resume 24.11.

## 2026-10-26: Change diagnose canceled synthetic loads and resume 24.11
- What changed: task-specific clarification in plan.md, corrected its stale implementation-pending header, and reopened 24.11 through blueprint.py. New evidence and diagnostic-only scripts live in .blueprint/qa/task-24.11/intake-diagnosis/ (README.md, existing-jobs.json, recovery.json, read_jobs.py, check_recovery.py). Earlier failure evidence is unchanged. No product code, test implementation, architecture, dependency, contract, fixture, prompt, timeout or retry policy changed.
- Why/evidence: read-only BigQuery history matched all five retained builds. The three failed typed loads are DONE with reason stopped (canceled), equal start/end timestamps, no output-row statistics, and 118.826/139.978/136.306 s creation-to-terminal time. Two earlier loads succeeded with 2,000 rows and zero bad records. Existing client wait is 120 s; cleanup cancels unfinished deterministic jobs. Delayed jobs reaching that wait and cleanup is consistent with the evidence, not proof of the canceling actor, original Python exception, underlying delay, quota issue or provider outage. Google's Job/error documentation supports the status/timestamp meanings; links are in the evidence README. No schema or authentication defect is established by the historical jobs.
- Recovery check: one fresh attempt with the unchanged typed loader/profile and exact retained generation schema/CSV, configured project/dataset/location and one uniquely named temporary table. PASS: 2,000 loaded rows (6.45 s), profile count 2,000 (2.08 s), exact-table cleanup complete; 11.72 s total. No models called. Both fixture hashes match. ADC refresh with normal process access also passed; a sandbox-only TransportError is not evidence about the original live failures. This prerequisite does not exercise generation, source registration, the full HTTP lifecycle or dashboard fidelity and does not guarantee future availability.
- Ruling (Clarification class, existing POC goals): no product fix or new task is justified. Resume 24.11 (M). Before its next live run, add scoped test-owned phase/elapsed-time/exception-class and reserved-job metadata diagnostics, retaining allowlisted codes and state/timestamps locally without provider messages, SQL, rows or credentials. Preserve exceptions, deadlines, cleanup, the one transient retry rule and every fidelity gate. The ordinary synthetic stage is the prerequisite; a repeated failure blocks again with evidence, never with a substituted data source or unbounded retries.
- Checks: blueprint lint PASS (85 tasks, 0 errors, 16 existing size warnings); status confirms 84/85 done, 24.11 ready and no blocked task. Independent fresh-context blueprint_reviewer delta review: No findings; script/fixture hashes match. Configured-secret scan of all five new evidence/scripts/docs files passed (no value found). No product test suite or full fidelity run was repeated in this planning session; prior recorded test passes remain historical. Architecture was unchanged, so no stamp; dependency approvals unchanged, no registry lookup repeated. Folder mode: no commit.
- Change requests: the 24.11 intake-diagnosis question is resolved by retained job metadata, a successful prerequisite check and the task's diagnostic clarification. No request deferred or declined; no new product decision required.
- Left open: implement test-only diagnostics, complete recreate/later-page/revision and no-reference live checks, required suites, and obtain the user's visual STOP. No fidelity or final acceptance claimed.
- Next: a supervised builder session for 24.11 in backend/, gpt-6-astra high (Spec plus visual STOP: frontier). Then backend final re-audit; release integration follows at the program root after backend acceptance.

## 2026-10-26: Task 24.11 Verify and approve two-stage reference fidelity
- Status: blocked
- Plan check: off
- What changed: scoped intake diagnostics and count guards; source snapshots/evidence in .blueprint/qa/task-24.11/RESUMED.md.
- Checks: live FAIL (1 passed/2 failed, 557.50s); style retry FAIL (170.74s). Focused FAIL (289 passed/1 failed, 566.94s); unchanged isolation PASS (6, 10.39s). Full `uv run pytest` PASS (1889, 981.60s), including focused modules. Observer oracle PASS (8). Review: P2 fixed, no remaining findings.
- Decisions: unchanged fixtures/instructions, runtime, caps, deadlines and cleanup; post-live diagnostic fix verified offline and distinguished by hashes.
- Tried and failed: recreate published three pages; missing worldwide, four area slots, clipped scorecard, crowded/full-date axis. Style footer failed twice; four intakes passed.
- Gotchas: existing timing guidance followed; isolated invalid_source cause unproven.
- Left open: fidelity, recreate revision/dry engine and visual STOP.
- Blocked because: (b) corrections require runtime work outside this verification task; repeated style failure exhausts its retry.
- Question: Which backend corrections should precede renewed fidelity acceptance?
- Options: A architect plans corrections under existing gates / B defer / Recommend: A.
- Next: new backend chat, gpt-6.1-sol high, $blueprint-solution-architect.

## 2026-10-26: Architect proposal for resumed 24.11 fidelity corrections
- What changed: added docs/change-24.11-fidelity.md as a reviewed draft; canonical PRD/architecture/essentials/plan and task markers remain unchanged pending the skill's user-review STOP. No product code, test, prompt, fixture, dependency, contract, timeout or retry policy changed.
- Evidence: inspected .blueprint/qa/task-24.11/RESUMED.md and the saved recreate comparison; narrow read-only explorers mapped title-based slot ownership, native preview formatting and shared wrapper/footer behavior. The access title correctly lost 2011 and gained (%); requiring worldwide when extraction omitted it exceeds the existing normalizer rule. Four different country-title properties force four native slots despite equal definitions. The clipped total-people scorecard already requests compact_numbers=true, which the preview ignores; the DATE field already carries proven year-grain metadata. Wrapper-induced flex stretching into the appended footer is a source-supported diagnosis, still to reproduce offline; real 564px slots remain below the required 568px minimum.
- Proposed disposition (Design class, existing POC goals): rework unfinished 24.11 into explicit shared-chart meaning/coverage (M); add 24.12 shared content/footer geometry (M), 24.13 compact scorecard/yearly preview readability (M), and move every live/visual obligation to 24.14 (M, supervised STOP). Proposed explicit shared chart modifier requires user approval and new input hashes; formulas, image, synthetic schema/CSV and unsupported substitutions remain fixed. No implicit equivalence from fields/formulas, fake background charts, relaxed gates or new model calls/caps.
- Review: fresh-context blueprint_reviewer delta audit: No findings; read relevant source and saved screenshots, ran no tests/services. Canonical blueprint lint: 85 tasks, 0 errors, 16 existing size warnings. This does not lint an applied proposed plan. No product/live tests, stamp or registry checks repeated: implementation and canonical architecture are unchanged.
- Decisions: keep all earlier failed runs and source hashes immutable; correct the over-specific title oracle only within the approved future verification task; promote only compact scorecards from the existing deferred preview-options item. Other preview gaps remain deferred. The draft records explicit defaults and complete acceptance oracles, not implementation or fidelity acceptance.
- Left open: user review of the four-task proposal, particularly explicit shared-chart authorization rather than implicit formula grouping; then apply approved changes top-down, stamp/lint and reopen through blueprint.py. Original 24.11 remains blocked. The latest builder question is not settled until the canonical Change entry is applied; no new live retries are authorized now.
- Next: user approves or amends the draft; afterward supervised backend builder for rewritten 24.11 on gpt-6.1-sol high, followed by 24.12/24.13 and 24.14 on gpt-6-astra high. Backend final re-audit follows visual approval; release integration follows backend acceptance at the program root.

## 2026-10-26: Clarification of the Argon-to-Flash handoff and thinking settings
- User direction: after saying "No need" to the proposed changes, the user asked why Flash 3.8 could recreate the dashboard from electricity-dashboard-prompt.md while this pipeline struggles, restated the idea of Argon authoring a prompt MD for Flash, and asked whether both models use HIGH thinking. The prior four-task proposal remains unapplied; this discussion does not approve it.
- Verified from local source: reference_brief.py:193 and designer.py:308 explicitly request thinking_level=LOW. The reference route already sends an Argon PageBrief (overall plus per-slot treatment, JSON, not a saved standalone MD) and the reference image to Flash. The brief has a 4k output cap, a 12k-character aggregate prose ceiling and skill guidance targeting about 6k characters; HTML has a 16k output cap. Both code budgets include thinking. No comparison with HIGH has been run here.
- Comparison: the supplied prompt lets Flash implement charts, supplied illustrative values, D3/TopoJSON scripts and interactions as a complete HTML dashboard. The current native-report route fixes components before briefing, forbids chart/data/control simulation in background HTML, measures empty slots and renders preview components separately. More capable reasoning or a more detailed prompt can be tested, but changing a background brief alone cannot repair fixed component grouping or the separate preview's ignored compact-number option. The MD filename itself is not the relevant difference.
- Checks/decisions: read-only source, prompt and retained-run inspection; no product/test/prompt/configuration/dependency/contract edits, model calls or tests. No assertion that LOW alone caused the failures or that HIGH would fix them. No need to repeat stamp/lint for this progress-only clarification.
- Left open: settle the intended level of Argon prompt detail and whether to run a bounded HIGH comparison before revising the implementation plan. Original 24.11 fidelity and visual STOP remain unresolved.

## 2026-10-26: Change HIGH thinking for both reference stages and test first
- User ruling: "No. Allow thinking high for both models. We'll test that first". This explicitly selects HIGH on Argon's reference brief and Flash 3.8's reference HTML before the proposed structural corrections; no further approval of that choice is needed.
- What changed: PRD.md records the user decision; architecture.md changes the two reference-stage budget paragraphs to HIGH, adds #Reference thinking comparison and a decision row; architecture-essentials.md summarizes and is stamped. plan.md expands the existing 24.11 Files to the two request-building nodes and their request tests, adds the HIGH-first comparison order/evidence, and is reopened through blueprint.py. docs/change-24.11-fidelity.md is marked not selected for implementation first. No new tasks. Runtime, tests, prompts, fixtures, dependencies, contracts and settings are unchanged in this architect session; the runtime still requests LOW until the builder implements the approved change.
- Scope: reference_brief HIGH on all pages/revisions; reference_html HIGH on initial/repair/later-page/revision calls. No-reference designer stays LOW; other nodes/routes unchanged. Preserve brief 12k input/4k output/120s and HTML 12k initial or24k repair input/16k output/600s per-page total, with thinking inside output caps, and existing retry/failure/publication/privacy/native-slot guards. No new alias grammar, footer wrapper or compact-number/axis fix before the comparison; no larger budget or silent LOW fallback. The electricity image/schema/CSV/INSTRUCTIONS/RECREATE_NOTES stay unchanged.
- Comparison: run request regressions before the existing bounded live cases; retain actual models, requested levels, nullable thinking counts, output/cap/truncation/time/hash/measurement/publication evidence and compare against immutable resumed LOW runs. Missing thought counts cannot prove zero thinking. Capture remaining known defects read-only before a post-publication assertion surfaces; do not weaken it or continue gated actions. HIGH may fail; output exhaustion is evidence for a later ruling, not authorization for more tokens. Visual STOP and all original task completion gates remain.
- Checks: blueprint stamp PASS; blueprint lint PASS (85 tasks, 0 errors, 16 existing size warnings); fresh-context read-only blueprint_reviewer delta audit: No findings. No product/offline/live tests or model calls run; no success/fidelity claim. No dependency changes or registry checks needed. Folder mode: no commit.
- Change requests: latest 24.11 builder question is resolved for the next step by the user's HIGH-first experiment order, with the narrow runtime setting change now inside its Files/Spec. Previous four-task proposal is not selected first; other structural decisions await trial evidence rather than being silently accepted or permanently dropped.
- Left open: builder sets the two reference request levels to HIGH and runs the comparison/required suites; then obtain the visual STOP or return the concrete remaining failure to the architect. Backend final re-audit and release integration remain downstream of accepted fidelity.
- Next: new backend builder chat, gpt-6-astra high (24.11 has Spec plus supervised visual STOP: frontier); implement/test HIGH first exactly as requested.


## 2026-10-26: Task 24.11 Verify and approve two-stage reference fidelity
- Status: blocked
- Plan check: off
- What changed: HIGH reference brief/HTML; no-reference LOW. Request regressions and comparison diagnostics/evidence: .blueprint/qa/task-24.11/high-comparison/README.md.
- Checks: request PASS (106; 170.20s). Live FAIL (1 passed/2 failed; 454.18s); recreate retry FAIL (236.32s). Focused FAIL (297 passed/1 failed; 527.30s); unchanged mixed-revision isolation PASS (4.90s). Full FAIL (1896 passed/1 failed/17 deselected; 1356.20s); isolated timing FAIL (2.35s). Review: No findings.
- Decisions: unchanged caps/prompts/fixtures; no-reference request/artifact/fallback fingerprints match checkpoint. Retain approved HIGH; no structural corrections. AGENTS.md records fake-counter bounds.
- Tried and failed: initial recreate Blueprint/view failure; retry and style briefs exhausted 4k (3 answer + 3997 thinking), no HTML/publication. Timing best 107.786ms/103.568ms against <100ms; cause unproven.
- Gotchas: in AGENTS.md.
- Left open: reference fidelity, HTML/later-page/revision/style acceptance, visual STOP and timing check.
- Blocked because: (b) further corrections exceed HIGH-only scope; required timing check also fails unchanged.
- Question: What approved follow-up resolves the brief cap and timing failures before fidelity acceptance?
- Options: A architect plans bounded corrections / B defer / Recommend: A, preserving gates.
- Next: new backend chat, gpt-6.1-sol high, $blueprint-solution-architect.

## 2026-10-26: Architect proposal after the HIGH comparison block
- What changed: added docs/change-24.11-high-followup.md as a reviewed draft. Canonical PRD/architecture/essentials/plan and task markers remain unchanged; 24.11 stays blocked. No product code, tests, prompts, fixtures, settings, dependencies, contracts, caps, timeouts or retry behavior changed.
- Evidence: read the latest blocked entry, high-comparison/README.md, RESUMED.md, the earlier unapplied structural proposal and narrow affected specifications. Read-only blueprint_explorer mappings confirmed the brief constant drives request/span/generation guards, prior LOW page-1 answer sizes (2,638 recreate; 2,480 style), and the exact failed ready/blocked recomputation test. Historical LOW thinking counts were zero-coalesced and cannot prove zero thinking. No new profile or model call was made; repeated alternative construction/validation/serialization are candidates to measure, not established causes.
- Proposed disposition (Design/Task class, existing POC): rewrite unfinished 24.11 as measured semantics-preserving recomputation recovery (M), then add 24.12 for an explicitly approved 8k total brief-output trial and all original fidelity/visual obligations (M, supervised STOP). Retain HIGH on both reference stages, brief 12k input/120 s/prose/schema bounds, HTML 12k initial or 24k repair input/16k output/600 s, no-reference LOW/fingerprints, exact fixtures/prompts/INSTRUCTIONS/notes and existing retry/failure rules. 8k is a bounded next trial, not a proven sufficient cap. The earlier shared-chart/footer/preview/title-oracle proposal remains unapplied.
- Review/checks: independent fresh-context blueprint_reviewer delta audit: No findings; read-only docs/evidence/source inspection only, no tests/services/profiling. Canonical blueprint lint PASS: 85 tasks, 0 errors, 16 existing size warnings; this does not lint the proposed tasks as an applied plan. No product/live tests, registry checks or stamp repeated because runtime/dependencies/canonical architecture are unchanged. Folder mode: no commit.
- Decisions: task comparisons normalize only per-call generated assessment ids; issue ids/order/evidence/digests, alternatives, provenance, page/title meaning, environment refresh, purity and all existing speed workloads/thresholds remain exact. The new bounded live sequence is authorized only after user approval, canonical application, performance recovery and request checks; earlier failed runs remain immutable failures. Cap failure or deterministic fidelity failure blocks with evidence, never automatic structural work, more output or visual approval.
- Left open: user approval/amendment of the two-task follow-up and the explicit brief output increase from 4k to 8k. The current builder question is not settled by this draft. No fidelity approval is requested for a nonexistent HIGH reference prototype; original visual STOP and backend final re-audit remain required.
- Next: review the proposal with the user; after approval apply canonical docs top-down, stamp/lint and reopen through blueprint.py. First builder: backend 24.11, gpt-6.1-sol high (Spec without STOP: deep); later 24.12 uses gpt-6-astra high (Spec plus visual STOP: frontier). Release integration follows at the program root after backend acceptance.

## 2026-10-26: Interview adjustable generation budgets and hidden assumptions
- User direction: ask about current assumptions one at a time, including thinking and token caps; make caps adjustable across prompt/brief creation and HTML generation. Attached usage: 6,632 input + 32,298 output = 38,930 total. It does not independently establish thinking accounting or a per-page requirement.
- What changed: docs/change-runtime-assumptions-interview.md records verified defaults, current HIGH brief-cap failures, the one-question queue and pending adjustment-mechanism choice; PRD Open questions links it. Architecture/essentials/plan/task markers and product code remain unchanged. The earlier 8k follow-up is still unapproved and is no longer the complete proposed response to the user's request.
- Evidence/decisions: narrow source/doc inspection and read-only blueprint_explorer mappings. Both reference stages already request HIGH. Brief output is 4k, HTML output 16k; input/repair/prose/time limits are separate. The existing app settings expose model names but not these controls. Keep already approved HIGH and ask only unresolved choices. Any Settings/API/frontend interface work needs program-root coordination before implementation.
- Checks: blueprint lint PASS (85 tasks, 0 errors, 16 existing size warnings). No product/offline/live tests or model calls run for this interview; prior full-suite failure (1 timing failure, 1896 passed, 17 deselected) is historical, not a new baseline run. No dependency or architecture changes; no stamp/registry check required.
- Left open: answer question 1 (where settings are adjusted), then review output/input/thinking/prose/deadline/retry/handoff/layout/observability assumptions individually. 24.11 remains blocked; no fidelity acceptance or other proposal approved by inference.
- Next: continue the interview in this chat and persist each answer before the next question. Builder handoff waits for the completed decisions and reviewed plan.

## 2026-10-26: Runtime assumptions interview — answer 1
- User answer: A. Record app Settings with independent defaults for each stage in the interview draft and PRD. Per-build overrides were not selected. The API/frontend contract work remains to coordinate at the program root before implementation.
- Next question: default Flash HTML output cap per generation/repair call. Recommendation pending user answer: 65,536 including thinking; alternative 49,152 or a specified value. Current runtime remains 16,000, and the brief remains 4,000. No numerical default or other proposal has been approved by this answer.
- Evidence: official Google Flash 3.8 model page checked 2026-10-26 lists output limit 65,536; official thinking guide states max_output_tokens includes thought tokens. Links and caveats are in the draft. No model call, provider-route compatibility trial or product tests run; runtime/architecture/essentials/task markers unchanged.

## 2026-10-26: Runtime assumptions interview — answer 2
- User answer: A. Flash HTML output cap defaults to 65,536 tokens per generation/repair call including thinking, adjustable through the selected app Settings controls. Saved in the draft and PRD; no product implementation or cap change performed in this planning interview.
- Next question: Argon's reference-brief output cap. Recommend 32,768 as a starting ceiling for HIGH reasoning plus instructions, alternative 65,536 or a specified value. Sufficiency remains unproven; prose-length/input/deadline limits need separate decisions. The two retained 4k cap failures do not prescribe an optimum larger cap.
- Evidence/checks: direct brief-schema inspection confirms 12,000 aggregate/8,000 overall/2,000 per-slot character limits; official Argon model documentation verified 2026-10-26 lists a normal synchronous output ceiling of 65,536. No product tests or model calls run; architecture/essentials/plan/task markers unchanged. Previously successful blueprint lint remains historical; not repeated for this answer-only doc update.

## 2026-10-26: Runtime assumptions interview — answer 3
- User answer: A. Argon reference-brief output defaults to 32,768 tokens per call including HIGH thinking, adjustable in app Settings. Saved to interview draft and PRD. The already accepted Flash HTML output default remains 65,536; runtime caps are unchanged pending implementation.
- Next question: the brief's independent prose compression/character limits. Direct source/skill read confirms about 6,000 characters of guidance, 12,000 aggregate hard maximum, 8,000 overall and 2,000 per slot. Recommend removing the fixed prose-character ceilings/numeric target while preserving the output-token cap and structured/content/native-slot/security validations. Alternatives: adjustable character ceilings or keep current limits. Downstream input capacity remains a separate pending decision.
- Checks/scope: answer-only planning edits; no product code, model calls, tests, architecture/essentials/plan/task-marker changes. Existing HIGH thinking remains approved. No new claim of budget sufficiency, fidelity acceptance or approval of the older proposals.

## 2026-10-26: Runtime assumptions interview — answer 4
- User answer: A. Remove brief prose-character ceilings (12k aggregate, 8k overall, 2k per slot) and the 6k-character target, including matching skill/schema/local validation requirements. Retain the accepted output-token cap, nonempty structured fields, page/slot identity/coverage and content/security/native-component checks. Recorded in draft and PRD; no runtime changes performed.
- Next question: Flash reference-HTML complete input cap for initial/later-page/repair/revision calls, currently 12k initially and 24k repair. Recommend 131,072 per request, alternative 262,144 or a chosen number. The complete brief/images/schema/instructions/components and prior HTML consume input together. Argon revision input and counting/overflow rules are subsequent independent choices; no input value approved yet.
- Checks/scope: read current context assembly to confirm full mandatory request contents and attempt-specific caps; no model calls or product tests. Architecture/essentials/plan/task markers unchanged. Previous lint remains historical; not repeated for this answer-only doc edit. Existing 24.11 block/fidelity gates remain unresolved.

## 2026-10-26: Runtime assumptions interview — answer 5
- User answer: A. Flash reference-HTML complete input cap defaults to 131,072 tokens per call across initial/later-page/repair/revision paths, adjustable in app Settings. Retain complete-request counting, mandatory content and over-budget diagnostics. Saved in draft and PRD; runtime still uses 12k initial/24k repair pending implementation.
- Next question: Argon reference-brief input, currently 12k even when revising prior HTML. Recommend 131,072 per first/later-page/revision request, alternative 262,144 or a specified number. No-reference designer/input estimation/overflow and timeout policies remain separate pending decisions.
- Checks/scope: answer-only planning edits; no new model calls, tests or product/architecture/essentials/plan/task-marker changes. No budget sufficiency or fidelity acceptance claimed. Previously recorded lint not repeated for this answer-only doc update.

## 2026-10-26: Runtime assumptions interview — answer 6
- User answer: A. Argon reference-brief complete input defaults to 131,072 tokens per initial/later-page/revision call, adjustable in app Settings. Saved in draft and PRD; current runtime is unchanged. Both selected reference-stage input defaults are now 131,072, with output 32,768 brief / 65,536 HTML, thinking included.
- Next question: input counting allowance. Current code uses max(complete-request character estimate, folded provider count * 1.20 rounded up + 512); earlier local full-request measurement explains why a margin exists. Recommend retaining the formula with the percentage adjustable under Advanced Settings and measured/enforced counts shown separately. Alternatives remove the estimate floor or the margin. Assembly reserves, provider capacity, overflow and no-reference scope remain to settle.
- Checks/scope: direct read of context.fit_request/request_estimate and llm.counting_contents/count_tokens confirms the counting boundary. No model requests, product tests, code/architecture/essentials/plan/task-marker changes; no new provider accuracy claim or fidelity acceptance. Previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 7
- User answer: A. Keep current conservative counting formula with the 20% margin adjustable in Advanced Settings. The complete-request text estimate remains a minimum, provider count gains 20% rounded up plus 512, and measured/enforced counts are distinguished. Saved in draft and PRD; no runtime changes.
- Next question: behavior when mandatory input exceeds its configured cap. Recommend a clean pre-generation stop showing stage/enforced count/limit, letting the user change Settings and retry. Alternative: automatic input expansion up to a separate configured maximum (needs a follow-up decision). Neither choice authorizes dropping intent, silent summarization, output reduction or bypassing provider capacity.
- Checks/scope: answer-only doc edits; no model calls, product tests, architecture/essentials/plan/task-marker changes. No new pause/resume API assumed. Runtime failures, 24.11 block and fidelity gates remain unresolved; previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 8
- User answer: A. Preserve a hard configured input cap; overflow stops before generation and shows stage/enforced count/limit so the user can adjust Settings and retry. No automatic expansion or loss of mandatory facts; no new paused-run/resume API assumed. Saved in interview draft and PRD.
- Next question: make reference-stage thinking editable per stage through Settings, retaining the already approved HIGH defaults, or keep HIGH hardcoded. Recommend editable model-supported levels. Current no-reference LOW and other routes are outside this unanswered scope choice.
- Checks/scope: answer-only doc edits; no model calls or product tests/code changes. Architecture/essentials/plan/task markers unchanged, no fidelity acceptance or older proposal approved by inference. Previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 9
- User answer: A. Reference brief and HTML each gain a thinking-level selector in app Settings; both default to already approved HIGH and offer selected-model-supported levels. Apply to each stage's first/later-page/repair/revision paths as applicable. Saved in draft and PRD; no runtime implementation yet.
- Next question: independent model selectors for reference brief and HTML versus the existing shared planner/worker settings. Direct llm/config read confirms reference_brief shares planner_model with blueprint/no-reference designer and reference_html shares worker_model with other workers. Recommend independent reference-stage selectors, retaining Argon/Flash defaults. Provider-family expansion and other-route changes are not inferred; fallback is a subsequent choice.
- Checks/scope: narrow source read and answer-only planning edits; no product tests, model calls, code/architecture/essentials/plan/task-marker changes. Original runtime failures and fidelity gates remain unresolved. Previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 10
- User answer: A. Reference brief and HTML gain independent model selectors in app Settings, defaulting to Argon and Flash 3.8, avoiding changes to other planner/worker routes when experimenting with one reference stage. Saved to draft and PRD; provider-family expansion and migration behavior are not assumed.
- Next question: automatic model fallback. Existing refresh replaces unavailable planner with worker on a successful model listing, logs a warning and retains the original stored setting. Recommend stopping the affected reference stage with a clear selected-model error rather than substituting models; alternatives are an explicit labeled fallback or legacy substitution. Same-model transient retries remain separate. Failed listing is unknown availability, not proven absence.
- Checks/scope: answer-only planning edits based on the immediately preceding llm/config inspection; no new product tests, model calls, code/architecture/essentials/plan/task-marker changes. Runtime/24.11/fidelity status unchanged. Previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 11
- User answer: B, fallback is Gemini 3.8 Flash. Save explicit reference-stage fallback in draft and PRD, with actual model use visible. Primary already Flash means no self-fallback/extra duplicate generation; allowed ordinary retries remain. Preserve primary selection and distinguish requested/actual model. This does not approve changing non-reference fallback.
- Next question: fallback activation. Recommend model unavailability/overload/eligible provider failures after allowed retries; alternative also permits content/truncation/validation failures after repair. Fallback must support selected settings and pass the same hard budgets and validation. Shared deadlines and exact error policy remain pending; no extra live retries authorized by this interview.
- Checks/scope: answer-only planning edits; no code, model calls, product tests, architecture/essentials/plan/task-marker changes. Original blocked 24.11 and fidelity gates remain. Previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 12
- User answer: A. Reference-stage fallback to Flash 3.8 triggers on selected-model unavailability/overload/eligible provider errors after allowed retries. Content failures, token truncation, invalid HTML and layout failures follow their separate repair/failure policies. Preserve actual-model visibility, no self-fallback, configured hard caps/settings and total deadline. Saved in draft and PRD.
- Next question: reference-brief per-page time allowance, currently 120 s total counting/generation/retry. Recommend 600 s including any fallback, adjustable in Settings; alternative 300 s or a finite chosen time. The larger HIGH/output budget motivates headroom, not a guarantee of completion. Other nodes' 30/120 s bounds do not change by inference.
- Checks/scope: answer-only planning edits; no code, model calls, product tests, architecture/essentials/plan/task-marker changes. No new live attempts or fidelity acceptance. Previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 13
- User answer: A. Reference-brief stage defaults to 600 s (10 minutes) per page, adjustable in Settings, with one clock across count/generation/retries/fallback. Record in draft and PRD; current runtime still 120 s until implementation. No change to unrelated planner/worker deadlines, cancellation or publication guards.
- Next question: reference-HTML stage total allowance, currently 600 s shared across generation and repair. Recommend 1,200 s (20 minutes) per page to accommodate the accepted larger output budget and repair; alternative keep 600 s or specify a duration. Counting/retry/measurement/repair/fallback share that clock, not a reset per attempt. No empirical completion guarantee.
- Checks/scope: answer-only planning edits; no product code/tests/model calls, architecture/essentials/plan/task-marker changes. Existing blocked 24.11 and visual acceptance gates remain unresolved. Previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 14
- User answer: A. Reference-HTML stage defaults to 1,200 s (20 minutes) per page, adjustable in Settings; count/generation/eligible retry/measurement/repair/fallback share one deadline. Each later page has its own deadline; no per-attempt reset or cancellation/publication changes. Saved in draft and PRD; runtime remains unchanged.
- Next question: HTML content-repair count, currently one. Recommend two repairs (three generations total/page), adjustable in Settings, within the same total stage deadline and hard token limits. Alternative one or a chosen finite count. Brief repairs, output truncation and transport retries will be reviewed separately; no invalid HTML publication or component/meaning edits implied.
- Checks/scope: answer-only planning edits; no product code/tests/model calls, architecture/essentials/plan/task-marker changes. Original 24.11 block, unresolved performance issue and visual acceptance remain. Previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 15
- User answer: A. Reference HTML gets two automatic validation repairs after the first generation (three content generation attempts total/page), adjustable in app Settings. Retain latest usable draft, required reference/component meaning, hard token limits and the shared 1,200 s stage deadline. No extra publication permission for invalid output. Saved in draft and PRD; no runtime implementation.
- Next question: reference-brief validation repair, currently none. Recommend one correction attempt (two brief generations total/page), adjustable in Settings and within 600 s. HTML starts only after a valid brief; truncation handling is a separate next decision and not inferred from repair count.
- Checks/scope: answer-only planning docs; no product code/tests/model calls, architecture/essentials/plan/task-marker changes. Existing 24.11/performance/fidelity blocks remain. Previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 16
- User answer: A. Reference brief gets one automatic validation repair (two brief generations maximum/page), adjustable in Settings, within the shared 600 s stage and selected hard token budgets. HTML starts only after a valid brief. Save in draft and PRD; no runtime change.
- Next question: output token cutoff (MAX_TOKENS), distinguished from completed-but-invalid responses. Recommend stop with stage/cap/available usage and retain old artifacts, allowing manual adjustment/retry. Alternatives full regeneration within repair allowance or separately bounded continuation. No extra provider fallback, silent thinking reduction or partial publication implied; no continuation count selected.
- Checks/scope: answer-only planning edits; no code, product tests/model calls or architecture/essentials/plan/task-marker changes. Original 24.11/performance/fidelity gates unresolved. Previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 17
- User answer: A. Output-token cutoff/MAX_TOKENS stops either reference stage with stage/cap/available usage, retains previous published artifacts and allows user Settings adjustment/manual retry. It does not consume content-repair allowance, auto-continue/regenerate, change models or lower thinking. This explicitly changes the current HTML cut-output-through-repair behavior when implemented. Saved in draft and PRD; runtime unchanged.
- Next question: generation-transport retry count on eligible 429/500/503 errors before any response. Current one after 1 s; recommend two retries with 1 s/2 s delays, adjustable per reference-stage Settings, then eligible configured fallback. Preserve total stage deadline and separate validation-repair counts; no 504/post-response retry or broader route change inferred.
- Checks/scope: answer-only planning edits based on retained source mapping; no product code/tests/model calls, architecture/essentials/plan/task-marker changes. Existing 24.11/performance/fidelity blocks unresolved. Previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 18
- User answer: A. Reference-stage generation transport defaults to two retries with 1 s/2 s waits, count adjustable per stage. Preserve 429/500/503-before-response scope, same-request/effective-model retries, shared deadline, separate validation-repair allowance, no 504/post-response replay; evaluate eligible Flash fallback afterward. Save in draft and PRD; no runtime change.
- Next question: save Argon's brief as a readable Markdown artifact plus canonical JSON per page/version, JSON only, or keep internal. Direct source inspection confirms PageBrief is passed as JSON into the larger Flash request, without a standalone reference-brief Markdown export. Saving the brief does not claim to capture the entire effective Flash prompt. Review/edit gates are a subsequent choice; API/UI work needs program-root coordination.
- Checks/scope: narrow designer/reference_brief/context and artifact/API search; no model calls or product tests/code changes. Architecture/essentials/plan/task markers unchanged, prior blocks/fidelity gates unresolved. Previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 19
- User answer: A. Save readable Markdown and canonical validated JSON for each page/version's Argon brief, with inspection/download access. Distinguish the brief from Flash's entire effective request; retain slot validation and protect secrets/hidden thoughts. Saved in draft and PRD, no export/runtime implementation.
- Next question: automatic HTML handoff versus review/edit approval gate. Recommend automatic by default with a Settings option to pause per page for review/edit/approval; alternatives always approve or automatic with inspection only. Edits remain design instructions under native-slot/coverage/content validation, and later-page sequencing retains page-1 dependencies. Human-gate contracts/UI/state work must be coordinated at the program root.
- Checks/scope: answer-only planning edits; no product code/tests/model calls, architecture/essentials/plan/task-marker changes. User-facing commentary explicitly states this remains planning and the running app is unchanged. Original 24.11/performance/fidelity gates remain unresolved; previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 20
- User answer: A. HTML handoff remains automatic by default, with an app Settings option to pause per page for brief review/edit/approval. Revalidate edited design instructions and current native bindings, record the exact validated brief used and retain final visual approval as separate. Human wait is persisted outside model clocks, not an open model request. API/UI/state design requires program-root coordination. Saved in draft and PRD; no runtime changes.
- Finding: directly read dashboard-design and reference_html prompts. The generic guide describes light cards, but the reference prompt explicitly already overrides that default with reference/brief composition, hierarchy, typography, colors and spacing. No missing-priority claim or duplicate user confirmation justified. Prior explicit native-chart ownership stays settled; structural proposals remain unapproved.
- Next question: expose a separate settings profile for the single-stage no-reference HTML designer (currently LOW, 12k input, 16k output, planner model, 120 s provider request, one repair and kit fallback), or retain reference-only controls. Recommend exposing applicable controls separately, then review its defaults without copying the reference settings by assumption.
- Checks/scope: direct prompt/PRD read; no product code/tests/model calls, architecture/essentials/plan/task-marker changes. Original 24.11/performance/fidelity gates remain unresolved; previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 21
- User answer: "Yes please, but make it configurable". Include the single-stage no-reference HTML designer in its own independent Settings profile, with applicable model/thinking/token/time/retry/repair controls. Save in draft and PRD. Do not infer copying reference defaults, changing kit fallback, or adding an Argon-brief gate to this one-stage route.
- Next question: starting no-reference token-budget policy. Recommend matching reference HTML's 131,072 input / 65,536 output (thinking included) while storing/editing them independently; alternatives retain current 12k/16k or choose a pair. Model/thinking/time/failure defaults remain separate upcoming choices. Explicit numerical approval is needed before superseding old no-reference request fingerprints.
- Checks/scope: answer-only planning docs; read-only explorer follow-up maps other upstream knobs for the remaining interview. No code/tests/model calls or architecture/essentials/plan/task-marker changes. Existing 24.11/performance/fidelity gates unresolved; previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 22
- User answer: A. No-reference HTML starts with 131,072 input / 65,536 output including thinking, stored and editable independently of the reference profile. This explicitly approves the numerical default changes, superseding no-reference fingerprint preservation only for these budgets; other behavior remains pending. Save in draft and PRD; no runtime change.
- Next question: no-reference model default, currently Argon in a combined design/HTML stage without a separate brief. Recommend keeping editable Argon default; alternatives Flash 3.8 or another compatible model. Thinking/time/repair/retry/failure defaults still upcoming, not copied implicitly.
- Additional findings: read-only explorer mapped upstream LOW/default thinking and separate budgets, profile compression, dropped observation context, and count/repair ceilings. Saved a concise map and remaining questions in the draft; no claim these caused a specific failure. Larger HTML caps do not settle those upstream choices.
- Checks/scope: no product code/tests/model calls or architecture/essentials/plan/task-marker changes. Original 24.11/performance/fidelity gates remain unresolved; previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 23 and expanded routing scope
- User answer: B, Flash 3.8 for no-reference HTML. Additional explicit direction: independently choose a model at every stage including interview; defaults Flash 3.8 interview/execution, Argon dashboard analysis and fully detailed HTML prompt, Flash 3.8 LOW for routine model work. Record in draft/PRD; preserve already approved reference brief/HTML HIGH. Other thinking values and broader analysis scope remain open; deterministic work remains code. Complete relevant intent/bindings/constraints are required, without arbitrary prompt-length compression or secrets/source rows.
- Next question: should no-reference HTML also use Argon briefing followed by Flash execution? Recommend the two-stage route for both modes, reusing configured brief parameters while retaining no-reference execution controls; alternative is one Flash design/code stage without reference. This additional model stage is not inferred merely from choosing Flash execution or changing labels.
- Scope: model-selector coverage now extends beyond the three generation profiles; record every selected/effective model and validate supported settings. Upstream thinking/token caps and native planning role still need review; no blanket copying or token cap increases approved for those stages yet.
- Checks: planning docs only; no product code/tests/model calls, architecture/essentials/plan/task-marker changes. Running app and 24.11/performance/fidelity blocks unchanged; previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 24
- User answer: A. Both reference and no-reference HTML use Argon analysis/full briefing followed by Flash execution. No-reference now gains a brief stage reusing the configured brief profile, with no invented image; retain independent execution profile and enabled inspection/review flow. Save in draft and PRD. This explicitly supersedes the old one-stage no-reference assumption, not its unrelated validation/publication rules.
- Next question: Argon analysis thinking for reference interpretation and native chart/metric/data planning. Native Blueprint is currently Argon LOW; reference extraction has no explicit thinking setting. Recommend HIGH, with MEDIUM/LOW alternatives and independent stage selectors. Existing extraction 4096/Blueprint 6000 output caps need a separate increase/time review before implementing HIGH.
- Checks/scope: planning docs only, using retained explorer source evidence; no product code/tests/model calls, architecture/essentials/plan/task-marker changes. Original 24.11/performance/fidelity gates remain unresolved. Previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 25
- User answer: A. Argon HIGH defaults for reference interpretation and native chart/metric/data planning, independently configurable. Save in draft and PRD. This changes native planning's current LOW and makes interpretation thinking explicit when implemented; current runtime unchanged.
- Next question: analytical token defaults, currently interpretation 12k input/4096 output and planning 14k/6000. Recommend independently stored 131,072 input/32,768 output including thinking for both, matching brief starting budgets. Alternative 65,536/16,384 or specified values. Scope/observation/profile compression caps and deadlines remain separate upcoming choices; larger token values alone do not remove those limits.
- Checks/scope: answer-only planning edits using retained source evidence; no product code/tests/model calls, architecture/essentials/plan/task-marker changes. Original 24.11/performance/fidelity gates remain unresolved; previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 26
- User answer: A. Argon reference interpretation and native chart/metric/data planning each default to 131,072 input / 32,768 output including thinking, independently adjustable in Settings. Save in draft and PRD; runtime still uses smaller historical budgets pending implementation. Scope/profile/detail truncation caps remain separate.
- Next question: each analysis stage's total time. Current interpretation provider bound 30 s, native planner request 120 s. Recommend 600 s/stage, alternative 300 s or specified finite values, covering counting/generation/retry/repair/fallback under one clock. This is per analysis action, not per page/attempt; unrelated upload/profile/query/engine limits stay outside this default change.
- Checks/scope: answer-only planning docs using retained router/source evidence; no product code/tests/model calls, architecture/essentials/plan/task-marker changes. Original 24.11/performance/fidelity gates unresolved; previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 27
- User answer: A. Each Argon analytical stage defaults to 600 s total, independently adjustable. Count/generation/eligible retry/repair/fallback share one action-level clock; provider request limits align to remaining time. It is not per page/attempt, nor a change to unrelated upload/profile/query/engine bounds. Save in draft and PRD; runtime unchanged.
- Next question: no-reference Flash HTML execution thinking, currently LOW, now following the approved Argon brief. Recommend HIGH to match reference execution, independent selector; alternatives MEDIUM/LOW. Routine Flash work stays LOW and the accepted 65,536 output cap includes thinking.
- Checks/scope: answer-only planning docs; no product code/tests/model calls, architecture/essentials/plan/task-marker changes. Original 24.11/performance/fidelity gates remain unresolved; previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 28
- User answer: A. No-reference Flash HTML execution defaults to HIGH, independently configurable from reference execution. Both execution routes now have HIGH defaults; routine model work remains Flash LOW. Save in draft and PRD; no runtime change.
- Next question: copy the previously selected execution operating preset to no-reference (1,200 s/page shared clock, two validation repairs, two eligible retries with 1 s/2 s waits), independently editable, or choose/retain other defaults. These are already explained knobs; standard-kit fallback and common failure-policy scope remain separate explicit decisions.
- Checks/scope: planning docs only; no product code/tests/model calls or architecture/essentials/plan/task-marker changes. Original 24.11/performance/fidelity gates unresolved; previous lint not repeated for this answer-only update.

## 2026-10-26: Runtime assumptions interview — answer 29
- User answer: A. No-reference execution starts with 1,200 s total/page, two validation repairs and two eligible service retries (1 s/2 s waits), all independently editable from reference settings. The shared outer stage clock is new for this route and must control provider request deadlines/remaining time. Save in draft and PRD; runtime unchanged.
- Next question: no-reference standard-layout kit fallback after completed HTML exhausts validation repairs. Recommend retain automatic fallback with clear labeling and a Settings switch; alternatives manual choice or stop/retry. Preserve actual native components/definitions/coverage. Input/output hard caps, cancellation, service/timeout failures and other stages are not implicitly reclassified by this layout-specific choice.
- Checks/scope: answer-only planning docs; no product code/tests/model calls, architecture/essentials/plan/task-marker changes. Original 24.11/performance/fidelity gates unresolved; chronological answer headings 1-28 were checked directly in the preceding turn. No product validation claimed; previous lint not repeated.

## 2026-10-26: Runtime assumptions interview — answer 30 and closed handoff
- User answer: A. Automatic standard-layout fallback for no-reference pages after completed HTML exhausts layout repairs, clearly labeled and configurable. User ends hypothetical questions and directs necessary file updates, frontend-task re-audit and a fresh-context handoff. Record in draft/PRD; no more questionnaire STOPs.
- What changed: closed the interview after all 30 answers, resolved unasked items by preserving current behavior/documented technical defaults, and created docs/HANDOFF-stage-settings.md with accepted stage table, exact policies, runtime/evidence distinctions, unresolved real performance/fidelity work and a program-root execution brief. Canonical cross-part architecture/contracts/tasks are assigned to the fresh session; this session does not report them or the frontend re-audit complete.
- Ownership: this closing session edits only the backend interview/handoff/PRD/progress. Fresh program-root architect owns canonical docs/contracts/backend/frontend tasks and independent frontend delta re-audit. Only backend is a saved app project; fresh chat must explicitly use the parent program root for the newly authorized cross-part planning work.
- Checks: blueprint lint PASS (85 tasks, 0 errors, 16 existing size warnings). Direct check finds 30 answered decision entries and no Pending question entry; progress answer headings are chronological. No product code/tests/model calls changed or run. Existing 24.11/performance/real visual approval remain open. Fresh-session dispatch follows this completed handoff; canonical/frontend audit is not claimed here.



## 2026-10-26: Stage Settings independent delta audit — coordination hold
- Scope: authorized program-root cross-part planning continuation of the closed 30-answer interview. Read-only frontend/backend source inventories and a fresh independent blueprint_reviewer first pass completed.
- Coordination: another writer changed API to3.0, conventions1.4, program/backend/frontend plans during preparation. Canonical edits paused to prevent overwrites; user ownership question pending. This session parked only its eight new unreferenced alternative draft files under .blueprint/parked-model-stages-draft/ and disabled its scratch apply script. No product code/task markers/retained failures changed by this session.
- Findings: 6 P1 + 1 P2 in docs/stage-settings-reconciliation.md: independent stage selectors, explicit legacy migration, layout-only fallback, hard-cap live retry, durable effective Settings, concurrent brief approval identity, complete persisted frontend review lock. Not builder-ready or independently accepted yet.
- Checks: release contract baseline command exited0 with all13 checks passed; no product tests/model calls/new performance or visual results. No final stamp/lint or final audit claimed while canonical ownership is unresolved.
- Next: settle writer ownership, reconcile the concrete defects, final independent delta review, mechanical checks and affected-part progress records, then hand off backend24.11. Existing performance/fidelity/real visual STOP remain.

## 2026-10-26: Change configurable model stages (program root)
- Source: user interview closed after 30 answers (backend/docs/change-runtime-assumptions-interview.md, backend/docs/HANDOFF-stage-settings.md); user cards 2026-10-26 (this session owns the change over a parallel architect session; grouped selectors; standard layout only after HTML repairs; migration keeps every explicit legacy model) and the user's request to add cost estimates in the frontend.
- Contracts: api.md 3.0 (Settings breaking: stage profiles, fallback_model, review_briefs, notices, issues; capabilities with verified prices; design-pages, brief review with revision/sha256, run calls with the settings snapshot and costs, build cost; event brief.review; stage-limit error codes), conventions.md 1.4 (legacy model env names only seed the migration; brief files and review candidate paths); fixtures in contracts/fixtures/stage-settings/ (api/settings.json kept until backend 25.1 and frontend 16.1, then removed by the architect).
- Checks: `blueprint.py lint` 0 errors in release, backend, frontend and engine; backend `stamp`; `uv run --project integration python integration/check_contracts.py` all 13 checks passed; every stage-settings fixture parses. Independent reviews: delta audit: 2 P1 + 9 P2 + 5 P3, all applied; user cards on 4 conflicts; re-review after cards and the cost request: 0 P0/P1, 3 P2 + 5 P3, all applied.
- Not run: no product code, tests, live models or paid calls. Backend's uncommitted HIGH-request code from blocked 24.11 stays for 24.11's first If to commit.
- What changed: architecture.md sections Stage settings, Stage execution, Design briefs, Feasibility recomputation performance preservation; change notes atop Blueprint, Blueprint observation coverage, Working memory assembly, Reference interpretation, Designed pages, Reference design brief, Reference HTML composition, Reference thinking comparison (historical); Graph model check; 9 decision rows; essentials, PRD (Decided by default, Open questions), AGENTS.md gotcha note. Plan: blocked 24.11 rewritten to the recomputation-budget recovery and reopened; Phase 25: 25.1 settings (M), 25.2 stage execution (L), 25.3 fallback, calls and costs (M), 25.4 briefs and artifacts (M), 25.5 no-reference brief -> HTML and labeled standard layout (M), 25.6 brief review (L), 25.7 live fidelity with the visual STOP (M).
- Settled requests: the 24.11 block question ("What approved follow-up resolves the brief cap and timing failures before fidelity acceptance?") -> planned as 24.11 (timing) and 25.1-25.7 (configurable caps, live check). docs/change-24.11-high-followup.md's 8k cap is superseded; docs/change-24.11-fidelity.md stays unselected. docs/stage-settings-reconciliation.md (parallel session) resolved and marked historical.
- Next: 24.11 in backend/.

## 2026-10-26: Task 24.11 Restore the deterministic recomputation budget
- Status: done
- Plan check: off
- What changed: requirements/feasibility share classification and literal definition parsing within evaluate; 13 purity/invalidation regressions. Baseline, profiles, assessments and mutation comparisons: .blueprint/qa/task-24.11/recompute-performance/.
- Checks: feasibility module PASS (265; 122.76s); corrected module plus compatibility cases PASS (268; 133.50s); full `uv run pytest` PASS (1910; 17 deselected; 1220.87s). Exact ready/blocked best: 90.501/101.761 -> 73.325/88.690ms. 24 checkpoint comparisons equal (assessment id only excluded); six original speed functions source-identical. Review: no findings.
- Decisions: parsing key = full text, complete Mapping JSON, ordered schema; no cross-call state or skipped candidate validation. Catalog/env/registry unchanged. AGENTS.md records positional test-hook compatibility. Folder mode; prior HIGH requests and older evidence untouched.
- Digest: requirements.evaluate reuses classification and definition parsing only within its call; blueprint_observations accepts requirement_issues; feasibility diagnostics/issue_rows accept observations. Assessment, coverage, provenance and contracts unchanged.
- Tried and failed: first full suite had three positional-hook failures; forwarding fixed. Initial sandbox/interference diagnostics documented in QA README.
- Gotchas: recorded in AGENTS.md.
- Left open: none.
- Next: 25.1 Stage profiles in Settings and the 3.0 settings routes.

## 2026-10-27: Task 25.1 Stage profiles in Settings and the 3.0 settings routes
- Status: done
- Plan check: off
- What changed: Stage profiles, atomic validation/merge/migration, capabilities; recipe validation dispatch.
- Checks: `uv run pytest tests/test_stage_settings.py tests/test_api_contract.py tests/test_cloud_mode.py` PASS (240); expanded compiler acceptance PASS (323); full `uv run pytest -x` PASS (2082; 17 live deselected; 1193.65s). Reviews: no findings.
- Decisions: planner=native_planning, worker=routine until 25.2. Compiler/test_compiler outside Files fixed required timing failures, preserving validation. Folder checkpoint preserves pre-existing Git work; AGENTS.md gotchas added.
- Digest: Config.stages holds 7 profiles; SettingsStore migrates once and merges per field. public(): notices/issues. GET /api/settings/capabilities; ModelRouter.available=None|set, planner=native_planning, worker=routine. Compiler validates unique op branches.
- Verified 2026-10-26: [Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash) and [Argon](https://ai.google.dev/gemini-api/docs/models/gemini-4-argon): max inputs 1,048,576 (Argon unified context), synchronous outputs 65,536, images, low/medium/high. [Prices](https://ai.google.dev/gemini-api/docs/pricing), USD/M input/output, both checked_on=2026-10-26: Flash 0.75/3.75; Argon 2/10.
- Tried and failed: full timing best 101.98/120.29ms; profiled compiler bottleneck, isolated best 86.08 -> 21.80ms; evidence .blueprint/qa/task-25.1/. Agent transport retries passed unchanged.
- Gotchas: recorded in AGENTS.md.
- Left open: none.
- Next: 25.2 Every model node runs from its stage profile; frontier work.

## 2026-10-27: Task 25.2 Every model node runs from its stage profile
- Status: partial
- Plan check: off
- What changed: Started task; folder checkpoint .blueprint/snapshots/task-25.2-1.zip. No implementation edits. Read-only execution map completed.
- Checks: Not run; stopped before implementation on a plan/Spec conflict.
- Decisions: Await user authorization before changing behavioral test expectations: task permits numeric updates only and says any other changed expectation is a block.
- Tried and failed: None.
- Gotchas: None.
- Left open: tests/test_designer.py:197-202 requires repair after cutoff; :149-154 requires fallback on overflow; :261-266 requires Argon for designer. Stage execution instead requires hard stops and html_no_reference Flash. tests/test_reference_brief.py:449-463 also pins one-call invalid/cut Fallback behavior.
- Next: Resolve the assertion-update exception with the user, then implement 25.2. Proposed exception: update only assertions directly superseded by change 2026-10-26 (routing, profile settings, clock/retry/repair behavior, overflow/cutoff codes); preserve unrelated assertions. Core execution stays with the primary agent; reviewer required after checks.

## 2026-10-27: Task 25.2 Every model node runs from its stage profile
- Status: done
- Plan check: off
- What changed: Snapshot-based routing, explicit thinking/caps, action/page deadlines, bounded transport retries and atomic overflow/cutoff stops.
- Checks: `uv run pytest tests/test_stage_execution.py tests/test_llm_retry.py tests/test_llm_timeouts.py tests/test_reference_brief.py tests/test_designer.py -q --tb=short` PASS (190, 212.45s); `uv run pytest -q --tb=short` PASS (2132, 17 live deselected, 971.02s). Final review: no findings.
- Decisions: User approved superseded behavioral assertions. Delegated decided regression updates only. Judge snapshot wiring and context/revision/graph/audit regressions outside Files were necessary. Snapshot lives on the first existing span; availability is private. No-reference HTML uses html_no_reference until 25.5; brief repair remains 25.4; runtime fallback/call records remain 25.3. AGENTS.md gotchas added; no dependency changes.
- Digest: stages.Execution(config,trace,available=...) snapshots; record() stores first-span settings. StageSession/StageClock and llm.bind_model/provider_model share action/page deadlines; fit_request records folded_request_tokens/enforced_input_bound.
- Tried and failed: Fixed ADK callback wrapping, routine retry timeout scope, deadline error masking, partial-MAX handling and a delegated-stream test fake. Updated stale budget/repair oracles.
- Gotchas: Recorded in AGENTS.md.
- Left open: none.
- Next: 25.3 Visible model fallback and stage call records; deep work.



## 2026-10-27: Task 25.3 Visible model fallback and stage call records
- Status: done
- Plan check: off
- What changed: Bounded, sticky model fallback; private persisted StageCalls; calls/cost routes; per-page actual HTML models; semantic rejection outcomes.
- Checks: `uv run pytest tests/test_stage_execution.py tests/test_api_contract.py tests/test_usage_events.py` PASS (129); Test (all) `uv run pytest` PASS (2163, 17 live deselected); reviewer: no findings after P1/P2 fixes.
- Decisions: Calls share the snapshot span; routine/interview sessions use node identity. Extra Files: request counting, page assembly, and Brief/Blueprint/reference/Context/revision validation hooks for accurate records. No dependencies. AGENTS.md adds the execution-alias gotcha. Earlier work backed up; final zip checkpoint avoids committing overlapping prior changes.
- Digest: `StageSession.actual_model`, `invalid_output(node)`; snapshot span holds calls. `episodic.run_calls(db, run_id)` / `build_cost(db, build_id)` back 3.0 routes; `Designed.model` preserves per-page HTML attribution.
- Tried and failed: Review hooks initially hit local name/alias collisions and an incomplete response fake; corrected and reverified.
- Gotchas: Recorded in AGENTS.md.
- Left open: Git commit deferred because prerequisite changes are uncommitted in shared files.
- Next: 25.4 Uncapped briefs, brief repair and saved brief artifacts.

## 2026-10-27: Task 25.4 Uncapped briefs, brief repair and saved brief artifacts
- Status: done
- Plan check: off
- What changed: Removed prose/report cuts; added profile repairs, canonical JSON/Markdown, page provenance, legacy-aware design-pages and atomic accept/revise publication.
- Checks: `uv run pytest tests/test_reference_brief.py tests/test_design_briefs.py tests/test_publication.py tests/test_api_contract.py` PASS (158); Test (all) `uv run pytest` PASS (2183, 17 live deselected, 4 warnings). Review: P1 fixed; re-review no findings.
- Decisions: design-pages.json keeps metadata outside DashboardSpec. Extra Files render.py/revise.py wire both publication paths; brief-only redraws increment spec_version. Preserved overlapping prior work using folder checkpoints. AGENTS.md records the redraw gotcha.
- Digest: PageBrief prose uncapped; reference_brief.record/canonical/markdown; designer.design/regenerate(..., briefs=dict); publication.design_artifacts -> {filename:bytes|None}; design-pages.json holds {spec_version,pages}; GET design-pages includes legacy projection.
- Tried and failed: Review regression proved an identical redraw dropped its new brief; corrected.
- Gotchas: Recorded in AGENTS.md.
- Left open: none.
- Next: 25.5 Pages without a reference: Argon brief, Flash HTML and the labeled standard layout; extend the brief collector and sidecar publication.

## 2026-10-27: Task 25.5 Pages without a reference: Argon brief, Flash HTML and the labeled standard layout
- Status: partial
- Plan check: off
- What changed: Attempt set aside; checkpoint restored. The attempt explored two-stage no-reference generation and deterministic revision fallback.
- Checks: `uv run pytest tests/test_design_briefs.py -q --maxfail=3` PASS (26 passed); task checks with `--maxfail=5` FAIL (5 failed, 156 passed); targeted prototype/revision fixtures PASS (8 passed). Test (all) not run.
- Decisions: The attempt is recoverable in `.blueprint/attempts/task-25.5-20261027-084338/`; it is not a completed implementation.
- Tried and failed: Revision failure test twice reported `Standard layout is unavailable; previous prototype retained`, instead of retaining its detailed pending-comment diagnostic. Setting the defaults' `layout_fallback` to false did not affect the active run in the second attempt.
- Gotchas: Task 25.5 is larger than its M sizing: it changes prototype and revision routing, fallback reconstruction, fixtures and publication metadata together.
- Left open: No review was run; acceptance checks and full suite remain.
- Next: Resume 25.5. Inspect how persisted Settings and stage snapshots override test defaults, then recover only useful pieces of the set-aside attempt; verify hard-stop behavior and revision fallback with a real design artifact before rerunning the checks.

## 2026-10-27: Task 25.5 Pages without a reference: Argon brief, Flash HTML and the labeled standard layout
- Status: done
- Plan check: off
- What changed: No-reference prototypes/revisions now generate an image-free brief before HTML. Completed invalid HTML alone permits labeled standard layout; hard stops preserve publication. Revisions run page 1 first, then later pages in parallel.
- Checks: `uv run pytest tests/test_designer.py tests/test_design_briefs.py tests/test_revise.py` PASS (196 passed); Test (all) `uv run pytest` PASS (2202 passed, 17 deselected, 4 warnings); independent review: no remaining findings.
- Decisions: Rebuild revision fallback from the saved Design and current native components. Protected decorations refuse generation rather than bypass fallback rules. Extra Files: publication.py preserves explicit fallback provenance; five shared test modules update routing, traces and the intentional prompt golden. AGENTS.md records persisted Settings/fake-routing pitfalls.
- Digest: reference_design prepares both brief/HTML routes; ReferenceDesign.design supplies revision kit fallback. Page-1 redraw precedes parallel siblings. design_artifacts preserves layout_fallback across revisions; unattempted pages have null html_model.
- Tried and failed: Old single-reply fakes and trace/golden expectations failed under the new stage; updated them. Review caught bypasses, ordering, prompt intent and provenance; all fixed and verified.
- Gotchas: Recorded in AGENTS.md.
- Left open: none.
- Next: 25.6 Optional per-page brief review.

## 2026-10-27: Task 25.6 Optional per-page brief review
- Status: done
- Plan check: off
- What changed: Persisted reviews pause accept/revise outside clocks; edit, approve and cancel resume exact briefs. Shared guards protect writes after awaits; restart preserves candidates and honors terminal publication journals.
- Checks: `uv run pytest tests/test_brief_review.py tests/test_api_contract.py -q` PASS (84); `uv run pytest -x` PASS (2237, 17 deselected). Pause and stale-backup regressions failed before fixes; independent re-review: no findings.
- Decisions: Extra files render.py and artifacts/state.py own accept finalization and shared reservation. Retain task-start folder checkpoint; existing SQLite backup boundary applies to receipts. AGENTS.md adds route/guard/recovery gotchas.
- Digest: `BriefGate` persists per-page accept/revise continuations; GET design-pages exposes review; PUT/approve/cancel `/briefs/review`; `episodic.require_no_brief_review` guards writes after awaits; terminal journals retire stale ownership.
- Tried and failed: Fixed request-repair variable, nested-router inventory and four review findings; two agent timing flakes passed unchanged in isolation and final full run.
- Gotchas: Recorded in AGENTS.md.
- Left open: none.
- Next: Task 25.7 live defaults and reference fidelity approval.


## 2026-10-27: Task 25.7 Live stage defaults and reference fidelity approval
- Status: blocked
- Plan check: off
- What changed: tests/live/test_reference_design.py moved to 3.0: PUTs capability defaults, records StageCalls/costs per run and build, checks html_brief -> HTML from each run's snapshot, design-pages/brief hashes, review edit/approve in the none case, globe-centre DOM check and visible-issue inventory; evidence .blueprint/qa/task-25.7/ (README.md). Fixture README updated.
- Checks: focused `uv run pytest tests/test_reference_brief.py tests/test_designer.py tests/test_design_briefs.py tests/test_brief_review.py tests/test_render.py tests/test_revise.py` PASS (365; 520.63s). Live `uv run pytest -m live tests/live/test_reference_design.py` FAIL (1 passed none, 2 failed; 1445.67s). Test (all) not run (block).
- Decisions: review_briefs exercised in the none case (one design action, three pauses). Clipped scorecards/axis labels recorded, not asserted (inspect at STOP). Test edits kept and committed unreviewed.
- Tried and failed: recreate blueprint `stage_timeout` (Argon high, enforced 6,395, no response in 599,296 ms); style reference_extract schema-invalid (169 + 1,489 thinking), 0 repairs -> llm_unavailable. No rerun. User-requested benchmark (timeout 3,600): blueprint 334.8 s, attempt 1 239.4 s with 25,240 thinking tokens (cap 32,768); then blocked on unapproved observation 'Location (%)' (legend read as a chart).
- Gotchas: in AGENTS.md.
- Left open: recreate/style/later-page/revision fidelity; visual STOP; reviewer pass on the test edits; full suite.
- Blocked because: (b) passing needs a default stage Settings or plan ruling (no reruns, no default changes allowed here).
- Question: Which native_planning/reference_interpretation defaults (timeout, thinking, repairs) and which extra drop for the legend-as-chart observation should 25.7 use?
- Options: A architect rules on defaults (contract table) plus the drop class, then rerun 25.7 / B keep defaults and allow one rerun per case as provider variance / Recommend: A: 25k thinking tokens in 239 s makes 600 s and 32,768 marginal, not variance.
- Next: new backend chat, `best` high, /blueprint-solution-architect; evidence .blueprint/qa/task-25.7/README.md.

## 2026-10-27: Change 25.7 block: native planning defaults (api.md 3.1)
- What changed: contracts/api.md 3.1 and stage-settings fixtures (capabilities, settings, run_calls): native_planning default output_tokens 32,768 -> 65,536, timeout_s 600 -> 1,200 per action. Task 25.7 rewritten to apply those defaults (S, reopened); the live fidelity check moved to new task 25.8 (Depends on 25.7). Essentials and architecture decision log updated, stamped.
- Why: 25.7 blocked (question (b)): recreate blueprint `stage_timeout` at 600 s; a 3,600 s benchmark used 25,240 thinking + 2,060 answer tokens of 32,768 in 239 s. User cards 2026-10-27: raise the caps (not thinking medium, not a test-only override); treat `llm_unavailable` from a schema-invalid answer on a 0-repair stage as transient (one rerun); drop the Rural/Urban legend however it is extracted (the 'Location (%)' chart misread included).
- Decided by default: stored Settings (seeded from 3.0) keep 600/32,768; no migration. A local app picks up the new defaults only after native planning is edited in Settings.
- Affected: backend 25.7, 25.8; release 2.6 now `Needs: backend 25.8`. Frontend: version reference only.
- Change requests: the 25.7 question (defaults and the legend drop) is settled: planned in 25.7 and 25.8.

## 2026-10-27: Task 25.7 Native planning defaults follow api.md 3.1
- Status: done
- Plan check: off
- What changed: stages.defaults() native_planning output_tokens 32,768 -> 65,536 and timeout_s 600 -> 1,200 (api.md 3.1); nothing else moves. New test_stored_native_planning_values_override_new_defaults: stored 32,768/600 read back unchanged across a restart, rows untouched.
- Checks: `uv run pytest tests/test_stage_settings.py tests/test_api_contract.py` PASS (228; contract-defaults test failed 65536 != 32768 before the change); Test (all) `uv run pytest` PASS (2241 passed, 17 deselected, 1571.95 s). No live models.
- Decisions: Outside Files, edited tests that hard-coded the old defaults: test_blueprint.py:100, test_llm_retry.py:178, test_llm_timeouts.py:26, test_stage_execution.py (scale 2 for blueprint clock, 65536 cap). Also rewrote test_reference_brief's live-assertion unit test to the current `assert_design_stages(spans, spec, mode, settings, design_pages)` signature (4 failures left by the blocked earlier 25.7 attempt, not this change); its reject cases now cover profile bound/output/model/truncation/design_failed. Stored Settings keep their values (no migration).
- Digest: stages.defaults()['stages']['native_planning'] = output_tokens 65536, timeout_s 1200 (api.md 3.1); other stages unchanged; stored Settings override defaults, no migration. Tests for blueprint clock/caps expect 1200 s/65536.
- Tried and failed: none
- Gotchas: none
- Left open: P3 stale `MAX_OUTPUT_TOKENS = 32768` in src/dss/harness/nodes/blueprint.py:26,280 (profile overrides it); P3 "Settings 3.0" docstrings in stages.py:1 and test_stage_settings.py:1.
- Next: Task 25.8. Start by reviewing the committed live test edits (tests/live/test_reference_design.py 3.0) and .blueprint/qa/task-25.7/ evidence.

## 2026-10-27: Task 25.8 Live stage defaults and reference fidelity approval
- Status: blocked
- Plan check: off
- What changed: 25.8 harness/fixture README: 3.1 defaults, approved legend chart drop, corrected fallback oracle. Evidence: `.blueprint/qa/task-25.8/README.md`.
- Checks: Focused 368 passed/548.63s; harness 24 passed/0.29s; live 2 failed/1 passed/738.55s; sole retries 1 failed/1 passed/651.06s; `uv run pytest` 2258 passed/1038.50s.
- Decisions: Runtime/defaults/fixtures unchanged. Reviewed harness edits uncommitted; ZIP preserved. None/style: four designed pages each, no fallback; edited brief hash matched. P1 resolved.
- Tried and failed: Recreate extraction twice: `llm_unavailable`, StageCall `invalid`, Argon high, zero repairs, no publication. Retries exhausted; fidelity/revision/STOP unavailable.
- Gotchas: none.
- Left open: P2 both smoke page-1 scorecards clip decimals; P2 style page-2 axes overlap. Slots/screenshots/costs in QA README.
- Blocked because: (b) runtime fix needs planning outside Files.
- Question: What repair should precede another recreate acceptance run?
- Options: A plan extraction fix / B change defaults, reauthorize acceptance / Recommend: A, preserve defaults.
- Next: New backend chat, gpt-6.1-sol high, `$blueprint-solution-architect`.

## 2026-10-27: Change 25.8 diagnostics before choosing an extraction repair
- What changed: architecture.md#Reference extraction diagnostics specifies bounded, sanitized boundary/category/path evidence on the existing span, plus truthful local-validation StageCall outcomes; essentials updated and stamped. Task 25.8 (M) gains the runtime/diagnostic-test Files and an offline prerequisite, followed by one fresh recreate attempt in the full live file with `-x`. Added a narrow Reference live acceptance heading without changing that oracle. No new task, dependency, contract, model default, fixture or product-code change.
- Why: reviewed the 25.8 block, its QA README/runs, reference_extract, tracing/stages and the existing invalid-reference regressions. The evidence proves two invalid outcomes before publication, not specifically schema-invalid observations: provider response errors, empty replies, JSON decoding and provider-schema rejection share `invalid`; local Pydantic details are discarded and a local-only box-invariant rejection can leave its call `ok`. Raw replies were not retained, so the precise old failure is unrecoverable. A guessed extraction repair is not justified.
- Ruling: diagnostics first, without changing strictness, prompts, normalization, repairs, fallback, budgets or lifecycle. Preserve all old evidence in place; new evidence gets fresh timestamped folders and a new summary. The existing failed recreate pair stays exhausted: after offline diagnostic checks, the first recreate reference action is the single new diagnostic attempt, with no separate paid probe and no new recreate-extraction retry for any error class. A failure blocks before later actions/cases; a valid response may continue that same case. Full live checks and visual approval still gate completion; a clean response does not establish that the intermittent defect was repaired.
- Change requests: the 25.8 request for an extraction repair is settled as planned diagnostic work inside 25.8; choose an actual repair only from the resulting classified evidence. Changing defaults is declined for this ruling because no recorded timeout/cutoff/overflow explains these failures and default changes are reserved for the user. No earlier unresolved change request is introduced or silently accepted.
- Checks: `blueprint.py stamp` and `blueprint.py lint` PASS (0 errors, 16 size warnings); backend-doc `git diff --check` PASS. Independent blueprint_reviewer: no findings; explorer confirmed the ambiguous failure mapping. No pytest or live/provider call run in this documentation session; prior builder results are read as evidence only.
- Decisions: keep 25.8's ID and fidelity meaning rather than replace an acceptance gate with a diagnostic-only completion. The diagnostic scope fits its current M session; block with evidence if an actual fix is needed outside that scope. POC change reviewed narrowly; no dependency lookup needed because dependencies are unchanged.
- Left open: full recreate/later-page/revision fidelity and user visual approval; previously observed scorecard decimal clipping and style page-2 axis overlap remain acceptance concerns. Pre-existing uncommitted edits to tests/live/test_reference_design.py and tests/data/reference_design/README.md are preserved untouched; the builder must preserve/checkpoint them before starting, never discard them to clean the tree. Normal process access confirms Git mode; sandbox status falsely reported folder mode.
- Next: reopen 25.8 with the blueprint script and hand off in backend/ to gpt-6-astra high (frontier: Spec plus visual STOP). Implement and verify diagnostics before any new live call; keep earlier live test edits and evidence intact.


## 2026-10-27: Task 25.8 Live stage defaults and reference fidelity approval
- Status: blocked
- Plan check: off
- What changed: Bounded extraction diagnostics, truthful local-invalid StageCalls, regressions/evidence. Diagnosis: `.blueprint/qa/task-25.8/diagnostics-20261027/README.md`.
- Checks: Diagnostic prerequisite 196 passed/56.00s; design/revision 368 passed/439.51s; live `-x` 1 failed/99.85s; `uv run pytest` 2277 passed/984.10s. Read-only review: no findings. Historical integrity: 2122 unchanged files.
- Decisions: Defaults/inputs/validation unchanged; no extraction repair. AGENTS records nullable-label trap. Code retained uncommitted in working tree and `diagnostic-code.zip`; checkpoint retained.
- Tried and failed: Sole recreate passed extraction; feasibility blocked on unlabeled dropdown o5 needing control_field. No retry/planning/HTML/publication/other cases. Estimate $0.051634, incomplete; StageCalls/hashes saved.
- Gotchas: none beyond AGENTS.
- Left open: Prior P2 scorecard clipping/style axes; recreate fidelity, revision and user STOP unavailable.
- Blocked because: (b) Actual control-binding repair needs scope beyond diagnostics.
- Question: How should an unlabeled reference control receive explicit field/type binding before acceptance resumes?
- Options: A plan binding repair / B user clarification and revised acceptance instructions / Recommend: A.
- Next: New backend chat, gpt-6.1-sol high, `$blueprint-solution-architect`.

## 2026-10-27: Change 25.8 binding: unlabeled reference control offers
- What changed: architecture.md gains #Unlabeled reference control binding (code-built need-substitution offers on an unlabeled field control's control_field issue: unused instruction control clauses first, then catalog-valid fields only when they fit the issue scope; decision record = provenance; clause revalidation; one clause binds one observation; distinct ids), a decision-log row, and the Live ruling for 25.9 under #Reference extraction diagnostics. Essentials updated and stamped. plan.md: 25.8 rewritten as "Extraction diagnostics and unlabeled control binding offers" (M, lands the reviewed uncommitted diagnostics plus the offers; no live call), new 25.9 "Live stage defaults and reference fidelity approval" (M) carries the live acceptance, its Ifs and the STOP.
- Why: the sole post-diagnostic recreate run (.blueprint/qa/task-25.8/recreate/20261027-173624-405b4862/) extracted cleanly but blocked at feasibility: the region checkbox list came back as control o5 with `label: null`, so `Region Selector = region, chart fixed_size_list` matched nothing and the control_field clarification had no alternatives. Labels stay the only automatic match; code never binds by position or sole candidate.
- Ruling (user cards 2026-10-27): binding offers through the existing `_offers` -> `feasibility/decisions` path, no contract change (chosen over a label-free instruction form or dropping the region list). The 25.9 live harness pre-accepts only the `Region Selector` clause offer for an unlabeled control; anything else blocks. In 25.9 a rejected recreate extraction answer blocks without rerun; provider-transient errors keep the one-rerun rule.
- Change requests: the 25.8 block question (how an unlabeled control gets explicit field/type binding) is settled as planned in 25.8 (offers) and 25.9 (harness acceptance). No other open request.
- Checks: `blueprint.py stamp`, `lint` 0 errors (16 existing warnings); `reopen 25.8`. Independent blueprint-reviewer: 5 P2 (label-match semantics vs decisions, clause revalidation, one clause/one observation, id collision, issue_scope hiding the issue) + 5 P3 (retry wording, stale 25.8 live ruling, positional o5 naming, needs_data wording, undefined default type/label), all applied. No pytest or provider call this session.
- Left open: prior P2 scorecard decimal clipping and style page-2 axis overlap stay 25.9 acceptance concerns. The diagnostics and 3.0 harness edits remain uncommitted in the working tree for 25.8 to commit unchanged.
- Next: 25.8 in a new session (opus high).

## 2026-10-27: Task 25.8 Extraction diagnostics and unlabeled control binding offers
- Status: done
- Plan check: off
- What changed: Committed the reviewed diagnostics unchanged (ZIP byte-match). requirements.py: unlabeled recreate field control's control_field issue offers unused instruction control clauses, then catalog fields; clause revalidation; decide guards; feasibility.md `## Decisions`. Fixture tests/data/recreate_unlabeled_control.json (generator .blueprint/qa/task-25.8/make_unlabeled_fixture.py).
- Checks: Done-when set 1: 469 passed/188.81s (then test_feasibility 274 passed after one edge test); set 2: 242 passed/295.95s; `uv run pytest` 2285 passed/1008.71s.
- Decisions: Field offers admitted greedily in issue order while all fit MAX_ISSUES; instruction offers excluded from the issue_scope count; binding offers never truncated. decide also requires the alternative visible in the stored assessment. observation_meaning gives an unlabeled bound control its control_field as dimension (completion/planner). Fixture context/outline/design/draft reuse the 24.10 fixture (run kept none); repair reply = page-1 rows. Started with `start --force` per task If. AGENTS.md Known gotchas gains the `choose` shadowing line.
- Digest: req._offers(r,slot,snap,checker,ledger) -> internal {id,label,needs,clause}; decision record adds `observation` (item id); _clause_current(r,clause,needs,snap,ledger); feasibility.md `## Decisions` lines `<oN> bound by clause <Label>` / `bound to field <f>`.
- Tried and failed: none.
- Gotchas: test_feasibility already defines `choose(client,bid,...)`; the new pure helper is `decide_on`.
- Left open: P3 one clause can bind two observations after a spec-mismatch revalidation cycle - requirements.py:_clause_current; P3 timing covers one clause decision, not 16 - tests/test_feasibility.py.
- Next: Task 25.9 Live stage defaults and reference fidelity approval.

## 2026-10-27: Task 25.9 Live stage defaults and reference fidelity approval
- Status: blocked
- Plan check: off
- What changed: Live harness (tests/live/test_reference_design.py): evidence task-25.9; `choose_decisions` accepts only `Region Selector: fixed_size_list on region (from your instructions)` on one unlabeled control, records `accepted_offers`; design_page hash in runtime_sha256. User-approved (card) footer fix outside Files: src/dss/render/design_page.py footer rule counts only painting elements (+svg shapes, list markers) and text; tests/test_design_page.py +12 cases.
- Checks: focused six-file 368 passed/431.65s; live run 1 1 failed/850.78s (page-1 reference_html footer x3); after fix focused+design_page 419 passed/459.54s; live run 2 1 failed/1329.77s (native_planning stage_timeout 1200 s); `uv run pytest` 1 failed (recompute timing 125-166 ms, pre-existing), 2302 passed/1433.83s; final affected suites 445 passed/573.63s. History 2164 files unchanged. Evidence .blueprint/qa/task-25.9/README.md.
- Decisions: Run 1 accepted the offer on o5 (alt_bae835673cff9247fccca3ed) plus o3 geo drops. Footer fix + rerun per user card; block after run 2 per user card. Not a default/cap change. AGENTS.md gains 4 gotchas.
- Tried and failed: run 1 (footer false positive, fixed); run 2 (planning timeout; also capability_check bound unlabeled o5 itself as dropdown/region, bypassing offers).
- Gotchas: see AGENTS.md.
- Left open: P3 architecture.md footer wording (nothing visible) and test_design_page.py outside Files; P3 two-offer guard per assessment - tests/live/test_reference_design.py; pre-existing recompute oracle failure - requirements.py allowed_types; prior P2 scorecard clipping/style axes.
- Blocked because: (b) native_planning clock variance, the model-inferred binding of an unlabeled control and the failing recompute oracle need architect/user decisions (defaults are the user's call).
- Question: How should 25.9 resume: raise/keep the native_planning clock, and must a model-filled control_field on an unlabeled control become an issue (or block in the harness)?
- Options: A plan a reconcile rule (strip/flag model control_field on unlabeled controls), fix allowed_types caching, keep 1,200 s and authorize one rerun / B user raises the planning clock and reruns as is / Recommend: A, since B can still publish a dropdown instead of the native list.
- Next: New backend chat, best at high, `/blueprint-solution-architect`.

## 2026-10-27: Change 25.9 repair: explicit binding before live acceptance
- Class: Design clarification/repair at POC; no product, interface, dependency or stage-default change. Only backend planning docs and new local planning evidence changed.
- What changed: PRD records the user ruling and carries forward the two existing 25.8 P3 limitations in Later. architecture.md adds #Unlabeled control binding enforcement and #Synthetic footer geometry, extends operation-local recomputation reuse and #Reference live acceptance, updates the live extraction ruling's task reference and adds three decision rows. Essentials updated/stamped. plan.md: blocked 25.9 becomes `Explicit control binding and bounded recomputation` (M, offline), reopened with blueprint.py; new 25.10 `Live stage defaults and reference fidelity approval` (M) depends on it and retains the visual STOP. Existing completed tasks and earlier progress/evidence are unchanged.
- Why: 25.9 run 2's capability_check filled dropdown/control_field=region on an originally unlabeled observation, bypassing the explicit offers; its native_planning then timed out at 1,200 s. The existing 100 ms binding-offer oracle also failed, with about 55% in repeated dotenv/allowlist reads. The approved footer fix was present but needed architecture/Files coverage.
- Ruling (user answer 2026-10-27): keep the 1,200 s contract default; repair first, then one new live acceptance campaign under the existing stop/retry rules. No deterministic-timeout rerun, cap increase, Settings override or separate paid benchmark. An originally unlabeled field control requires an applying explicit binding decision even if a model supplied fields/mappings; pure checks block polluted stored rows, explicit feasibility check normalizes them. Effective allowed types may be reused only within an operation, with current config on the next.
- Task boundary: 25.9 preserves the existing footer/harness edits, adds deterministic binding/performance regressions and cross-assessment harness guards, and runs offline suites/all tests. 25.10 alone runs real models, dry engine, fixture-preserving recreate/style/none acceptance and the user's visual approval; new live evidence is task-25.10, original task-25.9 evidence remains immutable. A labeled control may retain exact-label instruction provenance; an unlabeled one must record the accepted applying clause decision.
- Checks: `blueprint.py stamp`; `lint` 0 errors / 16 existing warnings; `reopen 25.9`; `status` 93/95 done, 0 blocked, 2 to do, next 25.9. Hash verification: all eight relevant runtime/test/fixture-README files unchanged. `blueprint.py deps` (read-only, no --write) could not refresh registry checks because DNS failed; existing dated dependency approvals retained, none added. No pytest, provider, BigQuery or engine call this planning session. Backups, hashes, lint and review: .blueprint/qa/change-25.9-plan/.
- Review: independent read-only blueprint_reviewer identified one unconditional accepted-offer requirement that contradicted the labeled-control path; corrected to conditional provenance in 25.10 Done when. Re-review: no findings remain. No new scope/STOP or dependency came from the review.
- Change requests: the 25.9 block question is settled by the ruling above, planned in rewritten 25.9 plus 25.10. Footer wording/Files and the per-assessment harness guard are included. No other open change request. The prior scorecard clipping/style axes remain 25.10 acceptance concerns; the two 25.8 P3 items remain Later, not extra tasks.
- Next: new backend chat, gpt-6.1-sol high, `$blueprint-solution-builder`, task 25.9; after that task passes, 25.10 in the same backend folder (gpt-6-astra high: Spec plus visual STOP). Final backend re-audit follows completed acceptance; no other part's code or docs are in this session's scope.

## 2026-10-27: Task 25.9 Explicit control binding and bounded recomputation
- Status: blocked
- Plan check: off
- What changed: requirements.py enforces unlabeled decisions, operation-local allowlists and pure-read gates; added polluted-row/publication/version-copy/harness regressions. Evidence: .blueprint/qa/task-25.9-repair/README.md.
- Checks: five-module suite 589 passed/758.36s; final targeted 9 passed/7.33s; final footer/harness 93 passed/31.16s. Full `uv run pytest -x`: 873 passed, 1 failed, 17 deselected/693.18s. Remaining cases not reached.
- Decisions: Retain reviewed candidate and original checkpoint; correctness repairs are not invalidated. Historical evidence/footer/inputs unchanged. No live calls. AGENTS.md records allowlist-digest and complete-timing gotchas.
- Tried and failed: extra Checker reads and narrowed digest corrected; final definition-reconciliation speed oracle failed. Details/logs in evidence.
- Gotchas: see AGENTS.md.
- Left open: unchanged full-suite 100 ms definition/grain reconciliation oracle. No remaining code review findings.
- Blocked because: (b) plan's explicit final-budget rule requires architect reopening; no favorable timing rerun.
- Question: Plan bounded repair of the exact failing workload at unchanged 100 ms?
- Options: A profile/rework definition/grain reconciliation plus evaluate / B retain block / Recommend: A.
- Next: Backend chat, gpt-6.1-sol high, $blueprint-solution-architect; 25.10 waits.

```text
AssertionError: [1.0768851000175346, 0.10506490000989288, 0.10436720002326183]
assert min(timings) < .1
1 failed, 873 passed, 17 deselected in 693.18s
```

## 2026-10-27: Change final backend closure — POC performance concession
- User request: make this the final backend audit; ask only for concrete concessions or decisions needed to clear this part.
- User answer: "Use 250 ms; record cold time separately" for the existing feasibility speed checks. This supersedes the 100 ms budget, not the historical failure evidence or functional guarantees. No backend contract fixes 100 ms.
- What changed: PRD records the concession; architecture.md#Feasibility recomputation performance preservation defines the authoritative 250 ms acceptance while retaining workloads, sample counts, best-sample comparisons and semantics; essentials updated. Existing blocked 25.9 is narrowed to a Small acceptance-test/reporting alignment and complete offline verification, reopened with blueprint.py. Retain the reviewed runtime/fixture/harness candidate; no runtime implementation is repeated. 25.10 remains separate, pending the user's live-closure choice.
- Review: independent read-only blueprint_reviewer found no contradiction in the concession or the named contracts. The final build review found the same two existing P1 acceptance gates and no additional demonstrable product-code blocker. Surviving P2/P3 items from 23.1–25.8 are grouped in PRD Later; historical review placeholders and stage-budget questions are superseded, and addressed footer/harness issues are not new tasks.
- Gotcha sweep: stage-import naming, changed-brief publication, brief-review mutation/recovery guards, full-workload speed timing and helper/fake-clock test rules moved into architecture.md; obsolete repeated dotenv and inferred-binding bypass traps removed after their reviewed repairs. Retained environment/provider quirks. Removed the superseded 600 s benchmark-first advice; current live campaign limits govern.
- Scope: this final audit campaign has only the existing 25.9/25.10 gates. No new audit-fix phase, product code, dependency, contract, model-default or cap change. Another repair/design/optimization phase is not automatic follow-up.
- Change requests: the latest 25.9 block's request for another 100 ms optimization is superseded by the explicit user concession. Earlier resolved block questions remain resolved. Live recreation and preview-cosmetic concessions have been presented to the user and are still pending; no silent waiver or fidelity approval.
- Verification in progress: fresh complete offline suite with normal process access; final outcome will be appended to the audit entry/report. Initial sandbox TestClient stall was stopped by its verified process tree, not counted as a completed test result. Backend .env tracking/history check returned no entries. Existing mixed uncommitted work is preserved; no commit of another session's runtime work.
- Closure report: docs/audit-final-2026-10-27.md; raw current-run evidence .blueprint/qa/final-audit-20261027/. No paid/provider/BigQuery/engine call this session.

## 2026-10-27: Audit (final) — final backend closure campaign
- Verdict: DEFECTS — existing acceptance gates only, not a new audit-fix phase. Independent read-only blueprint_reviewer found the same two existing P1 gates and no additional demonstrable product-code blocker. This is the final broad backend audit requested by the user; closure evidence is attached to docs/audit-final-2026-10-27.md instead of commissioning another broad audit.
- Scope: re-audit since ACCEPTED 22.1 (2026-10-23), tasks 23.1–25.9 and pending 25.10, affected earlier behavior, POC checklist and named backend contracts. No other part's code/docs inspected or changed.
- Fresh Test (all): PASS, 2,341 passed, 17 deselected, 4 warnings in 1,268.26 s (21m 08s), exit 0. Command `uv run pytest --basetemp=.blueprint/qa/final-audit-20261027/pytest-normal -o faulthandler_timeout=120`, workspace UV cache and normal Windows process access. Log pytest-all-normal.log. This run retains the old stronger 100 ms tests; successful timing samples were not captured. It establishes fresh offline correctness but does not erase the saved 25.9 failure or implement the user's revised test/reporting acceptance. Do not use it as a favorable-sample resolution of the former 100 ms dispute.
- Done-when coverage: the full run includes every offline module named by 23.1–25.9, staged/fake-engine paths, API/recipe/dashboard-intent/synthetic conformance tests, footer negatives, brief-review races/recovery, stage Settings/execution, binding purity/invalidation and publication/revision rollback. Separate overlapping module invocations were not repeated. Earlier task checks beyond those modules are covered by Test (all); earlier generation/route/cap assertions intentionally superseded by 25.1–25.7 use current stage-profile tests. No claim that a historical live check passed under new defaults.
- Skipped explicitly: real models/BigQuery and live 25.10 (offline acceptance alignment comes first, visual STOP remains unapproved); earlier paid live campaigns (historical evidence retained, not silently rerun); real-source Natural Earth CLI regeneration (full untracked GeoJSON unavailable). Current art CLI fixture/render tests pass, packaged SVG sizes match original evidence, current hashes saved in art-manifest.json. Full native engine/report integration remains the release boundary.
- POC checklist: Commands document backend install/start/agent/test; external account/ADC/model credentials remain prerequisites, no fresh-account five-minute cloud setup claimed. Fresh offline core flow passes; saved style/no-reference four-page dry-engine builds plus edited-brief equality are evidence, current recreate acceptance is not. Inspected saved style page-1/page-2 screenshots confirm the existing scorecard-decimal/axis limitations. Known limitations are in PRD Later.
- Security/dependencies: backend-scoped `git ls-files` and `git log --all` for .env/.env.* returned no entries; file-name-only API-key/private-key signature scan across source/tests/docs returned no matches. No secret values output, no exhaustive or program-wide secret audit claimed. Manifest matches dated approvals; no new dependency. Conventions 1.4 ports/config/paths/IDs reviewed against backend config/start/agent and passing contract tests; read-only contracts unchanged.
- Decisions: user-approved 250 ms warm plus separate first/cold reporting is canonical in PRD/architecture/essentials and the narrowed S task 25.9. Retain already-reviewed runtime correctness edits, footer fix, fixtures and historical evidence; remaining 25.9 work is test alignment and final verification. Current successful 100 ms samples do not reverse that decision. User has not yet answered the live-scope or preview-cosmetic cards: retain existing recreation/visual requirements and do not assume a waiver. 25.10 remains M with its visual STOP and unchanged 1,200 s default/campaign limits.
- Review/limitations: two independent narrow follow-ups found no contradiction in the 250 ms ruling or final docs. Five groups of surviving P2/P3 items and prior binding limitations are in PRD Later; resolved review placeholders/footer/harness questions are superseded. Durable conventions folded into architecture; obsolete gotchas removed. The old PRD deadline is corrected to the user's existing no-deadline ruling.
- Mechanical checks: stamp PASS; lint 0 errors / 17 size warnings (16 before closure plus one convention-section size warning); tracked backend-doc diff check PASS. No runtime/test source edited in this architect session. Existing mixed uncommitted runtime/docs work is preserved, not committed wholesale as this audit's work; closure documents are checkpointed locally.
- Remaining tasks: 25.9 Finalize binding repair and POC speed acceptance (S); 25.10 Live stage defaults and reference fidelity approval (M), unless explicitly deferred by the user. No new task or audit-fix phase. Backend is not yet marked ACCEPTED; close these fixed gates with real results and actual user approval or a recorded scope concession.
- Next: new backend builder session, gpt-6.1-sol high, task 25.9. No new broad audit, paid benchmark, default change or additional optimization campaign is part of that handoff.

## 2026-10-27: Task 25.9 Finalize binding repair and POC speed acceptance
- Status: done
- Plan check: off
- What changed: Seven tests/test_feasibility.py timing checks use 250 ms and record every original sample. Updated final-audit closure evidence; retained runtime, fixtures, footer and harness unchanged.
- Checks: `uv run pytest` PASS: 2341 passed, 17 deselected, 4 warnings, 1894.58 s; runner 1903.294 s. This single full run satisfies Done when and Test (all). Preservation: 12510 historical files unchanged. Narrow review: warning-description P3 corrected, then no findings.
- Decisions: JUnit properties retain original sample counts/states and first samples. Definition/grain/evaluation: 1136.191 / 76.008 / 75.017 ms. First is not process-cold; no process-cold measurement, warmup, favorable rerun or runtime change. Evidence: .blueprint/qa/task-25.9-repair/closure-250ms-20261027/.
- Digest: Seven feasibility timing gates use 0.250 s; JUnit recompute_* properties save first/all samples. Full offline suite 2341 passed; explicit binding/runtime preserved. Evidence: .blueprint/qa/task-25.9-repair/closure-250ms-20261027/.
- Tried and failed: no failed acceptance run.
- Gotchas: none new; AGENTS unchanged.
- Left open: 25.10 live/visual acceptance; first definition sample exceeds one second; no cold-start SLO or cosmetic waiver claimed.
- Next: Task 25.10 in a new backend builder chat; retain its existing user-decision/visual STOP.

## 2026-10-27: Task 25.10 Live stage defaults and reference fidelity approval
- Status: blocked
- Plan check: off
- What changed: Committed 25.9's pending work first (user card). User chose the live campaign. Run 1 blocked on unlabeled date_range o11 (year slider); user widened the year-slider drop (test harness only) and authorized a rerun. Run 2's recreate reference_extract answer was rejected; blocked per rule (user card).
- Checks: Done-when offline six-file suite PASS: 368 passed, 2 deselected, 601.99 s. Live run 1: 1 failed, 100.22 s (reconcile). Harness offline after widening: 49 passed. Live run 2: 1 failed, 45.66 s (reference_extract). Earlier evidence 10,874 files unchanged. Full suite and review not run (blocked, no runtime change).
- Decisions: `approved_year_slider` matches a year/slider-labeled control or an unlabeled control with chart_candidate date_range; never box/order. Harness change committed with this block (user-approved, in Files) so the next session starts clean. Evidence: .blueprint/qa/task-25.10/README.md.
- Blocked because: (b) recreate extraction acceptance needs a code/plan ruling; the plan forbids rerunning a rejected recreate reference_extract answer.
- Question: How should a recreate reference_extract answer whose only schema failures are style hex/font patterns be handled, and does 25.10 then get a new campaign?
- Options: A (recommended) plan an offline repair that normalizes or omits invalid style values in recreate extraction (observations are what recreate needs), then one new 25.10 campaign. B: the user reclassifies such rejections as one-rerun transients, then rerun 25.10 unchanged.
- Failure output (run 2):
  stage reference_interpretation, node reference_extract, gemini-4-argon, thinking high, fallback false
  input 3268 measured / 4434 enforced / 131072; output 204 + 1673 thinking / 32768; outcome invalid; 24672 ms
  diagnostic boundary provider_schema, category provider_schema_rejection, issue_count 8
  pattern at style.palette[0], [1], [2], style.background, style.surface, style.text, style.accent, style.font_family
  AssertionError: {'stage': 'reference', 'node': 'reference_extract', 'error': 'llm_unavailable'}
- Digest: 25.10 blocked: run 1 unlabeled date_range year slider (drop widened in harness, user card); run 2 recreate reference_extract rejected on style hex/font patterns; no prototype, no visual approval. Evidence .blueprint/qa/task-25.10/.
- Tried and failed: run 1 (harness predicate, fixed with user approval); run 2 (rejected extraction, no rerun per rule).
- Gotchas: added to AGENTS.md (unlabeled date_range year slider; style-only pattern rejection).
- Left open: o3 `Location` bar (legend) remains a feasible chart with no issue; name it at the eventual STOP. Style and none cases not reached.
- Next: architect resolves the extraction question, then a new 25.10 campaign.

## 2026-10-28: Change 25.10 repair: recreate extraction style repair before live acceptance
- Class: Design repair at POC; no product, interface, dependency or stage-default change. Only backend planning docs changed.
- What changed: architecture.md adds #Recreate extraction style repair, points the diagnostics budget at it, renames the live extraction ruling to 25.11 (a style-only issue set no longer counts as rejected), adds a 25.10-block resume bullet to #Reference live acceptance and one decision row. Essentials updated/stamped. PRD open question now names 25.11. plan.md: blocked 25.10 becomes `Recreate extraction style repair` (S, offline, Spec), reopened with blueprint.py; new 25.11 `Live stage defaults and reference fidelity approval` (M) carries the former 25.10 content with task-25.11 evidence folders, depends on 25.10 and retains the visual STOP.
- Why: 25.10 run 2 rejected a whole recreate reference_extract answer on 8 style-only `pattern` issues (palette[0..2], background, surface, text, accent, font_family); recreate needs the observations, and the same inputs extracted cleanly in earlier runs.
- Ruling (user cards 2026-10-28): option A, offline style repair then one new campaign; no rerun allowance added. Both modes normalize common color/font forms; recreate falls back per field to the build's design-prefill preset; style mode still rejects an unrecoverable style value; observations stay strict in both modes; StageCall ends ok on acceptance with sanitized `style_repairs`.
- Checks: `blueprint.py stamp`; `lint` 0 errors / 17 existing warnings; `reopen 25.10`. No pytest, provider, BigQuery or engine call this session. No delta audit (POC).
- Change requests: the 25.10 block question is settled by the ruling above, planned in 25.10 plus 25.11. The widened year-slider drop and the o3 `Location` legend note carry into 25.11's If line. No other open change request.
- Next: task 25.10 (offline), then 25.11 (live + visual STOP).

## 2026-10-28: Task 25.10 Recreate extraction style repair
- Status: done
- Plan check: off
- What changed: style_extract adds repair_style/preset_profile/repair_projection; reference_extract.save repairs style before local validation (normalize both modes; recreate falls back per field to the prefill preset), records `style_repairs` on the accepted span and flips the StageCall invalid->ok. 16 oracle test groups in tests/test_references.py.
- Checks: `uv run pytest tests/test_references.py tests/test_stage_execution.py` PASS 165 passed, 51.95 s; Test (all) `uv run pytest` PASS 2390 passed, 17 deselected, 1022.53 s. Review: no P0-P2.
- Decisions: Normalization (incl. trim) applies only to a value failing StyleProfile as returned, so every answer accepted today keeps today's path untouched (' Roboto ' stays; deliberate, reviewer P3). Action `preset` also covers recreate drops (invalid/surplus palette entry, unknown key as path ['style','?'], invalid notes -> ''). Flip only on acceptance with >=1 repair. A rejection with repairs re-validates the raw answer, so diagnostic/error/outcome are today's. Preset = DEFAULTS[builds.archetype] as design.prefill.
- Digest: style_extract.repair_style(reply, preset|None)->(reply,[(path,action)]); preset_profile(archetype)->StyleProfile dict; reference_extract span diagnostic `accepted` + style_repairs {repairs[<=10]{path,action normalized|preset},count,truncated}.
- Tried and failed: none
- Gotchas: none new; AGENTS unchanged.
- Left open: P3 flip doesn't re-check the repaired reply against the provider schema (lax non-style coercion + style repair reports ok) - reference_extract.py; P3 preset tests use preset_profile itself, executive only - tests/test_references.py; P3 valid padded values not trimmed - style_extract.py.
- Next: Task 25.11 (live campaign + visual STOP).

## 2026-10-28: Task 25.11 Live stage defaults and reference fidelity approval
- Status: blocked
- Plan check: off
- What changed: no runtime code. Live harness edits (evidence to task-25.11, `style_repairs` in runs.json, native_planning override) set aside by `restore 25.11` (git stash). Evidence: .blueprint/qa/task-25.11/README.md.
- Checks: offline Done-when 368 passed (443.89 s). Live run 1 (contract defaults): FAIL, blueprint native_planning `stage_timeout` 1,199.5 s, Argon high, no answer on a 6,356-token request; extraction ok with no style repairs; region offer accepted on o5. Live run 2 (user card: native_planning thinking medium): blueprint 78.9 s, feasibility ready; stopped by the user during prototype. Earlier evidence 10,909 files unchanged.
- Decisions: run 2's leftover BigQuery source/views of build b_dfa1e4db5e0e deleted by exact name.
- Tried and failed: Argon high thinking for native_planning at 1,200 s (also 25.9 run 2).
- Gotchas: native_planning at medium thinking answered in 79 s where high timed out at 1,200 s on the same ~5k-token input.
- Left open: none
- Change request: (user, 2026-10-28) send the reference image itself to Argon, not extracted observations. New Flash 3.8 node analyzes the image and reports which charts/filters/controls Data Studio can recreate natively (e.g. bar bottom, area right, region filter) and what stays static image (text, headline, globe); a human approval step ("2 charts and 1 filter can be native; text stays static. Proceed?") lets the user agree or change the split; then Argon gets the image plus the approved feasibility report to generate the design prompt.
- Blocked because: (b) needs a change to architecture and plan (new node, user gate, Argon input).
- Question: How should the reference path be redesigned around image analysis + human approval + image-to-Argon, and what becomes of 25.11's acceptance?
- Options: A replan via architect (new tasks replacing observation-driven recreate) / B keep current path with native_planning medium as a default change / Recommend: A, the user's explicit direction.
- Next: architect plans the change, then a new live acceptance task.

## 2026-10-28: Change reference analysis gate (replaces observation-driven recreate)
- Class: Contract (program root; api.md 3.2, dashboard-intent.md 1.3, synthetic-data.md 1.3, fixtures) plus Design in backend; frontend and release changed in the same commit.
- What changed: architecture.md adds #Reference analysis and approval gate, marks #Blueprint observation coverage, #Recreate definition reconciliation, #Recreate observation completion, #Unlabeled reference control binding and #Unlabeled control binding enforcement retired, retargets #Reference interpretation and #Recreate page placement to approved items, records 3.2 defaults under #Stage settings, adds the 25.11 supersede rule to #Reference live acceptance, one decision row. Essentials updated/stamped. PRD open question names 26.6. plan.md: blocked 25.11 removed (its entries stay as history); new Phase 26: 26.1 S, 26.2 M, 26.3 M, 26.4 M, 26.5 M, 26.6 M (live + visual STOP).
- Why: 24.7-25.11 blocked on observation edge cases (legend as chart, unlabeled control, year slider, style patterns), each settled by a harness-only approval the product had no screen for; native_planning at Argon high timed out twice at 1,200 s (medium: 79 s).
- Ruling (user request and cards 2026-10-28): Flash analysis right after upload proposes per item native (catalog type) or static art; the user approves or edits split, type and a note; design/confirm, blueprint, recipe and run refuse until approved (`409 reference_unapproved`); Argon blueprint and brief get the image plus the approved items; observation path deleted (not flagged); style mode has no gate; native_planning default medium; 25.11 superseded by new live task 26.6.
- Checks: `blueprint.py stamp`; `lint` 0 errors (existing warnings only); no delta audit (POC, change.md). No pytest, provider, BigQuery or engine call this session.
- Change requests: 25.11's (user, 2026-10-28) image-to-Argon + Flash analysis + human approval: planned in 26.1-26.6 here, frontend 17.1-17.3, release 2.6. No other open change request.
- Next: task 26.1, then 26.2-26.6 in order; frontend 17.1-17.2 can run in parallel against the fixtures.

## 2026-10-28: Task 26.1 Contract 3.2 shapes and stage defaults
- Status: done
- Plan check: unattended
- What changed: `references.public` adds `analysis` (record.get, null until 26.2); `BlueprintRow.reference_item: str | None = None`; `references.unapproved(id)` / `analysis_conflict(rev)` build the two 409 RunErrors; stages.py defaults reference_interpretation Flash/high/repairs 1 ([0,1]), native_planning thinking medium. New tests in test_api_contract, test_stage_settings, test_blueprint.
- Checks: `uv run pytest tests/test_api_contract.py tests/test_stage_settings.py` PASS (new checks fail before); Test (all) `uv run pytest` PASS 2394 passed, 17 deselected. No blueprint-reviewer run (S task, no gate behavior).
- Decisions: stage defaults live in harness/stages.py (not config.py); stored Settings untouched (test proves a stored Argon/0-repair row keeps values). Existing tests updated to 3.2: test_references (2 asserts validation_repairs 0 -> 1, hit 22 cases), test_stage_execution (native_planning thinking HIGH -> MEDIUM, 2 tests). Error codes are plain strings: constructors in spec/references.py, not yet raised anywhere.
- Digest: references.public()['analysis'] (None until 26.2); BlueprintRow.reference_item (None); references.unapproved(set_id), analysis_conflict(rev) -> 409 RunError; reference_interpretation default Flash/high/repairs 1, native_planning medium.
- Tried and failed: none
- Gotchas: none
- Left open: none
- Next: Task 26.2 Flash reference analysis.

## 2026-10-28: Task 26.2 Flash reference analysis
- Status: done
- Plan check: unattended
- What changed: reference_extract now returns a validated ReferenceAnalysis (recreate) or StyleProfile only (style, `analysis: null`), with the stage's one validation repair (previous answer + error paths); synthetic proposal reads items, 422 for a pre-1.3 set. New `references` analysis models/rules, `capabilities.component_types`, electricity analysis fixture.
- Checks: `uv run pytest tests/test_references.py tests/test_synthetic.py` PASS (227 passed); Test (all) `uv run pytest` PASS (2417 passed, 17 deselected)
- Decisions: model boxes stay thousandths (normalized to 0..1 by code); type tokens normalized ("Time series" -> time_series); summary "charts" = native non-control items (matches both contract fixtures, where a native image item counts); repair runs in both modes (style answers with items fail); repair is a direct call from `save` through the bound stage model (+ run.usage event) since the graph caps ADK at one call; `interpretation` kept with items [] for downstream readers; set summary "Recreate reference (aspect ratio X): <analysis summary>". Edited outside Files (needed): context.py (request/allowed types, synthetic items), api/synthetic_data.py (422), skills + synthetic prompt, and tests with old-shape fakes (test_render gets a transitional `seed_observations`). AGENTS.md gotcha added.
- Digest: references.{AnalysisItem,ReferenceAnalysis,analyze(answers,allowed),analysis_summary(items),item_issues(i,kind,disp,type,allowed)->[(path,msg)]}; capabilities.component_types(registry,allowed); references.json `analysis`; tests/data/reference_analysis_electricity.json
- Tried and failed: none
- Gotchas: none beyond AGENTS.md
- Left open: P3 type descriptions hard-coded in capabilities.DRAWS (limits/needs from registry) - src/dss/spec/capabilities.py
- Next: Task 26.3 Approval gate API. Start from `references.item_issues` for PUT issues and recompute allowed_types per read (`component_types`).

## 2026-10-28: Task 26.3 Approval gate API
- Status: done
- Plan check: unattended
- What changed: `PUT reference-images/analysis` and `POST .../analysis/approve` (builds.py; code only under `workflow.action`, connect-prototype). The `reference_unapproved` gate runs on design/confirm, blueprint regenerate/accept, recipe and run (workflow.py, run.py). references.py adds the edit/approve rules and a projection that rereads allowed types on every read. state.py adds `legacy()` and `reference_changed()`. New tests/test_reference_gate.py, plus tests in test_references and test_api_contract.
- Checks: `uv run pytest tests/test_reference_gate.py tests/test_references.py tests/test_api_contract.py` PASS (186 passed; 13 failed with the source changes stashed); Test (all) `uv run pytest` PASS (2436 passed, 17 deselected)
- Decisions: `allowed_types`, `issues` and the narrowed `pending` state are a read-only projection: the stored state stays approved, so restoring the allowlist reopens the gate without an edit. Editing or approving a style set, a pre-1.3 `null` set or no set returns 404 `not_found`. The gate runs before `require_confirmed`, because an edit marks the Blueprint stale and the actionable error should be `reference_unapproved`. A pre-2.0 (legacy) build's recipe/run is not gated. Editing an approved analysis calls `requirements.reference_changed` (assessment invalidated, prototype stale) and marks the Blueprint `stale` (stage kept). Editing a pending analysis is not a reference change, although the digest still changes. The analysis summary and the set summary are rewritten on each edit. reference.md is rewritten via `commit(..., entry=)`. Edited outside Files, because the gate broke them: transitional fixtures in test_render (`approved_static_analysis()`), test_blueprint and test_feasibility get an approved all-static analysis. AGENTS.md gotcha added.
- Digest: references: current_types(), current_analysis(a, allowed), approved(record, allowed=None), require_approved(folder), edit/approve(record, body, allowed), AnalysisEdit/Approval; state: legacy(build, folder), reference_changed(build); test_render approved_static_analysis().
- Tried and failed: The gate first ran after `require_confirmed`, so recipe answered `wrong_stage` after an edit. Moved the gate before it.
- Gotchas: none beyond AGENTS.md
- Left open: P3 Re-approving after an edit makes a `stale` Blueprint acceptable without a replan (`confirmed()` only refuses `missing`); 26.4's item coverage may close it - src/dss/artifacts/state.py. P3 No test that the gate holds on a new version (copy_inputs copies references.json whole) - tests/test_reference_gate.py
- Next: Task 26.4. Start by `status --task 26.4`; read requirements.inputs (still reads observations) and the native_planning context.

## 2026-10-28: Task 26.4 Argon planning and brief from the image and approved items
- Status: partial
- Plan check: off
- What changed: Salvaged planner images/items/note, item repair/issues/drop, coverage, brief slots/static boxes. Instructions/old observations cannot supply bindings. User requested handoff.
- Checks: Focused regressions 16 passed; legacy flows 3 + 5 passed (.blueprint/qa/task-26.4-* logs/XML). Warm recomputation 17-18 ms; syntax 136 files and diff --check passed. Broad checks interrupted; full suite/reviewer pending.
- Decisions: Retain Component.reference_item/auto_layout provenance (outside Files). Legacy helpers remain until 26.5; legacy_observation_inputs supplies test-only legacy snapshots. Real recreate snapshots include analysis, even null.
- Digest: requirements.reference_items(snapshot), item_components(snapshot,ledger,checker); feasibility.item_errors/dropped_items; planner image parts; brief reference_items={native,static}; legacy_observation_inputs is test-only until 26.5.
- Tried and failed: Updated obsolete incoming-image oracle. Interrupted write corrupted test_blueprint.py; reconstructed edits; syntax/NUL scan passed.
- Gotchas: Normal process access required; see AGENTS.md.
- Left open: Required checks/reviewer; task remains in progress.
- Next: Resume 26.4: status/diff, Done-when, full pytest, reviewer, progress, done, final commit. Stop before 26.5.

## 2026-10-28: Task 26.4 Argon planning and brief from the image and approved items
- Status: done
- Plan check: off
- What changed: Resumed checkpoint 48a295c (planner images/items/note, item repair/issue/drop, item -> row -> component coverage, brief native slots/static boxes). Adapted two old-premise tests: test_feasibility legacy polluted-rows test uses legacy_observation_inputs; test_reference_gate approves an all-static split (static_split).
- Checks: `uv run pytest tests/test_blueprint.py tests/test_feasibility.py tests/test_render.py tests/test_reference_brief.py` 501 passed, 1 failed (legacy test) -> fixed, passes; Test (all) `uv run pytest` 2451 passed, 17 deselected (.blueprint/qa/task-26.4-full2.log). Warm recompute 17-18 ms.
- Decisions: test_reference_gate.py edited outside Files (26.4 broke its premise). AGENTS.md gotcha added. Earlier: Component.reference_item/auto_layout provenance retained.
- Digest: requirements.reference_items(snapshot), item_components(snapshot,ledger,checker); feasibility.item_errors/item_fulfils/dropped_items; planner image parts + reference section; brief reference_items={native,static}; legacy_observation_inputs test-only until 26.5.
- Tried and failed: none this session.
- Gotchas: none beyond AGENTS.md
- Left open: P2 approved-item requirement records/evidence not persisted in requirements.json or feasibility.md - src/dss/spec/requirements.py:2272; P3 prompts/v1/blueprint.md and skills/blueprint.md, reference-design.md still state pre-item row/observation rules - prompts/, skills/; P3 accepted item alternative keeps a wrong-type row naming the item (replace_indices []) - src/dss/spec/feasibility.py:313; P3 stale reference_item drops still listed in feasibility.md - src/dss/spec/requirements.py:2674; P3 electricity e2e runs designed=False, brief split tested only via context builders - tests/test_render.py:899.
- Next: Task 26.5 Retire the observation path. Start by `status --task 26.5`.

## 2026-10-28: Task 26.5 Retire the observation path
- Status: done
- Plan check: off
- What changed: Deleted image-observation code: surface definitions, reconciliation, completion rows, unlabeled-control offers/enforcement, observation coverage/titling/drops (requirements, feasibility, references, context, blueprint/render/capability_check/reference_brief nodes). Old tests/fixtures removed or ported to approved items (designed accept, brief report, page-1 revision coverage).
- Checks: Grep for `observation|_unlabeled_control|ObservedItem|observation_errors` in src/dss, prompts: no match (no pre-1.3 exception needed; readers are `references.Interpretation.items` before-validator and `requirements.active_requirements`). `uv run pytest` 2271 passed, 17 deselected (full run before reviewer's small fixes); 190 targeted tests passed after them.
- Decisions: `Interpretation.items` is always []; `interpret()` lost its observed arg. `confirmed_kpis` dropped from snapshot (no reader). canonical_dates keeps only declared year buckets on native axes (same result as before for analysis sets). Decisions with a `clause` never apply. Outline keeps a 'Recreate reference' section (validated interpretation). Edited skills/reference-design.md (outside Files, one stale word). tests/test_compiler `_row_ops` parity assertions dropped with the function; ten offline campaign tests removed from tests/live/test_reference_design.py; fixtures recreate_{blueprint_gaps,definitions,designed,page_placement,unlabeled_control,year_buckets}.json deleted, recreate_electricity.json pruned. AGENTS.md: removed 9 observation-only gotchas (item-id positions, vision `items` boxes, definition-only instructions, sanitized ledger fixtures, page-1 observations, observed titles, multi-issue drop, null-label control, year-slider control), reworded 6.
- Digest: Observation path gone: no requirements.observation_*/blueprint_observations/_unlabeled_control, feasibility.complete/surplus/coverage/laid_out, references.ObservedItem/Item; `references.interpret(mode,w,h,notes)`; `req._seed_catalog`; image/reference ledger records ignored.
- Tried and failed: none
- Gotchas: none beyond AGENTS.md
- Left open: P2 truthful-title/unit rule (`_period_free`, observed_title, accept titling) removed with no replacement though architecture.md#Recreate page placement still applies it to item rows - architect to mark Retired or add a task; P3 tests/live/test_reference_design.py live body still calls removed campaign helpers (26.6 rewrites); P3 recompute tests run on an empty ledger; P3 old persisted code-added rows count as supporting controls; P3 dead `using` origin, `derived/checked` kwargs, unused canonical_dates args; saved ready assessments of recreate builds read stale once (input digest changed).
- Next: Task 26.6 Live reference analysis acceptance. Start by `status --task 26.6`.

## 2026-10-28: Task 26.6 Live reference analysis acceptance
- Status: done
- Plan check: off
- What changed: tests/live/test_reference_design.py now runs the 3.2 gate path. play_gate/gate_body/gate find the agreed split by kind, type and box, PUT only the changes and approve. The observation drops, Region Selector and reconcile code are gone. Item-chain coverage plus fidelity/headline oracles. README updated; evidence in .blueprint/qa/task-26.6/.
- Checks: offline Done-when suite 463 passed (330 s). Live: recreate PASSED (run 3, 761 s, $0.72); style + none PASSED (run 5, 1002 s, $0.55 + $0.23). Runs 1, 2 and 4 are recorded in the evidence README. `uv run pytest`: 2272 passed (1095 s). User visual STOP: approved run 3.
- Decisions: User cards: every right-hand area chart is native `area` (Flash returned four country panels). The run-2 layout was accepted: bar below the region list and areas at x >= 50% are recorded deviations, bounded. Style run 5 accepted. Harness fixes: a revision is checked by validate_revision+render (it has no publish span); native_planning outcome may be ok|invalid; a legend or globe is never a gate target; headline-left check added. AGENTS.md: 2 gotchas.
- Digest: tests/live/test_reference_design.py: play_gate(analysis)->(changes,{target:[ids]}), gate(flow,analysis,evidence,facts), require_items/fidelity_errors/ACCEPTED_DEVIATIONS; evidence .blueprint/qa/task-26.6/README.md (run 3 recreate approved).
- Tried and failed: run 1 gate block (4 right panels); run 2 failed the fidelity oracle plus the revision-span bug; style runs 3/4 failed on the harness planning-call check.
- Gotchas: none beyond AGENTS.md
- Left open: P2 style run 4 would have been a readiness block (q8 KPI repair left AVG(urban_pct)/AVG(rural_pct) missing); planner variance, accepted by the user. P3 GLOBE regex statics any non-target label with map/earth/globe. Visible: overlapping axis labels, full-date x labels, small headline card, two non-reference charts on page 1.
- Next: release part (engine/report integration); backend plan complete.

## 2026-10-29: Change acceptance with findings (release 2.6, program root)
- Class: Product (deferred work only): PRD Later gains release 2.6's backend weaknesses W5-W7 and W4's backend half (emit `date_granularity` on `bar`, after the engine).
- Why: user, 2026-10-29: log the weaknesses for a later version; GitHub upload and Cloud Run deployment come first.
- Tasks affected: none; no task added.

## 2026-10-29: Change Google sign-in (program root)
- Why: the user wants Google sign-in on the hosted link instead of only the access code (release 4.1 block). Cards: in-app Google sign-in (not IAP: the local build agent would need Google ID tokens too), any Google account but configurable to a domain later, access code kept for scripts.
- Contracts: api.md 3.3 (Access: `POST /api/session {google_id_token}`, `Session.google_client_id`/`user`, `403 signin_not_allowed`, `400 google_signin_off`; fixtures api/session.json updated, api/session.google.json new); conventions.md 1.5 (`GOOGLE_OAUTH_CLIENT_ID`, `DSS_SIGNIN_ALLOW`, Cloud deployment Access bullet and fail-closed rule). docs/program.md: goals, non-goal (no per-user accounts), hosted flow, decision log.
- What changed here: architecture.md Cloud mode (Google sign-in bullet, oracle) and decision log; essentials contract versions and the `google-auth` row (verified 2026-10-29, other rows re-verified by `deps --write`); PRD non-goals; plan Phase 27 with 27.1 Google sign-in session (M).
- Tasks affected: 27.1 new; release 4.1 needs it.

## 2026-10-29: Task 27.1 Google sign-in session
- Status: done
- Plan check: off
- What changed: session.py: `POST /api/session` takes exactly one of `{code}`/`{google_id_token}`; the token is verified off the loop, needs `email_verified` and passes `DSS_SIGNIN_ALLOW`, and the session gets a signed 24 h `g.` cookie. `Session` gains `google_client_id`/`user`. config.py reads `GOOGLE_OAUTH_CLIENT_ID`/`DSS_SIGNIN_ALLOW` and refuses to start with a client id but no code (main.py calls it). Adds `google-auth[requests]`. Tests: test_google_signin.py (new), test_cloud_mode.py, test_api_contract.py.
- Checks: Done-when `uv run pytest tests/test_google_signin.py tests/test_cloud_mode.py tests/test_api_contract.py` PASS 109 (before the change: 31 failed, 78 passed). Test (all) `uv run pytest` PASS 2298 passed, 2 skipped, 17 deselected (baseline 2270).
- Decisions: Google cookies count only while the client id is set. `email_verified` accepts True/"true"; a missing email is a 403 with `email ""`. Any verifier exception is a 401 after 1 s, unlogged. The email is unpadded base64url and the cookie has Max-Age=86400. A null or both keys gives a 422 `invalid_request`. `signin_allow` is parsed once by a validator. `validate_cloud` was renamed to `validate_start`. The `requests` extra is already locked. AGENTS.md: 1 gotcha.
- Digest: `session.access(request, config)->(ok,user)`; cookie `g.<b64url email>.<exp>.<hmac>` via google_value(code,email,exp)/google_user(value,code); Config.google_client_id:str, signin_allow:tuple; Config.validate_start(); errors google_signin_off, signin_not_allowed
- Tried and failed: none
- Gotchas: none beyond AGENTS.md (no root `.env` here; no test needed it).
- Left open: P3 Google certs fetched uncached on every sign-in, with google-auth's 120 s transport timeout (Spec names this call) - src/dss/api/session.py
- Next: backend has no open task; release 4.1 (Cloud Run deploy, repo root) needs this.

## 2026-10-29: Change open hosted link
- What changed: contracts/conventions.md 1.6 adds `DSS_PUBLIC`; docs/architecture.md Cloud mode gets the "Open link" bullet and a decision row; new task 28.1 (Open-link opt-in on Cloud Run, S) in Phase 28; essentials pin conventions 1.6 and are restamped.
- Why: the user wants the hosted URL open to anyone with the link (the GCP project's OAuth branding is limited to one domain); release 4.1 now `Needs: backend 28.1`.
- Affected tasks: 28.1 only; access middleware, session routes and agent token unchanged.

## 2026-10-29: Change local agent per judge
- What changed (program root, contracts api.md 3.4, recipe.md 1.4, conventions.md 1.7): hosted builds run on each visitor's own machine into their own Data Studio account. Build issues a one-shot job with a one-time code; one copied setup command (PowerShell tested, bash untested; Chrome required) installs uv, the repo zip and a dedicated Chrome profile, signs the visitor in once, then `dss-agent run --server --job` claims that job, runs dsengine and exits. The polling agent, heartbeat, shared agent token and `424 agent_offline` go. On hosted the view is exported to a public-read, not listable CSV in the share bucket and the recipe uses the `googleCloudStorage` header; GCS and BigQuery sources are locked on the open link; scale to zero (min 0, max 1).
- Why: user cards 2026-10-29 (one-shot job code over per-browser pairing with a polling agent, since the recipe already holds the whole build; Windows + untested bash; CSVs kept until the link is closed; own BigQuery/GCS and >32 MB uploads to Later; acceptance with a second Google account). Replaces "hosted v1 stops at the recipe" (change 2026-10-29 hosted scope).
- Tasks affected: 28.1 (agent-token clauses dropped; 29.1 retires that rule), new 29.1 one-shot job tickets, 29.2 `dss-agent run`, 29.3 hosting info and source lock, 29.4 share CSV + GCS header (`Needs: engine 14.1`). Spec: docs/architecture.md#Hosted one-shot builds (new). No change requests open.
- Delta audit (blueprint-reviewer, opus high, across the four parts and contracts): 0 P0/P1, 8 P2 + ~12 P3, all accepted by the user on cards and applied (cross-account GCS read check in release 4.5; 4.1's agent probe valid before and after backend 29.1; setup tested in the scriptblock form with a GitHub-shaped zip; 14.2 checks UI language and zoom; the Build panel restores its ticket after a reload and shows a failed hosted run; 4.6 expects `agent_timeout` for a claimed run; setup scripts pushed before the redeploy; stale contract lines, AGENTS.md command/fixture lines, 28.1's agent-token clauses and Review focus lines).
- Revised the same day (user card, setup step): new task 29.5 agent connection check (api.md 3.4 Checks, `dss-agent check`); docs/architecture.md#Hosted one-shot builds gains its bullet.

## 2026-10-29: Task 28.1 Open-link opt-in on Cloud Run
- Status: done
- Plan check: off
- What changed: config.py: `public_link` (env `DSS_PUBLIC`), `open_link` property (`K_SERVICE` set and `DSS_PUBLIC` exactly `"1"`); `validate_start` on Cloud Run exits for any other non-empty `DSS_PUBLIC`, or `1` with a code or client id, and skips the 12-char code rule only when `open_link`. main.py lifespan logs one warning when open. tests/test_cloud_mode.py: open start, fail-closed cases, off-Cloud-Run ignore, env mapping.
- Checks: `uv run pytest tests/test_cloud_mode.py` PASS 30 passed (7 failed with the source change stashed); Test (all) `uv run pytest` 2305 passed, 1 failed (`test_feasibility.py::test_decision_recompute_budget`, timing gate; known flake), rerun alone 1 passed and `tests/test_feasibility.py` 192 passed.
- Decisions: field is `public_link` (`public` collides with `Config.public()`). No strip: `" 1"` exits. Check order: DSS_PUBLIC rules first, then Google-needs-code, then code length, so existing messages are unchanged. Open path = existing empty-code path; middleware/session/agent routes untouched.
- Digest: `Config.public_link: str` (env DSS_PUBLIC), `Config.open_link -> bool` (cloud_service and public_link == "1") in src/dss/config.py; validate_start enforces conventions 1.6; main.py warns "API is open" once at startup.
- Tried and failed: none
- Gotchas: none
- Left open: P3 no test pins the agent-token rule on the open link (rule retired in 29.1) - tests/test_cloud_mode.py
- Next: Task 29.1. Start by `status` and recall docs/architecture.md#Hosted one-shot builds; 29.3 consumes `Config.open_link` for the source lock.

## 2026-10-29: Task 29.1 One-shot job tickets replace the polling agent
- Status: partial
- Plan check: off
- What changed: agent/jobs.py rewritten (SQLite `agent_tickets`, codes, claim, per-job token hash, sweep, startup recover/resume); api/agent.py (`POST /claim`, `X-DSS-Job-Token` on job routes, heartbeat/jobs/next gone); run.py (`GET /builds/{id}/job`, per-build `engine_busy`, `launch()`); engine.py agent fields false/null; config.py `share_bucket`/`share_dir` pair rule, agent-token start rule removed; main.py sweep task; db.py table. Tests rewritten in test_agent_server/test_cloud_mode/test_api_contract (+ test_recipe_contract, test_google_signin: superseded heartbeat asserts).
- Checks: `uv run pytest tests/test_agent_server.py tests/test_cloud_mode.py tests/test_api_contract.py` PASS (plus recipe_contract, google_signin: 219 passed). Full `uv run pytest` NOT yet seen (run was in flight at the usage limit).
- Decisions: shutdown leaves live tickets (no publish); recover deletes the interrupted run's `cancelled` trace and resumes waiting tickets under the same run_id via `run.launch`; ticket times fixed `%Y-%m-%dT%H:%M:%SZ`; `Config.agent_token` kept only as a redaction secret and for client.py until 29.2; job token added to the event parser's redaction list at claim.
- Digest: none yet (partial).
- Tried and failed: none
- Gotchas: tests/test_agent_client.py server-integration tests (LiveServer: console script, heartbeats, screenshots, job_not_found, nested images, network reconnect) still use heartbeat/jobs/next and will fail against 29.1; the If clause allows rewriting them in that file: claim via HTTP, then drive `Agent.run_job(httpx.Client(headers={"X-DSS-Job-Token": t}), job)`; polling-loop-only tests become "old polling form vs 3.4 server" checks.
- Left open: review (blueprint-reviewer) not run yet.
- Next: rerun full `uv run pytest`; fix test_agent_client.py as above; review; then progress entry `done` and `blueprint.py done 29.1`.

## 2026-10-29: Task 29.1 One-shot job tickets replace the polling agent
- Status: done
- Plan check: off
- What changed: (continuation of the partial entry) main.py cancels the sweep only if started (tests flip engine_mode to agent after startup); db.py live-code unique index now covers `waiting` and `running`; test_agent_server: periodic-sweep and running-code-uniqueness tests; test_agent_client.py server-integration tests now claim a code and drive `Agent.run_job` with `X-DSS-Job-Token`; the console-script test became "polling agent takes no job from a 3.4 server".
- Checks: `uv run pytest tests/test_agent_server.py tests/test_cloud_mode.py tests/test_api_contract.py` PASS (150); Test (all) `uv run pytest` PASS (2313 passed, 17 deselected).
- Decisions: index renamed `agent_tickets_live_codes` (WIP DBs keep the old one harmlessly); retired agent routes answer `404 job_not_found` via the catch-all.
- Digest: agent/jobs.py AgentJobs: prepare/issue/claim(code)->{job,job_token,api_version}/authorize(run_id,token)/ticket(bid)/sweep/recover; new_code(), normalize_code(); table agent_tickets(run_id,build_id,version,code,state,expires_at,claimed_at,token_sha256,last_event_at,job_json).
- Tried and failed: none
- Gotchas: client.py's polling loop raises JobGone uncaught on a 3.4 server's `jobs/next` 404 (exit 1, traceback); 29.2 replaces it.
- Left open: P3 client idle-check/heartbeat test removed without replacement (polling loop retired by 29.2) - tests/test_agent_client.py
- Next: Task 29.2 One-shot `dss-agent run`.

## 2026-10-29: Task 29.2 One-shot `dss-agent run`
- Status: done
- Plan check: off
- What changed: client.py: `dss-agent run --server --job [--dry-run]` claims one code, runs the 5.3 job path with `X-DSS-Job-Token`, prints the report link/failure, exits; polling loop, heartbeat and check loop removed; bare/old forms print usage, exit 2. Tests rewritten for main(); AGENTS.md command line.
- Checks: `uv run pytest tests/test_agent_client.py` PASS 30 (20 of the first 29 failed on the HEAD client); Test (all) `uv run pytest` PASS 2320 passed, 17 deselected (before the P3 fixes, which touch only client.py and its tests); manual: local agent-mode uvicorn + DSS_ENGINE_DRY_RUN=1, `uv run --project backend dss-agent run --server http://localhost:8000 --job <code> --dry-run` from an empty cwd exit 0, SSE `build.finished {"status": "ok"}`, code in 0 output lines/files.
- Decisions: api_version mismatch (checked before the claim's shape) best-effort posts finished(2) so the ticket ends now; data dir/engine cmd: env first, root .env fallback, no DSS_AGENT_SERVER/TOKEN; argparse errors print only USAGE (never echo the code); secrets = code forms + job token, redacted from events/tail; e2e tests use the live uvicorn LiveServer (persistent loop) rather than TestClient; exit = engine code (negative -> 1).
- Digest: dss.agent.client: main(argv)->int; Agent(server, token|None, data_dir, command, dry_run).run(code)->exit; Agent.from_env(server, dry_run); USAGE, CODE_INVALID, UPDATE; call(http, method, path) prefixes /api/agent; claim body {code, agent_version}.
- Tried and failed: none
- Gotchas: client.main's logging.basicConfig is a no-op under pytest (caplog owns root); user-facing lines use print (capsys), progress uses logging.
- Left open: P3 POST /claim retried on network errors can burn a committed claim (prints CODE_INVALID, ticket stays running until timeout_s+60) - src/dss/agent/client.py
- Next: Task 29.3. Start by `status --task 29.3`.

## 2026-10-29: Task 29.3 Hosting info and the source lock on the open link
- Status: done
- Plan check: off
- What changed: new src/dss/api/hosting.py `GET /api/hosting` (gated by AccessMiddleware like other /api routes); Config.locked_sources / Config.share_data properties; builds.connect_source answers `403 source_locked` (`detail.kind`) after require_build, before URI parsing and intake (no BigQuery factory or GCS read); main.py includes the router; tests/test_hosting.py; two Hosting contract tests in test_api_contract.py.
- Checks: `uv run pytest tests/test_hosting.py tests/test_api_contract.py` PASS (75 passed; test_hosting 9 failed before the change, 3 regression guards passed); Test (all) `uv run pytest` PASS (2335 passed, 17 deselected, 25m48s).
- Decisions: Hosting reads `app.state.config` (startup env, not Settings overlay); missing build -> 404 before the lock; the lock also precedes URI validation (invalid gs URI on the open link -> 403, not 422).
- Digest: `GET /api/hosting` -> {mode, public, locked_sources, share_data, api_version} in src/dss/api/hosting.py; `Config.locked_sources -> list[str]` (["gcs","bigquery"] iff open_link), `Config.share_data -> bool` (agent mode + both DSS_SHARE_*).
- Tried and failed: none
- Gotchas: none
- Left open: none
- Next: Task 29.4. Start by `status --task 29.4`.

## 2026-10-30: Task 29.4 Share data CSV and the GCS recipe header
- Status: done
- Plan check: off
- What changed: new src/dss/data/share.py (cell/query/write/export/discard/recorded); `POST /run` with `Config.share_data` reserves the build, runs `share.export` in a thread, then re-prepares the job; compiler `share_header(text, path)` swaps only the header to googleCloudStorage (ops keep bytes, header validated); agent/jobs.py `package(folder, shared)` + `prepare` reads the run's share record (outside Files, per the task's If: packaging lives there; a resumed ticket keeps its header); tests/test_share_data.py, contract + lifecycle tests.
- Checks: `uv run pytest tests/test_share_data.py tests/test_recipe_contract.py tests/test_agent_server.py` PASS 113 (collection errors before the src change); Test (all) `uv run pytest` PASS 2346 passed, 17 deselected; manual live: `share.export` on build b_26a2f60c564f v2 (ecommerce_sales.csv) view: COUNT(*) 2000 = 2000 exported rows/CSV records, 10 columns, no .tmp (run through share.export directly, not through `POST /run`, to avoid a live ticket in the real DB).
- Decisions: 100 MB = 100,000,000 bytes incl. header; `total_rows` precheck plus streaming row count; record `<version>/share/<run_id>.json` {folder,path,rows,bytes} (no route serves it); export in asyncio.to_thread while the build sits in harness.active_builds; bucket checked via the 1.4 header pattern before querying; prepare once before export (input check) and again after; csv default dialect (CRLF); failures log only the exception type.
- Digest: share.export(factory,config,table,recipe,folder,run_id,share_dir,bucket)->{folder,path,rows,bytes}; share.recorded(folder,run_id)->path|None; compiler.share_header(text,path); jobs.package(folder,shared=None); errors share_too_large 422, share_export_failed 503.
- Tried and failed: none
- Gotchas: none
- Left open: P3 cancel mid-export leaves an orphan CSV - src/dss/api/run.py; P3 second Run during export answers 409 wrong_stage, not engine_busy - src/dss/api/run.py; P3 POST /versions copies `share/` records into the next version - src/dss/api/builds.py; P3 discard after a failed second prepare untested - src/dss/api/run.py. Old share folders are never deleted (bucket lifecycle is the release part's).
- Next: Task 29.5. Start by reading api.md 3.4 Checks and the 29.1 code generator in agent/jobs.py.

## 2026-10-30: Task 29.5 Agent connection check for the setup step
- Status: done
- Plan check: off
- What changed: db.py table agent_checks + BEFORE INSERT triggers sharing the live-code namespace with agent_tickets; jobs.py AgentJobs.create_check/check/answer_check/expire_checks (sweep and recover expire waiting checks); api/agent.py `POST /api/agent/check` and router `checks` (`POST /api/agent-checks`, `GET /api/agent-checks/{id}`); main.py includes it (outside Files: the /api/agent prefix can't host it); client.py `dss-agent check --server --code`.
- Checks: `uv run pytest tests/test_agent_server.py tests/test_agent_client.py tests/test_api_contract.py` PASS (171 passed); Test (all) `uv run pytest` PASS (2367 passed, 17 deselected), rerun after review fixes.
- Decisions: GET also expires a waiting check past expires_at (page sees it between sweeps); create retries 8x on IntegrityError like issue(); POST /agent/check bools are StrictBool; client: `dsengine check` 30 s (tree killed on timeout), `dsengine browser` 60 s with output to DEVNULL and never killed (Chrome must outlive it), then up to 3 checks 1 s apart; lines `[ok]|[x]|[?] <item>`; exit 2 also for agent_mode_off/401/non-JSON answer; extra args print the typed command's usage (parse_known_args); AGENTS.md heredoc gotcha extended.
- Digest: table agent_checks(check_id,code,state,created_at,expires_at,checked_at,result_json); AgentJobs.create_check()/check(id)/answer_check(code,agent_version,api_version,chrome_running,signed_in); api/agent.py `checks` router; client Agent.check(code)->0/1/2, CHECK_USAGE.
- Tried and failed: none
- Gotchas: none beyond AGENTS.md
- Left open: P3 a missing or broken engine reads as "Chrome not running"/"sign in" instead of "rerun the setup command" - src/dss/agent/client.py
- Next: all plan tasks done; final audit with the architect.

## 2026-10-30: Audit (final)
- Verdict: ACCEPTED. Re-audit after the 2026-10-27 DEFECTS audit; independent blueprint-reviewer (opus, high) found no P0/P1 across 25.9-29.5.
- Scope: tasks done since that audit: 25.9, 25.10, 26.1-26.6, 27.1, 28.1, 29.1-29.5 (25.11 removed by change, superseded by 26.6). Earlier tasks covered by Test (all) only.
- Test (all): `uv run pytest` PASS 2367 passed, 17 deselected, 9 warnings, 977 s, exit 0 (log .blueprint/qa/final-audit-20261030/pytest-all.log, junit.xml). Every audited Done-when pytest module is in that run. 26.5 grep (`observation|_unlabeled_control|ObservedItem|observation_errors`, case-insensitive) in src/dss and prompts: no match.
- Skipped: 26.6 live campaign (paid; user approved its visual STOP on run 3, 2026-10-28) and every other live-marked check; engine 14.1 (29.4 Needs) is the engine part's.
- Secrets: `git log --all` for *.env/*.env.* and `git ls-files` .env: none. Dependencies match the verified table (google-auth 2026-10-29).
- Security (reviewer, file:line in its report): Google token aud/iss/exp + email_verified + hd-only domain match, HMAC cookie with constant-time compare; DSS_PUBLIC fail-closed; job codes from `secrets`, claim in BEGIN IMMEDIATE, token SHA-256 only, redaction; source lock before any GCS/BigQuery call; share CSV under 128-bit random folder, only the published view.
- POC checklist: Commands (AGENTS.md) cover install/run/agent/test; core flow passes offline and live (26.6); known limitations in PRD Later; backend has no UI screens of its own.
- Doc sweep: architecture.md#Recreate page placement marks the truthful-title/unit rule retired with 26.5 (code/doc mismatch, P2 -> Later); #Testing gains the 26.2-26.4 reference-fake and engine_mode-flip rules from AGENTS.md; obsolete native_planning 3.1-defaults gotcha removed; 15 gotchas written after the block's end marker moved inside it. Essentials: Cloud/agent and sign-in decisions folded; stamped. PRD: Open question closed; Later adds item-row titles, reference-path and hosted leftovers (audit 2026-10-30).
- Mechanical: stamp PASS; lint 0 errors, 21 warnings (size).
- Left for the user: untracked ../Dockerfile, ../.dockerignore, ../.gcloudignore, ../deploy/ belong to the release part (not touched).

## 2026-10-31: Change Linking without a template
- What changed: essentials Contracts row recipe.md 1.4 -> 1.5 (program root change). 1.5 changes only the engine's Linking URL alias rule; the backend's recipe output is unchanged.
- Affected tasks: none.

## 2026-10-31: Change share CSV numeric NULLs
- What changed: ../contracts/api.md 3.4 -> 3.5 (Share data: sum-only numeric NULLs as 0; no shape or route change, `API_VERSION` stays "3.4"); architecture.md#Hosted one-shot builds (Share data) + decision log; essentials (api 3.5); plan Phase 30, task 30.1 (S, offline); PRD Later: typing beyond sum.
- Why: release 4.6 finding H1: the share CSV writes NULL empty, so the derived `high_value_revenue` was empty in 1,949 of 2,000 rows, Data Studio's GCS source typed it Text, and page 4's pivot and table failed ("aggregation Sum is unavailable"), the same in v1 and v2.
- Ruling (whole class, user card): a numeric column used only as `sum` (or a sort) gets 0 for NULL, exact for every sum; every other NULL stays empty. Declined for now: NULL as 0 everywhere (changes avg/count/min), engine field typing from the recipe (unproven Data Studio UI; PRD Later).
- Affected tasks: 30.1 (new); release 4.6 `Needs: backend 30.1`, then redeploys and reruns.
- Delta audit: none (target POC).
