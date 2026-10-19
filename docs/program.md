# Program: Democratizing Google Data Studio
An agentic app that interviews a user, designs a Data Studio dashboard as an HTML prototype, and
builds the real dashboard in Data Studio from a compiled recipe. GCP hackathon entry, local first.
Written 2026-10-18.

## Problem and users
- Problem: building a Data Studio dashboard takes hours of clicking plus design skill; people who
  know their data (analysts, managers, students) can't turn their questions into a good dashboard.
- Local user (one, no accounts): connects data or describes a topic, answers an interview,
  comments on a prototype, and gets a real Data Studio dashboard link.
- Context: Google GCP hackathon (AI Builder Cup). Deadline **2026-10-23 01:05 MPST** (moved from
  2026-10-20 01:05 by the user on 2026-10-20, change 2026-10-20; earlier moved from 2026-10-19 01:05,
  change 2026-10-19).
- Hosted on Cloud Run in this version (change 2026-10-19): the app runs as one Cloud Run service
  behind a shared access code; the Data Studio build runs through a build agent on the user's
  machine, because the engine needs the signed-in Chrome profile.

## Parts
| Part | Folder | Purpose | Target | Provides | Consumes |
|---|---|---|---|---|---|
| engine | engine/ | `dsengine` CLI: runs a recipe in Data Studio through Playwright on a signed-in Chrome profile; streams one event per op | POC | contracts/recipe.md (events half) | contracts/recipe.md, contracts/conventions.md |
| backend | backend/ | the harness: ADK 2.0 graph, three memory types, Gemini calls, data intake to BigQuery, spec, HTML renderer, recipe compiler, REST + SSE API; cloud mode (static frontend, access code, DB backup) and the build agent (`dss-agent`) | POC | contracts/api.md, contracts/recipe.md (recipe half) | contracts/conventions.md, contracts/recipe.md (events half) |
| frontend | frontend/ | the web app: history, workspace with stage stepper, chat, click-to-comment prototype, build view, settings, trace tab; access-code gate and build-agent status | POC | - | contracts/api.md, contracts/conventions.md |
| release | . | end-to-end flow checks (local and deployed), start scripts, Dockerfile and Cloud Run deploy script, README, `.env.example`, LICENSE, the AI Builder Cup submission deck (pptx + pdf, HTML-rendered diagrams) | POC | - | every contract |

## Goals and non-goals
- Target: POC (hackathon prototype). No auth, no scaling; tests on the core flows and the contracts only.
- Goal: flow 1 works end to end for the demo; flows 2 and 3 after it.
- Goal: data sources: local CSV upload, CSV in GCS, BigQuery (multiple tables). All of them land in
  BigQuery; joins and derived fields live in one active BigQuery view per accepted spec.
- Goal: 4 dashboard archetypes (executive, storytelling, operational, analytical) as skills.
- Goal (required, change 2026-10-19): reference images in style and recreate modes; recreate the
  closest supported structure and design using connected data, with explained substitutions.
- Goal (required): verify requests against native product evidence, app/engine coverage and data;
  reject unsupported behavior and clarify unknowns before promising, rendering or building it.
- Goal (required): screenshot-only builds can propose/edit a schema and generate a sample CSV
  with row count/seed using a reusable Python API/CLI; store under DSS_DATA_DIR (hosted GCS volume),
  load BigQuery and visibly label invented sample data in the UI and resulting dashboard.
- Goal: closed component catalog, 12 types: scorecard, time series, bar/column, pie/donut, table,
  pivot table, geo map, scatter, text, image, date range control, dropdown control.
- Goal: models through a Google API key (Gemini API): planner `gemini-4-argon`, worker
  `gemini-3.8-flash`; both editable in the UI settings.
- Goal: the harness of `harness-architecture.md`, built as: procedural memory = skill files,
  semantic memory = an OKF bundle (no vector store), episodic memory = SQLite + FTS5,
  consolidation after every 5 builds that reach `done` (worker model), one trace per run.
- Goal: deployed on Cloud Run (contracts/conventions.md, Cloud deployment): one service, one
  instance, shared access code, state on a GCS volume, secrets in Secret Manager, the engine run by
  a local build agent; deployed with one script (`bash deploy/deploy.sh`).
- Non-goal: auth, accounts, multi-user (POC, one local user).
- Non-goal: the engine in the cloud (headless Chrome with a stored Google session): the Google
  session stays on the user's machine; the build agent runs the engine there.
