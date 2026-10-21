# Plan: frontend
Target: POC · Audit: done 2026-10-21 (delta, staged workflow: 16 findings, 16 applied; earlier audits recorded in progress.md)

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
  - Done when: `npm test` passes with tests/access.test.tsx, tests/agent-status.test.tsx and the contract test (now covering ../contracts/fixtures/api/session.json, engine_status.json, engine_status.local.json, agent_job.json): with session `{required:true, ok:false}` the gate shows and no other `/api` call is made; a wrong code shows "That code didn't work" from `401 access_denied`; the right code loads History; a later `401 access_required` returns to the gate; with `{required:false}` no gate appears; in agent mode with `agent_connected:false` the Build stage shows the offline panel with a copyable `uv run --project backend dss-agent --server <window.location.origin>` command (containing no code or token) and Build disabled; connected but `signed_in:false` shows "Run `dsengine login` on the agent's machine" instead of the sign-in button; connected and signed in enables Build; `424 agent_offline` from `POST /run` shows the panel; local mode still shows the sign-in button; `403 settings_locked` marks the API key and GCP fields as fixed by the deployment; a file over 32 MB is refused before upload and any `413` shows the 32 MB message; `npm run build` exits 0, vite `base` stays `/` (assets under `/assets/`), and dist contains no `localhost` or other absolute-origin URL (except the Google Fonts stylesheet, essentials Never do, and library-internal strings); manual: screenshots of the gate and the three agent states at 1280x800 and 1440x900, checked against docs/staged-ui.md and the UI design section.
  - Review focus: the code never reaches localStorage, a URL or a log; local mode looks exactly as before.

