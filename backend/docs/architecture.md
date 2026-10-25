# Architecture: backend
Target: POC · The source of truth for the design.
docs/architecture-essentials.md is its one-page summary: whenever this file changes, update the
essentials in the same session and run `blueprint.py stamp`.
Names follow ../harness-architecture.md (harness, agent run, working memory, procedural /
semantic / episodic memory, consolidation, guardrails, trace).

## Stack
| Layer | Choice | Why | Alternatives rejected |
|---|---|---|---|
| Runtime | Python 3.12, uv | one toolchain with the engine | Node |
| API | FastAPI + uvicorn, sse-starlette for SSE | async, typed, OpenAPI for free | Flask |
| Harness / graph | google-adk 2.x `Workflow` (nodes + edges, router, conditional loop) | GCP hackathon; graph engine in ADK | LangGraph |
| LLM | Gemini API via ADK / google-genai, `GOOGLE_API_KEY` | user's choice | Vertex AI auth |
| Storage | SQLite (stdlib sqlite3) + FTS5 | episodic memory without a server | Postgres, vector DB |
| Semantic memory | OKF markdown bundles, pyyaml frontmatter | user's constraint: OKF instead of RAG | embeddings |
| Data | google-cloud-bigquery (load jobs, views, dry runs, aggregates) | every source lands in BigQuery | pandas pipelines |
| Rendering | string templates + ECharts (CDN) in the HTML; Playwright Chromium for background.png; designed pages: planner HTML without a reference, Argon brief -> Flash HTML with one, sanitized and measured by code (#Designed pages) | deterministic components; the user wants AI-designed backgrounds | LLM-written component/chart HTML |
| Hosting | Cloud Run, one instance, image from the root `Dockerfile` (release part); serves the built frontend; builds through the local `dss-agent` | one service, same origin; the engine needs the user's signed-in Chrome | engine on Cloud Run with a stored session; separate frontend service |

## Folder structure
```text
backend/
  pyproject.toml
  src/dss/
    main.py               FastAPI app, routers, startup (db init, dataset ensure)
    config.py             env (../.env) + settings overlay from SQLite
    db.py                 schema and connection helpers
    bus.py                per-build async pub/sub for SSE
    api/                  builds.py, chat.py, prototype.py, run.py, settings.py, traces.py, engine.py,
                          workflow.py (context/outline/design/blueprint endpoints, 2026-10-21),
                          session.py (access code), agent.py (agent endpoints)
    agent/                jobs.py (job queue, heartbeat, timeouts), client.py (`dss-agent` CLI)
    harness/
      graph.py            the ADK Workflow: action router + nodes + edges
      nodes/              intake, context, outline, blueprint, feasibility, view, layout, validate,
                          render, revise, compile, execute, publish, ux_audit, style_extract,
                          research, consolidate (interview, plan, spec removed 2026-10-21)
      context.py          working memory assembly (per-node context recipes, budgets)
      llm.py              model routing (planner / worker), token accounting
      guardrails.py       loop limits and output checks at every loop exit
      tracing.py          one trace per run (spans per node)
    memory/
      procedural.py       skill loader (skills/*.md)
      semantic.py         OKF navigator over knowledge/ and data/knowledge/
      episodic.py         messages, events, FTS5 retrieval
    artifacts/            models.py (Context, Outline, Design, Blueprint), okf.py (read/write), state.py
    data/bigquery.py      intake loads, view creation, aggregate queries; data/profile.py (script)
    spec/                 models.py, validate.py, layout.py, patch.py
    render/               prototype.py, background.py, kits.py (decoration kits), design_page.py
                          (sanitize + measure designed pages), icons/ (vendored Lucide SVGs, ISC)
    recipe/compiler.py    spec -> recipe.jsonl (../contracts/recipe.md)
  skills/                 procedural memory: context.md, outline.md, blueprint.md, archetype-*.md (4),
                          revise.md, ux-audit.md, style-extract.md, research.md (2026-10-21)
  knowledge/              semantic memory seed (OKF): index.md, log.md, catalog/ (12 types),
                          archetypes/ (4), datastudio/ (product limits, fonts.md), themes/
  prompts/v1/             system prompts per node: the versioned release artifact
  tests/                  offline tests with FakeLLM, FakeBigQuery, fake engine
```

## Data model
SQLite `data/dss.sqlite`:
- `builds(id, title, archetype, mode, stage, current_version, created_at, updated_at, notes,
  artifacts_json)` (notes and artifacts_json added 2026-10-21)
- `versions(build_id, n, status, spec_version, report_url, created_at)`
- `sources(id, build_id, kind, name, bq_table, row_count, columns_json)`; kind adds `synthetic`
- `synthetic_generations(generation_key, build_id, request_hash, run_id, source_id, bq_table,
  state, retry_ready, error_json, created_at)` (additive migration; ../contracts/synthetic-data.md
  1.1: the only durable job record, backed up at once after reservation and registration)
- `messages(id, build_id, role, text, node, created_at)` + `messages_fts` (FTS5 over text, external content)
- `events(id, build_id, run_id, kind, payload_json, created_at)`
- `traces(run_id, build_id, node, model, input_tokens, output_tokens, latency_ms, tool_calls, status, error, spans_json, started_at)`
- `settings(key, value)` (API key stored here only when set from the UI; never returned)
- `consolidation(id, last_run_at, chats_since)`
Files per version: `data/builds/<id>/v<n>/` (../contracts/conventions.md).

## Key flows
- **Agent run** (one per API action): load settings -> assemble working memory for the node
  (`context.py`) -> node runs (LLM loop with tools, or code) -> guardrails -> write episodic
  (messages/events) -> emit SSE -> write exactly one trace -> drop run state. After each model
  response that reports usage, the run's running totals go out as `run.usage` (change
  2026-10-19; ../contracts/api.md 1.2), counted once per response, never per streamed chunk.
