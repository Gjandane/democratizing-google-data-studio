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
1.7 (2026-10-29, change local agent per judge, user cards; contracts/api.md 3.4, recipe.md 1.4)
hosted builds run on each visitor's own machine as one-shot jobs (`dss-agent run --server <URL>
--job <CODE>`, set up by one copied command; Chrome required) into the visitor's own Data Studio
account; added `DSS_SHARE_BUCKET` and `DSS_SHARE_DIR` (the build's data as a public-read CSV);
`DSS_AGENT_TOKEN` retired with the polling agent (from backend 29.1); scale to zero
(`--min-instances 0`); GCS and BigQuery sources locked on the open link. Sections Build agent,
Engine use, Cloud deployment, Paths, Data Studio.
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
| `GCP_PROJECT_ID` | (empty) | backend, engine | BigQuery project and billing project (engine: only for a `bigQuery` recipe header, 1.7) |
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
| `DSS_AGENT_TOKEN` | (empty) | backend (before 29.1), release (deploy, until 4.5) | retired in 1.7 (api.md 3.4 per-job tokens): the polling agent's shared token; backends before backend 29.1 still require it in agent mode on Cloud Run (at least 24 characters, from Secret Manager); from 29.1 nothing reads it and release 4.5's deploy stops creating it |
| `DSS_SHARE_BUCKET` | (empty = no share data) | backend, release (deploy) | 1.7: bucket name (no `gs://`) for the hosted share data: each agent-mode run's view as one public-read CSV (Build agent, Cloud deployment); needs `DSS_SHARE_DIR`. Cloud Run: `<GCP_PROJECT_ID>-dss-share`, set by `bash deploy/deploy.sh` |
| `DSS_SHARE_DIR` | (empty) | backend | 1.7: local folder where `DSS_SHARE_BUCKET` is mounted (Cloud Run: `/share`); the backend writes `<DSS_SHARE_DIR>/<hex>/data.csv` and names it `<DSS_SHARE_BUCKET>/<hex>/data.csv` in the recipe; both set = `Hosting.share_data` in agent mode |
| `DSS_ENGINE_MODE` | `local` | backend | `local` = the backend runs `DSS_ENGINE_CMD` itself; `agent` = builds run as one-shot jobs for a build agent on the builder's machine (Cloud Run; 1.7) |
| `DSS_AGENT_SERVER` | (empty) | release (deploy, e2e) | base URL of the hosted app (`https://<service>-<hash>.<region>.run.app`): the deploy's URL guard and the e2e `--server`; only in `.env`, never in a tracked file (1.7: the agent takes the URL from `--server` only) |
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
  and image files, `screens/`), on the machine that runs the agent (1.7: under the setup's
  install folder, Build agent).
