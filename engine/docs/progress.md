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
