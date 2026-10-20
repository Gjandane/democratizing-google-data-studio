# Backend final re-audit — fixes 13.1–13.3

Date: 2026-10-20 (Asia/Manila). Verdict: **ACCEPTED**, with documented P2/P3 limitations.

No remaining demonstrated P0/P1 blocker. All offline checks pass. Of 33 distinct focused
commands, 31 passed initially; reference vision and screenshot-only synthetic planning each
failed once and passed an unchanged isolated rerun. Four extra timing invocations also passed.
No new repair phase or task is added. All 44 planned tasks remain complete.

This re-audits the backend POC after the DEFECTS report in
`docs/audit-final-2026-10-20.md`, fixes 13.1–13.3, and the user-approved Phase 13
severity triage. It reviews those fixes and affected earlier behavior. It is not the
whole-program integration audit or evidence of actual Data Studio report creation.
No product source, tests, dependencies, contracts or other parts were changed here.

## Evidence and review

- Test (all), `uv run pytest`: **PASS**, 1,106 passed, 9 live deselected,
  3 upstream warnings, 387.27s. The full suite ran before focused checks.
- Fix suites 13.1/13.2/13.3: **PASS**, 260/33/208 tests. The original stalled-server
  oracle passed in **five fresh Windows processes** at the unchanged 1.5s + 0.5s ceiling,
  including closed-client and stopped-engine/descendant assertions. Controlled cleanup stalls
  also pass. Real Chromium dimensions and the 12-component render's **15s budget** pass.
- Fresh `uv run pytest -m live tests/live/test_backend_flow.py`: **PASS**, 3 passed,
  5 warnings, 384.74s, with no rerun. Real Gemini/BigQuery interview → plan → view →
  validated prototype → recipe → real configured engine dry-run reached `done`.
  All 12 recipe lines validated against recipe 1.0; 11 operations skipped, zero failed.
  GPS animation refused before view publication; image revenue ambiguity required explicit
  mapping and then reached a real prototype. No fixture spec replaced the core model output.
- Fresh isolated documented uvicorn startup, without reload: health **200**, `status:ok`,
  **4.25s**. Port 18073 avoided the existing developer server; state was isolated under QA.
  Only this audit's server process tree was stopped; root configuration was unchanged.
- Parent inspected fresh core, image-mapping and heading-fixture screenshots at 1200px width.
  A Chromium probe of the exact saved live spec found both title/subtitle boxes fit and
  their background crops had identical pixels. The fixture covers long/wrapped headings,
  explicit fonts, rounded corners and the protected synthetic footer. The saved live
  `prototype.png` is the actual API screenshot; the probe's `prototype.html` is regenerated
  decoration-only HTML from that spec, not a second live API capture.
- Independent read-only `blueprint_reviewer`: **no P0/P1 findings** in fixes or affected code;
  fresh heading/background images pass visual review. Shared geometry/styles, strict theme
  and recipe validation, Windows process ownership/cleanup and unchanged repair/deadline
  limits checked. No built Non-goal, new direct dependency or demonstrated design contradiction.
  Reviewer ran no product tests; command results here are the parent's runs.
- Reference vision smoke initially **FAIL**, invalid observations, 19.19s; one unchanged
  isolated rerun **PASS**, 1 test, 20.34s. Both results are retained. Independent reviewer
  grades this existing intermittent reliability limitation **P2**, not a new blocker: the
  one-generation/no-repair boundary safely rejects before committing reference artifacts,
  and the fresh live image-mapping path also passed. Sanitized logs do not identify the
  rejected field or distinguish malformed/truncated output; two attempts establish no
  reliability rate. Live evidence is not uniformly first-pass green.
- Synthetic live suite initially **1 PASS / 1 FAIL**, 244.05s: proposal, 1,000-row generation,
  typed BigQuery load and interview succeeded; screenshot-only planning exhausted the initial
  spec plus two repairs after heading-fit rejection and returned `invalid_request`. No clipped
  prototype was published. One unchanged isolated rerun **PASS**, 132.56s, reached a labeled
  prototype/recipe; parent inspected its title and footer. Both outcomes are retained.
  Failed trace/events were inspected before pytest removed its temp directory; the QA
  observation excerpt records the validation path, node order and error, not a database backup.
  The rejected heading's exact content/style/geometry is unavailable, so that attempt cannot
  establish whether the rejection was valid or a false negative for its particular input.
  Independent reviewer grades this **P2**, cause unconfirmed, with no demonstrated remaining
  P0/P1; the documented two-repair guardrail is preserved and first-attempt success is unproven.
