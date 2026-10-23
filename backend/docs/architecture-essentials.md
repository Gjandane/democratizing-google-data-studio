<!-- essentials-of: docs/architecture.md sha256:808c82cd13f9 (regenerate this page when architecture.md changes, then run stamp) -->
# Architecture essentials: backend
Read every build session. docs/architecture.md wins if they disagree.

## Stack
- Python 3.12/uv; FastAPI/uvicorn (no reload), SSE; ADK 2.x Workflow/LlmAgent; Gemini planner
  `gemini-4-argon` (blueprint, designer), worker `gemini-3.8-flash` (others), overridable in settings.
  SQLite/FTS5; BigQuery/ADC; Playwright Chromium; httpx. Cloud Run: one instance, local dss-agent.

## Folder map
```text
src/dss/        api/, agent/, artifacts/ (models, okf, state), harness/ (graph, nodes, context,
                llm, guardrails, tracing), memory/, data/ (bigquery, profile, research), spec/,
                render/ (prototype, background, kits, design_page, icons/), recipe/, ops/
skills/         procedural memory; prompts/v1/ versioned system prompts
knowledge/      OKF seed: catalog/, archetypes/, datastudio/ (fonts.md), themes/, index.md, log.md
tests/          offline fakes; tests/live/ explicitly marked live
```

## Conventions
- Vocabulary: ../harness-architecture.md. One API action = one ADK Workflow = one trace.
- api.md 2.0: connect -> context -> outline -> design -> blueprint -> prototype. Code profiles,
  validates, lays out 1-5 pages and writes files. Models return validated JSON, using compact
  profiles/upstream frontmatter, never rows/history; node-specific repair limits and budgets:
  architecture.md#Working memory assembly (chars/4 offline only).
- Artifact edits stale downstream work; confirmation preserves edits. Atomic OKF writes emit
  artifact/docs updates; question IDs never recycle. Schema-returning dry runs establish types.
- Only consolidate writes runtime semantic memory; git knowledge is the seed. OKF requires
  nonempty `type`, folder index/log. Config: ../.env + settings; contract env names/error codes.
- Engine argument list/cwd, worker-thread reads, whole-tree cleanup; Playwright sync in a worker
  thread. Provider: response_json_schema, guarded raw output, sanitized errors, callable context.
  Gemini: planner 120 s, worker 30 s; one retry on 429/500/503, never 504.
- Types: `DSS_ALLOWED_TYPES`; sort `{field, order}`. COUNT variants allow dimensions; dropdown
  uses one dimension. Chart colors override theme (no scorecards); accents affect only their target.
- Cloud: SPA/$PORT, code cookie/header, fail-closed startup; backup API every 30 s when dirty;
  agent token, model-only settings, 60 s retry deadline. Preview needs no engine; run recompiles
  current spec; flat job assets. Dev routes require DSS_DEV=1.
- Blueprint accept publishes its owned candidate view/spec/artifacts atomically; never clean a
  published view. Backgrounds: background.write_pages, render(page=n), not the stacked canvas; 3x, <2 MB.
- Designed pages: planner HTML, sanitized; Chromium measures slots -> component `box`, width
  1200-1920; one repair, then kit fallback; a page whose design breaks publish coverage falls
  back too (architecture.md#Designed pages).
  Heading wraps/text fitting: architecture.md#Implementation conventions.
- Feasibility: structured Blueprint rows; extraction only for Other, comments, references.
  Images are not data. User-approved Other fail-open limitation and contract gap: PRD Later;
  emitted unsupported requirements still block (architecture.md#Outline).
- Replans publish freshness with proof; comments need explicit recovery. Recreate reuses confirmed
  KPIs/user instructions with provenance; conflicts block.
- Synthetic: opt-in schema/count/seed -> stdlib CSV -> typed BQ intake; protected page-1 footer.
- Tests offline unless marked live; fixture keys/types exact. Research <=20 fetches, no retries.

## Never do
- No LangGraph, no vector store, no embeddings, no pandas.
- Never expose credentials to frontend/logs/prompts, or put rows/history in prompts.
- Never copy a live SQLite file byte by byte or open it on the GCS volume; use the backup API.
- Never write semantic memory outside the consolidate node.
- Never let an LLM produce HTML other than the sanitized designed-page layer, a whole spec, an artifact file, SQL DDL text that bypasses the
  view builder, or recipe lines.
- Never edit ../contracts/; a needed change is a blocked task.

## Contracts
| Contract | Version | Role | Conformance check |
|---|---|---|---|
| ../contracts/api.md | 2.0 | provides | `uv run pytest tests/test_api_contract.py` |
| ../contracts/recipe.md (+ recipe.schema.json, fixtures/) | 1.1 | provides recipes; consumes events | `uv run pytest tests/test_recipe_contract.py` |
| ../contracts/conventions.md | 1.2 | consumes | manual: env names, ports, paths and IDs match (1.2 renames the Cloud Run service only) |
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
| setuptools | pypi | * | build backend, console scripts (user-approved, 1.1) | 2026-10-22 (84.2.1) |
| lucide-static | npm | * | icon SVGs vendored into render/icons/ (ISC; not installed; user-approved 2026-10-22) | 2026-10-22 (1.61.0) |
