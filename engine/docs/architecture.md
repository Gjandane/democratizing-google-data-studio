# Architecture: engine
Target: POC · The source of truth for the design.
docs/architecture-essentials.md is its one-page summary: whenever this file changes, update the
essentials in the same session and run `blueprint.py stamp`.

## Stack
| Layer | Choice | Why | Alternatives rejected |
|---|---|---|---|
| Runtime | Python 3.12, uv | same toolchain as backend | Node Playwright (second runtime) |
| Browser control | Playwright for Python, `connect_over_cdp` to installed Chrome | reliable locators and waits; CDP attach avoids Google's automation sign-in block | Selenium; launching bundled Chromium |
| CLI | argparse | stdlib | click, typer |
| Recipe models | pydantic v2 + jsonschema against ../contracts/recipe.schema.json | typed ops; the contract schema is the oracle | hand-written dict checks |
| Selectors | OKF markdown files with YAML frontmatter (pyyaml) | a UI change is a data edit; same format as the backend's semantic memory | selectors in code |

## Folder structure
```text
engine/
  pyproject.toml            uv project; console script dsengine = dsengine.cli:main
  src/dsengine/
    cli.py                  argparse subcommands: run, validate, print, browser, login, check
    recipe.py               load + validate recipe (pydantic models, schema check)
    events.py               event writer (JSONL to stdout, flushed per line)
    linking.py              Linking API URL builder
    chrome.py               start Chrome with the profile, attach over CDP, signed-in check
    selectors.py            load knowledge/datastudio-ui/*.md frontmatter into a selector map
    executor.py             runs ops: verify, retry once, screenshot, events, final status
    ops/                    one module per op family: report.py, charts.py, controls.py, text.py, style.py, pages.py
    printer.py              op -> `dsengine <op> --flags` CLI line
  knowledge/datastudio-ui/  OKF bundle: index.md, log.md, one concept per UI area (selectors in frontmatter)
  spikes/                   throwaway spike scripts (task 1.3)
  tests/                    unit tests (fake driver); tests/live/ marked `live`
```

## Data model
- Recipe header and ops: exactly ../contracts/recipe.md. pydantic models mirror the schema;
  `recipe.schema.json` validation runs first and wins on any disagreement.
- Selector concept file (OKF): frontmatter `type: UI Selector Set`, `title`, `description`,
  `timestamp`, plus `selectors:` mapping a key (`add_chart_button`, `chart_menu.bar`,
  `setup.dimension_slot`, ...) to a Playwright locator string (`role=button[name="Add a chart"]`,
  `text=Bar chart`, CSS). Body text: how the UI area behaves, notes from the spike. `index.md`
  lists the files; `log.md` records selector changes, newest first.
- Component registry (in memory, per run): `component_id -> {op_id, box, page}` so later ops
  (`set_style`) can reselect a component by clicking its box centre.

## Key flows
- **run**: validate recipe (exit 2 on error) -> attach to Chrome (start it if not running) ->
  signed-in check (exit 3, `error_code: not_signed_in`) -> `run_started` -> ops in order ->
  `run_finished` -> exit code per contracts/recipe.md.
- **dry-run**: validate -> `run_started` -> for each op `op_started` + `op_finished(skipped)` ->
  `run_finished(status ok, report_url null)`. No browser.
- **login**: start Chrome with the profile at `https://accounts.google.com/` then
  `https://datastudio.google.com/`; poll the signed-in check every 3 s up to 5 min.
- Failure paths: Chrome missing -> exit 1 with a `log` error naming `DSS_CHROME_PATH`; CDP port
  busy by another browser -> `log` error and exit 1; a modal/tour popup -> dismiss via the
  `dismiss.*` selectors before each op.

## Core logic
### Recipe executor
- Problem: replay the recipe's ops in the Data Studio editor so the report matches the recipe,
  with no LLM.
- Inputs and outputs: a validated recipe (header + ops), the selector map, a Playwright `Page`;
  output: the event stream (contracts/recipe.md) and the exit code.
- Objective: as many ops `ok` as possible; the report is always saved and its link returned when
  `open_report` succeeded.
- Rules and invariants:
  - Ops run strictly in file order; exactly one `op_started` and one `op_finished` per op, in order.
  - Each op = locate (selectors) -> act -> verify a postcondition (e.g. component count +1 and the
    setup panel shows the fields; the box reads back within ±4 px where the UI exposes it).
  - Verify fails -> reset UI state (Escape, click an empty canvas spot) -> retry once -> still
    failing: screenshot `<op_id>_failed.png` into `--screens` (default
    `<recipe dir>/screens/`), `op_finished(failed, message)`, continue.
  - `open_report` failing ends the run: `run_finished(failed)`, exit 1.
  - `save_report` and `get_link` are attempted even after earlier failures.
  - Status: `ok` if no op failed; `partial` if some failed but open/save/link succeeded; else `failed`.
  - Per-op timeout 20 s; whole-run `--timeout` (default `DSS_ENGINE_TIMEOUT_S`, 600 s): when hit,
    no further ops start, `save_report` and `get_link` are still attempted, `error_code: timeout`.
  - No fixed sleep longer than 1 s (wait on conditions instead).
  - Never acts on a tab it didn't open; never navigates away from the report after `open_report`.
