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
Traps that cost an earlier session time and that the other docs don't cover, one line each. Builders add lines; the architect sorts them into the docs at the final audit.
- The shared op schema permits extension fields: interpret chart-only arguments only on add_chart, since other ops can carry identically named extras of any type.
- Git Bash is at `C:/Program Files/Git/bin/bash.exe` (outside PATH); use PowerShell for the blueprint script if the shell wrapper misquotes its absolute Windows path.
- Data Studio has two View buttons; disambiguate the saved-report action from the menu. Wait for lazy iframe creation and rendered content; scorecard and table render directly.
- Cross CDK's mouse-drag threshold with a short initial move; a single large image drag can select browser text instead of moving the component.
- Live Data Studio recipes must use DSS_TEST_TABLE (default: the public order_items table); contracts fixtures use a placeholder dss_demo table that cannot load in the editor.
- Playwright `locator.is_visible()` throws on multi-match locators; check `nth()` results when a selector returns a list.
- Chart chip names open the field picker and icons open the metric editor; scope primary sort radios because Secondary sort repeats their labels.
- Drill down exposes Add dimension asynchronously; stacked presets can insert an unrequested breakdown, and a single series hides the stacking switch.
- Batch field-label reads with `locator.evaluate_all`; per-chip CDP calls can exhaust the chart's 20 s budget before Setup actions.
- The generic `chart_components` selector also matches uploaded images; exclude `image_content` when counting or indexing charts in mixed reports.
- Control drawing mode can appear before its menu closes; wait for menu closure. Selecting a date control opens a calendar; Escape before geometry or Setup.
- Date controls clear the Data panel's fields; preserve the report source names before selecting one. Geo pickers with no compatible fields show No results without Chart fields; close them on failure.
- Pivot tables require a row dimension even with columns; date preset families (Last 7 days) require a second selection in their submenu.
- Images preserve aspect ratio by default; Setup exposes Preserve Aspect Ratio for arbitrary recipe boxes.
- Multiple chart series use clickable multiColor swatches; font dropdowns can have a tooltip overlay after the options, so scope options directly.
- Text formatting requires selecting all again before each property; Escape can leave text editing active, so verify selection mode before resizing.
- To leave text editing, click Selection Mode before geometry and viewer readback; image properties may require a canvas deselection and a top-left component click.
- Saved images may be visible while naturalWidth is zero; wait for image loading. Use logical block/BR readback for blank text lines, not textContent or innerText alone.
- Add a page inserts after the current page; navigate to the last page first when appending to preserve component page indices.
<!-- blueprint-solution:end -->
