# Backend final re-audit — 2026-10-20

Verdict: **DEFECTS**. Eight repairs in Phase 13; no product source/test changes made by the architect.
This follows the 2026-10-19 final audit and reviews completed tasks 9.1–12.5, plus affected earlier
behavior. Original task markers remain unchanged. Contracts and other parts were not edited.

## Findings

| Priority | Current evidence | Repair |
|---|---|---|
| P1 | Theme.palette accepts arbitrary strings (`src/dss/spec/models.py:51`); compiler emits them (`src/dss/recipe/compiler.py:44`). Live colors `2563EB`, `0EA5E9`, etc. violate the contract's #RRGGBB constraint. Real engine dry-run exits 2 at recipe line 6, `style.colors.items.pattern`; the API build returns to prototype. | 13.1 M — validate theme and generated recipe; extend live acceptance through real engine dry-run |
| P2 | Full suite stalled-retry check takes 2.031s for a 1.5s budget + 0.5s tolerance; isolated rerun takes 2.015s. Client closure/process teardown in `src/dss/agent/client.py:162,364` must stay bounded. Focused agent suites sometimes pass; this is not an accepted waiver. | 13.2 M — bound retry expiry cleanup, retain current tolerance |
| P2 | Fresh live core screenshot clips the heading. `.item` padding/hidden overflow (`src/dss/render/prototype.py:223`) consumes a 2-row title's 24px height; decoration content size is not validated (`src/dss/spec/validate.py:86`). Same HTML bakes the background. | 13.3 M — fit/validate heading text and inspect prototype/background |
| P2 | `chart_option` ignores bar orientation/pie donut (`src/dss/render/prototype.py:165,190`), with compact numbers, pivot axes and table rows_per_page also missing. Compiler preserves these supported options. Parent probes return identical options for horizontal/vertical and pie/donut. | 13.4 M — renderer/recipe semantic parity and visual oracles |
| P2 | Version destination is created before fallible copy/capture (`src/dss/api/builds.py:135,148`). Injected copy failure returns 422, leaves v2/current_version=1; every retry returns 422 because v2 exists. | 13.5 M — owned staging/publication and restart-safe rollback |
| P2 | `math.isfinite` runs before integer magnitude validation (`src/dss/data/synthetic.py:299,437`). 10**400 in decimal bounds/choice raises OverflowError; actual API returns 500. | 13.6 S — field-specific numeric rejection through function/API/CLI |
| P2 | Supported but unfulfilled pie requirement: ready → recipe 409 → blocked → explicit check 202 → ready/non-stale. `capability_check.py:126` recomputes support and overwrites `requirements.py:658`'s coverage block. Execution still refuses: false readiness, not an execution bypass. | 13.7 S — preserve fulfillment failure until artifact repair |
| P2 | Folded counter output is trusted directly (`src/dss/harness/llm.py:60`, `context.py:175`); recorded live evidence is 8,245 folded vs 8,695 billed input tokens. Whole-request budgets can be exceeded near the boundary. | 13.8 M — conservative enforced bound, distinct counts and near-limit live oracle |

Independent blueprint_reviewer confirmed the six original source defects, the added color P1 and
the repair plan. Its sizing/table-option findings were applied. Parent ran the reproducers and
checks. Reviewer ran no product checks. No built Non-goal or demonstrable Decision contradiction.

## Current checks

- `uv run pytest`: **FAIL**, 910 passed, 1 failed, 9 live deselected, 500.63s; only failure is
  `test_stalled_retry_cannot_outlast_the_budget_and_stops_the_engine`. Three upstream warnings.
  Isolated rerun: **FAIL**, same assertion, 5.08s. Do not claim Test (all) passes.
- Combined live invocation of models, backend_flow, references, synthetic_flow and render:
  **8 passed, 1 failed**, 25 non-live deselected, 457.84s. The failed reference call returned
  invalid observations. Its standalone rerun **passed** in 22.95s; no extra in-node retry added.
  Core interview/plan/view/prototype, GPS refusal, explicit image revenue mapping, typed synthetic
  intake, screenshot-only labeled prototype/recipe and both Chromium render checks passed.
- Fresh documented uvicorn startup without reload: `/api/health` **200**, `{status:ok}`, 3.22s.
  Runtime isolated; root .env unchanged. Real model-generated core flow was repeated to retain
  runtime for execution; it passed to prototype, then the real engine rejected its invalid color.
- Synthetic CLI: **PASS**, 20 rows, 1,529 bytes, SHA256
  `b70c89f0289cc8bec4f373d90b51b096bb6a67488525030008a3b707af37f8b1`.
  Measured 100,000×10: **PASS**, 13.81s under tracemalloc, peak 0.2MiB traced allocation,
  6.3MiB output; within 30s/128MiB budgets.
