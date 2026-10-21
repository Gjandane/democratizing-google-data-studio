# Progress log
Append-only handoff log: one entry per session, newest at the bottom, written for someone with no
context. Task status lives in docs/plan.md, not here.

## 2026-10-18: Plan frontend (POC)
- Status: done
- What changed: wrote PRD, essentials (with UI design: Studio Light), plan (10 tasks), AGENTS.md, CLAUDE.md
- Decisions: same-origin via Vite proxy so the prototype iframe DOM is readable; mock mode (`VITE_MOCK=1`) against fixtures that match ../contracts/api.md, so the UI is built before the backend exists; the backend renders the prototype, the frontend only overlays comments; design foundation 1.2 stops for the user's screenshot sign-off.
- Baseline: new project: none
- Next: Task 1.1. Start by scaffolding Vite + React + TS and writing src/api/types.ts from ../contracts/api.md.

## 2026-10-18: Audit
- Status: done
- What changed: one reviewer audit across the program (18 findings: 2 P0, 4 P1, 9 P2, 3 P3 plus a pass note); all 18 accepted by the user and applied to contracts/ and every part's docs
- Decisions: backend thin slice 1.3 before memory depth; engine must-have ops by 21:00 with DSS_ALLOWED_TYPES as fallback; shared API fixtures in ../contracts/fixtures/api/; no uvicorn --reload on Windows; gates written into docs/program.md's roadmap
- Next: build, starting with task 1.1

