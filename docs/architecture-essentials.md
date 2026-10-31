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
- Demo video (Phase 5, docs/demo-video.md): Playwright for Python (in `integration/`) records the
  app with the installed Chrome (`channel="chrome"`); ffmpeg/ffprobe from PATH (installed on the
  build machine, not a package) cut and mix it.
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
Dockerfile, .dockerignore, .gcloudignore   one image: backend + frontend/dist (no engine, data/, .env, .chrome-profile/)
agent-setup/             setup.ps1, setup.sh: the visitor's one copied command (conventions 1.7, Build agent; 4.4)
deploy/                  deploy.sh (idempotent setup + deploy, --dry-run), README.md
deck/                    diagrams/*.html, img/*.png, data/bench-*.json, the 1.3 deck files; render/ git-ignored
Submission Template _ AI Builder Cup.pptx   the cup's template (team details typed in by the user); tasks never edit it
README.md                pitch, features, capabilities, simplified architecture, links, start, sign-in, agent, deploy
docs/acceptance.md       the user's manual acceptance: one row per source (release 2.4, 2.6)
integration/video/       check_storyboard.py, record_app.py, make_video.py (Phase 5)
deck/video/              storyboard.json, cards/*.html (committed); demo.mp4, demo.srt, raw/, build/, music.* git-ignored
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
  (scale to zero, change 2026-10-29 local agent per judge),
  startup probe `/api/health`, env `GCP_PROJECT_ID`, `BQ_DATASET`, `BQ_LOCATION`,
  `DSS_DATA_DIR=/data`, `DSS_DB_PATH=/tmp/dss.sqlite`, `DSS_ENGINE_MODE=agent`,
  `DSS_STATIC_DIR=/app/frontend/dist` (never `DSS_DEV`); secrets `GOOGLE_API_KEY`,
  `DSS_AGENT_TOKEN`, and `DSS_ACCESS_CODE` only when gated; bucket `<project>-dss-state` at `/data`;
  runtime SA roles per the contract; `--allow-unauthenticated`. Open link (conventions 1.6, change
  2026-10-29): `DSS_PUBLIC=1` in .env deploys with no gate (`DSS_PUBLIC=1`, empty
  `GOOGLE_OAUTH_CLIENT_ID` and `DSS_SIGNIN_ALLOW`, no code secret); `DSS_PUBLIC` empty deploys the
  gated path (Google sign-in, code for scripts; plain env `GOOGLE_OAUTH_CLIENT_ID`,
  `DSS_SIGNIN_ALLOW`). Every deploy guards the
  project number and sets SA, port, ingress, env and secrets in full, then traffic to latest (4.1).
  Commands and checks refer to secrets as unexpanded `$VARS`, never literal values.
  From 4.5 (conventions 1.7): bucket `<project>-dss-share` (uniform access; `allUsers` gets a
  custom role with only `storage.objects.get`; runtime SA Storage Object User) mounted at
  `/share`, env `DSS_SHARE_BUCKET`, `DSS_SHARE_DIR=/share`; no `DSS_AGENT_TOKEN` secret.
- Diagrams: one HTML page per diagram on a 1840x800 canvas, white background, black text, Google
  accents (#4285F4, #EA4335, #FBBC04, #34A853), the vendored font, no network requests.
- Numbers in README come only from deck/data/bench-*.json (e2e runs), with the run date.
- Links, exactly: GitHub https://github.com/Gjandane/democratizing-google-data-studio ; hosted app: never in
  a tracked file (`DSS_AGENT_SERVER` in .env; shared privately with the judges; open link, no sign-in,
  until closed after 2026-11-07; from 4.5 a visitor builds into their own Data Studio through the
  setup command; Chrome required, Windows tested, macOS/Linux untested).
- README diagrams: deck/img d5 (node graph), d4 (harness, OKF not RAG), d8 (Google Cloud).
- README claims a feature on a target only after its acceptance passed there (local 2.4-2.6; hosted 4.2-4.3 up to the recipe, 4.6 the judge build).

## Never do
- Never edit engine/, backend/, frontend/ or contracts/; a fix there blocks the task.
- Never commit `.env`, `data/`, `.chrome-profile/`, keys, the access code, the hosted URL or the project number (change 2026-10-29), or screenshots showing
  account emails or avatars.
- Never push before the user confirms on a card (tasks 3.2, 4.4, 4.6 and 4.7); never force-push or rewrite
  history. Never deploy before the user confirms (task 4.1 STOP).
- Never show or commit, in the demo video, its SRT or storyboard, an account email or avatar, the
  hosted URL, the project number or ID, a key or a code (docs/demo-video.md#Privacy).
- Never edit the cup template; never put secrets in the image, Dockerfile or deploy.sh output.

## Contracts
| Contract | Version | Role | Conformance check |
|---|---|---|---|
| contracts/recipe.md | 1.5 | consumes (validates fixtures) | `uv run --project integration python integration/check_contracts.py` |
| contracts/api.md | 3.5 | consumes (e2e, local and deployed) | `uv run --project integration python integration/e2e_flow1.py` |
| contracts/conventions.md | 1.7 | consumes | `uv run --project integration python integration/check_contracts.py` (every env name is in .env.example) |
| contracts/dashboard-intent.md | 1.1 | consumes | `uv run --project integration python integration/check_contracts.py`; tasks 2.5 and 4.3 end-to-end |
| contracts/synthetic-data.md | 1.1 | consumes | release 2.5, 2.6 and 4.3 |

## Dependencies
| Package | Registry | Version | Why | Verified |
| --- | --- | --- | --- | --- |
| httpx | pypi | >=0.27 | e2e API calls | 2026-10-31 (0.28.1) |
| jsonschema | pypi | >=4.23 | validate contract fixtures | 2026-10-31 (4.26.0) |
| uv | pypi | >=0.13 | installs backend in the image | 2026-10-31 (0.13.6) |
| python:3.12-slim-bookworm | docker | 3.12-slim-bookworm | image base (stage 2) | 2026-10-19 (Docker Hub tag exists) |
| node:20-bookworm-slim | docker | 20-bookworm-slim | frontend build (stage 1) | 2026-10-19 (Docker Hub tag exists) |
| playwright | pypi | >=1.48 | records the demo video (5.2) | 2026-10-31 (1.64.1) |
