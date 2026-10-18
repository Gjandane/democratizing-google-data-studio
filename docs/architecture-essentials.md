<!-- essentials-of: none (no architecture.md; this page is the architecture) -->
# Architecture essentials: release
One page, read at the start of every build session. POC: this page is the whole architecture of
the root part. The whole system is described in docs/program.md.

## Stack
- bash (`start.sh`) and Windows PowerShell 5.1 (`start.ps1`) start scripts; Python 3.12 + uv for
  `integration/` (its own uv project: httpx, jsonschema; stdlib for the deck check and renders).
- Cloud Run: root `Dockerfile`: stage 1 `node:20-bookworm-slim` copies `frontend/` and `contracts/`
  (the mocks import the fixtures) and runs `npm ci && npm run build`; stage 2
  `python:3.12-slim-bookworm`, `pip install uv`, `uv sync --frozen` in backend/,
  `uv run playwright install --with-deps chromium`, a headless smoke screenshot, CMD
  `uv run python -m dss.main`. `deploy/deploy.sh` with the gcloud CLI (`gcloud run deploy --source .`
  through Cloud Build; `.gcloudignore` decides what is uploaded).
- Deck: the cup template filled through PowerPoint COM from PowerShell 5.1 (`deck/build_deck.ps1`,
  PowerPoint installed; checked 2026-10-19); diagrams as HTML rendered by headless Chrome
  (`--headless --screenshot --window-size=1840,800 --force-device-scale-factor=2
  --hide-scrollbars --virtual-time-budget=5000`).

## Folder map
```text
start.sh, start.ps1      start backend (8000) and frontend (5173) together; Ctrl+C stops both
.env.example             every name from contracts/conventions.md, no values for secrets
.gitignore, LICENSE      ignore data/, .env, .chrome-profile/, .venv/, node_modules/, .blueprint/, screens
samples/                 ecommerce_sales.csv (generated, committed)
integration/             pyproject.toml, make_sample.py, check_contracts.py, e2e_flow1.py,
                         render_diagrams.py, check_deck.py
Dockerfile, .dockerignore, .gcloudignore   one image: backend + frontend/dist (no engine, data/, .env, .chrome-profile/)
deploy/                  deploy.sh (idempotent setup + deploy, --dry-run), README.md
deck/                    diagrams/*.html (+ fonts/), img/*.png, data/bench-*.json, content.json, build_deck.ps1,
                         AI-Builder-Cup-Submission.pptx + .pdf, render/ (QA PNGs, git-ignored)
Submission Template _ AI Builder Cup.pptx   the cup's template: input only, never modified
README.md                what, hosted demo, prerequisites, start, sign-in, agent, deploy, demo script
```

## Conventions
- Run each part with the exact commands in that part's AGENTS.md, from that part's folder.
- `e2e_flow1.py` talks only to the API (contracts/api.md): `--server` (default
  `http://localhost:8000`), header `X-DSS-Access-Code` from `DSS_ACCESS_CODE` when set; polls
  `GET /api/builds/{id}` every 2 s (timeout 10 min) instead of parsing SSE.
- Deploy settings (contracts/conventions.md#Cloud deployment): service `dss`, `GCP_REGION`, gen2,
  `--min-instances 1 --max-instances 1 --no-cpu-throttling --timeout 3600 --cpu 2 --memory 2Gi`,
  startup probe `/api/health`, env `GCP_PROJECT_ID`, `BQ_DATASET`, `BQ_LOCATION`,
  `DSS_DATA_DIR=/data`, `DSS_DB_PATH=/tmp/dss.sqlite`, `DSS_ENGINE_MODE=agent`,
  `DSS_STATIC_DIR=/app/frontend/dist` (never `DSS_DEV`); secrets `GOOGLE_API_KEY`,
  `DSS_ACCESS_CODE`, `DSS_AGENT_TOKEN`; bucket `<project>-dss-state` at `/data`; runtime SA roles
  per the contract; `--allow-unauthenticated` only with the access code. Commands and checks refer
  to secrets as unexpanded `$VARS`, never literal values.
- Deck: content lives in `deck/content.json`, the script only places it; slides keep the template's
  header bar, title box position, fonts and sizes; at most 90 words of body per slide; speaker
  notes in the notes pane. Diagrams: one HTML page per diagram on a 1840x800 canvas, white
  background, black text, Google accents (#4285F4, #EA4335, #FBBC04, #34A853), Google Sans Flex
  (the template's font) vendored in deck/diagrams/fonts/ when its license allows, else Arial; no
  network requests.
- Diagrams in README and deck use the component names of harness-architecture.md and the part names.
- Numbers on slides come only from deck/data/bench-*.json (written by e2e runs 2.2, 2.3, 3.2),
  with the run date; unbuilt features are tagged "planned".

## Never do
- Never edit engine/, backend/, frontend/ or contracts/; a fix there is a blocked task naming the part.
- Never commit `.env`, `data/`, `.chrome-profile/`, API keys, the access code or screenshots
  containing account emails, avatars or the access code.
- Never push to GitHub; the user pushes. Never deploy before the user confirms (task 3.1 STOP).
- Never modify `Submission Template _ AI Builder Cup.pptx`; never put secrets in the image,
  the Dockerfile, deploy.sh output or the deck.

## Contracts
| Contract | Version | Role | Conformance check |
|---|---|---|---|
| contracts/recipe.md | 1.0 | consumes (validates fixtures) | `uv run --project integration python integration/check_contracts.py` |
| contracts/api.md | 1.1 | consumes (e2e, local and deployed) | `uv run --project integration python integration/e2e_flow1.py` |
| contracts/conventions.md | 1.1 | consumes | `uv run --project integration python integration/check_contracts.py` (every env name is in .env.example) |

## Dependencies
| Package | Registry | Version | Why | Verified |
| --- | --- | --- | --- | --- |
| httpx | pypi | >=0.27 | e2e API calls | 2026-10-18 (0.28.1) |
| jsonschema | pypi | >=4.23 | validate contract fixtures | 2026-10-18 (4.26.0) |
| uv | pypi | >=0.13 | installs backend in the image | 2026-10-19 (0.13.1) |
| python:3.12-slim-bookworm | docker | 3.12-slim-bookworm | image base (stage 2) | 2026-10-19 (Docker Hub tag exists) |
| node:20-bookworm-slim | docker | 20-bookworm-slim | frontend build (stage 1) | 2026-10-19 (Docker Hub tag exists) |
