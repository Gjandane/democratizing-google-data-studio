# Conventions (shared by every part)
Version 1.7 · Change log: 1.0 (2026-10-18) first version, revised by the plan audit before any build
(added DSS_ALLOWED_TYPES, DSS_CONSOLIDATE_EVERY, DSS_ENGINE_TIMEOUT_S, background_p<n>.png, engine lock).
1.1 (2026-10-19) Cloud Run deployment: one hosted service, access code, local build agent, DB backup
(added PORT, DSS_STATIC_DIR, DSS_ACCESS_CODE, DSS_ENGINE_MODE, DSS_AGENT_SERVER,
DSS_DB_PATH, GCP_REGION; sections Cloud deployment and Build agent), revised the same day by the
delta audit before any build (DSS_AGENT_TOKEN, DSS_DEV, agent paths and `--dry-run`, roles,
fail-closed start, backup cadence).
1.2 (2026-10-20) Cloud Run service renamed `dss` -> `dss-frontend` (keeps the submitted URL, kept out of the repo since 1.5; the full image replaces the earlier
static-frontend revision of that service). No other name, path or behaviour changed.
1.3 (2026-10-24, change reference fidelity) `DSS_ALLOWED_TYPES` default adds `area` and
`fixed_size_list` (recipe 1.3); no name added.
1.4 (2026-10-26, change configurable model stages) model choice moves to per-stage Settings
(contracts/api.md 3.0): `DSS_PLANNER_MODEL`/`DSS_WORKER_MODEL` only seed the one-time migration;
the agent-mode lock fixes the key and GCP values, not model settings. No name added or removed.
1.5 (2026-10-29, change Google sign-in) added `GOOGLE_OAUTH_CLIENT_ID`, `DSS_SIGNIN_ALLOW` and
`GCP_PROJECT_NUMBER`; the hosted URL and the project number live only in `.env`, never in a
tracked file (the repo is public; the link is shared privately);
the browser signs in with Google at the gate (contracts/api.md 3.3); the access code stays for
scripts. Cloud deployment: Access bullet, fail-closed rule, shared-history wording.
1.6 (2026-10-29, change open hosted link, user request) added `DSS_PUBLIC`: `1` on Cloud Run runs
the service with no gate (empty code, no Google sign-in; anyone with the URL gets in); the
fail-closed rule now has that one explicit opt-in. Access, Secrets bullets.
1.7 (2026-10-29, change cloud engine, user request) the engine runs inside the Cloud Run container
as a dedicated demo Google account, so visitors download nothing and get a finished report link:
`DSS_ENGINE_MODE=cloud`; added `DSS_GOOGLE_SESSION_FILE`, `DSS_CHROME_ARGS`, `DSS_REPORT_SHARE`,
`DSS_LOCKED_SOURCES`, `DSS_BOT_EMAIL`; sections Build agent, Engine use, Cloud deployment, Data
Studio. Agent mode stays for the owner's machine and is the rollback (hosted stops at the recipe).
Revised the same day by its delta audit and the user: scale to zero (`--min-instances 0`), the
source lock on every open deploy, a fourth secret, cache cap, session file `exported_at`.
Only the architect at the program root edits this file. Parts read it; they never edit it.

## Ports and URLs
- Backend (FastAPI): `http://localhost:8000`, every route under `/api`.
- Frontend (Vite dev server): `http://localhost:5173`. The frontend calls the backend only through
  relative `/api/...` paths; `vite.config.ts` proxies `/api` to `http://localhost:8000`. That keeps
  the prototype iframe same-origin, so the frontend can read its DOM.
- Chrome remote debugging (engine): `127.0.0.1:9222` (env `DSS_CDP_PORT`).
- Cloud Run (see Cloud deployment): one service serves the built frontend at `/` and the API at
  `/api` on the same origin, so relative `/api` paths and the same-origin prototype iframe still work.

## Environment variables
One `.env` at the repo root; backend and engine read it (python-dotenv, path `../.env` from the
part folder, overridable by real env vars). `.env.example` lists the names with empty or default
values. Names:

