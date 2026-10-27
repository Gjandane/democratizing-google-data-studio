<!-- essentials-of: docs/architecture.md sha256:4cf1670af09f (regenerate this page when architecture.md changes, then run stamp) -->
# Architecture essentials: backend
docs/architecture.md wins.

## Stack
- Python 3.12/uv; FastAPI/uvicorn (no reload), SSE; ADK 2.x Workflow/LlmAgent; Gemini models
  per stage from Settings (api.md 3.1; defaults Argon for analysis and briefs, Flash 3.8 for
  interview, routine and HTML; architecture.md#Stage settings).
  SQLite/FTS5; BigQuery/ADC; Playwright Chromium; httpx. Cloud: one instance, local dss-agent.

## Folder map
```text
src/dss/        api/, agent/, artifacts/, harness/, memory/, data/, spec/, render/, recipe/, ops/
skills/         procedural memory; prompts/v1/ system prompts
knowledge/      OKF seed: catalog/, archetypes/, datastudio/, themes/, index.md, log.md
tests/          offline fakes; tests/live/ marked live
```

## Conventions
- Vocabulary: ../harness-architecture.md. One action = one Workflow = one trace.
- api.md 2.0: connect -> context -> outline -> design -> blueprint -> prototype. Code profiles,
  validates, lays out 1-5 pages, writes files. Models return validated JSON from compact
  profiles/frontmatter, never rows/history; repair limits, budgets: architecture.md#Working memory assembly.
- Artifact edits stale downstream work; confirm preserves edits. Atomic OKF writes emit updates;
  question IDs never recycle; dry runs establish types. Only consolidate writes semantic memory
  (git knowledge = seed); OKF needs `type`, folder index/log. Config: ../.env + settings.
- Engine argument list/cwd, whole-tree cleanup; Playwright sync in a worker thread. Provider:
  response_json_schema, guarded raw output, sanitized errors. Every model node runs from its
  stage profile snapshot (#Stage execution): one total clock per action/page for generation
  stages, retries only on 429/500/503 before a response (1 s, 2 s, 4 s), Flash fallback on
  availability/provider failure, hard stops on overflow/cutoff, one StageCall per request.
  Interview/routine keep per-node caps and a 30 s request timeout. Shutdown cancels active work.
- Types: `DSS_ALLOWED_TYPES`; sort `{field, order}`. COUNT variants allow dimensions; dropdown
  uses one dimension. Chart colors override theme (no scorecards); accents affect only their target.
- Cloud: SPA/$PORT, code cookie/header, fail-closed startup; backup API every 30 s when dirty;
  agent token, 60 s retry. Run recompiles the current spec; dev routes need DSS_DEV=1.
- Accept publishes its candidate view/spec/artifacts atomically; never clean a published view.
  Backgrounds: background.write_pages per page, 3x, <2 MB.
- Designed pages: Argon brief (html_brief) -> Flash HTML (reference_html or html_no_reference),
  with or without a reference image (#Design briefs). Brief prose uncapped; brief JSON + Markdown
  saved per page/version; optional per-page review gate outside every clock. Count images;
  budgets, clocks and repair counts come from the profiles. Repair deduplicates facts/current
  HTML, retains intent/images. Chromium measures slots -> `box`; width 1200 (> ~1380 misplaces).
  Reference failure stops publication and preserves prior artifacts; no-reference uses the
  labeled standard layout only with `layout_fallback` and never for overflow/cutoff/cancel.
  No structural fidelity proposal (docs/change-24.11-fidelity.md) without a new user decision.
  `data-art` art; no new web access, fake charts or slot changes.
  Text fit: architecture.md#Implementation conventions.
- Feasibility: structured Blueprint rows; extraction only for Other, comments, references;
  images are not data. Other fail-open gap: PRD Later; unsupported still blocks.
- Replans publish freshness with proof; comments need explicit recovery. Recreate reuses confirmed
  KPIs/instructions with provenance; conflicts block; Blueprint ready => observations pass accept
  coverage (architecture.md#Blueprint observation coverage). Definition-only instructions are
  evidence; code adds determined missing rows (#Recreate observation completion). Recreate
  yearly dates reuse a projected base DATE with active full-column proof plus explicit intent
  or a selected native date-axis use of a recognized truncation; missing aliases need explicit
  intent. No guessed SQL simplification. Exact missing-KPI feedback uses the
  existing one repair; unresolved KPIs block (#Recreate date binding normalization).
  Recreate observations count only on their reference page; code-assigned observed titles drop
  unenforced period phrases and show the mapped unit (#Recreate page placement and truthful
  observed titles). An unlabeled field control's control_field issue offers unused instruction
  control clauses, then catalog-valid fields; never auto-bound (#Unlabeled reference control
  binding). Model-filled fields/mappings on an originally unlabeled field control cannot
  bypass those decisions, including after reload (#Unlabeled control binding enforcement).
  Reuse effective allowed types only within an operation; the next operation sees current
  env/.env (#Feasibility recomputation performance preservation).
  Final POC speed acceptance: 250 ms warm (user, 2026-10-27), with first/cold timings
  reported separately. This supersedes earlier 100 ms gates; workloads and correctness stay.
- Synthetic: opt-in schema/count/seed -> stdlib CSV -> typed BQ intake; protected page-1 footer.
  Footer checks visible paint/text; a transparent stretched container does not fail on its own.
- Reference extraction diagnostics: code-owned boundary/category + bounded schema paths on the
  existing span; no raw answers/validator messages/values (#Reference extraction diagnostics).
  Local rejection marks its call invalid. 25.8 added diagnostics; in live acceptance a rejected
  recreate extraction answer blocks without rerun (provider-transient: one). Defaults stay 3.1.
  Style values never reject a recreate extraction: common color/font forms are normalized,
  then still-invalid fields take the build's prefill preset; style mode still rejects them
  (#Recreate extraction style repair). After offline repair 25.10, one new live campaign is
  authorized in 25.11 at 1,200 s planning; deterministic failures stop. Region Selector
  authorization is checked across assessments.
- Tests offline unless marked live. Research <=20 fetches, no retries.
  Durable stage-import, brief-publication/recovery and test-oracle rules live in
  architecture.md#Implementation conventions and #Testing.

## Never do
- No LangGraph, no vector store, no embeddings, no pandas.
- Never expose credentials to frontend/logs/prompts, or put rows/history in prompts.
- Never copy a live SQLite file byte by byte or open it on the GCS volume; use the backup API.
- Never write semantic memory outside the consolidate node.
- Never let an LLM produce HTML outside the sanitized design layer, a whole spec, an artifact
  file, SQL DDL that bypasses the view builder, or recipe lines.
- Never edit ../contracts/; a needed change is a blocked task.

## Contracts
| Contract | Version | Role | Conformance check |
|---|---|---|---|
| ../contracts/api.md | 3.1 | provides | `uv run pytest tests/test_api_contract.py` |
| ../contracts/recipe.md (+ recipe.schema.json, fixtures/) | 1.3 | provides recipes; consumes events | `uv run pytest tests/test_recipe_contract.py` |
| ../contracts/conventions.md | 1.4 | consumes | manual: env names, ports, paths and IDs match |
| ../contracts/dashboard-intent.md | 1.2 | provides | `uv run pytest tests/test_api_contract.py tests/test_feasibility.py` |
| ../contracts/synthetic-data.md | 1.2 | provides | `uv run pytest tests -k synthetic` |

## Dependencies
| Package | Registry | Version | Why | Verified |
| --- | --- | --- | --- | --- |
| fastapi | pypi | >=0.115 | API | 2026-10-22 (0.159.1) |
| uvicorn | pypi | >=0.30 | ASGI server | 2026-10-22 (0.54.0) |
| sse-starlette | pypi | >=2.1 | SSE stream | 2026-10-22 (3.5.0) |
| python-multipart | pypi | >=0.0.9 | uploads | 2026-10-22 (0.0.32) |
| google-adk | pypi | >=2.0 | Workflow, agents, tools | 2026-10-22 (2.12.0) |
| google-genai | pypi | >=1.0 | Gemini client, token counts | 2026-10-22 (2.32.0) |
| google-cloud-bigquery | pypi | >=3.25 | loads, views, queries | 2026-10-22 (3.46.2) |
| python-dotenv | pypi | >=1.0 | ../.env | 2026-10-22 (1.2.4) |
| pydantic | pypi | >=2.8 | spec and API models | 2026-10-22 (2.14.1) |
| pyyaml | pypi | >=6.0 | OKF frontmatter | 2026-10-22 (6.0.3) |
| jsonschema | pypi | >=4.23 | recipe contract | 2026-10-22 (4.26.0) |
| playwright | pypi | >=1.48 | screenshots | 2026-10-22 (1.64.0) |
| jsonpatch | pypi | >=1.33 | RFC 6902 spec patches | 2026-10-22 (1.36) |
| httpx | pypi | >=0.27 | TestClient; dss-agent client | 2026-10-22 (0.28.1) |
| pytest | pypi | >=8.0 | tests | 2026-10-22 (9.1.1) |
| pytest-asyncio | pypi | >=0.23 | async tests | 2026-10-22 (1.4.0) |
| setuptools | pypi | * | build backend (user-approved, 1.1) | 2026-10-22 (84.2.1) |
| lucide-static | npm | * | icons in render/icons/ (ISC) | 2026-10-22 (1.61.0) |
| Natural Earth 110m | data | 5.1.2 | art source (PD) | 2026-10-24 (5.1.2) |
