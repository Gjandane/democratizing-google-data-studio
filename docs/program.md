# Program: Democratizing Google Data Studio
An agentic app that drafts a business context from the user's data, lets the user pick the
questions and the design, maps them to a feasible technical blueprint, renders an HTML prototype,
and builds the real dashboard in Data Studio from a compiled recipe. GCP hackathon entry, local first.
Written 2026-10-18.

## Problem and users
- Problem: building a Data Studio dashboard takes hours of clicking plus design skill; people who
  know their data (analysts, managers, students) can't turn their questions into a good dashboard.
- Local user (one, no accounts): connects data or describes a topic, confirms a drafted
  context, picks questions and a design, accepts a blueprint, comments on a prototype, and gets a real Data Studio dashboard link.
- Context: Google GCP hackathon (AI Builder Cup). Deadline: no longer binding; the user keeps the full
  scope past 2026-10-23 01:05 MPST (change 2026-10-23; earlier 2026-10-20 and 2026-10-19 01:05).
- Hosted on Cloud Run in this version (change 2026-10-19): the app runs as one Cloud Run service
  as an open link: anyone with the URL gets in, no sign-in (change 2026-10-29 open hosted link, conventions 1.6; Google sign-in stays in the code for a later lock-down). Change 2026-10-29 cloud engine
  (conventions 1.7): the hosted Data Studio build runs inside the container as a dedicated demo
  Google account (its session exported once on the owner's machine); each report is shared as
  "anyone with the link can edit", so visitors download nothing and open the result in their own
  Data Studio session. The build agent stays for the owner's machine and as the rollback (hosted
  then stops at the recipe).

## Parts
| Part | Folder | Purpose | Target | Provides | Consumes |
|---|---|---|---|---|---|
| engine | engine/ | `dsengine` CLI: runs a recipe in Data Studio through Playwright on a signed-in Chrome profile; streams one event per op | POC | contracts/recipe.md (events half) | contracts/recipe.md, contracts/conventions.md |
| backend | backend/ | the harness: ADK 2.0 graph, three memory types, Gemini calls, data intake to BigQuery, spec, HTML renderer, recipe compiler, REST + SSE API; cloud mode (static frontend, access code, DB backup) and the build agent (`dss-agent`) | POC | contracts/api.md, contracts/recipe.md (recipe half) | contracts/conventions.md, contracts/recipe.md (events half) |
| frontend | frontend/ | the web app: history, workspace with stage stepper, chat, click-to-comment prototype, build view, settings, trace tab; access-code gate and build-agent status | POC | - | contracts/api.md, contracts/dashboard-intent.md, contracts/synthetic-data.md, contracts/conventions.md |
| release | . | end-to-end flow checks (local and deployed), start scripts, Dockerfile and Cloud Run deploy script, README, `.env.example`, LICENSE, the AI Builder Cup submission deck (pptx + pdf, HTML-rendered diagrams) | POC | - | every contract |

## Goals and non-goals
- Target: POC (hackathon prototype). No auth, no scaling; tests on the core flows and the contracts only.
- Goal: flow 1 works end to end for the demo; flows 2 and 3 after it.
- Goal (change staged workflow 2026-10-21): a staged workflow, connect -> context -> outline ->
  design -> blueprint -> prototype -> build. Each stage writes one OKF artifact (context.md,
  outline.md, design.md, blueprint.md) that the user confirms. Code computes profiles, validates
  and writes every file; a model gets compact profiles and upstream artifacts, never data rows
  or the chat history, and fills only judgment fields. The outline is picked from suggested
  questions (Recommended flags, Other, suggest more); design from design-time theme presets;
  pages single or one per outline section. Replaces the free-text interview and the plan action.
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
  instance, an open link (`DSS_PUBLIC=1`; change 2026-10-29) through 2026-11-07, state on a GCS volume, secrets in Secret Manager, the engine
  in the container as the demo account with BigQuery and GCS sources locked (change 2026-10-29 cloud engine); deployed with one script (`bash deploy/deploy.sh`).
- Non-goal: per-user accounts, roles or data isolation (POC): every visitor of the open link
  shares the one history (change 2026-10-29).
- Non-goal: automated Google sign-in, signing in as a visitor, or a cloud browser for the owner's
  own account. Lifted in part (change 2026-10-29 cloud engine): the engine runs on Cloud Run,
  headful under Xvfb, as a dedicated demo account whose session is exported by hand.
- Non-goal: more than one Cloud Run instance, autoscaling, a custom domain, IAP or per-user accounts.
- Non-goal: vector store or embeddings (OKF navigation replaces RAG).
- Non-goal: Data Studio blends or calculated fields built through the UI (SQL view instead).
- Non-goal: editing Data Studio reports the app didn't create.
- Non-goal: mobile layout for the app.
- Non-goal: CI, and tests beyond the core flows and the contracts.
- Non-goal: LangGraph (ADK 2.0 Workflow is the only orchestrator).

