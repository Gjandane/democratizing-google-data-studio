# Contract: dashboard references and feasibility
Version 1.3 (2026-10-28, change reference analysis gate, user request; backend 25.11 block): a
recreate upload no longer extracts observations. A Flash analysis returns a `ReferenceAnalysis`
(each visible item proposed as a native Data Studio component or static art) that the user
approves or edits before any blueprint work (Reference analysis and approval). Approved native
items replace image observations as requirement records; static items are consented art, never
issues. Style mode has no analysis (`null`). New: `ReferenceSet.analysis`, `PUT
reference-images/analysis`, `POST reference-images/analysis/approve`, errors
`409 reference_unapproved` and `409 reference_analysis_conflict`; Assessment, Issue and decision
shapes unchanged. Fixtures: `reference_set.json` (approved), new `reference_set.pending.json`.
Version 1.2 (2026-10-21, change staged workflow): requirements come from structured artifacts
instead of free-text chat (Feasibility assessment); the stages and actions of api.md 2.0 replace
`interview` and `plan`. Where older text below says interview it means the context, outline and
design stages; plan, replan and direct plan mean `blueprint/accept` (and `blueprint/regenerate`);
ready_for_plan means an assessment `ready` at `blueprint/accept`. Assessment, Issue and decision
shapes are unchanged; the fixtures stay valid.
Version 1.1 (2026-10-19). Change: explicit synthetic-data fallback for screenshot-only builds;
original reference/feasibility rules retained. Version 1.0 was the initial planned contract. Provider: backend. Consumers: frontend, release.
2026-10-20 (no version change, shapes unchanged): example fixtures added for alternatives,
pending comments and a stale assessment; implementation task IDs follow frontend's split.
Status: backend 11.1-11.8 (task split 2026-10-20) and frontend 10.1-10.3 (split 2026-10-20).
API transport: contracts/api.md 2.0 (3.2 for the 1.3 additions). Recipe transport stays at 1.0.
Shared fixtures: contracts/fixtures/dashboard-intent/{reference_set,feasibility}.json, plus the
Assessment variants feasibility.alternatives.json (blocked, alternatives offered),
feasibility.pending.json (a blocked comment batch in pending_comments) and feasibility.stale.json.
Keep them separate from the pre-1.3 fixture inventory; new conformance tests explicitly load them.

## Scope
- Both reference modes and capability verification are required for this release (user decision
  2026-10-19). `style` borrows visual treatment; `recreate` reproduces the closest supported
  structure, chart choices and treatment using connected data. Never promise pixel identity.
- A screenshot supplies design evidence, never the underlying dataset. Displayed values, labels
  and formulas are untrusted observations. Without data, offer explicit synthetic generation per
  synthetic-data.md: propose schema/assumptions and generate sample rows after user selection;
  never claim those rows or definitions were recovered from the screenshot. This resolves
  needs_data only after intake; it does not override capability limits.
- Only the existing recipe/engine feature surface is eligible. Community visualizations,
  embedded applications, animation and a new GPS map engine are outside this change.

## Reference set
One active reference set per build version; uploading replaces the set atomically after successful
extraction. Failure keeps the old set and prototype. `style`: 1-3 PNG/JPEG; `recreate`: exactly one
PNG/JPEG (one dashboard page); maximum 5 MiB per file and 15 MiB total. Enforce streaming byte
limits, MIME/extension/signature agreement and successful image decode; maximum 20 million pixels
per image. Use existing Playwright Chromium to decode/measure if no approved image library exists.
No new dependency is assumed. Animated/unsupported/corrupt content rejects with `422 invalid_source`;
oversize bytes use `413`. Image text cannot authorize actions or override capability rules.

`POST reference-images`: multipart `files`, `mode=style|recreate`, `instructions` (0-2000 chars).
Allowed only in connect, context, outline, design, blueprint or prototype with no active action
on the build. Files get
server-generated plain names `reference_<id>.png|jpg` in the current version folder. Retain original
bytes for review through the existing authenticated files endpoint; never place them in recipes,
backgrounds, global memory or logs. Persist safe descriptors and extraction in `references.json`,
and an OKF `reference.md` summary; keep `style.md` for existing style consumers.

