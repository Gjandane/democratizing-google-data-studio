# Plan: backend
Target: POC · Audit: done 2026-10-18 (18 findings across the program, 18 applied)
Markers: [ ] to do, [~] in progress, [x] done, [!] blocked. Only blueprint.py changes them.
Sizes: S small, M a normal session, L needs a whole fresh session (never run unattended).

## Phase 1: Walking skeleton, intake and thin slice
- [x] 1.1 API, database, event bus and a one-node graph
  - Goal: FastAPI with health, settings and the SSE stream; SQLite schema; an ADK Workflow with a router, one function node and one LlmAgent node runnable with FakeLLM; one trace per run; the planner-model check.
  - Spec: docs/architecture.md#Graph
  - Files: pyproject.toml, .gitignore, src/dss/main.py, src/dss/config.py, src/dss/db.py, src/dss/bus.py, src/dss/api/settings.py, src/dss/api/builds.py, src/dss/harness/graph.py, src/dss/harness/llm.py, src/dss/harness/tracing.py, src/dss/harness/guardrails.py, tests/conftest.py, tests/fakes.py, tests/test_skeleton.py, tests/live/test_models.py
  - Depends on: none
  - Size: M
  - Done when: `uv run pytest tests/test_skeleton.py` passes: `GET /api/health` is ok; `PUT /api/settings` with `google_api_key` sets `google_api_key_set: true` and `GET /api/settings` never contains the key; `GET /api/builds/{id}/events` sends `ready`; a `hello` action through the Workflow with FakeLLM writes exactly one `traces` row whose spans list the router, function and LLM nodes in order; a missing planner model (fake model list) falls back to the worker model with a warning; `uv run pytest -m live tests/live/test_models.py` prints whether `gemini-4-argon` and `gemini-3.8-flash` are available with the real key; manual: `uv run uvicorn dss.main:app --port 8000` starts and `curl localhost:8000/api/health` prints `{"status":"ok"}`.
  - If: the installed google-adk has no `Workflow` graph API -> use the closest ADK 2.x graph construct per adk.dev, else ADK SequentialAgent + a router function with the same node boundaries; record it under Decisions and in Known gotchas.
- [x] 1.2 Builds and data intake to BigQuery
  - Goal: create/list/get builds; sources from CSV upload, GCS URI and BigQuery table with the intake rules; profile each source and write `data-profile.md`.
  - Spec: docs/architecture.md#Build docs
  - Files: src/dss/api/builds.py, src/dss/data/bigquery.py, src/dss/harness/nodes/intake.py, tests/test_intake.py, tests/data/small_sales.csv
  - Depends on: 1.1
  - Size: M
  - Done when: `uv run pytest tests/test_intake.py` passes with FakeBigQuery: `POST /api/builds` -> 201 stage `connect`; uploading two CSVs returns two `Source`s with columns, types and 3 samples; `Order Date` becomes `order_date`; a latin-1 file loads; an empty or over-100 MB file -> `422 invalid_source` with `detail.reason`; a STRING column of dates is flagged `date_like`; missing `gcp_project_id` -> `503 gcp_not_configured`; `data-profile.md` parses with `type: BigQuery Table`; `GET /api/builds` is newest first; responses match ../contracts/fixtures/api/build.json and builds.json shapes; manual (live): uploading any CSV creates a table in `BQ_DATASET` with the right row count.
  - Review focus: response shapes exactly as ../contracts/api.md (Build, Source, errors).
- [x] 1.3 Thin slice: fixed spec to prototype, recipe and dry-run build
  - Goal: the shortest path through the back half of flow 1, so the frontend and engine can integrate early: a fixture spec for the sample data renders a basic prototype (boxes and labels, contract attributes), compiles a recipe, and runs the engine (or the fake engine) with `--dry-run`.
  - Spec: docs/architecture.md#Layout; docs/architecture.md#Recipe compiler
  - Files: src/dss/spec/models.py, src/dss/spec/layout.py, src/dss/render/prototype.py, src/dss/recipe/compiler.py, src/dss/harness/nodes/execute.py, src/dss/api/prototype.py, src/dss/api/run.py, src/dss/api/dev.py, tests/data/thin_spec.json, tests/fake_engine.py, tests/test_thin_slice.py
  - Depends on: 1.2
  - Size: M
  - Done when: `uv run pytest tests/test_thin_slice.py` passes: `POST /api/dev/builds/{id}/load-spec` (dev-only route, loads tests/data/thin_spec.json) sets stage `prototype`; `GET /prototype` has one `data-cid` per spec item with `data-label` and `data-kind`; `POST /recipe` returns `{op_count, ops:[{op_id, line}]}` and every recipe line validates against ../contracts/recipe.schema.json; `POST /run` with the fake engine streams one `build.op` per `op_finished` and ends `build.finished`, stage `done`; manual: with the real engine installed and `DSS_ENGINE_DRY_RUN=1`, the same flow reaches `done`.

