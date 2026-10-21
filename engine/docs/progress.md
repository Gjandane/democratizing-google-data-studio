# Progress log
Append-only handoff log: one entry per session, newest at the bottom, written for someone with no
context. Task status lives in docs/plan.md, not here.

## 2026-10-18: Plan engine (POC)
- Status: done
- What changed: wrote PRD, architecture, essentials, plan (9 tasks), AGENTS.md, CLAUDE.md
- Decisions: recipe and events exactly as ../contracts/recipe.md; Chrome = installed Google Chrome with a dedicated profile, attached over CDP; selectors live in knowledge/datastudio-ui/ (OKF); no LLM in the engine; live tests use bigquery-public-data.thelook_ecommerce.order_items billed to GCP_PROJECT_ID.
- Baseline: new project: none
- Next: Task 1.1. Start by creating the uv project with the `dsengine` console script and the contract test against ../contracts/fixtures/.

## 2026-10-18: Audit
- Status: done
- What changed: one reviewer audit across the program (18 findings: 2 P0, 4 P1, 9 P2, 3 P3 plus a pass note); all 18 accepted by the user and applied to contracts/ and every part's docs
- Decisions: backend thin slice 1.3 before memory depth; engine must-have ops by 21:00 with DSS_ALLOWED_TYPES as fallback; shared API fixtures in ../contracts/fixtures/api/; no uvicorn --reload on Windows; gates written into docs/program.md's roadmap
- Next: build, starting with task 1.1

## 2026-10-18: Task 1.1 CLI skeleton, recipe validation and dry-run
- Status: done
- Plan check: off
- What changed: installed CLI, shared-schema JSONL validation, quoted command printing, flushed UTC events, dry-run executor and offline tests.
- Checks: `uv sync` PASS; `uv run dsengine --help` PASS; Done when and Test (all) `uv run pytest` PASS (39 tests, 3.03s); `uv run dsengine print ../contracts/fixtures/recipe.sample.jsonl` PASS (14 lines). Contract tests validate all 30 fixture events and reject donut. Read-only blueprint reviewer: no remaining findings.
- Decisions: user approved uv_build >=0.9.7,<0.10; added and verified via `deps --write`. Added package initializer and uv.lock for installation. Schema owns op arguments; Pydantic Operation retains extras. Recipe resolves assets relative to its file. Invalid runs emit one log/error event and exit 2. Live execution returns failed/not_implemented until later tasks. Dry-run previews all ops regardless of timeout. Updated AGENTS.md with the schema-extension gotcha.
- Tried and failed: first suite 37 passed/1 failed from an incorrect fixture index; corrected to select op s008. Reproduced and fixed reviewer P2 printer crash on permitted extension fields.
- Gotchas: Git Bash is at C:/Program Files/Git/bin/bash.exe, outside PATH.
- Left open: none.
- Next: Task 1.2 Chrome session and Linking API URL; implement dedicated-profile commands and URL builder.

## 2026-10-18: Task 1.2 Chrome session and Linking API URL
- Status: done
- Plan check: off
- What changed: added browser/login/check commands, dedicated-profile Chrome launch and CDP attachment, manual-login polling, and deterministic Linking API URL building with exact encoding tests.
- Checks: Done when `uv run pytest tests/test_linking.py` PASS (27 tests, 0.68s); Test (all) `uv run pytest` PASS (66 tests, 3.61s). Live login exited 0 after user manual sign-in; check exited 0 with `{"chrome_running": true, "signed_in": true}`. Browser no-op and CLI help PASS. Read-only reviewer: no findings, including final defensive handling.
- Decisions: `linking.build_url(Header, project_id=None, template_id=None)` reads env defaults, uses percent-encoded spaces and template last. Call before browser work. `ChromeConfig.from_env()` anchors relative profiles to engine/. CDP ownership uses a websocket/port marker in the dedicated profile; foreign endpoints are refused. Checks create/close their own probe page; login leaves its manual-sign-in page open. Sign-in requires a Google session cookie and a Studio landing host. Added verified Playwright to pyproject.toml/uv.lock; recorded shell gotcha in AGENTS.md.
- Tried and failed: blueprint diff through Git Bash misquoted its absolute Windows path; PowerShell succeeded. No failed implementation checks.
- Gotchas: Google accepted CDP sign-in; fallback was unnecessary.
- Left open: none.
- Next: Task 1.3 Spike: one chart in real Data Studio; use build_url and the signed-in dedicated Chrome profile, collect selectors and timings.

## 2026-10-18: Task 1.3 Spike: one chart in real Data Studio
- Status: partial
- Plan check: off
- What changed: added an entry-only live spike and selector knowledge files; added already-verified PyYAML to pyproject.toml/uv.lock outside task Files because selector loading requires it.
- Checks: Done when `uv run python spikes/spike_one_chart.py` FAIL (exit 1: invalid ds0 alias); Test (all) `uv run pytest` PASS (66 tests, 4.21s). `uv run dsengine check` reported chrome_running=true, signed_in=true. Screenshot: spikes/screens/entry.png, visually inspected.
- Decisions: blank create with ds.ds0 is rejected after data-access acknowledgement; DSS_TEMPLATE_REPORT_ID is absent. Navigation 0.719s; entry/review/load/screenshot total 5.172s. Keep task in progress while awaiting a compatible template. No saved report exists from this spike; geometry, chart, background, explicit save, and post-restart sign-in remain unverified.
- Tried and failed: initial import lacked PyYAML; installed verified 6.0.3. Live blank-create probe consistently returned "ds0 is not a valid data source alias for this report"; no implementation retries of chart behavior were attempted.
- Gotchas: none.
- Left open: review not run because implementation is incomplete.
- Next: obtain a template report with compatible ds0 alias, configure DSS_TEMPLATE_REPORT_ID without exposing secrets, then resume 1.3; collect chart/image selectors, separate step timings, box readback error, saved URL and approval evidence before 2.1.

## 2026-10-18: Task 1.3 Spike: one chart in real Data Studio
- Status: partial
- Plan check: off
- What changed: completed live spike and editor selector knowledge; saves a new report with bar chart and full-page image behind it, reloads the saved view, checks geometry and rendered chart, writes screenshots and per-step evidence.
- Checks: `uv run python spikes/spike_one_chart.py` PASS (exit 0); Test (all) `uv run pytest` PASS (66 tests, 3.73s). Saved URL opens after reload; report.png and saved_view.png visually inspected. Read-only blueprint reviewer: no findings. Evidence: spikes/screens/evidence.json; total 37.453s, median step 2.586s.
- Decisions: mouse drag at 100% zoom, 1920x1200 viewport; chart [24,120,560,300], background [0,0,1200,900], both 0 px error. Blank ds0 fails; configured template succeeds. Explicit Save and share plus acknowledgement required. Persistent sign-in held across script runs; browser restart untested. Spike uses test-table status/Record Count defaults. Recorded reusable UI gotchas in AGENTS.md.
- Tried and failed: ambiguous View locator caused one failed implementation run; disambiguated action passed. Visual QA found loading placeholders; added iframe render waits and reload verification, then passed again.
- Gotchas: none beyond AGENTS.md.
- Left open: task 1.3 STOP approach approval pending; keep [~] until user accepts.
- Next: obtain user approval of screenshot, timings and approach; record acceptance, mark 1.3 done through blueprint.py, then hand off 2.1 to a new chat. Folder mode; no Git commit.

## 2026-10-18: Task 1.3 Spike: one chart in real Data Studio
- Status: done
- Plan check: off
- What changed: recorded the user's explicit approval of the report screenshot, per-step timings and spike approach; closed the task 1.3 STOP gate. No implementation changes after verification.
- Checks: previous completed verification remains applicable: `uv run python spikes/spike_one_chart.py` PASS (exit 0), saved report reloaded and visually inspected; Test (all) `uv run pytest` PASS (66 tests, 3.73s). Read-only reviewer: no findings. No checks rerun for this approval-only update.
- Decisions: user approved mouse geometry at 100% zoom (0 px error), template fallback, explicit save acknowledgement and persistent sign-in across script runs. Browser-process restart remains untested. Carry the recorded editor selectors and evidence into task 2.1.
- Tried and failed: none in this approval update.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: Task 2.1 Executor and report ops, in a new chat using $blueprint-solution-builder. Folder mode; no Git commit.

