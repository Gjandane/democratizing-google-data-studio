# PRD: backend
Target: POC · Written 2026-10-18 · Kind: a part of a program (../docs/program.md)

## Problem
Turning a dataset and a vague goal into a good Data Studio dashboard needs an analyst's interview,
a designer's layout and hours of clicking. The backend is the agent harness that does the first
two with as few tokens as possible, and hands a compiled recipe to the engine for the clicking.

## Users
- frontend: calls the REST API and listens to the build's SSE stream (../contracts/api.md).
- the demo user, through the frontend: connects data, confirms the context, picks questions and
  a design, accepts the blueprint, comments, builds (change staged workflow 2026-10-21).

## Goals
1. Flow 1 end to end: CSV/GCS/BigQuery -> context -> outline -> design -> blueprint (feasibility)
   -> code-laid-out Dashboard Spec -> HTML prototype + background PNGs (1-5 pages) -> comments
   revise the spec -> recipe -> engine run -> link (change staged workflow 2026-10-21).
2. The harness from ../harness-architecture.md: procedural memory (skill files), semantic memory
   (OKF bundle, no vector store), episodic memory (SQLite + FTS5), consolidation every 5 chats by
   the worker model, guardrails at every loop exit, exactly one trace per run.
3. Graph engineering with Google ADK 2.0 Workflow: LLM nodes and code nodes, an action router,
   a validate-and-repair loop.
4. Token economy: code computes and writes; the LLM fills structured judgment fields from compact
   profiles and upstream artifacts (never rows or chat history); artifacts, spec layout, HTML,
   background, SQL view and recipe are deterministic code, except the designed page layer
   (goal 9); model routing (planner `gemini-4-argon` for blueprint, no-reference designer and
   reference design briefs; worker `gemini-3.8-flash` for reference HTML and the rest).
5. History: every build keeps its versions; a new version starts from the latest spec.

6. Required: style/recreate reference extraction and data reconciliation, with evidence-backed
   feasibility gates at blueprint, prototype, recipe and execution (dashboard-intent.md 1.2).

8. Staged workflow (change 2026-10-21): four confirmed OKF artifacts (context, outline, design,
   blueprint) per ../contracts/api.md 2.0; a reusable profile script; design-time theme presets.

7. Screenshot-only builds: schema/row-count/seed driven Python CSV generation, exposed as a
   reusable function/CLI and API; typed BigQuery intake, visible synthetic provenance.

9. Designed pages (change 2026-10-22, user; reference route revised 2026-10-25): without a
   reference, the planner, guided by a dashboard-design skill,
   writes each page's background HTML/CSS (header, titles, cards, icons) around one empty slot
   per spec component, and picks the page width (1200-1920; the prompt asks 1200 because the
   Data Studio editor zooms wider canvases, 20.5). Code sanitizes it, measures the
   slots in Chromium to place the native Data Studio components, screenshots the rest as the
   background, and falls back to the code layout and kit per page. Target look:
   docs/change-2026-10-22-reference.webp. With a reference, feasibility and the accepted native
   components precede an Argon visual brief, then Flash writes the sanitized background HTML.
   Recreate aims for the closest supported Data Studio structure; style borrows treatment only.
   Unsupported elements require the existing explicit decisions, never fake charts in the background.

## Non-goals
- No user identities, accounts or multi-user isolation (POC, one shared access code).
- No vector store or embeddings (OKF navigation + FTS5 instead).
- No Data Studio calculated fields or blends: derived fields and joins live in the BigQuery view.
- No LLM-generated recipe text, and no LLM HTML outside the sanitized designed page layer
  (goal 9; lifted for that layer by change 2026-10-22). Components, charts and their data stay
  native Data Studio objects drawn by code.
- No Dockerfile or deploy script here (the release part owns them); no engine in the cloud.
- No accounts: one shared access code, not users.
- No LangGraph (ADK 2.0 Workflow only).
- No CI; tests cover the core flow and the contracts only.

- No pixel-identical screenshot clone, claimed recovery of original rows, new chart engine, custom community
  visualization or animation in the reference/capability change.

## Core flows
1. Create build -> upload CSV -> intake loads it to BigQuery and writes `data-profile.md`.
2. Context: notes -> worker drafts KPIs, derived fields, thresholds, glossary from the profile ->
   code validates -> user edits and confirms. Outline: one proposal -> user ticks, adds other
   text, asks for more -> confirms. Design: preset prefill -> user edits -> confirms.
