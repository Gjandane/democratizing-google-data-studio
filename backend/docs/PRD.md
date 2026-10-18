# PRD: backend
Target: POC · Written 2026-10-18 · Kind: a part of a program (../docs/program.md)

## Problem
Turning a dataset and a vague goal into a good Data Studio dashboard needs an analyst's interview,
a designer's layout and hours of clicking. The backend is the agent harness that does the first
two with as few tokens as possible, and hands a compiled recipe to the engine for the clicking.

## Users
- frontend: calls the REST API and listens to the build's SSE stream (../contracts/api.md).
- the demo user, through the frontend: connects data, answers the interview, comments, builds.

## Goals
1. Flow 1 end to end: CSV/GCS/BigQuery -> interview -> OKF build docs -> Dashboard Spec -> HTML
   prototype + background PNG -> comments revise the spec -> recipe -> engine run -> link.
2. The harness from ../harness-architecture.md: procedural memory (skill files), semantic memory
   (OKF bundle, no vector store), episodic memory (SQLite + FTS5), consolidation every 5 chats by
   the worker model, guardrails at every loop exit, exactly one trace per run.
3. Graph engineering with Google ADK 2.0 Workflow: LLM nodes and code nodes, an action router,
   a validate-and-repair loop.
4. Token economy: the LLM only writes OKF docs and a compact spec or spec patch; HTML, background,
   SQL view and recipe are deterministic code; model routing (planner `gemini-4-argon` only for
   plan and spec; `gemini-3.8-flash` for the rest).
5. History: every build keeps its versions; a new version starts from the latest spec.

## Non-goals
- No auth, accounts or multi-user (POC, one local user).
- No vector store or embeddings (OKF navigation + FTS5 instead).
- No Data Studio calculated fields or blends: derived fields and joins live in the BigQuery view.
- No LLM-generated HTML or recipe text (deterministic renderers only).
- No Dockerfile or deploy script here (the release part owns them); no engine in the cloud.
- No accounts: one shared access code, not users.
- No LangGraph (ADK 2.0 Workflow only).
- No CI; tests cover the core flow and the contracts only.

## Core flows
1. Create build -> upload CSV -> intake loads it to BigQuery and writes `data-profile.md`.
2. Interview: start -> assistant asks one question at a time (worker model, interview skill +
   archetype skill) -> user answers -> ... -> the assistant says it has enough and suggests "Generate".
3. Plan: planner writes OKF build docs -> BigQuery view created (dry-run validated) -> planner
   writes the spec -> validator (repair loop, at most 2) -> render prototype + background ->
   stage `prototype`.
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
| interview, plan, spec, revise, render, compile, execute, publish nodes | style-from-picture node (vision) | LLM-judge release gate automation |
| episodic memory, context assembly, traces | research mode (google_search, capped) | multi-user |
| 4 archetype skills, 12-type catalog in OKF | LLM-judge eval script | |
| cloud mode, access code, agent mode + `dss-agent` | | |

## Constraints
- Deadline 2026-10-20 01:05 MPST (whole program); flow 1 ready for integration by about 14:00 on
  2026-10-19, cloud mode by about 18:00 (docs/program.md roadmap).
- Python 3.12 + uv on Windows 11; Gemini API key; one GCP project with BigQuery; ADC login.
- Contracts: ../contracts/api.md, ../contracts/recipe.md, ../contracts/conventions.md.

## Success criteria
- `uv run pytest` passes offline (fake LLM, fake BigQuery, fake engine).
- Live: with the sample CSV and real Gemini/BigQuery, a scripted interview reaches a prototype
  whose every component passes validation, and `DSS_ENGINE_DRY_RUN=1` reaches `done`.

## Decided by default
- Interview runs one LLM turn per user message (stateless run per request) rather than a
  long-lived human-input node: simpler with REST; the episodic store holds the chat.
- Graph: one ADK Workflow with an action router (interview_turn, plan, revise, build, audit,
  style, research) so the whole harness is one graph for the slides.
- Consolidation N = 5 chats (a chat = one build reaching `done`), global (one local user).
- Episodic retrieval: current build's last 12 messages + FTS5 top 3 from other builds.
- Loop limits: at most 6 tool calls per LLM node turn; at most 2 spec repair loops.
- Background PNG and prototype screenshot use Playwright's bundled Chromium (headless), separate
  from the engine's Chrome.

## Open questions
- none

## Later
- Cloud SQL/Firestore for episodic memory, more than one instance (change 2026-10-19).
- Automated Eval -> Gate -> Release loop with versioned prompts (plan).
- Data Studio calculated fields when a view can't express them (plan).
