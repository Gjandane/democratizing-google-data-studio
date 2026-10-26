# Proposed change: resolve the resumed 24.11 fidelity block

Date: 2026-10-26. Status: NOT SELECTED for implementation first. The user chose HIGH thinking
for both reference stages and a comparison first; canonical docs and task 24.11 carry that ruling.
The independently reviewed four-task proposal below is retained as historical, unapplied material.
Target: existing backend POC. The original proposal below did not change canonical task markers.
This is a design change inside the backend, with no new dependency or public contract shape.

## Evidence and disposition

Source: `.blueprint/qa/task-24.11/RESUMED.md`, recreate run
`20261026-102359-9b37ee47`, style runs `20261026-102804-06417f5d` and
`20261026-103415-5f9a001d`. Preserve these evidence trees and original hashes.

- All four resumed synthetic intakes passed. No intake runtime fix is proposed.
- Recreate published three designed pages with empty publish coverage errors, but four
  page-1 areas repeat the same all-country urban/rural bindings. Distinct exact country-title
  properties claim distinct slots in both Blueprint and publication coverage. The approved
  one-chart substitution therefore needs explicit shared-title semantics, not another live retry.
- The access title is `have access to electricity (%)`: 2011 was removed and the unit retained.
  Extraction omitted `worldwide`; adding that word is not an existing title-normalization rule.
  Correct the fixture oracle to the actual supported rule; do not invent geographic wording.
- The clipped 252 x 64 total-people scorecard already has `compact_numbers: true`. The preview
  ignores that option and prints the full value with two decimals. Its font depends only on height.
- The yearly DATE field has code-owned `date_granularity: year` in the saved spec. The preview
  prints ISO category strings instead of using that metadata, and numeric y-axis labels crowd.
- Style's repaired 564 px slots really violate the 568 px minimum; preserve that rejection.
  A separate structural interaction is indicated by the source: measurement and final rendering
  enlarge the designer root to include the code-owned footer, stretching flex columns into it.
  Reproduce this interaction offline before changing the shared wrapper. It is not established
  by an executed reproduction in this architect session.

## Proposed decisions (defaults pending approval)

1. Use an explicit `shared chart <name>` modifier on existing reference definition clauses.
   Do not infer grouping merely because two observations use the same fields or formulas.
   Reason: distinct titles currently represent distinct requirements, and equivalent formulas
   alone do not establish an instruction to combine panels. For the approved electricity
   substitution, append `, shared chart Urban vs rural access` to each of the four country
   definitions. All existing formulas, fields, grain, unit, image and synthetic data stay fixed.
   This deliberately changes INSTRUCTIONS hashes; retain old inputs and record both versions.
   The existing reference.instructions string carries the modifier; no API/schema field is added.
2. Keep the natural content height separate from the outer page host and synthetic footer in
   measurement, preview and background capture. No relaxed collision checks or min-size tolerance.
3. Honor the already accepted compact-number setting, and use validated field-grain metadata for
   yearly preview labels. Formatting affects display only. Actual report rendering remains a
   release integration check; no claim of engine screenshot parity is made here.
4. Title acceptance checks the normalized extracted label plus evidenced unit, with no
   unenforced fixed period. `worldwide` is optional when absent from extraction. Every other
   fidelity requirement, native-chart rule, cap, deadline and visual STOP remains.

## Architecture additions to apply after approval

### Shared recreate substitutions

- Problem/objective: several explicitly substituted image observations can require one native
  chart, yet their raw label properties currently force separate components. Prove all those
  observations against exactly one component on their reference page without erasing provenance.
- Inputs: active recreate instructions, image observations, confirmed KPIs, schema/projection
  proof, effective mappings/needs/properties, rows, decisions and reference/source identities.
  Output: existing assessment/spec/recipe shapes, with a private recomputed shared-chart proof.
- Extend the existing definition surface with optional final `, shared chart <name>`. The name
  is nonempty, fits the current one-line label limit including a possible unit suffix, and has no
  clause delimiter or comma. It is a user-authored display name and group identity, compared
  after trimming/case normalization, not a chart id or model-generated authorization.
- Only active, affirmative, wholly parsed definitions authorize sharing. Every participating
  observation must be identified by its own existing matching label and explicit shared name.
  Model suggestions, image text, equal field names, notes alone and leftover cached proof do not.
  Ungrouped observations retain their current exact-title behavior.
- A group must have a complete, consistent effective chart type, ordered metric/aggregation
  bindings, dimensions, date field/grain, units, options and non-label properties. Preserve all
  ordinary capability, source, grain, page and recipe checks. Missing/conflicting members or
  incompatible definitions remain actionable issues; never pick an arbitrary winner or union
  incompatible meanings. A conflicting separate confirmed question/KPI must not be removed.
