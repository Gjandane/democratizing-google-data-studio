# Reference images and feasibility: scope audit
2026-10-19. Planning audit, not a final release certification.

## User decisions
- Both features are required for this hackathon release.
- Recreate the closest supported layout, chart choices and styling using connected data;
  explain substitutions. Pixel-exact reproduction is not required.

## Findings and dispositions
Read-only blueprint_reviewer reviewed the current plans and relevant implementation.

| ID | Severity | Finding and evidence | Planned correction |
|---|---|---|---|
| F1 | P1 | Type-only checks cannot reject unsupported behavior; backend/docs/architecture.md (Dashboard Spec, Revise), contracts/recipe.md options, backend/src/dss/spec/models.py Component.options | Backend 11.1/11.5: feature/value registry and requirement-preserving gates |
| F2 | P1 | No unknown outcome or reliable product/app distinction; backend/docs/architecture.md (Working memory), backend/src/dss/harness/nodes/revise.py refusal | Structured statuses, evidence, explicit alternatives and fail-closed unknowns |
| F3 | P1 | StyleProfile has no layout/components; backend/src/dss/harness/nodes/style_extract.py, backend 7.1 and frontend 4.1 | Backend 11.2/11.5 and frontend 10.1: style versus recreate modes |
| F4 | P1 | Existing-field validation cannot resolve screenshot metric semantics; backend/docs/architecture.md Dashboard Spec | Confirm ambiguous definitions, units, aggregation and grain; no screenshot values used as rows |
| F5 | P2 | Upload/run response and overwritten style.md do not define reference lifecycle; contracts/api.md style-images, backend/src/dss/api/builds.py | One retained replaceable set per version; safe previews, remove, version copy, stale gates |

All five corrections are recommended. The former style feature is already implemented according
to its progress entries and inspected source; these are new tasks, not reopened completed work.
No engine expansion is planned. A product-level impossibility claim needs evidence; the moving
GPS request is rejected by this application's current supported surface.

## Proposed task sequence
| Part / ID | Task | Size |
|---|---|---|
| backend 11.1 | Evidence-backed capability registry and deterministic checks | M |
| backend 11.2 | Versioned references and structured image interpretation | M |
| backend 11.3 | Requirement ledger, assessments and explicit decisions | M |
| backend 11.4 | Stage candidate views and recover failed publication | M |
| backend 11.5 | Enforce feasibility throughout planning and building | M |
| frontend 10.1 | Reference modes and feasibility decisions | M |
| release 3.3 | Reference and refusal end-to-end acceptance | M |

Provider tasks precede consumers; release needs both implementations. Backend 9.7 is currently
in progress and must finish in its own session. Existing backend 10.1 is independent activity
work; existing task 10.1 completes before Phase 11 to keep task order stable; no additional stretch
expansion precedes the required scope.

## Defaults recorded for review
- Single page screenshot for recreation; up to three for style; retained per version.
- No community visualization, custom animation or expanded engine in this change.
- Curated, dated evidence with deterministic final checks; no web search on every user turn.
- Accept a proposed substitution explicitly; unknown requests ask for clarification.
- Original reference images stay private build assets; they are never inserted as a fake dashboard.
- Existing approved dependencies only. Additional dependencies require a separate decision.

## Verification
- Baseline root contract suite: 9/9 passed.
- Baseline lint: release 0 errors/0 warnings; backend 0 errors, task-count warning (27);
  frontend 0 errors, oversized essentials and historical out-of-order date warnings.
- The scoped reviewer did not run tests. No claim that the new behavior is built or verified.
- Active implementation edits and pre-existing deck/source/doc changes were present before this
  audit. This session changes planning documents and contract fixtures only.

## Delta audit and sizing
The reviewer found and the draft corrects five integration gaps: assessment recovery, durable
choices across spec changes, candidate-view rollback, comment recovery after reload, and deploying
the actual implementation before hosted acceptance. A focused recheck found no remaining P1
contradictions; its remaining P2 was task sizing, resolved by splitting 11.3 into 11.3-11.5.
Seven M tasks now implement two feature additions. The normal change-flow heuristic suggests a
new version beyond about five tasks; the user's explicit decision to require both in this release
keeps these here. This is a material deadline risk, not a claim they fit the remaining time.
The changed plan headers are Audit: pending; existing completed task markers remain intact.
No new dependency is proposed. Existing verification dates are retained; no new package lookup
was needed. Source/fixture compatibility check: frontend contract suite 31/31 passed.

## Final planning checks
- Release lint: 12 tasks, zero errors/warnings.
- Backend lint: 32 tasks, zero errors; existing large-plan warning remains.
- Frontend lint: 18 tasks, zero errors; historical progress-date warning remains.
- Architecture stamps regenerated. Root contract checks 9/9; frontend contract tests 31/31.
- New dashboard-intent JSON fixtures parse; their behavioral conformance is future task work.
- git diff --check on docs/contracts: no whitespace errors (Git printed line-ending notices).
- No product changes, full-suite claim, deployment or commit in this planning session.

## Status
Draft scope change awaiting the skill's final plan review. See contracts/dashboard-intent.md and
the affected part plans for the full rules, budgets and acceptance commands. Product code remains
for builder sessions. Do not interpret historical Audit: done lines as approval of this change.
