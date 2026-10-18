# Contract: backend HTTP API (REST + SSE)
Version 1.1 · Change log: 1.0 (2026-10-18) first version, revised by the plan audit before any build
(recipe ops with ids, stage rules, engine_busy, shared fixtures). 1.1 (2026-10-19) Cloud Run:
Access (session endpoints, `access_required`), engine status `mode`/agent fields, Agent endpoints,
errors `access_denied`, `login_on_agent`, `agent_offline`, `agent_timeout`; fixtures
`session.json`, `engine_status.json`, `agent_job.json`; revised the same day by the delta audit
before any build (agent token, `settings_locked`, `invalid_name`, `invalid_report_url`,
`agent_mode_off`, `job_not_found`, `413`, `engine_status.local.json`).
Provider: backend. Consumers: frontend, release. Base: `http://localhost:8000/api` (the frontend
uses relative `/api`, proxied by Vite; contracts/conventions.md). JSON bodies, UTF-8. Errors use
the shape in contracts/conventions.md. Long-running actions return `202 {"run_id": "r_..."}` at
once and report progress on the build's event stream.
Shared fixtures: `contracts/fixtures/api/` (one JSON file per response type, `events.sse`, and
`prototype.sample.html`). The frontend's mock mode loads them; the backend's and release's
contract tests check real responses against their shapes (same keys, same JSON types; a field
typed `|null` may be null or a value either way; a type with two fixtures, such as
`engine_status.json` and `engine_status.local.json`, matches either).

## Types
```text
Stage      = "connect" | "interview" | "plan" | "prototype" | "build" | "done"
Archetype  = "executive" | "storytelling" | "operational" | "analytical"
Mode       = "data" | "research"
Column     = { name: string, type: "string"|"number"|"date"|"datetime"|"boolean"|"geo", sample: string[] }
Source     = { id: string, kind: "upload"|"gcs"|"bigquery"|"research", name: string,
               bq_table: string /* project.dataset.table */, row_count: int, columns: Column[] }
DocRef     = { path: string /* relative to the version's docs/ */, title: string, type: string }
Version    = { n: int, status: "draft"|"building"|"published"|"failed", report_url: string|null,
               created_at: string }
Build      = { id: string, title: string, archetype: Archetype, mode: Mode, stage: Stage,
               created_at: string, updated_at: string, sources: Source[], docs: DocRef[],
               spec_version: int|null, current_version: int, versions: Version[],
               report_url: string|null,
               ready_for_plan: boolean /* the interview has enough to plan */ }
BuildSummary = { id, title, archetype, stage, updated_at, report_url }   (fields as in Build)
Message    = { id: string, role: "user"|"assistant"|"system", text: string /* markdown */,
               node: string|null, created_at: string }
Comment    = { component_id: string, text: string }
Trace      = { run_id: string, build_id: string|null, node: string, model: string|null,
               input_tokens: int, output_tokens: int, latency_ms: int, tool_calls: int,
               status: "ok"|"error", error: string|null, started_at: string }
Settings   = { planner_model: string, worker_model: string, gcp_project_id: string,
               bq_dataset: string, bq_location: string, gcs_bucket: string,
               google_api_key_set: boolean }
Session    = { required: boolean /* DSS_ACCESS_CODE is set */, ok: boolean /* this request carries a valid code */ }
EngineStatus = { mode: "local"|"agent", chrome_running: boolean, signed_in: boolean,
               agent_connected: boolean /* a heartbeat in the last 30 s; false in local mode */,
               agent_last_seen: string|null }
Job        = { run_id: string, build_id: string, version: int, dry_run: boolean, timeout_s: int,
               files: string[] /* "recipe.jsonl" first, then every file the recipe's ops name */ }
```