## 2026-10-18: Task 2.1 Executor and report ops
- Status: done
- Plan check: off
- What changed: implemented ordered live execution with verification, retry, failure screenshots, timeout finalizers, and report creation, canvas sizing, background image, save and link operations. Added selectors and fake-driver/live coverage.
- Checks: `uv run pytest tests/test_executor.py` PASS (11 tests); `uv run pytest -m live tests/live/test_report_ops.py` PASS (1 test, 26.55s; five ops returned ok and a saved view URL); Test (all) `uv run pytest` PASS (77 passed, 1 deselected, 4.98s). Read-only reviewer: no findings.
- Decisions: skip timed-out non-finalizers with explicit lifecycle events and no UI call; readiness waits for a visible generic Data panel field. Keep 20 s per-op timeout, mouse placement at 100% zoom, clamp image bounds with a warning, and strip `/edit` from saved links.
- Tried and failed: live fixture table `dss_demo` is a placeholder and cannot load; use `DSS_TEST_TABLE`. Initial page-style accessible name casing and multi-match field visibility caused live failures; corrected selectors and multi-match visibility handling.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: Task 2.2 Chart ops: scorecard, time series, bar, pie and table. Start a new chat with `$blueprint-solution-builder`.

## 2026-10-18: Task 2.2 Chart ops: scorecard, time series, bar, pie, table
- Status: done
- Plan check: off
- What changed: completed five chart types with fields, aggregations, dates, breakdowns, sort, titles, options and geometry verification. Added saved-report and retry regressions; updated selectors.
- Checks: `uv run pytest -m live tests/live/test_charts_a.py` PASS (3 tests, 173.31s); Test (all) `uv run pytest` PASS (77 passed, 4 deselected, 4.72s). Main recipe: 8/8 ok. Saved fields/aggregations independently checked; screenshots inspected; boxes within 4 px. Evidence: tests/live/screens/charts_a/. Reviewer: no findings.
- Decisions: retain 20 s budget and 100% zoom; reuse charts on retry; reject unsupported empty shapes; accept equivalent single-series stacking. Batch field-label reads. Median op 5.914s. Updated AGENTS.md gotchas.
- Tried and failed: gallery/chip ambiguity, secondary sort, drill-down timing, preset defaults, early screenshots and serial-read timeouts; corrected. Browser/navigation transients passed on rerun; restart retained sign-in.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: Task 3.1 Golden recipe and budget. Start a new chat with `$blueprint-solution-builder`. Folder mode; no Git commit.

## 2026-10-18: Report-building plan coverage audit
- Status: audit complete; implementation task statuses unchanged.
- What changed: added docs/coverage-audit.md with a feature-family matrix, seven prioritized findings, official Google sources and proposed expansion sequence; linked it from docs/plan.md. No product code, architecture or shared contracts changed.
- Checks: Test (all) `uv run pytest` PASS (77 passed, 4 deselected, 4.73s). No live tests run; implemented/live-tested claims distinguish source inspection from prior progress evidence.
- Decisions: user explicitly selected report-building scope, excluding sharing permissions, scheduled delivery, connector administration and Pro administration. Preserve existing docs/plan.md workflow rather than create a competing _blueprint/. PNG background is implemented; editable text/images/styles/pages and two controls are pending; native calculated fields/blends are excluded and persistent filters are absent. Full report-building parity requires a separate scope/design/contract revision.
- Findings: correct component identity/dispatch task scope, contradictory geo acceptance, incomplete miscellaneous-op checks and the gap between the golden reliability gate and feature-completeness/budget proof. Detailed evidence and recommended acceptance changes are in the audit.
- Left open: expansion scheduling against the POC deadline; shared contract revision must be handled by the architect at program root under the program guide. No other project files were inspected or changed.
- Next: use the audit to revise the remaining POC acceptance checks and plan the report-building expansion; first new feature priorities are native calculated fields and persistent filters after the interface/identity foundation.

## 2026-10-18: blueprint-builder startup escalation
- Status: blocked at skill startup; implementation task statuses unchanged.
- What changed: created _blueprint/ESCALATION.md to record the invoked skill's missing required build kit. The directory contains only the escalation; no competing plan was generated.
- Checks: `python C:/Users/gjand/.codex/skills/blueprint-builder/scripts/state.py status` FAIL (exit 1: no _blueprint/ directory). No product changes; no tests run.
- Decisions: do not substitute docs/plan.md for the invoked skill's required STATE.md/manifest/context/decisions/step files. Existing progress identifies blueprint-solution-builder as the continuation workflow.
- Left open: select the existing blueprint-solution-builder workflow or obtain an architect-generated _blueprint/ kit.
- Next: resolve _blueprint/ESCALATION.md before resuming the invoked skill.

## 2026-10-18: Task 3.1 Golden recipe and budget
- Status: done
- Plan check: off
- What changed: added golden.jsonl, background_p1.png and live acceptance tests for compiler op order, budget, saved report rendering/geometry and timeout recovery. Preserved evidence under tests/live/screens/golden/.
- Checks: `uv run pytest -m live tests/live/test_golden.py` PASS (2 passed, 86.92s); Test (all) `uv run pytest` PASS (77 passed, 6 deselected, 5.52s). Golden: 10/10 ok, 41.609s total, median op 2.929s. Timeout 30: error_code timeout, saved link reopened, 35.359s including finalizers. Manual: saved report screenshot inspected, background behind all five rendered charts, geometry within 4 px. Reviewer: no findings.
- Decisions: use one scorecard and existing order_items columns, substitute DSS_TEST_TABLE at runtime; compare supported op order against shared fixture. Exclude images from chart enumeration. Added AGENTS.md gotcha and durable acceptance evidence beyond task Files.
- Tried and failed: initial saved-report test counted the background as a chart; fixed filtering. Initial timeout run could not save after a UI timeout; unchanged engine passed rerun.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: Task 4.1 Chart ops: pivot table, geo map, scatter; controls. Start a new chat with `$blueprint-solution-builder`. Folder mode; no Git commit.

## 2026-10-18: Task 4.1 Remaining charts and controls
- Status: done
- Plan check: off
- What changed: chart/control handlers, selectors, live checks; registered controls outside task Files. Evidence: tests/live/screens/charts_b/.
- Checks: `uv run pytest -m live tests/live/test_charts_b.py --basetemp=.blueprint/check41verified -q` PASS (2 passed, 100.25s); Test (all) `uv run pytest` PASS (77 passed, 8 deselected, 4.37s). Main: 8 ok, permitted geo failure; median 4.610s, total ops 41.153s. Saved geometry/fields verified; screenshots inspected: date control filters time series to October 11–17. Reviewer: no findings.
- Decisions: pivot options replace dimensions; require rows. Scatter metrics map to X/Y/size. Cache source fields across date selection; reuse controls on retry. Added AGENTS.md gotchas.
- Tried and failed: geo picker left open; control menu/calendar overlays; empty pivot rows; preset submenu; transient chart text; one pivot budget timeout (unchanged rerun passed).
- Gotchas: order_items has no compatible geo fields; retained geo op fails clearly as allowed. Successful geo rendering untested.
- Left open: none.
- Next: Task 4.2 Text, image, style and page ops. New chat with `$blueprint-solution-builder`. Folder checkpoint; no Git commit.
 
## 2026-10-18: Task 4.2 Text, image, style and page ops
- Status: partial
- Plan check: off
- What changed: attempted handlers, selector bundle, registration and live acceptance; restored checkpoint after two geometry failures. Recoverable implementation: `.blueprint/attempts/task-4.2-20261018-220719/`.
- Checks: `uv run pytest -m live tests/live/test_misc_ops.py --basetemp=.blueprint/check42c -q` FAIL (1 failed, 103.54s): 9/12 ops ok; text geometry, image Setup selection, second-page text failed. Test (all) `uv run pytest` PASS after restore (77 passed, 8 deselected, 4.20s). Earlier offline check passed with changes. No final visual acceptance.
- Decisions: reuse creations on retry; verify rendered text and color previews; disable image aspect preservation. Registration requires ops/__init__.py outside task Files. Added observed UI gotchas to AGENTS.md. Folder mode.
- Tried and failed: initial open timeout; first implementation failed retry geometry and text-size readback; correction fixed chart styles and text-size readback but geometry still failed. Evidence: `.blueprint/check42b/` and `.blueprint/check42c/`.
- Gotchas: none beyond AGENTS.md.
- Left open: P2 actual creator-page tracking — saved `src/dsengine/ops/style.py:39`; P2 whitespace-only text verification — saved `src/dsengine/ops/text.py:139`.
- Next: resume 4.2 in a new chat; inspect saved code/evidence, resolve text selection/resize and image selection before another live run; fix review findings and verify persistence/budget.