3. Blueprint: planner maps questions to components -> code feasibility + view dry run (one repair
   each) -> user resolves issues -> accept -> code layout -> validate -> render prototype +
   backgrounds -> stage `prototype`.
4. Comments: N comments -> worker writes a JSON patch for the named ids -> validate -> re-render
   -> `prototype.updated`.
5. Build: compile recipe -> run `dsengine` -> relay events -> `build.finished` with the link ->
   stage `done` -> consolidation check.
6. History: `POST /versions` copies the latest spec into v<n+1> -> stage `prototype`.
7. Cloud mode (change 2026-10-19): the same app on Cloud Run: serves the built frontend, `$PORT`,
   shared access code, SQLite on local disk with a backup on the `/data` GCS volume, and agent
   mode, where `dss-agent` on the user's machine runs the engine for the hosted app.

## Features
| Must | Should | Won't (this version) |
|---|---|---|
| API per ../contracts/api.md (except stretch routes) | consolidation into data/knowledge/user | vector store |
| intake: CSV upload, GCS CSV, BigQuery tables; profile | UX audit node (ux-audit skill) | engine on Cloud Run |
| context, outline, blueprint, layout, revise, render, compile, execute, publish nodes; theme kit; reference modes, feasibility, synthetic data | (style-from-picture now in reference modes) | LLM-judge release gate automation |
| episodic memory, context assembly, traces | research mode (google_search, capped) | multi-user; LLM-written charts or component HTML |
| 4 archetype skills, 12-type catalog in OKF | LLM-judge eval script | |
| cloud mode, access code, agent mode + `dss-agent` | | |
| | live token totals on the event stream (`run.usage`, change 2026-10-19) | |

## Constraints
- Deadline no longer binding (user, 2026-10-23; program guide). Earlier October milestones
  are historical; the POC scope and final closure gates control the remaining work.
- Python 3.12 + uv on Windows 11; Gemini API key; one GCP project with BigQuery; ADC login.
- Contracts: ../contracts/api.md, ../contracts/recipe.md, ../contracts/conventions.md.

## Success criteria
- `uv run pytest` passes offline (fake LLM, fake BigQuery, fake engine).
- Live: with the sample CSV and real Gemini/BigQuery, scripted artifact picks reach a multi-page
  prototype whose every component passes validation, and `DSS_ENGINE_DRY_RUN=1` reaches `done`;
  the two-source GPS-style fixture reaches a blueprint with a union and a flagged ratio KPI.

## Decided by default
- Final closure decision 2026-10-27 (explicit user answer): use a 250 ms warm-run
  acceptance limit for the existing deterministic feasibility speed checks, and report
  first/cold timings separately. This supersedes the earlier 100 ms acceptance requirement;
  it does not relax any fixture size, correctness, binding, purity or invalidation check.
  The recorded 25.9 failure remains evidence, not a reason for another optimization campaign.
  Task 25.9 now needs the test acceptance updated and the complete offline suite verified.
- Change 2026-10-27 (25.9 block): preserve the existing explicit-decision rule for every
  originally unlabeled recreate field control, including model-filled and persisted mappings;
  restore the unchanged speed oracle with operation-local allowlist reuse. One M offline task
  groups the fixes because they share requirements.py and the blocked acceptance prerequisite.
  The approved footer implementation is documented and retained. No product scope, dependency,
  interface, model default or cap changes. User answer: keep native_planning at 1,200 s and,
  after the repairs, permit one new live acceptance campaign under the existing stop rules.
- Change 2026-10-26 (configurable model stages, architect defaults after the user ended the
  interview; source: user "stop the questioning ... proceed", backend/docs/HANDOFF-stage-settings.md):
  interview = context and outline nodes, routine = every other non-generation model node; both
  expose model, thinking and the 30 s request timeout only, because their nodes have different
  token caps and the user did not authorize blanket budget changes. Analysis stages keep their
  current transport retry (1) and repair counts (interpretation 0, native planning 1 row repair;
  the view SQL repair stays fixed at 1). Retry waits continue doubling past 2 s (4 s ...) when a
  count above 2 is chosen. The count margin is per generation profile. One global
  `fallback_model`; interview/routine keep only the listing-based swap. Unknown model ids are
  rejected against a code-owned capability table. Legacy planner/worker values seed only the
  stages whose role did not change. A paused brief review blocks other mutating build actions
  until approved or cancelled. No-reference pages keep a code-layout fallback behind
  `layout_fallback` (narrowed below); the label
  is shown in the app, not drawn into the Data Studio report. Interview's free-text input stays
  removed (api 2.0). Contracts: api.md 3.0, conventions.md 1.4. Superseding parts of this entry
  (user cards 2026-10-26, after the delta audits): the standard layout applies only when completed
  HTML still fails validation after its repairs (timeouts, model and brief failures stop); the
  migration keeps every explicit legacy model value (env only when it differs from the shipped
  default) on every stage its role served, and an unknown legacy id is kept and listed as a
  Settings issue (unknown ids are still rejected on PUT); cost estimates are in scope (user request), from verified backend prices, labeled
  estimated, per call, run and build; no budgets, alerts or billing data.