- Non-goal: more than one Cloud Run instance, autoscaling, a custom domain, IAP or per-user accounts.
- Non-goal: vector store or embeddings (OKF navigation replaces RAG).
- Non-goal: Data Studio blends or calculated fields built through the UI (SQL view instead).
- Non-goal: editing Data Studio reports the app didn't create.
- Non-goal: mobile layout for the app.
- Non-goal: CI, and tests beyond the core flows and the contracts.
- Non-goal: LangGraph (ADK 2.0 Workflow is the only orchestrator).

## Core flows (end to end)
1. **Build (must-have):** user uploads a CSV or picks GCS/BigQuery tables (frontend) -> intake
   loads it to BigQuery and profiles the schema (backend) -> interview through chat (frontend,
   backend) -> plan writes OKF build docs and the Dashboard Spec; render makes the HTML prototype
   (backend) -> user pins comments on prototype elements and applies them (frontend) -> revise
   patches the spec, re-render (backend) -> user clicks Build: backend compiles the recipe and
   runs `dsengine` (backend, engine) -> the light Chrome window shows the build; build events
   stream to the Build stage (engine, backend, frontend) -> the dashboard link shows (frontend).
2. **Research mode (stretch):** prompt -> capped web research (10-20 pages) -> cleaned CSV plus a
   sources file (backend) -> flow 1 from the interview.
3. **History:** open a past build from History (frontend) -> comment or chat edits -> re-run the
   recipe as a new dashboard version (backend, engine).
4. **Hosted (must-have after flow 1):** the user opens the Cloud Run URL and enters the access code
   (frontend, backend) -> flow 1 runs in the hosted app -> on Build, the backend queues a job ->
   `dss-agent` on the user's machine pulls it and runs `dsengine` with the signed-in Chrome (backend,
   engine) -> events stream back to the hosted Build stage -> the dashboard link shows.

## Contracts
| Contract | Version | Provider | Consumers | Conformance check |
|---|---|---|---|---|
| contracts/conventions.md | 1.1 | program | engine, backend, frontend, release | release: `uv run --project integration python integration/check_contracts.py` (the one root `.env.example` has every name); manual: each part's config reads these names, ports and paths |
| contracts/recipe.md | 1.0 | backend (recipe), engine (events) | engine, backend, release | engine: `uv run pytest tests/test_contract.py`; backend: `uv run pytest tests/test_recipe_contract.py` |
| contracts/api.md | 1.4 | backend | frontend, release | backend: `uv run pytest tests/test_api_contract.py`; frontend: `npm test -- contract`; both against contracts/fixtures/api/ |
| contracts/dashboard-intent.md | 1.1 | backend | frontend, release | backend: capability/reference/feasibility tests; frontend: contract and reference tests; release: task 3.3 |
| contracts/synthetic-data.md | 1.1 | backend | frontend, release | backend synthetic tests, frontend 11.1, release 3.3 |

## Delivery
- Targets: one GitHub repo (this folder; the user pushes) and one Cloud Run service `dss` in the
  user's GCP project (`bash deploy/deploy.sh`, after the user confirms; the user owns the billing).
- Start everything locally: `./start.ps1` (Windows) or `./start.sh`: backend on 8000, frontend on 5173.
- Hosted: the Cloud Run URL plus the access code; builds need `uv run --project backend dss-agent`
  running on the user's machine.
- Ships: all code, the planning docs (docs/, AGENTS.md, CLAUDE.md: they show the process), the
  submission deck `deck/AI-Builder-Cup-Submission.pptx` and `.pdf` (filled from the root
  `Submission Template _ AI Builder Cup.pptx`, which stays unchanged), README, MIT LICENSE, a sample
  CSV (e-commerce sales) as the guaranteed demo path. Never `.env`, `data/`, `.chrome-profile/`.
- CI: none.

## Roadmap
Re-planned 2026-10-19 (change 2026-10-19, revised by its delta audit). State then: engine 7/9
(4.2 in progress), frontend 10/11, backend 0 done (no code yet: the critical path), release 0/11.
Times are targets for 2026-10-19/20 (MPST). Backend runs in two sessions (A and B) on disjoint files.
1. 01:30-09:00: backend A 1.1-1.3, 3.1-3.3 (critical path); backend B, once 1.3 is done: 5.1
   (cloud mode), then 2.1; engine 4.2; frontend 5.1 (access gate, agent panel; against the
   fixtures); release 1.1, 1.2 (diagrams), 1.3 (deck draft).
   Gate: release 2.1 (start scripts) needs backend 1.1 and frontend 1.1.
