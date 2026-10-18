<!-- essentials-of: docs/architecture.md sha256:1ba778fa2eb8 (regenerate this page when architecture.md changes, then run stamp) -->
# Architecture essentials: backend
One page, read at the start of every build session. A summary of docs/architecture.md, which
wins if the two disagree.

## Stack
- Python 3.12 + uv; FastAPI + uvicorn (no `--reload`) + sse-starlette; google-adk 2.x `Workflow` graph with
  `LlmAgent` and function nodes; Gemini via `GOOGLE_API_KEY` (planner `gemini-4-argon` for plan
  and spec nodes, worker `gemini-3.8-flash` for all other LLM nodes, both overridable in settings);
  SQLite + FTS5 (stdlib); google-cloud-bigquery with ADC; Playwright Chromium (headless) for
  background.png; httpx (`dss-agent` client); pytest. Hosted on Cloud Run (one instance; image from
  the root Dockerfile, release part) with the engine run by the local `dss-agent`.

## Folder map
```text
src/dss/            main, config, db, bus, api/ (+ session, agent), agent/ (jobs, client = dss-agent),
                    harness/ (graph, nodes/, context, llm, guardrails, tracing), memory/
                    (procedural, semantic, episodic), data/bigquery.py, spec/, render/, recipe/compiler.py
skills/             procedural memory (one .md per skill)
knowledge/          semantic memory seed, OKF (index.md, log.md, catalog/, archetypes/, datastudio/ product limits)
prompts/v1/         one system prompt per LLM node (versioned release artifact)
tests/              offline: FakeLLM, FakeBigQuery, fake engine; tests/live/ marked `live`
```

## Conventions
- Harness vocabulary from ../harness-architecture.md in names and comments: agent run, working
  memory, procedural / semantic / episodic memory, consolidation, guardrails, trace.
- Every API action = one agent run = one ADK Workflow invocation = exactly one `traces` row.
- LLM nodes get context only from `harness/context.py` (per-node recipe and budget); never pass
  raw data rows, only `data-profile.md` and aggregate samples.
- The LLM writes only OKF build docs, the spec, or a spec JSON patch (structured output, validated
  with pydantic). HTML, background.png, view SQL and recipe come from code.
- Semantic memory is written only by the consolidate node (to `data/knowledge/`); `knowledge/`
  in git is the seed and changes only through tasks.
- Every OKF file: YAML frontmatter with non-empty `type`; folders have `index.md` and `log.md`.
- Config: `../.env` via python-dotenv, settings table overrides; names in ../contracts/conventions.md.
- Errors: `{"error": {code, message, detail}}`; codes from ../contracts/api.md.
- Engine subprocess: `subprocess.Popen` (argument list) read in a worker thread; Playwright: sync
  API in a worker thread. No asyncio subprocess or async Playwright (Windows event loop).
- One page per spec; component types limited to `DSS_ALLOWED_TYPES`.
- Cloud mode (architecture.md#Cloud mode): `DSS_STATIC_DIR` SPA serving, `$PORT`, access-code
  middleware (cookie or header; health and session open), fail-closed start on Cloud Run, DB on
  `DSS_DB_PATH` backed up every 30 s when dirty via `/tmp` to `DSS_DATA_DIR`; agent mode queues
  jobs for `dss-agent` (own token), consumes its events through the subprocess parser, locks
  settings to the models. Local defaults change nothing.
- `/api/dev/*` routes are test helpers outside the contract, mounted only when `DSS_DEV=1`.
- Contract tests compare responses with ../contracts/fixtures/api/ shapes (same keys and JSON types).
- Tests use FakeLLM / FakeBigQuery / fake engine; tests never call Gemini, BigQuery or Chrome
  unless marked `live`.

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
| ../contracts/api.md | 1.1 | provides | `uv run pytest tests/test_api_contract.py` |
| ../contracts/recipe.md (+ recipe.schema.json, fixtures/) | 1.0 | provides recipes; consumes events | `uv run pytest tests/test_recipe_contract.py` |
| ../contracts/conventions.md | 1.1 | consumes | manual: env names, ports, paths and IDs match |

## Dependencies
| Package | Registry | Version | Why | Verified |
| --- | --- | --- | --- | --- |
| fastapi | pypi | >=0.115 | API | 2026-10-19 (0.146.0) |
| uvicorn | pypi | >=0.30 | ASGI server | 2026-10-19 (0.54.0) |
| sse-starlette | pypi | >=2.1 | SSE stream | 2026-10-19 (3.5.0) |
| python-multipart | pypi | >=0.0.9 | CSV/image uploads | 2026-10-19 (0.0.32) |
| google-adk | pypi | >=2.0 | Workflow graph, agents, tools | 2026-10-19 (2.12.0) |
| google-genai | pypi | >=1.0 | Gemini client, token counts | 2026-10-19 (2.31.0) |
| google-cloud-bigquery | pypi | >=3.25 | loads, views, queries | 2026-10-19 (3.46.2) |
| python-dotenv | pypi | >=1.0 | ../.env | 2026-10-19 (1.2.4) |
| pydantic | pypi | >=2.8 | spec and API models | 2026-10-19 (2.14.1) |
| pyyaml | pypi | >=6.0 | OKF frontmatter | 2026-10-19 (6.0.3) |
| jsonschema | pypi | >=4.23 | recipe contract test | 2026-10-19 (4.26.0) |
| playwright | pypi | >=1.48 | background.png screenshot | 2026-10-19 (1.64.0) |
| jsonpatch | pypi | >=1.33 | RFC 6902 spec patches | 2026-10-19 (1.35) |
| httpx | pypi | >=0.27 | TestClient; dss-agent client (runtime) | 2026-10-19 (0.28.1) |
| pytest | pypi | >=8.0 | tests | 2026-10-19 (9.1.1) |
| pytest-asyncio | pypi | >=0.23 | async tests | 2026-10-19 (1.4.0) |
| setuptools | pypi | * | build backend for src/dss packaging and console scripts; approved by user for task 1.1 | 2026-10-19 (84.0.0) |