- Change 2026-10-26 (explicit user decision; superseded by the configurable-model-stages entry
  above: HIGH stays the default, caps/deadlines now come from stage profiles, the trial ran in
  blocked 24.11 and live verification moved to 25.7): enable HIGH thinking for both reference-generation
  stages, Argon's visual brief and Flash 3.8's HTML, and test that change first in task 24.11.
  Keep the current prompt/brief surface, fixtures, native slots, renderers, guards, model routes,
  caps, deadlines and retry limits for this comparison. The proposed shared-chart/footer/preview
  changes in docs/change-24.11-fidelity.md were not selected for implementation first. No-reference
  designer thinking stays LOW. A HIGH trial is evidence, not automatic fidelity acceptance.
- Change 2026-10-26 (24.9 block): repair planner-only recreate year buckets in code only when
  the actual projected source's aggregate profile proves the base DATE already supplies that
  grain, and each use has explicit date/grain intent or is a selected native date-axis slot
  with a complete recognized truncation. Undeclared aliases still need explicit intent.
  This is typed reconstruction, not general SQL simplification or field-name inference.
  Keep the confirmed-KPI gate and give the existing
  row repair exact missing/conflicting measures; an unresolved KPI still blocks. Reason:
  both saved runs failed before design, and the second also omitted a named q4 measure.
  No extra calls, budget, dependency, drop decision or public contract. Fix task 24.9 precedes
  live/visual task 24.10, which retains the user's original approval STOP.
- Change 2026-10-25 (24.8 block, user choices): reference HTML generation keeps its 12k
  input limit; its one repair may use 24k input, counted with the same conservative allowance.
  Remove duplicate representations first, retaining all authoritative facts. Output stays 16k
  including thinking; the whole HTML stage stays 600 s, with one validation repair. With
  designed pages enabled, a reference page that still fails stops acceptance and preserves
  existing artifacts; it cannot publish a standard-kit substitute. Revision failures retain
  existing artifacts and pending comments. No-reference fallback stays unchanged. These are
  explicit user decisions; implementation is 24.8 and live/visual acceptance is now 24.10.
- Change 2026-10-25: user keeps native Data Studio charts, allows HTML generation longer than
  five minutes (reported a roughly three-minute Flash 3.8 experiment), and chooses supplied
  reference/bundled assets first, with no new internet research. Default: 600 s per page's Flash
  stage, including counting, transport retry and its one HTML repair; reason: room beyond the
  observed three minutes, with a finite failure bound. Argon brief stage remains 120 s; output
  caps remain 16k for HTML, with a new 4k brief cap, both including thinking. No-reference
  requests stay identical. Reuse compatible pieces of the saved 24.5 work, inspected and
  applied only inside backend; no unconditional whole-stash restore. These defaults preserve
  existing API/recipe contracts and the required visual approval STOP.
- Change staged workflow 2026-10-21 (user choices in ../docs/program.md decision log): the
  defaults below about the interview and conversational definitions are superseded. New
  defaults: profile value lists for <= 20 distinct values; at most 15 KPIs/derived fields/
  thresholds, 24 selected questions, 12 rows per page, 5 pages; one repair per model node; the
  live two-source check uses a small backend-owned GPS-style fixture modelled on the user's
  activity_summary/route_speeding_events schema (the real files are not in the repo); builds
  made before the change keep their spec and re-plan from context.
- Change 2026-10-21 (release retry): explicit metric definitions apply to later compatible
  requests with provenance; ordinary blue-theme/accent wording permits choosing a supported
  blue shade. Reason: these are existing interview/style goals, and requiring special formula
  punctuation or hex-only user wording breaks the core flow. Unsupported behavior still blocks.
