# Backend final re-audit — staged workflow

Date: 2026-10-21 (Asia/Manila). Verdict: **DEFECTS** — one demonstrated P1.
The 27-component reproduction is blocked despite passing layout and Blueprint validation.
One repair task, 16.1 (M), is ready; no product fix was implemented in this audit.

This re-audits tasks 14.1–14.2 and 15.1–15.11 after the ACCEPTED final audit in
`docs/audit-reaudit-2026-10-20.md`, plus earlier tasks whose Files those changes touched.
It covers this backend POC, not whole-program integration or actual Data Studio report creation.
No product code, tests, dependencies, contracts or other parts were changed by this audit.

## Blocker and repair plan

**P1: the old 24-component ceiling rejects valid staged multi-page dashboards.**
`src/dss/spec/requirements.py:1118` unconditionally counts every page's components and blocks
totals above 24. The new workflow permits 24 selected questions, 1–3 rows per question, at most
12 rows per page and 1–5 pages. The old performance oracle's 24-component workload is not an
application capacity limit.

A fresh deterministic probe created nine selected questions with three revenue scorecards each,
laid out across three pages of nine components. Context/schema/Blueprint feasibility was ready
before layout; auto_layout and the complete spec validator returned zero errors. Evaluating the
candidate spec then returned blocked with only `More than 24 components; reduce the request
scope`. Candidate publication re-evaluates at `src/dss/harness/nodes/render.py:55` and rolls back
on this issue. Recipe/run share the same evaluator. A permitted dashboard cannot reach prototype.

Evidence: `.blueprint/qa/final-reaudit-2026-10-21/probe_scope.py` and `scope-probe.json`.
This probe used code, artifact models and real Chromium text fitting, with no model, SQL write,
injected application ledger or user runtime mutation.

Recommended repair: **16.1 Align feasibility with the staged multi-page component scope (M)**.
One build session and a final re-audit. The task targets the shared evaluator, proves the 27- and
60-component cases, tests API publication/recipe/fake-engine completion, retains negative gates
and rollback, and preserves existing timing/model budgets. One task fits the POC audit-fix budget.
The independent reviewer found no issue in this repair plan. No other P0/P1 found in its scoped
code review or documentation reconciliation.

## Evidence

- `uv run pytest`: **PASS**, 1,376 passed, 12 live deselected, two upstream warnings,
  773.53 seconds. This is the parent's current run, before focused commands.
- Focused feasibility/API command initially failed only its existing definition-recompute
  timing assertion: best of three **105.47 ms** against **100 ms** (other trials 1,077.23 and
  122.04 ms); 177 tests passed. The full suite passed this check. No overlapping test run was
  launched. An unchanged isolated rerun **PASS** (one test, 0.62 s); later serial feasibility
  commands also passed. The initial failed log is retained as focused-23.log.
- The focused synthetic-label/render command initially failed only the screenshot helper's
  20-second `Page.set_content(wait_until='load')` deadline; 58 tests passed. The same capture
  passed in the full suite and earlier/later focused commands. An unchanged isolated rerun
  **PASS** (one test, 2.29 s). Cause remains unconfirmed; the initial failure is focused-30.log.
- Focused ledger: **42/44 initially PASS**, two initial failures above, both passing isolated
  reruns. All checks ran serially; no product/test change was made between attempts. Live
  verification: **12/12 PASS on the first run**, 1,376 deselected, two upstream warnings,
  528.17 s. Both configured models were available. No live generation rerun was needed.
- Isolated documented uvicorn startup, without reload: health **200**, `status:ok`, **4.12 s**.
  State and logs live in this audit's QA folder; only its owned process tree was stopped.
- Parent and independent reviewer inspected all three fresh 1200px fixture prototypes; reviewer
  also inspected all three backgrounds. No clipping/overlap; each heading matches its page and
  every background excludes components. Captures: `.blueprint/qa/task-15.9/`, 19:48 local.
- Fresh real sample flow **PASS** through context, ratio KPI alternative, Outline Other,
  per-section Design, Blueprint, three-page prototype (22 components), both targeted color
  comments, schema-valid recipe and the configured engine dry-run: **49 skipped, zero failed**,
  stage done. Parent viewed all original/revised page PNGs and the compiled page-1 background;
  independent reviewer inspected all nine original/revised/background captures, with no visual
  P0/P1. Only the targeted trend and page-1 band changed; all other items remained unchanged.
  Evidence: `.blueprint/qa/task-15.11/sample/20261021-203348-f9d74811/`.
- Fresh two-source GPS flow **PASS**, with union SQL resolving both schemas plus dataset_name
  on BigQuery. Evidence: `.blueprint/qa/task-15.11/gps/20261021-203755-9fdc6771/`.
  Live request bounds and stage timings are saved in those runs.json/report.txt files.
