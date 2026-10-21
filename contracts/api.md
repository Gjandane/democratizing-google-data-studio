# Contract: backend HTTP API (REST + SSE)
Version 2.0 · Change log: 1.0 (2026-10-18) first version, revised by the plan audit before any build
(recipe ops with ids, stage rules, engine_busy, shared fixtures). 1.1 (2026-10-19) Cloud Run:
Access (session endpoints, `access_required`), engine status `mode`/agent fields, Agent endpoints,
errors `access_denied`, `login_on_agent`, `agent_offline`, `agent_timeout`; fixtures
`session.json`, `engine_status.json`, `agent_job.json`; revised the same day by the delta audit
before any build (agent token, `settings_locked`, `invalid_name`, `invalid_report_url`,
`agent_mode_off`, `job_not_found`, `413`, `engine_status.local.json`).
1.2 (2026-10-19) activity transparency: `run.usage` event (live token counts per run) and the
list of `node` values; new fixture `events.usage.sse` (`events.sse` unchanged).
1.3 (2026-10-19) planned reference modes/lifecycle and feasibility gates, specified in
contracts/dashboard-intent.md 1.0. Existing Build and SSE shapes unchanged; new response fixtures
contracts/fixtures/dashboard-intent/{reference_set,feasibility}.json (outside the legacy
fixture inventory until consumers implement 1.3). Legacy style-images remains a compatible alias.
1.4 (2026-10-19) planned synthetic CSV API/proposal/provenance; Source.kind adds synthetic,
new node names synthetic_schema/synthetic_generate; contracts/synthetic-data.md 1.0.
Shared fixtures live separately in contracts/fixtures/synthetic-data/.
1.5 (2026-10-20) consistency only, no shape or route change (a 1.4 implementation conforms):
cites dashboard-intent.md 1.1 and synthetic-data.md 1.1; section headings name the versions that
added them; the `node` list adds `reference_extract`, `capability_check`, `reference_delete`,
`synthetic_schema` and `synthetic_generate`; new example fixtures
dashboard-intent/feasibility.{alternatives,pending,stale}.json and
synthetic-data/{dataset,job.succeeded}.json; mis-encoded characters repaired.
2.0 (2026-10-21, change staged workflow; breaking): the free-text interview and the `plan` action
are replaced by four confirmed artifacts (context, outline, design, blueprint). `Stage` drops
`interview` and `plan` and adds `context`, `outline`, `design`, `blueprint`; `Build` drops
`ready_for_plan` and adds `notes` and `artifacts`; removed `POST interview/start`,
`POST messages` and `POST plan`; new section Staged workflow endpoints, new types (Context,
Outline, Design, ThemePreset, Blueprint), event `artifact.updated`, error `409 artifact_invalid`;
`node` values `context`, `outline_propose`, `outline_other`, `outline_suggest`, `blueprint`,
`prototype` replace `interview`, `plan` and `spec`; Prototype HTML names each page. Fixtures:
build.json, build.done.json, builds.json, events.sse, events.usage.sse, messages.json updated;
new context.json, outline.json, design.json, design_presets.json, blueprint.json,
blueprint.blocked.json, prototype.multipage.html; prototype.sample.html wraps its page in a section.
Revised the same day by the delta audit before any build: re-confirm keeps downstream work
(`outline/propose`, `design/prefill` replace explicitly), no edits in build/done, legacy builds,
page sections in Prototype HTML.
Requirements and feasibility follow contracts/dashboard-intent.md 1.2.
Provider: backend. Consumers: frontend, release. Base: `http://localhost:8000/api` (the frontend
uses relative `/api`, proxied by Vite; contracts/conventions.md). JSON bodies, UTF-8. Errors use
the shape in contracts/conventions.md. Long-running actions return `202 {"run_id": "r_..."}` at
once and report progress on the build's event stream.
Shared fixtures: `contracts/fixtures/api/` (one JSON file per response type, `events.sse`,
`events.usage.sse` (a blueprint run with live token counts) and `prototype.sample.html`). The
frontend's mock mode loads them; the backend's and release's
contract tests check real responses against their shapes (same keys, same JSON types; a field
typed `|null` may be null or a value either way; a type with two fixtures, such as
`engine_status.json` and `engine_status.local.json`, matches either).

