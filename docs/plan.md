# Plan: release
Target: POC · Audit: done 2026-10-18 (18 findings across the program, 18 applied); change 2026-10-19 (deck from the cup template, Cloud Run; delta audit 33 findings, all applied)
Markers: [ ] to do, [~] in progress, [x] done, [!] blocked. Only blueprint.py changes them.
Sizes: S small, M a normal session, L needs a whole fresh session (never run unattended).

## Phase 1: Root files and the deck draft
- [x] 1.1 Root files, sample data and contract check
  - Goal: the integration uv project, `.env.example`, `.gitignore`, LICENSE, the seeded sample CSV and the contract check, so Test (all) is real.
  - Files: integration/pyproject.toml, integration/make_sample.py, integration/check_contracts.py, samples/ecommerce_sales.csv, .env.example, .gitignore, LICENSE
  - Depends on: none
  - Size: S
  - Done when: `uv run --project integration python integration/check_contracts.py` passes: every line of contracts/fixtures/recipe.sample.jsonl and events.sample.jsonl validates against contracts/recipe.schema.json, a mutated op (`chart_type: "donut"`) is rejected; every JSON file in contracts/fixtures/api/ parses, events.sse holds only event names listed in contracts/api.md, prototype.sample.html has `#dss-canvas` and every `data-cid` element has `data-label` and `data-kind`; every env name in contracts/conventions.md appears in .env.example, with secrets (`GOOGLE_API_KEY`, `DSS_ACCESS_CODE`, `DSS_AGENT_TOKEN`) and `DSS_DB_PATH` empty; `.gitignore` also ignores `~$*` (Office lock files) and `deck/render/`; `uv run --project integration python integration/make_sample.py --check` regenerates samples/ecommerce_sales.csv byte-identical (seed 42, 2,000 rows, columns order_id, order_date, region, country, category, product_name, customer_segment, quantity, unit_price, revenue).
