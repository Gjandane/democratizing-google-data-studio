<!-- essentials-of: none (no architecture.md; this page is the architecture) -->
# Architecture essentials: release
Read before building. POC: this page is the root part's whole architecture; the system is in
docs/program.md.

## Stack
- bash (`start.sh`) and Windows PowerShell 5.1 (`start.ps1`) start scripts; Python 3.12 + uv for
  `integration/` (its own uv project: httpx, jsonschema).
- Cloud Run: root `Dockerfile`: stage 1 `node:20-bookworm-slim` copies `frontend/` and `contracts/`
  (the mocks import the fixtures) and runs `npm ci && npm run build`; stage 2
  `python:3.12-slim-bookworm`, `pip install uv`, `uv sync --frozen` in backend/,
  `uv run playwright install --with-deps chromium`, a headless smoke screenshot, CMD
  `uv run python -m dss.main`. `deploy/deploy.sh`: gcloud CLI, `--source .` via Cloud Build.
  Cloud engine (4.2, change 2026-10-29): the image also holds `engine/` (`uv sync --frozen
  --no-dev`), Xvfb and fonts; ENTRYPOINT `deploy/entrypoint.sh` starts Xvfb `:99` and execs the
  CMD; the smoke step also runs `dsengine browser` + `check` under Xvfb.
- Deck (done in 1.3, final): `deck/build_deck.ps1` via PowerPoint COM (WPS Office here). Diagrams:
  HTML rendered by headless Chrome through `integration/render_diagrams.py`.

## Folder map
```text
start.sh, start.ps1      start backend (8000) and frontend (5173) together; Ctrl+C stops both
.env.example             every name from contracts/conventions.md, no values for secrets
.gitignore, LICENSE      ignore data/, .env, .chrome-profile/, .venv/, node_modules/, .blueprint/, screens
samples/                 ecommerce_sales.csv (generated, committed)
integration/             pyproject.toml, make_sample.py, check_contracts.py, e2e_flow1.py, e2e_references.py,
                         check_repo.py, render_diagrams.py, check_deck.py
Dockerfile, .dockerignore, .gcloudignore   one image: backend + frontend/dist (+ engine/ from 4.2; never data/, .env, .chrome-profile/)
deploy/                  deploy.sh (idempotent setup + deploy, --dry-run, --engine-mode cloud|agent),
                         entrypoint.sh (Xvfb), spike-engine.sh (4.2 Cloud Run job), README.md
deck/                    diagrams/*.html, img/*.png, data/bench-*.json, the 1.3 deck files; render/ git-ignored
Submission Template _ AI Builder Cup.pptx   the cup's template (team details typed in by the user); tasks never edit it
README.md                pitch, features, capabilities, simplified architecture, links, start, sign-in, agent, deploy
docs/acceptance.md       the user's manual acceptance: one row per source (release 2.4, 2.6)
docs/img/                README screenshots from 2.4/2.6, cropped (no email, avatar, code or token)
```

## Conventions
- Run parts from their folders with AGENTS.md commands.
- `e2e_flow1.py` talks only to the API (contracts/api.md): `--server` (default
  `http://localhost:8000`), header `X-DSS-Access-Code` from `DSS_ACCESS_CODE` when set; polls
  `GET /api/builds/{id}` every 2 s (timeout 10 min) instead of parsing SSE.
