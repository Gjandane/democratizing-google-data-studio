# PRD: frontend
Target: POC · Written 2026-10-18 · Kind: a part of a program (../docs/program.md)

## Problem
The harness needs a face that makes the build process visible and steerable: reviewable
artifacts the user confirms by clicking (change staged workflow 2026-10-21), clear stages, a prototype the user can point at and comment on, and a live
view of the dashboard being built.

## Users
- The demo user (one, local): a business person who knows their data but not Data Studio.
- Hackathon judges watching the demo: the stages and the live build must read at a glance.

## Goals
1. One workspace walks a build through Connect -> Context -> Outline -> Design -> Blueprint ->
   Prototype -> Build -> Done with a stage stepper that shows each artifact's state (draft,
   confirmed, stale), and the activity log always visible on the left (change staged workflow
   2026-10-21; ../contracts/api.md 2.0). Users click to choose: KPI cards, question checkboxes
   with Recommended badges and Other text, theme presets; typing is optional.
2. Click-to-comment on the prototype: hover outlines any component or decoration, click opens a
   comment popover, numbered pins collect comments, "Apply N comments" sends them in one batch.
3. The Build stage shows the recipe as CLI lines and ticks each op live as the engine runs it,
   then the dashboard link.
4. History lists past builds with their links; a done build can start a new version.
5. Settings (models, API key, GCP values) and a Trace tab (tokens, latency per run).
6. Hosted on Cloud Run (change 2026-10-19): an access-code gate before the app when the backend
   requires one, and a Build stage that shows the build agent's status and how to start it when
   the backend runs in agent mode.
7. Activity transparency (change 2026-10-19): while a run works, the chat column shows a preset
   phrase for what it's doing, the elapsed time and the live token count, plus a preset step
   checklist for multi-step runs.

8. Required: reference mode/preview/removal UI and explicit feasibility decisions, showing
   product versus app versus data limitations without silently changing user intent.

9. Screenshot-only builds offer Generate sample data, schema/assumption review, row count/seed,
   CSV download and persistent synthetic-data labeling.

## Non-goals
- No auth or accounts (POC, one user): only the shared access code of ../contracts/api.md#Access.
- No mobile layout: desktop only, 1280 px wide and up.
- No rendering of charts in the frontend: the backend renders the prototype HTML.
- No direct calls to Gemini, BigQuery or the engine: only the backend API.
- No offline-first or PWA features; no i18n.
- No CI.

## Core flows
1. History -> "New dashboard" -> pick archetype + mode -> Connect: drop CSVs (or GCS/BigQuery) ->
   notes about the data -> "Draft context" -> edit KPI cards -> "Confirm context" -> tick
   questions (Other, Suggest more) -> "Confirm outline" -> pick a theme preset and page
   structure -> "Confirm design" -> blueprint table, resolve blocked rows -> "Accept blueprint"
   -> Prototype appears (page tabs).
2. Prototype: click elements, add comments -> "Apply N comments" -> prototype reloads at v+1.
3. Build: check engine sign-in (button to sign in) -> "Generate recipe" -> "Build in Data
   Studio" -> ops tick live -> link card.
4. History: open a done build -> "New version" -> Prototype stage of v2.
5. Screenshot-only (change 2026-10-19): Connect with no data -> attach a recreate reference ->
   "Generate sample data" -> review schema, row count, seed -> generate -> download CSV ->
   context -> outline -> design -> blueprint -> prototype, labeled as sample data throughout.

## Features
| Must | Should | Won't (this version) |
|---|---|---|
| History, workspace shell, stepper with artifact states, activity log | Trace tab | mobile layout; free-text chat (removed 2026-10-21) |
| Connect: archetype, CSV upload, GCS/BQ form, sources table | UX audit button | multi-user |
| Context review, outline picker, design picker, blueprint review, docs viewer; reference modes and feasibility decisions | | chart rendering in the client |
| Prototype click-to-comment, apply, reload | research-mode prompt | |
| Build: recipe lines, live op status, link, engine sign-in | screencast panel | |
| Settings modal; mock mode against fixtures | | |
| access-code gate; build-agent status in Build | | |
| | activity strip and run checklist (change 2026-10-19) | |
| synthetic sample data: schema review, generate, CSV download, labels (change 2026-10-19) | | |

## Constraints
- Deadline 2026-10-23 01:05 MPST (moved 2026-10-20) (whole program). Built against ../contracts/api.md with a mock
  until the backend is ready.
