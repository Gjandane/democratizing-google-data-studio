<!-- blueprint-solution:start  (shared by Codex and Claude Code; in an existing AGENTS.md, add only this block and keep the rest) -->
# engine: agent guide
`dsengine`: a CLI that replays a recipe (JSONL ops) in the Data Studio editor through Playwright,
attached over CDP to a signed-in Chrome profile, and streams one event per op. Target: POC.

## Commands
Run from this folder (`engine/`) in bash.
- Install: `uv sync`
- Run: `uv run dsengine --help`
- Test (all): `uv run pytest`   (each task's own check is its "Done when" in docs/plan.md; live tests run only with `-m live`)
- Lint: none
- Live demo: configure `GCP_PROJECT_ID` and a copyable `DSS_TEMPLATE_REPORT_ID` in the root `.env` when blank creation is unavailable; `uv run dsengine login` for manual first sign-in, then `uv run pytest -m live tests/live/test_golden.py -k budget`. Use `DSS_TEST_TABLE` for a different compatible source.

## Read before editing
- docs/architecture-essentials.md: always.
- docs/plan.md: find your task. Change task status only through the blueprint script.
- docs/progress.md: the latest entry, plus the entries of tasks yours depends on.
- The doc sections your task's `Spec:` names (`status` prints them): what your code must do, in full.
- docs/architecture.md: otherwise only if your task changes the design.
- docs/PRD.md: goals and non-goals; open it when a requirement is unclear.
- ../contracts/recipe.md, ../contracts/recipe.schema.json, ../contracts/conventions.md (read-only): the interfaces this part provides or consumes; read the one your task touches.

## Rules
- This folder is the engine part of Democratizing Google Data Studio. The other parts (backend `../backend/`, frontend `../frontend/`, release at `..`) are separate projects: their docs, rules and commits don't apply here; never read, edit or report on their files. From the program root's AGENTS.md, only the program block applies. The exception is the contracts above: read them, never edit them.
- Build only what the current task asks. Stay inside its Files, or say why before editing others.
- Never build anything listed under Non-goals in docs/PRD.md.
- Use only dependencies with a date in the Verified column of docs/architecture-essentials.md. Ask before adding any other.
- Never print, log or commit secret values. `.env` stays out of version control and shared copies; `.env.example` lists names only.
- Never type a password, never automate Google sign-in, never touch tabs other than the one the engine opened.
- A task is done only when its "Done when" command and Test (all) pass. Report real output; never describe a run you didn't do.
- Latitude: anything these docs don't fix is yours to decide. Pick the smallest change that passes the check and record it under Decisions in your progress entry. Smallest never means naive: code under a Spec meets all of it (rules, edge cases, budget), not just the tests.
- Before ending a session, add an entry to docs/progress.md.
- Decisions and task status live in docs/, never in a tool's memory. If a saved memory disagrees with these docs, the docs win.

## Known gotchas
- `tests/live/test_gcs_source.py` needs root .env `DSS_TEST_GCS_PATH` = `<bucket>/<path>.csv` (no `gs://`, no spaces) naming a CSV with the sample's columns, readable by the Data Studio account; check it exists with `gcloud storage ls gs://<path>` (gcloud's active account can differ from Chrome's) (2026-10-29, task 14.1).
Environment quirks stay here; editor/code conventions live in
`docs/architecture.md#Live editor conventions` and the essentials.
- Git Bash is at `C:/Program Files/Git/bin/bash.exe` (outside PATH); use PowerShell for the blueprint script if the shell wrapper misquotes its absolute Windows path.
- The Bash tool rejects multi-line heredocs holding quotes/apostrophes ("unexpected EOF while looking for matching"): write the text with Write/Edit (or a scratch file) instead (2026-10-24, task 13.2).
- The dedicated profile persists Chrome page zoom per site, and Ctrl+0 resets only to the profile default (`chrome://settings/appearance` Page zoom), which was 80% here. Live runs need 100%: `open_report` fails with the measured CSS size otherwise.
- Live Data Studio can display Data Set Configuration Error even after field metadata loads; diagnose the underlying source separately from geometry/selector failures.
- Ops failing with `TargetClosedError` (or `Chrome is not running`) mean the dedicated Chrome window closed mid-run: `uv run dsengine browser` restarts it with sign-in kept. Diagnostic scripts that attach and open tabs must close them; leftover editor tabs stay open.
<!-- blueprint-solution:end -->
- `tests/live/test_golden.py -k timeout` (30 s run budget) flakes: when the deadline cuts a chart op, `save_report` can time out at 20 s (pre-fix 1/3, after 11.1 3/5 runs, 2026-10-22). Rerun it alone before suspecting your change.
- A run of "operation timed out" after one failed op usually means a list or menu was left open: its transparent `cdk-overlay-backdrop` intercepts every later click, and retry cleanup skips Escape once the budget is spent. Close what your op opens on failure (2026-10-22, task 11.3).
- Daily time series on `order_items` and on the b_a8ace098d03b view can render "Too Many Rows" (no legend), with or without colors, and slow later ops on that page; live fixtures keep them on a page of their own.
- `tests/live/test_recipe_replay.py -k manual_acceptance` fails at s007 (six-metric table exhausts the 20 s op budget, then save/get_link fail), also with HEAD cfbc769 source (3/3 runs, 2026-10-22; passed 2/2 full runs 2026-10-23; 2026-10-24: passed 1 full run, then timed out in s007's placement `_reveal` in 1 full run and alone). Its recipe has no page or style ops; don't chase it from page, style or recipe changes.
- `tests/live/test_recipe_replay.py -k release_breakdown` (b_697880743b4f on its own dss_demo view) colors 3-5 of s011's 5 series by UI speed (4 runs, 2026-10-24); a warn "colors skipped (too little op time left)" is the budget working, not a failure.
- `tests/live/test_recipe_replay.py -k compiled_recipe` can time out at s005 (scorecard, Setup tab after placement) when the whole file runs (1 of 2 full runs, 2026-10-23, task 12.1); it passed alone. Rerun before suspecting your change.