`GET reference-images` returns `ReferenceSet|null`:
```text
ReferenceSet = { id: string, mode: "style"|"recreate", instructions: string,
  images: [{id: string, name: string, file: string}], summary: string,
  analysis: ReferenceAnalysis|null /* 1.3: recreate only; null in style mode and for a recreate
  set saved before 1.3 */ }
ReferenceAnalysis = { revision: int /* 1 = as analyzed; +1 on every saved edit */,
  state: "pending"|"approved",
  summary: string /* code-written from the items, e.g. "2 charts and 1 control can be native
  Data Studio components; 4 items stay static art." */,
  items: ReferenceItem[] /* 1-24, in reading order */,
  note: string /* the user's note to the planner, 0-1000 chars */,
  allowed_types: string[] /* catalog types a native item may use: the registry narrowed by
  DSS_ALLOWED_TYPES (recipe.md 1.3 type names) */,
  issues: ValidationIssue[] /* code checks, paths into the analysis (`/items/<i>/type`);
  approve needs [] */ }
ReferenceItem = { id: string /* r1, r2 ... stable for this analysis */,
  label: string /* 1-120 chars, what the image shows, e.g. "Yearly access bar chart" */,
  kind: "chart"|"control"|"kpi"|"text"|"image"|"legend"|"other",
  box: {x: number, y: number, w: number, h: number} /* 0..1 of the image */,
  disposition: "native"|"static", type: string|null /* an allowed_types entry when native,
  null when static */,
  shows: string /* 0-300 chars: measures, dimensions and grain as read from the image, e.g.
  "access % by year, 2000-2019"; display text, never a field binding */,
  reason: string /* 0-300 chars: why native or static */,
  proposed: {disposition: "native"|"static", type: string|null} /* the analysis' own choice,
  read-only, so a client can show what the user changed */ }
```
Names are display strings, never paths. URLs for previews use the existing files endpoint.
No raw model output is exposed. `DELETE reference-images` clears the current set, reference.md,
and reference-owned style.md and bytes. This changes future intent, not the already saved spec.
Replacing/deleting invalidates feasibility and marks any existing prototype stale (see assessment).
Replanning is explicit. During build/done, mutations return `409 wrong_stage`; use New version
from done. New version copies reference bytes and the analysis with its state and revision,
but clears assessment IDs and recomputes feasibility before compiling or executing. Durable
requirement-scoped choices carry over only if still valid under the copied inputs/evidence.
Past versions keep their own set. No retention cleanup beyond version deletion is added in this POC.

### Reference analysis and approval (1.3)
- A recreate upload's run (node `reference_extract`, stage `reference_interpretation`) sends the
  image, the instructions and the allowed catalog types to the model and commits the set with a
  `pending` analysis, revision 1. Code validates every item (box inside the image, a native
  item's type in `allowed_types`, a control type only for a control, lengths); one validation
  repair; an answer that still fails fails the upload (old set kept). A screenshot with more than
  24 items fails with a request to crop. A style upload commits `analysis: null`.
- `PUT reference-images/analysis` `{revision, items: [{id, disposition, type}], note}` saves the
  user's split: every item id exactly once, `type` null for static; code fills `issues` (a native
  item needs a type from `allowed_types`) and returns the ReferenceSet with `revision` + 1 and
  `state` `pending`. Labels, boxes, `shows` and `proposed` are read-only. A `revision` other than
  the current one -> `409 reference_analysis_conflict` (`detail.revision`: the current one).
- `POST reference-images/analysis/approve` `{revision}` -> `200 ReferenceSet`, `state`
  `approved`; needs `issues` [] (else `409 artifact_invalid`) and the current revision (else
  `409 reference_analysis_conflict`). Zero native items is a valid approval (all static art).
  Approving the same revision again returns the same set.
- Both are code-only (no run), allowed in connect to prototype under the per-build action lock,
  and `409 wrong_stage` in build/done. Saving an edit to an approved analysis is a reference
  change: the analysis returns to `pending`, the assessment goes `stale`, a saved Blueprint goes
  `stale` and an existing prototype is marked stale, as replacing the set does.
- Gate: while the current set is recreate and its analysis is not `approved` (pending, or `null`
  for a pre-1.3 set: re-upload to analyze), `design/confirm`, `blueprint/regenerate`,
  `blueprint/accept`, recipe and run answer `409 reference_unapproved` (`detail.reference_set_id`).
  Style sets, builds without a set, and a pre-2.0 build's recipe/run are not gated.
- The approved analysis is the reference's only structural input downstream: the blueprint
  planner and the design brief get the image plus the approved items and note (backend
  architecture.md). A native item is fulfilled by a Blueprint row that names it
  (`BlueprintRow.reference_item`, api.md 3.2) with the item's type; a static item is drawn as
  background art and never becomes a component or an issue.

Legacy `POST style-images` remains a style-mode replacement alias with the same validation and
lifecycle once backend 11.2 lands. Its request and 202 response stay compatible.