## Core flows (end to end)
1. **Build (must-have):** user uploads a CSV or picks GCS/BigQuery tables (frontend) -> intake
   loads it to BigQuery and profiles the schema (backend) -> the user adds notes about the data;
   context drafts KPI definitions, derived fields and thresholds; the user edits and confirms
   them (frontend, backend) -> outline proposes sections and questions; the user ticks them, adds
   Other text, confirms -> the user picks a theme preset and page structure -> blueprint maps
   each question to a chart and fields, code checks feasibility and dry-runs the view; the user
   resolves blocked rows and accepts -> code lays out the spec and renders the HTML prototype
   (backend) -> user pins comments on prototype elements and applies them (frontend) -> revise
   patches the spec, re-render (backend) -> user clicks Build: backend compiles the recipe and
   runs `dsengine` (backend, engine) -> the light Chrome window shows the build; build events
   stream to the Build stage (engine, backend, frontend) -> the dashboard link shows (frontend).
2. **Research mode (stretch):** prompt -> capped web research (10-20 pages) -> cleaned CSV plus a
   sources file (backend) -> flow 1 from the context step.
3. **History:** open a past build from History (frontend) -> comment edits -> re-run the
   recipe as a new dashboard version (backend, engine).
4. **Hosted (must-have after flow 1):** a visitor opens the Cloud Run URL (open link, no sign-in;
   frontend, backend) -> flow 1 runs in the hosted app with CSV upload, research or screenshot +
   synthetic data (BigQuery and GCS locked) -> on Build, the backend runs `dsengine` in the
   container as the demo account (backend, engine) -> events stream to the Build stage -> the
   report is shared "anyone with the link can edit" and the link shows; the visitor opens it in
   their own Data Studio session (change 2026-10-29 cloud engine).

## Contracts
| Contract | Version | Provider | Consumers | Conformance check |
|---|---|---|---|---|
| contracts/conventions.md | 1.7 | program | engine, backend, frontend, release | release: `uv run --project integration python integration/check_contracts.py` (the one root `.env.example` has every name); manual: each part's config reads these names, ports and paths |
| contracts/recipe.md | 1.4 | backend (recipe), engine (events) | engine, backend, release | engine: `uv run pytest tests/test_contract.py`; backend: `uv run pytest tests/test_recipe_contract.py` |
| contracts/api.md | 3.4 | backend | frontend, release | backend: `uv run pytest tests/test_api_contract.py`; frontend: `npm test -- contract`; both against contracts/fixtures/api/ and, from backend 25.1 / frontend 16.1, contracts/fixtures/stage-settings/ |
| contracts/dashboard-intent.md | 1.3 | backend | frontend, release | backend: capability/reference/feasibility tests; frontend: contract and reference tests; release: tasks 2.5 and 4.4 |
| contracts/synthetic-data.md | 1.3 | backend | frontend, release | backend synthetic tests, frontend 11.1-11.2, release 2.5, 2.6 and 4.4 |

## Delivery
- Targets: one GitHub repo, https://github.com/Gjandane/democratizing-google-data-studio (this
  folder, branch `main`; the release builder pushes only after the user confirms on a card, change
  2026-10-20 final phases), and one Cloud Run service `dss-frontend` in the user's GCP project,
  region asia-southeast1, URL in .env as `DSS_AGENT_SERVER`, never in the repo (the URL
  already submitted; `bash deploy/deploy.sh`, after the user confirms; the user owns the billing).
- Final order (change 2026-10-20 final phases): local integration and the user's manual acceptance
  of five dashboard sources (CSV upload, research mode, screenshot + synthetic data, BigQuery,
  GCS) -> README and the first GitHub push -> Cloud Run deploy and hosted acceptance -> final push.
- Start everything locally: `./start.ps1` (Windows) or `./start.sh`: backend on 8000, frontend on 5173.
- Hosted: the Cloud Run URL, open to anyone with the link (no sign-in, change 2026-10-29) through
  2026-11-07, then closed by hand (deploy/README.md); builds run in the container as the demo
  account and the report link opens with edit access for the visitor (change 2026-10-29 cloud engine).
- Ships: all code, the planning docs (docs/, AGENTS.md, CLAUDE.md: they show the process), the
  submission deck draft `deck/AI-Builder-Cup-Submission.pptx` and `.pdf` as built by release 1.3
  (no further deck work: change 2026-10-20 final phases), README (pitch, features, capabilities,
  simplified architecture), MIT LICENSE, a sample CSV (e-commerce sales) as the guaranteed demo
  path. Never `.env`, `data/`, `.chrome-profile/`; every `.env.example` has names only.
- CI: none.