## 2026-10-18: Task 1.1 App skeleton, typed client and mock mode
- Status: done
- Plan check: off
- What changed: Vite 8 + React 19 + TS 5.9 + Tailwind 4 app (all verified deps installed now: later tasks don't list package.json); `/api` proxy; src/api/types.ts (contract types + guards), client.ts (`ApiClient`, `httpApi`, `api`), events.ts (`useBuildEvents`); src/mocks/ (stateful fixture-backed `createMockApi`, fake stream); History route; tests.
- Checks: `npm test` PASS (2 files, 28 tests); `npm run typecheck` PASS; manual `VITE_MOCK=1 npm run dev` at :5173 shows the History list (yes; loading state and focus ring seen at 1280x800; no screenshots required).
- Decisions: guards are exact (extra keys fail), `problemsOf(guard, value)` names each mismatch; `api` = mock when `VITE_MOCK=1`, tests run with it (vite.config `test.env`), `resetMockState()` per test, `httpApi` importable for fetch-level tests; `ApiError{status,code,message,detail}` in types.ts; proxy's empty 502-504 → `network_error`; `useBuildEvents(id, onEvent, open?)` returns `connecting|open`, reopens with 1-15 s backoff after EventSource gives up; consumers re-fetch on every `ready`; mock `prototypeUrl` = same-origin blob URL of prototype.sample.html (jsdom: plain path); mock plays stage/run events per contract (STEP_MS 400, 0 in tests); src/index.css (Tailwind entry, outside Files, 1.2 extends) and .claude/launch.json added.
- Tried and failed: none
- Gotchas: see AGENTS.md Known gotchas (2 added).
- Left open: P3 no fetch timeout; 2xx non-JSON throws SyntaxError - src/api/client.ts; P3 mocks + fixture validation load in real mode too (static import) - src/api/client.ts; P3 `fs.allow: ['..']` exposes ../data and ../.chrome-profile via /@fs/ on localhost, essentials prescribe it (architect note: `['.', '../contracts']`) - vite.config.ts; P3 panel radius 8 px not 10 - HistoryPage.tsx (tokens in 1.2).
- Next: Task 1.2. Start by writing src/styles/tokens.css from the essentials' palette, then restyle HistoryPage with tokens.

## 2026-10-18: Task 1.2 Design foundation
- Status: done
- Plan check: off
- What changed: src/styles/tokens.css (Tailwind @theme, defaults cleared: only tokens exist); index.css (fonts, base, focus ring, reduced motion); src/components/ Button, Input/TextArea, Panel, Pin, Popover, Toast/ToastRegion, Spinner/LoadingState, EmptyState, ErrorState, Modal, Table, focus.ts; workspace/Stepper.tsx + WorkspaceShell.tsx (route `/builds/:id`); History restyled; App routes; tests/components.test.tsx.
- Checks: `npm test` PASS (3 files, 52 tests); `npm run typecheck` PASS; hex regex (Grep tool, rg not on PATH) matches only tokens.css; manual 1280x800 + 1440x900 via headless Chrome: History list/empty/error yes, shell (48 px bar, aside 380 px, stepper on Connect) yes, no overlap (scrollWidth 1280), focus ring 2 px #1E40AF on every control yes; screenshots/1.2-*.png (13). User signed off the look (STOP).
- Decisions: token classes: bg/surface/surface-muted/text/text-muted/border/border-strong(added #94A3B8)/primary(-hover,-soft)/accent(-hover)/success(-soft 5%)/danger(-hover,-soft)/focus; text-caption 12, label 13, body 14, title 16, heading 20, display 24; rounded-control/panel; shadow-popover; layout vars `--layout-topbar|chat|page` used as `w-(--layout-chat)`. `focusRing` in components/focus.ts. Button variants primary/secondary/ghost/accent/danger/inverse, sizes sm 28/md 32, `loading`, `buttonClass()` for links. Popover (non-modal, Esc/outside press, tone dark/light) and Modal (portal, focus trap, Esc, focus return) take `initialFocus`. Shell: Trace/Settings disabled until `onOpenTrace`/`onOpenSettings` props; stage areas are placeholders in `STAGE_VIEWS`, chat column a placeholder in `ChatColumn`: stage/chat tasks mount by editing WorkspaceShell.tsx (outside their Files: say why). Inter + Fira Code from Google Fonts (user kept it, reviewer read the /api rule as covering it).
- Tried and failed: none
- Gotchas: see AGENTS.md Known gotchas (3 added).
- Left open: none (review P2/P3s fixed: badge contrast, shell retry focus, outline-color transition, toast live region, long-title shot).
- Next: Task 2.1. Start by building src/features/workspace/connect/ and replacing `STAGE_VIEWS.connect` in WorkspaceShell.tsx with it.

## 2026-10-18: Task 2.1 Connect stage
- Status: done
- Plan check: off
- What changed: new src/features/history/NewBuildDialog.tsx (title, 4 archetype cards, data/research mode, createBuild then navigate) and src/features/workspace/connect/ConnectStage.tsx (drop zone + "Choose CSV files", GCS/BigQuery URI form, sources table with column chips, error state, "Start interview"); tests/connect.test.tsx (10); outside Files: HistoryPage.tsx ("New build" button, dialog mounted only while open), WorkspaceShell.tsx (mounts ConnectStage on `connect`, focuses `main` on stage change). client.ts/mocks unchanged.
- Checks: `npm test` PASS (4 files, 61 tests, stable over 4 runs); `npm run typecheck` PASS; hex regex only tokens.css; manual via headless Chrome at 1280x800 + 1440x900: empty, uploading, error, filled yes; screenshots/2.1-connect-{empty,uploading,error,filled}-{1280x800,1440x900}.png, 2.1-newbuild-dialog-1280x800.png.
- Decisions: built by a Sonnet worker from build notes (one call for all dropped files, server validates; ConnectStage props `{build, onBuildChange}`). `ARCHETYPE_INFO` (label + one-liner) exported from NewBuildDialog. Async callbacks read the latest build via ref (no lost sources); 422 errors offer Dismiss only, others Try again; URI field goes readOnly while busy and focus returns to it; startInterview never re-POSTs: if the follow-up getBuild fails the stage is set to interview locally; window-level dragover/drop prevented while on Connect.
- Tried and failed: `toBeDisabled` (no jest-dom).
- Gotchas: see AGENTS.md Known gotchas (3 added).
- Left open: P3 "Start interview" below the fold at 1280x800 - ConnectStage.tsx; P3 unused STAGE_VIEWS.connect icon/title/text - WorkspaceShell.tsx; one-off failure of the shell "Try again" focus test seen once mid-edit, not reproduced in 4 later runs - tests/components.test.tsx.
- Next: Task 2.2. Start by building src/features/workspace/chat/ and replacing `ChatColumn` in WorkspaceShell.tsx with it.

## 2026-10-18: Task 2.2 Chat panel with streaming and Interview stage
- Status: done
- Plan check: off
- What changed: new src/features/workspace/chat/ useBuildStream.ts (the one event stream per open build + chat state), ChatPanel.tsx (log, markdown bubbles, streamed drafts, composer), InterviewStage.tsx (sources, archetype, questions answered, Generate plan), Markdown.tsx; tests/chat.test.tsx (14). Outside Files: WorkspaceShell.tsx (`Workspace` child calls useBuildStream once, mounts ChatPanel + InterviewStage; stage-change focus skips when focus is outside main), HistoryPage.tsx + WorkspaceShell.tsx retry focus -> useLayoutEffect (fixed pre-existing history.test flake).
- Checks: `npm test` PASS (5 files, 75 tests, 8 consecutive runs green); `npm run typecheck` PASS; hex regex only tokens.css; manual via headless Chrome at 1280x800 + 1440x900: long messages wrap yes, list scrolled to newest yes, loading yes, error yes, streaming yes, ready yes; screenshots/2.2-chat-{loading,error,interview,streaming,ready}-{1280x800,1440x900}.png.
- Decisions: built by a Sonnet worker from build notes (hook owns stream; `ready` refetches build + messages; optimistic `local-N` bubble swapped to server id). `useBuildStream(build, onBuildChange, open?)` returns `{messages|null, loadError, drafts, status, reload, send, sendError}`; later stages read stage/build events through it (it calls onBuildChange for `build.updated`/`stage.changed`). Refetch merges by id and skips the build if a build event arrived meanwhile; `latest` ref set synchronously; failed `run.finished` clears drafts; drafts aria-hidden; composer locked until messages load and in connect. Generate plan enabled before ready (secondary), stage change left to events.
- Tried and failed: none.
- Gotchas: see AGENTS.md Known gotchas (2 added). Skills frontend-design/ui-ux-pro-max not invoked by the worker.
- Left open: P3 panel headings are h2 under the stage h2 - InterviewStage.tsx (Panel has no level prop); P3 code block has no box inside panels (bg-surface) - Markdown.tsx; P3 markdown links lack "opens in a new tab" - Markdown.tsx; P3 fallback error copy repeats title - useBuildStream.ts; P3 Generate plan below the fold with many answers at 1280x800 - InterviewStage.tsx.
- Next: Task 2.3. Start by building src/features/workspace/plan/ and replacing `STAGE_VIEWS.plan` in WorkspaceShell.tsx's StageArea; stream events come from useBuildStream.

## 2026-10-18: Task 2.3 Plan stage
- Status: done
- Plan check: off
- What changed: new src/features/workspace/plan/PlanStage.tsx (progress panel, docs list + markdown viewer) and tests/plan.test.tsx (8). Outside Files: chat/useBuildStream.ts (owns the one stream: now returns `progress: ProgressLine[]` and `planning`, handles node.progress, run.started reset, docs.updated -> build.docs) and WorkspaceShell.tsx (mounts PlanStage for stage `plan`). src/mocks unchanged (already emits the events and serves getDoc).
- Checks: `npm test` PASS (6 files, 84 tests, 3 consecutive runs green); `npm run typecheck` PASS; no raw hex/px in plan/; manual via headless Chrome at 1280x800 + 1440x900: waiting/loading yes, empty docs yes, progress yes, docs list + doc open yes, doc loading yes, doc error yes; screenshots/2.3-plan-{waiting,progress,docs,doc-loading,doc-open,doc-error}-{1280x800,1440x900}.png (taken before the last review fixes, which changed no layout).
- Decisions: `PlanStage({build, progress, planning})`; spinner shows on the last line only while a `plan` run is open (run.started/run.finished node `plan`); lines from other nodes are filtered out; docs are not auto-selected; an open doc refetches silently when `build.docs` changes identity; a selected doc that leaves the list is deselected. Doc headings styled via class variants on Markdown (shared component untouched). Skills frontend-design / ui-ux-pro-max not invoked (tokens and existing components reused).
- Tried and failed: none.
- Gotchas: see AGENTS.md Known gotchas (1 added).
- Left open: P3 doc `# Title` renders as h1 inside the h2 panel (Markdown has no heading offset) - PlanStage.tsx; P3 progress lines' done/running state is icon-only (aria-hidden), no sr-only text - PlanStage.tsx.
- Next: Task 3.1. Start by building src/features/workspace/prototype/ and replacing the prototype stage placeholder in WorkspaceShell.tsx's StageArea; `build.spec_version` and `prototype.updated` come through useBuildStream.

## 2026-10-18: Task 3.1 Prototype stage with click-to-comment
- Status: done
- Plan check: off
- What changed: new src/features/workspace/prototype/ (PrototypeStage, PrototypeCanvas, CommentPopover, PendingList, types.ts), tests/prototype.test.tsx (20). Outside Files: chat/useBuildStream.ts (`prototype.updated` -> build.spec_version; `applying`, `commentsError{seq,text}`; `ready` resets applying) and WorkspaceShell.tsx (mounts PrototypeStage). src/mocks: one stale comment fixed.
- Checks: `npm test` PASS (7 files, 104 tests); `npm run typecheck` PASS; no raw hex/px in prototype/; manual via headless Chrome at 1280x800 + 1440x900: canvas fits stage (scale 0.71 / 0.843) yes, pins inside their elements after a 200 px resize yes, popover never intersects its element yes; screenshots/3.1-prototype-{ready,hover,popover,pins,applying}-{1280x800,1440x900}.png.
- Decisions: built by a Sonnet worker from build notes (transparent target buttons per `[data-cid]` in the scaled pin layer, reading order, z by area so smaller boxes win; boxes read in iframe viewport coords on load, nothing injected; tag/pins counter-scaled; popover outside the scale wrapper, below else above). `PrototypeStage({build, applying, commentsError})`; frame size = max(canvas right/bottom, lowest box); targets disabled + veiled while applying; sent batch cleared on spec_version change; iframe tabIndex -1. Skills frontend-design / ui-ux-pro-max not invoked.
- Tried and failed: none.
- Gotchas: see AGENTS.md Known gotchas (1 added).
- Left open: P3 unapplied comments are lost on leaving the stage or a re-plan, no warning - PrototypeStage.tsx; reconnect mid-run re-enables Apply (applying reset on `ready`) - useBuildStream.ts.
- Next: Task 3.2. Start by building src/features/workspace/build/ and replacing the build stage placeholder in WorkspaceShell.tsx's StageArea.

## 2026-10-18: Task 3.2 Build stage
- Status: done
- Plan check: off
- What changed: new src/features/workspace/build/ (buildRun.ts reducer, BuildStage, EnginePanel, RecipePanel), tests/build.test.tsx (29); src/mocks/api.ts: `setMockEngine`, `setMockBuildOutcome('ok'|'partial'|'failed')`, 1200 ms build steps in dev, run.finished in the same step as build.finished. Outside Files: useBuildStream.ts (`buildRun` via reduceBuildRun: the build's one EventSource lives there), WorkspaceShell.tsx (mounts BuildStage, "Continue to build"/"Back to prototype"), PrototypeStage.tsx (`onPendingChange`).
- Checks: `npm test` PASS (8 files, 133 tests); `npm run typecheck` PASS; no raw hex/px in build/; manual via headless Chrome at 1280x800 + 1440x900: signed-out, recipe, running, partial, failed, done show yes; link target=_blank rel=noopener noreferrer yes; no horizontal scroll yes; focus ring yes; screenshots/3.2-build-*.png (13).
- Decisions: built by a Sonnet worker from build notes (reducer folds build.op/build.finished/run.finished; UI running = `build.stage === 'build'`, so a missed event can't lock it). Build view: from prototype via "Continue to build" (disabled while comments pending), auto-opens when a run starts, stays open in done after a run (3.4 owns Done for builds opened from History); failed keeps the card, stage back to prototype. "N ops failed" counted from build.op ("Some ops failed" if 0). Recipe in BuildStage state, auto-compiled once if opened mid-run; regenerating hides the previous run's results (`compiledFor`). Done stage: Build hidden, hint "Start a new version to build again." One sr-only role=status for the outcome. Engine login polls status every 2 s, max 5 min, sequence-guarded. Skills frontend-design / ui-ux-pro-max not invoked.
- Tried and failed: none.
- Gotchas: see AGENTS.md Known gotchas (1 added).
- Left open: none (review P1-P3 fixed).
- Next: Task 3.3. Start by reading its Files in docs/plan.md and wiring WorkspaceShell's `onOpenTrace`/`onOpenSettings`.


## 2026-10-18: Task 3.3 Settings and Trace tab
- Status: done
- Plan check: off
- What changed: new src/features/settings/ (serviceNotice.ts: `withServiceNotice(api)` reports 503 `llm_unavailable`/`gcp_not_configured`; SettingsModal, ServiceBanner, AppServices provider with `useAppServices()` -> `openSettings`, `openTrace(buildId?)`), src/features/trace/TraceModal.tsx, tests/settings.test.tsx (21). src/mocks/api.ts: `setMockSettings`, `setMockServiceFault('llm_unavailable'|'gcp_not_configured'|null)`; model actions answer 503 without a key, upload/add-source without a project. Outside Files: App.tsx (provider + `WorkspaceRoute` wires the top bar), api/client.ts (`api = withServiceNotice(...)`, needed for "any action"), WorkspaceShell.tsx (`h-dvh` -> `h-full`: the provider now owns the viewport column that holds the banner), components/Modal.tsx (size `lg` for the Trace table).
- Checks: `npm test` PASS (9 files, 154 tests); `npm run typecheck` PASS; manual via headless Chrome at 1280x800 + 1440x900: focus stays in the dialog over 50 Tab/Shift+Tab, Esc closes, focus returns to the Settings button, key field empty after save, "Key set" shown, trace totals 18,130 / 3,390, no horizontal scroll, banner button opens Settings yes; screenshots/3.3-{workspace-clean,settings-keyset,settings-edited,settings-saved,trace-table,banner-503,banner-missing}-{1280x800,1440x900}.png.
- Decisions: Settings and Trace are modals (Trace starts on "This build" when opened from a workspace, toggle "All builds"); modals mount fresh on each open. Banner shows when `google_api_key_set` is false or the project is empty (read once at app load, refreshed on save) or after any 503 of the two codes; Dismiss hides that message until the next failure; a save clears it. Save sends only changed (trimmed) fields plus the key when typed; the key lives only in the input state, cleared after save; the modal stays open and says "Settings saved.". Skills frontend-design / ui-ux-pro-max not invoked.
- Tried and failed: none.
- Gotchas: see AGENTS.md Known gotchas (2 added).
- Left open: P3 closing the modal drops unsaved edits with no warning - AppServices.tsx; P3 `src/api` now imports from `src/features/settings` (client.ts wrap), against the folder map's direction.
- Next: Task 3.4. Start by reading its Files in docs/plan.md; Done stage is mounted in WorkspaceShell.tsx's StageArea (the `done` branch is still the EmptyState placeholder).

## 2026-10-18: Task 3.4 Done stage and history versions
- Status: done
- Plan check: off
- What changed: new src/features/history/DoneStage.tsx (link card, Versions list newest first with per-version link/status, "New version" -> `api.createVersion` -> `onBuildChange`), tests/versions.test.tsx (7). WorkspaceShell.tsx: `done` branch mounts DoneStage; EmptyState import dropped. History and mocks unchanged (History already showed stage + link; mock `createVersion` already existed).
- Checks: `npm test` PASS (10 files, 161 tests, versions 7); `npm run typecheck` PASS; no raw hex in DoneStage; manual via headless Chrome at 1280x800 + 1440x900: done stage, versions list, "New version" lands on Prototype, no horizontal scroll yes; screenshots/3.4-{history,done,new-version}-{1280x800,1440x900}.png.
- Decisions: Done view shows when a done build is opened (History) and after "Back to versions" from a run's result; a run that finishes in the session keeps the Build result open in done (3.2 decision) with a "Back to versions" button. A run result whose `finished.version` != `current_version` is treated as idle (no stale v1 result under v2). Partial run in this session shows "N ops failed" on the link card. No-link card is neutral, not green. "Failed" pill uses text-text for 4.5:1. DoneStage lives in history/ (Files lists history/*). Skills frontend-design / ui-ux-pro-max not invoked.
- Tried and failed: none.
- Gotchas: none new.
- Left open: P2 no test renders a run finishing inside WorkspaceShell (Back to versions, stale-run reset) - tests/versions.test.tsx; P2 nothing on screen names the new version (v2) on the Prototype stage - WorkspaceShell.tsx.
- Next: Task 4.1. Start by reading its Files in docs/plan.md (stretch: style images, research prompt, UX audit, live build frames).

## 2026-10-19: Task 4.1 Style images, research prompt, audit and screencast
- Status: done
- Plan check: off
- What changed: connect/StylePanel.tsx + ResearchPanel.tsx (research mode only), "Run UX audit" in PrototypeStage, build/LiveViewPanel.tsx (BuildRun.frame from `build.frame`, reset on build run.started), new workspace/stretch.ts, mocks (png/jpg check, research source, audit findings message, frames via mocks/frame.ts + `setMockScreencast`), tests/stretch.test.tsx (18). Outside Files: useBuildStream.ts (`stretchRuns` per node from run.started/finished, running dropped on `ready`), WorkspaceShell.tsx (passes stretchRuns; `relative` on main), tests/build.test.tsx (`frame: null`).
- Checks: `npm test` PASS (11 files, 179 tests, stretch 18); `npm run typecheck` PASS; manual via headless Chrome at 1280x800 + 1440x900: style saved, research done + new source, audit done + findings in chat, live view mid-run, document overflow 0 yes; screenshots/4.1-{connect-style,connect-research,prototype-audit,build-live}-{1280x800,1440x900}.png.
- Decisions: built by a Sonnet worker from build notes. A 404 whose code isn't `build_not_found` hides the control, remembered per session (module set, `resetStretchAvailability()` for tests). `useStretchAction` follows its own run_id, adopts a newer run of the node (another tab), and `useRefocusAfter` returns focus when the action ends. Audit status is aria-live, not role=status (prototype tests use getByRole('status')). Review P2s fixed: stuck "running", document scroll from the sr-only status, focus loss. Skills frontend-design / ui-ux-pro-max not invoked.
- Tried and failed: none.
- Gotchas: see AGENTS.md Known gotchas (1 added, 1 extended).
- Left open: P3 no fetch-level test that each action hits its route - tests/stretch.test.tsx; P3 live view img has no intrinsic size (shift on first decode) - build/LiveViewPanel.tsx; P3 a POST accepted while the stream is down stays "running" until remount - stretch.ts.
- Next: Task 5.1 Access-code gate and build-agent status. Start by reading its Files and Spec in docs/plan.md.

## 2026-10-19: Change Cloud Run deployment (program root)
- Status: done
- What changed: the architect, at the program root, lifted Cloud Run from non-goal to goal and moved the deadline to 2026-10-20 01:05 MPST; contracts/api.md and contracts/conventions.md are now 1.1 (access code, agent mode, agent endpoints, Cloud deployment, Build agent); a reviewer delta audit (33 findings) was applied.
- Affects: new task 5.1 (access-code gate, agent panel, settings lock, 32 MB limit), built against the fixtures; essentials conventions updated.
- Next: task 5.1.

## 2026-10-20: Task 5.1 Access-code gate and build-agent status
- Status: done
- Plan check: off
- What changed: src/features/access/ (AccessGate around AppServicesProvider in App.tsx, accessNotice wrapper on `api` for `401 access_required`); client `getSession`/`createSession`, 413 mapping and 32 MB pre-check (`oversizeError`, `UPLOAD_LIMIT_BYTES` in types.ts); EngineStatus 1.1 fields, `Session`, `Job` guards; EnginePanel agent states (offline + copyable `dss-agent` command, signed-out "Run dsengine login", connected); BuildStage `onEngine`/`offlineSignal`; SettingsModal lock on `403 settings_locked`; mock: `setMockSession`, `MOCK_ACCESS_CODE`, agent-mode 424/409/403, gate on every gated call; tests access (8), agent-status (9), contract (+6).
- Checks: `npm test` PASS 13 files / 202 tests in 3 of 4 runs; 1 run had 1 failed test (not identified, did not recur in 2 reruns); `npm run typecheck` PASS; `npm run build` PASS, base `/`, assets under `/assets/`, no mock code, no `localhost:<port>`/`127.0.0.1`/`run.app` in dist; manual at 1280x800 + 1440x900: gate, agent offline/signed-out/ready yes, no horizontal scroll yes; screenshots/5.1-{gate,agent-offline,agent-signed-out,agent-ready}-{1280x800,1440x900}.png.
- Decisions: built myself, not delegated (cross-cutting, deadline). dist still holds literal `http://localhost` twice inside react-router's own code (dummy URL base) plus library doc links and the Google Fonts @import: no app origin; accepted. Mock kept out of prod via `/* @__PURE__ */` on `seed()` and the fixtures IIFE. Gate wraps the whole app (local mode shows "Checking access…" briefly; backend down → gate's error with retry). Settings lock learned from the first 403 (module flag), not up front. `setMockEngine` takes a Partial merged over engine_status.local.json.
- Tried and failed: none.
- Gotchas: Git Bash `sed -i` strips CRLF to LF on the whole file: restore endings after.
- Left open: P2 literal localhost in react-router bundle - dist; P3 EventSource/iframe 401 not routed to gate - src/api/events.ts; P3 stale in-flight 401 can re-lock after success - AccessGate.tsx; P3 lock only after failed save - SettingsModal.tsx; P3 command `<code>` not keyboard-scrollable - EnginePanel.tsx; P3 gate screenshot shows the session-ended hint; one unidentified test flake.
- Next: none in frontend plan; final audit / deploy.

## 2026-10-19: Change activity transparency (program root)
- Status: done
- What changed: the user asked for UI transparency like a coding agent's task list (what is happening, elapsed time, tokens), with preset wording. contracts/api.md is now 1.2: `run.usage {run_id, node, input_tokens, output_tokens}` (running totals) and the list of `node` values; new fixture contracts/fixtures/api/events.usage.sse (events.sse unchanged, so the app still loads). PRD goal 7 and Features, essentials UI design "Activity" and Contracts row updated.
- Affects: new task 6.1 (activity strip and run checklist), built against the fixture; no gate on backend 10.1 (without it the strip shows phrase and time, no tokens). Until 6.1 is done, `npm test` fails one check (contract.test.ts "has a check for every fixture file": events.usage.sse); the app itself is unaffected (fixtures.ts imports files by name; unknown live events are ignored).
- Next: task 6.1.

## 2026-10-19: Task 6.1 Activity strip and run checklist
- Status: done
- Plan check: off
- What changed: new src/features/activity/ (presets.ts phrases+steps per contract node, activity.ts reducer/selectors/clock/formatters, ActivityStrip.tsx above the composer, RunCard.tsx at the end of the chat log); useBuildStream returns `activity` (runs keyed by buildId); ChatPanel mounts both; types.ts `run.usage` + guard; mock startRun emits growing `run.usage` before each step; contract test covers events.usage.sse; tests/activity.test.tsx (16, fake timers).
- Checks: `npm test` PASS (14 files, 221 tests); `npm run typecheck` PASS; `npm run build` exit 0; manual headless Chrome: log height same before/with strip (601/601 at 1280x800, 701/701 at 1440x900), strip + plan card mid-run and done yes; screenshots/6.1-activity-{running,done}-{1280x800,1440x900}.png.
- Decisions: built myself, not delegated (design already settled while exploring). Clock lives in the strip/card (setTimeout to the next visible change, cleared every render/unmount), not in useBuildStream, so the workspace doesn't re-render each second. Strip slot always h-8 (no shift). Card = newest run with steps, shown once it outlasts 400 ms, stays after finish until the next stepped run; `aria-live="off"`; scrolls the log when it appears. Strip announces start phrase and end line once (sr-only status). Tokens floor to one decimal (92.5k). Legacy node names ('build','comments','style','audit') mapped to contract names in presets.ts ALIASES.
- Tried and failed: none.
- Gotchas: tests/agent-status.test.tsx "424 agent_offline" flakes ~1 in 6 on baseline too (not from this task).
- Left open: P2 contract 1.2 node names (revise, style_extract, ux_audit, execute) not matched by useBuildStream/buildRun.ts/mocks - useBuildStream.ts; P2 finished card stays pinned under later messages - activity.ts cardRun; P2 agent-status flake - tests/agent-status.test.tsx.
- Next: all frontend tasks done; next is the program's final audit (architect).

## 2026-10-19: Task 6.2 Contract 1.2 run node names
- Status: done
- Plan check: off
- What changed: task added by the architect after the 6.1 review P2 (user asked to record it as a task). Run `node` checks now use the contract 1.2 names: useBuildStream `revise` (applying/commentsError), StretchNode keys `style_extract`/`research`/`ux_audit` (StylePanel, PrototypeStage pass them), buildRun.ts `execute`; mock startRun/progress/run.finished and the audit message node use the same names; tests build/plan/prototype/stretch emit them. presets.ts ALIASES and `canonicalNode` removed (activity.ts stores the node as sent).
- Checks: Grep for run `node` values 'comments'/'style'/'audit'/'build' in src/ and tests/ finds none (only StretchRoute 'audit', an API route); `npm run typecheck` PASS; `npm test` 14 files / 221 tests: PASS 1 of 4 runs, the other 3 had 1 failure each, always tests/agent-status.test.tsx "424 agent_offline" (uses no stream events); same test fails 1 of 4 isolated runs at HEAD 65126e9 in a temp worktree, so pre-existing.
- Decisions: renamed StretchNode keys to the contract names (2 call sites) rather than mapping them. Mock audit message `node` also `ux_audit` (Message.node, nothing matches on it).
- Tried and failed: none.
- Gotchas: none new.
- Left open: P2 agent-status "424 agent_offline" flake (seen 3 of 4 full runs this session, more often than 6.1's ~1 in 6) - tests/agent-status.test.tsx; P2 finished card stays pinned under later messages - activity.ts cardRun (from 6.1).
- Next: program final audit (architect).

## 2026-10-19: Fix agent-status 424 flake (no plan task)
- Status: done
- Plan check: off
- What changed: the bug was in the app, not the test. On `424 agent_offline` BuildStage only bumped `offlineSignal`; EnginePanel's passive effect then set its load (panel text "Build agent offline" committed) and its `report` effect told BuildStage one commit later. In between Build stayed enabled next to the offline panel, and `findByText` could resolve there. BuildStage.start now also marks its own `engine` offline (`mode: 'agent', agent_connected: false`) in the same batch, so Build turns off before the panel text appears. Test unchanged.
- Checks: reproduced first, 2 of 6 isolated runs failed at agent-status.test.tsx:94. After fix: `npx vitest run tests/agent-status.test.tsx` 10 of 10 PASS (9 tests); `npm test` 3 of 3 PASS (14 files / 221 tests); `npm run typecheck` PASS.
- Decisions: fixed the one-commit UI lag in the app over adding a `waitFor` in the test, which would have hidden a clickable Build button next to "agent offline". Not recorded as a plan task (no blueprint task existed for it).
- Tried and failed: none.
- Gotchas: none new (same class as the useLayoutEffect gotcha: state reported up through a passive effect lags the child's DOM by a commit).
- Left open: P2 finished card stays pinned under later messages - activity.ts cardRun (from 6.1).
- Next: program final audit (architect).

## 2026-10-19: Audit (final)
- Status: done
- Verdict: DEFECTS (0 P0, 0 P1, 4 P2, P3s); Phase 7 added (7.1 run errors and the finished run card, M; 7.2 contrast and small UI fixes, S).
- Checks rerun (first final audit, so everything): `npm test` 14 files / 221 tests PASS 4 of 4 full runs (424 flake fix d7a472a holds); `npm run typecheck` PASS; `npm run build` exit 0, base `/`, assets under `/assets/`, `localhost` only inside react-router/vfile code; 1.2 hex search none; 6.2 node-name search none; secrets: no .env in frontend or its git history; fresh screenshots screenshots/audit-{history,prototype,done}-{1280x800,1440x900}.png, no horizontal scroll.
- Reviewer (blueprint-reviewer, opus high, with web-design-guidelines on src/): Review focus 3.1, 5.1, 6.1, 6.2 pass; no Non-goal built; package.json matches the verified table. P2: plan/interview/spec run errors never shown (useBuildStream.ts run.finished); Google Fonts @import vs the "only /api" rule; Trace "Error" pill ~4.3:1; finished run card pinned under later messages.
- Decisions (user): fix all four P2s plus a quick P3 bundle (7.1, 7.2); Google Fonts kept, so the essentials' Never do and 5.1's Done when now name it as the one exception; the other P3s and earlier Left open items are known limitations in the PRD's Later list.
- Docs: essentials Conventions gained the testing, guards, node-name, activity, focus/effect and settings-lock conventions from task Decisions and Known gotchas; UI design gained the "Activity" item plan 6.1 points to; the @types/react-dom row's extra cell removed. AGENTS.md Known gotchas: moved truncate, jest-dom, useLayoutEffect and mock knobs into the essentials, merged the sed -i line into line endings, split the cp1252 line.
- Left open: typescript row Verified shows 7.0.2 (latest) while the range is `>=5.5 <6` and 5.9.3 is installed: not re-verified (needs `deps`).
- Next: task 7.1.

## 2026-10-19: Task 7.1 Run errors and the finished run card
- Status: done
- Plan check: off
- What changed: useBuildStream gains `runErrors` (plan/spec/interview `run.finished` error text, fallback `RUN_ERROR_FALLBACK`); InterviewStage shows plan/spec errors as ErrorState (role=alert, "Generate plan again"); ChatPanel shows the interview error above the composer and places the run card in time order; activity runs carry `after`; mock knob `setMockRunFailure(node, error)`.
- Checks: `npm test` PASS 14 files / 228 tests (new: 5 in chat.test.tsx "Run errors", 2 card-order tests in activity.test.tsx; the pre-load anchor test fails on the unfixed code); `npm run typecheck` PASS; manual: yes, screenshots/7.1-interview-error-{1280x800,1440x900}.png, screenshots/7.1-card-later-message-{1280x800,1440x900}.png (headless Chrome over CDP, mock on 5199).
- Decisions: card anchor = message count known synchronously at `run.started` (a ref mirrors every messages update), not created_at vs client clock (skew); `after: null` before the first load, filled with the loaded count when it lands. A plan `run.started` also clears spec and interview errors. Interview error from the server gets " Send your answer again." appended (fallback already says it). WorkspaceShell.tsx (outside Files): 4 lines passing `runErrors` to InterviewStage, its only caller. Built in-session, not delegated: small, intertwined change.
- Tried and failed: none
- Gotchas: a `ready` event drops running runs, so a test of "run started before the chat loaded" must fire `ready` first, then `run.started` before advancing timers.
- Left open: P3 plan and spec errors can both show if spec fails inside a plan run - src/features/workspace/chat/InterviewStage.tsx; P3 anchor moves up one if a counted optimistic bubble's send fails mid-run - src/features/workspace/chat/useBuildStream.ts
- Next: Task 7.2. Start by reading its Files in docs/plan.md.

## 2026-10-19: Task 7.2 Contrast and small UI fixes
- Status: done
- Plan check: off
- What changed: Trace "Error" pill `text-text` on `bg-danger-soft`; `formatLatency` rounds to tenths before choosing the unit (119600 → "2 min 0 s", 59960 → "1 min 0 s"); Build result link and markdown links carry sr-only "(opens in a new tab)" (markdown rel now `noopener noreferrer`); PrototypeStage comment names `revise`; a done build with no messages says "No messages were kept for this build."
- Checks: `npm test` PASS 14 files / 230 tests (new asserts in settings, build, chat tests); `npm run typecheck` PASS; search of src/ for "`comments` run": 0 hits; manual: yes, screenshots/7.2-trace-error-1280x800.png (trace listing patched from the page with one error run).
- Decisions: link tests match `/^Open in Data Studio/` plus a textContent check, since the accessible name now includes the sr-only text.
- Tried and failed: none
- Gotchas: none new (sed -i CRLF flip already in Known gotchas; hit again, restored).
- Left open: none from review (P3 directional copy fixed). Pre-existing: trace total row wraps "2 min 43 s" at 1280; markdown link has no hover state.
- Next: Phase 7 done; all plan tasks [x].

## 2026-10-19: Audit (final, re-audit after Phase 7)
- Status: done
- Verdict: DEFECTS (0 P0, 0 P1, 0 P2, 4 P3); user chose to fix all four: Phase 8 added (8.1 retry guard, error punctuation, trace wrap and link hover, S).
- Checks rerun (re-audit: Test (all) plus 7.1, 7.2 Done when; earlier tasks whose Files they touched, 2.2, 2.3, 3.1, 3.2, 3.3, 6.1, are covered by the same `npm test`): `npm test` 14 files / 230 tests PASS; `npm run typecheck` PASS; `npm run build` exit 0, default base `/`, absolute URLs in dist only w3.org, react docs, react-router `localhost` and fonts.googleapis.com; hex search of src/components and src/features none; "`comments` run" search none; 6.2 node-name search none (only stage/scope `'build'`); secrets: no .env in frontend or its git history. Skipped: earlier manual screenshot checks of tasks 7.x didn't touch; no fresh core-screen screenshots, the reviewer used 7.1/7.2 screenshots (taken after the changes) plus the first audit's audit-* set.
- Reviewer (blueprint-reviewer, opus high, with web-design-guidelines on the 7.x UI files): 7.1 Review focus both pass (errors say what to do next; card anchor never shifts a live log); 7.2 Done when items present; no regressions, no Non-goal built, package.json matches the verified table. P3: "Generate plan again" can double-post `/plan` (InterviewStage.tsx:140); " Send your answer again." after text with no final punctuation (ChatPanel.tsx:209); trace latency and total row wrap at 1280 (TraceModal.tsx:35); markdown links have no hover (Markdown.tsx:13).
- Docs: essentials Conventions gained the run-card anchor rule and the `ready`-drops-running-runs test rule (7.1 Decisions and Gotchas); PRD Later gained 7.1's two Left open P3s as known limitations. AGENTS.md Known gotchas unchanged (7.x added none).
- Left open: typescript Verified row still not re-verified (from the first final audit); lint warns the essentials exceed one page (6.9k chars) and the 5.1 entry's date is out of order.
- Next: task 8.1, then a re-audit (architect).

## 2026-10-19: Task 8.1 Retry guard, error punctuation, trace wrap and link hover
- Status: done
- Plan check: off
- What changed: InterviewStage `generate` has a `useRef` in-flight guard and the three ErrorState retries get `retryDisabled={planning}`; ChatPanel adds "." before " Send your answer again." when the server text doesn't end in `.`, `!` or `?`; TraceModal Node and Latency columns carry `whitespace-nowrap` (footer shares it); markdown links get `hover:text-primary-hover`.
- Checks: `npm test` PASS 14 files / 233 tests (new: retry once + disabled, two punctuation cases, link hover class, nowrap cells); `npm run typecheck` PASS; manual: yes, screenshots/8.1-trace-1280x800.png (trace list patched from the page to 3 runs): "2 min 43 s" and "Total, 3 runs" each on one line.
- Decisions: new optional `retryDisabled` prop on src/components/ErrorState.tsx (outside Files): the retry button lives there and the prop is additive (default false). Built in-session.
- Tried and failed: none
- Gotchas: none new.
- Left open: P3 ErrorState edited outside Files (recorded above); P3 the double-click test passes with `disabled` alone, the ref covers same-frame clicks.
- Next: re-audit (architect).

## 2026-10-19: Audit (final, re-audit after Phase 8)
- Status: done
- Verdict: DEFECTS (0 P0, 0 P1, 0 P2, 4 P3); user chose to fix all four: Phase 9 added (9.1 retry gap, punctuation edge cases, retry spinner and total-row font, S).
- Checks rerun (re-audit: Test (all) plus 8.1 Done when; earlier tasks whose Files 8.1 touched, 2.2, 2.3, 3.3, 7.1, 7.2, are covered by the same `npm test`): `npm test` 14 files / 233 tests PASS; `npm run typecheck` PASS; `npm run build` exit 0; secrets: no .env on disk or in the frontend git history. Skipped: manual screenshot checks of tasks 8.1 didn't touch; the reviewer used screenshots/8.1-trace-1280x800.png.
- Reviewer (blueprint-reviewer, opus high, with web-design-guidelines on the 8.1 UI files): 8.1 Goal and Done when all present and tested; ErrorState `retryDisabled` additive (12 other callers unchanged); no Non-goal built; package.json matches the verified table. P3: punctuation check misses trailing space and closing quote (ChatPanel.tsx:209); retry re-enabled between POST return and `run.started`, a second click flashes "Couldn't start the plan" (InterviewStage.tsx:70-73); disabled retry has no spinner or aria-busy (ErrorState.tsx:32); total row "Total, N runs" in Fira Code via the Node column's mono (TraceModal.tsx:31,125, pre-existing). Also: the 8.1 double-click test passes on `disabled` alone; 9.1's Done when adds a same-frame test.
- Docs: 8.1's ErrorState `retryDisabled` decision is a component API detail, not folded into the essentials (already over one page). AGENTS.md Known gotchas unchanged (8.1 added none).
- Left open: typescript Verified row still not re-verified; lint warnings (essentials length, 5.1 entry date order) unchanged.
- Next: task 9.1, then a re-audit (architect).

## 2026-10-19: Task 9.1 Retry gap, punctuation edge cases, retry spinner and total-row font
- Status: done
- Plan check: off
- What changed: InterviewStage keeps "Generate plan" and its retries busy (spinner, aria-busy, ref guard) from click until the plan/spec run error clears, a POST error, or a 30 s fallback; ErrorState gets additive `retryLoading`; ChatPanel suffix checks the trimmed text and allows one closing quote/bracket; Table footer cells never get `font-mono`.
- Checks: `npm test` PASS 14 files / 241 tests (new: busy until run.started, rejected POST, same-frame clicks, run.started before POST, 30 s fallback, two punctuation cases, footer font, ErrorState no aria-busy); `npm run typecheck` PASS; manual: yes, screenshots/9.1-trace-1280x800.png ("Total, 2 runs" in Inter, one line), screenshots/9.1-retry-pending-1280x800.png (both buttons spinning).
- Decisions: `awaitingRun` state + `inFlight` ref released in a layout effect when `runErrors.plan/spec` clear; stage leave resets by unmount (WorkspaceShell). Fallback `AWAIT_RUN_MS = 30_000` (exported from InterviewStage) for a run missed while the stream was down (review P2). The main "Generate plan" button shares the busy state. Footer font fixed in Table (all footers body font); TraceModal unchanged.
- Tried and failed: none
- Gotchas: none new.
- Left open: none
- Next: re-audit (architect).

## 2026-10-19: Blueprint architect intake
- Status: awaiting scope clarification.
- Reviewed: frontend AGENTS.md, architecture essentials, plan, latest progress, PRD, package scripts, source/test layout, and blueprint-architect intake instructions.
- Findings: all plan tasks through 9.1 are marked done; the prior progress entry requests a re-audit. PROJECT_BRIEF.md and _blueprint/ are absent; .blueprint/ contains existing checkpoint snapshots.
- Decisions: asked whether this session covers the pending re-audit, a new frontend change, or conversion to the invoked skill's handoff format; no scope inferred from the skill invocation alone.
- Checks: none run (orientation only); no product code or plan status changed.
- Next: establish the requested outcome, then follow the applicable architect workflow.

## 2026-10-19: Change reference images and capability verification (frontend)
- Status: planned; scope confirmed, final plan review pending.
- User decisions: both features required this hackathon; closest supported recreation of layout/chart choices/style using connected data, with explained substitutions.
- What changed: API 1.3, dashboard-intent 1.0 and isolated shared fixtures; program/part PRDs, architecture/essentials and plans. Seven M tasks: backend 11.1-11.5, frontend 10.1, release 3.3. Existing task markers preserved. No product code changed in this planning session.
- Audit: five original gaps and five delta integration findings addressed; focused recheck found no remaining P1 contradictions, then requested task split (applied as 11.3-11.5). Full report: program-root docs/reference-capability-audit.md. Draft remains pending user review per architect skill.
- Decisions: dated product/app/data evidence; unknowns block; explicit durable substitutions; private replaceable reference sets per version; pending-comment recovery; distinct candidate views preserve old reports; required hosted acceptance redeploys tested source. No engine expansion or added dependency. New fixture folder avoids breaking legacy exhaustive API fixture inventories. Frontend full conventions/UI details moved into implementation-notes.md/reference-ui.md, essentials summarize.
- Checks: root check_contracts.py 9/9 PASS; frontend npm test -- contract 31/31 PASS. Planning lint/stamp run; final counts recorded in scope audit. No new behavior claimed tested; its acceptance commands belong to builders.
- Left open: seven sessions of M work may conflict with deadline; both remain required until user explicitly changes scope. Existing unrelated dirty source/deck files and historical progress entries preserved; no commit while draft review pending.
- Next: complete existing in-progress backend 9.7 and existing 10.1, then backend 11.1-11.5; frontend 10.1; release 3.3. Existing release infrastructure may proceed independently.

## 2026-10-20: Change gates after backend's task split (program root)
- Status: done
- What changed: backend split phases 11-12 (11.1-11.8, 12.1-12.5). 10.1 `Needs: backend 11.8` (was 11.5); 11.1 `Needs: backend 12.3` (was 12.2; user choice) with an `If:` line: when backend 12.5 isn't done, the label inside the backend-rendered prototype is left to release 3.3. Essentials: synthetic-data.md 1.1 (durability only; HTTP shapes unchanged). PRD deadline 2026-10-23 01:05 MPST.
- Affects: 10.1, 11.1 gates; no task content beyond the `If:`.
- Checks: `lint` frontend 0 errors; `program` 0 problems, 10.1 waits on backend 11.8.
- Left open: plan audit still pending from the 2026-10-19 reference/capability change.

## 2026-10-20: Change conventions 1.2 (program)
- What changed: contracts/conventions.md 1.1 -> 1.2 renames the Cloud Run service `dss` -> `dss-frontend` (keeps the submitted URL); this part's essentials Contracts row now says 1.2. Nothing this part reads or provides changed; no task affected.
- Also: plan 11.1's `If:` now points at release 2.5 (old 3.3 renumbered).

## 2026-10-20: Audit (delta, phases 10-11)
- Status: done
- Scope: plan 10.1/11.1, docs/reference-ui.md, docs/implementation-notes.md, essentials (References, Contracts), PRD; blueprint-reviewer (opus, high). `deps`: 16/16 FOUND. Accepted all 12 findings (user).
- What changed: 10.1 split into 10.1 reference panel + chat attach + API 1.4 guards, 10.2 feasibility panel/decisions/gates, 10.3 pending batches + stale replan; 11.1 split into 11.1 proposal/editor/generate, 11.2 status recovery/download/provenance. Each Done when now names its input and the asserted DOM/POST. Contract versions bumped to api 1.4 / dashboard-intent 1.1 / synthetic-data 1.1 (reference-ui, essentials, implementation-notes, Review focus); 10.1 adds `synthetic` to `SOURCE_KINDS` (1.4 makes the old "guards unchanged" line false). reference-ui: client-side image limits and route-specific 413/422 text, http(s)-only evidence links, fail-closed failed GET, mock default assessment `ready`, JSON schema textarea instead of a typed editor, request-bound generation_key, failed+Retry state. implementation-notes: match new runs by `run_id`, no stretch 404-hide on required routes. Files lists add ConnectStage, DoneStage, mocks/fixtures.ts, stretch/connect/prototype/versions tests. PRD: flow 5, synthetic feature row, success criterion. Essentials: fixed two mojibake characters, trimmed to one page.
- Decisions: tests build feasibility alternatives/stale/pending and succeeded-status variants from the shared fixtures by override (never copied files) until the contracts add them.
- Checks: `lint` 0 errors (warnings: 22 tasks; historical progress date order); `stamp` run.
- Left open (program root, frontend can't edit): (a) release 2.5 `Needs: frontend 10.1; frontend 11.1` and the program.md roadmap/decision log must move to frontend 10.3 and 11.2, or release 2.5 can start before this part finishes; (b) api.md still cites dashboard-intent/synthetic-data 1.0 and "(1.3)" headings, and its node list lacks reference_extract, capability_check, synthetic_schema, synthetic_generate; (c) fixtures missing: SyntheticDataset, succeeded GenerationStatus, feasibility with alternatives/pending_comments/stale; (d) program.md Parts table: frontend Consumes omits dashboard-intent and synthetic-data.
- Next: frontend 10.1 (backend 11.8 is done).

## 2026-10-20: Change frontend split gates and contract consistency (program root)
- Status: done
- What changed: contracts/api.md 1.5 (no shape or route change; complete `node` list adds reference_delete besides the 1.3/1.4 names; reference-ui.md presets line names it). New shared fixtures replace this part's override plan: dashboard-intent/feasibility.{alternatives,pending,stale}.json and synthetic-data/{dataset,job.succeeded}.json. Plan: 10.2 Done when (1) imports the three Assessment variants; 10.3 (1) names feasibility.pending.json; 11.1 (1) also imports dataset.json and job.succeeded.json; 11.2 uses them instead of overriding job.failed.json. Review focus lines, essentials Contracts row, reference-ui and implementation-notes cite api 1.5. Program: release 2.5 now needs frontend 10.3 and 11.2; program.md Parts table lists dashboard-intent and synthetic-data as consumed.
- Affects: 10.2, 10.3, 11.1, 11.2 (unstarted; checks only). Supersedes the audit's override Decision.
- Left open: none of (a)-(d) from the 2026-10-20 delta audit.


## 2026-10-20: Task 10.1 Reference panel, chat attach and API 1.4 guards
- Status: done
- Plan check: off
- What changed: Required style/recreate references, chat attachment, retained thumbnails, Replace/Remove, exact guards, synthetic Source support, mocks and activity labels.
- Checks: `npm test` PASS (15 files/260 tests); `npm run typecheck` PASS. Both viewports: keyboard/removal focus, truncation, no overflow; viewed all eight `screenshots/10.1-references-{empty,saved,processing,failed}-{1280x800,1440x900}.png`. Live style/recreate extraction each finished ok. Reviewer/web-design-guidelines: no remaining findings.
- Decisions: Chat focuses the same panel. stretch.ts subscribeWorkspace/publishWorkspace shares the existing SSE. ReferencePanel onReadyChange drives StageArea referencesReady, guarding plan/recipe/Build; panel remains available in Build view. Necessary extras: WorkspaceShell, useBuildStream, BuildStage and scoped prototype/build tests. Worker handled wiring/contract tests. AGENTS adds CDP Enter gotcha. Backend started with user permission.
- Tried and failed: native disclosure timing fixed; mock undefined-response cloning fixed, with real DELETE coverage. Legacy tests now await references and scope prototype status, preserving assertions.
- Gotchas: see AGENTS.
- Left open: none.
- Next: 10.2 Feasibility panel, decisions and Generate/Build gates (deep).

## 2026-10-20: Task 10.2 Feasibility panel, decisions and Generate/Build gates
- Status: done
- Plan check: off
- What changed: Exact Assessment guards/shared fixtures, feasibility API/mocks, requirement/evidence/alternative panel, explicit decisions, recovery checks and fail-closed plan/recipe/Build gates.
- Checks: `npm test` PASS (16 files/294 tests); `npm run typecheck` PASS; `git diff --check` PASS. Viewed eight `screenshots/10.2-feasibility-{unchecked,blocked,ready,error}-{1280x800,1440x900}.png`. Both viewports: no overflow; keyboard alternative/Enter returns heading focus; nine prototype overlay boxes aligned (<0.001 CSS px error). Live backend GPS request with invented CSV shows app-limitation copy and supported time-series alternatives. Reviewer and web-design-guidelines: no remaining findings.
- Decisions: Shell owns FeasibilityGates (planReady/buildReady); panel reuses workspace SSE fanout, refetches after reference readiness changes, and rejects obsolete GET/decision responses. checkTicket invalidates late check responses on reconnect; pending run matches run_id only. Worker implemented decided client/mock/fixture/contract-test glue. AGENTS adds resource-refetch test timing gotcha. Pending-batch actions/replan remain task 10.3.
- Tried and failed: corrected test preset export, loading-state assertion timing and screenshot overlay selector. Fixed review P2 delayed-POST/reconnect lock race, with regression.
- Gotchas: see AGENTS.
- Left open: none.
- Next: 10.3 Pending comment batches and stale-prototype replan (deep).


## 2026-10-20: Task 10.3 Pending comment batches and stale-prototype replan
- Status: done
- Plan check: off
- What changed: Saved-batch targets/text survive remount; explicit reapply/discard use current IDs and server assessments. Resolved stale intent permits repair while recipe/Build stay gated; preview shows Stale.
- Checks: `npm test` PASS (16 files/310 tests); `npm run typecheck` PASS; `git diff --check` PASS. Viewed all four `screenshots/10.3-{pending,stale}-{1280x800,1440x900}.png`. Keyboard reapply/discard return heading focus; no overflow; nine overlay targets align within 0.001 CSS px with Stale visible. Reviewer and web-design-guidelines: no remaining findings.
- Decisions: Necessary extra WorkspaceShell relays assessment and blocked-POST refresh. Reapply shares run-ID completion/reconnect handling. savedCandidate preserves async blocked-batch identity independently of applied pins. Replan guards local drafts. Mock pendingIssueIds distinguishes batch-owned requirements. AGENTS records resolved-issue test timing.
- Tried and failed: Updated obsolete stale-gate expectation and resolved-issue helper; fixed review findings for async handoff and draft loss. Restarted disconnected screenshot Chrome with a fresh profile; policy-rejected deletion replaced by reversible relocation to OS temp.
- Gotchas: see AGENTS.
- Left open: none.
- Next: 11.1 Synthetic proposal, schema editor and generation (deep; needs backend 12.3).

## 2026-10-20: Task 11.1 Synthetic proposal, schema editor and generation
- Status: done
- Plan check: off
- What changed: Exact synthetic-data guards/fixtures; client+mock proposal/generate routes; Connect choice Upload/connect data vs Generate sample data; SyntheticDataPanel (proposal table, assumptions, JSON columns, row count, seed, request-bound key).
- Checks: `npm test` PASS (17 files/343 tests); `npm run typecheck` PASS. Viewed all ten `screenshots/11.1-synthetic-{no-data,proposal,editing,invalid,busy}-{1280x800,1440x900}.png`; no overflow or console errors. CDP keyboard path: radio, Add a reference, columns, row count, seed, Generate (Enter); focus then lands on Start interview.
- Decisions: Textarea holds only the `columns` array. Live backend 422 detail is `{field, reason}` relative to spec; specFieldErrors also accepts `detail.errors[]`. Keys `sd_<uuid>` stay bound until edit, 409 conflict, stale proposal or failed run. ReferencePanel `onSavedChange` feeds the panel. Mock run failures cover synthetic nodes. AGENTS adds line-ending detection.
- Tried and failed: shell heredoc/Python patches missed CRLF lines; patched by byte-aware scripts or Edit.
- Gotchas: see AGENTS.
- Left open: P2 replay after reconnect can wait for a missed run.finished - SyntheticDataPanel.tsx (11.2 job status fixes); "Loading sample data" label needs 11.2 job polling.
- Next: 11.2 Synthetic status recovery, download and provenance (deep).

## 2026-10-20: Task 11.2 Synthetic status recovery, download and provenance
- Status: done
- Plan check: off
- What changed: Client+mock job list/status, datasets, CSV URL (mock jobs from shared job fixtures). SyntheticDataPanel recovers jobs on load, reconnect and an unanswered POST, polls every 2 s; Retry waits for retry_ready. Sources row: Synthetic badge, Download CSV, provenance details. Banner on Prototype/Build/Done; New dashboard for real-source builds.
- Checks: `npm test` PASS (17 files/359 tests); `npm run typecheck` PASS. Viewed `screenshots/11.2-synthetic-{success,failed-retry,reload}-{1280x800,1440x900}.png` (reload: job API patched in page to hold "loading"); no overflow or console errors. Backend keyboard run: manual columns -> Generate -> polled "Loading sample data…" -> badge, CSV (200, 1,000 rows), provenance -> focus Start interview -> interview. Not run: screenshot -> proposal, plan -> prototype (backend failures, Left open).
- Decisions: Panel always mounted (hidden) without sources; a found job selects Generate. Failed job with retry_ready false keeps polling until true. Job failures survive edits. Necessary extra: WorkspaceShell passes ConnectStage onAssessmentInvalidated. useBuildStream/types.ts unchanged. AGENTS adds stash and CDP-window gotchas.
- Tried and failed: none.
- Gotchas: see AGENTS.
- Left open: backend reference upload 503 "Image decoder failed" and plan llm_unavailable (gemini-4-argon) blocked proposal and prototype legs, incl. backend prototype label (12.5): rerun with fixed backend. P3 mock Download CSV has no blob - src/mocks/api.ts. Pre-existing: chat bubble sr-only labels extend document height - chat (not 11.2 files).
- Next: none in plan; all frontend tasks done.

## 2026-10-20: Audit (final, re-audit after Phase 11)
- Status: done
- Verdict: DEFECTS (0 P0, 1 P1, 2 P2, 9 P3); user accepted all 11 code findings: Phase 12 added (12.1 strip test, steady feasibility refetch and Prototype fold, M; 12.2 Connect feasibility, read-only copy, confirms and small UI fixes, M). TypeScript row fixed in this session.
- Checks rerun (re-audit: Test (all) plus the Done when of 9.1, 10.1-10.3, 11.1, 11.2; earlier tasks whose Files they touched, 1.1, 1.2, 2.1, 2.2, 3.1, 3.2, 3.4, 6.1, are covered by the same `npm test`): `npm test` 17 files / 359 tests PASS; `npm run typecheck` PASS; `npm run build` exit 0 (551 kB chunk warning); hex search of src/components and src/features none; 6.2 node-name search none; secrets: no .env on disk or in git history. Fresh screenshots screenshots/audit2-{history,connect,prototype,done}-{1280x800,1440x900}.png (mock, headless Chrome over CDP): no horizontal overflow, no page exceptions. Git checks for the reviewer's unverifiable items: 10.1 moved the four style-image tests out of stretch.test.tsx and references.test.tsx adds nine covering upload/run, run error and validation (404-hide dropped on purpose); 10.2 left prototype/build/versions tests unchanged. Skipped: live-backend legs (backend failures, see Later); keyboard paths judged from task screenshots and their entries.
- Reviewer (blueprint-reviewer, opus high, with web-design-guidelines on the Phase 9-11 UI files): Review focus 9.1, 10.1, 10.2, 10.3, 11.1, 11.2 pass; no Non-goal built; package.json matches the table; progress decisions consistent with essentials, implementation-notes and reference-ui. P1: 10.1 Done when (7) strip phrase untested. P2: FeasibilityPanel unmounts on every refetch (FeasibilityPanel.tsx:62,210; gates flicker); Prototype canvas below the fold at 1280x800 (always-open References + Feasibility). P3: Check feasibility leads an empty Connect and the mock never refreshes the assessment after interview; Done read-only References empty copy; mono table headers (Table.tsx:39); Stale badge on accent amber; no confirm on Remove references / Discard pending comments; References title not a heading; Clarify in chat focuses a disabled textarea; sample-data loading reads as an error; typescript Verified row.
- Docs: reference-ui.md Controls and states gains the collapsed-in-Prototype, confirm-before-loss and steady-refetch rules (12.1/12.2 Spec). implementation-notes gains the test traps (moved from AGENTS.md Known gotchas: fake timers, createObjectURL, compileRecipe, Modal focus) and the workspace-panel convention (shared EventSource fanout, shell-owned gates, obsolete responses dropped) from 10.1-10.2 Decisions. Essentials: `deps --write` re-dated rows; typescript row records 5.9.3 in range (own registry check). PRD Later: backend-blocked live legs (to release 2.5), mock CSV blob, chat sr-only height, bundle size.
- Left open: AGENTS.md "Resource-panel tests" and "Feasibility test helpers" gotchas stay until 12.1 changes the loading behavior (12.1 updates them).
- Next: task 12.1, then 12.2, then a re-audit (architect).

## 2026-10-20: Change Phase 12 triage (severity bar)
- Status: done
- What changed: Phase 12 re-graded against the architect skill's new severity bar (POC: only blockers become tasks, at most 2 fix tasks). Kept, in 12.1 (in progress, unchanged): P1 10.1 Done when (7) strip phrases untested; P2 Prototype canvas below the fold at 1280x800 (the must-survive prototype/comment screen; POC checklist "core screens match the UI design"); P2 FeasibilityPanel unmount on refetch (not a blocker at POC, kept because the in-progress 12.1 diff already builds it). Removed 12.2 (unstarted): its 8 P3 findings go to the PRD `## Later` list (source audit 2026-10-20). reference-ui.md Controls and states drops the confirm-before-loss rule, which only 12.2 built.
- Why: the 2026-10-20 retro found re-audits looping on P3-only fix phases (Phases 8, 9); Phase 12 was planned before the bar and accepted all 11 code findings. User picked the kept findings on a card.
- Tasks affected: 12.1 none (built as written); 12.2 removed.
- Change requests: none open.
- Next: finish task 12.1, then a re-audit (architect): blockers only.

## 2026-10-20: Task 12.1 Strip test, steady feasibility refetch and Prototype fold
- Status: done
- Plan check: off
- What changed: FeasibilityPanel and ReferencePanel keep the last assessment/set, controls and focus during a background refetch (loading text only before the first load; error kept until a GET succeeds); Prototype starts References collapsed (`defaultOpen`); a ready assessment with no open issue is one line. Tests for strip phrases, refetch, gates and fold.
- Checks: `npm test` PASS (17 files/376 tests); `npm run typecheck` PASS; 12 new tests fail on HEAD code. Manual (mock, headless CDP): `screenshots/12.1-prototype-{1280x800,1440x900}.png`, canvas top 326 px, no overflow; keyboard: focus on Use this alternative kept through a held docs.updated refetch, Enter saves; Attach reference opens and focuses Use style.
- Decisions: gates may only close while a refetch is pending (min with last emitted), so a finished run never reopens them on the pre-run assessment; referencesReady/refreshKey changes close the gates until their refetch lands (review P2). Mutation responses bump the request seq (`adopt`). Attach focus falls back to the summary. Draft-comments hint only beside Replan. WorkspaceShell/ChatPanel unchanged. AGENTS gotchas updated.
- Tried and failed: none.
- Gotchas: none new.
- Left open: none.
- Next: re-audit (architect); 12.2 was removed by the Phase 12 triage.

## 2026-10-20: Audit (final, re-audit after Phase 12)
- Status: done
- Verdict: DEFECTS (0 P0, 1 P1); user accepted Phase 13 (13.1 Steady feasibility focus test, S), a second audit-fix phase in a row, on a card naming its cost.
- Checks rerun (re-audit: Test (all) plus 12.1's Done when; 12.1 touched FeasibilityPanel, ReferencePanel and PrototypeStage, whose earlier tasks 3.1, 10.1, 10.2, 10.3 are covered by the same `npm test`): `npm run typecheck` PASS; `npm run build` exit 0 (chunk-size warning); hex search of src/components and src/features none; secrets: no .env on disk or in git history. `npm test` FLAKY: 4 full runs, 2 PASS (17 files/376 tests), 2 FAIL with 1 test each, tests/feasibility.test.tsx:77 "handles a finish arriving before the check POST returns" (heading not focused); the file alone passed 5 of 5. Screenshots: viewed screenshots/12.1-prototype-1280x800.png (canvas top above the fold); no fresh screenshots (12.1 changed only Prototype, and its own are current). Skipped: live-backend legs (still blocked, see Later).
- Reviewer (blueprint-reviewer, opus high, blockers only, web-design-guidelines on the three 12.1 UI files): P1: the test races 12.1's focus gate (FeasibilityPanel.tsx:91 waits for `!refreshing`; the status text renders before the mock GET's `setTimeout(0)` lands); the app behaves right, the test is wrong. Review focus passes (fail-closed on first load, failed GET, stale, blocked; obsolete responses dropped via seq/adopt and fetchSeq; a pending refetch only closes gates). Done when (1)-(4) each asserted. No Non-goal built; package.json matches the Verified table; 12.1 Decisions consistent. Below the bar: four P3 already on Later, one new P3 (late focus) added to Later.
- Docs: reference-ui.md Controls and states records the 12.1 decisions (a pending refetch may close a gate, never reopen it; focus moves to the heading once the refetch lands). The "Resource-panel tests" and "Feasibility test helpers" gotchas moved from AGENTS.md into implementation-notes.md Conventions as a test trap, plus the await-focus rule. PRD Later gains the late-focus P3.
- Next: task 13.1, then a re-audit (architect): blockers only.

## 2026-10-20: Task 13.1 Steady feasibility focus test
- Status: done
- Plan check: off
- What changed: tests/feasibility.test.tsx (3 heading-focus assertions after status messages, lines 77, 411, 446) and tests/references.test.tsx (file-chooser focus after "References removed.") now wrapped in `waitFor`. No src/ change.
- Checks: `npm test` PASS in 4 runs in a row, each 17 files/376 tests; `npm run typecheck` PASS; `git diff` touches no file under src/ (other diff entries in the repo are pre-existing, not this task).
- Decisions: other focus assertions (feasibility 218, 233, 269; references 75, 287) left sync: they follow no status message or assert focus kept. Reviewer subagent skipped: S task, test-only, wait-for-focus change.
- Tried and failed: none.
- Gotchas: none new.
- Left open: none.
- Next: re-audit (architect): blockers only.

## 2026-10-20: Audit (final, re-audit after Phase 13)
- Status: done
- Verdict: ACCEPTED (0 P0, 0 P1, 1 P3 fixed in docs).
- Checks rerun (re-audit: Test (all) plus 13.1's Done when; 13.1 touched tests only, no src/ file, so no earlier task's Files): `npm test` PASS in 4 full runs in a row, each 17 files/376 tests (the Phase 12 flake is gone); `npm run typecheck` PASS; `git diff 5d75607~1 5d75607 -- src/` empty; secrets: no .env on disk or in git history. No fresh screenshots (no UI change since 12.1's). Skipped: live-backend legs (still blocked, see PRD Later).
- Reviewer (blueprint-reviewer, opus high, blockers only): every Done-when clause met; the five focus assertions left synchronous (feasibility 218, 233, 269; references 75, 287) rightly follow no status message; 13.1 Decisions match implementation-notes' await-focus rule; package.json matches the Verified table; no Non-goal built. P3: plan 13.1 Files omitted tests/references.test.tsx, which its Done when requires; fixed in plan.md.
- Docs: plan.md 13.1 Files line. No new Decisions or Known gotchas to sort (13.1 recorded none).
- Release checklist (POC): AGENTS.md Commands run the mock demo in under 5 minutes; core flow covered by `npm test` and the earlier audits' screenshots (screenshots/audit2-*, 12.1-prototype-*); known limitations in PRD `## Later`.
- Next: nothing left to build. Retro, tag or a new version on the user's call.

## 2026-10-21: Change staged workflow (program root)
- What changed: PRD goals, flows, features and defaults (chat input removed; reference attach in Connect/Design/Prototype; user colors as data swatches); essentials folder map, layout and contract versions; new docs/staged-ui.md (stage areas, stepper states); reference-ui.md wording for blueprint/accept; phase 14 tasks 14.1-14.5 (14.5 Needs backend 15.11 for its live leg).
- Why: per-message requirement extraction in the free-text interview kept failing (backend 14.1, 14.2; release 2.3 `llm_unavailable`), and the one large plan run failed about 1 in 3 live runs, sending users back to the interview. The user asked for a context-engineered, node-per-artifact workflow where the model gets only enough context and code generates the files.
- Contracts: api.md 2.0, dashboard-intent.md 1.2, synthetic-data.md 1.2 (consumer); fixtures updated at the root.
- Tasks affected: none reopened; 14.1 is next and builds against the 2.0 fixtures.

## 2026-10-21: Audit (delta, staged workflow, program root)
- 16 findings (1 P1, 10 P2, 5 P3), all accepted and applied; details in ../docs/progress.md (same date).

## 2026-10-21: Task 14.1 Contract 2.0 types, mocks, stepper and activity column
- Status: done
- Plan check: off
- What changed: types/client/mocks speak api.md 2.0 (stages, artifacts, notes, staged endpoints, artifact.updated; interview/messages/plan calls removed); 8-step Stepper with artifact states and reopen; chat/ moved to activity/ (ActivityColumn, no input); Interview/Plan stages deleted; new StageFrame + ArtifactStage (read-only summary + confirm/secondary actions per artifact stage).
- Checks: `npm test` PASS (17 files, 371 tests); `npm run typecheck` PASS; Grep src for interview/start, /plan, startInterview, sendMessage, generatePlan: none; presets keys context, outline_propose, outline_other, outline_suggest, blueprint, prototype; screenshots/14.1-workspace-1280.png and -1440.png checked (stepper draft/confirmed/stale, activity column, no input, no overlap).
- Decisions: necessary extras outside Files: ArtifactStage.tsx, StageFrame.tsx (stage frame), ConnectStage (Start interview -> Draft context), FeasibilityPanel (Replan -> Regenerate blueprint via regenerateBlueprint; Clarify in chat removed), import/wording in PrototypeStage, ResearchPanel, StylePanel, stretch.ts, SettingsModal. Guards check JSON types only (no hex/palette/measure-xor rules: those are server issues). getBuild/createBuild now guard-checked (review P2). Mock: a failed accept leaves blueprint draft; edits move stage back at request time; knobs patchMockBuild, setMockArtifact; setMockRunFailure takes staged nodes. Shell: stepper reopen kept only while build.stage is unchanged. Trace/Settings icon-only below 1440 so the stepper fits at 1280. Activity column has no Attach reference; openReferencePanel stays for sample data.
- Digest: useBuildStream in src/features/activity/ ({running, artifactSeq, runErrors per staged node}); ArtifactStage(build,name,stream,feasibility,acceptReady) in StageFrame; Stepper({build,viewing,onSelect}), staleCause, prototypeStale; mock patchMockBuild/setMockArtifact.
- Tried and failed: none
- Gotchas: Bash heredocs containing non-ASCII (`·`) fail with "unexpected EOF": write patch scripts with the Write tool and run them.
- Left open: P2 reopening a step drops unsent draft comments - WorkspaceShell.tsx select / PrototypeStage; P2 stale prototype opened from an earlier stage keeps comment/Apply/Audit enabled - WorkspaceShell.tsx; P2 References/Feasibility controls not disabled while a run holds the lock on artifact stages - WorkspaceShell.tsx; P2 no rendered tests for ArtifactStage states (run lock phrase, per-artifact refetch, loading/empty/error, failed accept) - tests/; P3 raw `max-[1439px]` breakpoint - WorkspaceShell.tsx; P3 stale reason only as tooltip in stepper - Stepper.tsx; P3 footer status not tied to disabled buttons - StageFrame.tsx; P3 POST-to-run.started re-enable gap - ArtifactStage.tsx; P3 outline_other/suggest retry offers Re-propose - ArtifactStage.tsx.
- Next: Task 14.2 Notes box and context review. Start by replacing ArtifactStage's context summary with the editor in src/features/workspace/context/.

## 2026-10-21: Task 14.2 Notes box and context review
- Status: done
- Plan check: off
- What changed: Connect gets an "About this data" notes box (count, >4000 blocks Draft context, notes sent with draftContext). New src/features/workspace/context/ (ContextEditor, fields, model) replaces the read-only context summary in ArtifactStage: title/goal/audience, datasets, KPI cards (measure field+agg or ratio pickers), derived fields, thresholds, glossary edited in place with inline issues.
- Checks: `npm test -- context` PASS (13/13); `npm run typecheck` PASS; Test (all) `npm test` PASS (384/384); screenshots/14.2-context-1280.png (1 KPI column) and 14.2-context-1440.png (2 columns) checked: no overflow, issues inline, footer "2 open issues", Confirm off; headless Tab path through a card and ArrowRight mode switch checked.
- Decisions: selects/mode/add/remove PUT at once, text on blur; PUTs serialized by edit counters, a response never overwrites newer typing; saving never disables inputs. `onSavingChange` is true while a PUT runs or after one failed, and blocks Confirm/Redraft. Issues land on the deepest rendered JSON-pointer path (field > card/row > list > top). Aggs by type: number all; date/datetime count, count_distinct, min, max; others count, count_distinct. KPI ids read-only, new ids via `newId(prefix, rows)`; dataset summaries read-only. ArtifactStage ignores a load with a lower revision (late refetch). Necessary extras: ArtifactStage.tsx (hosts editor), tests/stepper.test.tsx (summary assertion moved to inline issue). AGENTS.md: fieldset/jsdom gotcha.
- Digest: ArtifactStage renders `<ContextEditor build context disabled onSaved onSavingChange>` (context/ContextEditor.tsx) for 'context'; model.ts: placeIssues(issues, paths), aggsFor(type), newId(prefix, rows); fields.tsx: SelectField, NumberField, IssueList; MAX_NOTES in ConnectStage.
- Tried and failed: none
- Gotchas: Fira Code ligatures draw `>=` as a single glyph in the Rule select; harmless.
- Left open: P3 Confirm clicked right after typing is dropped (blur starts the save first) - ArtifactStage.tsx; P3 raw `min-[1440px]` breakpoint and `mt-px` (same as WorkspaceShell's) - context/; P3 Remove KPI/row has no undo - ContextEditor.tsx
- Next: Task 14.3 Outline picker. Start by reading ArtifactStage OutlineSummary and the context/ editor pattern.

## 2026-10-21: Task 14.3 Outline picker
- Status: done
- Plan check: off
- What changed: New src/features/workspace/outline/OutlinePicker.tsx replaces the read-only outline summary in ArtifactStage: collapsible section groups, checkbox rows (label + describedby: Recommended, origin chip, KPI names, rationale), Suggest more and an Other box per section, "Add a section" box; mock explains GPS Other text in an assistant message.
- Checks: `npm test -- outline` PASS (12/12, run 3x); `npm run typecheck` PASS; Test (all) `npm test` PASS (19 files, 396 tests); screenshots/14.3-outline-1280.png and -1440.png checked (no overflow, tokens only, footer count + Confirm in view, GPS explanation in the activity column).
- Decisions: each tick PUTs only the changed ids, serialized; unsaved ticks show as overrides and count in the footer (onCountChange); a save in flight or failed blocks Confirm/Re-propose via onSavingChange, failed save offers Save again. After a Suggest/Other 202 every control stays off until that run_id shows in stream.activity (fallback AWAIT_RUN_MS 30 s). Other text clears only when a newer outline revision lands, so a failed run keeps it. KPI chips read names from GET context, ids until it loads. Mock: /\bgps\b/i Other text streams the explanation and keeps the question. Necessary extra: ArtifactStage.tsx (hosts the picker, optional stream.activity). AGENTS.md: heredoc backspace gotcha.
- Digest: ArtifactStage renders `<OutlinePicker build outline disabled onSaved onSavingChange onCountChange startedRuns>` (outline/OutlinePicker.tsx; exports selectedCount(outline, overrides?), MAX_OTHER=1000, AWAIT_RUN_MS); ArtifactStage stream prop takes optional `activity`.
- Tried and failed: clearing the run wait when `disabled` turned on: a run that starts and finishes before React renders never shows the lock, so controls stayed off.
- Gotchas: jsdom dispatches clicks on controls in a disabled fieldset; assert `:disabled`, not that a click did nothing.
- Left open: P3 Suggest more/Add question look enabled but do nothing while a selection PUT is in flight - OutlinePicker.tsx; P3 KPI chips swap ids for names after GET context (chip width shift) - OutlinePicker.tsx; P3 scroll assertion uses a stubbed scrollTop (real guard is same-node + no loading) - tests/outline.test.tsx; P3 mock rationale "Added by you." repeats the origin chip - src/mocks/api.ts.
- Next: Task 14.4 Design picker. Start by reading ArtifactStage DesignSummary and the outline/ picker pattern.

## 2026-10-21: Task 14.4 Design picker
- Status: done
- Plan check: off
- What changed: New src/features/workspace/design/DesignPicker.tsx (preset cards, base-color and palette hex fields, font select, pages and density radios, title/subtitle, source chip) and DesignPreview.tsx (Swatch, mini preview); ArtifactStage mounts the picker instead of DesignSummary; mock prefill takes a style reference as source `reference`.
- Checks: `npm test -- design` PASS (12/12); `npm run typecheck` PASS; Test (all) `npm test` PASS (408/408, 20 files); screenshots/14.4-design-1280.png and -1440.png checked: yes (no overlap, swatches carry hex text, preview beside fields).
- Decisions: save model copied from ContextEditor (preset pick, palette add/remove, selects and radios PUT at once; hex and text fields on blur; edit counters). Preset cards are aria-pressed buttons so re-pressing re-applies the preset. Color/palette/font edits set source `user`; title, subtitle, pages and density keep the source. Hex fields keep invalid text only while focused and never send it (like NumberField). Per-section hint counts outline sections with a selected question; over 5 it says so (no client block). Mock: a style ReferenceSet for the current version makes prefill accent/palette[0] #0F766E and source `reference`. Necessary extras: ArtifactStage.tsx (mount), tests/stepper.test.tsx (one assertion read the removed summary text, now reads the Accent input). ReferencePanel.tsx unchanged (already shown on Design).
- Digest: DesignPicker({build, design, disabled, onSaved, onSavingChange}) in src/features/workspace/design/; exports HEX, PALETTE_MIN/MAX, MAX_PAGES; DesignPreview.tsx exports Swatch({color, name?, small?}) and DesignPreview({design: DesignUpdate}).
- Tried and failed: none
- Gotchas: none
- Left open: P3 outline load failure silently drops the page-count hint - DesignPicker.tsx; P3 presets Try again sits inside the disabled fieldset during a run - DesignPicker.tsx; P3 no tests for a failed save, failed/empty preset load or another tab's artifact.updated adoption - tests/design.test.tsx.
- Next: Task 14.5 Blueprint review, prototype page tabs and the live staged walkthrough (needs backend 15.11 for its live leg). Start by reading ArtifactStage BlueprintSummary and FeasibilityPanel.

## 2026-10-21: Task 14.5 Blueprint review, prototype page tabs and the live staged walkthrough
- Status: done
- Plan check: off
- What changed: New blueprint/BlueprintTable.tsx (rows by page: question, chart icon+label, fields, page, status; derived fields) and blueprint/issueSlots.tsx; FeasibilityPanel portals each blocked row's issue under that row; PrototypeCanvas page tabs (data-page-name), per-page targets/pins, tab counts; PendingList page names; mock blocked ratio + multipage.
- Checks: `npm run typecheck` PASS; `npm test` PASS (21 files/423 tests). Live (backend 8000, DSS_ENGINE_DRY_RUN=1, Gemini): notes -> context -> outline (+1 Other) -> design per_section -> blueprint (real blocked ratio q3, alternative accepted) -> accept -> 4-page prototype -> comment applied (spec v2) -> build done: yes. Accept failure and stale-after-outline-edit seen live. Viewed screenshots/14.5-{context,outline,design,blueprint,prototype}-1280.png; 1440 table no overflow.
- Decisions: one FeasibilityPanel instance; IssueSlotProvider in ArtifactStage, table registers a slot per issue (first row owns it, others say "Decided with ... above"), panel createPortal()s fieldset or "Alternative accepted:/Dropped:". After a saved decision `decided` bumps and the blueprint refetches (live backend rewrites rows on decisions with no artifact.updated); 409 feasibility_blocked on accept refetches the panel. Tabs: one section shown (offset+clip), WAI-ARIA arrows/Home/End, page kept by position across versions; zero-height empty section gets 900 px. Mock: setMockBlueprintBlocked, mockRatioIssue/MOCK_RATIO_ISSUE_ID (i_aov_ratio); decisions rewrite that row (no event, like live); per_section design serves prototype.multipage.html. Necessary extras: ArtifactStage.tsx, .claude/launch.json (frontend-live). AGENTS.md: 2 gotchas.
- Digest: blueprint/BlueprintTable({build,blueprint,outlineSeq}); blueprint/issueSlots: IssueSlotProvider, IssueSlotContext {slots,register,issues,refresh,decided}, rowResolved(ids,issues). prototype Target.page, Page {index,n,name,top,height}; onRead(cids,pageNames).
- Tried and failed: first live accept failed "More than 24 components" (26 rows drafted); fixed by unticking 2 questions. A sort comment was blocked by 2 needs_clarification issues without alternatives; after Drop, Reapply failed twice llm_unavailable; a fresh comment applied.
- Gotchas: see AGENTS (pane upload/clicks, frontend-live).
- Left open: backend: decisions rewrite the blueprint without artifact.updated (api.md 2.0 says it follows every write); blueprint drafts >24 components that accept rejects; issue requirement is a bare id ("q3"); sort comment over-blocked; reapply revise llm_unavailable. P3 409 feasibility_blocked refetch untested - ArtifactStage.tsx.
- Next: none in frontend's plan (29/29); final audit by the architect.

## 2026-10-21: Audit (final, re-audit after Phase 14)
- Status: done
- Verdict: ACCEPTED (0 P0, 0 P1; 4 new P3 to PRD Later).
- Checks rerun (re-audit: Test (all) plus the Done when of 14.1-14.5; 14.1 touched the shell, stepper, client, types and mocks of earlier tasks, all covered by the same `npm test`; earlier Done-when clauses about the chat column, interview and plan stages are superseded by change staged workflow 2026-10-21): `npm run typecheck` PASS; `npm test` PASS 3 runs in a row, each 21 files/423 tests; `npx vitest run context|outline|design|contract` PASS (13, 12, 12, 76); `npm run build` exit 0 (chunk-size warning); hex search of src/components and src/features none; grep src for interview/start, startInterview, sendMessage, generatePlan, POST messages, /plan none (GET listMessages only); presets keys context, outline_propose, outline_other, outline_suggest, blueprint, prototype; secrets: no .env on disk or in git history. Screenshots: the Phase 14 tasks' 14.1-14.5 sets (current with HEAD), no fresh ones. Skipped: rerunning 14.5's live leg (done in 14.5 the same day, against backend 15.11).
- Reviewer (blueprint-reviewer, opus high, blockers only, web-design-guidelines on the Phase 14 UI files; its WebFetch got a summary of the rules only): every Review focus checked with citations (exact guards, one EventSource, notes limit, measure/ratio, inline issues, 409 artifact_invalid, checkbox labels, 24-at-most, run_id lock, #RRGGBB 3-8, swatch text, reference chip, per_section count, portalled issues, accept gate, 409 feasibility_blocked refetch, WAI-ARIA tabs, per-page pins). No Non-goal built; package.json matches the Verified table; no Decision contradicts the essentials or staged-ui.md. Four new P3 (page tabs truncate at 1280, "generating" copy, Connect not reopenable after context, "None" placeholders) to PRD Later.
- Docs: implementation-notes.md Conventions gain the Phase 14 decisions (artifact editor save model, run_id lock after a 202, blueprint issue slots and refetch, page tabs) and the disabled-fieldset jsdom trap, moved from AGENTS.md Known gotchas; node names now api.md 2.0. Essentials Conventions gain one line on the editor save model. PRD Later gains the Phase 14 Left open items, the four reviewer P3 and the backend issues seen live in 14.5 (for the backend part and release). Other new gotchas (heredocs, pane upload, frontend-live) are environment quirks and stay.
- Release checklist (POC): AGENTS.md Commands run the mock demo in under 5 minutes; core flow verified live in 14.5 (notes -> build done) and by `npm test`; known limitations in PRD `## Later`; core screens match staged-ui.md and the UI design section at 1280/1440 (reviewer, Phase 14 screenshots).
- Next: nothing left to build in frontend. Program: engine and backend final audits are due; then the integration audit at the program root.
