# Plan: engine
Target: POC · Audit: done 2026-10-18 (18 findings across the program, 18 applied)
Markers: [ ] to do, [~] in progress, [x] done, [!] blocked. Only blueprint.py changes them.
Sizes: S small, M a normal session, L needs a whole fresh session (never run unattended).

Coverage audit 2026-10-18: [report-building coverage and proposed revisions](coverage-audit.md).
This plan covers contract v1 POC features, not full Looker Studio report-building coverage.
See findings F4-F7 before the remaining tasks; proposed expansion packages are not active
tasks and require a separately specified scope/contract revision. Task statuses are unchanged.

## Phase 1: Walking skeleton and spike
- [x] 1.1 CLI skeleton, recipe validation and dry-run
  - Goal: `dsengine validate|print|run --dry-run` work on the contract fixture, and "Test (all)" is real.
  - Spec: docs/architecture.md#Recipe executor
  - Files: pyproject.toml, src/dsengine/cli.py, src/dsengine/recipe.py, src/dsengine/events.py, src/dsengine/printer.py, src/dsengine/executor.py, tests/test_contract.py, tests/test_cli.py, .gitignore
  - Depends on: none
  - Size: M
  - Done when: `uv run pytest` passes, including tests/test_contract.py, which runs `dsengine run ../contracts/fixtures/recipe.sample.jsonl --dry-run` and validates every output line against `../contracts/recipe.schema.json#/$defs/event`, and checks that a recipe with `chart_type: "donut"` makes `dsengine validate` exit 2; `uv run dsengine print ../contracts/fixtures/recipe.sample.jsonl` prints 14 `dsengine ...` lines.
- [x] 1.2 Chrome session and Linking API URL
  - Goal: `dsengine browser|login|check` manage the dedicated Chrome profile over CDP, and the URL builder is exact.
  - Spec: docs/architecture.md#Linking API URL
  - Files: src/dsengine/chrome.py, src/dsengine/linking.py, src/dsengine/cli.py, tests/test_linking.py
  - Depends on: 1.1
  - Size: M
  - Done when: `uv run pytest tests/test_linking.py` passes (exact URLs, encoding of `&`, `#`, spaces and non-ASCII names, template ID on and off, missing `GCP_PROJECT_ID` error); manual: after `uv run dsengine login` and a manual sign-in, `uv run dsengine check` prints `{"chrome_running": true, "signed_in": true}`.
  - If: Google still refuses the sign-in in the CDP-launched Chrome -> start Chrome without `--remote-debugging-port` for `login`, close it, then relaunch with the port for `run`; record it under Decisions.