## Phase 6: Activity transparency (change 2026-10-19)
- [x] 6.1 Activity strip and run checklist
  - Goal: while a run works on the open build, the chat column shows what is happening: the activity strip (preset phrase, elapsed time, live tokens from `run.usage`) and, for runs with steps, a preset checklist card, per the essentials' UI design section, "Activity", and ../contracts/api.md 1.2. Strip: phrase `·` `m:ss` `·` tokens (input+output: `950`, `12.4k`, `1.2M`; title shows the split; absent until the first `run.usage`), for `execute` also `· N ops done` from `build.op`; it appears 400 ms after `run.started` with its height reserved (no jump in the message list); after `run.finished` it reads "Done in m:ss · N tokens" or "Stopped after m:ss" for 5 s. Cards for plan, spec, revise, research, style_extract, ux_audit, intake and execute, keyed by run_id; presets per node: a phrase list (rotates every 4 s) and steps with seconds-per-step; steps tick on that timer, the last waits for `run.finished` ok, an error marks the current step failed; a `node.progress` text replaces the current step's label. Client-only: a reload mid-run shows nothing until the next run (events aren't replayed). Plan's steps: Reading the data profile, Writing build docs, Creating the BigQuery view, Writing the dashboard spec, Checking the layout, Rendering the prototype; the other nodes get 2-5 steps and 3-6 phrases each, written in the copy rules, plus a generic set for unknown nodes.
  - Files: src/features/activity/*, src/features/workspace/chat/*, src/api/types.ts, src/mocks/*, tests/activity.test.tsx, tests/contract.test.ts, screenshots/
  - Depends on: 2.2
  - Size: M
  - Done when: `npm test` passes with tests/activity.test.tsx (fake timers) and the contract test (now covering ../contracts/fixtures/api/events.usage.sse; red until this task, since the fixture-coverage check sees the new file): `run.started {node:"plan"}` shows the strip after 400 ms with plan's first phrase and `0:00`, and `1:05` 65 s later; no token text before the first `run.usage`, then `run.usage` 80140 + 12360 shows `92.5k tokens`; a run that finishes within 400 ms never shows the strip; the plan card lists its 6 steps, ticks them on the timer while the last stays in progress until `run.finished` ok, then all ticked and the strip reads "Done in m:ss · 92.5k tokens" for 5 s; `run.finished` error marks the current step failed, later steps pending, strip "Stopped after m:ss"; a `node.progress` text replaces the current step's label; an interview turn shows the strip but no card; an unknown node shows the generic phrases; an `execute` run counts `build.op` events in the strip; with prefers-reduced-motion the dots don't animate; in mock mode (`VITE_MOCK=1`) every mocked run emits `run.usage` so the strip counts up; `npm run build` exits 0; manual: screenshots of the strip and the plan card mid-run and done at 1280x800 and 1440x900, checked against docs/staged-ui.md and the UI design section (no layout shift when the strip appears).
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
  - Done when: `npm test` passes with tests/chat.test.tsx: `run.finished {node:"plan", status:"error", error:"Gemini quota hit"}` then `stage.changed: interview` shows "Gemini quota hit" in the Interview stage in a role=alert element, and the next `run.started {node:"plan"}` removes it; the same with `error: null` shows the fallback naming "Generate plan"; an `interview` run error shows its text in the chat; and tests/activity.test.tsx: a message arriving after a finished plan card renders after the card in DOM order; `npm run typecheck` passes; manual: screenshots 7.1-interview-error and 7.1-card-later-message at 1280x800 and 1440x900, checked against docs/staged-ui.md and the UI design section.
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
  - Done when: `npm test` passes with tests/chat.test.tsx: after a failed plan run, a click on "Generate plan again" whose POST resolves leaves the button disabled with `aria-busy="true"` until `run.started {node:"plan"}` arrives, and a second click in that gap posts nothing (`/plan` posted once); a rejected POST leaves the retry enabled with the error shown; two `click()` calls inside one `act` post `/plan` once (the same-frame ref guard, not only `disabled`); interview error `"quota hit. "` shows "quota hit. Send your answer again." and `He said "stop."` shows `He said "stop." Send your answer again.`; the earlier "quota hit" and "Model timed out." cases still pass; tests/settings.test.tsx: the total row's label cell has no `font-mono` class while a Node body cell keeps it, and the 8.1 `whitespace-nowrap` asserts still pass; tests/components.test.tsx: ErrorState without the new prop renders a retry with no `aria-busy`; `npm run typecheck` passes; manual: screenshots 9.1-trace-1280x800 (total row in the body font, one line) and 9.1-retry-pending-1280x800 (retry with spinner), checked against docs/staged-ui.md and the UI design section.
  - Review focus: the retry can never post `/plan` twice for one failed run, and can't stay disabled forever (a POST error, or a stage change without `run.started`, re-enables or removes it).

## Phase 10: Required references and feasibility (change 2026-10-19; split by delta audit 2026-10-20)
- [x] 10.1 Reference panel, chat attach and API 1.4 guards
  - Goal: one References panel (Connect, Interview, Prototype, and the chat's Attach reference button) uploads a style or recreate reference with instructions, shows the retained set, and replaces or removes it; types accept API 1.4 so a synthetic source never breaks the Build guard.
  - Spec: docs/reference-ui.md#Controls and states; ../contracts/dashboard-intent.md#Reference set
  - Files: src/api/client.ts, src/api/types.ts, src/mocks/api.ts, src/mocks/fixtures.ts, src/features/workspace/stretch.ts, src/features/workspace/ReferencePanel.tsx, src/features/workspace/connect/ConnectStage.tsx, src/features/workspace/connect/StylePanel.tsx, src/features/workspace/chat/ChatPanel.tsx, src/features/workspace/chat/InterviewStage.tsx, src/features/workspace/prototype/PrototypeStage.tsx, src/features/history/DoneStage.tsx, src/features/activity/presets.ts, tests/contract.test.ts, tests/references.test.tsx, tests/stretch.test.tsx, tests/connect.test.tsx, tests/chat.test.tsx, screenshots/
  - Depends on: 9.1
  - Size: M
  - Needs: backend 11.8
  - Done when: `npm test` and `npm run typecheck` pass, with tests asserting: (1) contract.test imports ../contracts/fixtures/dashboard-intent/reference_set.json through an exact `isReferenceSet`, and `isBuild` accepts a build whose source has `kind: "synthetic"` (from ../contracts/fixtures/synthetic-data/source.json) and still rejects an unknown kind; (2) Recreate dashboard + instructions + one PNG posts multipart `files`, `mode=recreate`, `instructions` exactly once, also on a same-frame double click; (3) the panel opened from chat Attach reference and from the stage shows the same saved set, and an upload in one appears in the other; (4) after remount, GET reference-images restores thumbnail (alt text names mode and filename), mode and summary; Replace posts a new set; Remove sends DELETE and shows the empty state; (5) before any POST the panel rejects 2 files in recreate, 4 in style, a 6 MiB file, 16 MiB total and a non-PNG/JPEG file, each with an inline message naming the limit; a mock 413 and 422 show reference-specific text (never the 32 MB CSV text) and keep the prior saved set and the user's selection; (6) the upload's run is matched by `run_id`: its `run.finished` refetches the set, and an unrelated `run.finished` for the same node does not settle it; (7) Done shows the set read-only (no Replace/Remove) next to New version; the strip shows a reference_extract phrase. Former style-images assertions in tests/stretch.test.tsx move to the reference route with equal coverage, never deleted. Manual at 1280x800 and 1440x900: screenshots/10.1-references-{empty,saved,processing,failed}-<viewport>.png; keyboard path Tab to mode radios, instructions, file chooser, Replace and Remove, with focus returning to the upload control after Remove; a long filename truncates with no horizontal overflow; one live-backend style upload and one recreate upload succeed.
  - Review focus: ../contracts/api.md 1.5 and ../contracts/dashboard-intent.md 1.1 (Reference set); the stretch 404-hide never applies to reference routes; no raw model output or file path shown.
- [x] 10.2 Feasibility panel, decisions and Generate/Build gates
  - Goal: show each blocking requirement with its reason, evidence and alternatives above Generate/Build; send only explicit decisions; Check feasibility recovers unchecked/legacy builds; blocked, unchecked, stale or unloadable assessments keep Generate plan, Generate recipe and Build off.
  - Spec: docs/reference-ui.md#Controls and states; ../contracts/dashboard-intent.md#Feasibility assessment
  - Files: src/api/client.ts, src/api/types.ts, src/mocks/api.ts, src/mocks/fixtures.ts, src/features/workspace/FeasibilityPanel.tsx, src/features/workspace/WorkspaceShell.tsx, src/features/workspace/chat/InterviewStage.tsx, src/features/workspace/chat/useBuildStream.ts, src/features/workspace/prototype/PrototypeStage.tsx, src/features/workspace/build/BuildStage.tsx, src/features/activity/presets.ts, tests/contract.test.ts, tests/feasibility.test.tsx, tests/build.test.tsx, tests/prototype.test.tsx, tests/versions.test.tsx, screenshots/
  - Depends on: 10.1
  - Size: M
  - Needs: backend 11.8
  - Done when: `npm test` and `npm run typecheck` pass, with tests asserting: (1) contract.test imports ../contracts/fixtures/dashboard-intent/feasibility.json and its feasibility.alternatives.json, feasibility.pending.json and feasibility.stale.json variants through an exact `isAssessment`; tests use those shared fixtures (src/mocks/fixtures.ts), never a copied file; (2) the mock's default assessment for `fixtures.build` is `ready`, and the existing prototype, build and versions tests pass unchanged; (3) `unchecked` shows Check feasibility, which POSTs feasibility/check once; that run's `run.finished` refetches, and a `ready` result enables Generate/Build; (4) a blocked issue shows its requirement and a status-specific reason (distinct copy for unsupported_product, unsupported_app, needs_data, needs_clarification and unknown), http(s) evidence as links opening a new tab with screen-reader text, other evidence as mono text, and no alternative preselected; (5) Use this alternative posts `{assessment_id, decisions:[{issue_id, action:"accept_alternative", alternative_id}]}` and Drop this requirement posts `alternative_id: null`; neither POSTs plan, recipe or run; `409 feasibility_stale` refetches and asks the user to review again; a late response for an older assessment id never overwrites a newer one; (6) needs_clarification focuses the chat input; (7) a failed GET feasibility shows ErrorState with Retry and keeps Generate plan, Generate recipe and Build disabled, and `stale` or `prototype_stale: true` keeps Generate recipe and Build disabled; (8) the assessment refetches on mount, SSE reconnect, `docs.updated` and `run.finished` (one test each); the strip shows a capability_check phrase. Manual at 1280x800 and 1440x900: screenshots/10.2-feasibility-{unchecked,blocked,ready,error}-<viewport>.png; keyboard decision path (Tab to Use this alternative, Enter, focus on the refreshed panel heading); a live-backend blocked request ("animate GPS points") shows the app-limitation copy and a supported alternative; the pin overlay stays aligned on Prototype with the panel shown.
  - Review focus: ../contracts/api.md 1.5 and ../contracts/dashboard-intent.md 1.1 (Feasibility assessment); product, app and data limitations read differently; no unsupported success or silently accepted alternative; Build/SSE guards unchanged.
- [x] 10.3 Pending comment batches and stale-prototype replan
  - Goal: a blocked comment batch survives reload with its targets and text; Reapply saved comments and Discard pending comments act on it only when the user asks; once intent resolves, a stale prototype can be replanned while Build stays off.
  - Spec: docs/reference-ui.md#Controls and states; ../contracts/dashboard-intent.md#Feasibility assessment
  - Files: src/api/client.ts, src/mocks/api.ts, src/features/workspace/FeasibilityPanel.tsx, src/features/workspace/prototype/PrototypeStage.tsx, src/features/workspace/prototype/PendingList.tsx, src/features/workspace/chat/InterviewStage.tsx, src/features/workspace/build/BuildStage.tsx, tests/feasibility.test.tsx, tests/prototype.test.tsx, screenshots/
  - Depends on: 10.2
  - Size: M
  - Needs: backend 11.8
  - Done when: `npm test` and `npm run typecheck` pass, with tests asserting: (1) an assessment with `pending_comments` (fixture feasibility.pending.json) shows each target component id and comment text after remount; (2) Reapply saved comments posts `{assessment_id, batch_id}` once, is disabled while any issue is unresolved, and its `run.finished` refetches; (3) Discard pending comments sends DELETE with query `assessment_id` and renders the returned assessment; a stale-id rejection refetches and keeps the batch shown until the refetch says otherwise; (4) a resolved `stale` assessment enables Replan (or Reapply) while Generate recipe and Build stay disabled until `prototype_stale` is false, and the old preview carries a visible Stale label; (5) no decision, reapply or discard ever POSTs recipe or run. Manual at 1280x800 and 1440x900: screenshots/10.3-{pending,stale}-<viewport>.png; keyboard reapply and discard path with focus return; pin overlay aligned with the Stale label shown.
  - Review focus: ../contracts/dashboard-intent.md 1.1 (pending_comments, reapply, discard rules); the server stays the authority on stale and blocked states.

## Phase 11: Screenshot-only synthetic data (change 2026-10-19; split by delta audit 2026-10-20)
- [x] 11.1 Synthetic proposal, schema editor and generation
  - Goal: Connect with no source offers Generate sample data; propose a schema from a recreate reference or enter one by hand; review it as JSON with row count and seed; generate once with a request-bound key.
  - Spec: docs/reference-ui.md#Synthetic data controls; ../contracts/synthetic-data.md#HTTP workflow and provenance
  - Files: src/api/client.ts, src/api/types.ts, src/mocks/api.ts, src/mocks/fixtures.ts, src/features/workspace/connect/ConnectStage.tsx, src/features/workspace/connect/SyntheticDataPanel.tsx, src/features/workspace/ReferencePanel.tsx, src/features/activity/presets.ts, tests/contract.test.ts, tests/synthetic.test.tsx, screenshots/
  - Depends on: 10.3
  - Size: M
  - Needs: backend 12.3
  - Done when: `npm test` and `npm run typecheck` pass, with tests asserting: (1) contract.test imports proposal.json, request.json, dataset.json, job.succeeded.json, job.failed.json and source.json from ../contracts/fixtures/synthetic-data/ through exact guards, exposed via src/mocks/fixtures.ts; (2) Connect with zero sources shows Upload/connect data and Generate sample data; with a recreate set, Propose schema posts once and renders field names, types, generators and assumptions labeled as invented sample data; a style-only set explains why a schema is needed; manual schema entry works with no image; (3) invalid JSON in the schema textarea blocks Generate with an inline message; `422 invalid_generation_spec` field errors show inline at their field path and keep the user's edits; row count defaults to 1000 and seed to 42; (4) Generate posts once with a `generation_key`; a transport-error retry resends the identical request with the same key; any edit to spec, count or seed mints a new key; `409 synthetic_request_conflict` explains the request changed and mints a new key; `413` shows a 64 KiB request message; (5) nothing here POSTs decisions, recipe or run; the strip shows phrases for synthetic_schema and synthetic_generate. Manual at 1280x800 and 1440x900: screenshots/11.1-synthetic-{no-data,proposal,editing,invalid,busy}-<viewport>.png; keyboard path from Generate sample data through editing to Generate.
  - Review focus: ../contracts/api.md 1.5 and ../contracts/synthetic-data.md 1.1; labels separate generated values from screenshot facts; no new design system or storage selector.
- [x] 11.2 Synthetic status recovery, download and provenance
  - Goal: recover a generation job after reload, reconnect or a lost response; poll it to a terminal state; retry only after cleanup; download the CSV; keep Synthetic labels on Connect, Prototype, Build and Done.
  - Spec: docs/reference-ui.md#Synthetic data controls; ../contracts/synthetic-data.md#HTTP workflow and provenance
  - Files: src/api/client.ts, src/api/types.ts, src/mocks/api.ts, src/features/workspace/connect/SyntheticDataPanel.tsx, src/features/workspace/connect/ConnectStage.tsx, src/features/workspace/prototype/PrototypeStage.tsx, src/features/workspace/build/BuildStage.tsx, src/features/history/DoneStage.tsx, src/features/workspace/chat/useBuildStream.ts, tests/synthetic.test.tsx, screenshots/
  - Depends on: 11.1
  - Size: M
  - Needs: backend 12.3
  - Done when: `npm test` and `npm run typecheck` pass, with tests asserting (fake timers per Known gotchas): (1) a lost POST response is recovered by GET synthetic-data/jobs/{key} with no second POST; (2) polling runs every 2 s and stops on a terminal state and on unmount; (3) a failed job shows Retry only when `retry_ready` is true, and Retry uses a new key; (4) after remount a succeeded job restores dataset metadata and provenance; the source row shows a Synthetic badge from `source.kind` and a Download CSV link to the files endpoint; (5) a sample-data banner shows on Prototype, Build and the Done report-link view; a build with an existing real source offers New dashboard instead of generating; (6) success refetches build, sources, docs and assessment and never POSTs decisions, recipe or run. Succeeded status and dataset metadata come from the shared job.succeeded.json and dataset.json fixtures (via src/mocks/fixtures.ts from 11.1), never a copied file. Manual at 1280x800 and 1440x900: screenshots/11.2-synthetic-{success,failed-retry,reload}-<viewport>.png; keyboard screenshot-only -> proposal -> generate -> interview -> prototype path against the backend without a CSV, with Synthetic labels and no overflow or focus loss.
  - Review focus: ../contracts/api.md 1.5 and ../contracts/synthetic-data.md 1.1 (replay, retry_ready, provenance); no automatic build.
  - If: backend 12.5 is not `[x]` yet -> the label inside the backend-rendered prototype is not checked here (the UI's own source/prototype labels still are); release 2.5 checks it. Note this under Left open.

## Phase 12: Audit fixes (final re-audit 2026-10-20, after Phase 11)
- [x] 12.1 Strip test, steady feasibility refetch and Prototype fold
  - Goal: test the reference_extract and reference_delete strip phrases (10.1 Done when 7); a background refetch of the assessment or reference set keeps the panel, its controls and focus in place, and the gates keep their last loaded state until it lands (no "Loading feasibility…" blink, no Generate/Build flicker after each chat reply); on Prototype the References panel starts collapsed and a ready assessment with no open issue is one line, so the canvas top shows above the fold at 1280x800.
  - Spec: docs/reference-ui.md#Controls and states
  - Files: src/features/workspace/FeasibilityPanel.tsx, src/features/workspace/ReferencePanel.tsx, src/features/workspace/WorkspaceShell.tsx, src/features/workspace/prototype/PrototypeStage.tsx, src/features/workspace/chat/ChatPanel.tsx, tests/references.test.tsx, tests/feasibility.test.tsx, tests/prototype.test.tsx, AGENTS.md, screenshots/
  - Depends on: 11.2
  - Size: M
  - Done when: `npm test` and `npm run typecheck` pass, with tests asserting: (1) the strip shows a `presetFor('reference_extract')` phrase after its `run.started`, and the same for reference_delete (an `it.each` like tests/synthetic.test.tsx's synthetic node phrases); (2) with a loaded blocked assessment and focus on Use this alternative, a `run.finished` and a `docs.updated` whose GET is still pending leave the issue list mounted, `document.activeElement` unchanged and no "Loading feasibility…" text; with a loaded ready assessment, Generate plan stays enabled while that refetch is pending and follows the new result when it lands; a failed refetch still shows ErrorState and disables Generate plan, Generate recipe and Build; a late response for an older request is still dropped; (3) a ReferencePanel background refetch never reports references as not ready (Generate plan doesn't flicker); (4) on Prototype the References `<details>` is closed by default and open on Connect and Interview; chat Attach reference opens it and focuses the panel; a ready assessment with no unresolved issue renders one line of text. AGENTS.md: update or drop the two Known gotchas that rely on loading removing controls ("Resource-panel tests", "Feasibility test helpers"). Manual at 1280x800 and 1440x900: screenshots/12.1-prototype-<viewport>.png with the top of the prototype canvas visible without scrolling at 1280x800; keyboard (CDP): focus on Use this alternative survives a `docs.updated` refetch.
  - Review focus: fail-closed rules intact (first load, failed GET, stale, blocked); obsolete responses still dropped; the server stays the authority while a gate shows its last loaded state.

## Phase 13: Audit fixes (final re-audit 2026-10-20, after Phase 12)
- [x] 13.1 Steady feasibility focus test
  - Goal: make `npm test` reliable: the test "handles a finish arriving before the check POST returns" (tests/feasibility.test.tsx:67-78) checks heading focus before the refetch that moves it lands; it must await the focus instead, with the app code unchanged.
  - Files: tests/feasibility.test.tsx, tests/references.test.tsx
  - Depends on: 12.1
  - Size: S
  - Done when: `npm test` passes in 4 full-suite runs in a row (report each run's totals) and `npm run typecheck` passes; the focus assertion at tests/feasibility.test.tsx:77 is awaited (`waitFor`), and every other post-action focus assertion in tests/feasibility.test.tsx and tests/references.test.tsx that follows a status message is awaited the same way; `git diff` touches no file under src/.

## Phase 14: Staged workflow (change 2026-10-21)
- [x] 14.1 Contract 2.0 types, mocks, stepper and activity column
  - Goal: the app speaks api.md 2.0: new stages, artifacts, notes and artifact.updated; the mock serves every staged endpoint from the shared fixtures; the stepper shows eight stages with artifact states; the chat input and the Interview/Plan stage areas are gone, the left column is the activity log.
  - Spec: docs/staged-ui.md
  - Files: src/api/types.ts, src/api/client.ts, src/api/events.ts, src/mocks/*.ts, src/components/Stepper.tsx, src/features/workspace/WorkspaceShell.tsx, src/features/workspace/Stepper.tsx, src/features/activity/*, src/features/workspace/chat/*, src/features/workspace/plan/*, src/features/workspace/ReferencePanel.tsx, tests/contract.test.ts, tests/stepper.test.tsx, tests/*.test.tsx
  - Depends on: 13.1
  - Size: M
  - Done when: `npm test` and `npm run typecheck` pass: contract guards accept every fixture in ../contracts/fixtures/api/ (build, context, outline, design, design_presets, blueprint, events*.sse) and reject a Build with `ready_for_plan` or an unknown stage; mock mode walks every stage; the stepper shows draft/confirmed/stale and reopens a confirmed step; src/features/activity/presets.ts has entries for context, outline_propose, outline_other, outline_suggest, blueprint and prototype and none for interview or plan; no code calls interview/start, POST messages or POST plan; screenshots/14.1-workspace-{1280,1440}.png show the stepper and the activity column with no input, checked against docs/staged-ui.md and the UI design section.
  - Review focus: ../contracts/api.md 2.0 (exact guards); one EventSource; tokens only.
- [x] 14.2 Notes box and context review
  - Goal: Connect gets "About this data" notes and "Draft context"; the Context stage edits KPI cards, derived fields, thresholds and glossary in place, shows issues inline and confirms.
  - Spec: docs/staged-ui.md
  - Files: src/features/workspace/connect/*, src/features/workspace/context/*, src/mocks/*.ts, tests/context.test.tsx
  - Depends on: 14.1
  - Size: M
  - Done when: `npm test -- context` and `npm run typecheck` pass: notes over 4000 chars are blocked with a count; each KPI card switches between measure (field + agg selects filtered by type) and ratio (two KPI pickers); an issue path from the fixture lands on its card and field; Confirm is disabled with issues and a 409 artifact_invalid shows the issues; a PUT keeps focus in the edited field; screenshots/14.2-context-{1280,1440}.png checked against docs/staged-ui.md and the UI design section (density, states, contrast).
  - Review focus: ../contracts/api.md 2.0 context endpoints; keyboard path through every card; loading/empty/error states.
- [x] 14.3 Outline picker
  - Goal: sections of question checkboxes with Recommended badges, rationale and KPI chips; Suggest more per section; Other text per section or as a new section; selection count; confirm.
  - Spec: docs/staged-ui.md
  - Files: src/features/workspace/outline/*, src/mocks/*.ts, tests/outline.test.tsx
  - Depends on: 14.2
  - Size: M
  - Done when: `npm test -- outline` and `npm run typecheck` pass: ticking sends PUT outline/selection and keeps the scroll position; Recommended questions start ticked from the fixture; Re-propose keeps Other questions; Suggest more and Other show a run in the activity column and the new questions appear after artifact.updated; 25 selected disables Confirm with "24 at most"; an Other text asking for GPS animation shows the assistant's explanation in the activity column; screenshots/14.3-outline-{1280,1440}.png checked against docs/staged-ui.md and the UI design section.
  - Review focus: ../contracts/api.md 2.0 outline endpoints; checkbox semantics and labels for screen readers; no layout shift when questions arrive.
- [ ] 14.4 Design picker
  - Goal: preset cards, palette editor, font, page structure, density, title/subtitle and a mini preview; reference-prefilled values marked; confirm.
  - Spec: docs/staged-ui.md
  - Files: src/features/workspace/design/*, src/features/workspace/ReferencePanel.tsx, src/mocks/*.ts, tests/design.test.tsx
  - Depends on: 14.1
  - Size: M
  - Done when: `npm test -- design` and `npm run typecheck` pass: picking a preset fills every field; Reset to preset calls design/prefill; palette chips accept #RRGGBB only (3-8); a low-contrast issue from the server shows on the field; per_section shows the page count from the confirmed outline; source `reference` shows "From your reference"; screenshots/14.4-design-{1280,1440}.png checked against docs/staged-ui.md and the UI design section, user colors only as data swatches.
  - Review focus: ../contracts/api.md 2.0 design endpoints; swatches have text labels (not color alone); tokens elsewhere.
- [ ] 14.5 Blueprint review, prototype page tabs and the live staged walkthrough
  - Goal: the blueprint table with feasibility decisions and accept; page tabs on the prototype; the whole staged flow verified against the real backend.
  - Spec: docs/staged-ui.md
  - Files: src/features/workspace/blueprint/*, src/features/workspace/FeasibilityPanel.tsx, src/features/workspace/prototype/*, src/mocks/*.ts, tests/blueprint.test.tsx, tests/prototype.test.tsx
  - Depends on: 14.3; 14.4
  - Size: M
  - Needs: backend 15.11
  - Done when: `npm test` and `npm run typecheck` pass: the blocked ratio row from blueprint.json shows its issue with Use this alternative / Drop this requirement and Accept stays disabled until ready; Regenerate and Accept post their actions; page tabs read `data-page-name` from ../contracts/fixtures/api/prototype.multipage.html and pins stay on their page; manual (live, backend on 8000 with `DSS_ENGINE_DRY_RUN=1`): the sample CSV goes notes -> context -> outline (one Other) -> design per_section -> blueprint -> accept -> a 2+ page prototype -> one comment -> build `done`, with screenshots/14.5-{context,outline,design,blueprint,prototype}-1280.png checked against docs/staged-ui.md and the UI design section.
  - Review focus: ../contracts/api.md 2.0 (blueprint, Prototype HTML) and dashboard-intent.md 1.2; Feasibility panel reuse per docs/reference-ui.md; stale states after editing an earlier step.