- For this explicitly shared meaning only, use its authored shared title (plus the existing
  evidenced-unit normalizer) in place of competing raw observed label properties. Retain each
  original observation, label, instruction provenance and decision independently. Publish each
  member's binding to the same native component id; the brief report includes member aliases.
- One shared rule must serve planner observation export, Blueprint simulated coverage, repair
  feedback, completion, accepted-spec titling, publication, recipe/run and revision coverage.
  Give the existing row repair one group requirement. Completion adds at most one group row
  when none fulfils it; it never adds one row per alias. More than one matching reference-page
  component is an unresolved cardinality issue, not successful shared coverage. Do not silently
  delete planner rows; the sole existing repair can resolve duplicates, otherwise acceptance blocks.
  Distinct valid analysis on later pages survives and cannot satisfy the page-1 group.
- Removing/changing instructions/reference or a member's evidence recomputes authorization.
  Reload, redraft and version copy retain valid bindings but never stale group proof. No new
  calls/repairs/queries, public fields or budgets. The 24-observation/24-clause <=100 ms oracle holds.
- Oracle: sanitized reconstruction of the saved resumed run retains four distinct country
  labels. With explicit shared modifiers one area row binds all four; without them distinct
  titles retain old behavior. Vary each semantic/provenance input independently and require
  refusal of unsafe sharing. Duplicate page-1 rows block after one failed repair. Accept,
  reload, revision and recipe/run use identical proof; the fake engine reaches done.

### Synthetic design content and footer geometry

- Keep the designer's natural content extent distinct from the final outer page height that
  includes the synthetic footer and bottom margin. Use the same code-owned host/content rule
  for Chromium measurement, prototype HTML and decoration-only background capture.
- Persist any necessary code-owned content geometry inside the existing sanitized design HTML,
  rather than introducing a public field or asking the model to supply trusted measurements.
  Revalidate after normalization; never hide overflow, clip offending elements or ignore empty
  containers to make collision checks pass. Revisions recompute the geometry rather than reuse
  a stale height. Existing published specs must render safely or fail through the existing
  validation path; no forced replan, destructive rewrite or extra model call on GET.
- Synthetic page 1 still has one code-drawn 64 px footer, existing grid/margin placement and
  maximum height. Text, slots, art and all relevant element rectangles still cannot enter it.
  Descendant percentages, flex/grid stretch, absolute children, later pages and revision are
  explicit edge cases. Non-synthetic wrapping and no-reference model requests/routing/fallback
  stay unchanged. A synthetic no-reference page uses the same corrected structural wrapper;
  this limited output-markup change supersedes earlier blanket byte-identity requirements.
- Brief/HTML facts and repair errors keep the actual measured width/minima authoritative.
  Explain content-vs-footer height and CSS border/padding arithmetic compactly in the existing
  reference prompts/skills, only after reproducing the retained failures. A real 564 px slot
  still fails a 568 px requirement. No layout solver, arbitrary CSS rewrite or extra retry.
- Oracle: reproduce the saved flex footer failure and test an independently built equivalent
  flex layout and grid/percentage/absolute variants. Passing layouts have identical slot boxes
  in measurement and final preview/background geometry within the existing tolerance. A real
  footer intrusion, undersized slot, overflow or over-height page still fails. Reference repair
  failure preserves prior publications and pending comments. Existing budgets remain.

### Readable native preview formatting

- Honor `scorecard.options.compact_numbers`. When true, abbreviate magnitude with K/M/B/T,
  round to at most two decimals and remove trailing zeros; carry rounding across suffix
  boundaries, preserve sign and zero, and retain the exact numeric value in the existing
  accessible data summary. Null stays No data. Font fitting must not go below 16 px; legitimate
  tested values must fit the accepted box. When false/absent preserve the existing format.
- Feed code-owned `DataField.date_granularity` into chart display formatting. Only proven year
  grain displays a DATE category as YYYY. Do not infer grain from a field named year, Jan-1
  samples or model prose; other grains/unknown metadata retain their current labels. Aggregates,
  date values, grouping, ordering and exact data summary values remain unchanged.
- Fit numeric tick labels and tick density to the available Cartesian plot, using compact
  magnitude labels where needed, readable fonts and enough distinct ticks to understand scale.
  No overlapping tick labels, clipped values or hidden data marks in the saved accepted boxes.
  Preserve full values in data summaries/tooltips. Components remain code-rendered native slots.