## Types
```text
Stage      = "connect" | "context" | "outline" | "design" | "blueprint" | "prototype" | "build"
             | "done"   /* 2.0: the order of the workflow; see Staged workflow endpoints */
ArtifactState = "missing" | "draft" | "confirmed" | "stale"
Archetype  = "executive" | "storytelling" | "operational" | "analytical"
Mode       = "data" | "research"
Column     = { name: string, type: "string"|"number"|"date"|"datetime"|"boolean"|"geo", sample: string[] }
Source     = { id: string, kind: "upload"|"gcs"|"bigquery"|"research"|"synthetic", name: string,
               bq_table: string /* project.dataset.table */, row_count: int, columns: Column[] }
DocRef     = { path: string /* relative to the version's docs/ */, title: string, type: string }
Version    = { n: int, status: "draft"|"building"|"published"|"failed", report_url: string|null,
               created_at: string }
Build      = { id: string, title: string, archetype: Archetype, mode: Mode, stage: Stage,
               created_at: string, updated_at: string, sources: Source[], docs: DocRef[],
               spec_version: int|null, current_version: int, versions: Version[],
               report_url: string|null,
               notes: string|null /* the user's "about this data" text, 2.0 */,
               artifacts: { context: ArtifactState, outline: ArtifactState, design: ArtifactState,
                            blueprint: ArtifactState } /* 2.0 */ }
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
| `GET /api/builds/{id}/messages` | — | `Message[]`, oldest first (assistant explanations, refusals and revise outcomes; 2.0 has no free-text chat input) |
| `GET /api/builds/{id}/docs/{path}` | — | `text/markdown` of one build doc |
| `GET /api/builds/{id}/spec` | — | the current spec JSON (read-only display) |
| `GET /api/builds/{id}/prototype` | query `layer=all\|decoration` (default `all`), `v=<spec_version>` (cache-buster, ignored) | `text/html` (see Prototype HTML) |
| `POST /api/builds/{id}/comments` | `{comments: Comment[]}` (1-20) | `202 {run_id}`; `prototype.updated` when done |
| `POST /api/builds/{id}/audit` | — | `202 {run_id}` (stretch); findings arrive as an assistant message |
| `POST /api/builds/{id}/recipe` | — | `200 {op_count: int, ops: [{op_id: string, line: string /* dsengine print line */}]}`; compiles from the current spec |
| `POST /api/builds/{id}/run` | — | `202 {run_id}`; stage -> `build`, then `done` (also after `partial`); after `failed` the stage returns to `prototype`. One engine run at a time on the machine: else `409 engine_busy`. Agent mode: queued as a `Job`; no agent heartbeat in the last 30 s -> `424 agent_offline` |
| `POST /api/builds/{id}/versions` | — | `201 Build`: new version from the latest spec and its four confirmed artifacts; stage -> `prototype` |
| `GET /api/builds/{id}/files/{name}` | — | a file from the current version folder (`background_p<n>.png`, `screens/<file>`) |
| `GET /api/builds/{id}/events` | — | `text/event-stream` (below) |
| `GET /api/traces` | query `build_id?` | `Trace[]`, newest first |
| `GET /api/engine/status` | — | `EngineStatus` (agent mode: `chrome_running` and `signed_in` come from the agent's last heartbeat) |
| `POST /api/engine/login` | — | `202 {run_id}`; opens the sign-in window. Agent mode: `409 login_on_agent` (run `dsengine login` on the agent's machine) |

## Staged workflow endpoints (added in 2.0)
The workflow is connect -> context -> outline -> design -> blueprint -> prototype -> build -> done.
Each middle stage produces one artifact the user reviews and confirms. Code writes every artifact
file (OKF build docs `context.md`, `outline.md`, `design.md`, `blueprint.md`); a model only fills
the judgment fields of a structured draft, and code validates it.

```text
Agg        = "sum" | "avg" | "count" | "count_distinct" | "min" | "max"
ValidationIssue = { path: string /* JSON pointer into the artifact */, message: string }
DerivedField = { name: string /* snake_case, unique across base and derived fields */,
               expression: string /* BigQuery row-level SQL over base columns; no aggregates */,
               type: "string"|"number"|"date"|"datetime"|"boolean"|"geo", description: string }
Kpi        = { id: string /* snake_case */, name: string, description: string, unit: string|null,
               measure: {field: string, agg: Agg}|null,
               ratio: {numerator: string, denominator: string}|null /* Kpi ids; exactly one of
               measure and ratio is non-null */ }
Threshold  = { id: string, name: string, field: string, operator: ">"|">="|"<"|"<="|"=",
               value: number, unit: string|null, description: string }
