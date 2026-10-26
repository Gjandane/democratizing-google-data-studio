# Proposed follow-up: HIGH brief output and recomputation budget

Date: 2026-10-26. Status: DRAFT, awaiting user review. Backend POC, Design/Task change.
Canonical PRD, architecture, essentials, plan and task markers are unchanged. Task 24.11
remains blocked. This proposal neither authorizes implementation nor grants a fresh live run.

## Evidence and scope

- `.blueprint/qa/task-24.11/high-comparison/README.md` records the completed HIGH-first trial:
  style and the permitted recreate retry each returned MAX_TOKENS from Argon's brief, with
  3 answer + 3,997 thinking tokens against 4,000 total. Neither reached reference HTML or
  publication. The initial recreate failed upstream. None passed. Preserve all these outcomes.
- The earlier LOW recreate page-1 brief had 2,638 answer tokens; the LOW style retry had 2,480.
  Historical thought counts were zero-coalesced and cannot prove no thinking. Those answer
  sizes plus the observed 3,997 HIGH thinking tokens motivate an 8,000 total next trial;
  they do not establish a stable thinking requirement, optimal cap or probability of success.
- Required full-suite and isolated timing checks failed the blocked state of
  `test_recreate_blueprint_recompute_speed_with_24_observations`: best 107.786 ms and
  103.568 ms against the unchanged strict <100 ms assertion. The cause is unproven.
- No new performance measurement or live generation was made in this planning session.
  Source mapping identifies repeated alternative construction/view validation/serialization as
  candidates to profile, not a diagnosed cause. Existing catalog and per-pass coverage caches
  already exist; do not propose their addition as though they were absent.
- The prior shared-chart/footer/preview proposal in `docs/change-24.11-fidelity.md` stays
  unapplied. This follow-up does not authorize its grammar, grouping, title-oracle change,
  footer normalization, compact-number or axis changes. Its visible defects remain unresolved.

## Decisions proposed for user approval

1. Retain HIGH on both reference stages. Increase only reference_brief's total output ceiling
   from 4,000 to 8,000 tokens, including thinking, on first/later pages and revisions. Keep
   its 12k input, strict PageBrief schema, 12k-character aggregate prose limit, current prompt
   targeting and one 120 s stage. This changes a hard budget explicitly; no claim of success.
2. Restore the existing recomputation budget through a separate offline task before the next
   live run. Preserve semantics, the exact workload and strict threshold. No threshold change,
   skipped case, fixture simplification or new timing warmup in the acceptance oracle.
3. After both the performance task and new request regressions pass, permit one fresh bounded
   live sequence at the new brief cap with the original recreate/style/none cases. Existing
   transient retry limits apply independently to that new sequence. Earlier attempts remain
   failed historical evidence, never overwritten or retroactively reclassified.
4. All other limits and fidelity gates remain: HTML 12k initial/24k repair input, 16k total
   output including HIGH thinking, one HTML repair and 600 s/page; no-reference LOW and its
   request/artifact/fallback behavior; no added calls, brief repair, timeout, fallback or
   numeric thinking-budget override. Do not assume local SDK fields establish provider support.

## Architecture sections to apply after approval

### Feasibility recomputation performance preservation

- Problem/objective: deterministic evaluation of ready and blocked recreate Blueprints must
  satisfy the existing <100 ms oracle without changing any feasibility or coverage decision.
- Inputs: current snapshot, ledger, checker, environment/allowed types, 24 observations and
  existing candidate alternatives; output: identical assessment semantics, digest and alternatives.
  Before/after comparisons normalize only the newly generated assessment id; preserve its
  ordinary per-call generation and never normalize issue ids, ordering, evidence or digests.
- Diagnose with stdlib profiling of the exact ready/blocked fixtures before optimization.
  Use a fixed diagnostic capture count (at most five evaluations per state per before/after
  profile); keep profiling outside timed acceptance assertions. Record process access and
  relevant environment/type configuration safely, without values of credentials or rows.
- The builder chooses the smallest measured optimization. Prefer reuse scoped to one evaluate
  call. Cache keys must cover every semantic dependency; never retain mutable snapshot/ledger
  objects or stale authorization across calls, builds, revisions or changes in allowed types.
  Do not bypass candidate validation or replace candidate-content identity with an index/id.
- Preserve issue ids/order/evidence/resolutions, alternatives, truncation/scope rules, digests,
  stale/provenance/reference/source checks, page placement and truthful titles. An alternative
  must still fulfil its target and preserve every previously fulfilled observation. Evaluation
  must not mutate the snapshot, ledger, checker or candidate rows and must make no model/query
  call. Do not change algorithmic meaning to obtain a faster result.