- All 17 declared dependency rows **FOUND** by `blueprint.py deps`; pyproject/lock unchanged.
  Backend-scoped tracked/history metadata and credential-pattern scans found no matching
  credential files or scanned values; nothing sensitive printed. This is scoped pattern
  evidence, not a whole-program security certification.

## Scope and reconciliation

- Re-ran distinct Done-when pytest commands for 13.1–13.3 and every earlier task whose Files
  those fixes touched (including test files). Identical commands are shared in the ledger.
- Individual earlier-task commands skipped: 1.1, 1.2, 2.1, 3.1, 3.2, 4.2, 5.1, 6.2, 7.1,
  7.2, 10.1, 11.1, 11.9, 12.1, 12.4. Their Files were untouched by the fixes; their offline
  tests still ran in Test (all), and the prior audit retains their separate check evidence.
  Earlier optional model-list, research, consolidation, judge and standalone-agent manual
  smokes were not repeated; they are outside this re-audit's changed paths. The large
  synthetic-generator performance oracle is unchanged and retains the prior audit evidence.
- Contract conformance: API, recipe, dashboard-intent and synthetic-data commands are in the
  ledger. Manual conventions review covers backend port/paths, version-relative recipes,
  UTC IDs, env names and access/agent credential separation; no contract change is needed.
- Five approved P2 deferrals remain in PRD Later: preview option parity, exceptional version
  publication recovery, enormous synthetic integers, misleading readiness after a fulfillment
  refusal, and folded token-count underestimation. Execution still refuses unfulfilled work.
  No task is added for them. Architecture paragraphs now explicitly label these deferred
  improvements rather than imply they are implemented.
- New P3 polish, recorded in PRD Later: some live generated labels retain punctuation, and
  an unavailable requested font falls back to the browser font. Text fitting still passes.
- Durable task decisions were folded into architecture conventions and the decision log:
  ship the shared recipe schema; cache validators; Windows Job ownership and shared 0.4s
  cleanup; cached Chromium content/style/geometry measurements with shared text CSS;
  three-row default title; preserve context section order and existing repair budgets.
  Duplicate convention gotchas were removed from AGENTS; environment quirks remain.
- Ignored evidence: `.blueprint/qa/final-reaudit-2026-10-20/`, plus the live suites' named QA
  directories. Live checks used isolated local state and the configured demo cloud project;
  test-created BigQuery resources may remain. Real user build folders were not changed.

## POC release checklist

- Documented demo startup under five minutes: **PASS**, fresh health in 4.25s.
- Backend core flow end to end: **PASS** through the real engine's dry-run; actual report
  creation, hosted deployment and whole-program integration remain the root part's gate.
- Prototype/background visual requirements: **PASS** for fresh core and heading fixtures.
- Known limitations: **PASS**, PRD Later preserves approved deferrals and observed polish.

Mechanical checks: `stamp` PASS; `lint` **0 errors, 4 historical warnings** (44 cumulative
tasks and long Spec sections for 11.3, 11.4 and 12.2); scoped diff whitespace check PASS.
Next program gate: root integration audit once the other parts' final audits are accepted.

## Current task check ledger