## 2026-10-19: Change Cloud Run deployment (program root)
- Status: done
- What changed: the architect, at the program root, lifted Cloud Run from non-goal to goal and moved the deadline to 2026-10-20 01:05 MPST; contracts/api.md and contracts/conventions.md are now 1.1 (access code, agent mode, agent endpoints, Cloud deployment, Build agent); a reviewer delta audit (33 findings) was applied.
- Affects: no engine task; the engine stays local and the CLI is unchanged (backend's `dss-agent` runs `dsengine run` on the user's machine). PRD wording and the conventions row updated.
- Next: finish 4.2.

## 2026-10-19: Task 4.2 Text, image, style and page ops
- Status: done
- Plan check: off
- What changed: implemented and registered text/image/style/page handlers; selector bundle and 20-op saved-report acceptance. Evidence: `.blueprint/check42final/test_misc_ops0/` (events and three page screenshots).
- Checks: `uv run pytest -m live tests/live/test_misc_ops.py --basetemp=.blueprint/check42final -q` PASS (1 passed, 85.19s); Test (all) `uv run pytest` PASS (77 passed, 9 deselected, 6.42s). 20/20 ops ok; summed ops 65.289s, median 2.633s. Saved formatting, images, three pages and geometry verified; screenshots inspected. Reviewer: no findings.
- Decisions: reuse creations on retry; record actual component ownership before navigation; append pages from the last page to preserve indices; logical block/BR readback preserves blank lines. Registration requires ops/__init__.py outside task Files. Updated AGENTS.md gotchas. Folder mode. Concurrent PRD/essentials edits and escalation removal were preserved, not authored here.
- Tried and failed: image selection/text edit focus; saved textContent loses line breaks; image visible before load; blank-line readback and insertion after current. Fixed with observed state/condition checks; exact font-size matching fixes review P2.
- Gotchas: none beyond AGENTS.md.
- Left open: none.
- Next: Task 4.3 Screencast frames (stretch). Start a new chat with `$blueprint-solution-builder`.

## 2026-10-19: Task 4.3 Screencast frames (stretch)
- Status: done
- Plan check: off
- What changed: added owned-page CDP JPEG capture in chrome.py and opt-in executor lifecycle; tests/test_screencast.py covers contract validity, throttling, acknowledgement and cleanup.
- Checks: `uv run pytest tests/test_screencast.py` PASS (7 passed, 4.54s); Test (all) `uv run pytest` PASS (84 passed, 9 deselected, 15.35s). Live `uv run dsengine run .blueprint/check43/recipe.jsonl --screencast` PASS (exit 0, 4/4 ops ok, 38 schema-valid frames between op events, stderr empty). Evidence: `.blueprint/check43/events.jsonl`, `summary.json`. Read-only reviewer: no findings.
- Decisions: use monotonic 500 ms emission gating (about 2 fps), JPEG quality 60, acknowledge every received frame including dropped frames; stop capture, remove listener and detach before closing the owned page. No background thread or new dependency. Evidence stored under .blueprint outside task Files. Folder checkpoint; no Git repository.
- Tried and failed: none.
- Gotchas: none.
- Left open: none.
- Next: all 9 tasks complete; return to the solution architect for final audit and retro.


## 2026-10-19: Final audit checkpoint (paused by user)
- Status: incomplete; user asked to change the signed-in account and project before continuing. Live runner stopped; no audit test processes remain. No final verdict or acceptance recorded.
- What changed: consolidated build decisions/editor conventions into docs/architecture.md and architecture-essentials.md; moved durable gotchas out of AGENTS.md; drafted Phase 5 audit-fix tasks 5.1 (Chrome startup, S), 5.2 (retry cleanup APIs, S), 5.3 (background image scoping/reuse, M), 5.4 (live acceptance/data access, M). No product code changed.
- Checks: `uv run pytest` PASS (84 passed, 9 deselected, 6.09s); explicit contract/linking/executor/screencast subset PASS (48 passed, 4.02s); CLI print produced 14 lines; blueprint lint before drafting Phase 5 PASS (0 errors, 0 warnings); stamp ran after architecture edits. `uv run dsengine check` initially false/false, then explicit `uv run dsengine browser` and check true/true (persisted session).
- Live checks: spike FAIL (AssertionError at add_bar_chart; screenshot shows Data Set Configuration Error). Report operations PASS (1 passed, 23.10s). Charts A FAIL (1 failed, 2 passed, 157.39s); primary recipe emitted 8/8 ok but saved report showed a data error instead of rendered data. Golden FAIL (1 failed, 1 passed, 105.50s; normal-budget saved rendering failed, timeout recovery passed). Charts B interrupted; miscellaneous ops and fresh live screencast not run. Evidence: .blueprint/audit-20261019/; spike evidence in spikes/screens/. Initial report check with a missing basetemp parent errored at fixture setup; parent created and rerun passed.
- Review: read-only reviewer found P1 run does not start a closed Chrome session, P2 retry reset passes unsupported timeout arguments to Keyboard.press/Mouse.click, and P2 background uploads are unscoped and repeated on retry. These are planned repairs, not fixes. No tracked engine secrets, unverified direct dependencies or implemented non-goals reported. Background aspect-ratio handling remains a regression case to verify. Follow-up review of drafted tasks was interrupted at user pause.
- Decisions: retain strict live render assertions. Data-error panels prevent sign-off even if op events say ok. Existing timeout-skipped lifecycle events are a recorded task 2.1 decision; the literal contract wording remains an interpretation to raise at program root, not silently change here. No sibling project files or shared contracts changed.
- Left open: user account/project change; unfinished live checks and task-plan review; PRD limitations/release checklist; final stamp/lint and final audit entry/commit after audit completes. No final-audit commit yet.
- Next: wait for the user to say continue. Recheck Chrome/session and configuration without exposing values, then resume the final audit against the new account/project; rerun affected live checks. Never automate sign-in.


## 2026-10-19: New-account live-check checkpoint
- Status: incomplete; live runner stopped while the user updates configuration for the new account.
- Checks: dsengine login confirmed Data Studio sign-in; offline suite PASS (84 passed, 9 deselected, 6.59s); blueprint lint PASS (13 tasks, zero errors/warnings). New-account spike FAIL (open_report timeout); screenshot shows "Copying is disabled for this report" for the configured template. Report-ops live test FAIL (exit 1, 9.63s). Charts A FAIL (3 failed, 28.11s), golden FAIL (2 failed, 19.17s), charts B FAIL (2 failed, 18.74s); miscellaneous suite interrupted. These runs encounter the template-entry blocker; no sign-off.
- What changed: reviewer confirmed Phase 5 repair coverage; added a regression to 5.3 proving set_style still targets the intended earlier component after background paint-order changes, with style.py included in Files. No product code or env edits.
- Evidence: .blueprint/audit-20261019-newaccount/ and spikes/screens/failed.png.
- Left open: configure GCP_PROJECT_ID for the intended billing project and a compatible DSS_TEMPLATE_REPORT_ID accessible/copyable by the new account; public DSS_TEST_TABLE remains suitable for existing fixtures. Then rerun live checks. Account credentials are never stored in env.