- No compiler/schema/recipe changes, new model calls, dependencies or queries. Recipe bytes for
  an unchanged spec stay identical. Other deferred preview option support stays in PRD Later;
  only compact scorecards and the evidenced date/numeric-label defects enter this change.
- Oracle: independent expected numeric strings (including negative/zero/null/rounding boundaries),
  proven-year vs ordinary DATE labels, unchanged aggregate inputs and compiled bytes. Render
  the saved 252 x 64 compact scorecard and yearly chart boxes in Chromium, inspect value and
  tick extents and screenshots, and verify no clipping/overlap at the accepted font/box sizes.
  The existing <=15 s renderer budget remains; no live model needed for these regressions.

## Proposed task sequence

Rework the blocked, unfinished 24.11; do not change completed task IDs. Move its original
verification obligations and retained evidence to 24.14. No marker changes before approval.

### 24.11 Honor explicitly shared recreate substitutions — M

- Depends on: 24.10. Spec: architecture.md#Shared recreate substitutions.
- Files: src/dss/spec/requirements.py, src/dss/spec/feasibility.py,
  src/dss/harness/nodes/blueprint.py, src/dss/harness/nodes/reference_brief.py,
  skills/blueprint.md, tests/test_blueprint.py, tests/test_feasibility.py,
  tests/test_render.py, tests/test_revise.py, tests/test_reference_brief.py,
  tests/data/recreate_shared_chart.json, .blueprint/qa/task-24.11/shared-chart/.
- Done when: offline saved-run regression fails before and passes after; all group/provenance,
  conflict, duplicate, page, removal/reload/version/revision and <=100 ms cases above pass.
  Every approved alias binds to one component in spec and compiled native recipe; fake engine
  done. Ungrouped recreate fixtures and style/data/none fingerprints remain unchanged.
  `uv run pytest tests/test_blueprint.py tests/test_feasibility.py tests/test_render.py tests/test_revise.py tests/test_reference_brief.py tests/test_compiler.py tests/test_api_contract.py tests/test_recipe_contract.py`
  and `uv run pytest` pass. No live generation in this task.
- Review focus: api.md 2.0/dashboard-intent.md 1.2/recipe.md 1.3 unchanged shapes; explicit
  instruction evidence is the only sharing authorization; no implicit observation drops.

### 24.12 Separate designed content from the synthetic footer — M

- Depends on: 24.11. Spec: architecture.md#Synthetic design content and footer geometry.
- Files: src/dss/render/design_page.py, src/dss/render/prototype.py,
  src/dss/harness/nodes/designer.py, src/dss/harness/nodes/reference_brief.py,
  src/dss/harness/context.py, prompts/v1/reference_brief.md, prompts/v1/reference_html.md,
  skills/reference-design.md, skills/dashboard-design.md, tests/test_design_page.py,
  tests/test_designer.py, tests/test_reference_brief.py, tests/test_context.py,
  tests/test_render.py, tests/test_revise.py, tests/test_synthetic_label.py,
  tests/data/reference_design/layouts/, .blueprint/qa/task-24.12/.
- Done when: save sanitized immutable failed drafts and hashes, reproduce the source-indicated
  stretch defect, and pass the independent host/geometry/security cases above. Saved style
  slot minima violations remain failures; a corrected fixture passes without any relaxed rule.
  Inspect Chromium geometry and screenshots for flex/grid/absolute/percentage cases, synthetic
  and non-synthetic pages, later pages and a revision. No-reference request/routing/fallback
  fingerprints and compiler bytes unchanged; list only intended synthetic wrapper markup diffs.
  `uv run pytest tests/test_design_page.py tests/test_designer.py tests/test_reference_brief.py tests/test_context.py tests/test_render.py tests/test_revise.py tests/test_synthetic_label.py tests/test_api_contract.py tests/test_recipe_contract.py`
  and `uv run pytest` pass. No live generation; if the saved interaction cannot be reproduced,
  stop for an architect ruling rather than changing the validator speculatively.
- Review focus: api.md 2.0 Prototype HTML and synthetic-data.md 1.2 provenance protection;
  measurement, preview and captured backgrounds share one geometry rule, with no gate relaxation.

### 24.13 Honor compact scorecards and readable yearly preview axes — M

- Depends on: 24.12. Spec: architecture.md#Readable native preview formatting.
- Files: src/dss/render/prototype.py, tests/test_render.py,
  tests/data/reference_design/preview/, .blueprint/qa/task-24.13/.