- Oracle: before/after semantic comparisons on both ready and blocked fixtures, repeated-call
  purity and targeted mutations of instructions, KPI meaning/unit, source/reference identity,
  page, title, mappings, decisions and allowed types. The existing negative fixtures remain
  independent expectations. All existing recomputation speed tests retain their workloads,
  timing loops and thresholds. Save unprofiled timings separately from profiler reports.
- Budget: the exact unchanged <100 ms ready/blocked 24-observation test, existing 24-clause
  and 40-requirement/24-component oracles, no new dependency or global mutable cache. If a
  measured semantics-preserving correction cannot pass, block with evidence; never rerun
  unchanged repeatedly until a lucky timing sample passes or relax the requirement.

### Bounded HIGH brief headroom trial

- Supersedes only the brief output ceiling and experiment-order clauses of #Reference thinking
  comparison after user approval. The completed 4k comparison stays documented as failed.
- Brief output becomes 8,000 total tokens, including thinking, through the same request/span/
  generation-guard constant. Input remains 12k, stage 120 s, aggregate prose 12k characters,
  strict schema/security/slot validation unchanged. HIGH applies to all reference brief routes;
  Flash reference HTML stays HIGH/16k output; no-reference stays LOW and unchanged.
- No prompt, fixture, schema/CSV, INSTRUCTIONS, RECREATE_NOTES, model selection, component,
  grouping, title oracle, preview, footer or HTML-input change accompanies this trial.
  A larger generated brief can still fail the unchanged HTML input gate; do not truncate
  authoritative context or raise that gate to force a request through.
- Before live generation, request tests pin the new brief cap and all retained limits for
  first/later/revision routes, strict schemas, count/deadline/cut-output/refusal guards and
  unchanged HTML repair/no-reference fingerprints. Update the live observer's brief cap,
  not historical snapshots or results. Preserve nullable usage semantics and thought privacy.
- New evidence lives under `.blueprint/qa/task-24.12/brief-headroom/`, with source/fixture/input
  hashes, actual models, requested thinking per stage/page/attempt, image counts, nullable
  provider thinking/ordinary usage, finish/truncation, durations, bounds and publication.
  Compare to both retained LOW and 4k HIGH runs without causal claims or treating missing
  metadata as zero. Preserve failed drafts/screenshots via existing sanitization guards.
- One new bounded case sequence follows the existing one transient retry then block policy;
  output-cap failures and deterministic coverage/title/geometry failures cannot earn another
  run. Timeout/refusal eligibility follows the existing failure policy unchanged. No
  silent HIGH-to-LOW fallback, cap escalation or extra attempt. Any failure returns concrete
  evidence to the architect rather than implementing the earlier structural proposal.
- All original 24.11 fidelity/intake/later-page/revision/style/none/coverage/recipe/dry-engine
  obligations move to 24.12 intact. Preserve the read-only visible-defect inventory before
  surfacing known post-publication assertion failures, without continuing gated actions.
  Successful generation, publication, tests and user visual approval are separate outcomes.

## Proposed task sequence

Rewrite only unfinished 24.11 and add 24.12 after it; never change completed task ids/markers.
The earlier HIGH implementation/request tests/evidence are retained as partial completed work,
with their current brief cap explicitly superseded only by the approved follow-up.

### 24.11 Restore the deterministic recomputation budget — M

- Depends on: 24.10.
- Goal: pass the current ready/blocked timing oracle through measured reuse without changing
  assessment meaning or authorization.
- Spec: docs/architecture.md#Feasibility recomputation performance preservation.
- Files: src/dss/spec/requirements.py, src/dss/spec/feasibility.py,
  src/dss/spec/validate.py, src/dss/spec/capabilities.py, tests/test_feasibility.py,
  .blueprint/qa/task-24.11/recompute-performance/, docs/progress.md.
- If: validate.py/capabilities.py are touched -> profiling must first implicate their timed
  shared work. Preserve environment/.env refresh and registry behavior. No unrelated cleanup.
- Done when: capture the exact unchanged ready/blocked oracle's baseline/profile and a safe
  before/after assessment comparison. Exercise purity and cross-call invalidation cases above;
  retain each existing expectation, timing loop, workload and threshold. Capture unprofiled
  before/after timing output; all existing speed oracles pass within the full module and full
  suite. `uv run pytest tests/test_feasibility.py` and `uv run pytest` pass. No live models or
  services. Record an unresolved performance cause or failed correction honestly as a block.
- Review focus: assessment/coverage/provenance/page/title equality and evaluation-local reuse;
  existing dashboard-intent/API shapes unchanged; no timing-oracle weakening or stale decisions.

### 24.12 Verify HIGH reference fidelity with bounded brief headroom — M, supervised

- Depends on: 24.11.
- Goal: test HIGH with an explicitly bounded 8k brief output budget, then require every existing
  fidelity gate; success at the cap experiment alone does not complete the task.