- Agent install folder (1.7, the visitor's machine): `%LOCALAPPDATA%\dss-agent\` on Windows,
  `~/.dss-agent/` with bash: `app/` (the repo zip, replaced on update), `chrome-profile/`
  (`DSS_CHROME_PROFILE`, kept across updates), `data/` (`DSS_DATA_DIR`), `uv` caches as uv puts
  them. Never inside the repo checkout.

## IDs and time
- Build: `b_` + 12 lowercase hex chars (`b_3f9a0c12d4e5`). Chat message: `m_` + 12 hex. Run:
  `r_` + 12 hex. Comment: `k_` + 12 hex. Source: `s_` + 12 hex. Agent check (1.7): `c_` + 12 hex.
- Spec component and decoration IDs: lowercase snake case, unique within a spec, prefixed by the
  page (`p1_kpi_revenue`, `p1_band_header`).
- Recipe op IDs: `s` + 3-digit sequence (`s001`).
- Times: ISO 8601 UTC with `Z` (`2026-10-18T07:05:00Z`) in storage, events and the API.
- Geometry: integer pixels, origin at the canvas's top-left; boxes are `x, y, w, h`.
- Default canvas: 1200 x 900 px (Data Studio's default page size).

## Engine use
- One engine run at a time on this machine (one Chrome profile): the backend holds a global lock;
  a second `POST /run` gets `409 engine_busy`. Agent mode (1.7): no global lock; each build has at
  most one `waiting` or `running` job ticket (contracts/api.md 3.4), and each visitor's agent runs
  one job at a time on their own machine.

## Build agent
- The engine never runs in the cloud: it needs a signed-in Chrome profile, which stays on the
  machine of whoever builds. 1.7: in `DSS_ENGINE_MODE=agent` each Build issues a one-shot job
  with a one-time code (contracts/api.md 3.4); the visitor runs `dss-agent run --server <URL>
  --job <CODE>` (provided by the backend) on their own machine; it claims that one job, downloads
  the recipe and its files into `data/agent/<build_id>/v<n>/`, runs `DSS_ENGINE_CMD run` exactly
  as the local backend does, posts the engine's events back with the job's token, and exits. The
  report is saved in the Google account signed into that machine's engine profile. There is no
  polling agent and no heartbeat.
- Setup (1.7): the Build stage shows one command to copy: PowerShell (Windows, tested) and bash
  (macOS/Linux, labeled untested). The script `agent-setup/setup.ps1` / `agent-setup/setup.sh`
  (release, fetched from the public repo's `main` on raw.githubusercontent.com) checks that
  Google Chrome is installed (else prints where to get it and exits 1), installs uv if missing,
  downloads the repo zip into the install folder (Paths) when missing or with `-Update`/`--update`,
  runs `uv sync --no-dev` for backend and engine, sets `DSS_CHROME_PROFILE` and `DSS_DATA_DIR` to
  the install folder, runs `dsengine login` when `dsengine check` says not signed in (the visitor
  signs in to Google and accepts Data Studio's first-run terms in that Chrome window), then runs
  `dss-agent run --server <URL> --job <CODE>`. Rerunning it with the next code reuses the install
  and the sign-in. No `.env`, Git or GCP project is needed on that machine.
- Setup step (1.7, revised before any build, user card): the Build stage first offers "Set up this
  computer" with a check code; the same script with `-Check <CODE>` / `--check <CODE>` instead of
  `-Job` does the install and sign-in, then runs `dss-agent check --server <URL> --code <CODE>`,
  which runs `dsengine check` (starting Chrome with the profile if it isn't running), posts the
  result (contracts/api.md 3.4, `POST /api/agent/check`), prints one line per item (server
  reached, versions match, Chrome running, signed in) with what to fix, and exits 0 only when all
  pass. The page then shows the agent as ready; the job command afterwards skips install and
  login.
- Setup command (1.7; the frontend shows it, release's scripts take it; `<origin>` is the app's
  `window.location.origin`, `<CODE>` the ticket's code), exactly:
  PowerShell: `& ([scriptblock]::Create((irm https://raw.githubusercontent.com/Gjandane/democratizing-google-data-studio/main/agent-setup/setup.ps1))) -Server <origin> -Job <CODE>`
  bash: `curl -fsSL https://raw.githubusercontent.com/Gjandane/democratizing-google-data-studio/main/agent-setup/setup.sh | bash -s -- --server <origin> --job <CODE>`
  The setup step's commands are the same with `-Check <CODE>` / `--check <CODE>` in place of
  `-Job <CODE>` / `--job <CODE>` (the check's code).
  Optional: `-Update` / `--update` (fresh repo zip), `-DryRun` / `--dry-run` (passed to the agent;
  skips `dsengine login`), `-Source <zip path or URL>` / `--source` (tests of an unpushed tree),
  `-Home <folder>` / `--home` (another install folder, tests).
- Paths: the agent resolves `DSS_DATA_DIR` and `DSS_ENGINE_CMD` as the backend does from
  `backend/` (it runs the engine with `cwd=backend/`); the setup's env vars win (Paths).
- Config: `--server` (required) and `--job` (required); the code and the job token are never
  logged or written to disk. `--dry-run` forces `--dry-run` on the engine run (rehearsals). A
  claim whose `api_version` differs from the agent's exits 2 with "Rerun the setup command with
  -Update".
- Timeouts: `Job.timeout_s` is passed to `dsengine run --timeout`; the server fails a claimed job
  after `timeout_s + 60` s without events. On `404 job_not_found` mid-job the agent kills the
  engine and deletes that job's folder. Network errors: retry with backoff up to 60 s, then exit
  non-zero.

## Cloud deployment
- One Cloud Run service (name `dss-frontend`, region `GCP_REGION`, execution environment gen2) runs one
  container image built from the root `Dockerfile`: the backend plus the built frontend
  (`DSS_STATIC_DIR`), Playwright Chromium for `background_p<n>.png`, no engine.
  `DSS_ENGINE_MODE=agent`. Startup probe on `GET /api/health`. Never `DSS_DEV`.
- Fail closed: when `K_SERVICE` is set (Cloud Run), the backend refuses to start if
  `DSS_ACCESS_CODE` is shorter than 12 characters or, in agent mode, `DSS_AGENT_TOKEN` is shorter
  than 24 (1.7: the agent-token rule ends with backend 29.1; `DSS_SHARE_BUCKET` without
  `DSS_SHARE_DIR`, or the reverse, refuses to start). Anywhere, `GOOGLE_OAUTH_CLIENT_ID` without `DSS_ACCESS_CODE` refuses to start (1.5).
  The one opt-in (1.6): `DSS_PUBLIC=1` replaces the code rule by "code and client id both empty";
  the agent-token rule stays until backend 29.1 (1.7: per-job tokens, no shared agent token).
- Access (1.5): the browser signs in with Google (any account unless `DSS_SIGNIN_ALLOW` narrows
  it); the access code stays for scripts, the e2e drivers and the owner. The OAuth consent screen
  is External and In production (basic scopes need no Google verification; in Testing only
  listed test users get in). Open link (1.6): with `DSS_PUBLIC=1` there is no gate at all, so
  every visitor shares one history and spends the owner's Gemini and BigQuery.
- One instance at most, scaling to zero (1.7: `--min-instances 0 --max-instances 1`; pay while
  in use, cold starts accepted), CPU always allocated while it runs (`--no-cpu-throttling`,
  runs continue after the `202`), request timeout 3600 s (SSE). An open browser tab's event
  stream keeps it up; nothing else polls it.
- State: a GCS bucket mounted as a Cloud Run volume at `/data` (`DSS_DATA_DIR=/data`). SQLite never
  opens a file on the bucket: `DSS_DB_PATH=/tmp/dss.sqlite`; at startup the backend restores it from
  `/data/dss.sqlite` when the local file is missing; every 30 s when anything was written, and at
  shutdown (graceful shutdown at most 3 s, inside Cloud Run's 10 s), SQLite's backup API writes
  `/tmp/dss.bak`, which is copied to `/data/dss.sqlite.tmp` and renamed over `/data/dss.sqlite`.
  At most 30 s of writes can be lost on a crash.
- Secrets: `GOOGLE_API_KEY`, `DSS_ACCESS_CODE` and (until release 4.5) `DSS_AGENT_TOKEN` come from Secret Manager as env
  vars; never in the image, the repo, the deploy script's output or the deck. With `DSS_PUBLIC=1`
  the service gets no `DSS_ACCESS_CODE` (1.6).
- Settings: on Cloud Run (agent mode) the API key and GCP values are fixed by the deployment;
  `PUT /api/settings` may change only model settings: stage profiles, fallback model and brief
  review (contracts/api.md 3.0).
- The runtime service account has BigQuery Data Editor and BigQuery Job User on `GCP_PROJECT_ID`,
  Secret Manager Secret Accessor on the secrets it gets, and Storage Object User on the state bucket;
  BigQuery on Cloud Run uses it as ADC. Without share data, the Google account signed into the
  agent's Chrome profile must be able to read `BQ_DATASET` (a project owner or BigQuery Data
  Viewer + Job User), so the report's data source can read the views; with share data (1.7) the
  report reads the public-read CSV instead.
- Share bucket (1.7): `<GCP_PROJECT_ID>-dss-share` in `GCP_REGION`, uniform bucket-level access,
  mounted at `/share` (`DSS_SHARE_DIR`); `allUsers` may read objects but never list them (only
  `storage.objects.get`: a custom role, never `roles/storage.objectViewer`, which lists); the
  runtime service account has Storage Object User on it. Objects stay until the owner closes the
  link (deploy/README.md deletes the bucket then; the visitors' reports lose their data).
- Sources on the open link (1.7): with `DSS_PUBLIC=1`, GCS and BigQuery sources are refused
  (`403 source_locked`), so a visitor can't read the owner's tables through the runtime service
  account; CSV upload, research and screenshot + synthetic stay. A visitor's own BigQuery or GCS
  data is PRD Later.
- Uploads through Cloud Run are limited to 32 MB per request (Cloud Run answers `413` itself).
- Shared by everyone who gets in: one history (no per-user data, POC). Each Build runs on the
  machine of whoever runs its job command, into that person's Data Studio account; builds don't
  wait on each other.

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
  application-default login`), so the report's data source can read the views. Cloud Run (1.7):
  with share data the report reads the public-read CSV, so any Google account works; without it
  (the owner's own deploy) see Cloud deployment.