Term       = { term: string, definition: string }
Context    = { revision: int, title: string, goal: string, audience: string|null,
               datasets: [{source_id: string, summary: string}], derived_fields: DerivedField[],
               kpis: Kpi[], thresholds: Threshold[], glossary: Term[],
               issues: ValidationIssue[] /* code checks; confirm needs [] */ }
OutlineQuestion = { id: string /* q1, q2 ... stable */, text: string, rationale: string,
               recommended: boolean, selected: boolean, kpi_refs: string[],
               origin: "proposed"|"suggested"|"other" }
OutlineSection = { id: string /* s1 ... */, title: string, purpose: string,
               questions: OutlineQuestion[] }
Outline    = { revision: int, sections: OutlineSection[] }
ThemePreset = { id: string, name: string, description: string, archetypes: Archetype[],
               background: string, surface: string, text: string, muted: string, accent: string,
               palette: string[], font_family: string, radius: int, decoration_kit: string }
Design     = { revision: int, preset_id: string, background: string, surface: string,
               text: string, accent: string, palette: string[] /* 3-8 */, font_family: string
               /* one of the presets' fonts */, page_structure: "single"|"per_section",
               density: "comfortable"|"compact", title: string, subtitle: string|null,
               source: "preset"|"user"|"reference", issues: ValidationIssue[] }
BlueprintComponent = { type: string /* a catalog type allowed by DSS_ALLOWED_TYPES */,
               label: string, dimensions: string[], metrics: [{field: string, agg: Agg|"none"}],
               date_dimension: string|null, breakdown: string|null,
               sort: {field: string, order: "asc"|"desc"}|null, options: object }
BlueprintRow = { question_id: string|null /* null for a supporting control */, section_id: string,
               page: int /* 1-based */, component: BlueprintComponent, note: string,
               status: "ok"|"blocked", issue_ids: string[] }
ViewSources = { base: string /* source id */,
               joins: [{source_id: string, on: [{left: string, right: string}]}],
               union: string[] /* source ids stacked under base: missing columns are NULL, plus a
               `dataset_name` column; joins and union are never both non-empty */ }
Blueprint  = { revision: int, view_sources: ViewSources, derived_fields: DerivedField[],
               rows: BlueprintRow[],
               view_table: string|null /* project.dataset.table, after a dry run passes */,
               assessment_id: string|null }
```
Colors are `#RRGGBB`. Fixtures: `context.json`, `outline.json`, `design.json`,
`design_presets.json`, `blueprint.json`, `blueprint.blocked.json` (a blocked ratio row) in
contracts/fixtures/api/.

| Method and path | Body | Response |
|---|---|---|
| `POST /api/builds/{id}/context` | `{notes?: string}` (at most 4000 chars) | `202 {run_id}`, node `context`; allowed in `connect` (at least one source) and `context` (redraft); stage -> `context`; saves `notes` and drafts the Context |
| `GET /api/builds/{id}/context` | — | `200 Context\|null` |
| `PUT /api/builds/{id}/context` | Context without `revision`, `issues` | `200 Context` (code fills `issues`, `revision` + 1) |
| `POST /api/builds/{id}/context/confirm` | — | `202 {run_id}`, node `outline_propose`; needs `issues` `[]` (else `409 artifact_invalid`); context -> `confirmed`; stage -> `outline`; proposes the Outline when none exists, otherwise revalidates it in code (unknown kpi_refs removed with a note, every selection kept, no model call) |
| `GET /api/builds/{id}/outline` | — | `200 Outline\|null` |
| `POST /api/builds/{id}/outline/propose` | — | `202 {run_id}`, node `outline_propose`; allowed in `outline`; re-proposes explicitly, keeping `other` questions and the selection of questions whose text is unchanged |
| `PUT /api/builds/{id}/outline/selection` | `{questions: [{id: string, selected: boolean}]}` (1-100) | `200 Outline`; code only, no run |
| `POST /api/builds/{id}/outline/other` | `{section_id: string\|null, text: string}` (1-1000 chars) | `202 {run_id}`, node `outline_other`; adds the normalized questions, selected, origin `other`, to that section (null: a new section) |
| `POST /api/builds/{id}/outline/suggest` | `{section_id: string}` | `202 {run_id}`, node `outline_suggest`; adds up to 5 unselected questions to that section |
| `POST /api/builds/{id}/outline/confirm` | — | `200 Build`; needs 1-24 selected questions (else `409 artifact_invalid`); outline -> `confirmed`; stage -> `design`; a missing Design is prefilled (archetype preset, then reference style; `per_section` when 1-5 sections have a selected question, else `single`); an existing Design is kept and revalidated |
| `GET /api/builds/{id}/design/presets` | — | `200 ThemePreset[]` |
| `GET /api/builds/{id}/design` | — | `200 Design\|null` |
| `POST /api/builds/{id}/design/prefill` | — | `200 Design`; allowed in `design`; replaces the Design with a fresh prefill (code only) |
| `PUT /api/builds/{id}/design` | Design without `revision`, `issues` | `200 Design` |
| `POST /api/builds/{id}/design/confirm` | — | `202 {run_id}`, node `blueprint`; needs `issues` `[]`; design -> `confirmed`; stage -> `blueprint`; drafts the Blueprint (on a redraft, rows of unchanged selected questions and their decisions are kept and only new or changed questions go to the model), checks feasibility and dry-runs the view |
| `GET /api/builds/{id}/blueprint` | — | `200 Blueprint\|null` |
| `POST /api/builds/{id}/blueprint/regenerate` | — | `202 {run_id}`, node `blueprint`; allowed in `blueprint` and `prototype`; stage -> `blueprint`; redrafts every row |
| `POST /api/builds/{id}/blueprint/accept` | — | `202 {run_id}`, node `prototype`; needs the assessment `ready` (else `409 feasibility_blocked`) and at least one ok row (else `409 artifact_invalid`); blueprint -> `confirmed`; lays out the spec and renders; stage -> `prototype` when the prototype is ready; on failure the stage stays `blueprint` and `run.finished` carries the error |