## Phase 2: Knowledge
- [x] 2.1 Procedural and semantic memory, knowledge seed
  - Goal: the skill loader, the OKF navigator (index, read, search by type/tags/text) over `knowledge/` and `data/knowledge/`, and the seed bundle: 12 catalog types with machine-readable limits, 4 archetypes, Data Studio product limits.
  - Spec: docs/architecture.md#Dashboard Spec
  - Files: src/dss/memory/procedural.py, src/dss/memory/semantic.py, knowledge/index.md, knowledge/log.md, knowledge/catalog/*.md, knowledge/archetypes/*.md, knowledge/datastudio/*.md, tests/test_memory_semantic.py
  - Depends on: 1.1
  - Size: M
  - Done when: `uv run pytest tests/test_memory_semantic.py` passes: every file under `knowledge/` has parseable frontmatter with non-empty `type`; `knowledge/catalog/` has exactly the 12 catalog types, each with `min_dimensions`, `max_dimensions`, `min_metrics`, `max_metrics`, `requires_date_dimension`, `min_w`, `min_h`; the navigator lists a folder from `index.md`, reads a concept by path, finds concepts by `type` and by a text term; the skill loader returns a skill's text by name and raises on an unknown name.

## Phase 3: Interview, plan and spec
- [x] 3.1 Interview node and chat API
  - Goal: interview start and turns through the graph with streaming replies, using the interview skill and the archetype skills; `mark_ready_for_plan` tool. Context for now: system prompt, skills, data profile, last 12 messages (6.1 adds the full assembler).
  - Files: src/dss/harness/nodes/interview.py, src/dss/api/chat.py, src/dss/harness/graph.py, src/dss/memory/episodic.py, skills/interview.md, skills/archetype-executive.md, skills/archetype-storytelling.md, skills/archetype-operational.md, skills/archetype-analytical.md, prompts/v1/interview.md, tests/test_interview.py
  - Depends on: 1.2; 2.1
  - Size: M
  - Done when: `uv run pytest tests/test_interview.py` passes with FakeLLM: `POST /interview/start` -> stage `interview`, SSE `message.delta` then `message.done`; `POST /messages` saves the user message and streams the reply; a FakeLLM `mark_ready_for_plan` tool call sets `ready_for_plan` and emits `build.updated`, and no marker text reaches the client; `GET /messages` returns both sides oldest first and matches ../contracts/fixtures/api/messages.json shape; one trace per request; manual (live, real Gemini): on the sample CSV the first question names real columns and asks one question only.
- [x] 3.2 Plan node, build docs and BigQuery view
  - Goal: the planner writes the OKF build docs; the view node builds, dry-runs and creates the per-version view.
  - Spec: docs/architecture.md#Build docs; docs/architecture.md#BigQuery view
  - Files: src/dss/harness/nodes/plan.py, src/dss/harness/nodes/view.py, src/dss/data/bigquery.py, src/dss/api/chat.py, skills/plan.md, prompts/v1/plan.md, tests/test_plan.py, tests/test_view_sql.py
  - Depends on: 3.1
  - Size: M
  - Done when: `uv run pytest tests/test_plan.py tests/test_view_sql.py` passes: FakeLLM docs are written under `v1/docs/` with the right `type`s and `docs.updated` is emitted; `/plan` is accepted in stage `interview` before `ready_for_plan`; view SQL for one table + 2 derived fields, for 2 joined tables, for a column named `date`, and for a `date_like` column matches golden strings; a dry-run error triggers exactly one repair turn, a second error ends the run with the BigQuery message and stage `interview`; manual (live): the sample CSV's view appears in BigQuery and `SELECT *` on it works.
- [x] 3.3 Spec node and validator
  - Goal: the planner writes the Dashboard Spec (allowed types only); code validates it against the catalog and the layout rules; a repair loop of at most 2.
  - Spec: docs/architecture.md#Dashboard Spec; docs/architecture.md#Layout
  - Files: src/dss/spec/models.py, src/dss/spec/validate.py, src/dss/spec/layout.py, src/dss/harness/nodes/spec.py, src/dss/harness/nodes/validate.py, src/dss/harness/graph.py, src/dss/api/prototype.py, skills/spec.md, prompts/v1/spec.md, tests/test_spec_validate.py, tests/test_layout.py, tests/test_spec_node.py
  - Depends on: 1.3; 2.1; 3.2
  - Size: M
  - Done when: `uv run pytest tests/test_spec_validate.py tests/test_layout.py tests/test_spec_node.py` passes: property tests (seed 7, 50 random specs) never accept an overlap, an unknown field, a type outside the catalog or `DSS_ALLOWED_TYPES`, two pages, or counts outside the catalog limits; golden invalid specs return the expected `{path, message}` list; layout gutters are 15-17 px and boxes stay inside the canvas; FakeLLM returning an invalid then a valid spec takes exactly one repair pass; three invalid specs end the run with the errors and stage `interview`; `GET /spec` returns the saved spec; manual (live): the sample build's spec from real Gemini validates on the first or second pass.
  - Review focus: the validator is the guardrail for the Data Studio fidelity promise: catalog limits read from knowledge/catalog frontmatter, not duplicated in code.

## Phase 4: Prototype, revise, recipe, build
- [x] 4.1 Prototype renderer and background
  - Goal: the full renderer (ECharts per type, theme, aggregate data in parallel with a cache) and `background_p1.png` from the decoration layer; stage `prototype` after plan.
  - Spec: docs/architecture.md#Prototype renderer; docs/architecture.md#Layout
  - Files: src/dss/render/prototype.py, src/dss/render/background.py, src/dss/harness/nodes/render.py, src/dss/data/bigquery.py, src/dss/api/prototype.py, tests/test_render.py
  - Depends on: 3.3
  - Size: M
  - Done when: `uv run pytest tests/test_render.py` passes: one `data-cid` per spec component and decoration with `data-label` and `data-kind`, boxes equal Layout's, no nested `data-cid`; `layer=decoration` hides every component; `background_p1.png` is 1200 px wide with the page height; a second render of the same version runs zero aggregate queries (cache); 12 components with FakeBigQuery render in under 15 s; `prototype.updated` and `stage.changed: prototype` are emitted; manual: the sample build's prototype opens at `http://localhost:8000/api/builds/<id>/prototype` with real numbers in each chart.
  - Review focus: the HTML contract in ../contracts/api.md "Prototype HTML" (the frontend's comment overlay depends on it).
- [x] 4.2 Revise from comments
  - Goal: comments -> validated JSON patch -> new spec version -> re-render.
  - Spec: docs/architecture.md#Revise
  - Files: src/dss/harness/nodes/revise.py, src/dss/spec/patch.py, src/dss/api/prototype.py, skills/revise.md, prompts/v1/revise.md, tests/test_revise.py
  - Depends on: 4.1
  - Size: S
  - Done when: `uv run pytest tests/test_revise.py` passes: a "make this bigger" comment patch grows the component and moves its neighbour to keep no overlap; a patch touching an unrelated id is rejected; a decoration comment changes the decoration; a request for a non-allowed type is refused with an assistant message; conflicting comments apply last-wins with a note; an empty patch keeps `spec_version`; otherwise `spec_version` increments, `decisions.md` gains one entry per comment and `prototype.updated` carries the new version; manual (live): "make the title bigger" on the sample prototype changes only the title.
- [x] 4.3 Recipe compiler (full)
  - Goal: every spec type compiles per ../contracts/recipe.md, deterministic, from `spec.datasource.table`.
  - Spec: docs/architecture.md#Recipe compiler
  - Files: src/dss/recipe/compiler.py, src/dss/harness/nodes/compile.py, src/dss/api/run.py, tests/test_recipe_contract.py, tests/data/golden_spec.json, tests/data/golden_recipe.jsonl
  - Depends on: 3.3
  - Size: S
  - Done when: `uv run pytest tests/test_recipe_contract.py` passes: a golden spec with all 12 types compiles to lines that each validate against ../contracts/recipe.schema.json (`header`, `op`); the output equals tests/data/golden_recipe.jsonl byte for byte on two runs; the header's table comes from `spec.datasource.table`; `POST /recipe` returns `ops` with sequential `op_id`s.
  - Review focus: ../contracts/recipe.md op arguments and order.
- [x] 4.4 Execute, publish, versions and engine endpoints
  - Goal: the real build path: engine lock and timeout, relay, publish, new versions, engine status/login.
  - Files: src/dss/harness/nodes/execute.py, src/dss/harness/nodes/publish.py, src/dss/api/run.py, src/dss/api/engine.py, src/dss/api/builds.py, tests/test_execute.py, tests/fake_engine.py, tests/test_api_contract.py
  - Depends on: 4.3
  - Size: M
  - Done when: `uv run pytest tests/test_execute.py tests/test_api_contract.py` passes: with `DSS_ENGINE_CMD` pointing at tests/fake_engine.py (prints ../contracts/fixtures/events.sample.jsonl), `POST /run` emits one `build.op` per `op_finished`, then `build.finished` with the fixture's status and URL, stage `done`, version `published`, `events.jsonl` saved; a second concurrent `POST /run` -> `409 engine_busy`; `--timeout` is passed; `DSS_ENGINE_DRY_RUN=1` adds `--dry-run`; exit 3 -> `build.finished(failed)`, `engine_not_signed_in`, stage `prototype`; `POST /versions` creates v2 reusing the view, stage `prototype`; tests/test_api_contract.py checks every endpoint's response against ../contracts/fixtures/api/ shapes; manual (live): with the engine installed and `DSS_ENGINE_DRY_RUN=1`, the sample build reaches `done`.
  - Review focus: subprocess read in a worker thread without blocking the event loop; argument list, no `shell=True`; the lock is released on every path.

## Phase 5: Cloud mode (Cloud Run)
- [x] 5.1 Cloud mode: static frontend, PORT, access code, DB backup
  - Goal: the same app runs on Cloud Run: serves the built frontend, listens on `$PORT`, gates `/api` with the shared access code, refuses to start unsafe on Cloud Run, and keeps SQLite on local disk with a backup on the `/data` volume.
  - Spec: docs/architecture.md#Cloud mode; ../contracts/api.md#Access; ../contracts/conventions.md#Cloud deployment
  - Files: src/dss/config.py, src/dss/main.py, src/dss/db.py, src/dss/api/session.py, tests/test_cloud_mode.py
  - Depends on: 1.3
  - Size: M
  - Done when: `uv run pytest tests/test_cloud_mode.py` passes: with `DSS_ACCESS_CODE=c0de-c0de-c0de`, `GET /api/builds` -> `401 access_required`, with header `X-DSS-Access-Code` -> 200, `POST /api/session` sets an HttpOnly `dss_session` cookie (with `Secure` when the request carries `X-Forwarded-Proto: https`) after which `GET /api/builds`, `GET /api/builds/{id}/events` and `GET /api/builds/{id}/prototype` succeed with the cookie alone, a wrong code -> `401 access_denied` after about 1 s, `GET /api/health` and `GET /api/session` stay open; with the code empty nothing is gated and `GET /api/session` is `{required:false, ok:true}`; with `K_SERVICE` set, startup fails with a clear message when the code is shorter than 12 characters, or in agent mode when `DSS_AGENT_TOKEN` is shorter than 24; with `DSS_STATIC_DIR` at a temp folder holding `index.html` and `assets/a.js`, `/`, `/builds/b_123` return index.html, `/assets/a.js` returns the file, and `/api/nope` returns the JSON 404 error shape; `python -m dss.main` reads `PORT`, trusts forwarded headers and uses a graceful-shutdown timeout of at most 3 s; with `DSS_DB_PATH` outside `DSS_DATA_DIR`: a build created, then a simulated shutdown, then a fresh app with the local DB deleted lists that build (restored from `<DSS_DATA_DIR>/dss.sqlite`); the periodic backup (interval shortened in the test) runs only after a write and never opens a SQLite connection on the data dir; and `uv run pytest` (all) passes.
  - If: another backend session is building tasks 2.x-4.x at the same time (docs/program.md roadmap) -> touch only this task's Files; in main.py change only startup, middleware and static mounting, and re-read it right before each edit.
  - Review focus: no route in ../contracts/api.md escapes the gate except the three open ones; the code is compared in constant time and never logged; backups go through `sqlite3.Connection.backup` into `/tmp`, then a file copy and rename onto the data dir.
- [x] 5.2 Agent mode: job queue and agent endpoints
  - Goal: with `DSS_ENGINE_MODE=agent` a build becomes a queued job served through the Agent endpoints, and the backend consumes the posted engine events exactly as it consumes the local subprocess's, so the hosted app builds through a remote agent; settings are locked to the deployment.
  - Spec: docs/architecture.md#Cloud mode; ../contracts/api.md#Agent endpoints
  - Files: src/dss/config.py, src/dss/main.py, src/dss/agent/__init__.py, src/dss/agent/jobs.py, src/dss/api/agent.py, src/dss/api/engine.py, src/dss/api/run.py, src/dss/api/settings.py, src/dss/harness/nodes/execute.py, tests/test_agent_server.py
  - Depends on: 4.4; 5.1
  - Size: M
  - Done when: `uv run pytest tests/test_agent_server.py` passes with a scripted fake agent over TestClient: in agent mode without a heartbeat `POST /run` -> `424 agent_offline`; after `POST /api/agent/heartbeat`, `GET /api/engine/status` shows `mode:"agent"`, `agent_connected:true` and the heartbeat's `signed_in`; `POST /run` -> 202 and `GET /api/agent/jobs/next` returns the `Job` (files `recipe.jsonl` first), a second call returns 204; the files download; posting ../contracts/fixtures/events.sample.jsonl then `finished` gives one `build.op` per `op_finished` then `build.finished` with the fixture's status and URL, stage `done`, version `published`; a `report_url` on another host fails the run with `invalid_report_url`; no events for the timeout (shortened in the test) -> `build.finished(failed)` with `agent_timeout` and a new `POST /run` is accepted; a job running at startup is failed the same way; agent calls without or with a wrong `X-DSS-Agent-Token` -> `401 agent_unauthorized`, and the access code alone is refused there; names like `../dss.sqlite` -> `400 invalid_name`; `/api/agent/*` -> `404 agent_mode_off` in local mode; `POST /api/engine/login` in agent mode -> `409 login_on_agent`; `PUT /api/settings` with `google_api_key` or `gcp_project_id` in agent mode -> `403 settings_locked` while model changes pass; the contract test accepts both engine_status fixtures; and `uv run pytest` (all) passes.
  - Review focus: the long poll doesn't block the event loop or other requests; the lock is released on every path; local mode behaves exactly as before; no token or code in logs.
- [x] 5.3 The `dss-agent` build agent
  - Goal: `dss-agent` (a console script of this project) runs on the user's machine, heartbeats, pulls jobs, runs the local engine and reports back, from any working folder.
  - Spec: docs/architecture.md#Cloud mode; ../contracts/conventions.md#Build agent
  - Files: pyproject.toml, src/dss/agent/client.py, tests/test_agent_client.py
  - Depends on: 5.2
  - Size: M
  - Done when: `uv run pytest tests/test_agent_client.py` passes: against a live uvicorn on a free port in agent mode with `DSS_ENGINE_CMD` = tests/fake_engine.py, the client started with cwd = the repo root, and again with cwd = backend/, takes a queued build to `done`, with the job's files in `<repo>/data/agent/<build_id>/v1/` both times; `--dry-run` adds `--dry-run` to the engine command; heartbeats keep arriving while a job runs and during long polls; `signed_in` is taken from a faked `dsengine check` at start and not during a run; a `404 job_not_found` mid-job kills the engine and deletes the job folder; network errors retry with backoff, then exit non-zero after 60 s; the token never appears in the captured logs; manual: from the repo root, `uv run --project backend dss-agent --server http://localhost:8000 --dry-run` against a local backend started with `DSS_ENGINE_MODE=agent` takes the sample build to `done`.
  - Review focus: subprocess with an argument list and `cwd=backend/`; the HTTP timeout exceeds the long poll; the agent never runs two engines at once.

## Phase 6: Harness memory depth
- [x] 6.1 Episodic retrieval and working memory assembly
  - Goal: FTS5 relevance + recency retrieval and the per-node context assembler with budgets, wired into the interview, plan, spec and revise nodes.
  - Spec: docs/architecture.md#Episodic retrieval; docs/architecture.md#Working memory assembly
  - Files: src/dss/memory/episodic.py, src/dss/harness/context.py, src/dss/db.py, src/dss/harness/nodes/interview.py, src/dss/harness/nodes/plan.py, src/dss/harness/nodes/spec.py, src/dss/harness/nodes/revise.py, tests/test_episodic.py, tests/test_context.py
  - Depends on: 4.4
  - Size: M
  - Done when: `uv run pytest tests/test_episodic.py tests/test_context.py` passes: a similar-but-old message from another build and a recent one both come back, deduped; FTS special characters don't raise; sections come out in the specified order per node; an over-budget context drops FTS hits first, then the oldest messages, never the system prompt, skills or user input; section token counts land in the trace span; all earlier node tests still pass.
  - Review focus: Spec order and drop order exactly as written; no raw data rows in any context.
- [x] 6.2 Consolidation
  - Goal: after every `DSS_CONSOLIDATE_EVERY` builds reach `done`, the worker model distills episodes into OKF facts in `data/knowledge/user/`.
  - Spec: docs/architecture.md#Consolidation
  - Files: src/dss/harness/nodes/consolidate.py, src/dss/harness/nodes/publish.py, prompts/v1/consolidate.md, tests/test_consolidation.py
  - Depends on: 4.4
  - Size: S
  - Done when: `uv run pytest tests/test_consolidation.py` passes: with N=5, 4 done builds write nothing; the 5th writes OKF files with non-empty `type`, updates `index.md`, prepends `log.md`, resets the counter; with N=1 each done build consolidates; a changed fact keeps "Previously" with the date; the publish response doesn't wait for it.

## Phase 7: Stretch (cut order: research first)
- [x] 7.1 UX audit and style from picture
  - Goal: `POST /audit` runs the ux_audit node (findings as an assistant message); `POST /style-images` runs style_extract (vision) and writes `style.md`, which the spec node then reads.
  - Files: src/dss/harness/nodes/ux_audit.py, src/dss/harness/nodes/style_extract.py, src/dss/api/prototype.py, src/dss/api/builds.py, skills/ux-audit.md, skills/style-extract.md, prompts/v1/ux_audit.md, prompts/v1/style_extract.md, tests/test_audit_style.py
  - Depends on: 4.2
  - Size: M
  - Done when: `uv run pytest tests/test_audit_style.py` passes with FakeLLM: audit findings arrive as one assistant message naming component ids; an uploaded PNG yields `style.md` (`type: Style Profile`) with palette hex values; the spec context includes `style.md` when present.
- [x] 7.2 LLM-judge eval script
  - Goal: `uv run python -m dss.ops.eval <build_id>` scores a version's spec against a rubric (coverage of high-priority questions, catalog fit, layout balance) with the worker model and stores scores on the trace.
  - Files: src/dss/ops/__init__.py, src/dss/ops/eval.py, prompts/v1/judge.md, tests/test_eval.py
  - Depends on: 4.3
  - Size: S
  - Done when: `uv run pytest tests/test_eval.py` passes with FakeLLM: the score JSON has each rubric item 1-5 and a pass flag (all >= 3); the run writes one trace.
- [ ] 7.3 Research mode
  - Goal: `POST /research` runs a capped web research (google_search tool, at most 20 fetches) that writes a cleaned CSV plus `sources.md`, then intake loads it as a `research` source.
  - Files: src/dss/harness/nodes/research.py, src/dss/api/builds.py, skills/research.md, prompts/v1/research.md, tests/test_research.py
  - Depends on: 1.2; 3.1
  - Size: M
  - Done when: `uv run pytest tests/test_research.py` passes with FakeLLM and a fake search tool: the run stops at 20 fetches, writes a CSV with a header row and `sources.md` listing every URL used, and registers a `research` source; manual (live): "NBA players 2025-26 season stats" yields a CSV with at least 20 rows.
