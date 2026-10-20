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
| Rendering | string templates + ECharts (CDN) in the HTML; Playwright Chromium for background.png | deterministic, no LLM | LLM-written HTML |
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
                          session.py (access code), agent.py (agent endpoints)
    agent/                jobs.py (job queue, heartbeat, timeouts), client.py (`dss-agent` CLI)
    harness/
      graph.py            the ADK Workflow: action router + nodes + edges
      nodes/              intake, interview, plan, view, spec, validate, render, revise, compile,
                          execute, publish, ux_audit, style_extract, research, consolidate
      context.py          working memory assembly (per-node context recipes, budgets)
      llm.py              model routing (planner / worker), token accounting
      guardrails.py       loop limits and output checks at every loop exit
      tracing.py          one trace per run (spans per node)
    memory/
      procedural.py       skill loader (skills/*.md)
      semantic.py         OKF navigator over knowledge/ and data/knowledge/
      episodic.py         messages, events, FTS5 retrieval
    data/bigquery.py      intake loads, profiling, view creation, aggregate queries
    spec/                 models.py, validate.py, layout.py, patch.py
    render/               prototype.py, background.py
    recipe/compiler.py    spec -> recipe.jsonl (../contracts/recipe.md)
  skills/                 procedural memory: interview.md, archetype-*.md (4), plan.md, spec.md,
                          revise.md, ux-audit.md, style-extract.md, research.md
  knowledge/              semantic memory seed (OKF): index.md, log.md, catalog/ (12 types),
                          archetypes/ (4), datastudio/ (product limits)
  prompts/v1/             system prompts per node: the versioned release artifact
  tests/                  offline tests with FakeLLM, FakeBigQuery, fake engine
```

## Data model
SQLite `data/dss.sqlite`:
- `builds(id, title, archetype, mode, stage, current_version, created_at, updated_at)`
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
- **interview_turn**: user message saved -> interview node (worker, skills: interview +
  archetype-<x>) -> reply streamed as `message.delta`/`message.done`. When the interview has
  enough, the agent calls its tool `mark_ready_for_plan()` (never a text marker), which sets
  `ready_for_plan` and emits `build.updated`.
- **intake**: CSV upload -> column names to snake_case (dedupe with `_2`), UTF-8 with latin-1
  fallback, reject over 100 MB or zero rows (`422 invalid_source`, `detail.reason`) -> BigQuery
  load job with autodetect into `src_<build_id>_<file slug>` -> profile (type, null %, distinct
  count, min/max, 3 samples; STRING columns whose samples parse as dates are flagged
  `date_like`) -> `data-profile.md`. GCS: load job from the `gs://` URI, same rules. BigQuery:
  profile in place, no copy.
- **plan**: feasibility preflight -> plan docs staged -> SQL dry run (one repair) -> new
  run-specific candidate view -> spec -> validation/repair (<=2) -> staged render/background ->
  atomic publish of spec/artifacts with the candidate table identity -> prototype. Failure
  cleans only the candidate and leaves prior docs/spec/view intact (Capability verification).
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
  invalid after repairs -> `run.finished(error)` listing the validation errors, stage back to
  `interview`; engine exit 3 -> `build.finished(failed)` + `engine_not_signed_in`; missing
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

### Graph
- Problem: one ADK 2.0 `Workflow` that is the harness's agent run for every action.
- Model check: at startup and when settings change, list the available models; if the planner
  model is missing, log a warning and use the worker model for plan and spec.
- Inputs and outputs: `{action, build_id, payload}` -> SSE events, DB writes, one trace.
- Rules: START -> router(action) -> the action's branch (Key flows). LLM nodes: interview, plan,
  spec, revise, ux_audit, style_extract, research, consolidate, reference_extract,
  capability_check, synthetic_schema. Code nodes: intake, view (SQL build + dry run), validate,
  render, compile, execute, publish, synthetic_generate. Requirement extraction is a node inside
  the triggering action's Workflow (interview, plan, revise, reference, feasibility check), never
  a second run: one action, one trace, its tokens in that trace (audit 2026-10-20). The validate -> spec (or revise)
  edge is the only loop, conditional, at most 2 passes. Every branch ends at a guardrail node.
- Edge cases: unknown action -> error, no LLM call; concurrent actions on one build -> the second
  gets `409 wrong_stage`.
- Approach: builder's choice within ADK 2.0 (`Workflow(edges=[...])`, router nodes, function
  nodes, `LlmAgent` nodes); see https://adk.dev/2.0/ and https://adk.dev/graphs/routes/index.md.
- Oracle: tests run each branch with FakeLLM and assert the node order recorded in the trace spans.

### Working memory assembly
- Problem: give each LLM node only what it needs, in a cache-friendly order, under a token budget.
- Inputs and outputs: node name, build, user input -> ordered list of context sections + the
  token count per section (recorded in the trace span).
- Rules: order = system prompt (`prompts/v1/<node>.md`) -> skills -> semantic concepts -> data
  profile -> build docs / spec subset -> episodic (past builds) -> current chat history -> user
  input; stable sections first so Gemini's implicit prefix caching can hit. Per-node recipe:

  | node | skills | semantic | other |
  |---|---|---|---|
  | interview | interview, archetype-<x> | archetypes/<x>.md, catalog/index.md | data profile, last 12 messages, FTS top 3 past |
  | plan | plan, archetype-<x> | archetypes/<x>.md, catalog/index.md, user facts | data profile, full interview transcript |
  | spec | spec | catalog/<types named in kpis/questions>.md, archetypes/<x>.md | build docs, field list |
  | revise | revise | catalog/<types of targeted components>.md | targeted components + their grid neighbours only |
  | ux_audit | ux-audit | archetypes/<x>.md | spec summary (ids, types, boxes) |
- Budgets (input tokens): interview 8k, plan 20k, spec 16k, revise 6k, ux_audit 10k. Over budget
  -> drop FTS past results, then the oldest messages, then semantic concepts beyond the first;
  never drop the system prompt, skills or user input. Count with the API's token counter or
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
  (worker model) reads those builds' interview summaries and decisions plus `data/knowledge/user/
  index.md`, and writes OKF concepts (`type: User Preference` or `Design Decision`) under
  `data/knowledge/user/`, updates `index.md`, prepends to `log.md`; then `chats_since = 0`. A
  changed fact keeps the old value under "Previously" with its date. Runs after the build's
  response, never blocking it.
- Count each successful/partial `build.finished` under the snapshot lock; consume only the
  count included in a successful snapshot, preserving builds completed while it ran. Inputs
  are brief/design/decisions, at most 3000 characters each, newest first; skip missing docs.
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
- Input: user text, current requirements/decisions, reference interpretation, schema/definitions,
  candidate spec and effective registry. Output: requirements.json plus Assessment/feasibility.md.
  Internal requirement: id, source reference (message/comment/image item), text, capability ids,
  proposed fields/unit/aggregation/grain, resolution and component bindings. Preserve provenance.
- Extract with at most one worker generation per incoming message/comment batch/reference change,
  as a node in that action's Workflow and trace (Graph);
  input <=12k full counted tokens, output <=4k, max 40 requirements, max 20 issues/alternatives
  total. Use full existing request guard; no unbounded retries, repairs or live searches. If limits
  are exceeded, request a smaller scope and remain blocked. Deterministic recomputation performs
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
  Keep source provenance authoritative when validating model output or old copied specs.
- Budgets/oracle are contract sections Generator request/Acceptance oracle; offline generator
  tests cover deterministic bytes and relationships, API tests fake model/BQ/storage; one live
  screenshot-only path validates schema proposal, typed load and the final report label.
- Deferred hardening (change 2026-10-20; PRD Later, former 13.6): validate numeric magnitude
  before float conversion. Arbitrarily large JSON integers in
  decimal bounds, choice/lookup values or dependencies produce field-specific SyntheticError,
  HTTP 422 and a clean nonzero CLI exit, never OverflowError/500/traceback or a partial CSV.

### Plan publication
- Ownership: nodes/plan.py, view.py, render.py and data/bigquery.py stage docs,
  candidate view and rendered files. Persist candidate run ownership before creation; on failed
  attempt/restart clean only abandoned candidate views, never published/legacy view identities.
  Keep previous artifacts until new files/spec/table pointer are committed under the build lock.
  No schema migration of old view names: accept existing table identities, use unique names only
  for new attempts. This is superseding behavior for old create-or-replace SQL golden tests.

### Build docs
- Problem: the plan node's output, the durable design brief (OKF bundle per version).
- Rules: `data/builds/<id>/v<n>/docs/` holds `index.md`, `log.md`, `data-profile.md`
  (`type: BigQuery Table`, written by intake code), `brief.md` (`Dashboard Brief`),
  `questions.md` (`Business Questions`: q1..qn with priority), `kpis.md` (`KPI Definitions`),
  `derived-fields.md` (`Derived Fields`, frontmatter `fields: [{name, sql, type}]`, `joins:
  [{table, on}]`), `design.md` (`Design Direction`), optional `style.md` (`Style Profile`),
  `decisions.md` (`Design Decisions`, appended by revise). Every file has OKF frontmatter.
- Oracle: test asserts every doc parses and has its `type`.

### BigQuery view
- Problem: one active view per accepted spec holds joins and derived fields; old report views
  remain stable. New plan attempts create a distinct candidate (change 2026-10-19).
- Rules: new attempts use `CREATE VIEW <project>.<BQ_DATASET>.dash_<build_id>_v<n>_<run_id> AS SELECT <base
  columns>, <expr> AS <name> ... FROM <base> [LEFT JOIN ...]`, built from `derived-fields.md`
  frontmatter by code; every identifier backtick-quoted (reserved words such as `date`, `order`,
  `group` must work); field names snake_case and unique; `date_like` STRING columns exposed as
  `SAFE.PARSE_DATE` (or `SAFE_CAST` to TIMESTAMP) under the same name; dry run first; on dry-run
  error, one plan-node repair turn with the error text, then fail. A new version (`POST
  /versions`) reuses the latest view (the spec's `datasource.table`) unless re-planned.
- Oracle: unit tests on the generated SQL strings (golden strings); live manual check.

### Dashboard Spec
- Problem: the single source of truth the LLM writes and code renders and compiles.
- Inputs and outputs: pydantic model, saved as `spec.json`:
  `{spec_version, build_id, title, archetype, canvas{width:1200,height}, grid{columns:12,
  row_height:20, gutter:16, margin:24}, theme{background, surface, text, muted, accent,
  palette[], font_family, radius}, datasource{table, fields[{name, type, label, role, default_agg}]},
  pages[{index, name, height, decorations[], components[]}]}`. POC: exactly one page.
  Decoration: `{id, kind: band|panel|title|subtitle|text|logo|divider, grid{col,row,w,h}, text?, style?}`.
  Component: `{id, type, label, grid{col,row,w,h}, dimensions[], metrics[{field,agg}],
  date_dimension?, breakdown?, sort?, options?, text?, image_path?, field?, question_ref?}`,
  `type` in the 12 catalog types: scorecard, time_series, bar, pie, table, pivot_table, geo_map,
  scatter, text, image, date_range, dropdown.
- Rules (validator): exactly one page; ids unique and snake_case with page prefix; types in the
  catalog and in `DSS_ALLOWED_TYPES` (the spec node's prompt lists only the allowed types); fields
  exist in `datasource.fields` with a role the catalog slot allows; dimension/metric counts within
  the type's catalog limits (`knowledge/catalog/<type>.md` frontmatter: `min_dimensions`,
  `max_dimensions`, `min_metrics`, `max_metrics`, `requires_date_dimension`, `min_w`, `min_h`);
  grid inside 12 columns and the page height; no two components overlap (decorations may sit
  under components); every question in `questions.md` with priority high is referenced by at
  least one component's `question_ref`. Errors are a list of `{path, message}` fed to the repair turn.
- Sort is a validated `{field, order: asc|desc}` object, matching the recipe contract. Renderer
  SQL and compiler consume that same shape; unknown keys or orders fail before publication.
  An explicitly ascending bar/table must render ascending as it will in Data Studio.
- Oracle: property tests on random valid/invalid specs (fixed seed) + golden invalid cases.

### Layout
- Problem: grid cells -> integer pixel boxes, identical for the prototype and the recipe.
- Rules: `col_w = (canvas.width - 2*margin - (columns-1)*gutter) / columns`; `x = margin +
  (col-1)*(col_w+gutter)`; `w = span*col_w + (span-1)*gutter`; `y = margin + (row-1)*row_height`;
  `h = rows*row_height - gutter`; round x and the right edge separately to integers so adjacent
  boxes keep a gutter of 16 ± 1 px; every box inside the canvas.
- Oracle: unit tests: two side-by-side spans of 6 fill the content width; gutters 15-17 px; no
  box exceeds the canvas.

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
  canvas size -> `background_p<n>.png` (POC: `background_p1.png`).
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
- Edge cases: empty query result -> chart shows "No data"; very long labels truncated with title attr.
- Oracle: tests parse the HTML: one `data-cid` per spec item, boxes equal Layout's, decoration
  layer has no visible component; background.png has the canvas size.

### Revise
- Problem: comments -> the smallest spec change.
- Rules: the revise node returns an RFC 6902 JSON patch touching only paths under the commented
  ids (and neighbours it must move to avoid overlap); the patch is applied to a copy, validated
  (one repair turn), then saved as `spec_version + 1`; each comment and the resulting change are
  appended to `decisions.md`.
- Edge cases: a comment on a decoration patches the decoration (it is re-rendered into the
  background); a request for a type outside the catalog or `DSS_ALLOWED_TYPES` is refused with an
  assistant message saying what Data Studio offers instead; conflicting comments on one id apply
  in order (last wins) and the message says so; an empty patch keeps `spec_version` and says
  "no change needed".
- Oracle: tests with FakeLLM patches: a patch touching an uncommented, non-neighbour id is
  rejected; each edge case above has a test.

### Recipe compiler
- Problem: spec -> recipe.jsonl valid against ../contracts/recipe.schema.json.
- Rules: header from build, version and `spec.datasource.table` (split into project, dataset,
  table); ops: `open_report`, `set_canvas`, `set_background_image` (`background_p1.png`), then components in reading order (y, then x) mapped by type
  (`date_range`/`dropdown` -> `add_control`, `text` -> `add_text`, `image` -> `add_image`, else
  `add_chart` with `chart_type` = type); per extra page `add_page`, `set_canvas`,
  `set_background_image`; one `set_style` per chart with the theme palette; then `save_report`,
  `get_link`. Boxes from Layout. Op ids `s001`... Deterministic: same spec -> byte-identical file.
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
| Gemini API (`gemini-4-argon`, `gemini-3.8-flash`) | LLM nodes | `GOOGLE_API_KEY` | per-call timeout (sent to Google, which enforces it as a 504): planner (plan/spec) 120 s, worker 30 s; errors -> `llm_unavailable`; one retry on 429/500/503, none on 504 (task 11.9) |
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
runtime dependency), pytest + pytest-asyncio (tests).

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
- Interview streams every LlmAgent; structured extractors ignore partial fragments and validate
  only the accumulated final response. Metric definitions start a sentence, optionally preceded
  by `For [the] [one qualifier] <audience role>,`; suggestions alone cannot confirm a mapping.
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