- [x] 1.2 Architecture diagrams as HTML, rendered to PNG
  - Goal: the deck's 8 diagrams as self-contained HTML pages and a script that renders each to a PNG with headless Chrome, so the architecture reads as real visuals in the pptx.
  - Files: deck/diagrams/_base.css, deck/diagrams/fonts/*, deck/diagrams/d1-solution.html, deck/diagrams/d2-process-flow.html, deck/diagrams/d3-parts.html, deck/diagrams/d4-harness-memory.html, deck/diagrams/d5-adk-graph.html, deck/diagrams/d6-token-economy.html, deck/diagrams/d7-recipe-engine.html, deck/diagrams/d8-cloud-run.html, integration/render_diagrams.py, deck/img/*.png
  - Depends on: 1.1
  - Size: M
  - Done when: `uv run --project integration python integration/render_diagrams.py` exits 0 and writes deck/img/<name>.png for every deck/diagrams/d*.html, each exactly 3680x1600 px (a 1840x800 CSS viewport at device scale 2, read from the PNG header), newer than its HTML and `_base.css`; two consecutive runs give identical PNG bytes for each diagram (no network fonts: the font is vendored or Arial; Chrome runs with `--virtual-time-budget=5000`); manual: open each PNG: no clipped or overlapping text, smallest label at least 14 CSS px, boxes and arrows aligned, a feature whose task isn't `[x]` in its part's plan (`blueprint.py program`) carries a small "planned" tag, and the content is: d1 user -> interview -> HTML prototype with comments -> compiled recipe -> real Data Studio dashboard; d2 flows 1 and 3 by stage (Connect, Interview, Plan, Prototype + comments, Build, Done; History -> new version) with the part that does each step; d3 the parts (frontend, backend, engine, release) with ports, contracts/ files and external services (Gemini API, BigQuery, Data Studio); d4 harness-architecture.md's run, working memory and three memory stores mapped to this build (procedural = skills/*.md, semantic = OKF bundle, episodic = SQLite + FTS5, consolidation after every 5 builds by the worker model, one trace per run, LLM Ops loop); d5 the ADK Workflow: START -> router(action) -> branches with LLM nodes interview, plan, spec, revise, consolidate (stretch: ux_audit, style_extract, research) and code nodes intake, view, validate, render, compile, execute, publish, the validate -> spec/revise repair loop (at most 2) and a guardrail at every exit, planner model on plan and spec only; d6 the token levers (spec as truth, grid layout, JSON-patch comments, compiled recipe, background image, per-node context recipes, model routing, OKF instead of RAG); d7 spec -> recipe.jsonl (three real lines from contracts/fixtures/recipe.sample.jsonl) -> `dsengine run` -> Playwright on the signed-in Chrome -> Data Studio, BigQuery view as the data source, the closed 12-type catalog; d8 Cloud Run service `dss` (backend + built frontend, one instance) with the GCS volume `/data`, Secret Manager, BigQuery via the runtime service account, Gemini API, the access code, and `dss-agent` + Chrome + `dsengine` on the user's machine pulling jobs to build in Data Studio.
  - If: Chrome isn't found -> the script takes `DSS_CHROME_PATH` from .env, then the standard install paths, and fails with a message naming both.
  - If: the template's font (Google Sans Flex) may not be redistributed or isn't available as a file -> use Arial in the diagrams and record it under Decisions.
- [~] 1.3 Submission deck draft from the AI Builder Cup template
  - Goal: `deck/build_deck.ps1` fills the cup's template with `deck/content.json` (every slide's text, images and speaker notes) and writes `deck/AI-Builder-Cup-Submission.pptx` and `.pdf`; the original template stays unchanged.
  - Files: deck/content.json, deck/build_deck.ps1, integration/check_deck.py
  - Depends on: 1.2
  - Size: M
  - Done when: `powershell -ExecutionPolicy Bypass -File deck/build_deck.ps1` exits 0, and `uv run --project integration python integration/check_deck.py --draft` passes: it reads the expected section titles and the brand images from `Submission Template _ AI Builder Cup.pptx` itself (no hardcoded title strings) and checks the output has 17-21 slides, the template's section titles in the template's order with the template's "Note: Please download" slide and its blank frame slide removed and the optional cost slide either kept or removed, 6 added slides right after the Architecture slide titled Parts and data flow, The harness: three memories, ADK graph and repair loop, Token economy, Recipe and engine, and Cloud Run deployment; every slide between Team Details and Thank you has a picture besides the brand images or at least 25 words of body text; no slide has more than 90 words of body text; every deck/img PNG used is newer than its HTML; `TBD` only with `--draft`; the PDF has the same page count; the template's SHA-256 still equals the baseline in docs/progress.md (change 2026-10-19 entry); manual: `deck/build_deck.ps1 -Png` exports every slide to deck/render/; view each: no text overflow, titles at the template's title position and font, diagrams fill the content area below the header bar without distortion, body text left-aligned.
  - If: writing build_deck.ps1 -> PowerPoint COM rules: `New-Object -ComObject PowerPoint.Application` may attach to the user's running PowerPoint, so close only the presentations the script opened and call `Quit()` only if `Presentations.Count` is 0 afterwards (in `finally`); open the template read-only, untitled and without a window, then `SaveAs` the output; make the added slides with `Slide.Duplicate()` of the template's Architecture slide (keeps the header bar and brand images); read content.json with `Get-Content -Raw -Encoding UTF8` and save the .ps1 as UTF-8 with BOM (PowerShell 5.1).
  - If: a template text box is too small for its content -> shorten the text in content.json; never shrink text below the template's own size.
  - If: PowerPoint has the output file open -> the script fails with that message; it never kills PowerPoint.
  - If: Google Sans Flex isn't installed -> PowerPoint substitutes it in the pptx view and the PDF; note it under Decisions and in README.

## Phase 2: Local integration
- [ ] 2.1 Start scripts
  - Goal: `./start.sh` and `./start.ps1` start backend and frontend with the commands from their AGENTS.md and stop both on Ctrl+C.
  - Files: start.sh, start.ps1
  - Depends on: 1.1
  - Size: S
  - Needs: backend 1.1; frontend 1.1
  - Done when: manual: `./start.sh` in Git Bash and `./start.ps1` in PowerShell each print both URLs, `curl -s localhost:8000/api/health` returns ok and http://localhost:5173 loads; Ctrl+C leaves no process listening on 8000 or 5173 (`netstat -ano | grep -E ":(8000|5173) "` prints nothing).
- [ ] 2.2 End-to-end flow 1 and 3, dry-run engine
  - Goal: `integration/e2e_flow1.py` drives flow 1 through the API (sample CSV, scripted interview of 3 answers, plan, one comment, recipe, run) and, with `--version2`, flow 3 (new version, one comment, run) against the backend with `DSS_ENGINE_DRY_RUN=1`; it prints seconds per stage and the run's token totals from `GET /api/traces?build_id=`, and writes them to `deck/data/bench-<UTC date>-<mode>.json` (the deck's benchmark source).
  - Files: integration/e2e_flow1.py, deck/data/*.json
  - Depends on: 2.1
  - Size: M
  - Needs: backend 4.2; backend 4.4; engine 1.1
  - Done when: with the parts started by `./start.sh` and `DSS_ENGINE_DRY_RUN=1` in .env, `uv run --project integration python integration/e2e_flow1.py --version2` exits 0, prints each stage reached for v1 and v2, a table of seconds per stage and input/output token totals, and writes the bench JSON with the same numbers, the server URL, the mode and the run date; it never prints the access code.
  - If: a step fails inside a part -> block this task with the part, the step and the API error body; never patch the part from here.
- [ ] 2.3 End-to-end live build and UI walkthrough
  - Goal: the same flow with the real engine and the signed-in profile, plus the demo clicked through the UI.
  - Files: integration/e2e_flow1.py, deck/data/*.json
  - Depends on: 2.2
  - Size: S
  - Needs: engine 3.1; frontend 3.2
  - Done when: with `DSS_ENGINE_DRY_RUN=0` and the signed-in profile, `uv run --project integration python integration/e2e_flow1.py --live` exits 0, prints a `https://datastudio.google.com/` link and writes its bench JSON; manual: the link opens the dashboard with charts over the background; the same flow clicked through the UI at http://localhost:5173 reaches the link.
  - If: engine chart ops fail for some types -> narrow `DSS_ALLOWED_TYPES` in .env to the types that pass, rerun, and record it under Decisions.
  - If: frontend 6.1 and backend 10.1 are done -> the UI walkthrough also checks that the activity strip shows a phrase, the elapsed time and a growing token count during plan, and the plan checklist ends all ticked; otherwise skip this (it is first in the cut order).

## Phase 3: Cloud Run
- [ ] 3.1 Dockerfile and Cloud Run deploy script
  - Goal: a root `Dockerfile` that builds the frontend and runs the backend on `$PORT`, and `deploy/deploy.sh` that sets up the GCP resources idempotently and deploys the service per contracts/conventions.md#Cloud deployment.
  - Files: Dockerfile, .dockerignore, .gcloudignore, deploy/deploy.sh, deploy/README.md
  - Depends on: 1.1
  - Size: M
  - Needs: backend 5.1; frontend 5.1
  - Done when: `gcloud meta list-files-for-upload` lists no path under `.env`, `data/`, `.chrome-profile/`, `.venv`, `node_modules`, `deck/` or `.blueprint/`; `bash deploy/deploy.sh --dry-run` prints every gcloud command without running it, exits 0, and `bash deploy/deploy.sh --dry-run | grep -cF "$DSS_ACCESS_CODE"` prints 0 (likewise for `DSS_AGENT_TOKEN` and `GOOGLE_API_KEY`); `bash deploy/deploy.sh` (after the STOP) enables the needed APIs, creates if missing the state bucket, the runtime service account with BigQuery Data Editor + Job User, Secret Accessor on the three secrets and Storage Object User on the bucket, grants the build service account `roles/run.builder`, creates the secrets `GOOGLE_API_KEY`, `DSS_ACCESS_CODE` and `DSS_AGENT_TOKEN` (values piped from the local .env, never echoed), and runs `gcloud run deploy dss --source . --quiet` with gen2, one instance, `--no-cpu-throttling`, timeout 3600, a startup probe on `/api/health`, the bucket mounted at `/data` and the env of this part's essentials, then prints the URL; `curl -s $URL/api/health` returns ok, `curl -s -o /dev/null -w "%{http_code}" $URL/api/builds` prints 401, and the same call with `-H "X-DSS-Access-Code: $DSS_ACCESS_CODE"` prints 200; the Dockerfile's build runs a headless Chromium smoke screenshot, so a missing browser fails the build; manual: the URL shows the gate, then History; a build created before a redeploy is still listed after it; deploy/README.md has the teardown commands.
  - STOP: before the first real deploy, show the user the project, region, service, bucket, service account, the commands from `--dry-run` and the cost (one always-on instance with 2 vCPU and 2 GiB: roughly USD 100+ per month while it runs; teardown in deploy/README.md), and ask: it creates billable resources in their GCP project.
  - If: `DSS_ACCESS_CODE` is under 12 characters or `DSS_AGENT_TOKEN` under 24 in .env -> the script refuses to deploy.
  - If: backend 5.2 isn't done yet -> deploy anyway; the hosted Build fails until 3.2 redeploys with 5.2 and 5.3.
  - If: an organization policy blocks `allUsers` (allow-unauthenticated) -> stop and ask the user; never weaken the access code instead.
- [ ] 3.2 Deployed end-to-end through the local build agent
  - Goal: redeploy with the agent endpoints, then `e2e_flow1.py --server <URL>` runs flow 1 against the deployed service with the access code while `dss-agent` runs locally, first in dry-run and then live.
  - Files: integration/e2e_flow1.py, deck/data/*.json
  - Depends on: 3.1; 2.3
  - Size: S
  - Needs: backend 5.2; backend 5.3; frontend 5.1
  - Done when: after `bash deploy/deploy.sh`, with `uv run --project backend dss-agent --server <URL> --dry-run` running locally, `uv run --project integration python integration/e2e_flow1.py --server <URL>` exits 0 with stage `done`; with the agent restarted without `--dry-run`, `uv run --project integration python integration/e2e_flow1.py --server <URL> --live` exits 0, prints a `https://datastudio.google.com/` link plus the seconds-per-stage table and token totals, and writes its bench JSON; manual: the same flow clicked through the UI at the URL reaches the link, and the Build stage shows the agent as connected.
  - If: the hosted run fails inside a part -> block this task with the part, the step and the API error body.

## Phase 4: Delivery
- [ ] 4.1 README
  - Goal: the root README for judges and for the user's own demo, local and hosted.
  - Files: README.md
  - Depends on: 2.1; 3.1
  - Size: S
  - Done when: manual: README has, in order, a one-paragraph pitch, the deck's d3 parts diagram (deck/img/d3-parts.png) and d8 Cloud Run diagram, the hosted demo (URL, "ask for the access code", that builds run only while the owner's build agent is online, otherwise the app stops at the recipe, and that everyone with the code shares one history), prerequisites (Chrome, Python 3.12 + uv, Node 20+, a GCP project with BigQuery, `gcloud auth application-default login`, a Gemini API key), install and `./start.sh` (a `DSS_ACCESS_CODE` in .env also gates the local app), the first-time Google sign-in (`dsengine login` via the Build stage button), running the build agent against the hosted URL (token in .env, never on the command line), deploying your own copy (`bash deploy/deploy.sh`, what it creates and costs, teardown, the 32 MB upload limit), a 6-step demo script with the sample CSV, a folder map naming each part and its docs, and links to deck/AI-Builder-Cup-Submission.pdf and .pptx; every command in it is copied from a part's AGENTS.md, deploy/README.md or this part's essentials.
- [ ] 4.2 Deck snapshots, benchmark and links
  - Goal: finish the deck with real screenshots, measured numbers, the team details and the submission links.
  - Files: deck/content.json, deck/img/*.png, deck/AI-Builder-Cup-Submission.pptx, deck/AI-Builder-Cup-Submission.pdf, integration/check_deck.py
  - Depends on: 1.3; 2.3
  - Size: S
  - Done when: `uv run --project integration python integration/render_diagrams.py` re-renders the diagrams with the "planned" tags current, then `uv run --project integration python integration/check_deck.py` (without `--draft`) passes: no `TBD`; Team name, Team leader name and Problem Statement are filled; the links slide has an `https://github.com/` repo URL, a demo video URL and the Cloud Run URL (`https://*.run.app`) labeled as the final product link with "access code on request; builds need the owner's agent online"; Snapshots shows at least 3 screenshots of the hosted app (Interview, Prototype with pins, Build with ops ticking) and 1 of the finished Data Studio dashboard; every number on the Performance and cost slides equals a value in a deck/data/bench-*.json file, shown with its run date; the cost slide shows only token counts from traces (a dollar figure only with a cited price page and date) or is removed; manual: every screenshot is cropped so no account email, avatar, access code or token is visible; view the rendered slides as in 1.3.
  - STOP: ask the user for the team name, team leader name, GitHub repo URL and the 3-minute demo video link; never invent them.
  - If: the hosted build was cut (docs/program.md cut order) or 3.2 isn't done -> run `check_deck.py --local-only`: screenshots from the local app, the links slide gives the Cloud Run URL with "hosted build: agent pending" or, without a deployment, "runs locally (see README)", and numbers from the 2.2/2.3 bench files only.
- [ ] 4.3 Repo ready to push
  - Goal: one git repo at this folder with no secrets or runtime data, ready for the user to push.
  - Files: .gitignore, .gitattributes
  - Depends on: 4.1; 4.2
  - Size: S
  - Done when: after `git init` and `git add -A`, `git status --porcelain` lists no path under data/, .chrome-profile/, node_modules/, .venv/, .blueprint/ or deck/render/, no `~$` file and no `.env`; `git grep -nE "AIza[0-9A-Za-z_-]{35}|BEGIN (RSA |EC )?PRIVATE KEY"` prints nothing; `git grep -nF "$DSS_ACCESS_CODE"` and `git grep -nF "$DSS_AGENT_TOKEN"` print nothing; no nested `.git` folder exists under engine/, backend/ or frontend/.
  - STOP: show the user the staged file list and ask before the first commit; the user pushes.
