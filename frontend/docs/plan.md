# Plan: frontend
Target: POC · Audit: done 2026-10-18 (18 findings across the program, 18 applied)
Markers: [ ] to do, [~] in progress, [x] done, [!] blocked. Only blueprint.py changes them.
Sizes: S small, M a normal session, L needs a whole fresh session (never run unattended).

## Phase 1: Walking skeleton and design foundation
- [x] 1.1 App skeleton, typed client and mock mode
  - Goal: Vite + React + TS + Tailwind app with the `/api` proxy, the typed client and event hook, mock mode with fixtures, and a History route that lists builds.
  - Files: package.json, vite.config.ts, tsconfig.json, index.html, .gitignore, src/main.tsx, src/App.tsx, src/api/client.ts, src/api/types.ts, src/api/events.ts, src/mocks/*, src/features/history/HistoryPage.tsx, tests/contract.test.ts, tests/history.test.tsx
  - Depends on: none
  - Size: M
  - Done when: `npm test` passes: tests/contract.test.ts checks every file in ../contracts/fixtures/api/ (Build, BuildSummary, Source, Message, Trace, Settings, recipe ops, error, and each event in events.sse) with the guards in types.ts, and a copy with a wrong `stage` fails; tests/history.test.tsx renders History from the mock and shows the builds newest first; `npm run typecheck` passes; manual: `VITE_MOCK=1 npm run dev` shows the History list at http://localhost:5173.
- [x] 1.2 Design foundation
  - Goal: tokens, base components and the workspace shell from the essentials' UI design section, applied to History and an empty Workspace.
  - Files: src/styles/tokens.css, src/index.css, src/components/*, src/features/workspace/WorkspaceShell.tsx, src/features/workspace/Stepper.tsx, src/features/history/HistoryPage.tsx, src/App.tsx, tests/components.test.tsx, screenshots/
  - Depends on: 1.1
  - Size: M
  - Done when: `npm test` passes, with tests/components.test.tsx covering Button (disabled, focus-visible class), Stepper (current and done steps), EmptyState and ErrorState; `rg -n "#[0-9A-Fa-f]{6}" src/components src/features` prints nothing (hex only in tokens.css); manual at 1280x800 and 1440x900: History (list, empty, error) and the Workspace shell (top bar, 380 px chat column, stepper on Connect) show without overlap; focus ring visible on every control; screenshots saved in screenshots/ as 1.2-<view>-<viewport>.png.
  - STOP: show the user the screenshots for sign-off on the look before any stage screen is built; small changes are made here, bigger ones become a change request.

## Phase 2: Connect, chat and plan
- [x] 2.1 Connect stage
  - Goal: new build (archetype cards with one-line descriptions, data/research mode), multi-CSV drag-and-drop upload, GCS/BigQuery URI form, sources table with columns, "Start interview".
  - Files: src/features/workspace/connect/*, src/features/history/NewBuildDialog.tsx, src/api/client.ts, src/mocks/*, tests/connect.test.tsx, screenshots/
  - Depends on: 1.2
  - Size: M
  - Done when: `npm test` passes with tests/connect.test.tsx: creating a build calls `POST /api/builds` with the picked archetype; dropping two CSVs uploads both and lists two sources with their columns; a `422 invalid_source` shows its message in the error state; "Start interview" stays disabled until one source exists; manual at both viewports: empty, uploading, error and filled states show; screenshots saved.
- [x] 2.2 Chat panel with streaming and Interview stage
  - Goal: the chat column: message list with markdown, streaming deltas from the event stream, input with send; the Interview stage area (sources summary, archetype card, questions answered so far) with "Generate plan", primary when `ready_for_plan`, secondary before.
  - Files: src/features/workspace/chat/*, src/api/events.ts, src/mocks/*, tests/chat.test.tsx, screenshots/
  - Depends on: 1.2
  - Size: M
  - Done when: `npm test` passes with tests/chat.test.tsx: `message.delta` events append to the same assistant bubble and `message.done` replaces it; sending posts `/messages` and shows the user bubble at once; reconnect re-fetches messages; `build.updated` with `ready_for_plan: true` shows "Generate plan", which calls `POST /plan`; manual at both viewports: long messages wrap, the list scrolls to the newest, loading and error states show; screenshots saved.
- [x] 2.3 Plan stage
  - Goal: node progress lines while planning, then the build docs list with a markdown viewer; moves to Prototype on `stage.changed`.
  - Files: src/features/workspace/plan/*, src/mocks/*, tests/plan.test.tsx, screenshots/
  - Depends on: 2.2
  - Size: S
  - Done when: `npm test` passes with tests/plan.test.tsx: `node.progress` lines appear in order; `docs.updated` lists docs and clicking one shows its markdown from `GET /docs/{path}`; `stage.changed: prototype` switches the stage; manual: loading and empty states show at both viewports; screenshots saved.

## Phase 3: Prototype, build, settings, history
- [x] 3.1 Prototype stage with click-to-comment
  - Goal: the prototype iframe with an overlay: hover outline + label on any `[data-cid]`, click opens a comment popover (dark card quoting the element's label, a textarea, "Cancel" and an amber "Add"), numbered amber pins, a pending-comments list, "Apply N comments", reload at the new version.
  - Files: src/features/workspace/prototype/*, src/mocks/*, tests/prototype.test.tsx, screenshots/
  - Depends on: 2.3
  - Size: M
  - Done when: `npm test` passes with tests/prototype.test.tsx (jsdom iframe with ../contracts/fixtures/api/prototype.sample.html, `getBoundingClientRect` stubbed): hovering a `[data-cid]` shows its `data-label`; adding a comment creates pin 1 at that element; removing a pending comment renumbers pins; "Apply 2 comments" posts both with their `component_id`s and disables while running; `prototype.updated` reloads the iframe with `?v=<new>` and clears applied pins; Esc closes the popover; one `scale()` wrapper holds both iframe and pin layer (asserted on the DOM); manual at both viewports: the whole 1200 px canvas fits the stage width, pins stay on their elements when the stage area resizes, the popover never covers the element it comments on, screenshots saved.
  - Review focus: overlay positions computed from the iframe's element boxes and zoom; no script injected into the iframe; keyboard path to add and apply comments.
- [x] 3.2 Build stage
  - Goal: engine status with "Sign in to Google" (`POST /engine/login`), "Generate recipe" showing the CLI lines, "Build in Data Studio", live per-op status from `build.op`, and the result card with the link.
  - Files: src/features/workspace/build/*, src/mocks/*, tests/build.test.tsx, screenshots/
  - Depends on: 1.2
  - Size: M
  - Done when: `npm test` passes with tests/build.test.tsx: recipe `ops` render in Fira Code with their op ids; each `build.op` ticks the line with the same `op_id` ok/failed/skipped and a failed line shows its message; `build.finished` with `partial` shows the link plus "N ops failed"; `signed_in: false` disables "Build" and shows the sign-in button; manual at both viewports: running, partial, failed and done states show; the link opens in a new tab; screenshots saved.
- [x] 3.3 Settings and Trace tab
  - Goal: the settings modal (planner and worker model, API key write-only, GCP project, dataset, location, bucket), a banner that opens it on `503 llm_unavailable` / `503 gcp_not_configured` or when the key or project is missing, and the Trace tab (runs table with node, model, tokens, latency, status, plus totals).
  - Files: src/features/settings/*, src/features/trace/*, src/mocks/*, tests/settings.test.tsx, screenshots/
  - Depends on: 1.2
  - Size: S
  - Done when: `npm test` passes with tests/settings.test.tsx: saving sends only changed fields; a 503 from any action shows the banner, and its button opens Settings; the key field is empty after save and shows "Key set" from `google_api_key_set`; the trace table totals input and output tokens; manual at both viewports: modal focus is trapped and Esc closes it; screenshots saved.
- [x] 3.4 Done stage and history versions
  - Goal: the Done stage area (link card, versions with links, "New version"); History shows each build's stage and link; "New version" (`POST /versions`) opens the Prototype stage of the new version.
  - Files: src/features/history/*, src/features/workspace/WorkspaceShell.tsx, src/mocks/*, tests/versions.test.tsx, screenshots/
  - Depends on: 3.1; 3.2
  - Size: S
  - Done when: `npm test` passes with tests/versions.test.tsx (fixture build.done.json): the Done stage shows the link card; a done build lists v1 with its link; "New version" posts and lands on Prototype with v2; manual: screenshots saved at both viewports.

## Phase 4: Stretch
- [x] 4.1 Style images, research prompt, audit and screencast
  - Goal: Connect accepts style screenshots (`POST /style-images`) and a research prompt in research mode (`POST /research`); Prototype has "Run UX audit" (`POST /audit`); Build shows `build.frame` images in a live panel when they arrive.
  - Files: src/features/workspace/connect/*, src/features/workspace/prototype/*, src/features/workspace/build/*, src/mocks/*, tests/stretch.test.tsx, screenshots/
  - Depends on: 3.2; 3.1
  - Size: M
  - Done when: `npm test` passes with tests/stretch.test.tsx: each action posts to its route and shows its run state; a `build.frame` event updates the live image; a `404` on a stretch route hides its control instead of erroring; manual: screenshots saved at both viewports.

## Phase 5: Cloud Run
- [x] 5.1 Access-code gate and build-agent status
  - Goal: the app works behind the hosted backend: an access-code gate when `GET /api/session` says it's required, an agent panel in the Build stage when the engine runs in agent mode, locked settings, and the 32 MB upload limit.
  - Files: src/api/client.ts, src/api/types.ts, src/features/access/*, src/App.tsx, src/features/workspace/build/*, src/features/workspace/connect/*, src/features/settings/*, src/mocks/*, tests/access.test.tsx, tests/agent-status.test.tsx, tests/contract.test.ts, screenshots/
  - Depends on: 3.2
  - Size: M
  - Done when: `npm test` passes with tests/access.test.tsx, tests/agent-status.test.tsx and the contract test (now covering ../contracts/fixtures/api/session.json, engine_status.json, engine_status.local.json, agent_job.json): with session `{required:true, ok:false}` the gate shows and no other `/api` call is made; a wrong code shows "That code didn't work" from `401 access_denied`; the right code loads History; a later `401 access_required` returns to the gate; with `{required:false}` no gate appears; in agent mode with `agent_connected:false` the Build stage shows the offline panel with a copyable `uv run --project backend dss-agent --server <window.location.origin>` command (containing no code or token) and Build disabled; connected but `signed_in:false` shows "Run `dsengine login` on the agent's machine" instead of the sign-in button; connected and signed in enables Build; `424 agent_offline` from `POST /run` shows the panel; local mode still shows the sign-in button; `403 settings_locked` marks the API key and GCP fields as fixed by the deployment; a file over 32 MB is refused before upload and any `413` shows the 32 MB message; `npm run build` exits 0, vite `base` stays `/` (assets under `/assets/`), and dist contains no `localhost` or other absolute-origin URL; manual: screenshots of the gate and the three agent states at 1280x800 and 1440x900, checked against the UI design section.
  - Review focus: the code never reaches localStorage, a URL or a log; local mode looks exactly as before.