- Edge cases: unknown field name (op failed: "field X not in data source"); box outside the canvas
  (clamp, warn in `log`); empty recipe (only header: run ok with 0 ops); re-running the same recipe
  creates a new report (never edits the old one); onboarding popups; slow BigQuery field load
  (wait for the field list, up to the op timeout).
- Budget: median op <= 15 s; a 20-op recipe <= 5 min on this machine.
- Approach: builder's choice, informed by spike task 1.3 (how to set exact position and size:
  numeric fields in the properties panel, the arrange menu, or a precise mouse drag at 100% zoom).
- Oracle: (1) unit tests with a fake driver for the control flow (order, retry, continue,
  abort-on-open, status and exit codes); (2) the dry-run event stream validates against
  ../contracts/recipe.schema.json; (3) the live golden recipe: >= 90% ops ok, link opens, boxes
  match the recipe (read-back or manual screenshot check).

### Linking API URL
- Problem: build the URL that opens a new report in edit mode with the recipe's BigQuery table.
- Inputs and outputs: recipe header + `GCP_PROJECT_ID` + optional `DSS_TEMPLATE_REPORT_ID` -> one
  URL string.
- Rules: base `https://datastudio.google.com/reporting/create`; params `c.mode=edit`,
  `r.reportName`, `ds.ds0.connector=bigQuery`, `ds.ds0.type=TABLE`, `ds.ds0.projectId`,
  `ds.ds0.datasetId`, `ds.ds0.tableId`, `ds.ds0.billingProjectId=GCP_PROJECT_ID`; `c.reportId`
  only when the template ID is set; every value URL-encoded; deterministic param order.
  Source: https://developers.google.com/looker-studio/integrate/linking-api
- Edge cases: report name with `&`, `#`, spaces, non-ASCII; missing `GCP_PROJECT_ID` (error before
  any browser work).
- Approach: fixed (string building). The spike confirms whether the data source alias for a
  blank report is `ds0` or needs a template.
- Oracle: unit tests with exact expected URLs, including the encoding cases.

## External APIs and services
| Service | Used for | Auth | Limits and failure handling |
|---|---|---|---|
| Data Studio web editor | building the report | the user's signed-in Chrome profile | UI changes break selectors -> op failed + screenshot; fix in knowledge/ |
| Linking API (URL) | opening a report with the data source | same session | no API key; saving needs the edit-mode save click |
| BigQuery (via Data Studio) | the report's data | owner's credentials of the signed-in account | public tables billed to `GCP_PROJECT_ID` |

## Dependencies
playwright (browser control over CDP), python-dotenv (read `../.env`), pydantic (typed ops),
jsonschema (validate against the contract schema), pyyaml (selector frontmatter), pytest (tests).

## Testing
pytest; `tests/` runs offline with a fake driver; `tests/live/` needs the signed-in Chrome and is
marked `live` (excluded by default via `addopts = "-m 'not live'"`). Test (all) = `uv run pytest`.

## Live editor conventions
These conventions consolidate the verified build decisions and selector traps from tasks
1.1–5.4. They describe the local editor workflow; the recipe contract remains the interface.
- Live runs call the ownership-validated browser startup helper before checking sign-in;
  `check` stays read-only. Dry runs and header-only recipes never start Chrome.
- Retry cleanup checks the remaining budget before keyboard/mouse calls, which have no timeout
  argument; canvas bounding-box lookup uses the remaining timeout. Cleanup is best-effort.
- Interpret chart-only extension arguments only for `add_chart`; the shared op schema allows
  identically named extras of other types on other ops.
- Use the 1920 x 1200 editor viewport and 100% zoom. Place components with mouse geometry;
  cross CDK's drag threshold with a short initial move before the target move. Read boxes back
  within ±4 px. Images need Preserve Aspect Ratio disabled for arbitrary recipe boxes.
- Retain creations and their actual owning page before retry/navigation, so retry does not
  duplicate components. Append pages from the last page: Add page inserts after the current one.
- Background uploads retain pending intent before submitting the file, then retain and scope
  the created element before waiting for image loading. Resize before moving so edge placement
  cannot hide resize handles. Sending a background back refreshes registry indices on its owning
  page by element identity. `OpContext.state` also contains a source-field list: registry walks
  must filter dictionary entries before reading component state.
- Disambiguate the saved-report View action from the View menu. Saving a new report requires
  Save and share and the acknowledgement; return the saved URL without `/edit`.