## Capability evidence
The backend owns a versioned, curated capability registry. Each record has a stable id, supported
feature/value combinations, prerequisites, scope (`native_product`, `app`, `data`), evidence
links or recipe/engine test paths, and a verification date. Cover every current recipe type,
option and style key, supported geographic granularity, controls, page/layout limits, interaction,
animation and refresh requests. Product limits and engine limits are separate fields.
Treat an option with no implementation evidence as unavailable in this app, even if recipe JSON
accepts it. `DSS_ALLOWED_TYPES` narrows the registry; it cannot add capabilities.

No runtime web search is required. Refresh evidence deliberately in a planning/build review.
Unknown, missing or contradictory evidence cannot yield `supported`. A model's assertion is not
evidence. Native product exclusions require official documentation; documentation silence means
unknown native support. An app exclusion can independently block the request.

## Feasibility assessment
Requirement records come from (1.2): each selected outline question and the blueprint row that
answers it (structured, no text extraction), the confirmed context's KPI definitions, the Design's
choices, normalized outline `other` text, the approved analysis' native items (1.3: replaces
image observations; static items are not requirements) and pending comments. Only `other`
text and comments go through model extraction. Normalize them into
stable requirement records; preserve requested behavior (not just the eventual chart type).
Match against capabilities, connected schema, metric definitions and compiler/engine coverage.
Code owns the final classification and checks. A model may extract requirements or suggest a
mapping, but cannot grant support, accept an alternative or silently drop a requirement.

`GET feasibility` returns `Assessment` (a new/legacy version starts `unchecked`):
```text
Assessment = { id: string|null, state: "unchecked"|"blocked"|"ready"|"stale",
  input_digest: string|null, prototype_stale: boolean, issues: Issue[],
  pending_comments: {id: string, comments: [{component_id: string, text: string}]}|null }
Issue = { id: string, requirement: string,
  status: "unsupported_product"|"unsupported_app"|"needs_data"|"needs_clarification"|"unknown",
  reason: string, evidence: string[], alternatives: [{id: string, label: string}],
  resolution: "unresolved"|"accepted_alternative"|"dropped" }
```
Full requirement-to-capability and requirement-to-component/mapping evidence is persisted internally
and summarized in OKF `feasibility.md`; the UI response is the blocking-issue projection.
`ready` requires every active requirement resolved and every proposed alternative rechecked.
`unchecked` and `stale` are never permission to build.

`POST feasibility/check` (empty body) starts bounded assessment and returns `202 {run_id}`,
using capability_check and existing run events. This is the recovery action for unchecked/legacy
builds. Allowed in connect, context, outline, design, blueprint and prototype, under the per-build
action lock. It never creates SQL, renders or launches the engine. Blueprint, outline `other`,
reference and comment actions also refresh assessment.
GET never launches model work. A stale prototype may be replanned/reapplied once intent issues
are resolved; `prototype_stale` blocks recipe/run, not the action that repairs it.

Persist a blocked ordered comment batch as `pending_comments`, including target IDs; GET returns
it on reload. `POST feasibility/reapply` accepts `{assessment_id,batch_id}` and returns
`202 {run_id}` through the ordinary revise branch; current IDs and resolved intent are required.
`DELETE feasibility/pending-comments` accepts query `assessment_id` and returns the refreshed
Assessment (200); stale IDs reject. Abandoning removes only that batch's requirements/decisions
and clears its stale reason, without touching other reference/intent issues or changing the spec.
A different posted comment batch replaces the pending batch and invalidates its decisions.

`POST feasibility/decisions`: `{assessment_id, decisions:[{issue_id,
action:"accept_alternative"|"drop", alternative_id:string|null}]}`; 1-20 distinct issues.
Accept requires an offered alternative id; drop requires null. The exact current assessment id is
mandatory; stale IDs get `409 feasibility_stale`. Apply atomically, record explicit user choices,
recompute and return the Assessment (200). Ambiguities requiring new data or text are answered
through a context edit, outline `other` text or new data (1.2). The server never treats silence or elapsed time as consent.
Decisions do not launch planning, SQL, rendering or builds.

For any change to user intent, references, connected schema, spec, capabilities or allowed types,
recompute before the next dependent operation. Assessment IDs expire on input/decision changes.
Durable choices bind to requirement id + requested meaning + chosen alternative/definition +
its data prerequisites and evidence, independently of the assessment ID. Normal generated spec
changes revalidate these choices and preserve them if unchanged and still supported; a new
request, changed mapping or invalid prerequisite requires a new choice. A registry update alone
revalidates support, never automatically repeats a still-valid approval. Digest includes normalized requirements, reference
set/extraction, schema/definitions, spec when present, registry version/content and allowed types.
Serialize with the existing per-build action lock; no check/use gap when committing an artifact.

