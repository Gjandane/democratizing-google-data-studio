# PRD: release
Target: POC · Written 2026-10-18 · Kind: a part of a program (docs/program.md)

## Problem
Three parts built in parallel only become a hackathon entry when they start with one command,
pass one end-to-end flow, and ship as a clean GitHub repo with a deck that explains them.

## Users
- The user: runs `./start.sh`, does the manual acceptance, gives the demo, approves each push.
- Hackathon judges: read the README and the submission deck, open the hosted app (an open link,
  no sign-in, change 2026-10-29) and build into their own Data Studio with the setup command, may
  run it locally.

## Goals
1. `./start.sh` (and `./start.ps1`) starts backend and frontend; `.env.example` lists every name
   in contracts/conventions.md.
2. `integration/e2e_flow1.py` proves flow 1 against the running parts (dry-run engine, and `--live`).
3. README (change 2026-10-20 final phases): a short pitch (your own UI/UX designer, data analyst
   and programmer building the dashboard with you), features, capabilities, a simplified
   architecture with three diagrams (the ADK node graph, the harness with its three memories and
   OKF instead of RAG, the Google Cloud deployment), then prerequisites, one-command start,
   first-time Google sign-in and the links (GitHub repo, hosted app).
4. The submission deck (change 2026-10-19): the AI Builder Cup template
   (`Submission Template _ AI Builder Cup.pptx`) filled where 1.3 could (4 slides still say TBD), with the architecture
   (parts, harness, ADK graph, token economy, recipe engine, Cloud Run) as HTML-rendered diagrams;
   delivered as `deck/AI-Builder-Cup-Submission.pptx` and `.pdf`. The 1.3 draft is final: no
   further deck work (change 2026-10-20 final phases, user choice); the 3.2 STOP asks whether the
   deck files ship as they are or stay out of the repo.
5. The repo is pushed to https://github.com/Gjandane/democratizing-google-data-studio (`main`):
   one git repo, no secrets in its history, no runtime data, every `.env.example` with names only;
   the builder pushes after the user confirms on a card.
6. Cloud Run (change 2026-10-19), last (change 2026-10-20 final phases): a root Dockerfile and
   `deploy/deploy.sh` deploy the app as service `dss-frontend` per
   contracts/conventions.md#Cloud deployment, so the submitted URL
   (`DSS_AGENT_SERVER` in .env, shared privately, never in the repo) serves the full app as an
   open link scaling to zero; flow 1 passes against it up to the compiled recipe (4.2, 4.3), and
   after the redeploy for judge builds (4.5) a visitor builds into their own Data Studio account
   through one copied setup command (change 2026-10-29 local agent per judge).

7. Required: reference-image recreation/style and unsupported-request refusal pass task 2.5
   locally and task 4.3 on the hosted API (up to the recipe) before release acceptance.

8. Release acceptance proves screenshot-only -> generated CSV -> BigQuery -> labeled dashboard
   locally, and up to the labeled prototype and recipe hosted, including persisted CSV download after service restart.
9. Manual acceptance (change 2026-10-20 final phases): before anything is published, the user
   builds one dashboard per source through the local UI and marks each PASS in
   docs/acceptance.md: CSV upload, research mode, BigQuery table and CSV in GCS right after the
   live e2e (2.4), screenshot + synthetic data once the reference work is in (2.6).
10. Judge path (change 2026-10-29 local agent per judge): `agent-setup/setup.ps1` (Windows,
   tested) and `agent-setup/setup.sh` (macOS/Linux, untested) install the one-shot agent per
   contracts/conventions.md 1.7 (Build agent); the user proves it in a private window with a
   second Google account that can't read the owner's BigQuery, and the report lands in that
   account with data (4.6). The link is closed by hand after judging ends 2026-11-07.
11. First-visit onboarding (change 2026-10-31): the hosted link is redeployed with frontend 20.1-20.2,
   so a visitor learns on the home page that Build needs the local build agent and can set it up
   there before the first build; README's hosted section says so (4.8).