- Done when: independent numeric/year/negative metadata cases, exact-data preservation and
  unchanged compiled-byte cases above pass; use the saved clipped scorecard/yearly bar and
  area boxes with synthetic aggregates, recording Chromium fit extents and screenshots. Show
  compact false/absent still uses the previous format. Prove non-overlapping ticks and <=15 s
  12-component render/background oracle without model calls. `uv run pytest tests/test_render.py tests/test_compiler.py tests/test_recipe_contract.py`
  and `uv run pytest` pass.
- Review focus: existing recipe.md 1.3 compact_numbers and DataField grain metadata; display
  formatting cannot change data, units, aggregations or accepted bindings. Engine parity remains
  a release check, and other deferred preview options are not part of this task.

### 24.14 Verify and approve corrected two-stage reference fidelity — M, supervised

- Depends on: 24.13. Spec: architecture.md#Reference HTML composition plus the three new sections.
- Files: tests/live/test_reference_design.py, tests/data/reference_design/,
  .blueprint/qa/task-24.14/, docs/progress.md.
- Carry forward every original 24.11 intake diagnostic/sanitization/prerequisite, exact fixture
  provenance, accepted substitution, budget, no-fallback, later-page/revision/style/none,
  compiled recipe/dry-engine and evidence obligation. Preserve the 24.9/24.10/24.11 trees.
  Source data remains labelled synthetic; full report integration belongs to release.
- Before the first new live run, add only the approved shared-chart modifier to the four
  definition clauses, record old/new full input hashes and provenance, and correct the access
  title oracle to the supported normalization rule. Collect all title/structure/fit results
  before asserting, so one failure cannot obscure the rest of a published candidate.
- A fresh bounded check is authorized only after 24.11-24.13 pass. Prior runs remain failures;
  they do not become successes or an excuse for more retries. Preserve one transient retry then
  block; deterministic coverage/title/geometry regressions block without a bypassing rerun.
- STOP: reference and successful recreate prototype side by side; identify every native slot,
  exactly one page-1 shared area bound to four aliases, every approved unsupported substitution,
  readable scorecard/yearly axes, globe placement/scale and all later-page/revision evidence.
  User approves fidelity or identifies remaining differences. Tests never grant approval.
- Done when: real configured planner/worker, same image/CSV/schema, dry engine; every original
  live acceptance condition plus new grouping/fit oracles passes with no reference fallback.
  Recreate, later-page/revision, style and none all have stage/model/image/token/time and
  publication evidence under existing caps. `uv run pytest -m live tests/live/test_reference_design.py`,
  `uv run pytest tests/test_reference_brief.py tests/test_designer.py tests/test_render.py tests/test_revise.py`
  and `uv run pytest` pass, then user grants the STOP.
- Review focus: native chart/control marks, no fake background charts, no implicit drops,
  no cap/deadline/contract changes and no automatic visual acceptance.

## Canonical documentation updates after approval

- PRD: record these explicit defaults under Decided by default; remove only compact scorecards
  from the deferred preview-options item, retaining its other options. Correct current live
  gate references to 24.14; historical task entries remain historical.
- Architecture: insert the three sections above, cross-reference them from observation
  completion/title rules, Designed pages, Prototype renderer and Reference HTML composition;
  append a decision row with rejected alternatives and evidence. State the explicit narrow
  supersession of synthetic-wrapper byte-identity and raw alias-title requirements.
- Essentials: summarize explicit sharing, footer host geometry and metadata-driven preview
  formatting alongside their budgets; stamp in the same session.
- Plan: rewrite blocked 24.11 and append 24.12-24.14. Reopen through blueprint.py only after
  approval, set audit result, stamp and lint. Add a Change progress entry settling the prior
  blocked question and recording review findings/decisions. Folder mode: no commit.
- AGENTS.md: no rule change needed. No new dependency; retain existing verified rows. No
  new package lookup or product/live test run is claimed by this architect proposal.
- Roadmap: finish backend implementation and 24.14 visual approval, then backend final re-audit;
  release integration resumes at the program root only after backend acceptance.

## Review and checks

- Fresh-context read-only blueprint_reviewer delta audit: **No findings**. The reviewer read
  the affected docs/source and saved screenshots. No implementation, tests or live services ran.
- Canonical plan lint: **85 tasks, 0 errors, 16 existing size warnings**. This checks the
  unchanged canonical plan, not an applied version of the proposed task definitions. Run stamp
  and lint again after applying the approved proposal to the canonical files.
- Existing dependency approvals are retained; no new dependency or registry lookup is needed
  for the proposal. No current product-test or fidelity pass is claimed. Prior recorded runs
  remain historical. Task 24.11 stays blocked until approval and script-controlled reopening.