2. 09:00-12:00: Gate: release 3.1 (Dockerfile, deploy; STOP before the first deploy) needs backend
   5.1 and frontend 5.1. The first hosted app reaches whatever the backend has; Build fails until 5.2.
3. 09:00-15:00: backend A 4.1-4.4. Gate: release 2.2 (dry-run e2e, flows 1 and 3) needs backend
   4.2, backend 4.4, engine 1.1; then release 2.3 (live e2e + UI walkthrough; needs engine 3.1,
   frontend 3.2).
4. 15:00-19:00: backend A 5.2 (agent server), 5.3 (`dss-agent`); backend B 6.1.
   Gate: release 3.2 (redeploy + deployed e2e through the local agent) needs backend 5.2, 5.3 and
   frontend 5.1.
5. 19:00-22:00: backend 6.2; release 4.1 (README), 4.2 (deck snapshots, benchmark, links; needs
   release 2.3 and 3.2, or its local-only path; STOP for team details).
6. 22:00-01:05: stretch in the cut order (backend 7.x, engine 4.3), release 4.3 (repo ready),
   rehearsal; submit by 00:45.
- Activity transparency (change 2026-10-19), first, before release 2.1: frontend 6.1 (activity strip and run checklist)
  now; backend 10.1 (`run.usage`) after backend's final-audit fixes 9.1-9.7 (it shares graph.py with
  9.6); no gate between them (frontend builds against `events.usage.sse`). Release 2.1-2.2 don't wait on them.
