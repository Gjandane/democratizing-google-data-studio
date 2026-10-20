# Contract: dashboard references and feasibility
Version 1.1 (2026-10-19). Change: explicit synthetic-data fallback for screenshot-only builds;
original reference/feasibility rules retained. Version 1.0 was the initial planned contract. Provider: backend. Consumers: frontend, release.
2026-10-20 (no version change, shapes unchanged): example fixtures added for alternatives,
pending comments and a stale assessment; implementation task IDs follow frontend's split.
Status: backend 11.1-11.8 (task split 2026-10-20) and frontend 10.1-10.3 (split 2026-10-20).
API transport: contracts/api.md 1.5. Recipe transport stays at 1.0.
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
Allowed only in connect, interview or prototype with no active action on the build. Files get
server-generated plain names `reference_<id>.png|jpg` in the current version folder. Retain original
bytes for review through the existing authenticated files endpoint; never place them in recipes,
backgrounds, global memory or logs. Persist safe descriptors and extraction in `references.json`,
and an OKF `reference.md` summary; keep `style.md` for existing style consumers.

`GET reference-images` returns `ReferenceSet|null`:
```text
ReferenceSet = { id: string, mode: "style"|"recreate", instructions: string,
  images: [{id: string, name: string, file: string}], summary: string }
```
Names are display strings, never paths. URLs for previews use the existing files endpoint.
No raw model output is exposed. `DELETE reference-images` clears the current set, reference.md,
and reference-owned style.md and bytes. This changes future intent, not the already saved spec.
Replacing/deleting invalidates feasibility and marks any existing prototype stale (see assessment).
Replanning is explicit. During plan/build/done, mutations return `409 wrong_stage`; use New version
from done. New version copies reference bytes, extracted observations and confirmed mappings,
but clears assessment IDs and recomputes feasibility before compiling or executing. Durable
requirement-scoped choices carry over only if still valid under the copied inputs/evidence.
Past versions keep their own set. No retention cleanup beyond version deletion is added in this POC.

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
Normalize explicit user requirements from messages, image observations and pending comments into
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
builds. Allowed in connect/interview/prototype, under the per-build action lock. It never creates
SQL, renders or launches the engine. Interview/reference/comment actions also refresh assessment.
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
through the existing data/interview flow. The server never treats silence or elapsed time as consent.
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
- Interview: explain unsupported requests immediately, give a supported alternative if any, and
  ask about ambiguous mappings. Do not signal ready_for_plan while active issues are unresolved.
- Direct plan calls also assess before creating any BigQuery view. The Generate shortcut
  cannot bypass this rule. Preflight blocks perform no view writes. After preflight succeeds, use
  a new run-specific candidate view for spec/render validation; later failure deletes only that
  candidate and preserves the previous spec/prototype/view. Commit the successful candidate
  reference atomically with the spec/artifacts; never replace a view used by an older report.
  On a block, preserve artifacts and return to interview.
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

## Sources checked 2026-10-19
- https://docs.cloud.google.com/data-studio/google-maps-reference : documented native map types
  and field restrictions; no documented temporal point-playback control was found. This is not
  proof that custom visualizations cannot animate.
- https://developers.google.com/data-studio/visualization : custom JavaScript/CSS visualizations
  are supported through the community visualization extension surface.
- contracts/recipe.md 1.0: current engine interface only offers country/region/city geo_map
  granularity and no animation/temporal playback op. Engine task/evidence is also required before
  claiming a supported alternative can actually be automated.
