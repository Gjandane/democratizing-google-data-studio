# PRD: frontend
Target: POC · Written 2026-10-18 · Kind: a part of a program (../docs/program.md)

## Problem
The harness needs a face that makes the build process visible and steerable: a chat for the
interview, clear planning stages, a prototype the user can point at and comment on, and a live
view of the dashboard being built.

## Users
- The demo user (one, local): a business person who knows their data but not Data Studio.
- Hackathon judges watching the demo: the stages and the live build must read at a glance.

## Goals
1. One workspace walks a build through Connect -> Interview -> Plan -> Prototype -> Build -> Done
   with a stage stepper, the chat always visible on the left.
2. Click-to-comment on the prototype: hover outlines any component or decoration, click opens a
   comment popover, numbered pins collect comments, "Apply N comments" sends them in one batch.
3. The Build stage shows the recipe as CLI lines and ticks each op live as the engine runs it,
   then the dashboard link.
4. History lists past builds with their links; a done build can start a new version.
5. Settings (models, API key, GCP values) and a Trace tab (tokens, latency per run).
6. Hosted on Cloud Run (change 2026-10-19): an access-code gate before the app when the backend
   requires one, and a Build stage that shows the build agent's status and how to start it when
   the backend runs in agent mode.

## Non-goals
- No auth or accounts (POC, one user): only the shared access code of ../contracts/api.md#Access.
- No mobile layout: desktop only, 1280 px wide and up.
- No rendering of charts in the frontend: the backend renders the prototype HTML.
- No direct calls to Gemini, BigQuery or the engine: only the backend API.
- No offline-first or PWA features; no i18n.
- No CI.

## Core flows
1. History -> "New dashboard" -> pick archetype + mode -> Connect: drop CSVs (or GCS/BigQuery) ->
   "Start interview" -> chat -> "Generate plan" -> Plan docs stream in -> Prototype appears.
2. Prototype: click elements, add comments -> "Apply N comments" -> prototype reloads at v+1.
3. Build: check engine sign-in (button to sign in) -> "Generate recipe" -> "Build in Data
   Studio" -> ops tick live -> link card.
4. History: open a done build -> "New version" -> Prototype stage of v2.

## Features
| Must | Should | Won't (this version) |
|---|---|---|
| History, workspace shell, stepper, chat with streaming | Trace tab | mobile layout |
| Connect: archetype, CSV upload, GCS/BQ form, sources table | UX audit button | multi-user |
| Plan docs viewer | style-image upload | chart rendering in the client |
| Prototype click-to-comment, apply, reload | research-mode prompt | |
| Build: recipe lines, live op status, link, engine sign-in | screencast panel | |
| Settings modal; mock mode against fixtures | | |
| access-code gate; build-agent status in Build | | |

## Constraints
- Deadline 2026-10-20 01:05 MPST (whole program). Built against ../contracts/api.md with a mock
  until the backend is ready.
- Same-origin via the Vite proxy (`/api` -> `http://localhost:8000`) so the iframe DOM is readable;
  on Cloud Run the backend serves the built app (`npm run build` -> `dist/`), same origin again.

## Success criteria
- `npm test` passes, including the contract test of the mock fixtures.
- In mock mode (`VITE_MOCK=1`), flow 1 can be clicked through end to end.
- Against the real backend, the same flow works without code changes.

## Decided by default
- Mock mode via a small fixture-driven fake API (no MSW dependency), switched by `VITE_MOCK=1`.
- Routing with react-router (two routes: `/` History, `/builds/:id` Workspace).
- Markdown in chat and docs via react-markdown; icons via lucide-react.
- Desktop viewports only: 1280x800 and 1440x900; accessibility: AA contrast + visible focus.

## Open questions
- none

## Later
- Live view of the agent's Chrome inside the hosted app (screencast relayed through the agent).
- Responsive layout (plan).