- Same-origin via the Vite proxy (`/api` -> `http://localhost:8000`) so the iframe DOM is readable;
  on Cloud Run the backend serves the built app (`npm run build` -> `dist/`), same origin again.

## Success criteria
- `npm test` passes, including the contract test of the mock fixtures.
- In mock mode (`VITE_MOCK=1`), flow 1 can be clicked through end to end.
- Against the real backend, the same flow works without code changes.
- Against the real backend, flow 5 reaches a labeled prototype without uploading a CSV.

## Decided by default
- Change staged workflow 2026-10-21: the chat input is removed (api.md 2.0 has no POST
  messages); the left column keeps the message log, run cards and activity strip. Other text and
  KPI edits are the only typing. Reference attach moves from the chat to the References panel in
  Connect, Design and Prototype. The design picker shows user-chosen colors as data swatches
  (inline style on swatches and the mini preview only; components still use tokens).
- Mock mode via a small fixture-driven fake API (no MSW dependency), switched by `VITE_MOCK=1`.
- Routing with react-router (two routes: `/` History, `/builds/:id` Workspace).
- Markdown in chat and docs via react-markdown; icons via lucide-react.
- Desktop viewports only: 1280x800 and 1440x900; accessibility: AA contrast + visible focus.

- Reference/capability change 2026-10-19 defaults: one recreation screenshot or 1-3 style
  images per version; explicit substitutions, curated capability evidence, existing dependencies.
  Closest supported recreation and release priority are user decisions, not defaults.

- Synthetic-data defaults (change 2026-10-19): 1,000 rows, seed 42; bounded stdlib generators;
  local DSS_DATA_DIR or existing GCS-backed /data volume; one new synthetic dataset in an empty
  build, no mixing with real data. User requested schema/count parameterization and sample CSVs.

## Open questions
- none

## Later
- Real per-step progress from the backend (`node.progress` at node boundaries) instead of timed presets (change 2026-10-19).
- Live view of the agent's Chrome inside the hosted app (screencast relayed through the agent).
- Responsive layout (plan).
- Known limitations (audit 2026-10-19): SSE event guards are exact, so an extra key on a live event drops it (types.ts, events.ts); EventSource/iframe 401 not routed to the gate; no fetch timeout; settings lock learned only after a failed save; unapplied comments and unsaved settings edits are lost without a warning; Settings and Trace reachable from History only via the banner; the Build view opened from Prototype is titled "Build" while the stepper stays on Prototype; the Stepper is a `<nav>` with no links; the live-view image has no intrinsic size; `server.fs.allow ['..']` in vite.config.ts; src/api/client.ts imports from features; react-router's literal `http://localhost` stays in dist.
- Known limitations (re-audit 2026-10-19): plan and spec error alerts can both show when spec fails inside a plan run (InterviewStage.tsx); a run card's anchor moves up one message if an optimistic send fails mid-run (useBuildStream.ts).
- Known limitations (audit 2026-10-20): the live-backend legs of 10.1 (uploads), 10.2 (GPS request) and 11.2 (screenshot -> proposal -> prototype, plus the label inside the backend-rendered prototype) were blocked by backend failures (reference upload 503, plan llm_unavailable) and are left to release 2.5's hosted check; the mock's Download CSV has no file behind it (src/mocks/api.ts); chat bubbles' sr-only labels extend the document height; the main bundle is 551 kB minified (Vite chunk-size warning).
- Known limitations (audit 2026-10-20, re-audit after Phase 11; P3, deferred by change 2026-10-20 triage): Connect shows Check feasibility before any source or reference, and the mock never refreshes the assessment after an interview run (src/mocks/api.ts); Done's read-only References reuses the "Add" empty copy and keeps a blank status line; mono columns put `font-mono` on their table headers (Table.tsx:39); the Stale badge uses the amber accent kept for pins; Remove references and Discard pending comments send without a confirm; the References title is a `<summary>`, not a heading; Clarify in chat on Connect focuses a disabled textarea; the sample-data panel shows the "isn't loaded" error while the reference set is still loading.
- Known limitations (audit 2026-10-20, re-audit after Phase 12; P3): after a feasibility action, focus moves to the panel heading only when the refetch lands, so a slow live GET could pull focus back after the user has moved on (FeasibilityPanel.tsx:91).