## 2026-10-19: Audit (final)
- Verdict: DEFECTS. The original live acceptance gates now pass with the current account/configuration; three independently reviewed implementation defects still require Phase 5. No product code changed in this audit.
- What changed: consolidated durable editor conventions and task decisions into docs/architecture.md and architecture-essentials.md; kept environment quirks and documented the live-demo command in AGENTS.md. Added known limitations to PRD.md and four reviewed audit-fix tasks in plan.md. Task 5.3 includes component-registry stability after background paint-order changes. Task 5.4 rechecks acceptance after repairs; the earlier data-access blocker is no longer active.
- Task 1.1: `uv run pytest` PASS (84 passed, 9 deselected, latest run 6.99s), including dry-run/event-schema validation and invalid-donut rejection; `uv run dsengine print ../contracts/fixtures/recipe.sample.jsonl` produced 14 lines. Explicit contract/linking/executor/screencast subset PASS (48 passed, 4.02s) earlier in this audit. No earlier task acceptance gate was skipped.
- Task 1.2: linking tests pass in both suites above. New-account manual-login checkpoint is recorded above; final `uv run dsengine check` reports chrome_running=true, signed_in=true. The original cold-start observation exposed defect 5.1; explicitly starting the browser restored the persisted session.
- Task 1.3: clean `uv run python spikes/spike_one_chart.py` PASS (exit 0, summed steps 33.062s); saved view reloaded, chart [24,120,560,300] and background [0,0,1200,900] both have 0 px error. Saved screenshot inspected. The first resumed spike failed with a Grant consent dialog; it is retained as a failed attempt. A later diagnostic found the dialog already absent and real chart data rendered (no Allow click was performed by that diagnostic). The clean rerun required no assistant intervention.
- Task 2.1: `uv run pytest -m live tests/live/test_report_ops.py --basetemp=.blueprint/audit-20261019-resumed/test_report_ops -q` PASS (1 passed, 20.82s); executor unit tests pass in the suites above.
- Task 2.2: `uv run pytest -m live tests/live/test_charts_a.py --basetemp=.blueprint/audit-20261019-resumed/test_charts_a -q` PASS (3 passed, 128.93s); primary recipe 8/8 ok. Saved report screenshot inspected: all five chart types render data.
- Task 3.1: `uv run pytest -m live tests/live/test_golden.py --basetemp=.blueprint/audit-20261019-resumed/test_golden -q` PASS (2 passed, 93.23s). Normal run: 10/10 ok, elapsed 40.797s, median op 3.210s. Timeout recovery: elapsed 36.468s, expected failed status/error_code timeout, saved link reopened. Saved golden screenshot inspected: background behind all charts.
- Task 4.1: `uv run pytest -m live tests/live/test_charts_b.py --basetemp=.blueprint/audit-20261019-resumed/test_charts_b -q` PASS (2 passed, 102.83s); saved report and date-filter screenshots inspected. The date control filters October 12–18; the incompatible geo dimension fails clearly as the task permits. Successful geo rendering remains unverified.
- Task 4.2: `uv run pytest -m live tests/live/test_misc_ops.py --basetemp=.blueprint/audit-20261019-resumed/test_misc_ops -q` PASS (1 passed, 72.60s); 20/20 ops ok, summed op time 60.287s, median 2.265s. All three saved-page screenshots inspected, including formatted text, images, chart colors and blank-line preservation.
- Task 4.3: screencast unit checks pass in the suites above. Fresh `uv run dsengine run .blueprint/audit-20261019-resumed/screencast/recipe.jsonl --screencast` PASS (exit 0, 4/4 ops ok, stderr empty). Independently validated all 39 output events against the contract schema; 29 frames decode as JPEG and appear between op events.
- Review findings: P1 executor.py:124-136 checks sign-in without starting a closed Chrome (5.1, S); P2 executor.py:32,42-43 uses unsupported timeout arguments on keyboard/mouse reset, with swallowed TypeErrors (5.2, S); P2 report.py:205-218 uploads backgrounds on every attempt and uses page-wide image locators, causing duplicate/multiple-match failures (5.3, M). Follow-up reviewer confirmed repair coverage, adding the registry regression. 5.4 (M) verifies all live behavior after those fixes. Background aspect-ratio behavior is an unproven risk covered by the new square-box regression, not an additional confirmed defect.
- Release checklist: setup/demo steps are documented in AGENTS.md; fresh saved reports, controls, images, styles and pages work end to end within budget. Known limitations are in PRD.md Later. Reviewer found no tracked engine secrets, unverified direct dependencies or implemented non-goals; all installed direct runtime/dev packages are in the dated Dependencies table. This CLI has no owned product UI requiring viewport/accessibility review. Release remains unaccepted because of the three code defects.
- Decisions: preserve strict render assertions and all failed attempts; do not weaken checks because op events are ok. The recorded task 2.1 timeout-event policy is an interpretation to settle at the program root; contracts are unchanged. No sibling project files or secrets were changed. Live reports created by this audit are retained as evidence.
- Evidence: `.blueprint/audit-20261019-resumed/` contains per-suite logs/evidence/screenshots, the first failed spike, the clean spike result and screencast summary. Earlier failing configuration runs remain in `.blueprint/audit-20261019/` and `.blueprint/audit-20261019-newaccount/`.
- Left open: implementation of tasks 5.1–5.4; compatible-source geo proof and full report-building expansion are deferred in PRD.md. No new STOP or UNVERIFIED dependency before the first repair task.
- Next: new engine build session for task 5.1 with blueprint-solution-builder; after Phase 5, return to the architect for a final re-audit. Program integration audit belongs at the program root after this part is ACCEPTED.

## 2026-10-19: Task 5.1 Start the dedicated Chrome session before checking sign-in
- Status: done
- Plan check: off
- What changed: executor.py calls ensure_browser before the sign-in check. test_executor.py covers cold startup, owned-browser reuse, unsigned-in exit 3, startup/ownership errors and browser-free early returns.
- Checks: `uv run pytest tests/test_executor.py tests/test_linking.py` PASS (48 passed, 1.06s); Test (all) `uv run pytest` PASS (94 passed, 9 live deselected, 5.51s); `git diff --check -- .` PASS. Read-only blueprint_reviewer: no findings. Live acceptance remains task 5.4.
- Decisions: reuse the existing ownership-validated startup helper; keep the check command read-only. No changes needed in chrome.py or test_linking.py. Startup regressions exercise the real ensure_browser helper with fake process/CDP boundaries. No dependency or AGENTS.md changes.
- Tried and failed: before the production fix, the new regression suite failed as expected (7 failed, 41 passed): startup was skipped before sign-in checking. Adding the startup call resolved all failures.
- Gotchas: none.
- Left open: none for this task.
- Next: task 5.2 Make retry cleanup call the supported Playwright APIs; start with strict keyboard/mouse fakes and the existing operation/run budget.

## 2026-10-19: Task 5.2 Make retry cleanup call the supported Playwright APIs
- Status: done
- Plan check: off
- What changed: executor.py uses supported Escape/mouse calls and bounds canvas lookup by the remaining budget. test_executor.py exercises real cleanup with strict input fakes, retry ordering, unavailable page/canvas and deadline cases.
- Checks: `uv run pytest tests/test_executor.py` PASS (36 passed, 0.66s); Test (all) `uv run pytest` PASS (109 passed, 9 live deselected, 5.06s); `git diff --check -- .` PASS. Read-only blueprint_reviewer: no findings.
- Decisions: check remaining time before input because keyboard/mouse APIs have no timeout parameter; give bounding_box the remaining timeout and skip deselection after exhaustion. Preserve existing deadlines and finalizer bypass. No dependency or AGENTS.md changes. Live acceptance remains task 5.4.
- Tried and failed: before the production fix, strict cleanup regressions exposed the unsupported calls and unbounded lookup (14 failed, 22 passed); the fix resolved all failures.
- Gotchas: none.
- Left open: none.
- Next: task 5.3 Scope and reuse background images across retries; start with retained image ownership and the live report-op regressions.

## 2026-10-19: Task 5.3 Scope and reuse background images across retries
- Status: done
- Plan check: off
- What changed: retained/scoped backgrounds and pending uploads; refreshed page-local registry indices after reordering; shared image ratio handling; added regressions and editor guidance.
- Checks: `uv run pytest tests/test_executor.py` PASS (44); `uv run pytest -m live tests/live/test_report_ops.py` PASS (2, 56.45s); `uv run pytest` PASS (117, 10 deselected, 5.90s); `git diff --check -- .` PASS. Final reviewer: no findings. Inspected `C:/Users/gjand/AppData/Local/Temp/pytest-of-gjand/pytest-448/test_backgrounds_reuse_upload_0/backgrounds_saved.png`: reopened images loaded, correct order, �4 px boxes, isolated style change. Median op 2.281s; nine ops 26.527s.
- Decisions: retain upload intent before set_files and element identity before loading; reindex only owning-page entries. Resize before moving to keep edge handles accessible. AGENTS.md records mixed cache types. No dependencies added.
- Tried and failed: cached field list broke registry iteration; filtered dictionaries. Edge placement hid resize handles; reversed resize/move. Text fixture snapped 5 px; moved away from guide. User restored interrupted sign-in manually.
- Gotchas: none beyond recorded guidance.
- Left open: none.
- Next: task 5.4 Recheck live acceptance after audit fixes; run original live gates and screencast/budget checks.