- Change 2026-10-21: ordinary audience context is retained without requiring a capability;
  incomplete or unsupported requirements keep the interview open for clarification while
  readiness and downstream work remain gated. This repairs the release 2.2 blocker under the
  existing interview/feasibility goals; no fixed answer count or capability bypass is introduced.
- Interview runs one LLM turn per user message (stateless run per request) rather than a
  long-lived human-input node: simpler with REST; the episodic store holds the chat.
- Graph: one ADK Workflow with an action router (interview_turn, plan, revise, build, audit,
  style, research, references, feasibility check, synthetic proposal/generate) so the whole harness is one graph for the slides.
- Consolidation N = 5 chats (a chat = one build reaching `done`), global (one local user).
- Episodic retrieval: current build's last 12 messages + FTS5 top 3 from other builds.
- Loop limits: at most 6 tool calls per LLM node turn; at most 2 spec repair loops.
- Background PNG and prototype screenshot use Playwright's bundled Chromium (headless), separate
  from the engine's Chrome.

- Reference/capability change 2026-10-19 defaults: one recreation screenshot or 1-3 style
  images per version; explicit substitutions, curated capability evidence, existing dependencies.
  Closest supported recreation and release priority are user decisions, not defaults.
- Designed pages change 2026-10-22 (user choices: planner-written page HTML with measured slots,
  page regenerated on geometry/heading comments, width 1200-1920, vendored Lucide icons with
  LLM-drawn SVG as fallback, deadline not a constraint). Defaults: designer on by default with a
  backend config flag to turn it off (no new env name or API setting); page 1 is designed first and sets the width and shared CSS, later
  pages reuse them; one repair per page, then the code layout and kit for that page; the
  design HTML lives in the spec, so versions and reloads reproduce it without a model call.

- Synthetic-data defaults (change 2026-10-19): 1,000 rows, seed 42; bounded stdlib generators;
  local DSS_DATA_DIR or existing GCS-backed /data volume; one new synthetic dataset in an empty
  build, no mixing with real data. User requested schema/count parameterization and sample CSVs.