Stage rules:
- Any other stage -> `409 wrong_stage`. One action per build at a time (existing lock).
- Builds stored in the removed stages `interview` or `plan` read as `context`.
- Artifact edits are allowed only in stages `context` to `prototype`; in `build` or `done` they
  get `409 wrong_stage` (from `done`, start a New version).
- Editing an earlier artifact in a later stage (`PUT context`, `PUT outline/selection`,
  `outline/other`, `outline/suggest`, `PUT design`) sets that artifact to `draft`, every later
  artifact to `stale`, and the stage back to that artifact's stage. The current spec, prototype
  and view stay until a new prototype commits. `PUT` in the artifact's own stage keeps `draft`.
  Confirming again keeps a stale downstream artifact and revalidates it in code; replacing it is
  the explicit `outline/propose`, `design/prefill` or `blueprint/regenerate`.
- `recipe` and `run` additionally need all four artifacts `confirmed`; a build made before 2.0
  (all four `missing` and a saved spec) is exempt, and so are its new versions.
- `artifact.updated` follows every artifact write; the client refetches that artifact.

## Reference and feasibility endpoints (added in 1.3)
Rules and exact response shapes: contracts/dashboard-intent.md 1.2. Fixtures:
contracts/fixtures/dashboard-intent/ (`reference_set.json`; `feasibility.json` and its
`.alternatives`, `.pending`, `.stale` variants). Auth and per-build action serialization apply.
Run nodes: `reference_extract`, `reference_delete` and `capability_check` (Event stream).

| Method and path | Body | Response |
|---|---|---|
| `GET /api/builds/{id}/reference-images` | none | `200 ReferenceSet|null` |
| `POST /api/builds/{id}/reference-images` | multipart files, mode, instructions | `202 {run_id}`; extraction commits atomically |
| `DELETE /api/builds/{id}/reference-images` | none | `204`; invalidates assessment and prototype intent |
| `GET /api/builds/{id}/feasibility` | none | `200 Assessment` |
| `POST /api/builds/{id}/feasibility/check` | none | `202 {run_id}`; assessment only |
| `POST /api/builds/{id}/feasibility/reapply` | assessment_id, batch_id | `202 {run_id}`; recover persisted blocked comments |
| `DELETE /api/builds/{id}/feasibility/pending-comments` | query assessment_id | `200 Assessment`; abandon only this pending batch |
| `POST /api/builds/{id}/feasibility/decisions` | assessment_id, decisions per dashboard-intent.md | `200 Assessment`; no auto-plan/build |

New errors: `409 feasibility_blocked` (detail assessment_id, issue_ids), `409 feasibility_stale`
(reload before choosing again). Reference upload errors use existing 413/422/409 codes. New
routes are required; legacy style-images is no longer optional once 11.2 lands. Stage transitions
additionally obey feasibility, including `blueprint/accept`, recipe and run calls (2.0).

## Synthetic data endpoints (added in 1.4)
See contracts/synthetic-data.md 1.1 for request/response types, generation rules, budgets,
replay behavior, failure handling and required labeling. Auth is unchanged. Fixtures:
contracts/fixtures/synthetic-data/ (`request.json`, `proposal.json`, `dataset.json`,
`source.json`, `job.succeeded.json`, `job.failed.json`).