- Remaining live Context/Outline and near-boundary request calibration, synthetic typed loads,
  screenshot-derived proposal/generation/intake and real Chromium render checks **PASS**.
  These synthetic live checks prove generation/intake, not a separate full synthetic prototype
  flow; the complete staged prototype/build evidence above uses the uploaded sample CSV.
- Profile CLI **PASS**, 2,000 rows/10 columns in **6.31 s**, below 10 s. The table expanded the
  backend-owned CSV with deterministic extra numeric columns; it was deleted after the check.
  All six approved preset sheets were regenerated in this audit's QA folder and parent-viewed
  as a gallery; prior user approval from task 15.5 remains in force. Configured engine
  `validate` on the fresh 49-operation sample recipe **PASS**, exit 0.
- `blueprint.py deps`: all 17 rows **FOUND**. Direct declared dependencies match the dated
  essentials table, including the build backend; no dependency or lockfile changed.
- Reviewer backend-scoped tracked/history credential-name and credential-pattern scans found
  no matches; no values printed. This is scoped scan evidence, not a program security audit.
  No built Non-goal found; candidate ownership, artifact rollback and staged execution gates checked.

## Scope and reconciliation

- The scope calculation selects 50 completed tasks: the 13 changes since the prior audit and
  earlier tasks sharing their Files. Distinct focused commands run serially, with logs and a
  machine-readable ledger under `.blueprint/qa/final-reaudit-2026-10-21/`.
- Individual earlier-task commands skipped: 2.1, 5.3, 7.2, 9.5, 9.7, 12.1, 13.2. Their Files
  are untouched by this change set; their offline tests still run in Test (all). The prior audit
  retains their separate/manual evidence.
- Task 15.1 deliberately deleted interview/plan/spec model paths and their tests. Old commands
  naming test_interview.py, test_plan.py or test_spec_node.py are superseded; the remaining
  files run, with original/effective commands retained in scope.json. Old live backend_flow
  interview/plan tests are superseded by test_staged_flow.py, not silently treated as passes.
- Old expectations of interview/plan stages, model-written whole specs, a one-page-only
  validator and one background file are superseded by tasks 15.1, 15.8 and 15.9. Current updated
  tests verify their replacements; they do not prove the removed features still exist.
- Earlier manual smokes for optional consolidation, judge and research schemas and the agent
  CLI are not repeated. Main staged behavior and affected offline suites are checked now.
- Durable decisions from tasks 15.x are folded into architecture.md and the compact essentials;
  redundant conventions and obsolete interview gotchas leave AGENTS.md. Architecture and
  essentials are stamped together. No existing task marker was changed.
- User-approved task 15.11 Other behavior is explicitly recorded in architecture/PRD Later:
  empty extraction creates no blocking record, tagged records skip needs_clarification and
  publication coverage. This can omit requested behavior, contrary to dashboard-intent.md's
  full preservation guarantee. It remains an accepted POC limitation under that explicit
  approval; the program-root architect must reconcile the read-only contract before claiming
  full conformance. The passing conformance tests alone do not prove that guarantee.
- Other task Left open items are retained in PRD Later: image rows without an asset path,
  conservative/duplicated title geometry, control coverage, stale background files, narrow
  removal/replan/partial-binding handling, consolidation truncation, incomplete live usage
  assertions and count/ratio presentation. Existing approved P2/P3 deferrals remain in place.

## POC release checklist

- Configured backend startup under five minutes: **PASS** (4.12 s); a clean-checkout install is
  not claimed. AGENTS.md contains install/run commands and required external setup is documented.
- Current staged core flow with real Gemini/BigQuery and configured engine dry-run: **PASS**
  for the fresh three-page/22-component sample; the larger permitted scope remains defective.
- Fresh multi-page fixture and live visuals: **PASS**.
- Known limitations: recorded. Valid multi-page capacity: **FAIL**, the P1 above.
- Program integration, hosted deployment and actual report creation remain the root part's gate.

## Current task check ledger

Mechanical checks: architecture/essentials stamp **PASS**; blueprint lint **0 errors, 4 historical
warnings** (cumulative plan size and long Specs for 11.3/11.4/12.2); scoped diff whitespace
check **PASS**. The compact essentials and AGENTS.md are now below their size limits.
All product/test/dependency paths still match backend source commit `64d4da9`.
Status: **57/58 done**, task **16.1 (M)** ready. Build it, re-audit this part, then resume
release integration at the program root after backend acceptance.

All paths in the Log column are relative to `.blueprint/qa/final-reaudit-2026-10-21/`.
The full suite passed before these focused commands. Original commands that name intentionally
deleted tests are recorded with their effective replacements in scope.json (see Scope).
Overlapping live selections ran once in the complete 12-test live selection, including all six
staged checks, model availability, references, typed/screenshot synthetic intake and two render
checks. No additional live generation rerun was needed.