## 2026-10-19: Task 5.4 Recheck live acceptance after audit fixes
- Status: partial.
- Plan check: off
- What changed: screencast/20-op acceptance checks; image-selection knowledge.
- Checks: evidence/logs under `.blueprint/check54/`:
  - `uv run dsengine check`: true/true.
  - `uv run python spikes/spike_one_chart.py`: PASS; `spike/` screenshots inspected, zero-pixel errors.
  - `uv run pytest`: PASS 117,11 deselected,5.15s (`offline.log`).
  - `uv run pytest -m live tests/live/test_report_ops.py tests/live/test_charts_a.py tests/live/test_golden.py tests/live/test_charts_b.py tests/live/test_misc_ops.py --basetemp=.blueprint/check54/live -x`: FAIL screenshot timeout; repeated with `--basetemp=.blueprint/check54/live-rerun`: report2/chartsA3 PASS, golden8/10 FAIL,33s/median2.820s.
  - `uv run pytest -m live tests/live/test_golden.py tests/live/test_charts_b.py tests/live/test_misc_ops.py --basetemp=.blueprint/check54/remaining -x`: golden8/10 FAIL,32.437s/median2.648s.
  - `uv run pytest -m live tests/live/test_golden.py -k 'timeout or screencast' tests/live/test_charts_b.py tests/live/test_misc_ops.py --basetemp=.blueprint/check54/independent`: timeout PASS; screencast98 JPEG/120 valid events, saved-render FAIL.
  - `uv run pytest -m live tests/live/test_charts_b.py tests/live/test_misc_ops.py --basetemp=.blueprint/check54/other`: chartsB2 PASS/screenshots inspected; misc17/20 FAIL,63.609s.
  - `uv run pytest -m live tests/live/test_misc_ops.py --basetemp=.blueprint/check54/misc-rerun`: repeated17/20 FAIL,64.015s/median1.867s.
- Decisions: retained assertions; reviewer: no test-diff findings. Prerequisites: signed-in dedicated Chrome, copyable template, billing-enabled project/BigQuery access; source queried successfully.
- Tried and failed: unchanged reruns.
- Gotchas: none.
- Left open: P1 image selection clears uncached fields; repeated misc s007 text timeout, consequential s015, s016 title-size failure.
- Next: approve product-repair scope (report.py; investigate text.py/style.py), fix regressions, rerun acceptance.

## 2026-10-19: Task 5.4 Recheck live acceptance after audit fixes (repair diagnostics)
- Status: partial; final gates running.
- Plan check: off
- What changed: report.py captures source fields at readiness; style.py polls exact title-size readback; tests/test_executor.py adds both regressions.
- Checks: logs/evidence under `.blueprint/check54fix/`.
  - `uv run pytest tests/test_executor.py -k retains_fields`, `uv run pytest tests/test_executor.py -k title_font_selection`, `uv run pytest tests/test_executor.py -k title_font_verification`: each FAIL before its repair.
  - `uv run pytest tests/test_executor.py`: PASS45, then46 (latest0.69s; `executor-final.log`).
  - `uv run pytest -m live tests/live/test_golden.py --basetemp=.blueprint/check54fix/golden -x`: PASS3,187.12s; golden10/10,55.781s/median4.710s; screencast124 JPEG/146 valid events.
  - `uv run python .blueprint/check54fix/diagnose_misc.py`: first19/20 FAIL; second PASS (`misc-diagnostic-2.log`).
  - `uv run python .blueprint/check54fix/diagnose_title.py`: PASS5/5 (`title.log`).
  - `uv run pytest -m live tests/live/test_misc_ops.py --basetemp=.blueprint/check54fix/misc`: FAIL19/20; repeated with `--basetemp=.blueprint/check54fix/misc-final`: PASS20/20,60.797s/median2.242s; three saved screenshots inspected.
  - `uv run pytest`: PASS118/5.20s, then119/4.62s.
- Decisions: user approved retention repair/regression scope; announced style.py repair for the same acceptance gate. No dependencies added.
- Tried and failed: Escape alone did not wait for font-dropdown teardown; replaced with bounded exact-value polling.
- Gotchas: editor observations recorded in knowledge.
- Left open: final combined suite.
- Next: finish live/offline gates, review, record completion.

## 2026-10-19: Task 5.4 Recheck live acceptance after audit fixes
- Status: done
- Plan check: off
- What changed: source-field retention, bounded exact font readback, regressions, live screencast/20-op acceptance, and saved-image readiness.
- Checks: evidence under `.blueprint/check54fix/`.
  - `uv run python spikes/spike_one_chart.py`: PASS; `spike.log`, `spike/evidence.json`, `spike/saved_view.png` inspected.
  - `uv run pytest -m live tests/live/test_report_ops.py tests/live/test_charts_a.py tests/live/test_golden.py tests/live/test_charts_b.py tests/live/test_misc_ops.py --basetemp=.blueprint/check54fix/all`: FAIL2/11 (`all.log`), immediate image-width reads.
  - Same command with `--basetemp=.blueprint/check54fix/final -v`: PASS11/448.76s (`final.log`). Golden10/10:38.016s/median3.0145s; 20-op20/20:45.578s/median1.562s. Screencast107 JPEG frames/129 schema-valid events between ops.
  - `uv run pytest`: PASS119,11 deselected,4.72s (`offline-complete.log`).
  - `git diff --check -- .`: PASS.
- Evidence inspected: `all/test_backgrounds_reuse_upload_0/backgrounds_saved.png`, `all/test_five_chart_types_save_a_v0/saved_report.png`, `all/test_remaining_chart_types_and0/{saved_report,date_filtered}.png`, `final/test_golden_recipe_budget_0/saved_report.png`, `final/test_misc_ops0/page{1,2,3}.png`.
- Decisions: retain exact assertions; wait up to20s for saved image width1200. Permitted incompatible-geo failure retained. Prerequisites: signed-in dedicated Chrome, copyable template, billing-enabled GCP project with BigQuery access; existing public source queries succeed.
- Tried and failed: first combined run raced saved-image loading; condition wait fixed it.
- Gotchas: none beyond recorded knowledge.
- Left open: none. Final reviewer: no findings.
- Next: engine final audit/retro with blueprint-solution-architect in a new chat.

## 2026-10-20: Change conventions 1.2 (program)
- What changed: contracts/conventions.md 1.1 -> 1.2 renames the Cloud Run service `dss` -> `dss-frontend` (keeps the submitted URL); this part's essentials Contracts row now says 1.2. Nothing this part reads or provides changed; no task affected.