12. Demo video (change 2026-10-31 demo video): a ~4-minute screen-capture demo for the judges,
   on-screen captions and callouts over the user's background music, no voiceover: a fresh live
   run on samples/ecommerce_sales.csv through to the real Data Studio report, brief mentions of
   the other sources, prototype edits, the feasibility refusal, traces and token costs, the
   screenshot recreation and the architecture (docs/demo-video.md). The MP4 is a local,
   git-ignored file the user uploads; scripts and storyboard are committed (5.1-5.3).

## Non-goals
- No code in the parts: the release never edits engine/, backend/ or frontend/ (program rule).
- No CI; no Terraform or other IaC beyond `deploy/deploy.sh`; no custom domain, IAP or second
  instance (program non-goals).
- No PRESENTATION.md: the cup's template is the deck.
- No `dist/` export: the repo itself is the deliverable.
- No push without the user's confirmation on a card; never a force push or a history rewrite
  (a secret found in history is a STOP for the user).
- No further deck work: no snapshots, benchmark slide or links slide (change 2026-10-20).
- No separate architecture document: features and the simplified architecture live in README.md.
- No GCS or BigQuery sources on the open link, no uploads over 32 MB, no automatic closing of the
  link (change 2026-10-29 local agent per judge; the parts' PRD Later lists hold the first two).
- Demo video (change 2026-10-31): no voiceover or TTS, no hosted URL on screen, no committed MP4,
  no upload to YouTube or the submission by a builder, no music download by a builder (the user
  supplies the track), no push in Phase 5 unless the user asks.

## Core flows
1. User runs `./start.sh` -> backend on 8000, frontend on 5173 -> opens http://localhost:5173.
2. `uv run --project integration python integration/e2e_flow1.py --live` -> sample CSV -> scripted
   interview -> prototype -> one comment -> recipe -> engine -> prints the Data Studio link.
3. The user, in the local UI, builds one dashboard per source and records it in
   docs/acceptance.md -> README -> push -> deploy to `dss-frontend` -> final push.

## Features
| Must | Should | Won't (this version) |
|---|---|---|
| start scripts, .env.example, .gitignore, LICENSE, sample CSV | demo rehearsal notes in README | CI |
| contract check, e2e flow 1 (local and deployed) | | IaC |
| README (pitch, features, architecture), pushed repo, manual acceptance of five sources | | dist/ bundle |
| Dockerfile, deploy.sh | | deck snapshots, benchmark, links slide |

## Constraints
- Deadline 2026-10-23 01:05 MPST (moved 2026-10-19 and 2026-10-20); deck draft early on 2026-10-19, final deck
  and submission by 00:45 on 2026-10-23 (docs/program.md roadmap).
- PowerPoint (for `deck/build_deck.ps1`) and Chrome on the build machine; the gcloud CLI signed in
  to the user's GCP project for the deploy.
- Windows 11 with Git Bash and PowerShell; Python 3.12 + uv; Node 20+.

## Success criteria
- `uv run --project integration python integration/check_contracts.py` passes.
- `e2e_flow1.py --live` prints a `https://datastudio.google.com/` link that opens the dashboard.
- `uv run --project integration python integration/check_repo.py` passes before each push.
- `e2e_flow1.py --server <Cloud Run URL> --until recipe` compiles a recipe, and Build answers
  `424 agent_offline`.
- docs/acceptance.md has a user-confirmed PASS row with a Data Studio link for each of the five
  sources.
- `git ls-remote origin main` equals local `HEAD` after the final push.
- `curl -s "$DSS_AGENT_SERVER/api/health"` returns ok (today
  it returns the frontend's index.html).

## Decided by default
- Sample data: `samples/ecommerce_sales.csv`, 2,000 rows from a seeded generator
  (`integration/make_sample.py`, seed 42), so every run of the demo uses identical data.
- License: MIT. The planning docs ship in the repo (they show the process to judges).
- The release has its own tiny uv project in `integration/` (httpx, jsonschema) so its checks
  don't depend on another part's environment.

- Reference/capability change 2026-10-19 defaults: one recreation screenshot or 1-3 style
  images per version; explicit substitutions, curated capability evidence, existing dependencies.
  Closest supported recreation and release priority are user decisions, not defaults.

- Synthetic-data defaults (change 2026-10-19): 1,000 rows, seed 42; bounded stdlib generators;
  local DSS_DATA_DIR or existing GCS-backed /data volume; one new synthetic dataset in an empty
  build, no mixing with real data. User requested schema/count parameterization and sample CSVs.

- Manual acceptance inputs (change 2026-10-20 final phases): CSV = samples/ecommerce_sales.csv;
  research = one prompt written in docs/acceptance.md before the run; screenshot =
  samples/reference-dashboard.png (from 2.5) with no CSV, so synthetic data is generated;
  BigQuery = `bigquery-public-data.thelook_ecommerce.order_items` (US, same location as the
  default `BQ_LOCATION`), or a table the user names; GCS = samples/ecommerce_sales.csv copied to
  `gs://$GCS_BUCKET/samples/`. Fixed inputs keep the rows repeatable.

- Demo video defaults (change 2026-10-31): captions <= 2 lines x 42 chars at >= 0.33 s per word;
  1920x1080 30 fps H.264 + AAC, burned-in captions plus an SRT; music about -16 LUFS; the
  screenshot segment reuses an existing finished build so it costs no model calls.

## Open questions
- none

## Later
- Multi-instance Cloud Run with a managed database (change 2026-10-19).
- CI running every part's tests (program, next version).
- Connect stage: a GCS source added with 201 shows in the list without a reload (frontend; release 2.4 P2, change 2026-10-22).
- Slider control (Data Studio sliders take number fields only; the year slider also needs a numeric year), per-chart filters (one chart per country) and a single highlighted bar (2011): release 2.6 change requests, deferred (change 2026-10-24).
- A user-set designer output cap with a warning when a page design is cut off: declined on the card (change 2026-10-24); the designer used 769-3,002 of its 16k output.
- Frontend dead end after Remove references with every issue dropped (Regenerate disabled, no Check feasibility): release 2.6 gotcha, not yet planned (change 2026-10-24).
- Release 2.6 Known weaknesses W1-W7 (docs/acceptance.md, build b_236ae4aa34ee): the user accepted
  the screenshot recreation as PASS with findings and put GitHub and Cloud Run first; each fix goes
  to its owner part in a later version (change 2026-10-29): engine W1-W3 (engine/docs/PRD.md
  Later), backend W5-W7 (backend/docs/PRD.md Later), and W4, a contract change at the program
  root: recipe 1.4 `date_granularity` on `bar` with a DATE dimension (engine applies it first,
  backend emits it after).
- Release 2.7 and 2.8, e2e driver upkeep (change 2026-10-29, user deferred them to reach Cloud Run):
  2.8's waits per action from `GET /api/settings` stage clocks instead of a fixed 600 s (blueprint
  3,900 s, design confirm 900 s, reference upload 900 s on the fixture) and check_contracts
  validating the stage-settings fixtures and events.review.sse; 2.7's full local live pass of
  `e2e_references.py --cases synthetic,recreate`. Its code is committed; the open point was the
  synthetic v2 GPS refusal reading `stale`, ruled for 4.3 as a refusal when the GPS issues stay
  unresolved, and backend returning `blocked` after an outline Other on a built version is a
  backend item (backend/docs/PRD.md Later). The bench `server_url: "hosted"` mask moved into 4.2/4.3.
- (Planned now, change 2026-10-29 local agent per judge: release 4.4-4.6 with backend 29.x,
  frontend 19.x, engine 14.x.) Hosted Data Studio builds in each visitor's own account.
- A zero-Python agent (docs/v2-handoff.md) instead of the uv-installed `dss-agent`: still a later
  option; this version ships the uv agent (change 2026-10-29 local agent per judge).
- An automatic reminder or scheduled teardown for closing the link after 2026-11-07 (the 4.7
  STOP offers the user a reminder; closing stays manual).