| Tasks | Command | Result | Log |
|---|---|---|---|
| 1.1 | `uv run pytest tests/test_skeleton.py` | PASS: 7 passed, 1 warning in 1.74s | focused-01.log |
| 1.2 | `uv run pytest tests/test_intake.py` | PASS: 23 passed, 1 warning in 6.24s | focused-02.log |
| 1.3 | `uv run pytest tests/test_thin_slice.py` | PASS: 10 passed, 1 warning in 15.92s | focused-03.log |
| 3.2 | `uv run pytest tests/test_view_sql.py` | PASS: 34 passed, 1 warning in 0.18s | focused-04.log |
| 3.3 | `uv run pytest tests/test_spec_validate.py tests/test_layout.py` | PASS: 171 passed, 1 warning in 38.91s | focused-05.log |
| 4.1 | `uv run pytest tests/test_render.py` | PASS: 37 passed, 2 deselected, 1 warning in 55.97s | focused-06.log |
| 4.2 | `uv run pytest tests/test_revise.py` | PASS: 71 passed, 1 warning in 61.81s (0:01:01) | focused-07.log |
| 4.3, contract | `uv run pytest tests/test_recipe_contract.py` | PASS: 46 passed, 1 warning in 9.82s | focused-08.log |
| 4.4 | `uv run pytest tests/test_execute.py tests/test_api_contract.py` | PASS: 57 passed, 1 warning in 48.13s | focused-09.log |
| 5.1 | `uv run pytest tests/test_cloud_mode.py` | PASS: 22 passed, 1 warning in 6.14s | focused-10.log |
| 5.2 | `uv run pytest tests/test_agent_server.py` | PASS: 53 passed, 1 warning in 40.64s | focused-11.log |
| 6.1 | `uv run pytest tests/test_episodic.py tests/test_context.py` | PASS: 45 passed, 1 warning in 7.01s | focused-12.log |
| 6.2 | `uv run pytest tests/test_consolidation.py` | PASS: 13 passed, 1 warning in 14.70s | focused-13.log |
| 7.1 | `uv run pytest tests/test_audit_style.py` | PASS: 17 passed, 1 warning in 11.48s | focused-14.log |
| 7.3 | `uv run pytest tests/test_research.py` | PASS: 28 passed, 1 warning in 10.96s | focused-15.log |
| 9.2 | `uv run pytest tests/test_recipe_contract.py tests/test_api_contract.py` | PASS: 93 passed, 1 warning in 44.93s | focused-16.log |
| 9.3 | `uv run pytest tests/test_execute.py tests/test_agent_server.py tests/test_revise.py` | PASS: 134 passed, 1 warning in 101.38s (0:01:41) | focused-17.log |
| 9.4 | `uv run pytest tests/test_spec_validate.py tests/test_render.py tests/test_recipe_contract.py` | PASS: 252 passed, 2 deselected, 1 warning in 70.91s (0:01:10) | focused-18.log |
| 9.6 | `uv run pytest tests/test_context.py tests/test_revise.py tests/test_audit_style.py tests/test_consolidation.py tests/test_eval.py tests/test_research.py` | PASS: 162 passed, 1 warning in 62.77s (0:01:02) | focused-19.log |
| 10.1 | `uv run pytest tests/test_usage_events.py` | PASS: 5 passed, 1 warning in 2.81s | focused-20.log |
| 11.1 | `uv run pytest tests/test_capabilities.py` | PASS: 33 passed, 1 warning in 0.16s | focused-21.log |
| 11.2 | `uv run pytest tests/test_references.py tests/test_api_contract.py` | PASS: 85 passed, 1 warning in 26.39s | focused-22.log |
| 11.3, 11.4, 11.8, 14.1 | `uv run pytest tests/test_feasibility.py tests/test_api_contract.py` | INITIAL FAIL: 1 failed, 177 passed, 1 warning in 107.01s (0:01:47); unchanged isolated rerun PASS | focused-23.log |
| 11.5 | `uv run pytest tests/test_publication.py tests/test_view_sql.py tests/test_render.py` | PASS: 110 passed, 2 deselected, 1 warning in 90.78s (0:01:30) | focused-24.log |
| 11.6 | `uv run pytest tests/test_feasibility.py` | PASS: 131 passed, 1 warning in 62.74s (0:01:02) | focused-25.log |
| 11.7 | `uv run pytest tests/test_feasibility.py tests/test_revise.py` | PASS: 202 passed, 1 warning in 139.78s (0:02:19) | focused-26.log |
| 11.9 | `uv run pytest tests/test_llm_retry.py` | PASS: 17 passed, 2 warnings in 26.98s | focused-27.log |
| 12.2, 12.3 | `uv run pytest tests/test_synthetic_api.py tests/test_api_contract.py` | PASS: 69 passed, 1 warning in 51.22s | focused-28.log |
| 12.4 | `uv run pytest tests/test_synthetic_recovery.py` | PASS: 21 passed, 1 warning in 14.79s | focused-29.log |
| 12.5 | `uv run pytest tests/test_synthetic_label.py tests/test_render.py` | INITIAL FAIL: 1 failed, 58 passed, 2 deselected, 1 warning in 75.22s (0:01:15); unchanged isolated rerun PASS | focused-30.log |
| 13.1 | `uv run pytest tests/test_spec_validate.py tests/test_recipe_contract.py tests/test_api_contract.py` | PASS: 262 passed, 1 warning in 77.93s (0:01:17) | focused-31.log |
| 13.3 | `uv run pytest tests/test_render.py tests/test_spec_validate.py tests/test_synthetic_label.py` | PASS: 228 passed, 2 deselected, 1 warning in 83.83s (0:01:23) | focused-32.log |
| 14.2 | `uv run pytest tests/test_feasibility.py tests/test_revise.py tests/test_api_contract.py` | PASS: 249 passed, 1 warning in 160.82s (0:02:40) | focused-33.log |
| 15.2 | `uv run pytest tests/test_artifacts.py tests/test_profile.py tests/test_intake.py` | PASS: 40 passed, 1 warning in 7.74s | focused-34.log |
| 15.3 | `uv run pytest tests/test_context_node.py tests/test_api_contract.py` | PASS: 77 passed, 1 warning in 40.14s | focused-35.log |
| 15.4 | `uv run pytest tests/test_outline.py tests/test_api_contract.py` | PASS: 68 passed, 1 warning in 84.66s (0:01:24) | focused-36.log |
| 15.5 | `uv run pytest tests/test_design.py tests/test_api_contract.py` | PASS: 82 passed, 1 warning in 52.61s | focused-37.log |
| 15.6 | `uv run pytest tests/test_blueprint.py tests/test_view_sql.py` | PASS: 64 passed, 1 warning in 65.36s (0:01:05) | focused-38.log |
| 15.7 | `uv run pytest tests/test_blueprint.py tests/test_feasibility.py tests/test_api_contract.py` | PASS: 208 passed, 1 warning in 143.62s (0:02:23) | focused-39.log |
| 15.8 | `uv run pytest tests/test_layout_auto.py tests/test_spec_validate.py` | PASS: 173 passed, 1 warning in 60.28s (0:01:00) | focused-40.log |
| 15.9 | `uv run pytest tests/test_render.py tests/test_compiler.py tests/test_revise.py` | PASS: 111 passed, 2 deselected, 1 warning in 83.49s (0:01:23) | focused-41.log |
| 15.10, contract | `uv run pytest tests/test_api_contract.py` | PASS: 47 passed, 1 warning in 29.69s | focused-42.log |
| contract | `uv run pytest tests/test_api_contract.py tests/test_feasibility.py` | PASS: 178 passed, 1 warning in 90.13s (0:01:30) | focused-43.log |
| contract | `uv run pytest tests -k synthetic` | PASS: 186 passed, 1202 deselected, 1 warning in 46.18s | focused-44.log |