- API/recipe/dashboard-intent conformance commands rerun among task checks below; synthetic
  conformance also rerun separately with `uv run pytest tests -k synthetic`.
  Manual conventions review: backend ports, env names, UTC IDs, version-relative paths,
  access/agent credential separation match the named contract. No contract change needed.
- Viewed fresh core, image-mapping and synthetic screenshots at their 1200px spec canvases;
  core heading fails visual acceptance, synthetic provenance footer is visible. This is backend
  prototype QA; frontend/deployment/whole-program integration acceptance belongs to the root.
- `blueprint.py deps`: all 17 declared rows FOUND, no new dependency. All 16 installed direct
  runtime/test dependencies satisfy declared ranges. Installed FastAPI 0.141.1 differs from the
  table's parenthetical 0.146.0, but fits >=0.115. Setuptools is an isolated build dependency.
- Reviewer metadata-only backend tracked/history scans: no tracked .env/.env.* or match for
  scanned Google API/OAuth, sk-key/private-key patterns; no values printed. This is scoped
  pattern evidence, not a whole-program history/security certification.

## Reconciliation and limits

- Superseded findings: planner schema transport, hosted recipe preview, current-spec execution,
  sort direction, flat agent assets and the old unbounded retry attempt now have passing task
  checks. The remaining retry completion/tolerance failure is recorded separately above.
- The old claim that every consolidate/judge success loses usage is disproved for judge by an
  effective ADK FakeLLM probe: trace records 5 input/2 output. Callback source replacement alone
  is not proof of lost metadata. Missing retry-listener ownership for independent optional runs
  and failed-response accounting remain explicitly deferred in PRD Later.
- Old synthetic cleanup readiness finding is superseded by 12.4's deterministic-job fence and
  pending-ownership recovery. Earlier partial/blocked task attempts were completed later.
- Still-deferred POC limits are in PRD Later: growing consolidation index, optional live schema
  smokes, Windows Ctrl+C measurement, no-hard-link concurrent output race, duplicate-key error
  paths, 8.3 reference aliases and case-sensitive packaging coverage. No current code-budget,
  fulfillment, visual or core-flow defect was silently deferred.
- Original manual research prompt, optional consolidation/judge/audit live smokes and the old
  standalone agent manual demo were not repeated: earlier audit evidence remains scoped to
  those paths; current required offline suites and affected live core paths were rerun. No
  accepted final/integration verdict or claim of successful real report creation is made.
- POC release checklist: documented startup PASS; core path to real-engine dry-run FAIL on
  color contract; visual heading FAIL; known limitations documented. Backend must pass the
  Phase 13 checks and a fresh final audit before root integration acceptance.

## Evidence and task check ledger

Ignored QA files: `.blueprint/qa/final-audit-2026-10-20/` (`checks.json`, check logs, probes.json,
engine-probe.json, engine-trace.json, manual.json, core/, live-runtime/). Live suites also write
their documented `.blueprint/qa/task-11.8/`, `task-12.5/` and `final-audit/task-11.2/` evidence.
Live core QA created tables/views in the previously authorized demo project; configuration and
real user build folders were not changed. Evidence may retain those test resources for diagnosis.

The ledger below records each distinct task Done-when pytest command once, sharing an identical
command across tasks. All 41 original tasks are represented; baseline suites were also rerun,
so no earlier automated task suite was skipped. The new Phase 13 tasks have not been built.

