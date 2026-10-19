# PRD: release
Target: POC · Written 2026-10-18 · Kind: a part of a program (docs/program.md)

## Problem
Three parts built in parallel only become a hackathon entry when they start with one command,
pass one end-to-end flow, and ship as a clean GitHub repo with a deck that explains them.

## Users
- The user: runs `./start.sh`, rehearses and gives the demo, pushes the repo.
- Hackathon judges: read the README and the submission deck, open the hosted app with the access
  code, may run it locally.

## Goals
1. `./start.sh` (and `./start.ps1`) starts backend and frontend; `.env.example` lists every name
   in contracts/conventions.md.
2. `integration/e2e_flow1.py` proves flow 1 against the running parts (dry-run engine, and `--live`).
3. README: what it is, prerequisites, one-command start, first-time Google sign-in, demo script.
4. The submission deck (change 2026-10-19): the AI Builder Cup template
   (`Submission Template _ AI Builder Cup.pptx`) filled in every section, with the architecture
   (parts, harness, ADK graph, token economy, recipe engine, Cloud Run) as HTML-rendered diagrams;
   delivered as `deck/AI-Builder-Cup-Submission.pptx` and `.pdf`.
5. The repo is ready to push: one git repo, no secrets, no runtime data.
6. Cloud Run (change 2026-10-19): a root Dockerfile and `deploy/deploy.sh` deploy the app as one
   service per contracts/conventions.md#Cloud deployment; flow 1 passes against the deployed URL
   with the local build agent.

7. Required: reference-image recreation/style and unsupported-request refusal pass task 3.3
   locally and on the hosted API before release acceptance.

8. Release acceptance proves screenshot-only -> generated CSV -> BigQuery -> labeled dashboard
   locally and hosted, including persisted CSV download after service restart.

## Non-goals
- No code in the parts: the release never edits engine/, backend/ or frontend/ (program rule).
- No CI; no Terraform or other IaC beyond `deploy/deploy.sh`; no custom domain, IAP or second
  instance (program non-goals).
- No PRESENTATION.md: the cup's template is the deck.
- No `dist/` export: the repo itself is the deliverable.
- No pushing to GitHub: the user pushes.

## Core flows
1. User runs `./start.sh` -> backend on 8000, frontend on 5173 -> opens http://localhost:5173.
2. `uv run --project integration python integration/e2e_flow1.py --live` -> sample CSV -> scripted
   interview -> prototype -> one comment -> recipe -> engine -> prints the Data Studio link.

## Features
| Must | Should | Won't (this version) |
|---|---|---|
| start scripts, .env.example, .gitignore, LICENSE, sample CSV | demo rehearsal notes in README | CI |
| contract check, e2e flow 1 (local and deployed) | | IaC |
| README, submission deck (pptx + pdf), git-ready repo | | dist/ bundle |
| Dockerfile, deploy.sh | | |

## Constraints
- Deadline 2026-10-23 01:05 MPST (moved 2026-10-19 and 2026-10-20); deck draft early on 2026-10-19, final deck
  and submission by 00:45 on 2026-10-23 (docs/program.md roadmap).
- PowerPoint (for `deck/build_deck.ps1`) and Chrome on the build machine; the gcloud CLI signed in
  to the user's GCP project for the deploy.
- Windows 11 with Git Bash and PowerShell; Python 3.12 + uv; Node 20+.

## Success criteria
- `uv run --project integration python integration/check_contracts.py` passes.
- `e2e_flow1.py --live` prints a `https://datastudio.google.com/` link that opens the dashboard.
- `git status` after `git init` shows no `.env`, `data/` or `.chrome-profile/`.
- `e2e_flow1.py --server <Cloud Run URL> --live` prints a Data Studio link.
- `integration/check_deck.py` passes without `--draft`.

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

## Open questions
- none

## Later
- Multi-instance Cloud Run with a managed database (change 2026-10-19).
- CI running every part's tests (program, next version).