| Additional check | Command | Result | Log |
|---|---|---|---|
| isolated-timing | `uv run pytest tests/test_feasibility.py::test_bounded_recompute_speed_with_definitions` | PASS: 1 passed, 1 warning in 0.62s | isolated-timing.log |
| isolated-capture | `uv run pytest tests/test_render.py::test_prototype_png_per_page_saved_for_visual_check` | PASS: 1 passed, 1 warning in 2.29s | isolated-capture.log |
| live | `uv run pytest -m live -s --junitxml=./.blueprint/qa/final-reaudit-2026-10-21/live.xml` | PASS: 12 passed, 1376 deselected, 2 warnings in 528.17s (0:08:48) | live.log |
| profile-cli | `uv run python ./.blueprint/qa/final-reaudit-2026-10-21/manual_checks.py profile` | PASS: {"seconds": 6.31, "rows": 2000, "columns": 10} | profile-cli.log |
| presets | `uv run python scripts/render_presets.py --output-dir ./.blueprint/qa/final-reaudit-2026-10-21/presets` | PASS: C:\Users\gjand\Workstation\Foldrer\1-1 AI Assisted\Hackaton\backend\.blueprint\qa\final-reaudit-2026-10-21\presets\preset_sheet.png | presets.log |
| engine-validate | `<configured engine> validate ./.blueprint/qa/task-15.11/sample/20261021-203348-f9d74811/build/recipe.jsonl` | PASS: exit 0 | engine-validate.log |
