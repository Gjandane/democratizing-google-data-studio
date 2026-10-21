<!-- blueprint-program:start  (shared by Codex and Claude Code; every part's sessions load it, so keep it under about 1,500 characters) -->
# Democratizing Google Data Studio: program guide
An agentic app that interviews a user and builds a real Data Studio dashboard from a compiled
recipe. Each part below is its own project, with its own AGENTS.md, docs/ and plan.

## Parts
- engine (`engine/`): `dsengine` CLI, runs a recipe in Data Studio via Playwright
- backend (`backend/`): ADK 2.0 harness, memory, BigQuery intake, spec, renderer, compiler, API,
  cloud mode and the build agent (`dss-agent`)
- frontend (`frontend/`): the web app (chat, stages, click-to-comment prototype, build view,
  access-code gate)
- release (this folder): end-to-end checks, root files, Dockerfile and Cloud Run deploy, README,
  the submission deck (deck/)

## Rules
- Work inside one part per session: open the session in that part's folder and run the blueprint
  skills there. The part's AGENTS.md holds its rules and commands.
- In a part's session, only this program block applies from this file; the root part's block
  below it is for sessions opened at this folder.
- `contracts/` holds the interfaces and shared conventions between parts. A part reads the
  contracts its AGENTS.md names and never edits them; only the architect, at this root, changes
  one.
- docs/program.md holds the parts, their order and the gates between them (the `Needs:` fields).
- Hard deadline 2026-10-23 01:05 MPST: no gold-plating; the cut order is in docs/program.md.

## Known gotchas
Traps that hit more than one part, one line each. The architect adds them.
- Windows: never run uvicorn with `--reload` (breaks subprocesses/Playwright, kills running builds).
<!-- blueprint-program:end -->

<!-- blueprint-solution:start  (shared by Codex and Claude Code; in an existing AGENTS.md, add only this block and keep the rest) -->
# release: agent guide
The root part of Democratizing Google Data Studio: end-to-end checks, start scripts, root files,
the Dockerfile and Cloud Run deploy script, README and the AI Builder Cup submission deck (deck/). Target: POC.

## Commands
Run from this folder in bash (Git Bash on Windows).
- Install: `uv sync --project integration`   (the parts install with their own AGENTS.md commands)
- Run: `./start.sh`
- Test (all): `uv run --project integration python integration/check_contracts.py`   (each task's own check is its "Done when" in docs/plan.md; the e2e flow is task 2.2's check)
- Lint: none

## Read before editing
- docs/architecture-essentials.md: always.
- docs/plan.md: find your task. Change task status only through the blueprint script.
- docs/progress.md: the latest entry, plus the entries of tasks yours depends on.
- The doc sections your task's `Spec:` names (`status` prints them): what your code must do, in full.
- docs/PRD.md: goals and non-goals; open it when a requirement is unclear.
- contracts/conventions.md, contracts/recipe.md, contracts/api.md (read-only): the interfaces between the parts; read the one your task touches.

## Rules
- This folder is the root part of Democratizing Google Data Studio: the end-to-end tests, the root files and the delivery. The parts (engine `engine/`, backend `backend/`, frontend `frontend/`) are separate projects: their docs and rules don't apply here, and you never edit their files. Read the contracts, and read each part's AGENTS.md Commands to run them from that part's folder.
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
- `blueprint.py start` (folder mode) dies with PermissionError on `.chrome-profile/lockfile` while the engine's Chrome (CDP 9222) runs: close that Chrome first, then rerun start.
- Diagram "planned" tags are hardcoded in deck/diagrams/*.html and go stale as parts finish tasks: recheck them against `blueprint.py program` and re-render before using the PNGs.
- `PowerPoint.Application` here is WPS Office (wpp.exe), not MS PowerPoint: `Slide.Duplicate()` is a no-op, `FindBySlideID` returns null, `Close()` on a modified deck hangs (set `Saved=-1`); a killed build leaves `wpp.exe /Automation` blocking COM (RPC_E_CALL_REJECTED): stop that process only.
- Live model nodes fail e2e runs nondeterministically (2.2: 4 of 7 runs; plan/revise `llm_unavailable`, `invalid_source`, `invalid_request`): rerun the e2e once per new failure before blocking, and block only on a repeat at the same step.
- Stopping `./start.sh` with the Bash tool's TaskStop leaves uvicorn and vite listening: `taskkill /PID <pid> /T /F` the 8000/5173 owners (netstat) after.
- Free localhost ports don't refuse here, they time out (curl rc 28, Invoke-WebRequest stalls ~2 s): test a port with netstat/`Get-NetTCPConnection -State Listen`, not an HTTP probe. The 2.1 netstat grep also lists TIME_WAIT lines for ~2 min after any probe.
<!-- blueprint-solution:end -->
- An engine op fails with `screenshot: null`: from engine/, `uv run dsengine run --screencast <recipe.jsonl> > cast.jsonl`, then base64-decode the last `frame` event's `data` (JPEG) to see the page it stuck on.
- Backend reads os.environ over the root `.env`: start it with `DSS_ENGINE_DRY_RUN=1 uv run uvicorn ...` (and run the driver with the same var) instead of editing `.env`.
- `e2e_flow1.py --live` exit 0 is not a full build: an engine `partial` still publishes with a report_url; read `run_finished` in data/builds/<id>/v<n>/events.jsonl (`failed` count) before the manual link check.