## 2026-10-20: Audit (final)
- Verdict: ACCEPTED. Final re-audit after tasks 5.1–5.4; no P0/P1 blockers. All 13 tasks remain done; no new build tasks. No product code changed in this session.
- What changed: folded Phase 5 startup, retry-budget, background identity/reindexing, source-field retention and exact font-readback decisions into docs/architecture.md and architecture-essentials.md. Moved the mixed-state registry convention from AGENTS.md into those docs. Aligned the PRD deadline with the supplied current program guide (2026-10-23 01:05 MPST). Stamped the essentials.
- Scope: reviewed the four repair tasks and their effects on earlier work. Because executor/browser, report/image/style and shared selector files touch every original gate, reran all original acceptance families; no task acceptance gate was skipped. The prior spike approach approval remains in force; no new design STOP.
- Test (all): `uv run pytest` PASS (119 passed, 11 live deselected, 5.00s). Covers task 1.1 CLI/schema/invalid-donut checks and all offline regressions.
- Tasks 1.2, 2.1, 4.3 and 5.1–5.3 offline checks: `uv run pytest tests/test_executor.py tests/test_linking.py tests/test_contract.py tests/test_screencast.py` PASS (83 passed, 3.48s), including ownership/startup, supported retry input signatures, background reuse and event conformance. `uv run dsengine print ../contracts/fixtures/recipe.sample.jsonl` produced 14 lines.
- Tasks 1.2–1.3 live: initial `uv run dsengine check` returned false/false with Chrome stopped. `uv run python spikes/spike_one_chart.py` PASS (exit 0; summed step time 39.015s). It started the owned browser, found the persisted sign-in, saved/reopened the report, and read both boxes with zero-pixel error. Subsequent `uv run dsengine check` returned true/true. Inspected `spike/saved_view.png`; chart data rendered and background was behind it. No sign-in automation or unrelated-tab interaction.
- Tasks 2.1–4.3 and 5.3–5.4 live: `uv run pytest -m live tests/live/test_report_ops.py tests/live/test_charts_a.py tests/live/test_golden.py tests/live/test_charts_b.py tests/live/test_misc_ops.py --basetemp=.blueprint/audit-20261020/live -v` PASS (11 passed, 458.00s). Includes original five report ops, background retry/identity/aspect-ratio regression, three chart-A checks, three golden checks, two chart-B/control checks and the 20-op misc flow. Full log: `.blueprint/audit-20261020/live.log`.
- Budgets: golden 10/10 ok, elapsed 39.609s, median op 3.164s; timeout recovery returned the saved link with expected timeout/failed result in 36.750s. Screencast 10/10 ok in 60.875s, median 5.719s, 102 decoded JPEG frames between op events and 124 schema-valid events. Misc 20/20 ok in 45.344s, median 1.546s (summed op time 43.585s), below 300s.
- Fresh visual evidence inspected under `.blueprint/audit-20261020/`: spike saved view; `live/test_backgrounds_reuse_upload_0/backgrounds_saved.png`; chart-A saved report; golden budget saved report; chart-B saved report/date-filtered view (October 13–19); misc pages 1–3 and `page1_rendered.png`. The permitted incompatible-geo error is the only accepted error panel. Geometry, square background placement, paint order, isolated styling, text formatting, page navigation and images passed their assertions.
- Extra visual check: misc page1.png captured a not-yet-rendered chart. `uv run python .blueprint/audit-20261020/verify_misc_view.py` ultimately PASS after explicitly reopening page 1 and waiting for its bar-chart iframe data and loaded image (`misc-page1-rendered.log`, `page1_rendered.png`). Two earlier diagnostic attempts incorrectly selected the saved current page / generic text-plus-chart collection; their failed logs are retained as harness mistakes, not product acceptance failures. The final screenshot shows the saved chart rendered with the intended colors and title size.
- Review: independent read-only blueprint_reviewer reported no blockers, including on the docs-only consolidation. It checked Phase 5 Specs/Review focus, non-goals, architecture decisions, direct dependencies and engine-scoped tracked/history credential indicators; no demonstrable secrets or unverified direct dependencies found. Shared conventions 1.2 manually checked against engine env names, loopback CDP port, profile path and recipe-relative assets; contract tests above pass. No shared contract or sibling project file changed.
- POC release checklist: AGENTS.md documents install, manual first sign-in/configuration and the under-five-minute golden demo; the current saved-report core flow works. External prerequisites remain installed Chrome, the manually signed-in dedicated profile, copyable template when blank creation is unavailable, and a billing-enabled GCP project/account with BigQuery read/job access to the compatible source. No new dependency, STOP point or required user decision.
- Known limitations: retain PRD Later items (compatible-source geo proof, report-building expansion and program-root timeout-lifecycle wording clarification). Earlier transient source/template access failures and earlier Phase 5 failures remain recorded; fresh strict acceptance passed. No owned product UI requiring a separate viewport/accessibility audit.
- Decisions: preserve all acceptance assertions, failed diagnostic evidence and live reports. No additional audit-fix phase. Final blueprint lint and git diff checks passed before the docs-only final-audit commit.
- Left open: none for engine POC acceptance. Optional retrospective, local release tag or separately planned new version. Program integration audit belongs at the program root after every part's latest final audit is ACCEPTED.

## 2026-10-21: Change data-access review dialog without checkbox (from release 2.3)
- What changed: plan.md Phase 6 adds task 6.1 (S): open_report and save_report accept Data Studio's "Review data access" dialogs with or without the "I understand and accept the risk." checkbox. architecture.md Live editor conventions gains the dialog rule plus a decision-log row; essentials updated and stamped.
- Why: release 2.3 blocked. Live run b_ae7f4bdaab30 v1 failed `open_report` (timeout, `open_report_failed`); last screencast frame shows the dialog with Close and Acknowledge only, while `_dismiss_access_review` (ops/report.py:45-54) returns False when `review_accept` is not visible, so the editor never becomes ready. The save path (ops/report.py:321) requires the checkbox too.
- Ruling: user chose the engine fix over pinning a template/URL that avoids the dialog (no known one; linking.md says the dialog appears on every create).
- Tasks affected: engine 6.1 new; release 2.3 now `Needs: engine 6.1`. Engine final audit (2026-10-20) stays ACCEPTED for 1.1-5.4; 6.1 gets the builder's own review.

## 2026-10-21: Task 6.1 Accept data-access review dialogs without the risk checkbox
- Status: done
- Plan check: off
- What changed: report.py `_accept_access_review(dialog, ctx, button_key)` shared by open_report and save_report: detect dialog by exact name, tick risk checkbox only if visible, click the dialog-scoped button, wait for dialog hidden. Selectors (linking.md, editor.md, log.md), spike and 5 fake-page regressions.
- Checks: `uv run pytest tests/test_executor.py` PASS (51; the 5 new fail on HEAD code); live `uv run pytest -m live tests/live/test_golden.py -k budget` PASS (1, elapsed 53.2 s, 10/10 ok, median op 3.2 s, saved screenshot shows rendered scorecard/line/bar/donut/table); Test (all) `uv run pytest` PASS (124, 11 deselected). Variant seen live (probe in engine tab): create dialog has no checkbox, buttons Close + Acknowledge; save dialog matched exact name and saved.
- Decisions: If-branch taken: exact role names via `"..."s` for `review_dialog`, `review_acknowledge`, `review_save_dialog` (create name is a prefix of save name). Checkbox/button looked up inside the dialog. log.md edited outside Files (essentials require a log line per selector change).
- Digest: report.py `_accept_access_review(dialog, ctx, button_key)`; selectors `review_dialog` (new, exact), `review_acknowledge`/`review_save_dialog` exact, `review_accept` optional and dialog-scoped. Live golden budget 53 s.
- Tried and failed: none
- Gotchas: none
- Left open: P3 late-rendering checkbox in old variant would time out the click (retry recovers) - src/dsengine/ops/report.py; P3 exact-selector test compares strings only (live run covers syntax) - tests/test_executor.py
- Next: release 2.3 can resume on the backend/release side; no engine task left in plan.