## Accepted configuration change (2026-10-26)
- The user closed the runtime-assumptions interview after answer 30 and directs necessary
  planning updates plus a frontend-task re-audit, with a fresh-context handoff. Preserve
  existing behavior for unasked hypotheticals; ask only for a real break or material ambiguity.
  Detailed decisions: [change-runtime-assumptions-interview.md](change-runtime-assumptions-interview.md).
  Continuation: [HANDOFF-stage-settings.md](HANDOFF-stage-settings.md).
  Answer 1: app Settings with separate defaults per stage (A).
  Answer 2: Flash HTML generation/repair output defaults to 65,536 tokens per call including
  thinking, adjustable in Settings (A).
  Answer 3: Argon reference-brief output defaults to 32,768 tokens per call including HIGH
  thinking, adjustable in Settings (A).
  Answer 4: remove the brief's fixed prose-character ceilings and 6,000-character target;
  retain output-token bounds and structured/content validation (A).
  Answer 5: Flash reference-HTML input defaults to 131,072 tokens per call across initial,
  later-page, repair and revision paths, adjustable in Settings (A).
  Answer 6: Argon reference-brief input defaults to 131,072 tokens per initial/later-page/
  revision call, adjustable in Settings (A).
  Answer 7: keep conservative counting (maximum of text estimate and provider count plus
  20% plus 512), with the 20% margin adjustable in Advanced Settings (A). Show measured
  versus enforced counts separately.
  Answer 8: when mandatory input exceeds its configured cap, stop before generation and
  show stage/count/limit; user adjusts Settings and retries (A). No automatic cap expansion
  or loss of required context.
  Answer 9: independent thinking-level selectors for the reference brief and HTML stages,
  both defaulting to HIGH and offering model-supported levels (A).
  Answer 10: independent reference-brief and reference-HTML model selectors, defaulting to
  Argon and Flash 3.8 respectively (A).
  Answer 11: explicitly configured fallback model is Gemini 3.8 Flash (B); clearly identify
  actual use and avoid a duplicate fallback when primary is already Flash. Trigger/time
  policies are refined below.
  Answer 12: fallback triggers on model unavailability/overload/eligible provider errors
  after allowed retries (A). Content/truncation/layout failures follow their own repair
  policy.
  Answer 13: reference-brief stage defaults to 600 seconds per page, adjustable in Settings,
  shared across counting/generation/retries/fallback (A).
  Answer 14: reference-HTML stage defaults to 1,200 seconds per page, adjustable in Settings,
  shared across counting/generation/retries/measurement/repair/fallback (A).
  Answer 15: reference HTML defaults to two automatic validation repairs after initial
  generation (three generation attempts total/page), adjustable in Settings, within the
  existing selected 20-minute allowance and validity gates (A).
  Answer 16: reference brief defaults to one automatic validation repair before HTML starts,
  adjustable in Settings, sharing the 10-minute stage allowance (A).
  Answer 17: output-token cutoff stops either reference stage, showing stage/cap/available
  usage and retaining old published artifacts for manual adjustment/retry (A). No automatic
  continuation, regeneration, model fallback or thinking downgrade for token cutoff.
  Answer 18: reference-stage generation transport defaults to two retries, with 1 s then 2 s
  delay, count adjustable per stage in Settings (A). Eligible errors remain 429/500/503
  before any response, within the stage's time allowance; fallback considered afterward.
  Answer 19: save Argon's brief as readable Markdown alongside canonical validated JSON,
  per page/version, viewable/downloadable (A).
  Answer 20: automatic HTML handoff by default, with a Settings option to pause per page
  for brief review/edit/approval (A). Edits retain validation and authoritative native bindings;
  this does not replace final fidelity approval.
  Answer 21: also expose an independent configurable "HTML without a reference" profile
  (yes/A, user explicitly reiterated configurability).
  Answer 22: its token defaults match reference HTML (131,072 input / 65,536 output including
  thinking), stored/editable independently (A).
  Answer 23: Flash 3.8 for no-reference HTML execution (B). Expanded user direction: model
  selection at every LLM stage including interview; defaults Flash 3.8 for interview and HTML
  execution, Argon for dashboard analysis and a fully detailed HTML brief, Flash 3.8 LOW for
  routine model work. Preserve existing approved reference-stage HIGH. This does not add
  LLMs to deterministic steps.
  Answer 24: use Argon briefing followed by Flash HTML execution even without a reference
  image, reusing the configured brief stage and preserving independently editable no-reference
  execution settings (A).
  Answer 25: reference interpretation and native chart/metric/data planning default to Argon
  HIGH, independently configurable per stage (A).
  Answer 26: both analytical stages default to 131,072 input / 32,768 output including
  thinking, independently stored/editable per stage (A).
  Answer 27: each Argon analysis stage defaults to 600 seconds total for its action,
  independently adjustable, sharing count/generation/retry/repair/fallback time (A).
  Answer 28: no-reference Flash HTML execution also defaults to HIGH, independently
  configurable; routine Flash work remains LOW (A).
  Answer 29: no-reference execution also starts with 1,200 s total/page, two validation
  repairs and two eligible transport retries with 1 s/2 s waits, stored/editable independently
  of reference execution (A).
  Answer 30: automatic standard-layout fallback after no-reference HTML exhausts layout
  validation repairs, clearly labeled and with a Settings enable/disable switch (A).

## Open questions
- Visual fidelity approval is the STOP in 26.6 (replaces 25.11, change 2026-10-28: reference
  analysis gate; user request and cards). No other planning question is open.

## Later
- Date-grain parity: feasibility can read component options while the compiler derives
  date_granularity from datasource-field proof; KPI grain inheritance is time_series-specific,
  and two TRUNC parsers remain (P2/P3, tasks 23.1/24.1; audit 2026-10-27).
- Legacy builds/brief projection: recreate builds published before 24.10 need re-acceptance
  for corrected placement/titles; reference_brief.report omits confirmed KPIs from
  observation_meaning and supplies every decision to every page (P2/P3, tasks 24.5/24.10;
  audit 2026-10-27).
- Observation completion uses note text to identify code-added rows, pruning can leave
  derived fields, and a missing `using` field reports clarification rather than missing data
  (P3, task 24.7; audit 2026-10-27).
- Art tags have no per-page count cap; list/dropdown null display differs; procedural design
  and extraction guidance lag the added native list/chart types (P3, tasks 24.1/24.4;
  audit 2026-10-27).
- Test/diagnostic precision: some older background/recipe/style tests use reconstructed or
  empty inputs; count-refusal arithmetic can describe pre-merge totals; stale 32,768 and
  Settings 3.0 text remains (P3, tasks 23.2/24.3/25.7; audit 2026-10-27).
