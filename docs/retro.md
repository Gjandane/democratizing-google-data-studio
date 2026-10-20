# Retro: Democratizing Google Data Studio (2026-10-20)

Subject: the architect skill's audit loop. Asked by the user: "I keep getting stuck in auditing and
keep adding new tasks."

## Metrics
- Tasks added by audits: backend 15 of 49 (phases 9, 13), frontend 6 of 24 (phases 7, 8, 9, 12),
  engine 4 of 13 (phase 5). 25 audit-fix tasks across the program, 3 days before the deadline.
- Audit entries: backend 4, frontend 6, engine 2, release 2. Change entries: backend 8, frontend 6,
  release 6.
- Plan/delta audits applied every finding: 18/18 (program), 12/12 (frontend delta), 13/13 (release
  delta).
- Bottleneck scores (retro script): no task over score 2. The cost is not in the build loop; it's
  the tasks the audits add.

## Bottlenecks
- Frontend final audit loop: 2026-10-19 final audit (4 P2) -> Phase 7 -> re-audit found 4 P3 ->
  Phase 8 -> re-audit found 4 P3 -> Phase 9 -> re-audit after Phase 11 found 1 P1, 2 P2, 9 P3 ->
  Phase 12 (2 M tasks, all 11 accepted). Phases 8 and 9 were P3 only (punctuation, a hover state,
  a footer font) and each cost a build session plus a re-audit.
- Backend final re-audit 2026-10-20: 1 P1 + 7 P2 -> 8 tasks (6 M, 2 S), at POC. One is a timing
  test over budget by 31 ms (13.2), one is 10**400 as generator input (13.6).
- Release change 2026-10-20 recorded "seven sessions of M work may conflict with deadline; both
  remain required until user explicitly changes scope": the skill had no step that weighed scope
  against the deadline.
- Tooling: `program` reports frontend "final audit ACCEPTED" (its entry says DEFECTS, "user
  accepted all 11 code findings") and release "final audit ACCEPTED" (it was a delta audit titled
  "final phases"; 12 tasks to do).

