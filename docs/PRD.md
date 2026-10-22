# PRD: release
Target: POC · Written 2026-10-18 · Kind: a part of a program (docs/program.md)

## Problem
Three parts built in parallel only become a hackathon entry when they start with one command,
pass one end-to-end flow, and ship as a clean GitHub repo with a deck that explains them.

## Users
- The user: runs `./start.sh`, does the manual acceptance, gives the demo, approves each push.
- Hackathon judges: read the README and the submission deck, open the hosted app with the access
  code, may run it locally.

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
   https://dss-frontend-872000338860.asia-southeast1.run.app serves the full app; flow 1 passes
   against it with the local build agent.

7. Required: reference-image recreation/style and unsupported-request refusal pass task 2.5
   locally and task 4.3 on the hosted API before release acceptance.

8. Release acceptance proves screenshot-only -> generated CSV -> BigQuery -> labeled dashboard
   locally and hosted, including persisted CSV download after service restart.
9. Manual acceptance (change 2026-10-20 final phases): before anything is published, the user
   builds one dashboard per source through the local UI and marks each PASS in
   docs/acceptance.md: CSV upload, research mode, BigQuery table and CSV in GCS right after the
   live e2e (2.4), screenshot + synthetic data once the reference work is in (2.6).

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
- `e2e_flow1.py --server <Cloud Run URL> --live` prints a Data Studio link.
- docs/acceptance.md has a user-confirmed PASS row with a Data Studio link for each of the five
  sources.
- `git ls-remote origin main` equals local `HEAD` after the final push.
- `curl -s https://dss-frontend-872000338860.asia-southeast1.run.app/api/health` returns ok (today
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

## Open questions
- none

## Later
- Multi-instance Cloud Run with a managed database (change 2026-10-19).
- CI running every part's tests (program, next version).
- Connect stage: a GCS source added with 201 shows in the list without a reload (frontend; release 2.4 P2, change 2026-10-22).
