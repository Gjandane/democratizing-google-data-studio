<!-- essentials-of: docs/architecture.md sha256:9e4031a2a47d (regenerate this page when architecture.md changes, then run stamp) -->
# Architecture essentials: backend
One page, read at the start of every build session. A summary of docs/architecture.md, which
wins if the two disagree.

## Stack
- Python 3.12/uv; FastAPI/uvicorn (no reload), SSE; ADK 2.x Workflow/LlmAgent; Gemini planner
  `gemini-4-argon` (plan/spec), worker `gemini-3.8-flash` (others), overridable in settings.
  SQLite/FTS5; BigQuery/ADC; Playwright Chromium; httpx. Cloud Run: one instance, local dss-agent.

## Folder map
```text
src/dss/        api/, agent/, harness/ (graph, nodes, context, llm, guardrails, tracing),
                memory/, data/ (bigquery, research), spec/, render/, recipe/, ops/
skills/         procedural memory; prompts/v1/ versioned system prompts
knowledge/      OKF seed: catalog/, archetypes/, datastudio/, index.md, log.md
tests/          offline fakes; tests/live/ explicitly marked live
```

## Conventions
- Harness vocabulary: ../harness-architecture.md. One API action = one agent run = one ADK
  Workflow invocation = exactly one `traces` row.
- Context only via `harness/context.py`; no raw rows. Online counts include the whole request;
  chars/4 is offline estimation. See architecture.md#Working memory assembly (task 9.6).
- The LLM writes only OKF build docs, the spec, a spec JSON patch or bounded structured
  observations (pydantic-validated). HTML, background.png, view SQL, CSV rows and recipe: code.
- Only consolidate writes runtime semantic memory (`data/knowledge/`); git knowledge is the seed.
- Every OKF file: YAML frontmatter with non-empty `type`; folders have `index.md` and `log.md`.
- Config: `../.env` via python-dotenv, settings table overrides; names in ../contracts/conventions.md.
- Errors: `{"error": {code, message, detail}}`; codes from ../contracts/api.md.
- Engine Popen argument list/cwd, read in a worker thread; reap the whole tree. Playwright sync in
  a worker thread (Windows). Provider schemas: response_json_schema; guard raw output before ADK
  validation, sanitize model errors, callable context instructions.
- One page per spec; component types limited to `DSS_ALLOWED_TYPES`. Sort `{field, order}`.
- Cloud: SPA/$PORT, code cookie/header, fail-closed startup; DB backup API every 30 s when dirty;
  agent token, model-only settings, 60 s whole-attempt retry deadline. Preview needs no engine;
  run recompiles the current spec; flat job image names (architecture.md#Build consistency).
- Staged revision, cache hashes, consolidation snapshots, backup deadlines:
  architecture.md#Implementation conventions. `/api/dev/*` only when `DSS_DEV=1`.
- Tests: contract fixture keys/types; offline fakes unless marked live (architecture.md#Testing).
- Research: one discovery + one metadata call; <=20 scraper fetches, no retries.
- References/feasibility (#Reference interpretation, #Capability verification): one set per
  version (style 1-3 images, recreate 1); images are never data. Registry + requirement ledger
  gate plan/render/compile/run; unknowns block; one extraction node per action (same trace).
- Plan publication: each plan attempt makes a run-specific candidate view; publish it with spec
  and artifacts; clean only uncommitted candidates; never replace a published view.
- Synthetic data (#Synthetic data, synthetic-data.md): schema/count/seed -> deterministic stdlib
  CSV -> typed BQ intake; opt-in; unremovable sample-data label.

## Never do
- No LangGraph, no vector store, no embeddings, no pandas.
- Never send the API key, the access code or the agent token to the frontend or a log; never put
  them in a prompt.
- Never copy a live SQLite file byte by byte or open it on the GCS volume; use the backup API.
- Never write semantic memory outside the consolidate node.
- Never let an LLM produce HTML, SQL DDL text that bypasses the view builder, or recipe lines.
- Never edit ../contracts/; a needed change is a blocked task.

## Contracts
| Contract | Version | Role | Conformance check |
|---|---|---|---|
| ../contracts/api.md | 1.4 | provides | `uv run pytest tests/test_api_contract.py` |
| ../contracts/recipe.md (+ recipe.schema.json, fixtures/) | 1.0 | provides recipes; consumes events | `uv run pytest tests/test_recipe_contract.py` |
| ../contracts/conventions.md | 1.1 | consumes | manual: env names, ports, paths and IDs match |
| ../contracts/dashboard-intent.md | 1.1 | provides | `uv run pytest tests/test_api_contract.py tests/test_feasibility.py` |
| ../contracts/synthetic-data.md | 1.1 | provides | `uv run pytest tests -k synthetic` |

## Dependencies
| Package | Registry | Version | Why | Verified |
| --- | --- | --- | --- | --- |
| fastapi | pypi | >=0.115 | API | 2026-10-19 (0.146.0) |
| uvicorn | pypi | >=0.30 | ASGI server | 2026-10-19 (0.54.0) |
| sse-starlette | pypi | >=2.1 | SSE stream | 2026-10-19 (3.5.0) |
| python-multipart | pypi | >=0.0.9 | uploads | 2026-10-19 (0.0.32) |
| google-adk | pypi | >=2.0 | Workflow, agents, tools | 2026-10-19 (2.12.0) |
| google-genai | pypi | >=1.0 | Gemini client, token counts | 2026-10-19 (2.31.0) |
| google-cloud-bigquery | pypi | >=3.25 | loads, views, queries | 2026-10-19 (3.46.2) |
| python-dotenv | pypi | >=1.0 | ../.env | 2026-10-19 (1.2.4) |
| pydantic | pypi | >=2.8 | spec and API models | 2026-10-19 (2.14.1) |
| pyyaml | pypi | >=6.0 | OKF frontmatter | 2026-10-19 (6.0.3) |
| jsonschema | pypi | >=4.23 | recipe contract | 2026-10-19 (4.26.0) |
| playwright | pypi | >=1.48 | screenshots | 2026-10-19 (1.64.0) |
| jsonpatch | pypi | >=1.33 | RFC 6902 spec patches | 2026-10-19 (1.35) |
| httpx | pypi | >=0.27 | TestClient; dss-agent client | 2026-10-19 (0.28.1) |
| pytest | pypi | >=8.0 | tests | 2026-10-19 (9.1.1) |
| pytest-asyncio | pypi | >=0.23 | async tests | 2026-10-19 (1.4.0) |
| setuptools | pypi | * | build backend, console scripts (user-approved, 1.1) | 2026-10-19 (84.0.0) |
