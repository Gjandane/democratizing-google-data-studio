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
  - Done when: `npm test` passes with tests/access.test.tsx, tests/agent-status.test.tsx and the contract test (now covering ../contracts/fixtures/api/session.json, engine_status.json, engine_status.local.json, agent_job.json): with session `{required:true, ok:false}` the gate shows and no other `/api` call is made; a wrong code shows "That code didn't work" from `401 access_denied`; the right code loads History; a later `401 access_required` returns to the gate; with `{required:false}` no gate appears; in agent mode with `agent_connected:false` the Build stage shows the offline panel with a copyable `uv run --project backend dss-agent --server <window.location.origin>` command (containing no code or token) and Build disabled; connected but `signed_in:false` shows "Run `dsengine login` on the agent's machine" instead of the sign-in button; connected and signed in enables Build; `424 agent_offline` from `POST /run` shows the panel; local mode still shows the sign-in button; `403 settings_locked` marks the API key and GCP fields as fixed by the deployment; a file over 32 MB is refused before upload and any `413` shows the 32 MB message; `npm run build` exits 0, vite `base` stays `/` (assets under `/assets/`), and dist contains no `localhost` or other absolute-origin URL (except the Google Fonts stylesheet, essentials Never do, and library-internal strings); manual: screenshots of the gate and the three agent states at 1280x800 and 1440x900, checked against the UI design section.
  - Review focus: the code never reaches localStorage, a URL or a log; local mode looks exactly as before.