- Spec: docs/architecture.md#Bounded HIGH brief headroom trial; #Reference design brief;
  #Reference HTML composition; retained observation/page/title specifications from 24.10.
- Files: src/dss/harness/nodes/reference_brief.py, tests/test_reference_brief.py,
  tests/test_designer.py, tests/live/test_reference_design.py, tests/data/reference_design/,
  .blueprint/qa/task-24.12/, docs/progress.md.
- If: implementation -> change only the brief output constant and related regression/evidence
  assertions. HTML runtime already requests HIGH; no designer.py runtime edit is needed.
  Existing brief prose/output safety, request counts/deadlines and no-reference fingerprints
  remain required. No fixture changes; record hashes to prove this.
- If: live -> first run `uv run pytest tests/test_reference_brief.py tests/test_designer.py`.
  Then run the existing real configured planner/worker + dry-engine cases under the unchanged
  transient retry policy and all original 24.11 intake diagnostics/fixture-provenance rules.
  Stop before models if synthetic intake fails. Preserve historical 24.9/24.10/24.11 evidence.
- STOP: show the reference and successful recreate prototype side by side; identify every
  native slot, every previously approved unsupported substitution and all remaining visible
  issues, plus later-page/revision evidence. User approves fidelity or names what is off.
  The approved substitutions remain: omit geo_map/keep static real-geography globe; omit
  legend-as-dropdown and extracted year slider; native fixed_size_list; four country panels
  become ONE native urban/rural area. Any other unsupported item still blocks. No approval
  may be requested for a nonexistent/failed-acceptance prototype. Never mark done without it.
- Done when: every original 24.11 acceptance requirement is carried forward verbatim into the
  applied task (including worldwide (%) title, one right-hand area, readable scorecard/yearly
  labels, truthful native slots, protected footer, no fallback for references, all pages and
  revision, style/no-reference, exact fixture hashes, coverage, compiled recipe and dry engine).
  Record stage/model/requested-thinking/image/nullable-usage/time evidence at the new brief
  cap with all other limits unchanged. No assertion or visible defect is silently corrected.
  `uv run pytest -m live tests/live/test_reference_design.py`,
  `uv run pytest tests/test_reference_brief.py tests/test_designer.py tests/test_render.py tests/test_revise.py`
  and `uv run pytest` pass, then obtain the visual STOP. A deterministic fidelity failure
  blocks with inventory/evidence rather than granting more retries or selecting structural work.
- Review focus: native charts/control marks and unchanged public contracts, input/privacy/
  publication/rollback rules, bounded trial attribution and explicit user visual acceptance.
  Full engine/report integration remains release work.

## Canonical updates after approval

- PRD: append the explicit user decision for this follow-up, retaining historical HIGH-first
  intent; update the current brief output cap and current live acceptance task to 24.12.
  No other goal, non-goal or Later item changes; no deferred structural fix is promoted.
- Architecture: add the two sections above, update current brief-budget statements in Working
  memory assembly and Reference design brief, and annotate #Reference thinking comparison
  as the completed 4k phase now followed by the approved 8k phase. Keep historical decision
  rows intact; add a dated decision row for the new cap and performance split.
- Essentials: summarize the new brief ceiling and preservation spec, remove obsolete wording
  that still treats the first HIGH comparison as pending, then stamp with architecture.
- Plan: rewrite blocked 24.11 and add 24.12 with the original fidelity requirements in full.
  Carry all original task-specific Ifs, provenance/retry/STOP obligations to 24.12; replace
  only output=4k by the approved 8k and obsolete comparison order/evidence destination.
  Update phase intro/current cross-references, retain completed-task history and earlier checks.
  Reopen 24.11 using blueprint.py only after approval, then stamp/lint and record Change.
- No dependencies, contracts, AGENTS rules, product code or tests change during planning.
  Folder mode: no commit. After accepted fidelity, backend final re-audit remains necessary;
  release integration follows at the program root after backend acceptance.

## Review and checks

- Independent fresh-context blueprint_reviewer delta review: **No findings**. The reviewer
  inspected the draft, canonical decisions, retained evidence and narrow source/tests; ran
  no tests, services, model calls, profiling or lint; and changed no files. A final wording
  clarification explicitly retains the existing timeout/refusal retry eligibility.
- Canonical blueprint lint: **85 tasks, 0 errors, 16 existing size warnings**. This validates
  the unchanged current plan, not a future applied version of these proposed tasks.
- No dependency changes or registry lookup; no architecture edit or stamp. No new model call,
  performance profile or product test result is claimed. Existing failed checks stay failed.
- User review remains pending. Approval would authorize the two tasks and the new bounded
  sequence, never fidelity or final audit acceptance. Apply top-down and rerun stamp/lint
  after approval; do not start a builder from this draft.