- Existing 25.8 Left open items: generic one-clause ownership after a spec-mismatch
  revalidation cycle (P3), and timing coverage with 16 accepted bindings rather than the
  current one accepted binding (P3). Keep the existing timing workload in 25.9; the live
  harness explicitly blocks a second observation taking Region Selector across assessments
  (change 2026-10-27, carried forward; no extra task).
- Outline Other text may lose behavior: empty extraction adds no blocking record, and tagged
  records skip needs_clarification and fulfillment coverage in favor of structured questions.
  This user-approved 15.11 tradeoff conflicts with dashboard-intent.md's full preservation
  guarantee; reconcile at the program root before claiming conformance (P2, audit 2026-10-21).
- Image Blueprint rows cannot carry image_path and fail layout despite an ok row verdict;
  refine the catalog/planner surface before offering those rows (P2, task 15.8; audit 2026-10-21).
- Stale extra background_p<n>.png files remain after replanning to fewer pages; removal prose
  is narrow, recreated IDs can collide with old removal intent, and a requirement bound to
  both a removed and retained item can still fail coverage (P3, task 15.9; audit 2026-10-21).
- Layout title-width estimates duplicate kit widths, wrap conservatively, and omit control-row
  question refs from the coverage oracle (P3, task 15.8; audit 2026-10-21).
- Five large staged builds can exceed consolidation's input budget and drop the oldest build;
  per-run live checks do not independently assert output budgets or absence of row literals
  (P3, tasks 15.10-15.11; audit 2026-10-21).
- Count scorecards show decimal places and ratio alternatives can duplicate existing KPI tiles
  (P3, task 15.11; audit 2026-10-21).
- After a crash and database-backup loss, candidate metadata reconciliation restores stage/spec
  metadata without fully reconstructing artifact flags; the recovered build can need restaging
  within the documented crash write-loss allowance (P2, audit 2026-10-21).
- Definition-recompute timing and screenshot capture can fail intermittently: one 105.47 ms
  result against 100 ms and one 20 s document-load timeout during the audit both passed an
  unchanged isolated rerun and other serial suites. Causes/reliability rates are unconfirmed;
  the final 2026-10-27 user decision supersedes the timing gate with 250 ms warm and separate
  first/cold reporting; the screenshot limit stays (P3/P2 respectively, audit 2026-10-21,
  updated audit 2026-10-27).
- One view per page for unjoinable sources (spec, recipe and engine change) (change staged
  workflow 2026-10-21).
- Document upload as context input (change staged workflow 2026-10-21).
- Cloud SQL/Firestore for episodic memory, more than one instance (change 2026-10-19).
- Automated Eval -> Gate -> Release loop with versioned prompts (plan).
- Data Studio calculated fields when a view can't express them (plan).
- Bound/compact the consolidated user index before it outgrows mandatory context; currently a
  long-running installation can fail consolidation while retaining its counter (audit 2026-10-19).
- Verify Windows idle Ctrl+C responsiveness; an in-flight agent long poll can delay it up to
  25 seconds (audit 2026-10-19, not yet measured).
- Live smoke checks for optional consolidation, UX audit and judge schemas remain unrun;
  offline checks pass. Main planner and reference vision flows pass live, but reference
  extraction intermittently rejects invalid observations: both audits saw an initial failure
  followed by an unchanged isolated rerun pass. No reliability rate established; one-call
  guardrail remains intact (P2, audit/re-audit 2026-10-20).
- Consolidate/judge retries do not have their own retry-listener binding; failed model events
  can lose reported usage because the event error is raised before token accounting. Successful
  judge responses do retain usage (runtime probe 5 input/2 output), superseding earlier progress
  claims that every such trace is zero (audit 2026-10-20; optional observability refinement).
- On filesystems without hard links, the local generator's no-replace fallback has a race with
  a concurrent output writer; ordinary pre-existing outputs are refused. Duplicate JSON-key
  errors identify the key but not its full nesting path (audit 2026-10-20).
- Windows 8.3 aliases of local reference assets are not explicitly denied; case-collision
  packaging on a case-sensitive filesystem remains untested here (audit 2026-10-20).
- Prototype preview ignores some supported chart options (bar orientation/stacking, pie donut,
  compact scorecards, table rows_per_page, pivot row/column assignments); the compiled report
  honors them (P2, was task 13.4; change 2026-10-20).