| Method and path | Request | Response |
|---|---|---|
| `POST /api/builds/{id}/synthetic-data/proposal` | reference_set_id | `202 {run_id}`; no CSV/source prerequisite |
| `GET /api/builds/{id}/synthetic-data/proposal` | none | `200 Proposal|null` |
| `POST /api/builds/{id}/synthetic-data` | generation_key, proposal_id, spec | `202 {run_id}`; generation + typed BigQuery intake |
| `GET /api/builds/{id}/synthetic-data` | none | `200 SyntheticDataset[]` |
| `GET /api/builds/{id}/synthetic-data/jobs` | none | `200 GenerationStatus[]`, latest 20 |
| `GET /api/builds/{id}/synthetic-data/jobs/{generation_key}` | none | `200 GenerationStatus`; persisted recovery state |
| `GET /api/builds/{id}/synthetic-data/{source_id}/csv` | none | CSV attachment, scoped to this build/source |

Node names add `synthetic_schema` and `synthetic_generate`; event payloads unchanged. Errors:
`422 invalid_generation_spec` (field errors), `422 synthetic_schema_unavailable`,
`409 synthetic_proposal_stale`, `409 synthetic_request_conflict`,
`409 synthetic_requires_empty_build`; body >64 KiB is `413`. Async failures use run.finished.

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
the current stage; `detail.stage`); `409 artifact_invalid` (confirm with open validation issues;
`detail.issues`: ValidationIssue[], 2.0); `409 engine_busy`; `422 invalid_source` (bad CSV or URI;
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
| `build.updated` | `{build: Build}` (sent whenever `artifacts`, `notes`, sources, versions or `report_url` change) |
| `artifact.updated` | `{artifact: "context"\|"outline"\|"design"\|"blueprint", revision: int}` (2.0) |
| `run.started` | `{run_id, node}` |
| `run.usage` | `{run_id, node, input_tokens: int, output_tokens: int}`: the run's totals so far, sent after each model response that reports usage (none for runs without a model call) |
| `node.progress` | `{run_id, node, text}` (short status line, e.g. "Checking feasibility") |
| `run.finished` | `{run_id, node, status: "ok"\|"error", error: string\|null}` |
| `docs.updated` | `{docs: DocRef[]}` |
| `prototype.updated` | `{spec_version: int}` |
| `build.op` | the engine's `op_finished` event (contracts/recipe.md) |
| `build.frame` | `{data}` base64 JPEG (stretch, screencast) |
| `build.finished` | `{status: "ok"\|"partial"\|"failed", report_url: string\|null, version: int}` |

`node` in `run.*` and `node.progress` is the action that started the run: `context`,
`outline_propose`, `outline_other`, `outline_suggest`, `blueprint`, `prototype` (2.0), `revise`, `research`, `style_extract`, `ux_audit`, `intake`, `create_build`, `versions`,
`load_spec`, `recipe`, `execute` (the Data Studio build), `engine_login`, `consolidate`,
`reference_extract`, `reference_delete`, `capability_check` (1.3), `synthetic_schema`,
`synthetic_generate` (1.4). A client
treats any other value as a generic run. `run.usage` totals only grow within a run; `run.finished`
follows the last one.

## Prototype HTML
`GET /api/builds/{id}/prototype` returns one self-contained HTML page (inline CSS; charts drawn
with ECharts loaded from a CDN or inlined). The frontend relies only on this:
- The page canvas is `<div id="dss-canvas">` with the spec's fixed pixel `width` and a height equal
  to the sum of its pages' heights. It holds one `<section data-page="<n>" data-page-name="<name>">`
  per page (2.0), stacked vertically with no gap, each `position: relative` with its page's
  height: one page per outline section when the Design's `page_structure` is `per_section` (at
  most 5). Fixtures: `prototype.sample.html` (one page), `prototype.multipage.html` (two pages).
- Every spec component and every decoration (header band, title, panel, logo) has a root element
  with `data-cid="<id>"`, `data-label="<human label>"` and `data-kind="component"` or
  `data-kind="decoration"`. It is absolutely positioned at its box inside its page section, and no
  `data-cid` element is nested inside another (a panel behind a chart is a sibling). Both kinds are commentable;
  a `Comment.component_id` may name either.
- `layer=decoration` returns the same page with every `data-kind="component"` element hidden
  (this is what becomes `background_p<n>.png`, one per page).