## Root causes
- Plan quality (audit rules): audit.md turns every finding into a task ("one `[ ]` task per
  defect"); no severity bar, no target-scaled threshold, no fix budget.
- Plan quality (audit rules): a re-audit is a full fresh audit, so each one finds a new layer of
  P3s. Nothing makes the loop converge.
- Plan quality (reviewer): the reviewer grades P0-P3 with no definitions, and the final-audit brief
  has no length cap or POC bar, so polish arrives with the same weight as defects.
- Plan quality (change flow): no scope gate against a deadline; changes add tasks freely.
- Tooling: `final_audit_state` matches "final" anywhere in a heading and "accepted" anywhere in
  the verdict prose.

## Proposed skill changes

### P1 Severity bar and fix budget for every audit
- File: blueprint-solution-architect/references/audit.md (new section after "Spawning the
  reviewer"; Contents line updated)
- Current: "none"
- Proposed:
  ```
  ## Severity bar: what an audit may add

  An audit always finds something; a deadline can't absorb all of it. Every audit (plan, delta,
  final, re-audit) grades each finding, and only a blocker earns a task.
  - P0: data loss, a leaked secret, a security hole, or the core flow broken.
  - P1: a PRD Goal, a Done when or the target's release checklist fails.
  - P2: wrong behavior off the core flow, or a fragile spot with a concrete failure.
  - P3: polish, wording, style, a hypothetical edge case.

  Blockers are P0 and P1, plus a P2 on the main path at MVP or production. Everything else is a
  known limitation: one line in the PRD's `## Later` list (source `audit <date>`), never a task,
  even when the fix is one line. On the cards, recommend only the blockers, and put the rest in
  one grouped option, "to Later", which the user can override.

  Fix budget: one audit-fix phase per final audit, at most 2 tasks at POC and 3 at MVP
  (production: no cap). Group the blockers into those tasks. If they don't fit, show them ranked
  on a card, with the program's cut order if there is one; the user picks, and the rest go to
  Later or to a change.

  A plan-audit or delta-audit finding fixed in the docs alone costs no build session: recommend
  it freely. One that adds or splits a task follows the bar.
  ```
- Evidence: frontend phases 8, 9 (P3 only); backend phase 13 (7 P2 at POC); 25 audit-fix tasks.
- Expected effect: frontend stops after Phase 7; backend Phase 13 shrinks to 13.1 plus at most one
  more. Several M sessions saved per part.

### P2 Re-audits converge: check the fixes, not the whole build again
- File: blueprint-solution-architect/references/audit.md, Final audit step 1 "Re-audits" and
  step 5 verdicts
- Current (step 1): "Name what you skipped, and why, in the entry. The first final audit of a
  version reruns everything."
- Proposed (appended): "The re-audit's reviewer brief names only the fix and change tasks since
  that audit and asks for blockers only (P0, P1; see "Severity bar"). No blocker means ACCEPTED.
  A second audit-fix phase in a row needs the user's yes on a card that names its cost: a build
  session per task and another re-audit."
- Current (step 5): "- **DEFECTS**: append a phase `## Phase N: Audit fixes` to plan.md with one
  `[ ]` task per defect, each with its own Done when."
- Proposed: "- **DEFECTS** (only when a blocker remains, per "Severity bar"): append a phase
  `## Phase N: Audit fixes` to plan.md within the fix budget, each task with its own Done when."
  and ACCEPTED gains: "No blocker is ACCEPTED, whatever the count of P2 and P3."
- Evidence: frontend re-audits after Phases 7 and 8 each found 4 new P3s and added a phase.
- Expected effect: at most one fix phase plus one narrow re-audit per final audit.

### P3 Reviewer grades by fixed definitions, with a POC bar
- Files: ~/.claude/agents/blueprint-reviewer.md (shared with the builder); audit.md final-audit
  brief (step 2)
- Current (agent): "Cite file:line evidence, order findings by severity (P0 to P3), and keep to
  the length the brief asks for."
- Proposed (agent): "... (P0 to P3): P0 data loss, a leaked secret, a security hole or the core
  flow broken; P1 a Goal, Done when or release checklist fails; P2 wrong behavior off the core
  flow; P3 polish or a hypothetical case. Never raise a finding's severity to get it fixed. For a
  POC, list P3s in one line each, at most five."
- Proposed (brief, appended to step 2's quoted brief): "Grade each finding P0-P3. At most about
  600 words."
- Evidence: backend 13.2 (31 ms over a timing budget) and 13.6 (10**400 input) graded P2 at POC.

### P4 Scope gate in the change flow
- File: blueprint-solution-architect/references/change.md, section 2, after the class table
- Current: "none"
- Proposed: "**Scope gate.** When the PRD or docs/program.md names a deadline, a Task- or
  Product-class change that adds tasks is a card, never a ruling: show the tasks left, their sizes
  and the days left, and recommend deferring to the PRD's `## Later` list unless it fixes a blocker
  (audit.md, "Severity bar") or the user calls it critical."
- Evidence: release change 2026-10-20 ("seven sessions of M work may conflict with deadline");
  18 change entries across parts in 3 days.

### P5 Script: read the final-audit verdict strictly
- File: scripts/blueprint.py `final_audit_state` (all 4 copies: ~/.claude/skills and
  ~/.agents/skills, architect and builder)
- Current: heading matches `final` anywhere; verdict matches `accepted` anywhere (case-insensitive).
- Proposed: heading must read "Audit (final..." or "Final audit"; verdict reads its leading word
  (ACCEPTED or DEFECTS), else uppercase-only ACCEPTED/DEFECTS.
- Evidence: `program` shows frontend and release "final audit ACCEPTED"; both wrong.

## Kept as project notes (no skill change)
- Backend 13.2-13.8 and frontend 12.1-12.2 are open now. Under the new bar most are P2/P3 at POC:
  a change session in each part can move them to Later (user's call).
- WPS Office COM quirks, the Chrome lockfile and CRLF patching: environment, already in AGENTS.md.