## Access
When `DSS_ACCESS_CODE` is set (contracts/conventions.md), every `/api` route except
`GET /api/health`, `GET /api/session` and `POST /api/session` needs either the `dss_session`
cookie (set by `POST /api/session`; HttpOnly, SameSite=Strict, Secure on https) or the header
`X-DSS-Access-Code: <code>`; otherwise `401 access_required`. The browser uses the cookie, because
`EventSource` and the prototype iframe can't send headers; scripts use the header. The cookie is
`Secure` whenever the request arrived over https (Cloud Run's `X-Forwarded-Proto`). A wrong code
answers after a 1 s delay. When the code is empty, nothing is gated and `GET /api/session`
returns `{required: false, ok: true}`. The Agent endpoints use their own token instead (below).
Every `{name}`/`{file}` path parameter must match `^[A-Za-z0-9._-]+$` and resolve inside its
folder; otherwise `400 invalid_name`.

## Endpoints
| Method and path | Body | Response |
|---|---|---|
| `GET /api/health` | — | `{status: "ok"}` (never gated; Cloud Run probes it) |
| `GET /api/session` | — | `Session` |
| `POST /api/session` | `{code: string}` | `200 Session` with `Set-Cookie: dss_session=...`; wrong code -> `401 access_denied` |
| `GET /api/settings` | — | `Settings` |
| `PUT /api/settings` | partial `Settings` fields, plus `google_api_key?: string` (write-only) | `Settings`. Agent mode (Cloud Run): any field other than `planner_model`/`worker_model` -> `403 settings_locked` |
| `GET /api/builds` | — | `BuildSummary[]`, newest `updated_at` first |
| `POST /api/builds` | `{title?: string, archetype: Archetype, mode: Mode}` | `201 Build` (stage `connect`) |
| `GET /api/builds/{id}` | — | `Build` |
| `POST /api/builds/{id}/sources/upload` | multipart, field `files` (one or more `.csv`) | `201 {sources: Source[]}` |
| `POST /api/builds/{id}/sources` | `{kind: "gcs"\|"bigquery", uri: string}` (`gs://bucket/path.csv` or `project.dataset.table`) | `201 Source` |
| `POST /api/builds/{id}/style-images` | multipart, field `files` (png/jpg) | `202 {run_id}` (stretch) |
| `POST /api/builds/{id}/research` | `{prompt: string}` | `202 {run_id}` (stretch; mode `research`) |
| `POST /api/builds/{id}/interview/start` | — | `202 {run_id}`; stage -> `interview`; the first question streams |
| `GET /api/builds/{id}/messages` | — | `Message[]`, oldest first |
| `POST /api/builds/{id}/messages` | `{text: string}` | `202 {run_id, message_id}` (the user message's id) |
| `POST /api/builds/{id}/plan` | — | `202 {run_id}`; allowed in stage `interview` (even before `ready_for_plan`) or `prototype` (re-plan); stage -> `plan`, then `prototype` when the prototype is ready; on failure stage returns to `interview` and `run.finished` carries the error |
| `GET /api/builds/{id}/docs/{path}` | — | `text/markdown` of one build doc |
| `GET /api/builds/{id}/spec` | — | the current spec JSON (read-only display) |
| `GET /api/builds/{id}/prototype` | query `layer=all\|decoration` (default `all`), `v=<spec_version>` (cache-buster, ignored) | `text/html` (see Prototype HTML) |
| `POST /api/builds/{id}/comments` | `{comments: Comment[]}` (1-20) | `202 {run_id}`; `prototype.updated` when done |
| `POST /api/builds/{id}/audit` | — | `202 {run_id}` (stretch); findings arrive as an assistant message |
| `POST /api/builds/{id}/recipe` | — | `200 {op_count: int, ops: [{op_id: string, line: string /* dsengine print line */}]}`; compiles from the current spec |
| `POST /api/builds/{id}/run` | — | `202 {run_id}`; stage -> `build`, then `done` (also after `partial`); after `failed` the stage returns to `prototype`. One engine run at a time on the machine: else `409 engine_busy`. Agent mode: queued as a `Job`; no agent heartbeat in the last 30 s -> `424 agent_offline` |
| `POST /api/builds/{id}/versions` | — | `201 Build`: new version from the latest spec; stage -> `prototype` |
| `GET /api/builds/{id}/files/{name}` | — | a file from the current version folder (`background_p1.png`, `screens/<file>`) |
| `GET /api/builds/{id}/events` | — | `text/event-stream` (below) |
| `GET /api/traces` | query `build_id?` | `Trace[]`, newest first |
| `GET /api/engine/status` | — | `EngineStatus` (agent mode: `chrome_running` and `signed_in` come from the agent's last heartbeat) |
| `POST /api/engine/login` | — | `202 {run_id}`; opens the sign-in window. Agent mode: `409 login_on_agent` (run `dsengine login` on the agent's machine) |

## Agent endpoints
Agent mode only (`404 agent_mode_off` in local mode). Used only by the build agent
(contracts/conventions.md, Build agent). Every call needs `X-DSS-Agent-Token: <DSS_AGENT_TOKEN>`
(constant-time compare), else `401 agent_unauthorized`; the access code is not accepted here.

| Method and path | Body | Response |
|---|---|---|
| `POST /api/agent/heartbeat` | `{chrome_running: boolean, signed_in: boolean, agent_version: string}` | `{ok: true}`; the agent sends it every 10 s |
| `GET /api/agent/jobs/next` | query `wait=<s>` (long poll, max 25) | `200 Job`, or `204` when no job is queued within `wait` |
| `GET /api/agent/jobs/{run_id}/files/{name}` | — | the bytes of one file listed in `Job.files` |
| `POST /api/agent/jobs/{run_id}/events` | `{events: object[]}` (engine stdout events, in order, one or more) | `{ok: true}`; each `op_finished` is relayed as `build.op` |
| `PUT /api/agent/jobs/{run_id}/screens/{file}` | raw PNG bytes | `{ok: true}`; stored as `screens/<file>` of the build version |
| `POST /api/agent/jobs/{run_id}/finished` | `{exit_code: int, stderr_tail: string}` | `{ok: true}`; mapped like a local `dsengine run` exit (contracts/recipe.md), then `build.finished` |

A job with no events or `finished` for `Job.timeout_s + 60` s fails with `build.finished(failed)`
and error `agent_timeout`, and the engine lock is released; a server restart fails the running job
the same way. A job is handed out once; calls for an unknown or finished `run_id` get
`404 job_not_found`. A `report_url` whose host is not `datastudio.google.com` or
`lookerstudio.google.com` is never stored: the run fails with `invalid_report_url`. Screens and
files are accepted only for names in `Job.files` or plain screenshot names (Access, `invalid_name`).

Errors worth handling in the UI: `404 build_not_found`; `409 wrong_stage` (action not allowed in
the current stage; `detail.stage`); `409 engine_busy`; `422 invalid_source` (bad CSV or URI;
`detail.reason`); `424 engine_not_signed_in`; `503 llm_unavailable` (no API key or the model
call failed); `503 gcp_not_configured` (no `gcp_project_id`). The UI sends the user to Settings
on both 503s. Cloud Run: `401 access_required` (the UI shows the access-code gate);
`401 access_denied` (wrong code); `409 login_on_agent`; `424 agent_offline` (the UI shows how to
start the build agent); `403 settings_locked` (Settings shows the field as fixed by the
deployment); `413` from Cloud Run (an HTML page, not the JSON shape) on uploads over 32 MB: the UI
checks file size first and maps any 413 to "Files over 32 MB can't be uploaded to the hosted app";
`400 invalid_name`.

## Event stream: `GET /api/builds/{id}/events`
Server-Sent Events. Each event has an `event:` name and a JSON `data:` line. The stream starts
with `ready` and sends a `ping` comment every 15 s. Events are not replayed: after (re)connecting,
the client re-reads `GET /api/builds/{id}` and `GET /api/builds/{id}/messages`.

| event | data |
|---|---|
| `ready` | `{build_id}` |
| `message.delta` | `{message_id, text}` (append `text` to that assistant message) |
| `message.done` | `{message: Message}` |
| `stage.changed` | `{stage: Stage}` |
| `build.updated` | `{build: Build}` (sent whenever `ready_for_plan`, sources, versions or `report_url` change) |
| `run.started` | `{run_id, node}` |
| `node.progress` | `{run_id, node, text}` (short status line, e.g. "Writing questions.md") |
| `run.finished` | `{run_id, node, status: "ok"\|"error", error: string\|null}` |
| `docs.updated` | `{docs: DocRef[]}` |
| `prototype.updated` | `{spec_version: int}` |
| `build.op` | the engine's `op_finished` event (contracts/recipe.md) |
| `build.frame` | `{data}` base64 JPEG (stretch, screencast) |
| `build.finished` | `{status: "ok"\|"partial"\|"failed", report_url: string\|null, version: int}` |

## Prototype HTML
`GET /api/builds/{id}/prototype` returns one self-contained HTML page (inline CSS; charts drawn
with ECharts loaded from a CDN or inlined). The frontend relies only on this:
- The page canvas is `<div id="dss-canvas">` with fixed pixel `width` and `height` (the spec's
  canvas), and pages stacked vertically with `data-page="<n>"`.
- Every spec component and every decoration (header band, title, panel, logo) has a root element
  with `data-cid="<id>"`, `data-label="<human label>"` and `data-kind="component"` or
  `data-kind="decoration"`. It is absolutely positioned at its box, and no `data-cid` element is
  nested inside another (a panel behind a chart is a sibling). Both kinds are commentable;
  a `Comment.component_id` may name either.
- `layer=decoration` returns the same page with every `data-kind="component"` element hidden
  (this is what becomes `background.png`).