## Enforcement
- Blueprint (1.2): code checks every blueprint row against the registry, catalog limits, field
  roles and the confirmed definitions; a row that fails after its one repair becomes an Issue
  with code-built alternatives where any exist (for a ratio Kpi: its numerator and denominator as
  separate metrics). Outline `other` text that asks for unsupported behavior is explained in an
  assistant message at once and kept as a requirement. `blueprint/accept` needs `ready`.
- Reference items (1.3): an approved native item with no ok row that names it with its type
  after the one row repair becomes an Issue (`needs_clarification`) whose alternatives are only
  ones code can build and recheck; `drop` on it records the user's choice to keep that item as
  static art. Code never moves an item between native and static by itself.
- `blueprint/accept` also assesses before creating any BigQuery view. The Generate shortcut
  cannot bypass this rule. Preflight blocks perform no view writes. After preflight succeeds, use
  a new run-specific candidate view for spec/render validation; later failure deletes only that
  candidate and preserves the previous spec/prototype/view. Commit the successful candidate
  reference atomically with the spec/artifacts; never replace a view used by an older report.
  On a block, preserve artifacts and stay in `blueprint`.
- Validate a generated/revised spec against normalized requirements AND the registry before
  publishing a prototype. An allowed geo_map with `animate=true` is rejected, not silently stripped.
- Comments: assess the requested behavior before patching. A blocked batch leaves the entire spec
  and recipe unchanged and records issues; resolving issues does not secretly apply comments.
  Reapplying the same batch uses its confirmed decisions; changed text invalidates them.
- Recipe and run endpoints recheck the current spec and assessment before compile/queue/subprocess.
  Changed references or unresolved comments block running an old prototype. Reference changes need
  explicit replan; comment changes need successful reapply. Empty revisions may clear staleness
  only when code verifies the confirmed intent is already satisfied.
- Synchronous blocks: `409 feasibility_blocked`, detail `{assessment_id, issue_ids}`. Asynchronous
  blocks use run.finished error plus a persisted assistant explanation; existing stage rollback
  applies. UI refetches feasibility after run.finished, docs.updated, reconnect and successful
  decisions. No new SSE payload keys or Build fields.

## Required oracle cases
1. A supported bar with real field bindings is ready and still compiles to recipe 1.0.
2. "Animate GPS points along a route" blocks as unsupported_app with no model/renderer-only
   animation accepted. Never say all Data Studio extensions are incapable. A country aggregate
   map or time series is offered only if its data requirements and engine evidence pass.
3. A feature supported by Data Studio but not the engine says unsupported_app, not unsupported_product.
4. Unknown feature or unreadable screenshot asks for clarification; no invented support or data.
5. "Revenue" with both gross_sales and net_sales needs a definition; a confirmed mapping preserves
   aggregation, unit and date grain. A missing latitude field is needs_data, not product impossibility.
6. Unsupported requirement in an otherwise supported request, image or comment cannot disappear.
7. Stale assessment submissions reject; accept -> replan/reapply -> changed spec -> recipe/run
   preserves unchanged authorized intent after deterministic revalidation; changed prerequisites block.
8. Direct plan/recipe/run calls, new versions and changed DSS_ALLOWED_TYPES enforce the same gates.
9. Failed extraction/revision preserves previous bytes and artifacts; successful replacement/removal
   survives reload, marks stale, and cannot accidentally build the old interpretation.
10. Untouched legacy build -> Check feasibility -> ready; reference replacement -> check ->
    replan; blocked comments -> choose -> reload -> reapply; abandon discards only that batch.
11. Spec/renderer failure after candidate-view creation leaves the previous view/spec/preview
    usable; cleanup never drops an earlier report's view. No new view on a preflight refusal.
12. (1.3) Recreate upload -> pending analysis; design/confirm, blueprint and recipe/run refuse
    with `reference_unapproved` until approve; an edit after approval re-gates and marks the
    Blueprint/prototype stale; a stale revision gets `reference_analysis_conflict`; a native item
    with a type outside `allowed_types` is an issue that blocks approve; static items never
    appear as issues or components; style mode is never gated.

## Sources checked 2026-10-19
- https://docs.cloud.google.com/data-studio/google-maps-reference : documented native map types
  and field restrictions; no documented temporal point-playback control was found. This is not
  proof that custom visualizations cannot animate.
- https://developers.google.com/data-studio/visualization : custom JavaScript/CSS visualizations
  are supported through the community visualization extension surface.
- contracts/recipe.md 1.0: current engine interface only offers country/region/city geo_map
  granularity and no animation/temporal playback op. Engine task/evidence is also required before
  claiming a supported alternative can actually be automated.
