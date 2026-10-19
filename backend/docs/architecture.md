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
- `sources(id, build_id, kind, name, bq_table, row_count, columns_json)`
- `messages(id, build_id, role, text, node, created_at)` + `messages_fts` (FTS5 over text, external content)
- `events(id, build_id, run_id, kind, payload_json, created_at)`
- `traces(run_id, build_id, node, model, input_tokens, output_tokens, latency_ms, tool_calls, status, error, spans_json, started_at)`
- `settings(key, value)` (API key stored here only when set from the UI; never returned)
- `consolidation(id, last_run_at, chats_since)`
Files per version: `data/builds/<id>/v<n>/` (../contracts/conventions.md).

## Key flows
- **Agent run** (one per API action): load settings -> assemble working memory for the node
  (`context.py`) -> node runs (LLM loop with tools, or code) -> guardrails -> write episodic
  (messages/events) -> emit SSE -> write exactly one trace -> drop run state.
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
- **plan**: plan node (planner) writes build docs -> view node builds SQL, BigQuery dry run;
  on error one repair turn with the error -> create view -> spec node (planner) -> validate
  -> repair loop (<= 2) -> render -> background -> stage `prototype`.
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

### Graph
- Problem: one ADK 2.0 `Workflow` that is the harness's agent run for every action.
- Model check: at startup and when settings change, list the available models; if the planner
  model is missing, log a warning and use the worker model for plan and spec.
- Inputs and outputs: `{action, build_id, payload}` -> SSE events, DB writes, one trace.
- Rules: START -> router(action) -> the action's branch (Key flows). LLM nodes: interview, plan,
  spec, revise, ux_audit, style_extract, research, consolidate. Code nodes: intake, view (SQL
  build + dry run), validate, render, compile, execute, publish. The validate -> spec (or revise)
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
- Oracle: test with FakeLLM and `DSS_CONSOLIDATE_EVERY=5`: 4 builds -> no write; 5th -> files written, counter reset, every
  file has parseable frontmatter with non-empty `type`.

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
- Problem: one view per version that holds joins and derived fields, attached to the report.
- Rules: `CREATE OR REPLACE VIEW <project>.<BQ_DATASET>.dash_<build_id>_v<n> AS SELECT <base
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

## External APIs and services
| Service | Used for | Auth | Limits and failure handling |
|---|---|---|---|
| Gemini API (`gemini-4-argon`, `gemini-3.8-flash`) | LLM nodes | `GOOGLE_API_KEY` | errors -> `llm_unavailable`; one retry on 429/5xx |
| BigQuery | loads, profile, view, aggregates | ADC (`gcloud auth application-default login`) | errors surfaced with BigQuery's message |
| GCS | CSV source URIs (read by BigQuery load jobs) | ADC | bad URI -> `422 invalid_source` |
| Google Search (ADK tool) | research discovery (stretch) | API key | one model call; provider-internal fetches opaque |
| Python table scraper (stdlib) | research CSV/HTML retrieval | none | 20 HTTP requests per run, redirects/failures included; no retries |

Research budget refinement (task 7.3, approved by user 2026-10-19): discovery uses one
Google Search model call. Code retrieves public CSV/HTML tables within the separate
20-request cap. A second model call selects a table from title, URL, headers and row counts;
scraped rows stay out of model context. Code normalizes headers/whitespace, removes exact
duplicate rows and repeated headers, and writes the CSV and sources.md before existing
intake registers a research source. Provenance records discovery citations and every
attempted HTTP URL, including redirects and failures. The reusable Python scraper command
shares the same limits and parser; it does not execute JavaScript or invent missing data.
| dsengine (subprocess) | building the report | none | exit codes per ../contracts/recipe.md |
| Cloud Run | hosting (one instance) | runtime service account (BigQuery Data Editor + Job User) is the ADC there | restart -> running agent job fails with `agent_timeout`; DB restored from the volume |
| Secret Manager | `GOOGLE_API_KEY`, `DSS_ACCESS_CODE`, `DSS_AGENT_TOKEN` as env vars | Cloud Run (runtime SA: Secret Accessor) | too short or missing code/token -> the backend refuses to start on Cloud Run |
| GCS volume (`/data`) | state files and the DB backup | Cloud Run gen2 (runtime SA: Storage Object User) | no file locking: the live DB stays on local disk; up to 30 s of writes lost on a crash |

## Dependencies
fastapi/uvicorn (API), sse-starlette (SSE), python-multipart (uploads), google-adk (graph,
agents, tools), google-genai (Gemini client, token counts), google-cloud-bigquery (data),
python-dotenv (env), pydantic (models), pyyaml (OKF frontmatter), jsonpatch (RFC 6902 patches), jsonschema (contract test),
playwright (background screenshot), httpx (TestClient and the `dss-agent` HTTP client, so a
runtime dependency), pytest + pytest-asyncio (tests).

## Testing
pytest, offline by default: FakeLLM (scripted responses by node), FakeBigQuery (in-memory rows
from a CSV), fake engine (a script that prints ../contracts/fixtures/events.sample.jsonl).
Live tests marked `live` (excluded by default). Test (all) = `uv run pytest`.

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
| 2026-10-19 | Build agent `dss-agent` lives in backend and reuses the execute node's event handling; in-memory job queue | agent in engine; Pub/Sub queue | one part owns both sides of the agent endpoints; one instance needs no external queue | change 2026-10-19 |