- Token budgets trust the folded count; live evidence 8,245 folded vs 8,695 billed input tokens,
  so a request near a node budget can exceed it (P2, was task 13.8; change 2026-10-20).
- A copy, capture or commit failure during POST /versions strands the next version folder and
  every retry returns 422; the normal path works (P2, was task 13.5; change 2026-10-20).
- An explicit feasibility check can report ready again after execution refused a supported but
  unfulfilled requirement; execution still refuses (P2, was task 13.7; change 2026-10-20).
- Huge integers (e.g. 10**400) in synthetic numeric bounds or choices raise OverflowError: the
  API returns 500 instead of 422 (P2, was task 13.6; change 2026-10-20).
- Live generated labels can retain stray punctuation; an unavailable requested font (observed:
  Inter) uses the browser fallback. Refine label copy and deterministic font fallback later
  (P3, audit re-audit 2026-10-20); measured headings still fit prototype and background.
- Screenshot-only live planning can exhaust two spec repairs after heading-fit rejection and
  safely return `invalid_request` without publishing. An unchanged fresh rerun passed; the
  original input is unavailable and the cause unconfirmed. First-attempt success is not
  guaranteed (P2, audit re-audit 2026-10-20).
- The designer schema accepts canvas widths up to 1920 while the engine misplaces components
  above ~1380 px; only the prompt asks 1200. Clamp in code or fix the engine at the program
  root (P2, audit 2026-10-23; designer.py FirstPage).
- Live `test_staged_flow_sample_csv` is stale since designed pages became default: page 1 has a
  `design` decoration, not band/panel/title, so its decoration comment step raises
  StopIteration (tests/live/test_staged_flow.py:250); the flow itself reaches prototype
  (P3, audit 2026-10-23).
- A comment on a component (not on `p<n>_design`) asking for an icon or card color gets no
  redesign route (P2, 20.4 left open; audit 2026-10-23).
- Coverage proves heading text in `design.html` by substring ("Sales" matches "Sales
  Overview"); non-comment rows lose component ids absent from the spec at every merge, also
  before a spec exists; `observed_labels` guards (strict subset, validate failure) are untested;
  the Blueprint doc keeps planner titles while the prototype shows observed ones; same-metric
  observations are titled first come first served (P3, 21.1 left open; audit 2026-10-23).
- Designed-page sanitizer/measure gaps: non-slot elements outside the page give no error; a root
  `display:none/contents` reports 0x0 slots without the cause; `layout.minimum_box` duplicates
  `design_page.minimum`; the 2x background fallback is not re-checked against the 2 MB limit;
  code-laid specs validate at widths 1201-1920; the revision repair turn carries two HTML copies
  (P3, 20.1/20.2/20.4 left open; audit 2026-10-23).
- Smaller open items: Extracted.component_ids > 24 untested against the live Gemini schema;
  staged 13-row/6-page negatives stop at evaluate; a legit quoted list label is cut to its first
  fragment; an instruction naming a missing field reports needs_clarification, not needs_data;
  two KPIs with the same measure count as one match; the prototype still renders scorecard
  colors (dead path); an empty page-1 name fails compile (P3, 16.1-19.4 left open; audit
  2026-10-23).
- Engine-side: the s021/s025 time_series "Too Many Rows" timeout cascade on the b_a8ace098d03b
  replay, and canvas placement above ~1380 px (program root; audit 2026-10-23).
- Blueprint observation check (22.1): its titling mirror walks rows in row order and skips accept's
  `after < before` recheck, so rows competing for one title on a multi-page Blueprint could
  disagree with accept; the fallback gap text names a title claim when an op, option or label
  failed; a gap with no nearest row marks no row blocked (accept still blocks) (P3; re-audit
  2026-10-23).
- Release 2.6 weaknesses (change 2026-10-29, deferred; ../docs/acceptance.md, build
  b_236ae4aa34ee): W5 static legends from the approved split (rural/urban, map scale) missing
  from background_p1; W6 page-1 reference HTML failed validation 3x on the first prototype run
  (trace r_2051c7758120; retry passed); W7 the KPI caption is missing and two scorecards not in
  the reference are added on page 1. W4 (contract, recipe 1.4): emit `date_granularity` on a
  `bar` over a DATE bucket column once the engine applies it (yearly bar s015 labels
  "Jan 1, 2000" and folds groups past 10 into "Others").