- **staged workflow** (change 2026-10-21; #Staged workflow): context (draft, edit, confirm) ->
  outline (propose, tick, other, suggest, confirm) -> design (prefill, edit, confirm) -> blueprint
  (draft, feasibility, view dry run, decisions, accept) -> prototype. Each step writes its artifact
  through code and emits `artifact.updated`.
- **intake**: CSV upload -> column names to snake_case (dedupe with `_2`), UTF-8 with latin-1
  fallback, reject over 100 MB or zero rows (`422 invalid_source`, `detail.reason`) -> BigQuery
  load job with autodetect into `src_<build_id>_<file slug>` -> profile (type, null %, distinct
  count, min/max, 3 samples; STRING columns whose samples parse as dates are flagged
  `date_like`) -> `data-profile.md`. GCS: load job from the `gs://` URI, same rules. BigQuery:
  profile in place, no copy.
- **blueprint accept** (replaces plan): feasibility recheck -> new run-specific candidate view
  from the blueprint -> code layout (#Spec layout) -> designer per page (#Designed pages) ->
  validate -> staged render/backgrounds ->
  atomic publish of spec/artifacts with the candidate table identity -> prototype. Failure
  cleans only the candidate and leaves prior docs/spec/view intact; the stage stays `blueprint`.
- **revise**: comments -> revise node (worker) -> JSON patch -> validate (repair <= 1) -> render ->
  background -> `spec_version` + 1 -> `prototype.updated`.
- **build**: take the global engine lock (else `409 engine_busy`) -> compile -> execute
  (`DSS_ENGINE_CMD run <recipe> --timeout DSS_ENGINE_TIMEOUT_S [--dry-run]` via
  `subprocess.Popen` with an argument list, read line by line in a worker thread and handed to
  the event loop; each line -> `events` row + `build.op` SSE) -> publish (`report_url`, version
  status) -> stage `done` (`ok`/`partial`) or back to `prototype` (`failed`) -> release lock ->
  consolidation check. Windows note: the asyncio subprocess and async Playwright APIs are not
  used (uvicorn's loop on Windows may not support them); Playwright runs its sync API in a worker
  thread.
- Failure paths: LLM error or missing key -> `run.finished(error)` with `llm_unavailable`, stage
  unchanged; BigQuery error -> `422`/`run.finished(error)` with BigQuery's message; spec still
  invalid -> `run.finished(error)` listing the validation errors, stage stays `blueprint`; engine exit 3 -> `build.finished(failed)` + `engine_not_signed_in`; missing
  `gcp_project_id` -> `503 gcp_not_configured` before any BigQuery call.

- **access** (when `DSS_ACCESS_CODE` is set): one middleware in front of every `/api` route except
  health and session; cookie or header per ../contracts/api.md#Access.
- **build, agent mode**: as **build**, but execute enqueues a `Job` instead of starting the
  subprocess, then consumes the events the agent posts exactly as it consumes the subprocess's
  stdout lines (same parser, same `events` rows, same SSE, same publish).

## Core logic
### Cloud mode
- Problem: the same backend runs locally and on Cloud Run (../contracts/conventions.md#Cloud
  deployment) with no code path that only one of them tests.
- Static frontend: when `DSS_STATIC_DIR` is set, files under it are served at `/`; any non-`/api`
  path without a file returns `index.html` (SPA routes); `/api/*` never falls back.
- Server: `python -m dss.main` runs uvicorn on `0.0.0.0:$PORT` (default 8000), never `--reload`,
  with `forwarded_allow_ips="*"` (so `X-Forwarded-Proto` marks https) and
  `timeout_graceful_shutdown` of at most 3 s (Cloud Run kills 10 s after SIGTERM; open long polls
  must not hold shutdown).
- Fail closed: with `K_SERVICE` set, startup exits with a message if `DSS_ACCESS_CODE` is under 12
  characters or, in agent mode, `DSS_AGENT_TOKEN` is under 24.
- Access: `POST /api/session` compares the code with `hmac.compare_digest` and sleeps 1 s on a
  miss; the cookie value is an HMAC of a fixed label keyed by the code (no extra secret; changing
  the code logs everyone out); `Secure` when the request is https.
- DB backup: when `DSS_DB_PATH` is outside `DSS_DATA_DIR`, startup copies
  `<DSS_DATA_DIR>/dss.sqlite` to `DSS_DB_PATH` if the local file is missing. A background task
  checks every 30 s whether anything was written since the last backup (a dirty flag set by the db
  layer); if so, and once at shutdown, `sqlite3.Connection.backup` writes `/tmp/dss.bak`, which is
  copied to `<DSS_DATA_DIR>/dss.sqlite.tmp` and renamed over `dss.sqlite`. SQLite never opens a
  file in `DSS_DATA_DIR` on Cloud Run. A failed backup logs a warning and never fails a request; at
  most one backup at a time.
- Settings lock: in agent mode, `PUT /api/settings` accepts only `planner_model`/`worker_model`
  (`403 settings_locked`), so a code holder can't swap the API key or the GCP project.
- Agent jobs (server, task 5.2): an in-memory FIFO (one instance, so no external queue); a job is
  handed out once (`GET /jobs/next` long-polls up to 25 s); the heartbeat refreshes
  `agent_last_seen`, `chrome_running`, `signed_in`; "connected" = a heartbeat within 30 s. Agent
  routes check `X-DSS-Agent-Token` only. The engine lock is taken at `POST /run` and released on
  `finished`, on timeout (`Job.timeout_s + 60` s without events) and at startup (a job running
  before a restart fails with `agent_timeout`). Posted events go through the same parser as the
  subprocess's stdout lines. `report_url` must be on `datastudio.google.com` or
  `lookerstudio.google.com`, else `invalid_report_url`. File names: `^[A-Za-z0-9._-]+$`, resolved
  inside the version folder, downloads only for names in `Job.files` (`400 invalid_name`).
- The agent (`dss-agent`, task 5.3): resolves the root `.env`, `DSS_DATA_DIR` and
  `DSS_ENGINE_CMD` from its package location as the backend does from `backend/`, whatever the
  cwd. A heartbeat thread (every 10 s, also during jobs and polls); `dsengine check` at start and
  every 60 s while idle feeds `signed_in`/`chrome_running`. Per job: download `Job.files` into
  `data/agent/<build_id>/v<n>/`, run `DSS_ENGINE_CMD run recipe.jsonl --timeout <Job.timeout_s>
  [--dry-run] --screens screens/` with `subprocess.Popen` (argument list, `cwd=backend/`); `--dry-run`
  on the agent's command line forces `--dry-run`; post events in batches (flush at least every
  second), `PUT` each screenshot an event names, then `finished` with the exit code. HTTP timeout
  > 35 s. `404 job_not_found` mid-job -> kill the engine, delete the job folder. Network errors:
  retry with backoff up to 60 s, then exit non-zero. One job at a time. Never logs the token.
- Edge cases: agent disconnects mid-job -> timeout path; two agents -> each job goes to one;
  `POST /run` while a job is queued or running -> `409 engine_busy`; uploads over 32 MB on Cloud
  Run get Cloud Run's own `413`; the hosted app with no agent stops at the recipe (`424
  agent_offline`), which is also the cut fallback (docs/program.md).
- Oracle: tests/test_cloud_mode.py, tests/test_agent_server.py, tests/test_agent_client.py (plan
  tasks 5.1-5.3); every earlier test passes with the code empty and `DSS_ENGINE_MODE=local`.

### Build consistency
Final-audit corrections (2026-10-19):
- Recipe preview must work without an engine installation or agent connection. Backend code
  formats each op's human-readable `line`, preserving the `dsengine print` convention in the API
  contract. Fixture tests compare preview lines with recorded engine output. Hosted runtime
  never launches the engine, including for preview.
- Running an already compiled version must use the current spec. Refresh the recipe from the
  current spec before execution/job preparation; the recipe action still provides preview.
  Compile failure starts no engine/job and preserves stage, lock and previous complete artifacts.
  A recipe request on a busy build must not mutate an in-flight job's files.
- Package version-relative image assets into deterministic plain filenames for agent transport,
  rewriting only packaged recipe references. Preserve canonical compiler bytes and original
  assets. Names must be collision-safe, stable across runs and deduplicated for repeated sources;
  reject missing files, traversal and resolved paths outside the version folder before queueing.
  Do not loosen the shared filename guard or change contracts.
- The agent's 60 s retry budget starts at its first failed attempt. Before each subsequent
  request, check the remaining deadline and bound the whole attempt, including stalled I/O,
  by that remainder. Backoff and HTTP 429/5xx share the deadline; expiration exits nonzero and
  cleans up a running engine. The first ordinary long poll keeps its >35 s timeout.
- Deadline cleanup must not add an ordinary socket timeout or unbounded client close, process
  wait or reader join. On the supported Windows machine the shortened stalled-server oracle
  (1.5 s budget) exits and reaps its engine within budget + 0.5 s. Preserve that acceptance
  tolerance; diagnose and bound teardown instead of hiding overruns by increasing the budget.
- Deferred hardening (change 2026-10-20; PRD Later, former 13.5): new-version creation is to
  become a publication transaction: copy/render to an owned staging location,
  commit the complete destination and DB version pointer, or roll back only this attempt.
  A copy, capture or DB failure leaves the old version usable and an immediate retry possible;
  restart cleans an abandoned owned destination. Never remove a committed/existing version.

### Staged workflow
- Problem (change staged workflow 2026-10-21): the free-text interview needed a model to extract
  requirements from every chat turn, and one large plan run did docs, SQL, spec and render, so a
  wording quirk or one failed call sent the user back to the interview (14.1, 14.2, release 2.3).
  The staged workflow replaces both: connect -> context -> outline -> design -> blueprint ->
  prototype, each middle stage one artifact the user confirms (../contracts/api.md 2.0, Staged
  workflow endpoints; ../contracts/dashboard-intent.md 1.2).
- Principle: code computes, the model judges, code writes files. Code profiles the data, builds
  every prompt from upstream artifacts, validates every model output and writes every artifact
  file. A model gets compact profiles and upstream artifacts, never data rows, never the chat
  history, and returns structured JSON (response_json_schema) for the judgment fields only.
- Artifacts: pydantic models for Context, Outline, Design and Blueprint, field for field as
  api.md 2.0 (one module, `src/dss/artifacts/`). Each is saved as OKF markdown in the version's
  `docs/`: frontmatter `type` (`Business and Data Context`, `Dashboard Outline`, `Design
  Preferences`, `Technical Blueprint`), `title`, `revision`, then the model JSON under `data:`;
  the body is a readable rendering by code (KPI table, question list, theme swatch list, question
  -> chart -> fields table). Reading an artifact parses the frontmatter only. Writes are atomic
  (temp file + rename) and emit `artifact.updated`, `docs.updated`. Artifact states and `notes`
  live on the build row (additive migration: `builds.notes`, `builds.artifacts_json`).
- State rules (api.md 2.0 Stage rules): confirm needs zero issues; edits only in stages context
  to prototype (build/done -> `409 wrong_stage`); an edit to an earlier artifact sets it `draft`,
  every later one `stale`, and the stage back. Confirming again keeps work: a stale downstream
  artifact is revalidated by code (unknown references removed with a note, selections and user
  edits kept), never replaced; replacing is explicit (`outline/propose`, `design/prefill`,
  `blueprint/regenerate`). The published spec/view/prototype stay until a new prototype commits
  (Plan publication). Stored stages interview/plan read as context; a legacy build (all four
  artifacts missing, a saved spec) skips the four-confirmed rule for recipe, run and versions.
  Every action takes the existing per-build lock.
- Staged artifact writes require a build/run-bound async emit callback and maintain OKF
  index/log files. Blueprint confirmation commits with candidate publication; rollback restores
  artifacts_json as well as the previous published spec/view/prototype. Raw Context expressions
  retain source scope; Blueprint extras use the normalized projection. BigQuery dry-run schemas,
  not only successful SQL resolution, establish declared derived-field types before numeric use.
- Oracle: tests/test_artifacts.py: every artifact round-trips model -> file -> model unchanged,
  frontmatter parses with its `type`; state transitions match the Stage rules table for every
  edit/confirm in every stage; fixture shapes equal ../contracts/fixtures/api/*.json.

### Data profile
- Problem: give every model node enough facts about the data in a few thousand tokens.
- Reusable script: `uv run python -m dss.data.profile <project.dataset.table> [--json]` and the
  function the intake and nodes call. Per column: name, type, null %, distinct count (approx),
  min/max for numbers and dates, the full value list with counts when distinct <= 20 (each value
  <= 60 chars), else the top 5 values with counts plus 3 samples; per source: row count and date
  range of each date-like column. Computed with BigQuery aggregate queries (approximate counts and
  top counts), never by fetching rows; at most 2 queries per source. Stored in
  `data-profile.md` frontmatter, replacing the old 3-sample profile; intake rules unchanged.
- Prompt form: one deterministic compact text per source (`column type null% distinct values`),
  stable across calls so it caches; budget 6k tokens for 30 columns: drop samples first, then
  shorten value lists to the top 5; columns past the first 40 of a source go as name and type
  only; a column is never dropped.
- Implementation (15.2): one aggregate query per source; prompt_text uses a conservative
  6,000 UTF-8 byte target, samples-first trimming, then top-five lists. This is separate from
  the model request's enforced token bound; schema names/types remain intact.
- Edge cases: all-null column (type kept, "all null"); a BigQuery source profiled in place.
- Oracle: tests/test_profile.py with FakeBigQuery: low-cardinality columns list all values,
  high-cardinality ones the top 5; the prompt text is byte-identical for the same profile;
  30 columns fit the budget; 60 columns send 41-60 as name and type. Live: profiling the 2,000-row sample takes <= 10 s.

### Context
- Input: compact profiles of all sources, `notes` (<= 4000 chars), archetype, recreate reference
  observation labels if any. Output: a Context draft (api.md 2.0) from one worker generation.
- Code validation fills `issues` (ValidationIssue paths): every field reference exists (base or
  derived); a derived expression has no aggregate or window function and all derived fields pass
  one BigQuery dry run `SELECT <exprs> FROM <base>`; SUM/AVG only on numbers, MIN/MAX on numbers
  and dates, COUNT/COUNT_DISTINCT on any field; exactly one of `measure`/`ratio`, and a ratio names
  two measure KPIs; ids unique snake_case, derived names don't collide with columns; a threshold's
  field exists and is numeric; at most 15 KPIs, 15 derived fields, 15 thresholds, 30 terms.
- One repair generation when the draft has issues (input: the draft plus its issues only); what
  remains goes to the user, who fixes it with `PUT context`, which reruns the same checks (no model).
- Gross/net, count/distinct and similar choices are the user's: the draft states its assumption in
  the KPI description, and the KPI cards are where the user changes it. No chat clarification.
- Budget: input <= 10k counted tokens, output <= 3k; one generation + at most one repair.
- Oracle: tests/test_context_node.py with FakeLLM: a valid draft writes context.md with no issues; an
  unknown field, an aggregate inside a derived expression, SUM on a string and a ratio naming a
  missing KPI each give an issue at the right path; one repair runs, never two; PUT revalidates
  without a model call; confirm with issues -> `409 artifact_invalid`.

### Outline
- outline_propose (on context confirm): input = context frontmatter, the compact field list,
  archetype skill, recreate observations if any, consolidated user facts (<= 500 tokens). Output:
  3-5 sections of 3-6 questions, each with rationale (<= 200 chars), `recommended`, `kpi_refs`.
  Code assigns ids (q1, q2 ... never reused within a build), drops unknown kpi_refs with a note,
  removes duplicates (case- and space-normalized text), sets `recommended = false` (the rationale
  says why) for a question whose kpi_refs are all ratio KPIs, sets `selected = recommended`. A
  later context confirm revalidates the existing outline in code instead (unknown kpi_refs removed
  with a note, selections kept); `outline/propose` re-proposes explicitly, keeping `other`
  questions and the selection of questions whose text is unchanged. Budget 8k in / 3k out, one
  generation, no repair.
- outline_suggest: the same input plus one section and its question texts; up to 5 new questions,
  unselected. Budget 6k / 2k.
- outline_other: input = context KPIs and fields, the section, the user's text (saved as a user
  Message). One generation returns 1-3 normalized questions (selected, origin `other`) and the
  requirement records of any behavior the text asks for (the existing extraction schema and
  limits, dashboard-intent.md 1.2); unsupported behavior gets an assistant message at once and
  stays in the ledger. Budget 6k / 2k.
- Selection is code only; confirm needs 1-24 selected questions.
- Accepted POC limitation (user-approved task 15.11; audit 2026-10-21): outline_other records
  carry `mapping_origins.origin=outline_other`. Empty extraction adds no unknown requirement;
  these records' needs_clarification verdicts and publication coverage checks are skipped in
  favor of the selected question's Context KPI refs and Blueprint rows. Emitted unsupported,
  unknown and missing-data verdicts still block. Omitted behavior is therefore not guaranteed
  to survive extraction. This is a documented gap against dashboard-intent.md's preservation
  rule, not full conformance; only the program-root architect may reconcile that contract.
- Context KPI restatements retain `kpi:<label>=<id>:<field>:<agg>:<unit>` provenance; redundant
  field/value argument restatements are removed only for outline_other. Other extraction paths
  keep their ordinary evidence rules. Build-level question ID counters never recycle IDs.
- Oracle: tests/test_outline.py with FakeLLM: 3-5 sections; ids stable across suggest/other/
  re-propose; other questions and selections survive re-confirm and re-propose; a ratio-only
  question is not recommended; duplicates dropped; "animate the GPS points" as other text keeps
  a blocked requirement and a reply; 25 selected -> `409 artifact_invalid`.

### Design and theme kit
- Theme kit (design-time, task 15.4): at least 6 presets covering the 4 archetypes, as OKF files
  `knowledge/themes/<id>.md` (`type: Theme Preset`, frontmatter = ThemePreset), plus the
  decoration kits they name (header band, panel grid, side rail ...) as deterministic decoration
  generators in `render/kits.py`. Crafted once with the frontend-design and ui-ux-pro-max skills;
  every text/surface pair has contrast >= 4.5:1; palettes stay distinguishable for common color
  blindness (a stdlib check in tests/test_design.py: simulate protanopia and deuteranopia with
  standard matrices; the first 4 palette colors keep a pairwise CIE76 delta E >= 10); fonts only from `knowledge/datastudio/fonts.md` (fonts Data
  Studio offers, checked in its font menu). The user approves the rendered preset sheet (STOP).
- Design (code only, no model): prefill = the archetype's default preset; a style or recreate
  reference overrides background/accent/palette with the StyleProfile colors snapped to valid
  values (`source: reference`); `per_section` when 1-5 sections have a selected question, else
  `single`; an existing Design is kept and revalidated, `design/prefill` replaces it. Validation:
  #RRGGBB, palette 3-8, text contrast >= 4.5:1 on background and surface, font among the presets'
  fonts (all from fonts.md), title <= 80 chars, `per_section` needs 1-5 outline
  sections with a selected question.
- Oracle: tests/test_design.py: every preset passes its own validation; prefill per archetype and
  with a reference; a low-contrast edit gives an issue; 6 selected sections with per_section ->
  issue. Manual: the preset sheet PNG reviewed by the user.

### Blueprint
- Problem: map each selected question to one buildable component, the user's KPI definitions
  intact, and prove it buildable before any prototype work.
- Input (planner model, one generation): context (derived fields, KPIs, thresholds), the compact
  field list with roles, selected questions (id, text, kpi_refs, section), the page plan (code:
  section -> page by `page_structure`), the catalog summary (allowed types with slot limits and
  options from `knowledge/catalog/*.md` frontmatter, `DSS_ALLOWED_TYPES`, the recipe's lack of
  chart filters: filtering is a derived field), and the join facts code found (columns with equal
  names and types across sources), and in recreate mode the active image observations
  (#Blueprint observation coverage). Output: ViewSources, extra derived fields, and rows: every
  selected question 1-3 rows; at most 2 supporting controls per page; at most 12 rows per page.
- Code feasibility, per row (the requirement records are the rows: no text extraction): type in
  the catalog, the registry and `DSS_ALLOWED_TYPES`; dimension/metric counts and date dimension
  per catalog; fields exist in the view's field list; roles and aggregations as the spec
  validator; every selected question has a row; a page holds at most 12 rows; sort field among the row's fields; option keys per recipe.md; a KPI the question
  names is used with exactly its field and aggregation; a ratio KPI cannot be a metric (Data
  Studio calculated fields are a non-goal); more than one source needs joins or union, never both.
- Repair and issues: failing rows (except ratio and source rules) go back once with their errors;
  the view is built from ViewSources + derived fields (BigQuery view below) and dry-run, with one
  SQL repair. What still fails becomes Issues on the Assessment with code-built alternatives:
  ratio -> numerator and denominator as two metrics, or drop; no date field -> the nearest type
  without one; no join key -> one source per option, or union; a question without a row -> drop;
  a page over 12 rows -> drop its last non-recommended questions until it fits, or per_section
  pages when 1-5 sections; always drop. Decisions apply in code (alternative replaces the row,
  drop removes it); no regeneration.
- Redraft (design confirm with an existing blueprint): rows of unchanged selected questions and
  their decisions are kept and rechecked by code; only new or changed questions go to the model;
  rows of deselected questions are removed. `blueprint/regenerate` redrafts every row. Accept
  needs at least one ok row (`409 artifact_invalid`).
- Union: base columns plus each other source's columns, missing ones as typed NULL, plus
  `dataset_name`; built by the view builder.
- Budget: input <= 14k counted tokens, output <= 6k; one generation + at most one row repair + at
  most one SQL repair; no candidate view is published here (Plan publication still applies at
  accept).
- Oracle: tests/test_blueprint.py with FakeLLM and FakeBigQuery: the ecommerce fixture gives
  ok rows plus a blocked ratio row with its two alternatives; a time_series without a date ->
  repair, then an issue; a question naming a KPI but using another aggregation is rejected; two
  unjoinable sources -> issue with one-source and union options; accept with a blocked row ->
  `409 feasibility_blocked`; decisions update rows without a model call; a fake omitting a
  question -> repair, then an issue; a redraft sends only changed questions; 13 rows on a page ->
  issue; zero ok rows -> `409 artifact_invalid`.

### Recreate date binding normalization
- Problem (24.9 block, change 2026-10-26): the electricity source's `year` is already a
  DATE with full-column `bucket_start: year` proof. Planner drafts nevertheless introduce
  `year_trunc = DATE_TRUNC(year, YEAR) - INTERVAL 0 DAY` (declared datetime), bind rows to an
  undeclared `year_year`, or emit invalid DATE arithmetic `DATE_TRUNC(year, YEAR) * 1`.
  A separate q4 error omits confirmed AVG(urban_rural_gap); date normalization cannot fix it.
- Objective: make a proven yearly date binding deterministic before row/view
  checks, without accepting arbitrary SQL, guessing field meaning or relaxing KPI coverage.
- Inputs: active recreate observations and reconciled instructions/confirmed Context, selected
  questions, ViewSources, projected schema, source-specific aggregate profiles, protected
  Context/retained derivations, planner extra derivations and rows. Output: canonical extra
  derivations and rows, then the existing diagnostics, Assessment, dry-run and coverage paths.
  No public shape or contract change; no model-written proof.
- Rules:
  - Scope is recreate Blueprint date bindings. Reuse a base field only when its actual
    projected type is DATE and the active source's
    full-column profile proves year starts. Samples, the field name, image text and planner
    declarations are not proof. Missing/all-null/stale proof does not authorize this repair.
  - Resolve proof through the same selected-source/projection rules as the view builder.
    An unrelated or shadowed same-named source cannot supply proof. For unions, every
    contributing non-NULL column must independently prove the same DATE/year fact; typed
    NULL padding is harmless. If provenance or output type is ambiguous, keep the ordinary
    validation/repair path. No new data query or profiling format is needed.
  - Code may reconstruct a planner-only date binding from a whole DATE_TRUNC(base, YEAR)
    extra expression, optionally with the observed `- INTERVAL 0 DAY` or `* 1` suffix, onto
    the proven base DATE. These suffixes identify bounded planner artifacts, not valid DATE
    algebra: * 1 is invalid SQL and subtracting an interval may change type. Reconstruction
    requires either explicit reconciled field/year-grain intent, or a selected question's
    native DATE-axis slot whose complete recognized expression names that base/YEAR. The
    second route covers the saved overall-access time series without inventing observation
    identity from matching metrics. Every use must independently qualify (including its sort),
    exclusively for date grouping with no conflicting confirmed field/grain/type semantics.
    Never apply this to a required datetime value, a metric, protected Context/retained definitions, an
    expression referenced by another derivation, or a name colliding with a real field.
    Recognize only those complete forms (case/whitespace/identifier quoting may vary), not
    partial SQL matches. Other arithmetic, intervals, casts, functions and trailing SQL keep
    their existing validation/one-SQL-repair outcome; never execute expressions to infer intent.
  - A missing code-style `<base>_year` row alias may resolve to the base only with the same
    explicit field/grain binding and proof, a unique target and no existing field/definition
    of that name. Suffix matching alone is insufficient. Other unknown fields remain errors.
  - Normalize a view and its date-grouping references together: date_dimension, date-bound
    dimensions/breakdown and the corresponding sort.field. Do not text-replace SQL or metric
    fields. Remove an eligible planner extra only after accounting for every use, with no
    dangling alias. Preserve row ids, page, question, provenance, metric meaning and decisions.
  - Apply the same rule after initial drafting, the existing row repair and SQL repair, before
    validation/completion; observation completion reuses the proven base instead of adding a
    redundant bucket. Recompute proof from current inputs on redraft/reload/accept. A changed
    source/profile/definition invalidates authorization rather than reviving a cached alias.
    Blueprint ready and publish coverage must agree; compiler grain remains code-owned.
  - Missing/wrong confirmed KPI measures remain repairable errors. The existing one row
    repair receives the question id and each missing required field/aggregation or conflicting
    actual measure, rather than only generic advice. Planner guidance requires all named KPIs
    across that question's 1-3 rows within catalog/page limits. If still missing, retain the
    Issue and block accept; never delete kpi_refs, substitute aggregation or auto-add a measure.
- Edge cases: normalization is idempotent; already-canonical rows stay unchanged. Preserve
  valid user/protected derivations and non-year buckets. Style/data/no-reference success
  behavior and published artifact/recipe bytes stay unchanged; existing error categories and
  gates remain. Ineligible inputs retain existing actionable failures, not readiness.
- Budget: no new model call, data query, dependency or repair; Blueprint remains 14k input/6k
  output with one row repair and one SQL repair. Existing 100 ms deterministic recomputation
  oracle holds with 24 observations and 24 definition clauses.
- Oracle: read-only saved runs .blueprint/qa/task-24.9/recreate/20261025-233319-bc455866/
  and 20261025-233550-34512aef/ supply profiles, Context/outline/design, reference requirements
  and persisted Blueprint artifacts. Original model replies were not captured: reconstruct
  FakeLLM draft/repair/view replies from those artifacts, label each reconstruction/adjustment,
  and hash original inputs separately from the derived fixture. Both reproduce the old failure.
  After normalization and a faithful q4 row repair, each reaches ready after only the existing
  approved drops, publishes real observation bindings, compiles, and completes the fake engine.
  No invalid DATE arithmetic reaches the dry-run. An uncorrected q4 remains blocked after its
  one repair. Cover every ingress plus projection collisions, unions, proof removal, protected
  definitions, unknown aliases and non-identity expressions; verify idempotence and unchanged
  18.2/21.1/22.1, style/data/no-reference results. Live readiness and visual evidence are separate
  gates in tasks 24.9/24.10; offline success cannot approve fidelity.

### Blueprint observation coverage
- Problem (final audit 2026-10-23): in recreate mode the Blueprint planner never sees the image
  observations and Blueprint feasibility never checks rows against them, so a Blueprint reports
  ready and accept then fails publish coverage (`422 invalid_request`, "Candidate no longer
  fulfills") with no recovery: b_48ef72ff1bff (observed monthly series, no month bucket field)
  and b_dfb67c24f176 (observed table, bar row).
- Inputs and outputs: the active supported image observation requirements after
  #Recreate definition reconciliation (reconciled meaning only: kind, chart candidate, metric
  label/field, aggregation, unit, date grain, label; no boxes, image bytes or rows) -> (a) a
  compact `observations` section in the blueprint context; (b) per observation, a verdict on the
  Blueprint rows: fulfilled by named rows, or an Issue on the Assessment.
- Rules:
  - Fulfilled means at least one ok row meets the same observation checks publish coverage
    applies to a component (chart type, metric field and aggregation, dimension, date grain,
    label as #Recreate definition reconciliation binds them). Invariant: when Blueprint
    feasibility is ready for every observation, accept's publish coverage raises no error for
    them on the candidate (code-laid or designed).
  - Unfulfilled observations join the existing one row repair with their errors (no extra model
    call); what still fails becomes an Issue with code-built alternatives where code can build
    one: the observed chart type replaces the row's type when the catalog accepts the row's
    fields for it; a derived date-bucket field at the observed grain added to the view (built and
    dry-run by the view builder); otherwise needs_data or needs_clarification per #Recreate
    definition reconciliation. Drop is an explicit user decision recorded with provenance;
    code never drops or rebinds an observation by itself.
  - Accept with an unresolved observation issue -> `409 feasibility_blocked`, like other rows.
    Style mode, data mode and builds without observations: unchanged behavior and bytes.
- Edge cases: two observations one row satisfies (both bound to it); an observation whose
  metric is unsupported keeps its existing unsupported verdict; a reference replaced or removed
  after drafting marks the Blueprint check stale (existing freshness rules), never ready.
- Budget: the observations section fits the blueprint's 14k input (drop order: observation
  labels before fields); no new model call or repair; the deterministic recomputation oracle
  (<= 100 ms) still holds with 24 observations.
- Oracle: offline fixtures rebuilt from read-only copies of b_48ef72ff1bff and b_dfb67c24f176:
  before the fix the Blueprint is ready and accept fails coverage; after it the Blueprint shows
  the gap as an Issue with its alternative, the decision makes it ready, and accept publishes
  with every observation bound to a real component (recipe compiles, fake engine done). The
  21.1 and 18.2 recreate fixtures still publish unchanged.
- Built (task 22.1): the observations are the current recreate reference's image and
  instruction records that publish coverage checks, minus dropped, retired, layout-only and ones
  with their own unresolved issue (stale ones stay; freshness blocks them). One bound by
  component ids or non-label properties can't be checked against rows: needs_clarification. An
  alternative is offered only when recomputed coverage fulfils it and keeps every other
  observation. A drop is a requirement-level ledger decision with `source_id` and `issue_id`.

### Multi-page feasibility scope
- The Outline limit is 24 selected questions, not 24 rendered components. A question may have
  1-3 Blueprint rows; each page may have at most 12 rows, over 1-5 pages. A valid staged
  dashboard can therefore contain up to 60 components. Preserve the existing row, page,
  question, capability, field and KPI checks; do not invent a lower total-component ceiling.
- Preflight, candidate publication, explicit reassessment, revision, recipe and run must agree
  on this scope. A valid three-page 9+9+9-row dashboard must remain ready after layout and
  reach prototype, recipe and a fake-engine done result; five pages of 12 rows must also be
  assessed without the obsolete scope refusal. Invalid Blueprint page counts/capacity and
  unsupported requirements still reject before dependent side effects.
- Keep the existing 100 ms recomputation oracle for 40 requirements/24 components; that test
  workload is not an application limit. This requirement is currently broken at the legacy
  total-component check (final re-audit 2026-10-21); task 16.1 repairs it without budget changes.

### Spec layout
- Problem: blueprint + design -> a valid spec with no model call (replaces the spec node).
- Rules: pages from the page plan (names = section titles; single -> the design title); theme
  from the design; decorations from the preset's kit (title, subtitle, section heading,
  synthetic footer when required); components from ok rows in order, `question_ref` = question id;
  per page: controls row, then scorecards (up to 4 per row), then charts packed by a per-type
  default footprint and the density (time_series, table and pivot_table full width; others half
  width), each at least the catalog's `min_w`/`min_h`; page height grows to fit; no overlaps; a
  page whose rows were all dropped is omitted (later pages renumber, names kept).
  Deterministic: the same inputs give byte-identical spec.json. The result passes the existing
  validator (Dashboard Spec) unchanged except for the page count.
- Controls come first, then scorecards (at most four per row), then charts; density chooses
  footprints. Page 1 owns the synthetic footer; later pages keep their own height.
  Use background.write_pages(spec, folder), which calls render(page=n), never a stacked canvas
  screenshot. Insert explicit heading breaks with auto_layout._wrap before text-fit validation:
  Chromium's hanging pre-wrap spaces can protrude after a soft wrap at any height.
- Oracle: tests/test_layout_auto.py: golden blueprint + design -> golden spec; property test
  (fixed seed): any valid blueprint (<= 12 rows per page, 1-5 pages) gives a validator-valid spec.

### Graph
- Problem: one ADK 2.0 `Workflow` that is the harness's agent run for every action.
- Model check: at startup and when settings change, list the available models; if the planner
  model is missing, log a warning and use the worker model for blueprint.
- Inputs and outputs: `{action, build_id, payload}` -> SSE events, DB writes, one trace.
- Rules (change staged workflow 2026-10-21): START -> router(action) -> the action's branch. LLM
  nodes: context, outline_propose, outline_suggest, outline_other, blueprint, revise, ux_audit,
  style_extract, research, consolidate, reference_extract, synthetic_schema, designer (planner),
  reference_brief (planner), reference_html (worker; change 2026-10-25). Code nodes: intake,
  profile, artifact validation and write, feasibility, view (SQL build + dry run), layout, validate,
  render, compile, execute, publish, synthetic_generate. Repair edges: context -> context (once),
  blueprint rows -> blueprint (once), view dry run -> blueprint (once), revise validate -> revise
  (once), design measure -> designer (once per page). The designer runs in the prototype action
  after layout and in revise when a designed page is regenerated (#Designed pages). With a
  reference, the brief -> HTML stages replace the designer call within that same Workflow/trace
  (#Reference design brief, #Reference HTML composition); no new API action. The interview, plan and spec nodes and per-message requirement extraction are removed;
  extraction runs only inside outline_other, revise (comments) and reference actions, as a node in
  that action's Workflow. Every branch ends at a guardrail node.
- Edge cases: unknown action -> error, no LLM call; concurrent actions on one build -> the second
  gets `409 wrong_stage`.
- Approach: builder's choice within ADK 2.0 (`Workflow(edges=[...])`, router nodes, function
  nodes, `LlmAgent` nodes); see https://adk.dev/2.0/ and https://adk.dev/graphs/routes/index.md.
- Oracle: tests run each branch with FakeLLM and assert the node order recorded in the trace spans.

### Working memory assembly
- Problem: give each LLM node only what it needs, in a cache-friendly order, under a token budget.
- Inputs and outputs: node name, build, user input -> ordered list of context sections + the
  token count per section (recorded in the trace span).
- Rules (change staged workflow 2026-10-21): order = system prompt (`prompts/v1/<node>.md`) ->
  skills -> semantic concepts (catalog, archetype, themes) -> compact data profile -> upstream
  artifacts (frontmatter only) -> this action's input; stable sections first so Gemini's implicit
  prefix caching can hit. No node reads data rows, the chat history or FTS hits. Per-node recipe:

  | node | skills | semantic | other |
  |---|---|---|---|
  | context | context, archetype-<x> | archetypes/<x>.md | compact profiles, notes, reference labels |
  | outline_propose | outline, archetype-<x> | archetypes/<x>.md, user facts | context, field list, reference observations |
  | outline_suggest | outline | archetypes/<x>.md | context, field list, the section and its questions |
  | outline_other | outline, capability-check | - | context KPIs and fields, the section, the user's text |
  | blueprint | blueprint | catalog summary (allowed types, slots, options) | context, field list, selected questions, page plan, join facts |
  | revise | revise | catalog/<types of targeted components>.md | targeted components + their grid neighbours only |
  | ux_audit | ux-audit | archetypes/<x>.md | spec summary (ids, types, boxes) |
  | designer | dashboard-design | icon names list | design theme/title, the page's name and components (id, type, label, min px size), page 1's width and CSS (later pages), previous page HTML + comments (regenerate) |
  | reference_brief | reference-design | icon/art names, supported styling summary | mode/instructions, reference images/notes, compact approved-component report, theme, shared CSS or previous HTML/comments |
  | reference_html | dashboard-design (Reference rules) | icon/art names | validated brief, immutable slots, reference images/notes, theme, shared CSS or previous HTML/comments, repair errors |
- Budgets (input tokens): context 10k, outline_propose 8k, outline_suggest 6k, outline_other 6k,
  blueprint 14k, revise 6k, ux_audit 10k, designer 12k (output <= 16k including thinking),
  reference_brief 12k/4k output and reference_html 12k initial input, 24k repair input / 16k
  output (thinking included; change 24.8, user). Only the internal second HTML attempt gets
  the repair limit; reference_brief, no-reference designer and every other node keep their limits.
  Reference-stage images, instructions, approved slots/decisions and brief are mandatory, not
  droppable reference-label sections. Reference HTML repair may replace duplicate representations
  as specified in #Reference HTML composition; it never drops authoritative facts to fit.
  Both new nodes use the existing conservative enforcement
  allowance used by designer, including images/schema/repair. Over budget -> shorten profile value lists to the top 5,
  then drop reference observations, then semantic concepts beyond the first; never drop the
  system prompt, skills, upstream artifacts or user input (if those alone exceed it, refuse with
  `llm_unavailable` detail `over_budget`). Count with the API's token counter or
  chars/4 when offline.
- Offline assembly may use chars/4 as an estimate; live requests must count the complete
  effective request with the configured model's token counter before generation, including
  instructions, schemas, tools, contents, images and repair text. Apply the documented drop
  order and recount. Counting failure returns sanitized `llm_unavailable`, rather than
  generating over budget. Record estimated section counts separately from the authoritative
  request count. Counting calls do not add generation calls or consume the research scraper
  quota; preserve all generation/repair limits.
- Deferred hardening (change 2026-10-20; PRD Later, former 13.8): the Developer API only counts
  contents; folding instructions/schema/tools into text has
  measured undercount (8,245 folded vs 8,695 billed). Do not call that folded value an exact
  effective-request count or compare it directly to the hard budget. Retain it separately,
  use a conservative complete-request enforcement allowance, refit/recount against that bound,
  and record the enforced bound and billed usage distinctly. Calibrate the allowance against
  real structured/tool/vision/repair requests, including near-boundary cases; if the bound
  cannot be established, refuse generation. No budget relaxation is authorized by this audit.
- Oracle: unit tests assert section order, budget enforcement and the drop order.

### Episodic retrieval
- Change staged workflow 2026-10-21: no model node reads chat history or FTS hits any more;
  messages stay the episodic log for the UI and consolidation. The rules below stay for
  `messages_fts` and its tests.
- Problem: past context that is both recent and relevant, without embeddings.
- Rules: recency = this build's last 12 messages (current chat history); relevance = FTS5 `bm25`
  over `messages_fts` of other builds, query = the user input's terms (stopwords
  removed), top 3; merge = union, dedupe by id, relevance hits first, then recent; each hit carries
  its date and build title.
- Edge cases: empty FTS query -> recency only; FTS special characters escaped.
- Oracle: unit tests with seeded rows (a dissimilar-but-recent and a similar-but-old message both
  appear; duplicates removed).

### Consolidation
- Problem: distill episodes into durable facts in semantic memory (the only semantic write path).
- Rules: after a build reaches `done`, `chats_since += 1`; when it reaches `DSS_CONSOLIDATE_EVERY`
  (default 5; 1 for the demo), the consolidate node
  (worker model) reads those builds' context, outline and design summaries and decisions plus `data/knowledge/user/
  index.md`, and writes OKF concepts (`type: User Preference` or `Design Decision`) under
  `data/knowledge/user/`, updates `index.md`, prepends to `log.md`; then `chats_since = 0`. A
  changed fact keeps the old value under "Previously" with its date. Runs after the build's
  response, never blocking it.
- Count each successful/partial `build.finished` under the snapshot lock; consume only the
  count included in a successful snapshot, preserving builds completed while it ran. Inputs
  are context/outline/design/decisions (old builds: brief/design/decisions), at most 3000 characters each, newest first; skip missing docs.
  Consolidation has its own Workflow and one build-less trace. Failure preserves the counter.
- Oracle: test with FakeLLM and `DSS_CONSOLIDATE_EVERY=5`: 4 builds -> no write; 5th -> files written, counter reset, every
  file has parseable frontmatter with non-empty `type`.

### Reference interpretation
- Problem/objective: derive reviewable visual intent from screenshots, preserving the existing
  deterministic spec -> prototype -> recipe path. Source rules: ../contracts/dashboard-intent.md
  1.1 (Reference set and Required oracle cases); that contract owns API/lifecycle behavior.
- Input: validated reference bytes, mode and instructions. Output: StyleProfile plus a bounded
  ReferenceInterpretation: mode, canvas aspect ratio, palette/type/spacing notes, and up to 24
  observed items {id, kind, label, box{x,y,w,h}, chart_candidate|null, metric_label|null,
  unit|null, aggregation|null, date_grain|null, confidence:high|medium|low}. Box coordinates are
  normalized to 0..1, positive dimensions, inside the image; null means unknown, never a guess.
  kind is chart|control|decoration|unknown. Style mode does not import chart/data requirements.
- Constraints: one recreation screenshot, one page, existing 1200px/12-column target; map relative
  placement into that grid. Explain structural changes such as unsupported widgets and compression.
  Screenshots with more than 24 elements must request a crop/simplification, not silently truncate.
  Labels <=120 chars, notes <=1000, instructions <=2000; profile is local Pydantic-validated.
- Budget: one worker vision generation, no repair loop, 12k full counted input / 4k output maximum;
  use fit_request with images included. Reject over-budget requests before generation. No network
  calls except existing model transport/counting. Original images and their text are untrusted.
- Image checks, in order: streamed byte limits; signature/extension/MIME agree; width and height
  read from the PNG IHDR / JPEG SOF header with stdlib before any decode (>20 MP rejects without
  launching Chromium); PNG with an `acTL` chunk (APNG) rejects as animated; then Chromium decode.
- Persist atomically per contract. New reference extraction replaces observations but preserves
  old artifacts on failure; reference mode success requires explicit replan to affect a prototype.
- Oracle: tests/test_references.py covers both modes, structured boxes, count/byte/pixel limits,
  corrupt images, prompt-like image text, replacement rollback, deletion, reload and version copy.
  A live synthetic screenshot proves actual image parts reach Gemini and extracted geometry/theme
  reaches the deterministic spec. Do not claim pixel-identity based on that check.

### Capability verification
- Problem: an allowed chart type alone cannot prove that the requested behavior is implementable.
  Objective: preserve every explicit requirement and explain unsupported/unknown work early.
  Source of truth: ../contracts/dashboard-intent.md 1.1 (Capability evidence, assessment,
  enforcement and oracle). Record product evidence separately from application/engine evidence.
- Registry: knowledge/datastudio/capabilities.json, explicit version and dated records, validated
  by Pydantic. Initial coverage is the recipe 1.0 surface plus negative animation/streaming/custom
  widget cases. App support cites ../contracts/recipe.md, recipe.schema.json or a contract
  fixture that exercises it (the engine's files are another part's); an option the schema accepts
  with no such citation is unsupported_app. Tests derive coverage from recipe.schema.json.
  Keep product sources in OKF product-limits.md and link the registry in knowledge indexes.
- Input (change 2026-10-21, dashboard-intent.md 1.2): blueprint rows, confirmed KPI definitions,
  design choices, outline `other` text, comments, current requirements/decisions, reference
  interpretation, schema and effective registry. Selected questions and blueprint rows are
  structured requirements and skip extraction. Output: requirements.json plus Assessment/feasibility.md.
  Internal requirement: id, source reference (message/comment/image item), text, capability ids,
  proposed fields/unit/aggregation/grain, resolution and component bindings. Preserve provenance.
- Extract with at most one worker generation per outline `other` text/comment batch/reference change,
  as a node in that action's Workflow and trace (Graph);
  input <=24k full counted tokens, output <=8k (change 2026-10-24; was 12k/4k: release 2.6's
  requests grew 6.9k -> 12.7k over one build's comments and an output reached 3,839 of 4,000, so a
  one-line "enlarge the globe" comment hit the scope refusal), max 40 requirements, max 20
  active issues/alternatives total (dropped or decided issues don't count). A comment batch's
  request carries only the ledger rows bound to its target components plus unbound rows; code
  keeps every other row unchanged. Use full existing request guard; no unbounded retries,
  repairs or live searches. If limits are exceeded, remain blocked with a reason that names the
  limit hit (input budget, output limit or issue count) and its size, never a bare "reduce the
  scope". Deterministic recomputation performs
  no model call; target <=100ms on 40 requirements and 24 components excluding disk/model time.
- Keep the active requirement ledger and explicit decisions mandatory in plan/spec/revise contexts;
  no dropping them as episodic context. Reconcile image metric names to real fields/definitions:
  ambiguity requires user clarification; no automatic gross/net, sum/avg or grain substitutions.
  Derive fields only through the existing SQL view pipeline once the intended definition is clear.
- Registry validation rejects unknown keys, enum values and unsupported feature combinations,
  including model attempts to place animation under a valid geo_map. Check fulfillment against the
  original ledger so removing the unsupported option cannot masquerade as success.
- Assess before SQL side effects, before publishing a spec/prototype and before compile/execute;
  use the existing lock and staged rollback. Legacy builds start unchecked. Runtime registry,
  data, reference, spec or allowlist changes invalidate the assessment; durable unchanged choices
  survive if their prerequisites and selected capability remain valid. Persist blocked comment
  batches for reload/reapply/abandon. Recovery uses explicit assessment/check, not model work in GET.
  Offline agent status is still a separate run precondition, not a product limitation.
- Supported behaviors must agree across renderer, compiler and engine. Decorative theme/background
  flattening may match a reference; interactive charts must be real bound components. Never send
  a whole reference screenshot as the resulting dashboard background to hide missing behavior.
- Oracle: tests/test_capabilities.py and tests/test_feasibility.py exercise all eleven contract cases,
  plus confirmed choices replayed against changed spec/registry and supported requests with no image.
  Live plan smoke compares expected refusal/mapping to the persisted ledger, not prose alone.
- Deferred hardening (change 2026-10-20; PRD Later, former 13.7): a saved dashboard that fails
  fulfillment at execution is to stay blocked or visibly prototype-stale
  through GET, unchanged explicit checks and reload. Support alone must not overwrite a
  fulfillment failure with ready/non-stale. Replan/reapply may recover only after coverage of
  the repaired artifact passes; pending supported comments retain their explicit reapply flow.

### Interview feasibility recovery
- Superseded by #Staged workflow (change 2026-10-21): the interview and its per-message
  extraction are removed. Audience and goal live in the Context; incomplete definitions are
  Context issues the user fixes on the KPI cards. History: tasks 14.1 and progress.md.

### Conversational definitions and supported styling
- Superseded by #Staged workflow (change 2026-10-21): metric definitions are structured KPIs in
  the confirmed Context, so no formula is parsed from chat; styling comes from the Design
  (presets, palette), and comments still revise per-chart colors (task 14.2's `colors` stays).
  History: task 14.2 and progress.md.

### Synthetic data
- Problem: a reference can describe a dashboard without supplying its source data. Offer explicit
  synthetic generation instead of requiring a CSV before the app can proceed.
- Source: ../contracts/synthetic-data.md 1.1. It specifies GenerationSpec, generators/relations,
  API lifecycle, limits, storage and oracle. Implement a reusable Python generate_csv function
  and module CLI in data/synthetic.py; no model/cloud dependency for the local generator.
- One bounded worker schema proposal uses recreate observations; fields/distributions/definitions
  are suggestions with assumptions. User edits/accepts schema, row_count and seed; Python generates
  rows deterministically. Never ask the LLM to emit bulk CSV or execute generated Python.
- API orchestration: synthetic_data.py -> code generation -> completed file/provenance -> existing
  intake extended with explicit BQ types -> registered synthetic Source. Schema proposals work
  in Connect with zero sources. Generation remains bounded and uses the existing action lock.
- Generation table (Data model) holds key/hash/run/source/table/state and is the only job
  record; job status reads it, never SSE. Durability (contract 1.1, task 12.4): reservation and
  registration each commit in one transaction, then call the existing backup routine at once
  (same lock and dirty flag; best-effort: a failure logs a warning, the periodic backup retries)
  before the 202 and before run.finished. Startup, before serving, turns every in-flight row into
  failed `generation_interrupted`, cleans only that row's generated prefix and BigQuery table,
  then sets retry_ready. No manifest files, no reconciliation pass.
- Local output uses DSS_DATA_DIR/generated; hosted uses the existing GCS volume, with generation
  in local temp and metadata-last publication. Downloads authorize source ownership and only
  serve registered completed files. No new dependency, environment variable or bucket.
- Typed synthetic loading bypasses prepare_csv row dropping/renaming; verify exact row count.
  Use declared schema, never autodetect; set the load's null marker explicitly to the empty
  field so all-null columns and all-empty rows load as NULL, not '' or a parse error. Add
  Source.kind=synthetic; preserve provenance through versions. Reference labels infer proposed
  schema only, not original values; never silently supplement or overwrite a real dataset.
- Enforce an unremovable Synthetic sample data decoration in the deterministic spec/render/
  background/compile path for synthetic source participation. Its box is reserved by layout,
  read-only to revise; image-based styling cannot hide it. UI also labels sources/prototype.
  The background PNG is the report's one copy of the label: the recipe places no text op for it
  (change 2026-10-23: a native text op over the background label drew it twice, overlapping).
  Keep source provenance authoritative when validating model output or old copied specs.
- Budgets/oracle are contract sections Generator request/Acceptance oracle; offline generator
  tests cover deterministic bytes and relationships, API tests fake model/BQ/storage; one live
  screenshot-only path validates schema proposal, typed load and the final report label.
- Deferred hardening (change 2026-10-20; PRD Later, former 13.6): validate numeric magnitude
  before float conversion. Arbitrarily large JSON integers in
  decimal bounds, choice/lookup values or dependencies produce field-specific SyntheticError,
  HTTP 422 and a clean nonzero CLI exit, never OverflowError/500/traceback or a partial CSV.

### Plan publication
- Ownership: nodes/blueprint.py (accept), view.py, render.py and data/bigquery.py stage docs,
  candidate view and rendered files. Persist candidate run ownership before creation; on failed
  attempt/restart clean only abandoned candidate views, never published/legacy view identities.
  Keep previous artifacts until new files/spec/table pointer are committed under the build lock.
  No schema migration of old view names: accept existing table identities, use unique names only
  for new attempts. This is superseding behavior for old create-or-replace SQL golden tests.

### Replan freshness recovery
- Problem: release 2.5 build b_24747c71b7e3 remained ready but prototype_stale after reference
  deletion and successful regeneration/acceptance; recipe returned 409 feasibility_blocked
  with no issues. A repaired artifact must become executable without weakening the old-artifact gate.
- Inputs: current intent, reference set, confirmed staged artifacts, connected schema, effective
  registry/allowlist, active ledger and candidate spec/prototype/view. Output: one published
  bundle with its matching assessment, digest, verification and artifact-freshness state.
- A successful explicit replan may clear the old artifact's stale flag only after candidate
  support and coverage validation under the existing build lock. Publish the new proof and fresh
  state with the candidate bundle. Revalidate preserved decisions against current prerequisites.
  GET, an unchanged feasibility check, a restored allowlist or merely resolving an issue never
  authorize the old artifact. Pending comments retain their separate reapply/abandon lifecycle;
  replanning must not silently apply, clear or authorize them.
- Replacement/deletion of a reference, changed outline requirements and an allowlist narrowing
  can each invalidate a built artifact. All use the same recovery rule. An intent change during
  generation, unsupported candidate or failed render/publication preserves the previous published
  artifacts and applicable stale/blocked state; candidate cleanup cannot delete a published view.
- Budget: deterministic work within the existing feasibility budget, with no added model calls
  or repair attempts. Keep API and event shapes, legacy builds and version isolation unchanged.
- Oracle: staged API tests begin with an accepted prototype, invalidate it through each trigger,
  prove recipe/run blocked, then explicitly regenerate and accept a valid candidate and prove
  ready/non-stale, recipe success and fake-engine completion. Reload preserves the outcome;
  publication failure and changed intent preserve the old bundle and execution block. Pending
  comments still require their existing explicit action. Tests live in test_feasibility.py,
  test_render.py and test_publication.py. Release 2.5 owns the real-model/engine replay.

### Recreate definition reconciliation
- Problem: release 2.5 b_b4319fb6113d retained needs_clarification for screenshot metrics even
  with explicit definitions; dropping the observations made the test cease to prove recreation.
- Inputs: active image observations with reference/image/item provenance, user reference
  instructions, confirmed Context KPIs and their artifact state, connected schema, blueprint
  rows and current decisions. Output: reconciled mappings and coverage proof, or actionable
  clarification/data issues. Every active observation remains accounted for.
- Reuse a confirmed Context KPI for an unambiguously matching observation metric label/id,
  preserving its field, aggregation and any supplied unit/date-grain semantics. Do not require
  a repeated conversational definition. Read confirmed Context independently of whether a
  Blueprint exists; draft/unconfirmed edits cannot authorize a mapping. Confirmation changes,
  removed definitions or schema/reference changes invalidate the associated proof.
- User-entered reference instructions are definition evidence, unlike model guesses or text
  inside image bytes. Honor explicit formula clauses already within the definition surface,
  including `Revenue = SUM(revenue) in USD`, and coordinated definitions for distinct labels.
  Retain source provenance when an instruction clarifies an image item. Recompute from active
  evidence so removal/replacement cannot leave an orphaned instruction binding behind.
- A matching field name alone does not define a metric. Gross/net, sum/avg, count/distinct count,
  unit and date-grain conflicts stay unresolved until explicitly clarified; conflicting active
  instructions and confirmed KPIs must not silently override one another. A later confirmed
  KPI edit replaces its prior artifact definition but must still satisfy the current image
  request and schema. Missing fields remain needs_data. Ratios and unsupported capabilities
  retain their existing refusal/alternative path. Never bind two metrics merely because they
  share a field, and never drop an image observation to make acceptance pass.
- Carry the reconciled meaning through preflight, candidate coverage, publication, deterministic
  checks, recipe/run and version copy. Successful publication binds each supported observation
  to actual component ids; decoration-only flattening cannot satisfy a live-chart requirement.
  Style-only images still introduce no chart/data requirements. Legacy message/comment behavior
  is preserved; this does not restore the removed interview flow or create a new parser API.
- Accept titles an observed chart with its screenshot title in code (21.1,
  `requirements.observed_labels`), only when the titled candidate's coverage errors are a strict
  subset of the untitled one's and the spec validates; date-bucket SQL is compared trimmed; a
  non-comment observation's component ids not in the spec are ignored. The Blueprint check
  before accept: #Blueprint observation coverage.
- Budget: existing extraction/model/repair limits and <=100 ms recomputation oracle unchanged;
  definition reuse and revalidation add no model call. No new dependency or contract shape.
- Oracle: offline staged API fixtures with supported image observations and a connected schema
  cover confirmed KPIs and explicit instructions separately and together, before/after Blueprint
  creation; acceptance retains all observations, publishes real component bindings, compiles a
  recipe and reaches fake-engine done. Negatives cover ambiguous/conflicting definitions,
  unconfirmed edits, missing fields, unsupported observations, instruction removal and changed
  KPIs/schema; reload and version copy preserve valid evidence but not invalid authorization.

### Recreate observation completion
- Problem (task 24.7 block, change 2026-10-25): the electricity recreate fixture stays blocked
  at 21 issues. Its definition-only instructions become `unknown` requirement rows; `Region
  Selector = region` isn't accepted as an explicit control field; `date grain year using year`
  doesn't name the date field; a scorecard observation is asked for a year grain; and the
  Blueprint lacks the observed yearly bar after the one repair. Evidence: .blueprint/qa/task-24.7/
  recreate/20261025-104805-795461ae/ (assessment.json, issues-uncapped.json, build/).
- Inputs and outputs: as in #Recreate definition reconciliation and #Blueprint observation
  coverage. Output: the same Assessment shape and decision API (no contract change).
- Definition surface (user-entered reference instructions only; one clause each):
  `<Label> = <metric>[ and <metric>...][, unit <u>][, date grain <g>[ using <date field>]][,
  chart <catalog type>]`, where `<metric>` is `AGG(field)`; and `<Label> = <field>[, chart
  <type>]` for a control or dimension. Labels match observation `label` or `metric_label`
  case-insensitively after trimming. Units may be symbols (`%`). The existing forms stay valid.
- Rules:
  - An instruction clause that is wholly a definition becomes definition evidence only, with no
    requirement row and no `unknown` issue. Unused definitions raise no issue, and the
    reconciliation span lists them. A sentence that isn't wholly definitions stays a
    requirement, as now. A field missing from the schema -> needs_data; conflicting
    definitions for one label -> needs_clarification (existing rule); an unknown aggregation
    stays unknown.
  - `<Label> = <field>` explicitly defines a control's control_field or a chart's dimension,
    never a metric (a metric still needs an aggregation).
  - `using <field>` binds the date field for that grain. It must be a DATE, DATETIME or
    TIMESTAMP field (or the code-built bucket at that grain); otherwise needs_clarification.
  - `chart <type>` overrides the observation's chart_candidate when the catalog accepts the bound
    fields for that type, else needs_clarification. The user's instruction outranks the
    extractor's guess.
  - A multi-metric definition is the user's explicit substitution: every observation it defines
    is checked against that meaning, so one row can satisfy several observations (existing
    edge case).
  - Scorecard observations: date grain is not a coverage check, because a single value has no
    time axis. This is one shared rule in `coverage_errors`, so the Blueprint check and publish
    coverage agree.
  - Blueprint completion: after the one existing row repair, each observation still unfulfilled
    whose reconciled meaning is complete (catalog type, metric fields and aggregations,
    dimension or date field) gets a code-built row. It goes on the reference's page (page 1),
    is validated by the existing row and capability checks, has its date bucket built and
    dry-run by the view builder, and carries `observation <ref>:<item>` provenance in the row
    note. No model call. With no capacity left (12 rows) or an incomplete meaning, it stays an
    Issue, as now. Code never drops, retypes or rebinds an observation on its own: added rows
    only fulfil the observation's meaning.
- Edge cases: an added row a later redraft would duplicate counts once (rows already fulfilling
  it win). Removing the instruction or reference recomputes and removes code-added rows that no
  longer fulfil anything. Style mode, data mode and builds without a reference: unchanged
  behavior and bytes.
- Budget: no new model call; the 100 ms recomputation oracle holds with 24 observations and
  24 definition clauses.
- Oracle: an offline staged fixture rebuilt from read-only copies of the 104805 run's inputs
  (references.json, requirements.json, blueprint-inputs.json; tests/live/test_reference_design.py
  INSTRUCTIONS, updated to the surface above). Before the fix it is blocked with the 12
  definition `unknown` rows. After it, the only issues are the user-approved drop classes
  (geo_map needs_data, the misread Rural/Urban legend control, a year slider if extracted). With
  those dropped it is ready, and accept publishes every other observation bound to a real
  component: region fixed_size_list, the AVG(access_pct) scorecard, the code-added yearly
  SUM(people_without_access) bar, and one urban/rural area chart bound to all four per-country
  observations. The recipe compiles and the fake engine is done. The 18.2, 21.1 and 22.1
  fixtures publish unchanged.

### Build docs
- Problem: the durable design brief (OKF bundle per version), written by code (change 2026-10-21).
- Rules (change staged workflow 2026-10-21): `data/builds/<id>/v<n>/docs/` holds `index.md`,
  `log.md`, `data-profile.md` (`type: BigQuery Table`, #Data profile), `context.md`,
  `outline.md`, `design.md`, `blueprint.md` (#Staged workflow, all written by code),
  `feasibility.md`, optional `style.md` (`Style Profile`), `decisions.md` (`Design Decisions`,
  appended by revise). Every file has OKF frontmatter. Builds made before the change keep their
  old docs (brief, questions, kpis, derived-fields) and their spec; a new version from them works,
  and re-planning one starts at context.
- Oracle: test asserts every doc parses and has its `type`.

### BigQuery view
- Problem: one active view per accepted spec holds joins and derived fields; old report views
  remain stable. New plan attempts create a distinct candidate (change 2026-10-19).
- Rules: new attempts use `CREATE VIEW <project>.<BQ_DATASET>.dash_<build_id>_v<n>_<run_id> AS SELECT <base
  columns>, <expr> AS <name> ... FROM <base> [LEFT JOIN ...]`, built by code from the blueprint's
  `view_sources` and `derived_fields` (union: NULL-padded `UNION ALL` with `dataset_name`; change
  2026-10-21); every identifier backtick-quoted (reserved words such as `date`, `order`,
  `group` must work); field names snake_case and unique; `date_like` STRING columns exposed as
  `SAFE.PARSE_DATE` (or `SAFE_CAST` to TIMESTAMP) under the same name; dry run first; on dry-run
  error, one blueprint-node SQL repair with the error text, then fail. A new version (`POST
  /versions`) reuses the latest view (the spec's `datasource.table`) unless re-planned.
- Oracle: unit tests on the generated SQL strings (golden strings); live manual check.

### Dashboard Spec
- Problem: the single source of truth code lays out, renders and compiles. auto_layout writes
  it from confirmed artifacts; only revision patches come from the model (change 2026-10-21).
- Inputs and outputs: pydantic model, saved as `spec.json`:
  `{spec_version, build_id, title, archetype, canvas{width:1200,height}, grid{columns:12,
  row_height:20, gutter:16, margin:24}, theme{background, surface, text, muted, accent,
  palette[], font_family, radius}, datasource{table, fields[{name, type, label, role, default_agg}]},
  pages[{index, name, height, decorations[], components[], design?}]}`. 1-5 pages (change 2026-10-21).
  Decoration: `{id, kind: band|panel|title|subtitle|text|logo|divider|design, grid{col,row,w,h}, text?, style?}`.
  Component: `{id, type, label, grid{col,row,w,h}, box?{x,y,w,h}, dimensions[], metrics[{field,agg}],
  date_dimension?, breakdown?, sort?, options?, text?, image_path?, field?, question_ref?}`,
  Designed pages (change 2026-10-22, #Designed pages): `canvas.width` is an integer 1200-1920
  (code-laid builds keep 1200); a designed page carries `design{html, source, model}` (the
  sanitized page HTML, stored in the spec so versions and reloads need no model), one
  `p<n>_design` decoration of kind `design` covering the page, and a measured pixel `box` on
  every component; `grid` stays as the code layout's cell, the fallback if the design is dropped.
  `type` in the 12 catalog types: scorecard, time_series, bar, pie, table, pivot_table, geo_map,
  scatter, text, image, date_range, dropdown.
- Rules (validator): 1-5 pages; ids unique and snake_case with page prefix; types in the
  catalog and in `DSS_ALLOWED_TYPES` (the blueprint prompt lists only the allowed types); fields
  exist in `datasource.fields` with a role the catalog slot allows; dimension/metric counts within
  the type's catalog limits (`knowledge/catalog/<type>.md` frontmatter: `min_dimensions`,
  `max_dimensions`, `min_metrics`, `max_metrics`, `requires_date_dimension`, `min_w`, `min_h`);
  grid inside 12 columns and the page height; no two components overlap (decorations may sit
  under components); every blueprint row with status ok is a component whose `question_ref` is its
  question id, checked on the code layout output; a revise patch may remove a component, which
  decisions.md records (change 2026-10-21; old builds: questions.md high priority). Errors are a list of
  `{path, message}`, fed to the revise repair turn; a code layout that fails validation is a
  `run.finished(error)` with those errors (a defect, never sent to a model). On a designed page
  the same rules apply to `box`: inside canvas width x page height, no two component boxes
  overlap, each at least the type's `min_w`/`min_h` converted to pixels by Layout, clear of the
  reserved synthetic footer; `box` and `design` appear together or not at all on a page.
- Sort is a validated `{field, order: asc|desc}` object, matching the recipe contract. Renderer
  SQL and compiler consume that same shape; unknown keys or orders fail before publication.
  An explicitly ascending bar/table must render ascending as it will in Data Studio.
- Per-chart colors override the theme in both prototype and recipe. Scorecards take no colors
  (no series swatch; the recipe sends no `set_style` for them): feasibility returns
  `unsupported_app` for colors on a scorecard, so such a comment fails fast instead of staying
  pending (change 2026-10-22). COUNT/COUNT DISTINCT may
  take a dimension field. Blueprint dropdown rows have exactly one dimension, mapped to the
  control field by layout.
- Oracle: property tests on random valid/invalid specs (fixed seed) + golden invalid cases.

### Layout
- Problem: grid cells -> integer pixel boxes, identical for the prototype and the recipe.
- Rules: `col_w = (canvas.width - 2*margin - (columns-1)*gutter) / columns`; `x = margin +
  (col-1)*(col_w+gutter)`; `w = span*col_w + (span-1)*gutter`; `y = margin + (row-1)*row_height`;
  `h = rows*row_height - gutter`; round x and the right edge separately to integers so adjacent
  boxes keep a gutter of 16 ± 1 px; every box inside the canvas. A component with a `box`
  (designed page) returns that box unchanged; prototype, background and recipe all ask Layout,
  so they agree (change 2026-10-22).
- Oracle: unit tests: two side-by-side spans of 6 fill the content width; gutters 15-17 px; no
  box exceeds the canvas; a component with `box` gets exactly that box.

### Prototype renderer
- Problem: spec + data -> one HTML page matching ../contracts/api.md "Prototype HTML".
- Objective and budget: render + background for a 12-component spec in <= 15 s; aggregate
  queries run in parallel (thread pool of up to 8) and are cached per version by SQL hash, so a
  revise that moves boxes re-queries nothing.
- Rules: absolute boxes from Layout; each component drawn with ECharts (scorecard/text/controls
  as HTML) from a per-component aggregate query (`SELECT dims, AGG(metric) ... GROUP BY ...
  ORDER BY ... LIMIT 50` on the view; table/pivot LIMIT 20 rows); theme colors and font from the
  spec; `data-cid`, `data-label`, `data-kind` on every component and decoration;
  `layer=decoration` hides components; a chart type the catalog lacks can't render (raises).
  Background: Playwright Chromium (sync API in a worker thread) screenshots `layer=decoration` at
  canvas size and device scale 3 (change 2026-10-22: 3x pixels, e.g. 3600 x 1596 for 1200 x 532,
  so Data Studio's scaled view stays sharp; user target >= 1920 x 1080 px, each file < 2 MB, no
  minimum file size) -> `background_p<n>.png`, one per page (change 2026-10-21). Each page is a
  `section[data-page][data-page-name]` under `#dss-canvas` (../contracts/api.md 2.0).
  A designed page (change 2026-10-22) renders its `p<n>_design` decoration as one root element
  at 0,0 with the page's size holding the sanitized HTML (CSS scoped to that root, slots
  transparent), and the components as sibling elements on top at their boxes; no `data-cid`
  inside the design root. A designed page's PNG drops to device scale 2 only if its 3x file
  would be >= 2 MB (recorded in the trace); the recipe box is unchanged either way.
- Deferred preview parity (change 2026-10-20; PRD Later, former 13.4): supported options are to
  have matching visible semantics: bar orientation/stacking, pie donut,
  scorecard compact formatting, table rows_per_page (within the 20-row query cap) and pivot row/column assignments. Derive both aggregate
  grouping and displayed axes/cells from the accepted bindings; verify against independent
  expected values, not the renderer's own serialization. Preserve compiler contract bytes.
- Decoration text must fit its content box after font, wrapping, line height and padding;
  title/subtitle defaults are part of that measurement. Reuse the geometry/style rule across
  prototype, background and validation. Insufficient boxes are rejected into the existing
  repair path, or deterministically laid out without obscuring other items. Never bake a
  clipped heading into the final background; preserve the reserved synthetic footer.
- Recipe 1.3 types (change 2026-10-24): `area` draws an ECharts line series with area fill
  per metric or breakdown value on the date axis (stacked when `stacked`, normalised to 100 %
  when `stacked_percent`); a `bar` with `stacked_percent` normalises each category to 100 %;
  `fixed_size_list` is HTML: the field's distinct values (aggregate query, LIMIT 50) as a
  vertical list of unchecked checkboxes with labels in the theme font, scrolling inside its box.
- Edge cases: empty query result -> chart shows "No data"; very long labels truncated with title attr.
- Oracle: tests parse the HTML: one `data-cid` per spec item, boxes equal Layout's, decoration
  layer has no visible component; background_p<n>.png is 3x the page's canvas size in pixels
  and under 2 MB (designed pages: 3x, or 2x when 3x would reach 2 MB).

### Designed pages
- Problem (change 2026-10-22, user; target look docs/change-2026-10-22-reference.webp: light
  gray page, white rounded cards with soft shadows, KPI cards with pastel icon tiles, section
  cards with a title, a header with a bold title and subtitle): the planner designs each page's
  background as HTML/CSS around the native components; code turns it into component boxes and a
  background image, so Data Studio charts sit exactly in the AI's cards.
- Inputs and outputs: the laid-out spec (theme, title, pages, components with type, label and
  minimum size), the dashboard-design skill and the icon list -> per page `{canvas_width (page 1
  only), html}` from the designer node (planner model, `prompts/v1/designer.md`,
  `skills/dashboard-design.md`) -> code: sanitize -> render in Chromium at the canvas width ->
  measure -> a spec with `design`, the `p<n>_design` decoration, component boxes and the
  measured page height.
- Rules:
  - Slots: exactly one empty `<div data-slot="<component id>">` per component on the page; no
    slot for an unknown, missing or duplicate id. The designer never adds, removes or retypes
    components (types stay the blueprint's Data Studio types). Code empties and makes slots
    transparent; a card behind a slot is allowed.
  - Measured slot rect -> integer `box`; page height = the page root's measured height (within
    the validator's page-height limit). A box below its type's minimum, outside the page, or
    overlapping another box is a measure error.
  - No text, icon or image element intersects any slot box; every text element fits its box
    (no overflow or clipping, same rule as #Prototype renderer's text fit); on page 1 of a
    synthetic build, nothing intersects the reserved 64 px footer, which code still draws.
  - Sanitizer (stdlib parser, allowlist): structural/text tags, one `<style>` scoped to the page
    root, inline SVG limited to shape elements; strip scripts, event attributes, iframes,
    forms, links, `<use>`, `foreignObject`, `href`/`src`, CSS `url()`, `@import`, `@font-face`
    and `position: fixed`. Fonts: the theme font and fonts.md only. Chromium renders the page
    with JavaScript off and every network request aborted.
  - Icons: `<i data-icon="<name>">` -> the vendored Lucide SVG inline (`render/icons/`, ISC
    licence kept beside them); an unknown name is a measure error unless the model drew its own
    sanitized inline `<svg>` (the user's fallback).
  - Width: the schema accepts 1200-1920, but the designer prompt asks for 1200: the Data Studio
    editor zooms canvases wider than about 1380 px to fit and the engine then misplaces every
    component (20.5: 1440/1560 failed, 1200 ok). Code does not yet clamp it (PRD Later).
  - Order: page 1 first; it sets `canvas_width` (1200-1920) and the shared stylesheet; pages
    2-n then run in parallel with both as input. Each page: one repair turn with the sanitizer
    and measure errors, then that page falls back to the code layout and kit (trace span and
    assistant message say so). If page 1 falls back, the whole build uses the code path at
    width 1200 with no further designer calls.
  - Config flag `designed_pages` (default on; a Config attribute, not an env name or API
    setting, so no contract change). Off, a legacy spec, or a fallback page: today's code
    path, byte-identical output.
  - Revise on a designed page: comments on `p<n>_design`, geometry (move, resize, layout),
    removal, or heading/text/icon/decoration colors regenerate that page (designer with the
    previous HTML and the comments, then sanitize, measure, one repair); on failure the spec is
    unchanged and the comments stay pending with the errors as the reason. Data comments
    (metrics, aggregation, sort, chart colors, type) use the revise patch with no designer call,
    unless the new type's minimum no longer fits its slot, which regenerates the page.
  - Coverage: a decoration requirement on a designed page (a heading text, a hex color) is
    verified by its presence in the sanitized `design.html`; components keep their recipe checks.
    A coverage failure records its errors in the `publish` span (change 2026-10-23). Specified
    but not built: a page whose design alone breaks publish coverage falls back to the code
    layout and kit (`designer_fallback`, reason `coverage`); 21.1 found the recreate failures
    came from titles, SQL text and stale component ids, not designs, so it built no fallback.
  - Reference (change 2026-10-25, supersedes 24.5's one-stage proposal): for either mode, use
    #Reference design brief then #Reference HTML composition. Images reach both stages; native
    slots remain authoritative. The generic look applies only without a reference. No-reference
    model requests, routing, bytes and repair/fallback behavior remain unchanged. The screenshot
    is never placed in the background; slot, sanitizer, text-fit and footer rules still apply.
    Change 24.8: when designed pages are enabled, failure on any reference page stops acceptance
    instead of using the kit, including failures before HTML generation or during assembled-spec
    validation. This overrides the general fallback rules above for reference builds only.
  - Art (change 2026-10-24): `<i data-art="<name>">` -> a vendored static SVG from
    `render/art/` (like icons: inlined by code after sanitizing, scaled to the element's CSS
    box), so a real globe or world map costs the designer one tag instead of tens of thousands
    of path tokens. Art: orthographic globes centred on Europe/Africa, the Americas and
    Asia/Pacific, and a flat world map, generated by a committed stdlib script from Natural
    Earth 110m Admin 0 countries (public domain); every country path carries
    `class="land <continent> c-<ISO_A3>"` so page CSS colors land, continents or single countries
    (a static choropleth look); each file <= 80 KB. The context lists the art names; an unknown
    name is a measure error. Art is decoration: it never binds data and never enters a slot.
  - Determinism: the model runs only in the prototype action and in revise regeneration, never
    in GET, recompile or new versions; the same spec gives the same prototype, PNG and recipe
    bytes.
- Edge cases: model output that isn't valid HTML or has zero slots -> repair, then fallback; a
  text that only fits by shrinking below 12 px -> measure error; a 5-page build -> 1 + 4
  parallel calls.
- Budget: no-reference designer input <= 12k tokens (traces before 2026-10-24:
  ~3-4k text, 769-3,002 output), output <= 16k including thinking (low thinking level),
  each call within the planner's 120 s deadline; sanitize + measure + background for a
  12-component designed page <= 15 s excluding model time.
- Oracle: tests/test_design_page.py: hostile fixtures (script, onerror, `url(http...)`,
  `@import`, `javascript:`, `foreignObject`) come out stripped and the Chromium network log is
  empty; a hand-written reference-style fixture measures to its expected boxes ± 1 px; text over
  a slot, overflow, missing/extra slots and small slots each give their error. FakeLLM tests
  cover repair, per-page fallback and page-1 fallback. Live: the user approves the real
  planner's pages against the reference image (STOP), and the Data Studio report shows each
  chart inside its card.

### Reference design brief
- Problem/objective (change 2026-10-25): separate visual reasoning from HTML coding while
  retaining native Data Studio charts. A detailed, feasible Argon brief tells Flash how to
  reproduce the reference's regions, proportions, hierarchy, typography, palette and art.
- Preconditions: existing current feasibility/preflight passes before generation. Accept uses
  the laid-out candidate spec; revision uses the checked candidate components and relevant
  resolved decisions. No new feasibility LLM call and no readiness bypass. Unsupported or
  unresolved requirements still block through the existing contract.
- Input: reference mode, user instructions, images in original order/MIME, summary and
  palette/type/spacing notes; current theme/title; page metadata, footer reservation; code-built
  approved-component report. That report contains assessment identity/state, component id,
  type, label, field/aggregation/grain/option metadata, minimum size, relevant requirement and
  observation bindings and accepted substitutions/drops, plus supported styling and bundled
  art/icon names. Use the real candidate and ledger, not only unresolved issues (a ready
  assessment's issue list is empty). No raw data rows, secrets, full catalog, observation boxes
  or copied screenshot values as factual data. Instructions/observations are framed as untrusted
  task data; they cannot override system/slot rules. No network tools.
- Output: an internal validated page brief: page index, overall visual instructions, and one
  treatment entry per accepted slot id. Exact id set, no duplicates/unknown/missing slots;
  aggregate prose <= 12,000 characters; no replacement component definitions, data, executable
  code or external assets. Text describes layout, not changes to data semantics. Brief is
  ephemeral run state, not a new public artifact or spec field; final HTML remains persisted.
- Modes: recreate matches the approved screenshot structure using native slots and explicit
  substitutions. Style borrows visual treatment around existing components and never imports
  charts/controls. Neither stage invents a slider, split bar, small multiple, legend/data marks
  or data-bearing map in background HTML to simulate an absent native component. Static
  vendored globe art is permitted decoration, not data binding. Other pages adapt the visual
  language to their own components rather than repeat page-1 charts.
- Ordering: brief for page 1 -> HTML for page 1 -> later-page brief/HTML pairs in parallel,
  sharing page 1's actual validated width/CSS. Revise regenerates a fresh brief for each affected
  page using current reference, candidate slots, previous sanitized HTML and comments, so
  removed/retyped slots and accepted decisions cannot be stale. No-reference route skips both
  new nodes; missing/corrupt required reference bytes fail the reference stage, never silently
  reduce the image set or select the generic designer. Artifact/feasibility freshness is rechecked
  at the existing publication boundary; no brief reuse across changed inputs.
- Budget: reference_brief uses the configured planner (normally Argon), LOW thinking, full
  counted input <= 12k including images and output <= 4k including thinking. One generation,
  no semantic repair; existing single transport retry on 429/500/503 only. A 120 s total stage
  bound includes counting and any retry; cancellation propagates. Validate raw output under
  existing secret guards before parsing. Failed, cut, invalid or over-budget brief follows
  #Reference HTML composition's failure policy (change 24.8: stop reference publication);
  it never reaches Flash. Mandatory inputs may not be dropped
  to fit. A repair to the HTML reuses the same valid brief.
- Oracle: fake-model tests prove report contents even with zero open issues, exact slot-set
  validation, mode semantics, image ordering/MIME on every page/revision, count-before-generation,
  conservative allowance and refusal when mandatory context exceeds the bound; no rows/secrets,
  no tools; malformed/cut brief prevents the worker call. No-reference request fingerprint unchanged.

### Reference HTML composition
- Problem/output: Flash implements the validated visual brief as the existing FirstPage/LaterPage
  JSON containing sanitized background HTML around the exact native component slots. The
  renderer/compiler stay deterministic; chart definitions, data and recipe ops remain code-owned.
- Input: validated brief, authoritative slot metadata, theme, bundled icon/art names, reference
  images/notes and instructions, shared width/CSS or previous HTML/comments. Count complete
  requests, including every repair. Use existing dashboard-design Reference rules, sanitizer,
  measurement, minimum sizes, text-fit, footer, coverage and publication guards. The brief never
  overrides these constraints. Strip scripts and network references as today; Chromium stays
  offline/JavaScript-disabled. No model search or asset downloads in this change.
- Routing: new reference_html node uses the configured worker (normally Flash 3.8); keep
  designer on the planner for no-reference builds. Page Design.model records the HTML model;
  per-stage spans record actual model, page, attempt, image count, duration, budget/refusal reason
  and existing token usage. Both stages contribute to the same trace/run.usage totals; no raw
  brief, HTML, image bytes or provider text in logs/spans. Model fallback is visible by actual
  model identity, never claimed as Argon if unavailable.
- Budget (change 24.8, user): initial input <= 12k; the one repair input <= 24k. Both use
  the existing conservative complete-request bound, including schema and ordered images.
  Only the internally selected second HTML attempt may use 24k; not the brief, first attempt,
  no-reference designer or another worker. Output <= 16k including LOW thinking on both
  attempts. Give the reference_html client
  a 600,000 ms timeout independent of planner/worker defaults. One 600 s wall-clock budget
  covers each page's entire HTML stage: token counting, generation, the existing transport
  retry and at most one validation/measurement repair. An outer cancellable deadline prevents
  retries/repair from multiplying the budget; do not start another attempt with an expired
  budget. Other workers remain 30 s; planner calls remain 120 s. Per-page brief + HTML therefore
  totals at most 720 s of stage time; page 1 then later pages can take up to two such waves,
  plus existing deterministic rendering/publication. This is bounded, not a speed guarantee.
- Repair context: remove duplicate representations before counting, not mandatory meaning.
  There is one authoritative page component projection with all ids/types/labels, minima,
  data bindings and accepted decisions; do not repeat that projection in page metadata. Keep
  the full validated brief, theme, reference mode/instructions/notes, ordered descriptors and
  image bytes, fixed width/shared CSS, and original revision comments. If a parsed failed HTML
  draft exists, include it once as the current page; it replaces the older revision HTML for
  this repair only. With no usable draft (empty, truncated or malformed output), retain the
  original revision HTML when present and the errors; never send an unbounded raw bad reply.
  First-page repair retains the proposed width or the schema's width-selection constraint.
  All error paths and measured size/collision guidance remain available to the one repair
  under the existing 20-error bound; sanitization and measurement run again afterwards.
  No new HTML minifier, automatic layout solver, dropped slots, lossy brief summary or
  additional model loop is required. A complete request still over its limit refuses before
  generation; no truncation of mandatory facts or weakening of the allowance.
- Failure (change 24.8, user): with designed pages enabled, any reference-page failure stops
  acceptance before publication. This includes missing/damaged reference, failed brief,
  over-budget input, timeout, model/JSON/measurement failure after the allowed repair, a
  requirements-bound page that would otherwise keep its kit, and assembled-spec validation.
  Do not publish any mixture of designed and fallback pages. Emit the existing run.finished
  error with a sanitized stage/page/reason (existing error codes/shapes); retain the Blueprint
  stage, prior published spec/view/artifacts and pending comments, clean the unpublished
  candidate and release ownership. A successful page is never published alone after a
  sibling fails. Revision failure keeps the old spec/artifacts and pending comments as today.
  No-reference fallback and the explicit designed_pages=False path stay unchanged.
  Input overflow and missing reference are failures, not silent truncations.
  Output truncation can use the one existing HTML repair at the same cap; a repeated cap hit
  is recorded for the live STOP, never silently raises the cap. No extra Argon retry loop.
- Diagnostics: per-attempt spans retain folded count, enforced bound, applicable input budget,
  billed usage, stage/page/attempt/model/duration, refusal reason and error count. Record only
  code-owned validation categories/counts in spans, not HTML, brief, text snippets or provider
  output. The live test may save sanitized failed drafts, measurement errors and screenshots
  as backend-local QA evidence after the existing secret guard; never add these to runtime
  logs or public artifacts. Diagnose the remaining measurement error before changing prompts;
  a larger input budget alone does not prove layout quality.
- Lifecycle: accept still responds 202; background work keeps build ownership until completion
  or cancellation. User disconnect from SSE does not cancel a run. Server shutdown cancels and
  drains tracked workflow tasks under the existing shutdown grace rather than waiting 600 s;
  propagate CancelledError, close model streams, clean unpublished candidates, retain previous
  published versions and release build ownership. Do not alter the engine's timeout controls.
- Oracle: tests use injectable shortened deadlines/fake clocks, not ten-minute sleeps: a worker
  that passes the old 30 s boundary succeeds within the new budget; retry/repair together cannot
  exceed it; cancellation/timeout preserve old publications, close generation and release locks.
  Routing tests pin designer/planner/ordinary-worker deadlines. A repair whose complete bound
  is between 12k and 24k generates once; initial input above 12k or repair above 24k never
  generates. Revision repair contains one current draft plus the original comments, not two
  HTML copies; all required facts/images survive compaction. A failed first/later reference
  page or assembled spec leaves publication bytes/version/view unchanged, releases ownership
  and cleans candidates; a second invalid measurement never publishes. No-reference requests,
  artifact bytes and fallback are unchanged. Existing text/slot/footer/security checks remain
  the oracle; no relaxed checks to pass a live screenshot.
- Live acceptance: backend-owned reproducible recreate fixture from the electricity reference,
  same synthetic data and explicit accepted substitutions; real configured planner/worker,
  dry engine. Save the reference/prototype side by side and redacted stage counts/models/times.
  No fallback; headline left, real-geography globe centre, native list card left, yearly chart
  bottom and right panels, with every supported chart/control represented by a real bound slot.
  Explain unsupported substitutions; never draw fake controls to satisfy appearance. Exercise
  a later page, a design revision, style mode and no-reference regression. The user approves
  fidelity at the STOP; passing tests alone cannot mark the live task done. Full engine/report
  integration remains the release part's responsibility.

### Revise
- Problem: comments -> the smallest spec change.
- Rules: the revise node returns an RFC 6902 JSON patch touching only paths under the commented
  ids (and neighbours it must move to avoid overlap); the patch is applied to a copy, validated
  (one repair turn), then saved as `spec_version + 1`; each comment and the resulting change are
  appended to `decisions.md`.
- Edge cases: a comment on a decoration patches the decoration within its kit's style keys
  (text, color, background, border_color) and is re-rendered into the background; a color request
  on a decoration is supported, never `invalid_request` (change 2026-10-21, release 2.2 P1); a
  removal comment deletes the component and records it in decisions.md; a request for a type outside the catalog or `DSS_ALLOWED_TYPES` is refused with an
  assistant message saying what Data Studio offers instead; conflicting comments on one id apply
  in order (last wins) and the message says so; an empty patch keeps `spec_version` and says
  "no change needed".
- Decoration accent changes use kits.accent_key(kind); one hex in a decoration comment's
  text/need/property normalizes to that style property. Supported removal comments record
  mapping_origins['remove'] plus removed_item and retire requirements bound only to the removed
  item. Keep the narrow parser and partial-binding recovery limitations in PRD Later; do not
  claim arbitrary deletion prose is understood.
- On a designed page, which comments regenerate the page instead of patching: #Designed pages
  (change 2026-10-22).
- Oracle: tests with FakeLLM patches: a patch touching an uncommented, non-neighbour id is
  rejected; each edge case above has a test.

### Recipe compiler
- Problem: spec -> recipe.jsonl valid against ../contracts/recipe.schema.json.
- Rules: header from build, version and `spec.datasource.table` (split into project, dataset,
  table); ops: `open_report`, `rename_page` (page 1's name; recipe 1.1, change 2026-10-22), `set_canvas`, `set_background_image` (`background_p1.png`), then components in reading order (y, then x) mapped by type
  (`date_range`/`dropdown` -> `add_control`, `text` -> `add_text`, `image` -> `add_image`, else
  `add_chart` with `chart_type` = type); per extra page `add_page`, `set_canvas`,
  `set_background_image` (its box stays the canvas size: x0 y0 w=canvas width h=page height);
  one `set_style` per chart with the theme palette, none for scorecards (no series swatch);
  then `save_report`,
  `get_link`. Boxes from Layout. Op ids `s001`... Deterministic: same spec -> byte-identical file.
- Date buckets (recipe 1.2, change 2026-10-23): a `time_series` whose `date_dimension` is a
  `DATE_TRUNC`/`DATETIME_TRUNC`/`TIMESTAMP_TRUNC` derived field of the view gets
  `options.date_granularity` = that field's grain (day, week, month, quarter, year), so Data
  Studio draws one point per bucket like the prototype; any other date dimension gets none. The
  grain comes from the code-built derivation (Blueprint derived fields / derived-fields.md),
  reaches the compiler through the spec (`compile_recipe(spec, version)` stays pure), and a
  `date_granularity` from model output is never trusted (code overwrites or drops it).
  Base DATE columns (change 2026-10-24, release 2.6 b_697880743b4f s008/s010: `year` DATE with
  every value YYYY-01-01 drew daily spikes): a `time_series` or `area` on a source DATE column
  whose data profile shows every value on a bucket start gets that grain, the coarsest that
  holds (year when all are Jan 1, quarter when all are a quarter's first day, month when all
  are a month's 1st); the profile is code-computed, recorded in the spec with the grain, and a
  column with any other value gets none.
- Recipe 1.3 types (change 2026-10-24): `area` -> `add_chart` `chart_type: area` with options
  `stacked`/`stacked_percent` and the date grain rule above; `bar` option `stacked_percent`;
  `fixed_size_list` -> `add_control` `control_type: fixed_size_list` with `field`. Catalog
  entries (knowledge/catalog/), registry records citing ../contracts/recipe.md, the default
  `DSS_ALLOWED_TYPES` (../contracts/conventions.md 1.3), the prototype renderer and the
  blueprint skill all list them; the compiler emits them only for specs that use them, so older
  specs compile byte-identically.
  Every `set_canvas` takes `spec.canvas.width` (1200-1920 on designed builds) and the page
  height, so the report's canvas matches the designed background (change 2026-10-22).
- Oracle: every line validates against the schema; golden spec -> golden recipe file; ids sequential.
- All accepted Theme colors must meet the recipe's #RRGGBB constraint, including palette items;
  invalid model colors are rejected into the existing bounded spec repair before publication.
  The compiler/recipe endpoint must not publish a contract-invalid recipe from a legacy or
  corrupted saved spec. Preserve the last complete recipe/stage on rejection. Verify live
  model-produced recipes against the shared schema, then execute them with the real engine's
  dry-run; fixture-only golden validation is insufficient release evidence.

## External APIs and services
| Service | Used for | Auth | Limits and failure handling |
|---|---|---|---|
| Gemini API (`gemini-4-argon`, `gemini-3.8-flash`) | LLM nodes | `GOOGLE_API_KEY` | per-call timeout (sent to Google, which enforces it as a 504): planner (blueprint) 120 s, worker 30 s; errors -> `llm_unavailable`; one retry on 429/500/503, none on 504 (task 11.9) |
| BigQuery | loads, profile, view, aggregates | ADC (`gcloud auth application-default login`) | errors surfaced with BigQuery's message |
| GCS | CSV source URIs (read by BigQuery load jobs) | ADC | bad URI -> `422 invalid_source` |
| Google Search (ADK tool) | research discovery (stretch) | API key | one model call; provider-internal fetches opaque |
| Python table scraper (stdlib) | research CSV/HTML retrieval | none | 20 HTTP requests per run, redirects/failures included; no retries |
| dsengine (subprocess) | building the report | none | exit codes per ../contracts/recipe.md |
| Cloud Run | hosting (one instance) | runtime service account (BigQuery Data Editor + Job User) is the ADC there | restart -> running agent job fails with `agent_timeout`; DB restored from the volume |
| Secret Manager | `GOOGLE_API_KEY`, `DSS_ACCESS_CODE`, `DSS_AGENT_TOKEN` as env vars | Cloud Run (runtime SA: Secret Accessor) | too short or missing code/token -> the backend refuses to start on Cloud Run |
| GCS volume (`/data`) | state files and the DB backup | Cloud Run gen2 (runtime SA: Storage Object User) | no file locking: the live DB stays on local disk; up to 30 s of writes lost on a crash |

Research budget refinement (task 7.3, approved by user 2026-10-19): discovery uses one
Google Search model call. Code retrieves public CSV/HTML tables within the separate
20-request cap. A second model call selects a table from title, URL, headers and row counts;
scraped rows stay out of model context. Code normalizes headers/whitespace, removes exact
duplicate rows and repeated headers, and writes the CSV and sources.md before existing
intake registers a research source. Provenance records discovery citations and every
attempted HTTP URL, including redirects and failures. The reusable Python scraper command
shares the same limits and parser; it does not execute JavaScript or invent missing data.
## Dependencies
fastapi/uvicorn (API), sse-starlette (SSE), python-multipart (uploads), google-adk (graph,
agents, tools), google-genai (Gemini client, token counts), google-cloud-bigquery (data),
python-dotenv (env), pydantic (models), pyyaml (OKF frontmatter), jsonpatch (RFC 6902 patches), jsonschema (contract test),
playwright (background screenshot), httpx (TestClient and the `dss-agent` HTTP client, so a
runtime dependency), pytest + pytest-asyncio (tests). Vendored data: lucide-static icons (ISC); Natural Earth 110m
Admin 0 countries (public domain, v5.1.2) as the source of the generated `render/art/` SVGs (change
2026-10-24; the GeoJSON is read by the generator script only, never at runtime).

## Implementation conventions
- Use callable ADK instructions for assembled user context; braces in string instructions are
  state templates. Identify Workflow function nodes via `node_info.path` when author is the workflow.
- Structured output uses `response_json_schema`, not converted `response_schema`. Keep strict
  Pydantic validation locally; strip only demonstrated unsupported provider bounds (worker
  nested `maxItems`). Guard raw output before ADK output-schema validation can log inputs;
  sanitize provider exceptions in `on_model_error_callback`. Apply to plan/repair as well as
  spec/revise/audit/style/consolidation/judge.
- Timeout/cancellation owns the engine process tree until terminated and reaped, including
  wrappers whose descendants hold stdout open. Keep backend cwd explicit.
- Revision stages spec, prototype, background and cache, publishes with rollback, and preserves
  aggregate SQL hashes for layout-only changes. Canonical no-ops keep `spec_version`; supply
  rendered defaults (title 28px) in context. New versions reuse the view and copy render
  inputs/docs, omitting recipe, events and engine screenshots.
- Secrets use SecretStr and an allowlisted public settings response. Agent mode ignores saved
  deployment overrides except models. Backups track committed-write generations, serialize
  copies/rename, and use daemon I/O with a shared 3 s shutdown deadline.
- GCP configuration needs a project ID, not its display name; verify syntax/access before live
  paid runs. Never repair the root .env from a backend build task.
- Recipe JSONL uses UTF-8, LF and ensure_ascii=False. Split on LF only: U+2028/U+0085 can occur
  inside a JSON string. Compiler preview rejects top-level boolean arguments; nested style
  booleans work. Run refreshes canonical recipe bytes from spec.json before execution.
- Knowledge index links target Markdown files or folders; mention machine-readable JSON in a
  code span because Navigator.list_folder parses every linked file as a concept.
- Capability field bindings use bq_type, snake_names and date_like projection, not the API's
  display type. Recipe 1.0 has no unit/grain chart options: keep units in the ledger and express
  explicit date grain through SQL view bucket fields.
- Pending-comment staleness comes from pending_comments alone, separate from prototype_stale,
  so abandoning a batch clears only its own reason. comment_batch history is not re-extracted;
  the ledger owns that intent. Preserve supersession chains for later property assignments.
- Candidate.begin snapshots rollback stage before setting stage=plan, including deferred plan
  initialization after extraction. Keep volume ownership/commit records when removing rollback
  artifacts: SQLite backups can lag them. Retain candidate ownership until the deterministic
  BigQuery job is terminal; result(timeout=...) can leave it running. Never clean a published view.
- Structured model nodes ignore partial streamed fragments and validate only the accumulated
  final response (change 2026-10-21: the interview sentence rules no longer apply).
- Synthetic generator version dss-synthetic/1 seeds independent column streams from the canonical
  seed/name/index/version, uses Decimal ticks and half-away-from-zero product rounding, and
  publishes completed files without replacing existing output. Generation keys own deterministic
  load jobs; unresolved cleanup retains ownership and retry_ready=false, including after restart.
- Synthetic provenance is source-owned, including joined sources. Reserve a 64px footer for
  p1_synthetic_sample_data; restore it on legacy reads, revisions and copied versions before
  publishing artifacts. Neither model patches nor reference images may hide or replace it.
- Theme colors revalidate locally, including mutated/legacy specs; cache recipe-schema validators
  and validate compiled headers/ops before publication. Ship `contracts/recipe.schema.json`
  beside backend at runtime; the compiler loads that shared contract without an engine install.
- On Windows, assign each agent engine to an owned Job Object before resuming it, so wrapper
  exit cannot orphan descendants. Retry expiry shares a 0.4 s cleanup allowance across HTTP
  close, process reaping, pipe/reader shutdown and the main loop; keep the 0.5 s test tolerance.
- Decoration text uses shared CSS and cached Chromium measurements of content/style/geometry
  in a worker thread. Titles/subtitles have zero padding and line-height 1.25; a default 28px
  title needs three grid rows. Reject insufficient boxes into existing repair; never enlarge
  them automatically. Prototype/background retain identical wrapping/fonts and footer protection.
- Context recipes have tested section order and shapes. Append node guidance inside existing
  system sections instead of adding sections that change working-memory tracing contracts.
- The requirements.json section is mandatory in revise's 6k budget; do not repeat source text
  per row. Cache requirement regexes and read the catalog once per feasibility pass
  (`validate.catalog()` re-parses its YAML, ~25 ms) to preserve the 100 ms recompute oracle. Extraction
  normalization accepts only provably redundant bindings, not fabricated capability evidence.
- Typed synthetic CSV loads use an empty null_marker so a single-column all-null csv.writer
  record (`""`) remains NULL and still counts as a row (live-checked task 12.2).

## Testing
pytest, offline by default: FakeLLM (scripted responses by node), FakeBigQuery (in-memory rows
from a CSV), fake engine (a script that prints ../contracts/fixtures/events.sample.jsonl).
Live tests marked `live` (excluded by default). Test (all) = `uv run pytest`.
- Fixtures needing `app.state.db/settings/harness` request `client` or `build_id` to run lifespan.
  Cwd tests must start outside backend. Encode dot-dot as `%2e%2e` for path-boundary tests; use
  byte headers for non-ASCII credentials under httpx.
- Fixture recipes use newline="\n"; Windows CRLF is non-canonical and triggers recompilation.
  tests/live/__init__.py isolates live/offline module basenames. API shape helpers compare every
  list item with the first fixture item; heterogeneous lists need exact comparisons.
- Final-audit evidence: `.blueprint/qa/final-audit/` (ignored). Prototype screenshots use the spec
  canvas (default 1200x900); frontend QA belongs to its part. A fixture render after a failed live
  plan proves render/build behavior only.

## Decision log
| Date | Decision | Alternatives | Why | Source |
|---|---|---|---|---|
| 2026-10-18 | Spec JSON is the single source of truth; grid layout; deterministic HTML/recipe | LLM writes pixels/HTML/recipe | tokens, no overlaps, small patches | program |
| 2026-10-18 | One view per version holds joins and derived fields | Data Studio calculated fields | engine never builds fields in the UI | program |
| 2026-10-18 | No vector store; OKF + FTS5 | harness doc's vector stores | user constraint | program |
| 2026-10-18 | One interview LLM turn per request | long-lived human-input node | stateless REST | plan |
| 2026-10-18 | Threads for engine subprocess and Playwright; no `--reload` | asyncio subprocess, async Playwright | Windows event loop limits | audit |
| 2026-10-18 | One-page specs; `DSS_ALLOWED_TYPES` gate; no `events_fts` | multi-page; all types always | deadline; fallback if engine ops slip | audit |
| 2026-10-18 | Thin slice task 1.3 first; context assembler and consolidation after the build path | memory first | critical path to integration | audit |
| 2026-10-19 | Cloud mode in this part: static frontend, `$PORT`, access code, DB on local disk with a backup-API copy to `/data` | SQLite on gcsfuse; Firestore | one code path for local and Cloud Run; gcsfuse has no locking | change 2026-10-19 |
| 2026-10-19 | Delta audit: backup every 30 s when dirty via /tmp, graceful shutdown <= 3 s, fail-closed start, separate agent token, settings lock, path guards, report_url host check, agent split 5.2/5.3, 5.1 right after 1.3 | backup only after builds; access code for the agent | restarts and redeploys lost unbuilt work; a code holder could steal jobs or swap the API key | change 2026-10-19 (audit) |
| 2026-10-19 | `run.usage` emitted from the one place graph.py sums tokens; consolidate/eval runs (no build stream) emit none | a usage field on `run.finished` only | the UI shows tokens climbing during the run; one emit site | change 2026-10-19 |
| 2026-10-19 | Build agent `dss-agent` lives in backend and reuses the execute node's event handling; in-memory job queue | agent in engine; Pub/Sub queue | one part owns both sides of the agent endpoints; one instance needs no external queue | change 2026-10-19 |
| 2026-10-19 | Fold task decisions into implementation conventions; preserve concurrent consolidation completions | reset all counters; direct artifact publication | retain verified concurrency, redaction, staging and cache behavior | tasks 1.1-7.3; final audit |
| 2026-10-19 | Correct schema transport, engine-free preview, current-spec execution, sort parity and flat agent assets | accept isolated test passes as release evidence | live plan and cross-node checks failed despite 350 passing tests | final audit; tasks 9.1-9.5 |
| 2026-10-19 | Enforce live token counts and whole-attempt retry deadline | waive original budgets for POC | explicit requirements; CJK estimate and retry loop violate them | final audit; tasks 9.6-9.7 |
| 2026-10-19 | Closest supported recreation and evidence-backed feasibility required; explicit user substitutions, private versioned references | style-only; prompt-only capability checks; runtime web search | user scope decision and five-gap plan audit | change reference/capability 2026-10-19 |
| 2026-10-19 | Synthetic schema/count/seed API and reusable Python generator; local folder or existing mounted GCS state | require user CSV; LLM emits rows; new storage service | user requested screenshot-only recreation with fake CSV generation | change synthetic-data 2026-10-19 |
| 2026-10-20 | Plan delta audit: extraction inside the action's trace; app evidence from contracts; header-first image checks; explicit CSV null marker; 11.3/11.5/12.2 split | separate extraction run; manual engine review | one trace per action; engine files are another part's; reviewer findings | audit 2026-10-20 |
| 2026-10-20 | Synthetic durability: generation table plus immediate best-effort DB backups after reservation and registration; startup fails in-flight jobs and cleans their own artifacts (synthetic-data.md 1.1) | immutable manifests + startup reconciliation; fail-closed 503 on backup failure | same POC guarantee on the existing backup path, no new files or error code | change 2026-10-20 (program root, user choice) |
| 2026-10-20 | Gemini per-call timeout: planner 120 s, worker 30 s; one retry on 429/500/503, none on 504 | one 30 s timeout for all calls; 120 s for all | the fixed 30 s timeout cut off slow spec calls with a 504 (`llm_unavailable`) and blocked 11.8; a retry after our own deadline would just wait again | change 2026-10-20 (blocked 11.8, user choice) |
| 2026-10-20 | Fold durable implementation and test rules from tasks 9-12 into conventions | leave them in every session's gotchas | keep canonical recipes, intent provenance, staged publication and synthetic recovery explicit | final re-audit |
| 2026-10-20 | Keep fixes 13.1-13.3; defer former 13.4-13.8 to PRD Later and mark their design paragraphs as deferred | another five build sessions and re-audit | user-approved POC severity triage; no silent claim that deferred invariants are implemented | change triage phase 13 |
| 2026-10-20 | Shared-schema recipe validation, Windows Job ownership/0.4 s cleanup, shared cached text fitting and existing context-section ordering | repeated schema loading, wrapper-only cleanup, enlarged heading boxes or changed context recipes | retain completed task decisions and unchanged repair/deadline limits | tasks 13.1-13.3; final re-audit |
| 2026-10-21 | Preserve audience context and continue interview clarification while feasibility blocks readiness and side effects | rewrite release answers to evade the gate; suspend feasibility until a fixed answer count | release 2.2 demonstrated a core-flow failure; the interviewer must be able to collect missing definitions | change interview feasibility recovery (program root) |
| 2026-10-21 | Recognize coordinated explicit formulas, reuse confirmed metric definitions with provenance, and normalize ordinary blue styling to evidenced capabilities | rewrite the integration fixture into isolated sentences and hex-only style requests; automatically drop unresolved rows | release 2.2 still fails after 14.1; persisted evidence shows parser boundaries, missing forward definition reuse and unclassified styling | change conversational definitions and styling (program root) |
| 2026-10-21 | Staged workflow: context, outline, design and blueprint artifacts replace the interview, plan and spec nodes; code profiles, validates, lays out and writes files; models see compact profiles and upstream artifacts only | keep the interview and patch extraction; keep both paths | per-message extraction was the repeated failure; structured picks need none; checkpoints rerun alone; smaller cacheable prompts | change staged workflow (program decision log) |
| 2026-10-21 | Spec laid out by code from blueprint + design, 1-5 pages; ratio KPIs and unjoinable sources become feasibility issues with code-built alternatives | spec model node; Data Studio calculated fields | determinism and no extra model call; calculated fields stay a non-goal | change staged workflow |
| 2026-10-21 | Fold staged artifact, aggregate-profile, raw-expression, dry-run-schema, layout, background and revision decisions into conventions | leave them only in task logs | preserve tasks 15.1-15.11 decisions for future sessions | final re-audit |
| 2026-10-21 | Record the user-approved outline_other fail-open behavior as a POC limitation and contract gap | claim complete original-behavior preservation | task 15.11 explicitly approved empty extraction and skipped clarification/coverage; contracts remain root-owned | task 15.11; final re-audit |
| 2026-10-22 | Recover freshness only with validated candidate publication; reconcile recreate observations with active user instructions and confirmed Context KPI definitions | clear staleness on check; accept dropped image observations | user chose both release 2.5 blocker fixes; preserve acceptance and existing contracts | change reference recovery (program root) |
| 2026-10-22 | Backgrounds captured at device scale 2 with the recipe box unchanged; page 1 named by `rename_page`; no palette `set_style` for scorecards | SVG or higher-res upload per component; accept "Untitled Page" | user flagged soft backgrounds and the engine skips scorecard palettes; recipe 1.1 adds the op | change report quality (program root) |
| 2026-10-22 | Backgrounds at device scale 3 (each PNG < 2 MB, no minimum size); feasibility rejects colors on scorecards as unsupported_app | keep 2x; per-page scale to an exact 1920 x 1080; pad files to 200 KB; leave scorecard color comments pending | user target >= 1920 x 1080 (2x page 1 is 1064 tall); bytes don't add sharpness; renderer, compiler and engine must agree on scorecard colors | change backgrounds 3x and scorecard colors |
| 2026-10-22 | Designed pages: the planner writes each page's background HTML around measured component slots; code sanitizes, measures, screenshots and falls back to the kit per page; width 1200-1920 via `set_canvas`; page regenerated on geometry/heading comments; vendored Lucide icons | design JSON rendered by an upgraded code kit; AI grid + code-drawn cards; code-only revise moves; a 1920 canvas for every build; native Data Studio text for headings | user wants AI-designed backgrounds and layouts with native charts placed in them (reference image); recipe 1.1 already has `set_canvas`; measured slots keep charts inside their cards | change designed backgrounds (user, after 19.3) |
| 2026-10-23 | Recreate publish failures are diagnosed from the `publish` span's coverage errors; a designed page that breaks coverage falls back to the code layout | expose errors in the API (contract change); accept recreate unproven live | release 2.5 recreate/synthetic accepts fail coverage with no visible errors; user chose a backend fix over a limit | change recreate publication (program root) |
| 2026-10-23 | Designer prompt asks for canvas width 1200 (schema still 1200-1920) | 1440-1920 designed canvases; block wide designs | the Data Studio editor zooms canvases wider than ~1380 px and the engine misplaces every component (20.5); user chose the prompt | task 20.5 |
| 2026-10-23 | Recreate accept titles observed charts in code; the Designed-pages coverage fallback stays specified but unbuilt | build the fallback; send observations to a model again | 21.1 replays: failures came from titles, SQL text and stale ids, not designs | task 21.1 |
| 2026-10-23 | Blueprint feasibility checks rows against recreate observations, and the planner sees them | leave the gap to publish coverage; Later list | feasibility said ready while accept failed with no recovery (b_48ef72ff1bff, b_dfb67c24f176); PRD goal 6 gate at blueprint | final audit 2026-10-23 (user) |
| 2026-10-23 | Time series on a date bucket carry recipe 1.2 `date_granularity` from the code-built derivation | cast buckets to text; engine infers from names; bar/table bucket axes too | Data Studio reads a DATE_TRUNC bucket as a daily DATE: spikes on the 1st, zeros between (release 2.5, b_36f20b42159c s015); bar/table bucket labels stay readable (first day) | change live report defects (program root) |
| 2026-10-23 | The synthetic label is drawn once, by the background; the compiler places no label text | keep the native text and hide the label in the background (synthetic-data.md change); align both copies | synthetic-data.md 1.2 puts the final label in the background pipeline; two renderers never align (b_91869163c217 page 1 drew it twice) | change live report defects (program root) |
| 2026-10-24 | The designer gets the reference images and a Reference section in its skill; the reference wins over the generic look | keep the text-only style profile; move reference_extract to the planner; let the designer write free HTML with scripts | the planner designed blind (title, theme, slot ids only) and the skill forced a light KPI-row page; release 2.6's screenshot came out as a generic page with a blob globe, while Argon shown the image recreated it | change reference fidelity (program root, user choice) |
| 2026-10-24 | Vendored static art (`data-art`: globes, world map from Natural Earth 110m, public domain) inlined by code | the model writes world paths (~30k tokens, over the 16k cap); network topojson + d3 (scripts and network are stripped); a crop of the screenshot (never the screenshot as background) | a static globe with real geography at the cost of one tag; CSS classes give a choropleth look | change reference fidelity (program root, user choice) |
| 2026-10-24 | Capability check 24k input / 8k output, comment batches send only bound + unbound ledger rows, only active issues count toward 20, the refusal names its limit | raise the budget only; a user-set cap with a warning (declined on the card) | release 2.6's comment requests grew 6.9k -> 12.7k and one output used 3,839 of 4,000, so "enlarge the globe" hit the scope refusal | change reference fidelity (program root, user choice) |
| 2026-10-24 | Recipe 1.3 `area`, `fixed_size_list`, `stacked_percent`; base DATE columns on bucket starts get a grain from the data profile | slider control (number fields only; year is a DATE); per-chart filters and single-bar highlight (Later) | release 2.6's change requests: Data Studio has these natively, and a yearly DATE column drew daily spikes (b_697880743b4f s008/s010) | change reference fidelity (program root, user choice) |
| 2026-10-25 | Reference builds: current feasibility + native candidate slots -> Argon visual brief -> Flash sanitized HTML, both with images; no-reference designer unchanged | one-stage Argon HTML; arbitrary scripted chart clone; changing style mode to import charts | user retains native Data Studio charts; the blocked style experiment lacked slots and a second model alone cannot create them | change 24.5 (user) |
| 2026-10-25 | Reference HTML gets 600 s per page including counting/retry/repair; brief 120 s; retain 12k inputs and 16k HTML output, new 4k brief output | 30 s worker default; 120 s HTML; unlimited wait or cap increase | user permits over five minutes and reports Flash 3.8 HTML in about three minutes; finite 600 s bound is a documented default; shutdown must cancel long work | change 24.5 (user timing permission, default bound) |
| 2026-10-25 | Use supplied reference and bundled assets; no new web research, dependencies or contract changes | add bounded internet research; runtime external assets | user selected bundled assets first; existing sanitized background and native-chart rules remain | change 24.5 (user) |
| 2026-10-25 | Recreate observation completion: definition-only instructions are evidence, not rows; `Label = field`, `using <date field>`, `chart <type>`, multi-metric substitution; scorecards skip the grain check; code adds a page-1 row for a fully determined unfulfilled observation | alternative the user picks for the added row; drop policy inside the test; keep the extracted dropdown | 24.7 blocked at 21 issues on the electricity fixture; the user chose the code-added row, the `chart` clause and one urban/rural area for the per-country small multiples; geo_map, legend and slider drops approved for that fixture | change 24.7 (user) |
| 2026-10-25 | Compact duplicate reference repair input; 12k initial / 24k repair input, unchanged conservative count allowance, 16k output and 600 s/one repair; reference design failure prevents publication and preserves prior artifacts | keep every request at 12k; publish the standard kit after reference failure; keep retrying live | 24.8 evidence: repair bound 14,117 exceeded 12k; another repair retained one measurement error. User chose the 24k repair limit and stopping failed reference builds. Native-slot validation and visual acceptance stay mandatory | change 24.8 (user answers in architect session) |
| 2026-10-26 | Reconstruct recreate yearly dates onto the projected base DATE with active full-column proof plus explicit field/grain intent or a selected native date-axis use of a complete recognized truncation; undeclared aliases need explicit intent; share completion/ingress rules and give exact missing-KPI feedback | infer aliases/observations from names or metrics; simplify arbitrary SQL; repeat live until ready; waive q4's missing KPI | 24.9 failed twice before design: mismatched year aliases/invalid DATE arithmetic, including overall series without observation links, plus an independent missing confirmed q4 measure. Retain typed SQL, KPI and coverage gates | change 24.9 (architect ruling; implementation 24.9, live/visual verification 24.10) |