## Phase 6: Activity transparency (change 2026-10-19)
- [x] 6.1 Activity strip and run checklist
  - Goal: while a run works on the open build, the chat column shows what is happening: the activity strip (preset phrase, elapsed time, live tokens from `run.usage`) and, for runs with steps, a preset checklist card, per the essentials' UI design section, "Activity", and ../contracts/api.md 1.2. Strip: phrase `·` `m:ss` `·` tokens (input+output: `950`, `12.4k`, `1.2M`; title shows the split; absent until the first `run.usage`), for `execute` also `· N ops done` from `build.op`; it appears 400 ms after `run.started` with its height reserved (no jump in the message list); after `run.finished` it reads "Done in m:ss · N tokens" or "Stopped after m:ss" for 5 s. Cards for plan, spec, revise, research, style_extract, ux_audit, intake and execute, keyed by run_id; presets per node: a phrase list (rotates every 4 s) and steps with seconds-per-step; steps tick on that timer, the last waits for `run.finished` ok, an error marks the current step failed; a `node.progress` text replaces the current step's label. Client-only: a reload mid-run shows nothing until the next run (events aren't replayed). Plan's steps: Reading the data profile, Writing build docs, Creating the BigQuery view, Writing the dashboard spec, Checking the layout, Rendering the prototype; the other nodes get 2-5 steps and 3-6 phrases each, written in the copy rules, plus a generic set for unknown nodes.
  - Files: src/features/activity/*, src/features/workspace/chat/*, src/api/types.ts, src/mocks/*, tests/activity.test.tsx, tests/contract.test.ts, screenshots/
  - Depends on: 2.2
  - Size: M
  - Done when: `npm test` passes with tests/activity.test.tsx (fake timers) and the contract test (now covering ../contracts/fixtures/api/events.usage.sse; red until this task, since the fixture-coverage check sees the new file): `run.started {node:"plan"}` shows the strip after 400 ms with plan's first phrase and `0:00`, and `1:05` 65 s later; no token text before the first `run.usage`, then `run.usage` 80140 + 12360 shows `92.5k tokens`; a run that finishes within 400 ms never shows the strip; the plan card lists its 6 steps, ticks them on the timer while the last stays in progress until `run.finished` ok, then all ticked and the strip reads "Done in m:ss · 92.5k tokens" for 5 s; `run.finished` error marks the current step failed, later steps pending, strip "Stopped after m:ss"; a `node.progress` text replaces the current step's label; an interview turn shows the strip but no card; an unknown node shows the generic phrases; an `execute` run counts `build.op` events in the strip; with prefers-reduced-motion the dots don't animate; in mock mode (`VITE_MOCK=1`) every mocked run emits `run.usage` so the strip counts up; `npm run build` exits 0; manual: screenshots of the strip and the plan card mid-run and done at 1280x800 and 1440x900, checked against the UI design section (no layout shift when the strip appears).
  - Review focus: ../contracts/api.md 1.2; only `run.finished` ok ticks the last step (presets never claim a finished result early); timers cleared on unmount and on build change.
- [x] 6.2 Contract 1.2 run node names
  - Goal: the app matches runs by the ../contracts/api.md 1.2 `node` values: `revise` (applying comments: `applying`, `commentsError`), `style_extract` and `ux_audit` (stretch runs), `execute` (the build run in buildRun.ts), instead of the pre-1.2 names 'comments', 'style', 'audit', 'build'; the mock emits the same names; the 6.1 ALIASES map in presets.ts goes.
  - Files: src/features/workspace/chat/useBuildStream.ts, src/features/workspace/build/buildRun.ts, src/features/workspace/connect/StylePanel.tsx, src/features/workspace/prototype/PrototypeStage.tsx, src/features/activity/presets.ts, src/features/activity/activity.ts, src/mocks/api.ts, tests/build.test.tsx, tests/plan.test.tsx, tests/prototype.test.tsx, tests/stretch.test.tsx
  - Depends on: 6.1
  - Size: S
  - Done when: a search of src/ and tests/ finds no run `node` value 'comments', 'style', 'audit' or 'build'; `npm test` and `npm run typecheck` pass.
  - Review focus: ../contracts/api.md 1.2 `node` list; StretchRoute 'audit' (an API route, not a node) unchanged.

## Phase 7: Audit fixes (final audit 2026-10-19)
- [x] 7.1 Run errors and the finished run card
  - Goal: a failed `plan`, `interview` or `spec` run says why and what to do next: the `run.finished` error text (fallback when null: "The plan didn't finish. Try \"Generate plan\" again." for plan, a matching line for the others) shows where the user lands (Interview stage for plan and spec, the chat for interview) with role=alert, and clears on the next `run.started` of that node. The finished run checklist card no longer stays pinned at the end of the chat log: it sits in time order among the messages (after the last message created before its run started), so later messages render below it.
  - Files: src/features/workspace/chat/useBuildStream.ts, src/features/workspace/chat/InterviewStage.tsx, src/features/workspace/chat/ChatPanel.tsx, src/features/activity/activity.ts, src/features/activity/RunCard.tsx, src/mocks/api.ts, tests/chat.test.tsx, tests/activity.test.tsx, screenshots/
  - Depends on: none
  - Size: M
  - Done when: `npm test` passes with tests/chat.test.tsx: `run.finished {node:"plan", status:"error", error:"Gemini quota hit"}` then `stage.changed: interview` shows "Gemini quota hit" in the Interview stage in a role=alert element, and the next `run.started {node:"plan"}` removes it; the same with `error: null` shows the fallback naming "Generate plan"; an `interview` run error shows its text in the chat; and tests/activity.test.tsx: a message arriving after a finished plan card renders after the card in DOM order; `npm run typecheck` passes; manual: screenshots 7.1-interview-error and 7.1-card-later-message at 1280x800 and 1440x900, checked against the UI design section.
  - Review focus: errors follow the copy rule (say what to do next); the card's position never shifts the log while a run is live.
- [x] 7.2 Contrast and small UI fixes
  - Goal: the Trace "Error" pill meets 4.5:1 (`text-text` on `bg-danger-soft`, as DoneStage); `formatLatency` never prints "60 s" (119.6 s reads "2 min 0 s"); every link that opens a new tab (Build result card, markdown links) carries the sr-only "(opens in a new tab)" that History and DoneStage use; the stale "A `comments` run" comment in PrototypeStage names `revise`; a done build with no messages shows copy that fits a done build instead of "The assistant's first question shows up here."
  - Files: src/features/trace/TraceModal.tsx, src/features/workspace/build/BuildStage.tsx, src/features/workspace/chat/Markdown.tsx, src/features/workspace/chat/ChatPanel.tsx, src/features/workspace/prototype/PrototypeStage.tsx, tests/settings.test.tsx, tests/chat.test.tsx, tests/build.test.tsx, screenshots/
  - Depends on: 7.1
  - Size: S
  - Done when: `npm test` passes with: `formatLatency(119600)` is "2 min 0 s" and `formatLatency(59960)` is not "60.0 s"; the trace error pill has class `text-text`, not `text-danger`; the Build result link and a markdown link each contain "(opens in a new tab)"; the done-build empty chat no longer contains "first question"; a search of src/ finds no "`comments` run"; `npm run typecheck` passes; manual: screenshot 7.2-trace-error at 1280x800.

## Phase 8: Audit fixes (final re-audit 2026-10-19)
- [x] 8.1 Retry guard, error punctuation, trace wrap and link hover
  - Goal: the Interview stage's "Generate plan again" (ErrorState action) can't post `/plan` twice: one in-flight guard covers it and the main "Generate plan" button, and the retry is disabled while the POST runs; the interview error suffix " Send your answer again." follows a sentence end (add ". " when the server text doesn't end in `.`, `!` or `?`); in the Trace table the latency cells and the total row ("Total, N runs", total latency) never wrap (`whitespace-nowrap` through the Column `className`, which the footer cells share); markdown links show hover feedback (`hover:text-primary-hover`).
  - Files: src/features/workspace/chat/InterviewStage.tsx, src/features/workspace/chat/ChatPanel.tsx, src/features/trace/TraceModal.tsx, src/features/workspace/chat/Markdown.tsx, tests/chat.test.tsx, tests/settings.test.tsx, screenshots/
  - Depends on: none
  - Size: S
  - Done when: `npm test` passes with tests/chat.test.tsx: after a failed plan run, two clicks on "Generate plan again" before the POST resolves post `/plan` once and the button is disabled while it runs; an `interview` run error "quota hit" shows "quota hit. Send your answer again." and "Model timed out." shows "Model timed out. Send your answer again."; a markdown link has class `hover:text-primary-hover`; and tests/settings.test.tsx: the trace latency cells and the total row's node and latency cells have class `whitespace-nowrap`; `npm run typecheck` passes; manual: screenshot 8.1-trace-1280x800 shows "2 min 43 s" and "Total, 3 runs" each on one line.

## Phase 9: Audit fixes (final re-audit 2026-10-19, after Phase 8)
- [x] 9.1 Retry gap, punctuation edge cases, retry spinner and total-row font
  - Goal: after "Generate plan again" (or "Generate plan") posts `/plan` successfully, the retry stays disabled until the plan error clears (the next `run.started` of `plan`) or the stage leaves Interview, so a click in that gap posts nothing; a rejected POST re-enables it with its error shown; while the retry is disabled for a run in flight it shows the Button spinner and `aria-busy` (ErrorState passes a loading state through to Button, additive, default off); the interview suffix " Send your answer again." checks the sentence end on the trimmed text and allows one closing quote or bracket after `.`, `!` or `?` (`"quota hit. "` gives "quota hit. Send your answer again.", `He said "stop."` gets no extra "."); the Trace total row's label cell ("Total, N runs") uses the body font, not Fira Code (the Node column's body cells stay mono), and the cells still never wrap.
  - Files: src/features/workspace/chat/InterviewStage.tsx, src/features/workspace/chat/ChatPanel.tsx, src/components/ErrorState.tsx, src/features/trace/TraceModal.tsx, src/components/Table.tsx, tests/chat.test.tsx, tests/settings.test.tsx, tests/components.test.tsx, screenshots/
  - Depends on: none
  - Size: S
  - Done when: `npm test` passes with tests/chat.test.tsx: after a failed plan run, a click on "Generate plan again" whose POST resolves leaves the button disabled with `aria-busy="true"` until `run.started {node:"plan"}` arrives, and a second click in that gap posts nothing (`/plan` posted once); a rejected POST leaves the retry enabled with the error shown; two `click()` calls inside one `act` post `/plan` once (the same-frame ref guard, not only `disabled`); interview error `"quota hit. "` shows "quota hit. Send your answer again." and `He said "stop."` shows `He said "stop." Send your answer again.`; the earlier "quota hit" and "Model timed out." cases still pass; tests/settings.test.tsx: the total row's label cell has no `font-mono` class while a Node body cell keeps it, and the 8.1 `whitespace-nowrap` asserts still pass; tests/components.test.tsx: ErrorState without the new prop renders a retry with no `aria-busy`; `npm run typecheck` passes; manual: screenshots 9.1-trace-1280x800 (total row in the body font, one line) and 9.1-retry-pending-1280x800 (retry with spinner), checked against the UI design section.
  - Review focus: the retry can never post `/plan` twice for one failed run, and can't stay disabled forever (a POST error, or a stage change without `run.started`, re-enables or removes it).