| Tasks | Command | Result |
|---|---|---|
| 1.3 | `uv run pytest tests/test_thin_slice.py` | PASS: 9 passed, 1 warning in 13.64s |
| 3.3 | `uv run pytest tests/test_spec_validate.py tests/test_layout.py tests/test_spec_node.py` | PASS: 172 passed, 1 warning in 22.18s |
| 4.1 | `uv run pytest tests/test_render.py` | PASS: 27 passed, 2 deselected, 1 warning in 8.43s |
| 4.3 | `uv run pytest tests/test_recipe_contract.py` | PASS: 46 passed, 1 warning in 4.02s |
| 4.4 | `uv run pytest tests/test_execute.py tests/test_api_contract.py` | PASS: 55 passed, 2 warnings in 24.72s |
| 5.2 | `uv run pytest tests/test_agent_server.py` | PASS: 53 passed, 1 warning in 22.11s |
| 5.3, 9.7 | `uv run pytest tests/test_agent_client.py` | PASS: 22 passed, 1 warning in 63.79s (0:01:03) |
| 6.1 | `uv run pytest tests/test_episodic.py tests/test_context.py` | PASS: 57 passed, 2 warnings in 6.28s |
| 7.3 | `uv run pytest tests/test_research.py` | PASS: 28 passed, 1 warning in 3.19s |
| 9.1 | `uv run pytest tests/test_plan.py tests/test_spec_node.py` | PASS: 38 passed, 2 warnings in 21.24s |
| 9.1, 9.6, 11.8, 13.1, 13.3 | `uv run pytest -m live tests/live/test_backend_flow.py` | PASS: 3 passed, 5 warnings in 384.74s (0:06:24) |
| 9.2 | `uv run pytest tests/test_recipe_contract.py tests/test_api_contract.py` | PASS: 90 passed, 2 warnings in 35.36s |
| 9.3 | `uv run pytest tests/test_execute.py tests/test_agent_server.py tests/test_revise.py` | PASS: 107 passed, 1 warning in 75.09s (0:01:15) |
| 9.4 | `uv run pytest tests/test_spec_validate.py tests/test_render.py tests/test_recipe_contract.py` | PASS: 229 passed, 2 deselected, 1 warning in 41.26s |
| 9.5 | `uv run pytest tests/test_agent_server.py tests/test_agent_client.py` | PASS: 75 passed, 1 warning in 88.15s (0:01:28) |
| 9.6 | `uv run pytest tests/test_context.py tests/test_plan.py tests/test_revise.py tests/test_audit_style.py tests/test_consolidation.py tests/test_eval.py tests/test_research.py` | PASS: 170 passed, 2 warnings in 81.36s (0:01:21) |
| 11.2 | `uv run pytest tests/test_references.py tests/test_api_contract.py` | PASS: 85 passed, 2 warnings in 35.02s |
| 11.2 | `uv run pytest -m live tests/live/test_references.py` | INITIAL FAIL: 1 failed, 1 warning in 19.19s |
| 11.3, 11.4, 11.8 | `uv run pytest tests/test_feasibility.py tests/test_api_contract.py` | PASS: 150 passed, 2 warnings in 52.22s |
| 11.5 | `uv run pytest tests/test_publication.py tests/test_view_sql.py tests/test_plan.py tests/test_render.py` | PASS: 97 passed, 2 deselected, 2 warnings in 35.29s |
| 11.6 | `uv run pytest tests/test_feasibility.py tests/test_plan.py tests/test_interview.py` | PASS: 149 passed, 2 warnings in 60.04s (0:01:00) |
| 11.7 | `uv run pytest tests/test_feasibility.py tests/test_revise.py` | PASS: 149 passed, 1 warning in 60.91s (0:01:00) |
| 12.2, 12.3 | `uv run pytest tests/test_synthetic_api.py tests/test_api_contract.py` | PASS: 65 passed, 2 warnings in 25.70s |
| 12.2, 12.5 | `uv run pytest -m live tests/live/test_synthetic_flow.py` | INITIAL FAIL: 1 failed, 1 passed, 4 warnings in 244.05s (0:04:04) |
| 12.5 | `uv run pytest tests/test_synthetic_label.py tests/test_render.py` | PASS: 52 passed, 2 deselected, 1 warning in 13.40s |
| 13.1 | `uv run pytest tests/test_spec_validate.py tests/test_spec_node.py tests/test_recipe_contract.py tests/test_api_contract.py` | PASS: 260 passed, 2 warnings in 60.20s (0:01:00) |
| 13.2 | `uv run pytest tests/test_agent_client.py tests/test_execute.py` | PASS: 33 passed, 1 warning in 62.94s (0:01:02) |
| 13.2 | `uv run pytest tests/test_agent_client.py::test_stalled_retry_cannot_outlast_the_budget_and_stops_the_engine` | PASS: 1 passed, 1 warning in 3.89s |
| 13.3 | `uv run pytest tests/test_render.py tests/test_spec_validate.py tests/test_synthetic_label.py` | PASS: 208 passed, 2 deselected, 1 warning in 31.19s |
| contract/render acceptance | `uv run pytest tests/test_api_contract.py` | PASS: 44 passed, 2 warnings in 16.27s |
| contract/render acceptance | `uv run pytest tests/test_api_contract.py tests/test_feasibility.py` | PASS: 150 passed, 2 warnings in 51.02s |
| contract/render acceptance | `uv run pytest tests -k synthetic` | PASS: 185 passed, 930 deselected, 1 warning in 33.97s |
| contract/render acceptance | `uv run pytest -m live tests/test_render.py` | PASS: 2 passed, 27 deselected, 1 warning in 3.02s |

Timing check 13.2 also passed four additional fresh-process invocations (five total).
Reference isolated rerun: **PASS**, 1 passed in 20.34s; original failure retained above.
Synthetic screenshot-only isolated rerun: **PASS**, 1 passed in 132.56s; original failure retained above.
