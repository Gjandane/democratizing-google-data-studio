# Stage Settings reconciliation hold

> Resolved 2026-10-26 (user card): the program-root architect session that wrote API 3.0 owns
> the change. Findings 1 (kept grouped by user choice), 2-7 were applied there; see the
> 2026-10-26 Change entries in docs/progress.md. This record is historical.

Date: 2026-10-26. Status: first-pass independent delta audit has defects; canonical planning
is NOT builder-ready. This is a coordination record, not a replacement contract or build task.

## What happened

The authorized fresh architect session read API 2.0 and the closed 30-answer interview.
While it prepared the canonical update, another writer changed `../contracts/api.md` to 3.0,
conventions to 1.4, the program roadmap, backend architecture/tasks and frontend tasks.
Observed modification times progressed through 20:31 (API), 20:34 (backend architecture),
20:36 (backend plan) and 20:38 (frontend/root plans), Asia/Manila. These were not writes made
by this session or its read-only explorers/reviewer. The originating interview chat is idle;
the available app chat inventory did not identify the writer.

To avoid overwriting it, this session stopped canonical mutations and asked the user whether
another session is still writing. That coordination question remains pending. Its eight newly
created, unreferenced alternative contract/schema/example files were moved to
`.blueprint/parked-model-stages-draft/` inside backend. The scratch alternative apply script is
disabled. Neither is canonical or a builder input. No product code, task markers, secrets,
published artifacts or retained failed evidence were changed by this session.

## Independent delta findings

Reviewer: read-only `blueprint_reviewer`, fresh context. It inspected current canonical API 3.0,
backend planning docs, affected frontend plans and actual frontend source. No files edited;
no tests, network, services or paid model requests run by the reviewer. Line references below
refer to the external draft as read during the audit; re-anchor them if that writer continues.

1. **P1 — Independent selectors collapsed.** API lines 319-350 groups Context/Outline as
   `interview` and unrelated model nodes as `routine`; frontend task 16.2 tests seven rows
   (frontend plan line 270). This contradicts the accepted independent model choice at every
   LLM stage (interview lines 25-32). Enumerate real model stages, retaining separate stored
   selections and tests that editing one leaves all others unchanged. There is no separate
   free-text interview node: Context is the current interview. Repairs reuse parent profiles;
   deterministic nodes do not get model selectors. Include synthetic-schema, research
   discovery/selection, consolidation and existing diagnostics where they call a model.
2. **P1 — Migration loses explicit choices.** API lines 366-372 preserves only known values
   different from old defaults and omits role-changing routes. Preserve explicit stored/env
   values, including default-equal and unknown ids, with visible compatibility correction;
   do not replace them silently. Use documented role mapping, presence/origin tracking and
   idempotent restart tests in backend 25.1. Accepted source: handoff lines 53-55.
3. **P1 — Layout fallback too broad.** Backend architecture lines 1486-1492 and task 25.5
   (plan line 814) allow nearly any non-cap/non-cancel failure to publish standard layout.
   Restrict to completed HTML exhausting permitted layout/HTML validation repairs. Provider,
   timeout and failed-brief paths must not newly publish a kit. Preserve strict reference
   behavior and test excluded failures. Accepted source: handoff lines 87-90 and answer 30.
4. **P1 — Hard caps classified as transient live retries.** Backend plan line 837 groups cap,
   clock and model failures under one rerun rule. Input overflow/output cutoff stop and retain
   evidence without automatic fresh generation. Separate eligible transient case reruns from
   deterministic cap/content/coverage failures; preserve the exact real fidelity and timing
   gates. Accepted source: interview lines 236-245.
5. **P1 — Effective Settings snapshot not durable.** Backend architecture lines 1399-1401
   passes an in-memory immutable snapshot, but API StageCall lines 406-413 omits timeout,
   retry/repair allowances, counting margin and review/layout policies. Persist a complete
   credential-free action snapshot and exact used brief identity. Add restart/read-back and
   in-flight Settings-change tests to backend 25.2/25.3. Accepted source: interview 392-394.
6. **P1 — Approval can approve unseen edited text.** API lines 419-421 uses only `review_id`
   for save/approve. Tab B can save a new brief while tab A approves the old display using the
   same id. Add edit revision/CAS and expected validated brief hash, atomic review consumption,
   defined duplicate approval/cancel outcomes and lost-response recovery. Include two-client,
   stale edit/approval and restart checks in backend review task and frontend conflict tests.
   Artifact/reference freshness alone does not detect a concurrent edit to that same brief.
7. **P2 — Pending-review lock coverage incomplete.** Frontend spec lines 68-70 requires all
   workspace mutations locked, but task 16.3 checks only five actions (plan 278) and omits
   ArtifactStage.tsx from Files (275). Its current lock is transient running state
   (ArtifactStage.tsx:196-197), cleared by run.finished (useBuildStream.ts:228-255). Plan a
   persisted review lock restored on mount/reconnect and propagate it to artifact editors,
   references, feasibility decisions/checks, audit, uploads/intake and other mutation paths,
   with Settings/read/download/cancel behavior explicitly retained.

These are future-plan defects, not claims that the expected yet-unimplemented feature is a
new runtime bug. All are in the human's accepted change scope and can be corrected without
restarting the questionnaire once writer ownership is settled.

## Checks actually run

- Read-only frontend/backend explorer inventories completed; source evidence returned.
- `uv run --project integration python integration/check_contracts.py` at program root,
  with normal process access and backend-local UV cache: exit 0, **all 13 checks passed**.
  This is a baseline of the existing checker; it does not certify new API 3.0 shapes or any
  new implementation, and predates completion of the concurrent planning writes.
- No product suite, performance profile, paid trial, visual acceptance, final stamp/lint or
  final independent acceptance is claimed here. The known <100 ms performance and real
  fidelity/side-by-side approval gates remain unresolved.

## Resume

Resolve the pending coordination question, obtain a stable canonical file set, apply the
findings top-down to contract/architecture/essentials/tasks/fixtures, then re-review the final
delta independently. Stamp/lint each changed part, validate shared examples/schema and run
the release contract checker again; record real results in each affected progress log.
Preserve completed history and use blueprint.py only for task markers. Do not commit another
writer's changes while ownership is unclear. The intended first builder task remains backend
24.11 measured semantics-preserving performance recovery, but do not issue a builder-ready
handoff until the canonical change and review are complete.