- Data-access review dialogs (on create and on first save) may or may not carry the "I understand
  and accept the risk." checkbox (both variants observed on 2026-10-21). Detect the dialog itself
  (exact name: "Review data access" is a prefix of the save dialog's name), tick the checkbox only
  when present, click the dialog's own Acknowledge button (never Close), and wait for it to hide.
  Dialog visibility does not mean its controls are ready: the risk checkbox can render later
  while acknowledgement stays disabled. Within the existing operation/run budget, recheck for a
  visible checkbox and accept it when necessary, or proceed when acknowledgement is enabled.
  Do not spend the remaining budget waiting on a disabled button without rechecking the checkbox.
  Apply the same readiness rule in the spike. A timeout consumes the shared retry budget; retry
  is not a recovery strategy for this race.
- Wait for lazy chart iframes and their rendered content; scorecards and tables render directly.
  Saved images may be visible before `naturalWidth` is nonzero. Generic chart selectors also
  match uploaded images: exclude `image_content` when enumerating charts.
- Test each match when a locator has multiple results; `is_visible()` on the full locator throws.
  Batch chip labels with `evaluate_all` to stay inside the 20 s per-op budget.
- Chart chip names open field pickers; chip icons open metric editors. Scope primary sort
  radios because Secondary sort repeats their labels. Drill-down adds dimension slots
  asynchronously; presets may add an unwanted breakdown, and single series may hide stacking.
- Wait for the control menu to close before drawing. Escape the calendar opened by selecting
  a date control. Cache source field names when the editor becomes ready, before selecting any
  image or source-less control: those selections can clear the Data panel.
  A geo picker without compatible fields can omit Chart fields entirely; close it on failure.
- Pivot tables need a row dimension, even with column dimensions. Date preset families such
  as Last 7 days need a second submenu selection.
- Multiple series expose clickable multiColor swatches. Scope font options directly to avoid
  tooltip overlays. Select all text again before each formatting property; use Selection Mode
  to leave text editing before geometry/readback. Image Setup can require canvas deselection
  and a top-left component click. Poll exact title-font readback within the operation budget;
  closing dropdown options can briefly appear in the combobox text.
- Read text through logical blocks and BR elements to preserve blank lines; neither textContent
  nor innerText alone is a reliable whitespace oracle.
- Live recipes use `DSS_TEST_TABLE`; shared contract fixtures contain an unavailable placeholder
  table. Successful geo rendering needs a source with a compatible geographic field.
- Screencast is opt-in, JPEG quality 60, gated by a monotonic 500 ms interval. Acknowledge every
  CDP frame, including dropped frames; stop, remove the listener and detach before page closure.

## Decision log
| Date | Decision | Alternatives | Why | Source |
|---|---|---|---|---|
| 2026-10-18 | CDP attach to installed Chrome with a dedicated profile | Playwright-launched Chromium | Google sign-in refuses automation-launched browsers | plan |
| 2026-10-18 | Selectors as OKF files | constants in code | UI drift is fixed by editing data | plan |
| 2026-10-18 | No LLM in the engine | vision agent | token budget; recipe is complete | program |
| 2026-10-18 | Must-have ops (open, canvas, background, scorecard, time series, bar, pie, table, save, link) before the rest | all ops first | integration by 21:00; backend narrows DSS_ALLOWED_TYPES if needed | audit |
| 2026-10-19 | Mouse placement at 100% zoom with geometry readback; explicit save acknowledgement and template fallback | numeric geometry controls; blank Linking URL | spike proved exact boxes and blank `ds0` rejection; user approved the approach | tasks 1.3–3.1 |
| 2026-10-19 | Reuse created components on retry, record their real page and append pages from the end | recreate after transient failure; infer page from recipe order | prevents duplicates and preserves page indices | tasks 2.2, 4.1, 4.2 |
| 2026-10-19 | Read rendered text by logical blocks/BR; verify loaded images and saved report state | textContent-only checks; immediate screenshots | preserves blank lines and avoids accepting loading placeholders | tasks 4.2, 3.1 |
| 2026-10-19 | Owned-page CDP JPEG frames, monotonic 500 ms gating and acknowledgement of dropped frames | a background thread or an additional dependency | schema-valid opt-in streaming with deterministic cleanup | task 4.3 |
| 2026-10-20 | Start the owned browser before sign-in checking; budget retry input using supported Playwright signatures | check before startup; timeout keywords on keyboard/mouse APIs | cold runs must work and retry cleanup must actually execute | tasks 5.1–5.2, final re-audit |
| 2026-10-20 | Retain pending background uploads and element identity; refresh owning-page registry indices after reordering | upload again on retry; page-wide image lookup; stale paint-order indices | avoids duplicates and preserves later style targeting beside other images | task 5.3, final re-audit |
| 2026-10-20 | Capture source fields at editor readiness; poll exact title-font readback and saved image loading | defer field lookup until after image selection; immediate readback | live acceptance exposed cleared field panels and asynchronous editor/view state | task 5.4, final re-audit |
| 2026-10-21 | Detect data-access review dialogs by dialog, with the risk checkbox optional | pin a template or URL that avoids the dialog | Data Studio's dialog now has Close/Acknowledge only and blocked release 2.3; user chose the engine fix | change 2026-10-21, task 6.1 |
| 2026-10-21 | Wait for review controls within the existing deadline, rechecking the optional checkbox until acknowledgement is enabled | check checkbox once at dialog visibility; rely on retry | audit probe proved the checkbox renders after the dialog while the button stays disabled, consuming the shared attempt budget | final re-audit, task 7.1 |