## 2026-10-21: Audit (final)
- Verdict: DEFECTS. Re-audit of task 6.1 after ACCEPTED 2026-10-20. One P1 blocker: late-rendered risk checkboxes block create/save acknowledgement. Added task 7.1 (S), within the POC fix budget; existing markers unchanged. Fresh failures override the earlier acceptance claim.
- What changed: docs/plan.md Phase 7; architecture.md and architecture-essentials.md specify bounded control readiness and correct the claim that the checkbox was removed universally; PRD Later records the existing P3 selector-string-only regression limitation. No product code, dependency, contract or sibling-project change. Audit-only captures/probes/logs live under `.blueprint/audit-20261021/` (ignored).
- Scope: reviewer checked only task 6.1 and consequences. Shared report code/selectors affect every live recipe, so reran all original live acceptance families and spike. No automated task gate skipped. Full/focused runs cover all offline commands. Prior spike approach approval stands. Fresh saved-report/manual checks and successful golden/20-op budgets could not complete because creation failed; these are failed acceptance, not waived requirements.
- Test (all): `uv run pytest` PASS, 124 passed, 11 live deselected, 6.08 s (`offline.log`). Focused: `uv run pytest tests/test_executor.py tests/test_linking.py tests/test_contract.py tests/test_screencast.py` PASS, 88 passed, 11.19 s (`focused.log`), including 51 executor tests, all five new dialog regressions, contract conformance and screencast. `uv run dsengine print ../contracts/fixtures/recipe.sample.jsonl` produced 14 lines. Conventions 1.2 manually checked against engine env lookup, root `.env` precedence, loopback CDP 9222, profile and recipe-relative paths; no mismatch introduced.
- Spike: `uv run python spikes/spike_one_chart.py` FAIL, exit 1, save_report TimeoutError after 20.563 s (`spike.log`). Creation/chart data rendered; both boxes had zero-pixel error. Inspected screenshot: unchecked risk checkbox and disabled Acknowledge and save. Preserved `spike-save-failed.png`, `spike-evidence.json` from `spikes/screens/`.
- Task 6.1 live gate: `uv run pytest -m live tests/live/test_golden.py -k budget --basetemp=.blueprint/audit-20261021/golden -v` FAIL, 1 failed/2 deselected, 23.76 s (`golden.log`): open_report timed out at 20.032 s, no link, screenshot null.
- Repeat: `uv run dsengine run --screencast .blueprint/audit-20261021/golden/test_golden_recipe_budget_0/golden.jsonl --screens .blueprint/audit-20261021/repeat-screens` FAIL, exit 1, open_report 20.046 s, no link. Captured stdout to `repeat-cast.jsonl`; decoded/inspected last of 36 frames as `repeat-last-frame.jpg`: create dialog with unchecked checkbox/disabled acknowledgement.
- Probe: `uv run python .blueprint/audit-20261021/probe_review.py` FAIL same open_report (`probe-events.jsonl`). It wraps the unchanged production handler and observes only its owned dialog. `probe-observations.json`: before handler, exact dialog count 1, checkbox count 0, button disabled, 17.797 s left; after timeout, dialog count 1, checkbox visible/unchecked, button disabled, 0 s left. Confirms delayed controls, not exact-name mismatch. report.py:48-51 checks once; spike_one_chart.py:108-111 repeats it.
- Full live: `uv run pytest -m live tests/live/test_report_ops.py tests/live/test_charts_a.py tests/live/test_golden.py tests/live/test_charts_b.py tests/live/test_misc_ops.py --basetemp=.blueprint/audit-20261021/live -v` FAIL, 11 failed, 246.24 s (`live.log`, per-test events/diagnostics under `live/`), all blocked at report creation. Includes original report ops/background identity, chart/control variants, golden budget/timeout/screencast and 20-op misc. Screencast captured 36 frames but no successful dashboard. Short failed-run times do not prove budgets.
- Prerequisites: after the suite, `uv run dsengine check` returned `{"chrome_running": true, "signed_in": true}`. Installed Chrome, persisted manual sign-in and configured template/project/public source are available; the spike rendered data. No sign-in automation, unrelated-tab interaction or external-account repair required by this defect.
- Review: independent read-only blueprint_reviewer confirmed one P1 from live/probe evidence; no other blockers, non-goal expansion, contradictory decisions, new unverified direct dependencies or engine-scoped tracked/history credential-pattern indicators. Reviewer also checked repair docs: no findings.
- Decisions: bounded readiness polling, existing deadlines, unchanged strict acceptance. Correction to task 6.1 Left open: late checkbox is demonstrated P1, not P3; retry cannot recover after a button wait exhausts the deadline shared by both attempts (executor.py:178-185). The other P3 goes to PRD Later without a task. No new environment gotcha; readiness convention belongs in architecture, not AGENTS.md.
- Release checklist: documented install/demo commands remain; current core live flow and fresh saved-report/budget proof fail, so acceptance withheld. Retain earlier PRD Later limitations. No new STOP/unverified dependency. Historical folder-mode tasks without individual git commits were already accepted; this session commits its docs only.
- Left open: task 7.1, then final re-audit. The earlier release 2.3 resumption note is superseded by this failed engine acceptance. Program-root sessions own cross-part gate updates; integration must await engine acceptance.
- Next: fresh engine builder session for 7.1, gpt-6.1-sol at high, then re-audit. Stamp, blueprint lint and git diff checks pass before the docs-only final-audit commit.

## 2026-10-21: Task 7.1 Wait for asynchronously rendered data-access review controls
- Status: done
- Plan check: off
- What changed: report.py and spike poll scoped checkbox/button readiness before acknowledging once; knowledge notes corrected; eight fake-clock regressions cover create/save delayed checkbox, checkbox-free delayed enabling, and operation/run exhaustion. Initially present/absent variants retained.
- Checks: `uv run pytest tests/test_executor.py` PASS (59); `uv run python spikes/spike_one_chart.py` PASS; `uv run pytest -m live tests/live/test_report_ops.py tests/live/test_charts_a.py tests/live/test_golden.py tests/live/test_charts_b.py tests/live/test_misc_ops.py` PASS (11, 583.40s; evidence flag --basetemp=.blueprint/task-7.1-live); `uv run pytest` PASS (132, 11 deselected). Golden elapsed/median 62.390/5.461s; screencast 84.641/7.516s, 135 schema-valid JPEG frames; expected timeout recovery 35.83s; 20 ops 48.312s. Inspected rendered spike, charts-A and both complete golden saved screenshots. Evidence: .blueprint/task-7.1-evidence/{evidence.json,saved_view.png}; .blueprint/task-7.1-live/**/{budget.json,saved_report.png}. Spike saw delayed checkboxes at create/save polls 1/3; checkbox-free variants verified offline. Review: no findings.
- Decisions: 250ms readiness polling; deadlines/selectors unchanged. Local evidence retained outside Files; no dependency/AGENTS.md changes.
- Digest: report._accept_access_review(page, dialog, ctx, button_key) polls scoped controls within existing op/run deadlines; spike matches bounded readiness. No executor-budget or contract changes.
- Tried and failed: eight new cases failed pre-fix; corrected fake locator to resolve delayed presence dynamically.
- Gotchas: none.
- Left open: none.
- Next: final architect re-audit in a fresh engine chat.