## Roadmap
Current priority (change staged workflow 2026-10-21): the staged workflow (contracts/api.md 2.0)
replaces the interview and plan. Order: backend 15.1-15.11 in backend/ (15.5 has a STOP for the
user's approval of the theme kit); frontend 14.1-14.5 in frontend/ in parallel, against the 2.0
fixtures (no gate until frontend 14.5's live check); then release 2.3 at this root, gated on
backend 15.11, frontend 14.5 and engine 6.1, and the later release tasks in their order. The user
put this workflow ahead of the deadline (2026-10-21): the deadline stays, but it no longer cuts
this scope; when it nears, report the state and let the user decide on a card.

Re-planned 2026-10-19 (change 2026-10-19, revised by its delta audit). State then: engine 7/9
(4.2 in progress), frontend 10/11, backend 0 done (no code yet: the critical path), release 0/11.
Times are targets for 2026-10-19/20 (MPST). Backend runs in two sessions (A and B) on disjoint files.
Release task IDs in items 1-6 are the pre-2026-10-20 numbering; the current order is "Final
phases" below.
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
  (done), backend 10.1, then backend 11.1-11.8 and 12.1-12.5; frontend 10.1-10.3 follow backend
  11.8, then frontend 11.1-11.2 follow backend 12.3 (synthetic API complete; the backend prototype
  label from 12.5 is checked in release 2.5 if 12.5 lands later); release 2.5 follows backend 11.8,
  12.4, 12.5 and frontend 10.3, 11.2 (frontend split 10.1 and 11.1, change 2026-10-20 frontend
  split), i.e. all required feature work. These take precedence
  over further stretch expansion; existing release infrastructure can continue.
  Images and feasibility cannot be silently cut. If these gates threaten the deadline, report
  the conflict for the user's scope decision. Earlier clock slots are historical targets.
- Cut order if behind: activity transparency (frontend 6.1, backend 10.1; release is unaffected),
  research mode (backend 7.3), screencast (engine 4.3), UX audit (backend 7.1 audit half),
  eval script (backend 7.2), history re-edit, consolidation (backend 6.2),
  episodic depth (backend 6.1), then the agent client (backend 5.3). Without 5.3 the hosted app
  runs in agent mode with no agent: Build shows the offline panel, the live build is shown from
  the local app. Backend 5.2 is the minimum for
  that fallback; Cloud Run without the engine can't build in local mode.
- If engine chart ops slip: set `DSS_ALLOWED_TYPES` to the types the engine passes; the spec node
  and validator then only use those.
- Must survive: reference style/recreation and feasibility rejection (release 2.5 and 4.3), plus CSV -> context -> outline -> design -> blueprint -> prototype -> one comment edit -> recipe
  -> live build -> link
  (locally), and the same flow at the Cloud Run URL at least to the recipe.
- Final phases (change 2026-10-20 final phases), once backend 12.5 and frontend 10.3 and 11.2 are done
  (engine is done):
  1. Local: release 2.1 start scripts, 2.2 dry-run e2e, 2.3 live e2e and 2.4 the user's manual
     acceptance of CSV, research, BigQuery and GCS (STOP) need no further part work; 2.5
     reference/synthetic e2e waits on backend 12.5 and frontend 10.3 and 11.2; 2.6 the user's manual
     screenshot + synthetic acceptance (STOP) follows it.
  2. GitHub: release 3.1 README, 3.2 repo ready and first push (STOP before the push).
  3. Cloud Run: release 4.1 Dockerfile and deploy to `dss-frontend` (STOP before the deploy),
     4.2 hosted e2e through the local agent, 4.3 hosted reference/synthetic acceptance, 4.4
     README hosted section and final push (STOP before the push).
  If the deadline nears with Cloud Run unfinished, the repo from 3.2 is already the working
  version: report it and let the user decide; never skip 2.4 or 2.6 to reach the deploy. If 2.5 or 2.6 is
  blocked near the deadline, the user decides on a card (change flow) whether to push with the
  screenshot feature tagged "planned"; never silently.
- Manual acceptance fixes (change 2026-10-22): release 2.4 waits on engine 10.1 and backend 17.1 (`Needs:`), then reruns rows 2-3 only. Engine 10.1 first (it holds the signed-in Chrome); backend 17.1 is offline and can run alongside; release 2.5 (live, Chrome) after engine 10.1.
- Reference recovery (change 2026-10-22, user chose both fixes): backend 17.1 -> 18.1 (validated replan freshness) -> 18.2 (recreate definition reconciliation), then release 2.5 reruns all five live cases, restart persistence and its comparison STOP. Release 2.5 waits on both tasks; release 4.3 retains the same hosted acceptance via its existing dependency on 2.5. No observation drops or relaxed recreation claim; no interface change. Release 2.6 remains independently ready after 2.3.
- Report quality (change 2026-10-22, user chose all four fixes): engine 11.1 (scorecard value size, STOP) -> 11.2 (`rename_page`, recipe 1.1) -> 11.3 (palette colors) in engine/ (one signed-in Chrome, so one at a time and not alongside release 2.5's live runs); backend 19.1 (HD backgrounds, STOP) needs no gate and can run first; backend 19.2 (page 1 name, no scorecard palette op) `Needs: engine 11.2`. No release task waits on them: release 2.5 stays the critical path; release 2.6's acceptance screenshots and README images (3.1) show the fixes only if these land first. Cut first if behind: 11.3, then 19.2 + 11.2.
- Recreate publication (change 2026-10-23, user choice): backend 21.1 (coverage errors in the publish span; recreate and screenshot-only accepts publish with designed pages) -> release 2.5 reruns the full five-case `--live` suite, `--after-restart` and its comparison STOP; then 2.6, 3.x, 4.x in order. No contract change.
- Live report defects (change 2026-10-23, from release 2.5's approved comparison): engine 12.1 (`date_granularity`, recipe 1.2; signed-in Chrome, so not alongside release live runs) and backend 23.1 (emits it for date buckets) -> 23.2 (one synthetic label, from the background) in parallel (backend is offline); release 2.6 waits on all three (`Needs:`), then release 2.7 updates the e2e synthetic label check before 4.3 reuses it.
- Reference fidelity (change 2026-10-24, from release 2.6's block and the user's audit): engine 13.1 (breakdown series colors) -> 13.2 (area, 100% stacked bar) -> 13.3 (fixed-size list), signed-in Chrome, not alongside release live runs; backend 24.1 (recipe 1.3 types; first, it repairs test_capabilities) -> 24.2 (base DATE grain) -> 24.3 (comment check limits) -> 24.4 (globe art) -> 24.5 (designer sees the reference, STOP), offline except the live checks; frontend 15.1 (labels) any time; release 2.6 reruns after all, then 2.7.
- Configurable model stages (change 2026-10-26, user interview closed after 30 answers; api.md 3.0, conventions.md 1.4): backend 24.11 (recomputation budget, offline) -> 25.1 (stage settings API) -> 25.2 (stage execution, L) -> 25.3 (fallback, stage calls) -> 25.4 (uncapped briefs, brief artifacts) -> 25.5 (no-reference Argon brief -> Flash HTML, labeled standard layout) -> 25.6 (brief review gate) -> 25.7 (live fidelity, visual STOP) in backend/; frontend 16.1 (3.0 types, mocks) -> 16.2 (stage settings editor) -> 16.3 (brief panel, Standard layout chip) -> 16.4 (brief review gate) -> 16.5 (stage calls, stage-limit errors) against the stage-settings fixtures, in parallel with backend; frontend 16.6 (live walkthrough) `Needs: backend 25.6`. Release 2.6 now also needs backend 25.7 and frontend 16.6; release 2.8 (e2e waits from the stage clocks, stage-settings fixture check) `Needs: backend 25.1` and comes before 4.2/4.3. Once backend 25.1 and frontend 16.1 are done, the architect removes contracts/fixtures/api/settings.json (2.0 Settings).
- Native planning defaults (change 2026-10-27, backend 25.7 block, user cards; api.md 3.1, no shape change): backend 25.7 (defaults) -> 25.8 (live fidelity, visual STOP) in backend/; release 2.6 `Needs: backend 25.8`. Frontend and release 2.8 read the defaults from the API: no task.
- Reference analysis gate (change 2026-10-28, backend 25.11 block, user request and cards; api.md 3.2, dashboard-intent.md 1.3, synthetic-data.md 1.3): backend 26.1 (3.2 shapes and defaults) -> 26.2 (Flash reference analysis) -> 26.3 (approval gate API) -> 26.4 (Argon planning and brief from the image + approved items) -> 26.5 (observation path removed) -> 26.6 (live acceptance, visual STOP; replaces 25.11) in backend/; frontend 17.1 (1.3/3.2 types, mocks) -> 17.2 (analysis review on the reference panel) against the fixtures, in parallel with backend; frontend 17.3 (live walkthrough) `Needs: backend 26.4`. Release 2.6 now needs backend 26.6 and frontend 17.3 (instead of backend 25.8) and goes through the gate.
- Acceptance with findings (change 2026-10-29, release 2.6, user): 2.6 is accepted as PASS with findings (engine `partial`, 16 of 49 ops failed; weaknesses W1-W7 in docs/acceptance.md) and reopened only for check_contracts' ReferenceSet shape (dashboard-intent 1.3). No part tasks: W1-W7 go to the owner parts' PRD Later lists for a later version. Next: release 2.6 (close), 2.7, 2.8, 3.1, 3.2 (push), 4.1 (deploy), 4.2-4.4; 4.3 passes on a hosted `partial` only when its failures match W1-W7.
- Release upkeep deferred (change 2026-10-29, user cards): release 2.7 and 2.8 (e2e driver upkeep, no
  app code) go to release PRD Later; 4.1 is next, 4.2 and 4.3 no longer wait on them and carry the
  bench URL mask themselves; 4.3 reads a `stale` synthetic GPS refusal with unresolved issues as a
  refusal. Backend returning `blocked` there is a later backend item. Next: 4.1 (deploy), 4.2-4.4.

- Cloud engine (change 2026-10-29, user cards; conventions 1.7, api 3.4, recipe 1.4): release 4.1
  (agent-mode deploy, in progress) first; engine 14.1 (session export/import; STOP: the user creates
  the demo Gmail account, signs its profile in by hand, grants it BigQuery) -> release 4.2 (Cloud
  Run job spike, STOP go/no-go). In parallel, offline: backend 29.1 (cloud mode) -> 29.2
  (`share_report`, locked sources; `Needs: engine 14.2`), frontend 19.1 (cloud Build panel, locked
  sources), engine 14.2 (`share_report`, live in the demo profile) after 14.1. Then release 4.3
  (cloud deploy + hosted live e2e; needs all of them), 4.4 (hosted acceptance), 4.5 (README, push).
  No-go at 4.2 -> the user's fallback: hosted stops at the recipe on the 4.1 revision; the
  architect removes 4.3's cloud steps and the parts' cloud-engine tasks, keeping 29.2's source
  lock (every open deploy sets it). The service scales to zero (user 2026-10-29), 4.1 included. Engine tasks share the one
  signed-in Chrome with release live runs: never at the same time.

## Integration checks
- `uv run --project integration python integration/check_contracts.py`: the recipe and event
  fixtures validate against contracts/recipe.schema.json; every env name is in `.env.example`.
- `uv run --project integration python integration/e2e_flow1.py --version2`: with `./start.sh`
  running and `DSS_ENGINE_DRY_RUN=1`, the sample CSV and scripted artifact picks (api.md 2.0) reach stage `done`
  (flow 1), then a second version reaches `done` (flow 3).
- `uv run --project integration python integration/e2e_flow1.py --live`: same, with the real
  engine and the signed-in Chrome profile; prints a `https://datastudio.google.com/` link.
- `uv run --project integration python integration/e2e_flow1.py --server <Cloud Run URL> --live`:
  flow 1 at the deployed open service builds live with the cloud engine to a Data Studio link that
  another Google account opens with edit access (release 4.3, change 2026-10-29 cloud engine).

- Manual acceptance (release 2.4 and 2.6): the user builds one dashboard per source through the local UI
  (CSV upload, research mode, screenshot + synthetic data, BigQuery table, CSV in GCS); each row in
  docs/acceptance.md has a Data Studio link and the user's PASS.
- Required image/capability acceptance: release 2.5 (local) and 4.4 (hosted) run `integration/e2e_references.py`, `--live`
  locally and `--server <Cloud Run URL> --live` hosted (change 2026-10-29 cloud engine); scenario oracle is dashboard-intent.md.

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
| 2026-10-20 | Final phases re-sequenced: local integration + manual acceptance of five sources -> README + GitHub push -> Cloud Run -> final push; release 3.3 split into local (2.5) and hosted (4.3) | old order (Cloud Run before README/repo) | user's order: test locally first, publish the working version, deploy last | change 2026-10-20 final phases (user choice) |
| 2026-10-20 | Deploy the full image as service `dss-frontend` (conventions.md 1.2), replacing its static-frontend revision | new service `dss` with a new URL | keeps the already-submitted URL; same origin as before | change 2026-10-20 final phases (user choice) |
| 2026-10-20 | The release builder pushes to origin main after the user confirms on a card | the user pushes | user choice; history is checked for secrets first | change 2026-10-20 final phases (user choice) |
| 2026-10-20 | No further deck work: the 1.3 draft ships; README is the judge-facing document | finish deck with screenshots and benchmark | already submitted; user choice | change 2026-10-20 final phases (user choice) |
| 2026-10-20 | GCS joins the four manual acceptance sources | four sources only | README claims GCS; every claimed source gets a tested row | change 2026-10-20 final phases (user choice) |
| 2026-10-20 | Release 2.5 gates on frontend 10.3 and 11.2, the last tasks of frontend's split of 10.1 (10.1-10.3) and 11.1 (11.1-11.2); api.md 1.5 (consistency: cross-refs, complete `node` list); example fixtures for SyntheticDataset, a succeeded GenerationStatus and Assessment alternatives/pending/stale (dashboard-intent and synthetic-data keep 1.1, shapes unchanged); frontend consumes dashboard-intent and synthetic-data | keep the old gates; bump dashboard-intent and synthetic-data too | the old gates let release 2.5 start before frontend finishes; consumers test against shared fixtures instead of overrides; no shape changed, so no part rework | change 2026-10-20 frontend split (frontend delta audit) |
| 2026-10-21 | Backend 14.1 repairs audience-context classification and interview clarification; release 2.2 waits, then recovers its saved driver | alter demo wording to evade feasibility; defer all checks until three answers | ordinary sales-audience context and incomplete metrics stopped the core flow; existing contract already requires clarification with readiness gated | change interview feasibility recovery |
| 2026-10-21 | Backend 14.2 repairs coordinated formulas, forward reuse of confirmed definitions and supported blue styling; release 2.2 waits, then restores the 02:11 stash | change the release wording; drop unresolved requirements | 14.1 passed different wording, but release's explicit formulas and theme still block planning; one core-flow repair, no new feature or contract | change conversational definitions and styling |
| 2026-10-21 | Staged workflow replaces the free-text interview and plan: context -> outline -> design -> blueprint, each a confirmed OKF artifact; api.md 2.0 (breaking), dashboard-intent.md 1.2, synthetic-data.md 1.2 | keep the interview and patch its extraction (14.1, 14.2 pattern); keep both paths as a quick mode | per-turn requirement extraction from chat was the repeated failure (14.1, 14.2, release 2.3 `llm_unavailable`); ticked choices are structured and need no extraction; each artifact is a checkpoint, so a failed step reruns alone | change staged workflow (user choice) |
| 2026-10-21 | Code computes, the model judges, code writes files: profiles by a reusable Python script; models get compact profiles and upstream artifacts only, never rows or chat history; the spec is laid out by code from blueprint + design (no spec model node) | model writes OKF docs and the spec | smaller, cacheable prompts and deterministic files; user asked that the model get only enough context | change staged workflow (user choice) |
| 2026-10-21 | Artifacts are OKF markdown with the structured data in YAML frontmatter, validated by pydantic; readable body for the UI | pure YAML; markdown only | matches the existing build-docs convention; code can validate it | change staged workflow (user choice) |
| 2026-10-21 | Business facts come from an optional notes box at connect; the context model drafts KPI definitions, derived fields and thresholds; the user edits KPI cards and confirms | document upload; profile-only draft | definitions settled once, up front, instead of mid-chat | change staged workflow (user choice) |
| 2026-10-21 | Outline: one proposal call (sections, questions, Recommended flags); the user ticks, adds Other text (one normalize call) or asks to suggest more for a section | section-by-section rounds | fewest model calls | change staged workflow (user choice) |
| 2026-10-21 | Polished look from design-time theme presets and a decoration kit per archetype, crafted once with the frontend-design/ui-ux-pro-max skills; the runtime renderer stays deterministic and the background PNG carries the look into Data Studio | model writes HTML per build | the prototype keeps mirroring what the recipe can build | change staged workflow (user choice) |
| 2026-10-21 | Pages: the user picks single or one per outline section (default per section, at most 5), all on one view | always per section; single page only | the recipe already has add_page/go_to_page | change staged workflow (user choice) |
| 2026-10-21 | Unjoinable sources stay one view: feasibility flags them and offers one dataset or a UNION into a long table | a page per source with its own view | no spec, recipe or engine change | change staged workflow (user choice) |
| 2026-10-21 | Recorded as a change in place (backend phase 15, frontend phase 14, release 2.3-2.6 rewritten), not a new version | archive v1 and plan v2 per part | starts building sooner; obsolete sections replaced in place | change staged workflow (user choice) |
| 2026-10-21 | Live chart/control field setting fixed in engine (8.1) before release 2.3; the user's screenshot is a capability test of the current version (release 2.6), gaps recorded not built | pin a template; extend recipe 1.0 with area, list/slider controls, chart filters | smallest fix to the blocker; contract extensions don't fit the deadline | change live chart fields (user choice) |
| 2026-10-21 | Placement below the viewport fold on tall per_section canvases fixed in engine (9.1) before release 2.3 | backend caps page height at the viewport; accept `partial` and defer | keeps the staged per_section design; must-survive live build needs `failed: 0` | change tall canvas (user choice) |
| 2026-10-22 | Release 2.4 rows 2 (research) and 3 (BigQuery) fixed in the parts: engine 10.1 (off-screen picker fields, date control size, nearest rows-per-page value), backend 17.1 (clean labels, research aggregate rows); rerun rows 2-3 only | engine only; accept as known limits and relax 2.4 | both rows block a clean demo; no contract change; P2s (page 1 name, scorecard font) to Later | change manual acceptance fixes (user choice) |
| 2026-10-22 | Report quality: engine sizes scorecard values like the prototype (11.1), adds `rename_page` (recipe 1.1, additive; 11.2) and applies palette colors to the swatches a chart has (11.3); backend renders backgrounds at 2x device scale (19.1) and names page 1 (19.2) | keep 1.0 and accept "Untitled Page"; send explicit scorecard font sizes in the recipe | user flagged scorecard size and soft backgrounds on release 2.4 row 2; audit found 16/16 palette ops skipped; a derived size rule needs no new argument | change report quality (user choice) |
| 2026-10-22 | Fix both release 2.5 blockers in backend 18.1 and 18.2, then repeat full acceptance | stale-state fix only and accept dropped recreate observations | user chose both; existing required recreation/feasibility behavior is broken, no new feature or contract shape | change reference recovery (user choice) |
| 2026-10-23 | Deadline (2026-10-23 01:05 MPST) no longer binding: full scope kept; release 2.5's recreate/synthetic publish failure fixed in backend 21.1 | cut to push with recreate tagged planned; backend switch to turn designed pages off | user choice on cards after the deadline passed with 2.5 blocked | change recreate publication (user choice) |
| 2026-10-23 | Release 2.5's live report defects fixed in the parts before release 2.6: recipe 1.2 adds `time_series` `date_granularity` (engine 12.1 applies it in the chart, backend 23.1 emits it for date-bucket fields); the synthetic label is drawn once, by the background (backend 23.2, as synthetic-data.md already says), and release 2.7 updates its e2e check | engine infers granularity from field names; backend casts buckets to text; keep both label copies aligned; keep the native text and drop it from the background (synthetic-data.md change) | a DATE_TRUNC bucket is a DATE column, which Data Studio draws per day (spikes on the 1st, zeros between; b_36f20b42159c s015, b_91869163c217 s016); two copies of one text never align across renderers (b_91869163c217 page 1) | change live report defects (program root) |
| 2026-10-24 | Reference fidelity: the designer (planner) gets the reference images and a reference-first skill; vendored static globe/world art; capability check 24k/8k with trimmed comment ledgers; recipe 1.3 adds `area`, `fixed_size_list`, `stacked_percent` and breakdown series colors; base DATE columns on bucket starts get a code-owned grain | keep the text-only style profile; raise the designer cap with a user warning (declined); free model HTML with scripts and network; slider, per-chart filter and single-bar highlight now (deferred) | the image reached only the worker's extraction, so Argon designed blind (title, theme, slot ids; 769-3,002 of 16k output) under a skill that forces a light KPI page; the comment check refused at 12.7k of 12k; Data Studio has area charts, 100% stacked bars and fixed-size lists natively; s011 timed out and yearly DATE charts spiked (b_697880743b4f) | change reference fidelity (program root, user choice) |
| 2026-10-26 | Configurable model stages: every model call belongs to one stage with an editable global profile in Settings (model, thinking, and for the five generation stages input/output caps, one total clock, transport retries, validation repairs, count margin); defaults Flash LOW for interview/routine, Argon HIGH 131,072/32,768 for reference interpretation, native planning and the HTML brief, Flash HIGH 131,072/65,536 for HTML with and without a reference; Argon brief -> Flash HTML on both routes; uncapped brief prose with saved Markdown/JSON briefs; optional per-page brief review; explicit Flash fallback on availability/provider failures; hard stops on input overflow and output cutoff; labeled standard-layout fallback for no-reference pages behind a switch; api.md 3.0 (Settings breaking), conventions.md 1.4 | fixed 8k brief cap trial (docs/change-24.11-high-followup.md, superseded); per-build overrides; code-only budgets; structural fidelity proposal (docs/change-24.11-fidelity.md, not selected) | the HIGH brief hit its 4k cap twice (3 answer + 3,997 thinking tokens); the user wants every model stage adjustable from the app, not from code, and visible model/limit evidence | change configurable model stages (user interview, backend/docs/change-runtime-assumptions-interview.md) |
| 2026-10-26 | After the delta audits (user cards): grouped stage selectors kept; no-reference standard layout only after HTML repairs; migration keeps every explicit legacy model; brief review edits carry revision/sha256; cost estimates added on user request (verified backend prices, per call/run/build, labeled estimated) | one selector per model step; today's fall-back-on-anything; non-default-only migration; no costs | user cards and request 2026-10-26; a parallel architect session's review (backend/docs/stage-settings-reconciliation.md) | change configurable model stages (user) |
| 2026-10-27 | api.md 3.1: native_planning defaults output 65,536 and 1,200 s per action (no shape change; stored Settings keep their values); backend 25.7 rewritten to apply them, live fidelity moved to backend 25.8; release 2.6 now needs backend 25.8 | thinking medium; a test-only override; keep 3.0 defaults | backend 25.7 block: Argon high blueprint hit 600 s, 25k thinking tokens of 32,768 in a benchmark | change backend 25.7 block (user cards) |
| 2026-10-28 | Reference analysis gate (api.md 3.2, dashboard-intent.md 1.3, synthetic-data.md 1.3): a recreate upload gets a Flash analysis (each item native component with a catalog type, or static art, with box and reason) that the user approves or edits (split, type, note) before design/confirm, blueprint, recipe or run (`409 reference_unapproved`); approved native items replace image observations as requirements, static items are consented art; Argon blueprint and brief get the image plus the approved items; `BlueprintRow.reference_item`; defaults reference_interpretation Flash high with 1 repair, native_planning thinking medium; the observation path (extraction, reconciliation, unlabeled-control offers, approved drops) is deleted; style mode has no gate; backend 26.1-26.6 (26.6 replaces 25.11), frontend 17.1-17.3, release 2.6 gated on both | keep observations with native_planning medium (fastest; edge cases stay); gate at design/confirm with field bindings; keep the old path behind a flag | backend 25.7-25.11 blocked on observation edge cases settled by harness-only drops/offers; one explicit user decision replaces them; Flash is cheaper for the analysis; Argon high timed out twice at 1,200 s where medium answered in 79 s | change 2026-10-28 (user request and cards) |
| 2026-10-29 | Google sign-in at the hosted gate (api.md 3.3, conventions 1.5): `POST /api/session {google_id_token}` verified with google-auth, `DSS_SIGNIN_ALLOW` (empty = any Google account; `@domain` via `hd`, or emails) so a domain lock after the hackathon is one env change and a redeploy; signed 24 h cookie keyed by the code; the code and header stay for scripts and e2e drivers; agent token unchanged; backend 27.1, frontend 18.1, release 4.1 gated on both | IAP on Cloud Run (the local build agent would need Google ID tokens too; lifts the IAP non-goal); code only | user wants Google sign-in on the hosted link; in-app keeps SSE, iframe and agent paths unchanged | change 2026-10-29 (user, release 4.1 block, cards) |
| 2026-10-29 | Release 2.6 accepted as PASS with findings; W1-W7 (engine area auto-fields and box placement, `bar` date grain, backend legends, HTML flake, scorecard pick) deferred to the parts' Later lists; 2.6 reopened only to fix check_contracts' ReferenceSet schema; GitHub and Cloud Run next | plan engine/backend/contract fixes now, gate 4.3 on them | user: finish the GitHub upload and Cloud Run deployment first; the report is usable with recorded findings | change 2026-10-29 (user, release 2.6 block) |
| 2026-10-29 | Hosted v1 scope: the Cloud Run app goes from Google sign-in to the compiled recipe; Build answers `424 agent_offline` (the contract's existing stop, no contract change); Data Studio builds stay local; release 4.2/4.3 run `--until recipe` hosted, 4.3 skips the narrowed-allowlist step hosted, 4.4's README says so; one always-on instance kept | hosted builds through the owner's `dss-agent` (v1 plan); scale to zero (`--min-instances 0`) | user: the local agent is v2; no cold starts for judges, runs after 202 and the DB backup keep CPU | change 2026-10-29 hosted scope (user, release audit cards) |
| 2026-10-29 | Open hosted link (conventions 1.6): `DSS_PUBLIC=1` on Cloud Run, with the code and the Google client id empty, runs the service ungated; agent token unchanged; backend 28.1 (fail-closed opt-in), release 4.1 gated on it (deploy.sh open and gated modes), 4.2/4.4 wording; frontend unchanged (the gate opens on `required: false`) | OAuth client in a separate billing-free project with External branding (no code change); access code shared with the link; switch the existing branding to External | user: anyone with the link gets in; the project's branding is limited to one domain; an explicit flag so a missing secret never opens the service | change 2026-10-29 open hosted link (user cards) |
| 2026-10-29 | Cloud engine (conventions 1.7, api 3.4, recipe 1.4): on Cloud Run the backend runs the engine in the container (`DSS_ENGINE_MODE=cloud`, Chromium under Xvfb) as a dedicated demo Gmail account whose session is exported on the owner's machine and imported (never a sign-in in the cloud); recipes end with `share_report` (anyone with the link: Editor); `DSS_LOCKED_SOURCES=bigquery,gcs` on the open link; one engine lock (busy message, no queue); a Cloud Run job spike first (release 4.2, go/no-go); engine 14.1-14.2, backend 29.1-29.2, frontend 19.1, release 4.2-4.5 (old 4.2-4.4 renumbered) | a build agent on each visitor's PC with a guided setup command and pairing, report data as a public CSV in GCS (judges would download uv and the repo); a Chrome extension bridge (engine rewrite, store review); a VM; the owner's PC as the agent | user: judges download nothing and get the finished link they can edit in their own Data Studio; a dedicated account limits what an imported session can lose; an open link must not read the owner's tables; fallback if Google won't keep the session: hosted stops at the recipe | change 2026-10-29 cloud engine (user cards) |
| 2026-10-29 | Scale to zero and delta-audit fixes for the cloud engine: `--min-instances 0 --max-instances 1` (4.1 and 4.3), a build cut by a stopped instance fails at startup (backend 29.1); source lock on every open deploy in any mode; session files carry `exported_at`; lock before `check`; Secret Accessor on the session secret; Chrome disk cache capped; spike re-checks after 12 h; the close removes the demo account's BigQuery roles; paths under the root data/ | always-on instance (no cold start, about USD 40 to Nov 8); a Cloud Run job per build (parallel, but new backend work) | user: pay only when it is used; audit: 6 P1 and 7 P2 findings, all fixed in the docs, P2-7 to Later | change 2026-10-29 cloud engine (delta audit, user cards) |