<!-- task-ledger:start -->
| Tasks | Command | Current result |
|---|---|---|
| 1.1 | `uv run pytest tests/test_skeleton.py` | PASS: 7 passed, 1 warning in 5.83s |
| 1.2 | `uv run pytest tests/test_intake.py` | PASS: 23 passed, 1 warning in 6.02s |
| 1.3 | `uv run pytest tests/test_thin_slice.py` | PASS: 9 passed, 1 warning in 14.37s |
| 2.1 | `uv run pytest tests/test_memory_semantic.py` | PASS: 11 passed, 1 warning in 1.23s |
| 3.1 | `uv run pytest tests/test_interview.py` | PASS: 19 passed, 2 warnings in 13.96s |
| 3.2 | `uv run pytest tests/test_plan.py tests/test_view_sql.py` | PASS: 39 passed, 2 warnings in 31.49s |
| 3.3 | `uv run pytest tests/test_spec_validate.py tests/test_layout.py tests/test_spec_node.py` | PASS: 47 passed, 1 warning in 36.29s |
| 4.1 | `uv run pytest tests/test_render.py` | PASS: 25 passed, 2 deselected, 1 warning in 5.17s |
| 4.2 | `uv run pytest tests/test_revise.py` | PASS: 43 passed, 1 warning in 39.86s |
| 4.3 | `uv run pytest tests/test_recipe_contract.py` | PASS: 24 passed, 1 warning in 3.88s |
| 4.4 | `uv run pytest tests/test_execute.py tests/test_api_contract.py` | PASS: 17 passed, 2 warnings in 21.77s |
| 5.1 | `uv run pytest tests/test_cloud_mode.py` | PASS: 22 passed, 1 warning in 5.12s |
| 5.2 | `uv run pytest tests/test_agent_server.py` | PASS: 53 passed, 1 warning in 33.57s |
| 5.3, 9.7 | `uv run pytest tests/test_agent_client.py` | PASS: 17 passed, 1 warning in 65.81s (0:01:05) |
| 6.1 | `uv run pytest tests/test_episodic.py tests/test_context.py` | PASS: 57 passed, 2 warnings in 10.34s |
| 6.2 | `uv run pytest tests/test_consolidation.py` | PASS: 12 passed, 1 warning in 8.04s |
| 7.1 | `uv run pytest tests/test_audit_style.py` | PASS: 18 passed, 1 warning in 6.45s |
| 7.2 | `uv run pytest tests/test_eval.py` | PASS: 14 passed, 1 warning in 3.28s |
| 7.3 | `uv run pytest tests/test_research.py` | PASS: 28 passed, 1 warning in 6.07s |
| 9.1 | `uv run pytest tests/test_plan.py tests/test_spec_node.py` | PASS: 36 passed, 2 warnings in 35.24s |
| 9.2 | `uv run pytest tests/test_recipe_contract.py tests/test_api_contract.py` | PASS: 32 passed, 2 warnings in 17.23s |
| 9.3 | `uv run pytest tests/test_execute.py tests/test_agent_server.py tests/test_revise.py` | PASS: 105 passed, 1 warning in 75.89s (0:01:15) |
| 9.4 | `uv run pytest tests/test_spec_validate.py tests/test_render.py tests/test_recipe_contract.py` | PASS: 82 passed, 2 deselected, 1 warning in 32.11s |
| 9.5 | `uv run pytest tests/test_agent_server.py tests/test_agent_client.py` | PASS: 70 passed, 1 warning in 94.26s (0:01:34) |
| 9.6 | `uv run pytest tests/test_context.py tests/test_plan.py tests/test_revise.py tests/test_audit_style.py tests/test_consolidation.py tests/test_eval.py tests/test_research.py` | PASS: 170 passed, 2 warnings in 81.32s (0:01:21) |
| 10.1 | `uv run pytest tests/test_usage_events.py` | PASS: 7 passed, 2 warnings in 3.66s |
| 11.1 | `uv run pytest tests/test_capabilities.py` | PASS: 32 passed, 1 warning in 0.16s |
| 11.2 | `uv run pytest tests/test_references.py tests/test_api_contract.py` | PASS: 49 passed, 2 warnings in 21.61s |
| 11.3, 11.4, 11.8 | `uv run pytest tests/test_feasibility.py tests/test_api_contract.py` | PASS: 114 passed, 2 warnings in 44.95s |
| 11.5 | `uv run pytest tests/test_publication.py tests/test_view_sql.py tests/test_plan.py tests/test_render.py` | PASS: 95 passed, 2 deselected, 2 warnings in 43.85s |
| 11.6 | `uv run pytest tests/test_feasibility.py tests/test_plan.py tests/test_interview.py` | PASS: 149 passed, 2 warnings in 95.08s (0:01:35) |
| 11.7 | `uv run pytest tests/test_feasibility.py tests/test_revise.py` | PASS: 149 passed, 1 warning in 61.98s (0:01:01) |
| 11.9 | `uv run pytest tests/test_llm_retry.py` | PASS: 18 passed, 2 warnings in 19.06s |
| 12.1 | `uv run pytest tests/test_synthetic.py` | PASS: 115 passed, 1 warning in 18.50s |
| 12.2, 12.3 | `uv run pytest tests/test_synthetic_api.py tests/test_api_contract.py` | PASS: 29 passed, 2 warnings in 23.76s |
| 12.4 | `uv run pytest tests/test_synthetic_recovery.py` | PASS: 21 passed, 1 warning in 13.82s |
| 12.5 | `uv run pytest tests/test_synthetic_label.py tests/test_render.py` | PASS: 47 passed, 2 deselected, 1 warning in 7.85s |
<!-- task-ledger:end -->

Synthetic contract subset: **182 passed, 738 deselected**, 56.87s.
Final mechanical check: stamp PASS; lint **0 errors, 4 warnings** (49 cumulative tasks and
historical Spec sizes for 11.3, 11.4, 12.2). Essentials and AGENTS size warnings resolved.
