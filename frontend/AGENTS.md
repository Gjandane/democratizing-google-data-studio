<!-- blueprint-solution:start  (shared by Codex and Claude Code; in an existing AGENTS.md, add only this block and keep the rest) -->
# frontend: agent guide
The web app of Democratizing Google Data Studio: history, a staged workspace with chat,
click-to-comment prototype, live build view, settings and traces. Target: POC.

## Commands
Run from this folder (`frontend/`) in bash.
- Install: `npm install`
- Run: `npm run dev`   (mock API: `VITE_MOCK=1 npm run dev`)
- Test (all): `npm test`   (each task's own check is its "Done when" in docs/plan.md)
- Lint: `npm run typecheck`

## Read before editing
- docs/architecture-essentials.md: always.
- docs/plan.md: find your task. Change task status only through the blueprint script.
- docs/progress.md: the latest entry, plus the entries of tasks yours depends on.
- The doc sections your task's `Spec:` names (`status` prints them): what your code must do, in full.
- docs/PRD.md: goals and non-goals; open it when a requirement is unclear.
- ../contracts/api.md, ../contracts/fixtures/api/, ../contracts/conventions.md (read-only): the interfaces and shared fixtures this part consumes; read the one your task touches.

## Rules
- This folder is the frontend part of Democratizing Google Data Studio. The other parts (engine `../engine/`, backend `../backend/`, release at `..`) are separate projects: their docs, rules and commits don't apply here; never read, edit or report on their files. From the program root's AGENTS.md, only the program block applies. The exception is the contracts above: read them, never edit them.
- Build only what the current task asks. Stay inside its Files, or say why before editing others.
- Never build anything listed under Non-goals in docs/PRD.md.
- Use only dependencies with a date in the Verified column of docs/architecture-essentials.md. Ask before adding any other.
- Never print, log or commit secret values. `.env` stays out of version control and shared copies; `.env.example` lists names only.
- A task is done only when its "Done when" command and Test (all) pass. Report real output; never describe a run you didn't do.
- Latitude: anything these docs don't fix is yours to decide. Pick the smallest change that passes the check and record it under Decisions in your progress entry. Smallest never means naive: code under a Spec meets all of it (rules, edge cases, budget), not just the tests.
- Before ending a session, add an entry to docs/progress.md.
- Decisions and task status live in docs/, never in a tool's memory. If a saved memory disagrees with these docs, the docs win.

## Known gotchas
Traps that cost an earlier session time and that the other docs don't cover, one line each. Builders add lines; the architect sorts them into the docs at the final audit.
- Desktop app's browser pane: `preview_start` with config `frontend-mock` (.claude/launch.json) runs `VITE_MOCK=1 npm run dev` through `C:/Program Files/Git/bin/bash.exe`; plain `bash` isn't on its PATH.
- Browser pane can't save PNGs and its screenshot can time out: for `screenshots/`, drive headless Chrome (`C:/Program Files/Google/Chrome/Application/chrome.exe --headless=new --remote-debugging-port=N`) over CDP from a scratch Node script (Node 24 has global WebSocket/fetch, no deps): `Emulation.setDeviceMetricsOverride`, `Page.captureScreenshot`.
- To show mock empty/error states in the browser, patch `api` from the page: `import()` the exact module URL the app loaded (find it in `performance.getEntriesByType('resource')`; HMR appends `?t=`, a plain `/src/api/client.ts` import is a different instance), then navigate client-side (`history.pushState` + `popstate`).
- `rg` isn't on Git Bash's PATH: run a Done-when `rg` check with the Grep tool (same regex).
- Screenshot cleanup: kill the headless Chrome you spawned by its process (`child.kill()`/PID), never `taskkill /IM chrome.exe`: it closes the user's own Chrome too.
- Drop-zone screenshots: dispatch `new DragEvent('drop', {dataTransfer, bubbles: true})` with a `DataTransfer` built in page JS; mock state resets on reload, so recreate the build per state.
- A background mock server for screenshots (`VITE_MOCK=1 npx vite --port 5199 --strictPort &`; 5173 may be taken): `kill $!` leaves node running, so stop it by the PID listening on its port (PowerShell `Get-NetTCPConnection -LocalPort 5199`).
- Screenshot script re-opening the same `/builds/<id>` via `pushState` + `popstate` doesn't refetch (the `id` param is unchanged): navigate to `/` first, then back.
- Under vitest `URL.createObjectURL` exists, so the mock `prototypeUrl` returns a blob URL with no `?v=`: to assert the URL, spy it with `mockImplementation(httpApi.prototypeUrl)`.
- Mock `compileRecipe` needs `spec_version` set: a build from `createBuild` has null, so build-stage tests use `fixtures.build.id` (stage prototype).
- Line endings are mixed (most src files CRLF, a few LF like client.ts and Modal.tsx): a Python text-mode rewrite on Windows flips LF files to CRLF and floods the `diff`; open with `newline=''` or edit with the Edit tool. Rewriting a whole CRLF file with the Write tool flips it to LF the same way: check `diff` for whole-file hunks and restore the ending. Git Bash `sed -i` does the same to CRLF files.
- The blueprint checkpoint zip skips every folder named `build/`, so `diff` and `restore` miss src/features/workspace/build/: review those files in full and back them up yourself before risky edits.
- Modal returns focus to the `document.activeElement` at open: in a test call `button.focus()` before `fireEvent.click` to assert the return.
- Fake timers + mock API: mock `respond` uses `setTimeout(0)`, so `await api.x()` hangs under `vi.useFakeTimers`; wrap it (`await vi.runAllTimersAsync(); return promise`), see tests/activity.test.tsx `call`.
- A Python edit on Windows without `encoding='utf-8'` writes a new non-ASCII literal (`·`, `…`) as cp1252.

## Skills
Use each skill only at its step, on that task's files. If one isn't installed in your tool, skip it and say so under Gotchas. The essentials' UI design section wins over a skill's generic advice.
- frontend-design: build, before writing UI code.
- ui-ux-pro-max: build, to look up a UX rule or stack pattern instead of guessing.
- web-design-guidelines: review, on the task's changed UI files; final audit, on all UI files.
<!-- blueprint-solution:end -->