## 2026-10-21: Audit (final)
- Verdict: ACCEPTED. Re-audit after task 7.1, following the earlier 2026-10-21 DEFECTS audit. No remaining P0/P1 blocker; all 15 tasks stay done and no build task is added.
- What changed: folded task 7.1's 250 ms readiness polling into architecture.md conventions/decision log and architecture-essentials.md; stamped the essentials. PRD Later retains intermittent insertion/verification timeouts with unresolved causes. No product code, dependency, contract or sibling-project changes.
- Scope: task 7.1 and consequences; independent review checked its Spec/Review focus. Shared report/spike/selectors affect every live recipe, so reran all original live acceptance families, spike and offline checks. No automated acceptance family skipped; earlier unchanged design reviews remain covered by ACCEPTED 2026-10-20. Prior spike approach approval stands; no new STOP.
- Evidence root: `.blueprint/audit-7.1-20261021/` (ignored). All commands below ran this session with existing account/configuration and unchanged assertions/budgets.
- Test (all): `uv run pytest` PASS, 132 passed, 11 deselected, 5.37 s (`offline.log`). `uv run pytest tests/test_executor.py tests/test_linking.py tests/test_contract.py tests/test_screencast.py` PASS, 96 passed, 4.15 s (`focused.log`), including all 59 executor tests/new delayed-control and budget regressions. `uv run dsengine print ../contracts/fixtures/recipe.sample.jsonl` produced 14 lines.
- Spike: `uv run python spikes/spike_one_chart.py` PASS, exit 0; summed steps 41.687 s (`spike.log`, `spike-evidence.json`, `spike-saved-view.png`). Create/save checkboxes first appeared at polling passes 2/3. Saved chart data rendered, background behind it, both boxes zero-pixel error, persisted manual sign-in at start/end. Checkbox-free/delayed-button variants covered offline.
- First combined live command: `uv run pytest -m live tests/live/test_report_ops.py tests/live/test_charts_a.py tests/live/test_golden.py tests/live/test_charts_b.py tests/live/test_misc_ops.py --basetemp=.blueprint/audit-7.1-20261021/live -v` FAIL, 10 passed/1 failed, 576.82 s (`live.log`). Misc s007 add_text timed out waiting for exactly one inserted component; s015 then failed because that heading was missing (18/20 ok, 65.000 s). Creation/save succeeded. Preserved events/diagnostics/s015 screenshot; s007 screenshot null after deadline exhaustion. Cause unconfirmed; no evidence tying insertion failure to the dialog repair.
- Focused repeat: `uv run pytest -m live tests/live/test_misc_ops.py --basetemp=.blueprint/audit-7.1-20261021/misc-repeat -v` PASS, 1 passed, 57.40 s (`misc-repeat.log`); 20/20 ops in 48.828 s, median 1.789 s. Reviewer inspected saved pages; page-2 heading present. Its page-1 screenshot caught chart loading, requiring the explicit saved-page check below.
- Final combined live command: same 11-test command with `--basetemp=.blueprint/audit-7.1-20261021/final -v`, PASS, 11 passed, 596.81 s (`final.log`). Covers report/background identity/retry, chart variants, golden budget/timeout/screencast, controls/date filter and 20-op misc. No product edits, assertion or deadline changes between runs.
- Final budgets: golden 10/10 ok in 63.281 s, median 6.070 s; expected failed/timeout recovery saved/returned a link in 35.281 s. Misc 20/20 ok in 57.703 s, median 1.711 s, summed op time 55.585 s; below 300 s.
- Screencast: first run 10/10 ok in 80.985 s, median 7.7495 s, 132 decoded JPEG frames/154 schema-valid events; final run 9/10 ok (partial) in 86.485 s, median 7.7575 s, 130 decoded JPEG frames/152 schema-valid events. Final s008 table add timed out at 22.172 s but all five charts rendered in the saved screenshot. Meets the existing at-least-90% criterion; retain the partial result. Frames occurred between op events in both runs.
- Visual evidence: parent/reviewer inspected spike, background-identity and chart-A reports; both golden budget/screencast saved reports; chart-B saved/date-filtered views; misc-repeat and final pages. Rendered data, boxes/paint order, isolated styling, text formatting, loaded images and navigation passed; only the explicitly permitted incompatible-geo panel remains. `uv run python .blueprint/audit-7.1-20261021/verify_misc_view.py` PASS, exit 0 (`misc-rendered.log`): opened its own saved-report tab, switched to page 1, waited for numeric chart iframe data and image naturalWidth 1200, saved `final/test_misc_ops0/page1_rendered.png`, closed its own tab. Parent and reviewer inspected the rendered chart/image. Audit-only probe reuses the earlier accepted audit's saved-page check.
- Contracts/prerequisites: recipe/event conformance passed above. Conventions 1.2 manually checked against env lookups/root .env precedence, loopback CDP 9222, dedicated profile and recipe-relative assets. Final `uv run dsengine check` returned `{"chrome_running": true, "signed_in": true}`. Prerequisites remain installed Chrome, manually signed-in dedicated profile, copyable template when blank creation is unavailable, and billing-enabled GCP project/account with read/job access to the compatible source. No sign-in automation or unrelated-tab interaction.
- Review: independent read-only blueprint_reviewer returned no findings after code/spec/docs and fresh screenshot checks. No non-goal expansion, contradictory decisions, new unverified direct dependencies or engine-scoped tracked/history credential-pattern indicators. Initial misc failure and final partial screencast remain unresolved intermittent limitations; no invented root cause or claim that passing repeats erase the failed run.
- POC release checklist: AGENTS.md documents install/manual sign-in/configuration and the under-five-minute golden demo; fresh saved-report core flow/20-op budget pass. Limitations live in PRD Later. No owned product UI requiring separate viewport/accessibility audit. No dependency, STOP, required decision or second audit-fix phase. Environment gotchas stay in AGENTS.md; no new one identified.
- Decisions: preserve strict checks and failed evidence; document observed intermittent behavior. Existing progress.md contains legacy non-UTF-8 bytes, so appended this entry without rewriting earlier entries. Final stamp/lint/diff checks pass before docs-only commit.
- Left open: none for engine POC acceptance. Optional retrospective, local release tag or separately planned new version. Cross-part gates/program integration audit belong to the program-root session.
- Next: nothing left to build in engine; continue release/integration work from the program root.

## 2026-10-21: Change live chart fields on a compiled recipe (program)
- What changed: task 8.1 (M) added in Phase 8; the final audit's ACCEPTED verdict covers tasks to 7.1 only.
- Why: release 2.3 live run b_31ee6bedd325 ended `partial` (ok 19, failed 25): add_chart scorecard after a date control, time_series, bar, pie, table and every dropdown add_control timed out with the default Record Count inserted and the Setup panel not shown; s006_failed.png shows the editor drawn in the top-left quarter of a 3840 x 2400 capture. Evidence: ../data/builds/b_31ee6bedd325/v1/ (recipe.jsonl, events.jsonl, screens/).
- Ruling: user chose an engine fix (release never edits parts). No contract change: recipe 1.0 stays the interface.
- Tasks affected: 8.1 only; release 2.3 waits on it.

## 2026-10-21: Task 8.1 Chart and control fields on a real compiled recipe
- Status: done
- Plan check: off
- What changed: report.py `_check_layout` fails open_report unless innerWidth/innerHeight are 1920 x 1200; charts.py `_inherent_sort` accepts only date-asc time_series sort (no UI); editor.md `field_picker` keyed on `ng2-selector-dialog`, canvas Auto/Custom exact; new live test_recipe_replay.py + recipe; 5 offline regressions.
- Checks: diagnosis `dsengine run --screencast` on b_31ee6bedd325 (frame .blueprint/8.1/s005_frame.jpg: editor at 3840 x 2400 CSS px, picker without "Chart fields"). Measured 3840x2400 DPR 0.5 (50% zoom), 2400x1500 DPR 0.8 after Ctrl+0, 1920x1200 DPR 1 after Settings 100%. Release replay after fix: run_finished ok, 44 ok, failed 0. test_recipe_replay: pre-fix FAIL (s006), after PASS. Live recipe_replay+charts_a+charts_b+golden: 8 passed, 1 failed (charts_a saved-table render timeout, all ops ok); charts_a rerun PASS. `uv run pytest` PASS 141 passed, 12 deselected.
- Decisions: four causes. Zoom: CDP cannot reset Chrome page zoom, so detect and fail with the measured size (Ctrl+0 + Settings > Appearance hint). Time series has no Sort section: date-asc sort is inherent; other time_series sorts fail before insertion. "Chart fields" is only a used-fields group; key the picker on its component. `text=Custom` matched page tooltip "Customer Segment Analysis". AGENTS.md gained a zoom gotcha.
- Digest: open_report fails "editor laid out at W x H CSS px ..." unless 1920x1200 (report._check_layout). time_series sort must be {date_dimension, asc} (charts._inherent_sort), else rejected pre-insert. field_picker = .cdk-overlay-pane:has(ng2-selector-dialog).
- Tried and failed: none beyond the diagnosis iterations above.
- Gotchas: set_style `colors` logs "unsupported style key colors" for scorecard/time series/bar/pie/table on the release recipe (outside Files). charts_a saved-table render can exceed 20 s once.
- Left open: P3 picker regression asserts the selector string only - tests/test_executor.py; P3 zoom detected not corrected, and open_report retries the deterministic failure - src/dsengine/ops/report.py; P3 canvas size selectors still page-wide (page named exactly "Custom"/"Auto") - knowledge/datastudio-ui/editor.md.
- Next: release 2.3 live run from the program root; engine has no task left.

## 2026-10-21: Change tall canvas placement (program)
- What changed: task 9.1 (M) added in Phase 9; architecture.md Live editor conventions gained the tall-canvas rule and a decision-log row; essentials line added; stamp rerun.
- Why: release 2.3 live run b_b2ac19ea6696 ended `partial` (ok 36, failed 3), all on page 3 (canvas 1200 x 1492): s025 set_background_image timed out (image at natural size mid-canvas, Arrange menu left open), s034 table at y884 drawn ~400 px wide, s036 bar at y1204 timed out. Isolated replay ../data/builds/b_b2ac19ea6696/v1/replay_p3.jsonl reproduces all three.
- Ruling: user chose the engine fix over capping page height in the backend or accepting partial. No contract change: recipe 1.0 stays the interface.
- Tasks affected: 9.1 only; release 2.3 waits on it.