- [x] 1.3 Spike: one chart in real Data Studio
  - Goal: prove the hard UI steps on the live editor and record their selectors, before building every op.
  - Spec: docs/architecture.md#Recipe executor
  - Files: spikes/spike_one_chart.py, knowledge/datastudio-ui/index.md, knowledge/datastudio-ui/log.md, knowledge/datastudio-ui/*.md
  - Depends on: 1.2
  - Size: M
  - Done when: `uv run python spikes/spike_one_chart.py` opens a report from the Linking API URL on `DSS_TEST_TABLE`, adds a bar chart with one dimension and one metric, places it at x=24 y=120 w=560 h=300, inserts an image as background and sends it to the back, saves, and prints the report URL; manual: the URL opens the saved report; the knowledge files hold every selector the spike used, each with frontmatter `type: UI Selector Set`.
  - STOP: show the user the report screenshot, per-step timings, and the answers to: (a) how exact position/size is set (numeric fields, arrange menu or mouse drag) and its measured error in px; (b) does a blank create URL accept `ds.ds0` without a template (else set `DSS_TEMPLATE_REPORT_ID`); (c) does edit mode need an explicit save click; (d) does sign-in hold across runs. The user approves the approach before 2.1.

## Phase 2: Ops
- [x] 2.1 Executor and report ops
  - Goal: the executor with verify, retry once, screenshot and continue, plus open_report, set_canvas, set_background_image, save_report and get_link on the live editor.
  - Spec: docs/architecture.md#Recipe executor
  - Files: src/dsengine/executor.py, src/dsengine/selectors.py, src/dsengine/ops/__init__.py, src/dsengine/ops/report.py, tests/test_executor.py, tests/live/test_report_ops.py, knowledge/datastudio-ui/*.md
  - Depends on: 1.3
  - Size: M
  - Done when: `uv run pytest tests/test_executor.py` passes with a fake driver covering: strict order, one start/finish pair per op, retry once then `failed` and continue, `open_report` failure ends `failed` with exit 1, `partial` vs `ok` vs `failed` status, exit 3 when not signed in; `uv run pytest -m live tests/live/test_report_ops.py` passes: a 5-op recipe ends `ok` with a report URL.
  - Review focus: run status and exit codes exactly as ../contracts/recipe.md; no op can stop the run except open_report.
- [x] 2.2 Chart ops: scorecard, time series, bar, pie, table
  - Goal: `add_chart` for these five types with dimensions, metrics and aggregation, date dimension, sort, title and options, placed at the box.
  - Spec: docs/architecture.md#Recipe executor
  - Files: src/dsengine/ops/charts.py, tests/live/test_charts_a.py, tests/live/recipes/charts_a.jsonl, knowledge/datastudio-ui/*.md
  - Depends on: 2.1
  - Size: M
  - Done when: `uv run pytest -m live tests/live/test_charts_a.py` passes: the recipe with one chart of each of the five types on `DSS_TEST_TABLE` ends with every op `ok`; manual: in the saved report each chart shows its fields and sits at its box (within ±4 px where the UI reads it back, else by eye against the recipe).
## Phase 3: Golden run (must-have for integration)
- [x] 3.1 Golden recipe and budget
  - Goal: the must-have recipe (open, canvas, background, scorecard, time series, bar, pie, table, save, link) in the backend compiler's op order runs live within budget; this is what integration needs by 21:00.
  - Spec: docs/architecture.md#Recipe executor
  - Files: tests/live/test_golden.py, tests/live/recipes/golden.jsonl, tests/live/recipes/background_p1.png
  - Depends on: 2.2
  - Size: S
  - Done when: `uv run pytest -m live tests/live/test_golden.py` passes: tests/live/recipes/golden.jsonl uses only `DSS_TEST_TABLE` columns, follows the op order of ../contracts/fixtures/recipe.sample.jsonl (open_report, set_canvas, set_background_image, charts in reading order, save_report, get_link), at least 90% of ops `ok`, `run_finished.report_url` set, total time under 300 s; `--timeout 30` on the same recipe ends with `error_code: "timeout"` and still returns a link; manual: the report opens with the background image behind the charts.

## Phase 4: Remaining ops (after integration starts)
- [x] 4.1 Chart ops: pivot table, geo map, scatter; controls
  - Goal: `add_chart` for pivot_table, geo_map and scatter, and `add_control` for date_range and dropdown.
  - Spec: docs/architecture.md#Recipe executor
  - Files: src/dsengine/ops/charts.py, src/dsengine/ops/controls.py, tests/live/test_charts_b.py, tests/live/recipes/charts_b.jsonl, knowledge/datastudio-ui/*.md
  - Depends on: 3.1
  - Size: M
  - Done when: `uv run pytest -m live tests/live/test_charts_b.py` passes with every op `ok`; manual: the date range control filters the time series from 2.2's recipe pattern when both are on the page.
  - If: geo_map can't map a field to a geo type on the test table -> mark the op `failed` with a clear message, keep it in the recipe, and record it under Gotchas; do not block the task.
- [x] 4.2 Text, image, style and page ops
  - Goal: add_text, add_image, set_style, add_page and go_to_page.
  - Spec: docs/architecture.md#Recipe executor
  - Files: src/dsengine/ops/text.py, src/dsengine/ops/style.py, src/dsengine/ops/pages.py, tests/live/test_misc_ops.py, tests/live/recipes/misc.jsonl, knowledge/datastudio-ui/*.md
  - Depends on: 3.1
  - Size: M
  - Done when: `uv run pytest -m live tests/live/test_misc_ops.py` passes: text with font size and color, an image, a style with colors on a chart, and a second page all end `ok`; unsupported style keys end `ok` with a `log` warning naming the key.
- [x] 4.3 Screencast frames (stretch)
  - Goal: `dsengine run --screencast` emits `frame` events from CDP `Page.startScreencast` at about 2 fps.
  - Files: src/dsengine/chrome.py, src/dsengine/executor.py, tests/test_screencast.py
  - Depends on: 4.2
  - Size: S
  - Done when: `uv run pytest tests/test_screencast.py` passes (frames from a fake CDP session become schema-valid `frame` events, at most one per 400 ms); manual: a live run with `--screencast` prints frame events between op events.

## Phase 5: Audit fixes
- [x] 5.1 Start the dedicated Chrome session before checking sign-in
  - Goal: a live run starts a closed dedicated Chrome profile and then checks sign-in; preserve ownership checks and exit 3 for an actually unsigned-in profile. Missing Chrome and an occupied/unrecognized CDP port must retain useful browser errors.
  - Spec: docs/architecture.md#Recipe executor; docs/architecture.md#Key flows
  - Files: src/dsengine/executor.py, src/dsengine/chrome.py, tests/test_executor.py, tests/test_linking.py
  - Depends on: 4.3
  - Size: S
  - Done when: `uv run pytest tests/test_executor.py tests/test_linking.py` passes with regressions proving a stopped browser is launched before sign-in checking, a running owned browser is reused, launch/ownership failures produce browser_error, and unsigned-in still exits 3. Dry-run and header-only recipes must not launch Chrome. `uv run pytest` passes.
  - Review focus: final-audit P1 at executor.py:124-136; do not automate sign-in or act on unrelated tabs.
- [x] 5.2 Make retry cleanup call the supported Playwright APIs
  - Goal: after a transient operation failure, Escape and canvas deselection actually run before retry, within the existing operation/run budget. Cleanup must remain best-effort if the page or canvas is unavailable.
  - Spec: docs/architecture.md#Recipe executor
  - Files: src/dsengine/executor.py, tests/test_executor.py
  - Depends on: 5.1
  - Size: S
  - Done when: `uv run pytest tests/test_executor.py` passes with strict keyboard/mouse fakes matching installed Playwright method signatures; regressions observe Escape and the empty-workspace click before the second attempt, no unsupported keyword arguments, and safe cleanup when canvas/page is absent. `uv run pytest` passes.
  - Review focus: final-audit P2 at executor.py:32,42-43; permissive mocks must not hide API signature errors.
- [x] 5.3 Scope and reuse background images across retries
  - Goal: set_background_image addresses only its own newly created image, reuses it on retry, works beside ordinary images/other backgrounds, and meets arbitrary clamped recipe boxes without aspect-ratio distortion of the box.
  - Spec: docs/architecture.md#Recipe executor; docs/architecture.md#Live editor conventions
  - Files: src/dsengine/ops/report.py, src/dsengine/ops/text.py, src/dsengine/ops/style.py, tests/test_executor.py, tests/live/test_report_ops.py, knowledge/datastudio-ui/*.md
  - Depends on: 5.2
  - Size: M
  - Done when: `uv run pytest tests/test_executor.py` and `uv run pytest -m live tests/live/test_report_ops.py` pass. New regression coverage includes an ordinary image before the background, two background ops on one page, an injected transient failure after upload (retry does not increase component count), and the 1200x900 fixture placed in a square box; verify the intended background is behind other content, loaded, and within ±4 px after saving/reopening. After sending a background back, apply set_style to an earlier component and assert that only the intended component changes (paint-order changes must not invalidate the component registry). Keep the original five-op test. `uv run pytest` passes.
  - Review focus: final-audit P2 at report.py:205-218; scope image_content under the retained component and verify that component's paint order rather than any image's presence.
- [x] 5.4 Recheck live acceptance after audit fixes
  - Goal: repeat all original live gates and the 20-op budget after tasks 5.1–5.3. Account/template/billing access was restored during the 2026-10-19 audit and the original nine live tests passed; preserve that behavior after repair. Diagnose first-query consent or data-access errors explicitly: an ok event with an error panel is not visual acceptance.
  - Spec: docs/architecture.md#Recipe executor; docs/architecture.md#Testing
  - Files: spikes/spike_one_chart.py, tests/live/test_report_ops.py, tests/live/test_charts_a.py, tests/live/test_golden.py, tests/live/test_charts_b.py, tests/live/test_misc_ops.py, knowledge/datastudio-ui/*.md
  - Depends on: 5.3
  - Size: M
  - Done when: `uv run python spikes/spike_one_chart.py`, `uv run pytest -m live tests/live/test_report_ops.py tests/live/test_charts_a.py tests/live/test_golden.py tests/live/test_charts_b.py tests/live/test_misc_ops.py`, and `uv run pytest` pass. Inspect fresh saved-report screenshots; keep the permitted incompatible-geo failure only. Record golden elapsed/median op time and 20-op elapsed under 300 s. A fresh live run with --screencast emits schema-valid frames between op events. Record every command, evidence path, and external prerequisite in docs/progress.md; never weaken render assertions to accept data errors.
  - If: the underlying source cannot be queried with the existing account/configuration -> stop with safe error evidence and the exact prerequisite the user must repair; never automate sign-in, expose secrets or provision a replacement source silently.

## Phase 6: Live UI drift
- [x] 6.1 Accept data-access review dialogs without the risk checkbox
  - Goal: open_report and save_report get past Data Studio's "Review data access" dialogs whether or not they show the "I understand and accept the risk." checkbox, so a live run reaches a saved report link again. Release 2.3 is blocked on this.
  - Spec: docs/architecture.md#Live editor conventions
  - Files: src/dsengine/ops/report.py, knowledge/datastudio-ui/linking.md, knowledge/datastudio-ui/editor.md, tests/test_executor.py, spikes/spike_one_chart.py
  - Depends on: 5.4
  - Size: S
  - Done when: `uv run pytest tests/test_executor.py` passes with new fake-page regressions: the create dialog with and without the checkbox (Acknowledge clicked once, checkbox ticked only when present, Close never clicked, editor readiness reached), and the save dialog with and without the checkbox (saved URL returned). Live: `uv run pytest -m live tests/live/test_golden.py -k budget` passes on the signed-in profile and its saved-report screenshot shows rendered charts; record elapsed and the dialog variant seen. `uv run pytest` passes.
  - If: the dialog selector `role=dialog[name="Review data access"]` also matches "Review data access before saving" (Playwright name match is a case-insensitive substring) -> make it exact (`name="Review data access"s`) or scope by the open op; record the choice under Decisions.
  - If: the live run shows a different save dialog (name or button text) -> update editor.md from the screencast's last frame (`uv run dsengine run --screencast`), not by guessing, and record it.
  - Review focus: old-variant behaviour kept (checkbox present -> ticked); Acknowledge located inside the dialog, so "Acknowledge and save" and other buttons can't match; no clicks on Close.

## Phase 7: Audit fixes
- [x] 7.1 Wait for asynchronously rendered data-access review controls
  - Goal: report creation and saving handle a risk checkbox that appears after the dialog, as well as checkbox-free dialogs, without exhausting the budget on a disabled acknowledgement button. Restore task 6.1's live gate.
  - Spec: docs/architecture.md#Live editor conventions
  - Files: src/dsengine/ops/report.py, spikes/spike_one_chart.py, tests/test_executor.py, knowledge/datastudio-ui/linking.md, knowledge/datastudio-ui/editor.md, knowledge/datastudio-ui/log.md
  - Depends on: 6.1
  - Size: S
  - Done when: `uv run pytest tests/test_executor.py` passes with regressions that fail on the pre-fix code: for both create and save, dialog visibility precedes a delayed checkbox and disabled acknowledgement; the checkbox is checked when it becomes visible and the scoped acknowledgement is clicked once. Retain initially present and absent-checkbox variants; cover checkbox-free delayed button enabling and budget exhaustion without clicking Close or waiting indefinitely. Keep exact dialog matching, existing deadlines and no fixed sleep over 1 s. `uv run python spikes/spike_one_chart.py`, `uv run pytest -m live tests/live/test_report_ops.py tests/live/test_charts_a.py tests/live/test_golden.py tests/live/test_charts_b.py tests/live/test_misc_ops.py`, and `uv run pytest` pass. Inspect fresh saved-report screenshots for rendered charts; record golden elapsed/median, 20-op elapsed under 300 s, and schema-valid screencast frames. Record the dialog variants seen and evidence paths in docs/progress.md; never weaken render assertions.
  - Review focus: P1 final re-audit 2026-10-21 at report.py:48-51 and spike_one_chart.py:108-111. The probe in .blueprint/audit-20261021/probe-observations.json observes checkbox count 0 before acknowledgement and 1/unchecked after timeout. Both attempts share one deadline (executor.py:178-185); retry cannot recover from spending it all. Fix readiness in report and spike without changing executor budgets, sign-in, unrelated tabs, credentials, or contracts.

## Phase 8: Live recipe drift (change 2026-10-21)
- [x] 8.1 Chart and control fields on a real compiled recipe
  - Goal: a recipe compiled by the backend runs live with every `add_chart` and `add_control` setting its fields, so the charts land on the background as specified. Release 2.3 is blocked on this: its live run (build b_31ee6bedd325) ended `partial`, ok 19, failed 25, while this part's own live suite passed at 20:02 the same day.
  - Spec: docs/architecture.md#Live editor conventions
  - Files: src/dsengine/ops/charts.py, src/dsengine/ops/controls.py, src/dsengine/ops/report.py, src/dsengine/executor.py, src/dsengine/chrome.py, knowledge/datastudio-ui/editor.md, knowledge/datastudio-ui/log.md, tests/test_executor.py, tests/live/test_recipe_replay.py, tests/live/recipes/*.jsonl
  - Depends on: 7.1
  - Size: M
  - Done when: diagnosis first, from `uv run dsengine run --screencast ../data/builds/b_31ee6bedd325/v1/recipe.jsonl > cast.jsonl` (AGENTS.md screencast gotcha), recorded in progress.md with the frame that shows the cause; new `tests/live/test_recipe_replay.py` replays the failing op sequence on `DSS_TEST_TABLE` with a background image: set_background_image, date_range control, then scorecard (sum, compact_numbers), time_series with `date_dimension` and two metrics (one `count_distinct`) and a sort, add_page, dropdown control, horizontal bar sorted desc, pie, table; it fails on the pre-fix code and passes after, every op `ok`, each chart's Setup fields read back as the recipe's (not the default Record Count) and each box within ±4 px; offline regressions in tests/test_executor.py cover the cause found (e.g. Setup panel not shown after insert, or a field picker that opens without the "Chart fields" heading); the replay of the release recipe above ends `run_finished` with `failed: 0`; `uv run pytest -m live tests/live/test_charts_a.py tests/live/test_charts_b.py tests/live/test_golden.py` and `uv run pytest` pass.
  - If: the editor lays out narrower than 1920 x 1200 CSS px (evidence: s006_failed.png is 3840 x 2400 with the editor drawn in its top-left quarter, the Properties panel collapsed to the right rail and the Data panel showing "Let's get started") -> read `window.innerWidth`, `innerHeight` and `devicePixelRatio` at editor readiness, make the owned Chrome window and viewport give 1920 x 1200 CSS px at 100% zoom whatever the Windows display scale, and fail `open_report` with a clear message when it can't; record the numbers seen.
  - If: the Setup tab is not shown after a chart or control is inserted -> open the Properties panel by its rail button (add the selector to editor.md from the screencast frame, with a log.md line), never by coordinates.
  - If: the table `dash_b_31ee6bedd325_v1` no longer exists in BigQuery -> skip the release-recipe replay, say so in progress.md, and rely on test_recipe_replay.py.
  - If: one type still fails after the fix -> list it with its last frame in progress.md and block naming the type; release narrows `DSS_ALLOWED_TYPES` (program cut order).
  - Review focus: contracts/recipe.md 1.0 (no new op or argument); selectors only from knowledge/datastudio-ui; no fixed sleeps over 1 s; existing budgets unchanged; the replay asserts on read-back fields, not on op status alone.

## Phase 9: Tall canvas (change 2026-10-21)
- [x] 9.1 Placement on a canvas taller than the viewport
  - Goal: a backend-compiled recipe whose page canvas is taller than the 1920 x 1200 viewport (per_section pages) runs live with every op `ok`: the background image lands at its recipe box behind everything, and charts, controls and text below the fold land at their boxes. Release 2.3 is blocked on this: its live run b_b2ac19ea6696 ended `partial`, ok 36, failed 3, all on page 3 (canvas 1200 x 1492); pages 1-2 passed with 8.1's fix.
  - Spec: docs/architecture.md#Live editor conventions
  - Files: src/dsengine/ops/report.py, src/dsengine/ops/charts.py, src/dsengine/ops/controls.py, src/dsengine/ops/text.py, knowledge/datastudio-ui/editor.md, knowledge/datastudio-ui/log.md, tests/test_executor.py, tests/live/test_recipe_replay.py, tests/live/recipes/*.jsonl
  - Depends on: 8.1
  - Size: M
  - Done when: diagnosis first, from `uv run dsengine run --screencast ../data/builds/b_b2ac19ea6696/v1/replay_p3.jsonl > cast.jsonl` (AGENTS.md screencast gotcha), recorded in progress.md with the frame that shows the cause (known evidence: ../data/builds/b_b2ac19ea6696/v1/screens/replay_s025_stuck.jpg, replay_last.jpg, s034_failed.png: background_p3.png inserted at natural size near x420 y356, Image properties and the Arrange > Order menu left open; the next add_chart leaves the image selected and opens a "Choose a field" filter chip; table at x24 y884 w1152 h304 drawn ~400 px wide; bar at y1204 times out); `tests/live/test_recipe_replay.py` gains a tall-canvas case on `DSS_TEST_TABLE`: add_page, set_canvas 1200 x 1492, set_background_image full canvas, then a table at y884 h304 and a bar at y1204 h264 (plus one control or text box below y1200); it fails on the pre-fix code and passes after, every op `ok`, each box within ±4 px read back in canvas coordinates, the background at 0,0 full size and last in paint order, each chart's Setup fields read back as the recipe's; offline regressions in tests/test_executor.py cover the cause found (e.g. drag target outside the viewport, background left selected or a menu left open); replaying ../data/builds/b_b2ac19ea6696/v1/recipe.jsonl ends `run_finished` with `failed: 0`; `uv run pytest -m live tests/live/test_recipe_replay.py tests/live/test_charts_a.py tests/live/test_charts_b.py tests/live/test_golden.py` and `uv run pytest` pass.
  - If: the editor canvas does not scroll to bring the region into view -> record what was tried in log.md and block; never zoom below 100% or place by keyboard nudging without a readback.
  - If: the table `dash_b_b2ac19ea6696_v1` no longer exists in BigQuery -> skip the release-recipe replay, say so in progress.md, and rely on test_recipe_replay.py.
  - If: one op type still fails below the fold after the fix -> list it with its last frame in progress.md and block naming the type.
  - Review focus: contracts/recipe.md 1.0 (no new op or argument); selectors only from knowledge/datastudio-ui; no fixed sleeps over 1 s; existing budgets unchanged; 8.1's replay still passes; the replay asserts on read-back boxes and fields, not on op status alone.

## Phase 10: Manual acceptance fixes (change 2026-10-22)
- [x] 10.1 Off-screen picker fields, date control size and table rows per page
  - Goal: the recipes from release 2.4's failed rows run live with every op `ok`. Release 2.4 is blocked on this: research build b_568901c19819 ended `partial` (ok 35, failed 6: three tables `add_chart` "Data Studio option 15 is unavailable" for `options.rows_per_page: 15`, plus their `set_style`), BigQuery build b_b17ad783d730 ended `partial` (ok 42, failed 3: `add_chart` scorecard `count_distinct` of `user_id` "field user_id not in data source", and `add_control` date_range "control box did not match the requested position and size").
  - Spec: docs/architecture.md#Live editor conventions
  - Files: src/dsengine/ops/charts.py, src/dsengine/ops/controls.py, knowledge/datastudio-ui/editor.md, knowledge/datastudio-ui/log.md, tests/test_executor.py, tests/live/test_recipe_replay.py, tests/live/recipes/*.jsonl
  - Depends on: 9.1
  - Size: M
  - Done when: diagnosis first, recorded in progress.md with the frame that shows each cause (known evidence in ../data/builds/b_b17ad783d730/v1/screens/: s014_failed.png shows the scorecard field picker open with `user_id` in the Data panel but below the picker list's visible rows, so `_choose_picker_field` finds no visible button; s004_failed.png and s014_failed.png show the date_range control drawn at about 302 x 52 instead of 276 x 44 at x24 y264, overlapping the dropdown at x316; ../data/builds/b_568901c19819/v1/screens/s012_failed.png the rows-per-page menu); fixes: (1) a field that exists in the source but is outside the picker's visible list is found (through the picker's search box or by scrolling it into view) and selected, for chart dimensions, metrics, date dimension, breakdown, sort and dropdown fields alike; (2) a date_range control lands at its recipe box within ±4 px like every other control; (3) a table `rows_per_page` the Data Studio menu doesn't offer applies the nearest offered value (ties: the smaller), the op ends `ok` and its message names the requested and applied values; `tests/live/test_recipe_replay.py` gains cases on `DSS_TEST_TABLE` (order_items): a scorecard `count_distinct` of `user_id` and a table dimension `status` with `rows_per_page: 15`, after a date_range control at x24 y264 w276 h44 and a dropdown at x316; they fail on the pre-fix code and pass after, every op `ok`, Setup fields read back as the recipe's, each box within ±4 px; offline regressions in tests/test_executor.py for the nearest-value choice and the off-screen field lookup; replaying ../data/builds/b_b17ad783d730/v1/recipe.jsonl and ../data/builds/b_568901c19819/v1/recipe.jsonl each ends `run_finished` with `failed: 0`; `uv run pytest -m live tests/live/test_recipe_replay.py tests/live/test_charts_a.py tests/live/test_charts_b.py tests/live/test_golden.py` and `uv run pytest` pass.
  - If: Data Studio enforces a minimum date_range control size larger than the recipe box -> record the minimum (w x h) in editor.md and progress.md and block naming it; the backend's layout then reserves it (change flow). Never accept a box outside ±4 px.
  - If: the rows-per-page setting is a free number input, not a menu -> type the recipe's value and read it back; no nearest-value mapping.
  - If: a replay table (`dash_b_b17ad783d730_v1`, `dash_b_568901c19819_v1`) no longer exists in BigQuery -> skip that replay, say so in progress.md, and rely on test_recipe_replay.py.
  - Review focus: contracts/recipe.md 1.0 (no new op or argument; the nearest-value rule is an engine behaviour reported in the op message); selectors only from knowledge/datastudio-ui; no fixed sleeps over 1 s; existing budgets unchanged; 8.1's and 9.1's replays still pass; the replay asserts on read-back boxes and fields, not on op status alone.
