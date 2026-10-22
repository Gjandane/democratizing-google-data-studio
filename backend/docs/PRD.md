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
   (goal 9); model routing (planner `gemini-4-argon` for blueprint and designer;
   `gemini-3.8-flash` for the rest).
5. History: every build keeps its versions; a new version starts from the latest spec.

6. Required: style/recreate reference extraction and data reconciliation, with evidence-backed
   feasibility gates at blueprint, prototype, recipe and execution (dashboard-intent.md 1.2).

8. Staged workflow (change 2026-10-21): four confirmed OKF artifacts (context, outline, design,
   blueprint) per ../contracts/api.md 2.0; a reusable profile script; design-time theme presets.

7. Screenshot-only builds: schema/row-count/seed driven Python CSV generation, exposed as a
   reusable function/CLI and API; typed BigQuery intake, visible synthetic provenance.

9. Designed pages (change 2026-10-22, user): the planner, guided by a dashboard-design skill,
   writes each page's background HTML/CSS (header, titles, cards, icons) around one empty slot
   per spec component, and picks the page width (1200-1920). Code sanitizes it, measures the
   slots in Chromium to place the native Data Studio components, screenshots the rest as the
   background, and falls back to the code layout and kit per page. Target look:
   docs/change-2026-10-22-reference.webp.

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
- Deadline 2026-10-23 01:05 MPST (moved 2026-10-20) (whole program); flow 1 ready for integration by about 14:00 on
  2026-10-19, cloud mode by about 18:00 (docs/program.md roadmap).
- Python 3.12 + uv on Windows 11; Gemini API key; one GCP project with BigQuery; ADC login.
- Contracts: ../contracts/api.md, ../contracts/recipe.md, ../contracts/conventions.md.

## Success criteria
- `uv run pytest` passes offline (fake LLM, fake BigQuery, fake engine).
- Live: with the sample CSV and real Gemini/BigQuery, scripted artifact picks reach a multi-page
  prototype whose every component passes validation, and `DSS_ENGINE_DRY_RUN=1` reaches `done`;
  the two-source GPS-style fixture reaches a blueprint with a union and a flagged ratio KPI.

## Decided by default
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

## Open questions
- none

## Later
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
  retain the existing limits (P3/P2 respectively, audit 2026-10-21).
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
