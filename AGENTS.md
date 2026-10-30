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
- Cloud sessions (claude.ai/code) open at the repo root: the prompt names the part and task; `cd` into
  that part's folder, follow only its AGENTS.md plus this program block, and run the builder's script
  from the repo copy: `python .claude/skills/blueprint-solution-builder/scripts/blueprint.py --root <part> ...`.
  There is no `.env`, Chrome or Google sign-in there: only tasks whose checks run offline. The repo
  copies in .claude/ are refreshed from ~/.claude by the user.
- The repo is public: the hosted URL and the project number live only in `.env` (`DSS_AGENT_SERVER`,
  `GCP_PROJECT_NUMBER`), never in a tracked file (change 2026-10-29).
- Deadline no longer binding (user, 2026-10-23): still no gold-plating; the cut order is in docs/program.md.

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
- Live model nodes fail e2e runs nondeterministically (2.2: 4 of 7 runs; plan/revise `llm_unavailable`, `invalid_source`, `invalid_request`; staged: blueprint view fails SQL validation -> 0 rows -> accept `409 artifact_invalid`): rerun the e2e once per new failure before blocking, and block only on a repeat at the same step.
- Stopping `./start.sh` with the Bash tool's TaskStop leaves uvicorn and vite listening: `taskkill /PID <pid> /T /F` the 8000/5173 owners (netstat) after.
- Free localhost ports don't refuse here, they time out (curl rc 28, Invoke-WebRequest stalls ~2 s): test a port with netstat/`Get-NetTCPConnection -State Listen`, not an HTTP probe. The 2.1 netstat grep also lists TIME_WAIT lines for ~2 min after any probe.
<!-- blueprint-solution:end -->
- An engine op fails with `screenshot: null`: from engine/, `uv run dsengine run --screencast <recipe.jsonl> > cast.jsonl`, then base64-decode the last `frame` event's `data` (JPEG) to see the page it stuck on.
- Backend reads os.environ over the root `.env`: start it with `DSS_ENGINE_DRY_RUN=1 uv run uvicorn ...` (and run the driver with the same var) instead of editing `.env`.
- `e2e_flow1.py --live` exit 0 is not a full build: an engine `partial` still publishes with a report_url; read `run_finished` in data/builds/<id>/v<n>/events.jsonl (`failed` count) before the manual link check.
- Built-in browser can't drive the CSV file chooser: in the page, fetch `/@fs/<abs repo path>/samples/ecommerce_sales.csv` from Vite (:5173), wrap it in a File, set it on `input[aria-label="CSV files"]` via DataTransfer and dispatch `change`.
- Built-in browser isn't signed in to Google (never sign in there): view a report through the engine's Chrome with a scratch Playwright script (`connect_over_cdp("http://127.0.0.1:9222")`, new tab, screenshot, close), run from engine/ with `uv run python <script>`. Open the report_url (bare `/reporting/<id>` never loads), `bring_to_front()`, wait ~25 s; it lands on the last page, so click the first nav item (120,112) for page 1; clip x>=270,y>=80 drops the avatar.
- `gcloud`/`gsutil` here need an interactive reauth (they hang or fail); ADC works: reach GCS/BigQuery from backend/ with `uv run python` + `google.auth.default()` and REST (httpx).
- `git stash drop` is denied by the auto-mode classifier: leave the drops the plan asks for to the user and list them under Left open.
- `GET /api/builds/<id>/files/events.jsonl` serves the current version's engine events: read `run_finished` (`status`, `failed`) over the API instead of the data/ folder (needed before a New version replaces "current").
- Backend sets `prototype_stale` for good after a reference change, an outline Other on a built version or a `feasibility/check` under a narrowed `DSS_ALLOWED_TYPES`: that version's recipe/run stay `409 feasibility_blocked` even after a replan (2026-10-22); do those steps last, on throwaway builds.
- `e2e_references.py` live runs: rerun only the failed cases with `--cases a,b` (the bench merges per case); `--after-restart` needs a passed synthetic case in the bench.
- Build view "Build in Data Studio" does nothing while the engine reads "Chrome not running": click "Sign in to Google" there first (opens the engine profile, already signed in); after navigating away the view forgets the recipe, so Generate recipe again.
- Built-in browser on the New build dialog: coordinate clicks/typing misfire (wrong frame, text typed twice); set the title with form_input and pick radios/buttons with a JS `.click()` (form_input on a radio doesn't update React state).
- A run fails `invalid_request` and the API shows no detail: read its `run.finished` error and the trace's per-node spans read-only, `sqlite3 "file:data/dss.sqlite?mode=ro" "select payload_json from events where run_id='<r_id>'"` (and `spans_json from traces`); publish candidates in data/.publications/ are cleaned after a failure.
- Report charts in the engine's Chrome stay blank while its window is occluded or the network is slow (blank != broken): after a nav click wait ~45 s, wheel down then up to make them paint, and use `page.screenshot(..., timeout=120000)` (fonts can stall); CDP `Page.captureScreenshot` returns blank frames there. Nav clicks can miss: check each shot's page title.
- Report view tab stays blank even after the waits above (seen 3x): `page.on("response")` on `batchedDataV2` proves the charts got rows, and an edit-mode `dsengine run --screencast` rerun's frames show them painted (it makes a new report; say so).
- Build view can keep "Chrome not running" after Sign in while `GET /api/engine/status` already says `chrome_running: true, signed_in: true` (Check again doesn't help): reload the build page, Continue to build, Generate recipe again.
- `render_diagrams.py` rerenders every deck/diagrams/*.html and rewrites unchanged PNGs with new bytes (seen on d2): `git checkout --` the deck/img PNGs your task doesn't own before staging.
- Hosted POST with no body (`curl -X POST $URL/...`) gets `411` from Google's front end, not the app: add `-H 'Content-Length: 0'` (task 4.1's agent probe then prints 401).
- Root `.env` values can carry leading spaces (`GCP_PROJECT_ID= ...`): ad-hoc `grep|cut` reads must strip whitespace (`tr -d '\r" '`), or gcloud rejects the project; deploy.sh's parser already strips.
- CSV upload `422 invalid_source` "Data service failed" after ~110 s (local and hosted): BigQuery's shared load pool (`default-pipeline`) is queueing loads past the backend's fixed 120 s wait (seen 2026-10-30: 14-16 min); list `bigquery/v2/projects/<p>/jobs?allUsers=true&projection=full` via ADC and compare `startTime` to `creationTime` before suspecting code.
- Windows TCP table can report listening sockets as `CLOSED`/`FIN_WAIT_1` (netstat and Get-NetTCPConnection alike, seen 2026-10-30): `./start.sh` then says "did not start" although both servers run; start backend (`DSS_ENGINE_DRY_RUN=1 uv run uvicorn dss.main:app --port 8000` in backend/) and frontend (`npm run dev`) by hand and wait for their ready lines.