- Deploy settings (contracts/conventions.md#Cloud deployment): service `dss-frontend`, `GCP_REGION`
  (asia-southeast1; keeps the existing URL), gen2,
  `--min-instances 0 --max-instances 1 --no-cpu-throttling --timeout 3600 --cpu 2 --memory 2Gi`
  (scale to zero, user 2026-10-29; 4.3: `--memory 4Gi`),
  startup probe `/api/health`, env `GCP_PROJECT_ID`, `BQ_DATASET`, `BQ_LOCATION`,
  `DSS_DATA_DIR=/data`, `DSS_DB_PATH=/tmp/dss.sqlite`, `DSS_ENGINE_MODE=agent` (4.1; 4.3: `cloud`),
  `DSS_STATIC_DIR=/app/frontend/dist` (never `DSS_DEV`); secrets `GOOGLE_API_KEY`,
  `DSS_AGENT_TOKEN`, and `DSS_ACCESS_CODE` only when gated; bucket `<project>-dss-state` at `/data`;
  runtime SA roles per the contract; `--allow-unauthenticated`. Open link (conventions 1.6, change
  2026-10-29): `DSS_PUBLIC=1` in .env deploys with no gate (`DSS_PUBLIC=1`, empty
  `GOOGLE_OAUTH_CLIENT_ID` and `DSS_SIGNIN_ALLOW`, no code secret); `DSS_PUBLIC` empty deploys the
  gated path (Google sign-in, code for scripts; plain env `GOOGLE_OAUTH_CLIENT_ID`,
  `DSS_SIGNIN_ALLOW`). Every deploy guards the
  project number and sets SA, port, ingress, env and secrets in full, then traffic to latest (4.1).
  Cloud engine (4.3, conventions 1.7): `DSS_ENGINE_MODE=cloud`, `DSS_REPORT_SHARE=link_editor`,
  `DSS_LOCKED_SOURCES=bigquery,gcs` (every open deploy, both modes), `DSS_CHROME_PATH`, `DSS_CHROME_ARGS=--no-sandbox
  --disable-dev-shm-usage --disk-cache-size=33554432`, `DSS_CHROME_PROFILE=/tmp/chrome-profile`, secret `DSS_GOOGLE_SESSION`
  mounted at `/secrets/google-session/session.json` (`DSS_GOOGLE_SESSION_FILE`), `--memory 4Gi`;
  grants `DSS_BOT_EMAIL` BigQuery Data Viewer on `BQ_DATASET` + Job User; `--engine-mode agent`
  redeploys 4.1's setup (rollback). Copy link (conventions 1.8): bucket `<project>-dss-share`
  (uniform access, `allUsers` Object Viewer, 14-day delete), `DSS_SHARE_BUCKET`, runtime SA
  Storage Object User on it. The demo account's session comes from
  `data/session-export.json` (engine 14.1), never tracked.
  Commands and checks refer to secrets as unexpanded `$VARS`, never literal values.
- Diagrams: one HTML page per diagram on a 1840x800 canvas, white background, black text, Google
  accents (#4285F4, #EA4335, #FBBC04, #34A853), the vendored font, no network requests.
- Numbers in README come only from deck/data/bench-*.json (e2e runs), with the run date.
- Links, exactly: GitHub https://github.com/Gjandane/democratizing-google-data-studio ; hosted app: never in
  a tracked file (`DSS_AGENT_SERVER` in .env; shared privately with the judges; open link, no sign-in;
  open through 2026-11-07; builds run in the cloud as the demo account and the report link opens
  with edit access in the visitor's own Data Studio session; change 2026-10-29 cloud engine).
- README diagrams: deck/img d5 (node graph), d4 (harness, OKF not RAG), d8 (Google Cloud).
- README claims a feature on a target only after its acceptance passed there (local 2.4-2.6; hosted 4.3-4.4, live builds with the cloud engine).

## Never do
- Never edit engine/, backend/, frontend/ or contracts/; a fix there blocks the task.
- Never commit `.env`, `data/`, `.chrome-profile/`, keys, the access code, the hosted URL or the project number (change 2026-10-29), or screenshots showing
  account emails or avatars.
- Never push before the user confirms on a card (tasks 3.2 and 4.4); never force-push or rewrite
  history. Never deploy before the user confirms (task 4.1 STOP).
- Never edit the cup template; never put secrets in the image, Dockerfile or deploy.sh output.

## Contracts
| Contract | Version | Role | Conformance check |
|---|---|---|---|
| contracts/recipe.md | 1.4 | consumes (validates fixtures) | `uv run --project integration python integration/check_contracts.py` |
| contracts/api.md | 3.5 | consumes (e2e, local and deployed) | `uv run --project integration python integration/e2e_flow1.py` |
| contracts/conventions.md | 1.8 | consumes | `uv run --project integration python integration/check_contracts.py` (every env name is in .env.example) |
| contracts/dashboard-intent.md | 1.1 | consumes | `uv run --project integration python integration/check_contracts.py`; tasks 2.5 and 4.4 end-to-end |
| contracts/synthetic-data.md | 1.1 | consumes | release 2.5, 2.6 and 4.4 |

## Dependencies
| Package | Registry | Version | Why | Verified |
| --- | --- | --- | --- | --- |
| httpx | pypi | >=0.27 | e2e API calls | 2026-10-18 (0.28.1) |
| jsonschema | pypi | >=4.23 | validate contract fixtures | 2026-10-18 (4.26.0) |
| uv | pypi | >=0.13 | installs backend in the image | 2026-10-19 (0.13.1) |
| python:3.12-slim-bookworm | docker | 3.12-slim-bookworm | image base (stage 2) | 2026-10-19 (Docker Hub tag exists) |
| node:20-bookworm-slim | docker | 20-bookworm-slim | frontend build (stage 1) | 2026-10-19 (Docker Hub tag exists) |