- Required scope change 2026-10-19 (task IDs per backend's split, change 2026-10-20): backend 9.7
  (done), backend 10.1, then backend 11.1-11.8 and 12.1-12.5; frontend 10.1 follows backend 11.8,
  then frontend 11.1 follows backend 12.3 (synthetic API complete; the backend prototype label
  from 12.5 is checked in release 3.3 if 12.5 lands later); release 3.3 follows backend 11.8,
  12.4, 12.5 and frontend 11.1, i.e. all required feature work. These take precedence
  over further stretch expansion; existing release infrastructure can continue.
  Images and feasibility cannot be silently cut. If these gates threaten the deadline, report
  the conflict for the user's scope decision. Earlier clock slots are historical targets.
- Cut order if behind: activity transparency (frontend 6.1, backend 10.1; release is unaffected),
  research mode (backend 7.3), screencast (engine 4.3), UX audit (backend 7.1 audit half),
  eval script (backend 7.2), history re-edit, consolidation (backend 6.2),
  episodic depth (backend 6.1), then the agent client (backend 5.3). Without 5.3 the hosted app
  runs in agent mode with no agent: Build shows the offline panel, the live build is shown from
  the local app, and the deck takes release 4.2's local-only path. Backend 5.2 is the minimum for
  that fallback; Cloud Run without the engine can't build in local mode.
- If engine chart ops slip: set `DSS_ALLOWED_TYPES` to the types the engine passes; the spec node
  and validator then only use those.
- Must survive: reference style/recreation and feasibility rejection (release 3.3), plus CSV -> interview -> prototype -> one comment edit -> recipe -> live build -> link
  (locally), and the same flow at the Cloud Run URL at least to the recipe.

## Integration checks
- `uv run --project integration python integration/check_contracts.py`: the recipe and event
  fixtures validate against contracts/recipe.schema.json; every env name is in `.env.example`.
- `uv run --project integration python integration/e2e_flow1.py --version2`: with `./start.sh`
  running and `DSS_ENGINE_DRY_RUN=1`, the sample CSV and a scripted interview reach stage `done`
  (flow 1), then a second version reaches `done` (flow 3).
- `uv run --project integration python integration/e2e_flow1.py --live`: same, with the real
  engine and the signed-in Chrome profile; prints a `https://datastudio.google.com/` link.
- `uv run --project integration python integration/e2e_flow1.py --server <Cloud Run URL> --live`:
  with `dss-agent` running locally, flow 1 at the deployed service (access code from `.env`) prints
  a `https://datastudio.google.com/` link; with `dss-agent --dry-run` the same run reaches `done`
  without touching Data Studio.

- Required image/capability acceptance: release 3.3 runs `integration/e2e_references.py --live`
  locally and with `--server <Cloud Run URL>`; scenario oracle is dashboard-intent.md.

## Research facts (2026-10-18)
- Data Studio API (`datastudio.googleapis.com/v1`) only searches assets and manages permissions:
  no method creates reports, pages, charts or layout. Source:
  https://developers.google.com/looker-studio/integrate/api/reference
- Linking API: `https://datastudio.google.com/reporting/create?c.reportId=...&c.mode=edit&r.reportName=...&ds.<alias>.connector=...`
  opens a report (blank or from a template) with data sources replaced. Connectors: bigQuery
  (TABLE or CUSTOM_QUERY), googleSheets, googleCloudStorage (CSV file or folder), cloudSpanner,
  googleAnalytics, community. Saving needs the user's "Edit and share" click. No local files.
  Source: https://developers.google.com/looker-studio/integrate/linking-api
- So charts, sizes and positions have to go through browser automation of the Data Studio UI.
- "Google OFK" = Google Open Knowledge Format (OKF) v0.1, 2026-06-12: a folder of markdown files,
  one concept per file, YAML frontmatter (`type` required; `title`, `description`, `resource`,
  `tags`, `timestamp` recommended), reserved `index.md` (folder listing) and `log.md` (newest-first
  history). Repo: GoogleCloudPlatform/knowledge-catalog (`okf/SPEC.md`).
- Google ADK 2.0 (Python) runs graph workflows: `Workflow(edges=[...])`; nodes are functions,
  LlmAgents, tools or human input; routers, fan-out, conditional loops. Sources:
  https://adk.dev/2.0/ , https://adk.dev/graphs/routes/index.md
- `gemini-3.8-flash` is a GA model ID (ai.google.dev). `gemini-4-argon` is the user's ID for Argon.
- Risk (engine spike checks it): Google sign-in is often refused in browsers launched with
  automation flags; the fix is a normally launched Chrome with a dedicated profile that Playwright
  attaches to over CDP.
- User reference: `harness-architecture.md` (harness, three memory types, LLM Ops loop).

## Open questions
- none

## Decision log
| Date | Decision | Alternatives | Why | Source |
|---|---|---|---|---|
| 2026-10-18 | Target POC | MVP | hackathon demo, security and scale later | program |
| 2026-10-18 | A program, grilled at the root only; all part docs written in the same session | grill each part in its own sessions | 10-hour deadline | program |
| 2026-10-18 | Parts engine/, backend/, frontend/, root release | one project; frontend+backend only | engine is the riskiest piece and testable alone; three builders in parallel | program |
| 2026-10-18 | Python 3.12 + uv, FastAPI, google-adk 2.x Workflow, google-genai, Playwright; Vite + React + TS + Tailwind + ECharts | LangGraph; Next.js | GCP judging favours ADK; one orchestrator | program |
| 2026-10-18 | Dashboard Spec JSON is the single source of truth; HTML, background PNG and recipe are deterministic code | LLM writes HTML and recipe | token cost, determinism, small comment patches | program |
| 2026-10-18 | Every source lands in BigQuery; one view per build holds joins and derived fields; Linking API attaches the view as a table | Data Studio blends and calculated fields; SQL in the URL | the UI's most fragile clicks disappear; a view avoids URL length limits | program |
| 2026-10-18 | No LLM vision in the engine's normal path; selectors live in OKF | agent looks at the screen | token budget | program |
| 2026-10-18 | Live view: headed Chrome `--app` window; CDP screencast is a stretch | screencast only | free with the headed window; screencast is what Cloud Run will need | program |
| 2026-10-18 | No vector store: semantic = OKF, episodic = SQLite + FTS5 | harness doc's vector stores | user constraint: OKF instead of RAG | program |
| 2026-10-18 | Backend runs the engine as a subprocess (`dsengine run`), events as JSONL on stdout | import as a library | keeps the parts independent; the recipe is a real CLI script | program (user confirmed) |
| 2026-10-18 | Frontend look: Studio Light; skills frontend-design, ui-ux-pro-max, web-design-guidelines | Dark Ops Console; Warm Editorial | matches Data Studio; dense workspace | program |
| 2026-10-18 | Folder mode while building; release 4.3 runs `git init` | one git repo from the start | three parallel builders would race on one git index | program |
| 2026-10-18 | Only one part has a UI, so no contracts/design.md; the UI design lives in frontend's essentials | shared design contract | single UI part | program |
| 2026-10-19 | Deadline moved to 2026-10-20 01:05 MPST; Cloud Run lifted from non-goal to goal | keep local-only, Cloud Run next version | user request | change 2026-10-19 |
| 2026-10-19 | One Cloud Run service (backend serves the built frontend), one instance, CPU always allocated | separate frontend service; autoscaling | same origin keeps relative `/api`, the cookie and the iframe working; SQLite and the engine lock need one instance; runs continue after `202` | change 2026-10-19 |
| 2026-10-19 | Engine stays local: a build agent (`dss-agent`, in backend) pulls jobs from the hosted API | headless engine on Cloud Run with a stored Google session | no Google cookies in the cloud; Data Studio has no create API | change 2026-10-19 (user choice) |
| 2026-10-19 | Shared access code (`DSS_ACCESS_CODE`, cookie for the browser, header for the agent) | IAP allowlist; fully public | judges get the code; protects Gemini/BigQuery spend and the build queue | change 2026-10-19 (user choice) |
| 2026-10-19 | State on a GCS volume at `/data`; SQLite on local disk with a backup-API copy to the volume | SQLite directly on gcsfuse; Firestore/Cloud SQL | user chose the GCS volume; gcsfuse has no file locking, so the live DB stays on local disk | change 2026-10-19 (user choice + architect) |
| 2026-10-19 | Submission deck = the AI Builder Cup template filled by `deck/build_deck.ps1` (PowerPoint COM), diagrams as HTML rendered to PNG by headless Chrome, plus a PDF | PRESENTATION.md; python-pptx | the cup requires its template; no new dependency; PowerPoint and Chrome are on the machine | change 2026-10-19 (user choice) |
| 2026-10-19 | Delta audit of the change: 33 findings, all applied (agent paths and `--dry-run`, SA roles, `.gcloudignore`, DB backup every 30 s, Secure cookie, agent token, settings lock, path guards, fail-closed start, backend 5.1 in parallel after 1.3, agent split into 5.2/5.3, local-only deck path, bench JSON, COM rules) | - | reviewer audit | change 2026-10-19 |
| 2026-10-19 | The hosted app is shared by everyone with the code (one history, one engine lock) and builds only while the owner's agent is online | per-user sessions; hosted engine | POC with one owner; judges are told in README and on the links slide | change 2026-10-19 (audit) |
| 2026-10-19 | Activity transparency: a pinned strip in the chat column (preset phrase, elapsed, live tokens) and a preset step checklist per run; contracts/api.md 1.2 adds `run.usage` (running token totals per run) and lists the `node` values | frontend only (tokens after the run from /api/traces); rotating phrase without checklist; strip in the stage area | the user sees the agent working; real token counts cost one emit where tokens are already summed; presets need no backend detail | change 2026-10-19 (user choice) |
| 2026-10-19 | `run.usage` example in a new fixture `events.usage.sse`; `events.sse` unchanged | add it to events.sse | the frontend validates events.sse at app load, so a new event there would break the app until frontend 6.1 lands | change 2026-10-19 (architect) |
| 2026-10-18 | Plan audit: 18 findings, all applied (backend thin slice, engine must-have ops, DSS_ALLOWED_TYPES fallback, shared API fixtures, no --reload on Windows, model check, gates in the roadmap, recipe ops with ids, background_p<n>.png, view reuse, ready_for_plan tool, deps, edge cases, stage areas, renderer budget, flow 3 e2e, trims) | - | reviewer audit | program |

| 2026-10-19 | Images: closest supported recreation plus style; both image references and capability checks required | style only; recreation later | user explicitly selected both required and closest supported recreation | change 2026-10-19 reference/capability audit |

| 2026-10-19 | Screenshot-only synthetic data: schema/count/seed Python generator plus API; local directory or existing GCS volume | require CSV; LLM writes bulk rows; new bucket/client | user explicitly requests fake CSV generation when original data is unavailable | change synthetic-data 2026-10-19 |
| 2026-10-20 | Deadline moved to 2026-10-23 01:05 MPST | keep 2026-10-20 01:05 | user request (exact time confirmed) | change 2026-10-20 |
| 2026-10-20 | Cross-part gates follow backend's task split: frontend 10.1 needs backend 11.8, frontend 11.1 needs backend 12.3, release 3.3 needs backend 11.8, 12.4, 12.5 and frontend 11.1 | frontend 11.1 waits for backend 12.5 | frontend starts as soon as the synthetic API is complete; release 3.3 already checks the backend label | change 2026-10-20 (user choice) |
| 2026-10-20 | synthetic-data.md 1.1: generation table plus immediate best-effort DB backups after reservation and after registration; startup fails in-flight jobs and cleans their own artifacts; replay stays idempotent | immutable manifests + startup reconciliation; fail-closed 503 on backup failure | same guarantee for the POC with the existing backup path, no new files or error code | change 2026-10-20 (user choice; backend audit finding 4) |