| Name | Default | Used by | Meaning |
|---|---|---|---|
| `GOOGLE_API_KEY` | (empty) | backend | Gemini API key |
| `DSS_PLANNER_MODEL` | `gemini-4-argon` | backend | legacy planner model: seeds the stages it served at the one-time 3.0 Settings migration (contracts/api.md, Stage settings); unused afterwards |
| `DSS_WORKER_MODEL` | `gemini-3.8-flash` | backend | legacy worker model: seeds its stages at the same migration; unused afterwards |
| `GCP_PROJECT_ID` | (empty) | backend, engine | BigQuery project and billing project |
| `BQ_DATASET` | `dss_demo` | backend, engine | dataset that holds uploaded tables and build views |
| `BQ_LOCATION` | `US` | backend | dataset location |
| `GCS_BUCKET` | (empty) | backend | default bucket for GCS sources (optional) |
| `DSS_DATA_DIR` | `../data` (from a part folder; = `<repo>/data`) | backend, engine | runtime files, see Paths |
| `DSS_CHROME_PATH` | (empty = auto-detect installed Chrome) | engine | Chrome executable |
| `DSS_CHROME_PROFILE` | `../.chrome-profile` (= `<repo>/.chrome-profile`) | engine | dedicated, persistent Chrome profile |
| `DSS_CDP_PORT` | `9222` | engine | Chrome remote debugging port |
| `DSS_TEMPLATE_REPORT_ID` | (empty) | engine | optional blank template report for the Linking API, if a blank create URL doesn't work (engine spike decides) |
| `DSS_ENGINE_CMD` | `uv run --project ../engine dsengine` | backend | how the backend starts the engine |
| `DSS_ALLOWED_TYPES` | `scorecard,time_series,area,bar,pie,table,pivot_table,geo_map,scatter,text,image,date_range,dropdown,fixed_size_list` | backend | component types the spec node may use and the validator accepts; narrow it if engine ops slip |
| `DSS_CONSOLIDATE_EVERY` | `5` | backend | consolidation runs after this many builds reach `done` (demo: `1`) |
| `DSS_DEV` | (empty) | backend | `1` mounts the `/api/dev/*` test helpers; never set on Cloud Run |
| `DSS_ENGINE_TIMEOUT_S` | `600` | backend, engine | whole-run timeout for `dsengine run` |
| `DSS_ENGINE_DRY_RUN` | `0` | backend | `1` = the backend adds `--dry-run` to `dsengine run` (tests, rehearsals without Data Studio) |
| `PORT` | `8000` | backend | listen port; Cloud Run sets it (8080) |
| `DSS_STATIC_DIR` | (empty = serve no frontend) | backend | built frontend folder served at `/` with SPA fallback (container: `/app/frontend/dist`) |
| `DSS_ACCESS_CODE` | (empty = no gate) | backend | shared access code, at least 12 characters; when set, `/api` needs it (contracts/api.md, Access). Cloud Run: from Secret Manager; the root `.env` value also gates the local app |
| `GOOGLE_OAUTH_CLIENT_ID` | (empty = no Google sign-in) | backend | 1.5: OAuth 2.0 Web client id (public, not a secret) for Google sign-in at the gate (contracts/api.md 3.3, Access); its Authorized JavaScript origins list the Cloud Run URL, `http://localhost:5173` and `http://localhost:8000`; needs `DSS_ACCESS_CODE`. Cloud Run: a plain env var |
| `DSS_PUBLIC` | (empty = gated) | backend | 1.6: read only when `K_SERVICE` is set (Cloud Run). `1` = open hosted link: the backend starts with `DSS_ACCESS_CODE` and `GOOGLE_OAUTH_CLIENT_ID` empty and gates nothing (contracts/api.md, Access, empty code); `1` with either of them set refuses to start; any other non-empty value refuses to start. Cloud Run: a plain env var, set from `.env` by `bash deploy/deploy.sh` |
| `DSS_SIGNIN_ALLOW` | (empty = any Google account) | backend | 1.5: who may sign in with Google: empty or `*` = any verified Google account; otherwise a comma list of `@domain` (the token's Workspace `hd` claim) and exact emails. Cloud Run: a plain env var, changed by editing `.env` and rerunning `bash deploy/deploy.sh` |
| `DSS_AGENT_TOKEN` | (empty) | backend, agent | secret token for `/api/agent/*` (header `X-DSS-Agent-Token`), at least 24 characters; never shown in the UI. Cloud Run: from Secret Manager |
| `DSS_ENGINE_MODE` | `local` | backend | `local` = the backend runs `DSS_ENGINE_CMD` itself; `agent` = builds are queued for a build agent; 1.7 `cloud` = on Cloud Run the backend runs `DSS_ENGINE_CMD` itself in the container, as the demo Google account (Cloud deployment) |
| `DSS_GOOGLE_SESSION_FILE` | (empty) | engine | 1.7: a Google session file (`dsengine session export`, contracts/recipe.md 1.4) imported into the profile when it is not signed in. Cloud Run: secret `DSS_GOOGLE_SESSION` mounted as a file at `/secrets/google-session/session.json`. Holds the demo account's cookies: a secret |
| `DSS_CHROME_ARGS` | (empty) | engine | 1.7: extra Chrome flags, space-separated (container: `--no-sandbox --disable-dev-shm-usage --disk-cache-size=33554432`; /tmp is memory on Cloud Run) |
| `DSS_REPORT_SHARE` | (empty = no sharing op) | backend | 1.7: `link_viewer` or `link_editor`: the compiler appends `share_report` with that access to every recipe (contracts/recipe.md 1.4); Cloud Run sets `link_editor` |
| `DSS_LOCKED_SOURCES` | (empty) | backend | 1.7: comma list of the `Source.kind` values `gcs` and `bigquery` that the API refuses (`403 source_locked`, contracts/api.md 3.4); any other value refuses to start; Cloud Run sets `bigquery,gcs` on every deploy with `DSS_PUBLIC=1`, in any engine mode (an open link must not read the owner's tables or buckets) |
| `DSS_BOT_EMAIL` | (empty) | release (deploy) | 1.7: the demo Google account's email; the deploy grants it BigQuery Data Viewer on `BQ_DATASET` and Job User on the project; only in `.env`, never in a tracked file |
| `DSS_AGENT_SERVER` | (empty) | agent, release (deploy) | base URL of the hosted app the agent pulls jobs from (`https://<service>-<hash>.<region>.run.app`); 1.5: also the deploy's URL guard and the e2e `--server`; only in `.env`, never in a tracked file |
| `GCP_PROJECT_NUMBER` | (empty) | release (deploy) | 1.5: the project number the deploy guard expects from `gcloud projects describe`; only in `.env`, never in a tracked file |
| `DSS_DB_PATH` | (empty = `<DSS_DATA_DIR>/dss.sqlite`) | backend | live SQLite file; when it is outside `DSS_DATA_DIR`, the backend keeps a backup at `<DSS_DATA_DIR>/dss.sqlite` (Cloud deployment) |
| `GCP_REGION` | `asia-southeast1` | release (deploy) | Cloud Run region, Artifact Registry and the state bucket |

Settings saved in the UI (stage profiles, GCP values, API key) override the env values at runtime; the
backend stores them in SQLite. The API key is write-only through the API: it is never returned.

## Paths (all under `<repo>/data/`, git-ignored)
- `data/dss.sqlite`: the backend's database (episodic memory, builds, settings, traces).
- `data/uploads/<build_id>/<file>.csv`: uploaded files.
- `data/builds/<build_id>/v<n>/`: one folder per build version:
  `docs/` (OKF build docs), `spec.json`, `prototype.html`, `background_p<n>.png` (one per page,
  `background_p1.png` for page 1), `recipe.jsonl`,
  `events.jsonl`, `screens/` (engine screenshots), `brief_p<n>.json` and `brief_p<n>.md` (each
  designed page's saved brief, api.md 3.0). A waiting brief review keeps its unpublished
  candidate under `data/.publications/` until it is approved or cancelled.
- `data/knowledge/`: semantic memory written at runtime (consolidated facts), OKF format.
- `<repo>/.chrome-profile/`: the engine's Chrome profile, git-ignored, never copied.
- `data/agent/<build_id>/v<n>/`: the build agent's local copy of a job (`recipe.jsonl`, background
  and image files, `screens/`), on the machine that runs the agent.

## IDs and time
- Build: `b_` + 12 lowercase hex chars (`b_3f9a0c12d4e5`). Chat message: `m_` + 12 hex. Run:
  `r_` + 12 hex. Comment: `k_` + 12 hex. Source: `s_` + 12 hex.
- Spec component and decoration IDs: lowercase snake case, unique within a spec, prefixed by the
  page (`p1_kpi_revenue`, `p1_band_header`).
- Recipe op IDs: `s` + 3-digit sequence (`s001`).
- Times: ISO 8601 UTC with `Z` (`2026-10-18T07:05:00Z`) in storage, events and the API.
- Geometry: integer pixels, origin at the canvas's top-left; boxes are `x, y, w, h`.
- Default canvas: 1200 x 900 px (Data Studio's default page size).

## Engine use
- One engine run at a time on this machine (one Chrome profile): the backend holds a global lock;
  a second `POST /run` gets `409 engine_busy`. In agent mode the lock covers the one build agent;
  in cloud mode (1.7) it covers the container's one Chrome, shared by every visitor.

## Build agent
- Agent mode: the engine runs on the agent's machine with its signed-in Chrome profile (1.7: on
  Cloud Run the hosted service runs it itself instead; Cloud deployment, Cloud engine). In `DSS_ENGINE_MODE=agent` the hosted backend queues each build as a job; the
  build agent (`uv run --project backend dss-agent`, from the repo root, provided by the backend)
  runs on the user's machine, long-polls the job, downloads the recipe and its files into
  `data/agent/<build_id>/v<n>/`, runs `DSS_ENGINE_CMD run` exactly as the local backend does, and
  posts the engine's events back (contracts/api.md, Agent endpoints).
- Paths: whatever folder it is started from, the agent resolves the root `.env`, `DSS_DATA_DIR`
  and `DSS_ENGINE_CMD` exactly as the backend does from `backend/` (it runs the engine with
  `cwd=backend/`), so `data/agent/` is `<repo>/data/agent/`.
- Config: the root `.env` (`DSS_AGENT_SERVER`, `DSS_AGENT_TOKEN`, `DSS_ENGINE_CMD`); `--server`
  overrides the URL. The token comes only from `.env` (no flag: shell history, process list); the
  agent never logs it. `--dry-run` forces `--dry-run` on every engine run (rehearsals).
- Timeouts: `Job.timeout_s` is passed to `dsengine run --timeout`; the server fails a job after
  `timeout_s + 60` s without events. The agent's HTTP timeout is longer than the long poll's
  `wait + 10` s. On `404 job_not_found` mid-job (server restart) the agent kills the engine and
  deletes that job's folder.
- Heartbeat: every 10 s from its own thread, also during jobs and long polls; `signed_in` and
  `chrome_running` come from `dsengine check`, run at start and every 60 s while idle, never during
  a run.

## Cloud deployment
- One Cloud Run service (name `dss-frontend`, region `GCP_REGION`, execution environment gen2) runs one
  container image built from the root `Dockerfile`: the backend plus the built frontend
  (`DSS_STATIC_DIR`), Playwright Chromium for `background_p<n>.png`, and (1.7) the engine.
  `DSS_ENGINE_MODE=cloud` (1.7; `agent` = the rollback). Startup probe on `GET /api/health`. Never `DSS_DEV`.
- Fail closed: when `K_SERVICE` is set (Cloud Run), the backend refuses to start if
  `DSS_ACCESS_CODE` is shorter than 12 characters or, in agent mode, `DSS_AGENT_TOKEN` is shorter
  than 24. Anywhere, `GOOGLE_OAUTH_CLIENT_ID` without `DSS_ACCESS_CODE` refuses to start (1.5).
  The one opt-in (1.6): `DSS_PUBLIC=1` replaces the code rule by "code and client id both empty";
  the agent-token rule stays (Agent endpoints keep their token).
- Access (1.5): the browser signs in with Google (any account unless `DSS_SIGNIN_ALLOW` narrows
  it); the access code stays for scripts, the e2e drivers and the owner. The OAuth consent screen
  is External and In production (basic scopes need no Google verification; in Testing only
  listed test users get in). Open link (1.6): with `DSS_PUBLIC=1` there is no gate at all, so
  every visitor shares one history and spends the owner's Gemini and BigQuery.
- At most one instance (1.7, user: scale to zero, `--min-instances 0 --max-instances 1`): the
  instance starts on the first request and stops after Cloud Run's idle period; CPU stays
  allocated while it is up (`--no-cpu-throttling`, builds continue after the `202`), request
  timeout 3600 s (SSE and long polls). A cold start (image pull, app import) delays the first
  visit after idle; SQLite comes back from the `/data` backup. A build still `building` when the
  instance stopped is failed at the next startup (1.7).
- State: a GCS bucket mounted as a Cloud Run volume at `/data` (`DSS_DATA_DIR=/data`). SQLite never
  opens a file on the bucket: `DSS_DB_PATH=/tmp/dss.sqlite`; at startup the backend restores it from
  `/data/dss.sqlite` when the local file is missing; every 30 s when anything was written, and at
  shutdown (graceful shutdown at most 3 s, inside Cloud Run's 10 s), SQLite's backup API writes
  `/tmp/dss.bak`, which is copied to `/data/dss.sqlite.tmp` and renamed over `/data/dss.sqlite`.
  At most 30 s of writes can be lost on a crash.
- Secrets: `GOOGLE_API_KEY`, `DSS_ACCESS_CODE` and `DSS_AGENT_TOKEN` come from Secret Manager as env
  vars (1.7: `DSS_GOOGLE_SESSION` as a mounted file, `DSS_GOOGLE_SESSION_FILE`); never in the image, the repo, the deploy script's output or the deck. With `DSS_PUBLIC=1`
  the service gets no `DSS_ACCESS_CODE` (1.6).
- Settings: on Cloud Run (agent and cloud mode) the API key and GCP values are fixed by the deployment;
  `PUT /api/settings` may change only model settings: stage profiles, fallback model and brief
  review (contracts/api.md 3.0).
- The runtime service account has BigQuery Data Editor and BigQuery Job User on `GCP_PROJECT_ID`,
  Secret Manager Secret Accessor on the secrets it mounts (1.7: four, with `DSS_GOOGLE_SESSION`), and Storage Object User on the state bucket;
  BigQuery on Cloud Run uses it as ADC. The Google account signed into the agent's Chrome
  profile must be able to read `BQ_DATASET` (a project owner or BigQuery Data Viewer + Job User),
  so the report's data source can read the views.
- Uploads through Cloud Run are limited to 32 MB per request (Cloud Run answers `413` itself).
- Shared by everyone who gets in (Google sign-in, the code, or the open link): one history and one engine lock; in
  agent mode builds need the owner's `dss-agent` online, otherwise the hosted app stops at the
  recipe (Build shows the agent panel); in cloud mode (1.7) the container builds.
- Cloud engine (1.7, `DSS_ENGINE_MODE=cloud`, replaces agent mode on the hosted service): the
  image also holds the engine (`/app/engine`, `DSS_ENGINE_CMD` pointing at it), Playwright
  Chromium (`DSS_CHROME_PATH`) and a virtual display (Xvfb, so Chrome renders headful with nobody
  watching); `DSS_CHROME_ARGS=--no-sandbox --disable-dev-shm-usage --disk-cache-size=33554432`. The Chrome profile lives on
  local disk (`DSS_CHROME_PROFILE=/tmp/chrome-profile`), never on the bucket; the session comes
  from `DSS_GOOGLE_SESSION_FILE` (secret `DSS_GOOGLE_SESSION`, exported once on the owner's machine
  from a profile signed in as the demo account) or the refreshed `/data/session/google.json`
  (each carries `exported_at`; a renewal deletes the refreshed copy). The runtime service account
  gets Secret Accessor on `DSS_GOOGLE_SESSION`. The backend starts Chrome (`DSS_ENGINE_CMD browser`) at startup and again before a run when
  `check` says it isn't running; Google sign-in is never automated and never happens in the
  container (`POST /api/engine/login` -> `409 login_in_cloud`). Settings are locked as in agent
  mode. `--memory 4Gi --cpu 2`. The demo account is a dedicated Gmail account with nothing else
  in it; it needs BigQuery Data Viewer on `BQ_DATASET` and Job User on the project
  (`DSS_BOT_EMAIL`). Reports land in the demo account and `share_report` (`DSS_REPORT_SHARE=link_editor`)
  gives anyone with the link edit access, so a visitor opens it in their own Data Studio session
  ("Shared with me"); the data source reads with the demo account's credentials. Sources
  `bigquery` and `gcs` are locked (`DSS_LOCKED_SOURCES`, on every open deploy); upload, research
  and synthetic stay. Rollback: the agent-mode revision (hosted stops at the recipe; sources stay
  locked). Closing after judging also removes the demo account's BigQuery roles: its reports'
  data sources keep reading with its credentials after a sign-out.

## Errors
- HTTP errors: status 4xx/5xx with body `{"error": {"code": "<snake_case>", "message": "<what
  happened and how to fix it>", "detail": {}}}`.
- Engine failures: `op_finished` events with `status: "failed"` and a `message`; exit codes in
  contracts/recipe.md.

## Logging
- Plain text to stdout: `<LEVEL> <part>.<module>: <message>`. Never log secret values, the API key
  or full prompt text; log token counts instead.

## Data Studio
- Product name in UI copy: "Data Studio". Report base URL: `https://datastudio.google.com/`.
- Local mode: the Google account signed into the engine's Chrome profile must be the same account
  as the Application Default Credentials the backend uses for BigQuery (`gcloud auth
  application-default login`), so the report's data source can read the views. Cloud Run: see
  Cloud deployment (agent mode: the agent's account; cloud mode, 1.7: the demo account).
