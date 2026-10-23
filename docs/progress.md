# Progress log
Append-only handoff log: one entry per session, newest at the bottom, written for someone with no
context. Task status lives in docs/plan.md, not here.

## 2026-10-18: Plan Democratizing Google Data Studio program and release (POC)
- Status: done
- What changed: wrote docs/program.md, contracts/ (conventions, recipe + schema + fixtures, api), the program block and release block in AGENTS.md, CLAUDE.md, release PRD/essentials/plan (6 tasks), and every part's docs (engine 9 tasks, backend 15, frontend 10)
- Decisions: grilled at the root only and planned every part in one session (10-hour deadline); the Dashboard Spec JSON is the single source of truth and HTML/background/view/recipe are deterministic code; every source lands in BigQuery with one view per build version; engine = installed Chrome over CDP + OKF selectors, no LLM; folder mode during the build, git initialised by release 2.4.
- Baseline: new project: none
- Next: three parallel builder sessions (engine/, backend/, frontend/), plus release 1.1 here; start the engine first, it holds the riskiest spike (1.3).

## 2026-10-18: Audit
- Status: done
- What changed: one reviewer audit across the program (18 findings: 2 P0, 4 P1, 9 P2, 3 P3 plus a pass note); all 18 accepted by the user and applied to contracts/ and every part's docs
- Decisions: backend thin slice 1.3 before memory depth; engine must-have ops by 21:00 with DSS_ALLOWED_TYPES as fallback; shared API fixtures in ../contracts/fixtures/api/; no uvicorn --reload on Windows; gates written into docs/program.md's roadmap
- Next: build, starting with task 1.1

## 2026-10-19: Change deck from the cup template, Cloud Run deployment
- Status: done
- What changed: user asked to (1) fill `Submission Template _ AI Builder Cup.pptx` instead of PRESENTATION.md, with HTML-rendered architecture diagrams, and (2) deploy to Cloud Run; the deadline moved to 2026-10-20 01:05 MPST. Edited contracts/conventions.md and contracts/api.md (both 1.1), new fixtures session.json, engine_status.json, engine_status.local.json, agent_job.json; docs/program.md (goals, flow 4, delivery, roadmap, cut order, decision log), AGENTS.md (program block, release intro); this part's PRD, essentials and plan (11 tasks: deck tasks 1.2-1.3 early, start scripts and e2e 2.1-2.3, Cloud Run 3.1-3.2, delivery 4.1-4.3). Delta audit by the reviewer: 33 findings (9 P1), all accepted and applied across the parts.
- Decisions: deck built by deck/build_deck.ps1 through PowerPoint COM (no new dependency; PowerPoint export checked on this machine), diagrams as HTML rendered by headless Chrome, plus a PDF; Cloud Run = one service (backend serves frontend/dist), one instance, shared access code, GCS volume with SQLite on /tmp backed up every 30 s, engine local through backend's `dss-agent` with its own token; Docker bases python:3.12-slim-bookworm and node:20-bookworm-slim, uv from PyPI (verified 2026-10-19).
- Template baseline: `Submission Template _ AI Builder Cup.pptx` SHA-256 4b749f59f68d927b5ea99023b574999e3ecae506673b5bfbc229b05ee149eadb (2026-10-19); task 1.3's check compares against it.
- Affects: release all tasks; backend 5.1-5.3 (new), 6.x/7.x (renumbered); frontend 5.1 (new); engine none (PRD wording only).
- Next: release 1.1, then 1.2 and 1.3 (no gates); backend task 1.1 is the program's critical path.

## 2026-10-19: Task 1.1 Root files, sample data and contract check
- Status: done
- Plan check: off
- What changed: new integration/ uv project (pyproject, uv.lock), make_sample.py (seeded CSV + `--check`), check_contracts.py (Test (all), 9 checks); samples/ecommerce_sales.csv; .env.example, .gitignore, MIT LICENSE.
- Checks: `make_sample.py --check` PASS (2000 rows, sha256 573c7a35406e1099..., also on py3.11); Test (all) `check_contracts.py` PASS 9/9; 17 mutation cases in a scratch copy all FAIL as expected.
- Decisions: .env.example holds the conventions' non-secret defaults, secrets and DSS_DB_PATH empty; DSS_ENGINE_CMD quoted (bash `source` + dotenv); `.gitignore` anchors `/data/` so deck/data/ and parts' data/ fixtures stay tracked; own `date-time` format checker (UTC with Z), no rfc3339-validator; check also enforces increasing op ids, `build.op` data vs event schema, data-cid unique/not nested/snake case; CSV: one order per row, 2026-01-01..09-30, 4 regions' countries, 4 categories x 5 products, integer-cents money, `\n` endings; uv.lock generated (outside Files, needed for repeatable runs); LICENSE holder "Democratizing Google Data Studio contributors" until 4.2 gives the team name; AGENTS.md: added the Chrome-lockfile gotcha.
- Tried and failed: none
- Gotchas: in AGENTS.md Known gotchas.
- Left open: P3 sample `--check` fails on a Windows clone with autocrlf - task 4.3 .gitattributes needs `samples/*.csv -text` (or `* text=auto eol=lf`) and `*.sh eol=lf`.
- Next: Task 1.2 (diagrams as HTML -> PNG); 1.3 after it. 2.1 needs backend 1.1 and frontend 1.1.

## 2026-10-19: Task 1.2 Architecture diagrams as HTML, rendered to PNG
- Status: done
- Plan check: off
- What changed: deck/diagrams/_base.css + d1..d8 HTML pages (absolute boxes, one inline SVG arrow layer each); integration/render_diagrams.py (headless Chrome, throwaway profile per page, checks PNG header 3680x1600, exit 1 on any failure); deck/img/d1..d8 PNGs.
- Checks: `render_diagrams.py` PASS 8/8, exit 0; second run sha256-identical for all 8; every PNG newer than its HTML and _base.css; bad DSS_CHROME_PATH -> clear error, exit 1; no http/@import/url() refs; Test (all) `check_contracts.py` PASS 9/9; manual: all 8 PNGs viewed, no clipped/overlapping text, min font 14px.
- Decisions: Arial (Google Sans Flex not available as a local file; deck/diagrams/fonts/ left empty); "planned" tags derived from part plans at 2026-10-19 (backend 1.1-1.3, 2.1, 3.1 done; engine, frontend all done); partial features tagged by piece ("full compiler: planned", "real run: planned", "FTS5 retrieval: planned"); Chrome from env DSS_CHROME_PATH, then .env (only that key read), then standard paths; built in-session rather than delegated (content needed the harness/program context).
- Tried and failed: none
- Gotchas: in AGENTS.md Known gotchas (planned tags drift).
- Left open: none
- Next: Task 1.3 (deck draft from the cup template). Re-check planned tags against `blueprint.py program` first and re-render.

## 2026-10-19: Task 1.3 Submission deck draft from the AI Builder Cup template
- Status: done
- Plan check: off
- What changed: deck/content.json (every slide's text, image, notes), deck/build_deck.ps1 (COM fill, pptx + pdf, `-Png` QA renders), integration/check_deck.py (stdlib); deck/AI-Builder-Cup-Submission.pptx/.pdf (19 slides). Outside Files: stale "planned" tags fixed in deck/diagrams d1,d2,d3,d5,d7 (backend 3.2 done) and two tag overlaps (d2, d4), all PNGs re-rendered, as the 1.2 entry asked.
- Checks: `build_deck.ps1` exit 0; `check_deck.py --draft` PASS 12/12 (non-draft exits 1 on 4 TBD slides, expected); mutations (swapped added slides, 1-word body, touched HTML) each FAIL as expected; locked output -> clear message, exit 1; Test (all) `check_contracts.py` PASS 9/9; manual: all 19 renders in deck/render/ viewed: no overflow, titles at template position, diagrams 678pt wide undistorted, body left-aligned.
- Decisions: COM server is WPS Office (no MS PowerPoint): added slides via `Slides.InsertFromFile` from a temp copy of the template instead of `Duplicate()` (no-op in WPS); own slide-ID lookup; `Saved=-1` before Close; cost slide removed (no bench numbers yet; content.json `remove`); body 16pt Google Sans Flex in a new textbox at the title's left edge, bullets; Team Details kept from the template's own text (team Prisma, leader Jan Daniel Gonzalvo, typed into the template by the user), problem statement added; Future Development condensed from the template's 7 items to fit 90 words; WPS renders Google Sans Flex, so no substitution note needed here (MS PowerPoint without the font would substitute: README 4.1 should say so); text slides tag unbuilt features "planned".
- Tried and failed: `Slide.Duplicate()` (silent no-op), `InsertFromFile` on the open template (E_FAIL, empties deck), `Font.Size = 16` int (InvalidCast).
- Gotchas: in AGENTS.md Known gotchas (WPS COM).
- Left open: P3 essentials still say "PowerPoint installed" (architect to update: WPS) - docs/architecture-essentials.md; P3 freshness check skips images without an HTML source (screenshots) - integration/check_deck.py
- Next: Task 2.1 Start scripts.

## 2026-10-19: Change activity transparency (frontend, backend)
- Status: done
- What changed: user request: show what the agent is doing in the background (preset wording), elapsed time and tokens, like a coding agent's task list. contracts/api.md 1.1 -> 1.2 (`run.usage` event, `node` values), new fixture contracts/fixtures/api/events.usage.sse; program.md Contracts row, roadmap step and cut order (first to cut), two decision rows; new tasks backend 10.1 (S) and frontend 6.1 (M); release essentials Contracts row 1.2, release 2.3 gets an `If:` for the walkthrough. Fixed the 1.3 P3: essentials now say WPS Office.
- Affects: release 2.3 (optional walkthrough check). Release 2.1-2.2 unchanged; Test (all) `check_contracts.py` PASS 9/9 with the new fixture.
- Next: frontend 6.1 now; backend 10.1 after the backend final audit's fix tasks 9.1-9.7 (9.6 shares graph.py); release 2.1 in parallel.

## 2026-10-19: Change reference images and capability verification (release/program)
- Status: planned; scope confirmed, final plan review pending.
- User decisions: both features required this hackathon; closest supported recreation of layout/chart choices/style using connected data, with explained substitutions.
- What changed: API 1.3, dashboard-intent 1.0 and isolated shared fixtures; program/part PRDs, architecture/essentials and plans. Seven M tasks: backend 11.1-11.5, frontend 10.1, release 3.3. Existing task markers preserved. No product code changed in this planning session.
- Audit: five original gaps and five delta integration findings addressed; focused recheck found no remaining P1 contradictions, then requested task split (applied as 11.3-11.5). Full report: program-root docs/reference-capability-audit.md. Draft remains pending user review per architect skill.
- Decisions: dated product/app/data evidence; unknowns block; explicit durable substitutions; private replaceable reference sets per version; pending-comment recovery; distinct candidate views preserve old reports; required hosted acceptance redeploys tested source. No engine expansion or added dependency. New fixture folder avoids breaking legacy exhaustive API fixture inventories. Frontend full conventions/UI details moved into implementation-notes.md/reference-ui.md, essentials summarize.
- Checks: root check_contracts.py 9/9 PASS; frontend npm test -- contract 31/31 PASS. Planning lint/stamp run; final counts recorded in scope audit. No new behavior claimed tested; its acceptance commands belong to builders.
- Left open: seven sessions of M work may conflict with deadline; both remain required until user explicitly changes scope. Existing unrelated dirty source/deck files and historical progress entries preserved; no commit while draft review pending.
- Next: complete existing in-progress backend 9.7 and existing 10.1, then backend 11.1-11.5; frontend 10.1; release 3.3. Existing release infrastructure may proceed independently.

## 2026-10-20: Change cross-part gates, synthetic durability and deadline (release/program)
- Status: done
- User decisions: frontend 11.1 waits on backend 12.3; synthetic durability simplified, best-effort immediate backups; backend 12.4 rewritten as S; deadline 2026-10-23 01:05 MPST.
- What changed: settled backend's change request (backend progress 2026-10-20). contracts/synthetic-data.md 1.1 (generation table plus immediate backups after reservation and registration; startup fails in-flight jobs; no manifests); dashboard-intent.md status line names backend 11.1-11.8; program.md deadline, required-sequence paragraph, contracts row and three decision-log rows; AGENTS.md program-block deadline; root/frontend/backend PRD deadlines. Release 3.3 `Needs: backend 11.8; backend 12.4; backend 12.5; frontend 11.1`, its Done when names 12.4/12.5. Frontend 10.1 -> backend 11.8, 11.1 -> backend 12.3. Backend 12.4 rewritten; architecture#Synthetic data updated and stamped.
- Checks: `lint` 0 errors in release, backend and frontend; `program` 0 problems; waits: frontend 10.1 on backend 11.8, release 3.3 on backend 11.8/12.4/12.5 + frontend 11.1. No delta audit (POC target).
- Left open: release and frontend plan audits still pending from 2026-10-19; root and frontend essentials are slightly over one page (existing).
- Next: backend 10.1, then backend 11.x/12.x; frontend 10.1 after backend 11.8.

## 2026-10-20: Supplement screenshot-only synthetic data
- Status: supplement delivered to the current planning documents; no additional review requested.
- User direction: another architect is already reviewing; only supplement the changes.
- What changed in this continuation: docs/synthetic-data-supplement.md and this append-only progress entry. The supplement explains the no-CSV flow, schema/count/seed API example, reusable Python function/CLI, local/GCS-backed storage, current task ownership and acceptance reminders.
- Coordination: inspected the other architect's current task split (backend 12.1-12.5), synthetic-data.md 1.1 and latest program decisions. Those supersede this session's earlier v1.0 manifest draft; no shared plan/contract/architecture, task marker, approval status or deadline changed in this continuation.
- Checks: embedded request parses as JSON; row_count=1000 and the revenue product references preceding declared numeric columns. No implementation, live CSV generation, full test suite or duplicate audit claimed.
- Next: the existing architect review proceeds from current contracts/plans, with this supplement as explanatory context. No new build task or approval gate added.


## 2026-10-20: Change final phases (release/program)
- Request (user): audit the final steps once engine, backend and frontend are finished: local integration with the user's manual test of four dashboard types (CSV upload, research mode, screenshot recreation with synthetic data, BigQuery), then upload the consolidated working version to GitHub with empty env files and an md of features, capabilities and simplified architecture (graph engineering, harness with memories and OKF instead of RAG, Google Cloud diagrams) with a short pitch, and lastly deploy to Cloud Run; links: https://github.com/Gjandane/democratizing-google-data-studio and https://dss-frontend-872000338860.asia-southeast1.run.app.
- Found: the prod URL serves the static frontend only (`/api/health` returns index.html), service `dss-frontend`, project wti-bigquery-poc; local main is 52 commits ahead of origin/main (fast-forward); gcloud credentials expired; the cup template was modified (the user's team details); no large blobs or forbidden paths in history; 121 frontend screenshots tracked.
- User choices (cards): deploy the full image as `dss-frontend` (conventions.md 1.2); add GCS as a fifth manual source; the builder pushes after the user confirms; no further deck work.
- What changed: contracts/conventions.md 1.2 (service name); docs/program.md (Delivery, Final phases, Integration checks, decision log); docs/PRD.md (goals 3-9, non-goals, success criteria, acceptance inputs); docs/architecture-essentials.md; docs/plan.md phases 2-4 re-sequenced: 2.1-2.3 unchanged, 2.4 manual CSV/research/BigQuery/GCS (L), 2.5 local reference/refusal/synthetic e2e (L, old 3.3 local half), 2.6 manual screenshot + synthetic (S), 3.1 README (M), 3.2 repo ready and first push (S), 4.1 Dockerfile and deploy to dss-frontend (M), 4.2 hosted e2e (S), 4.3 hosted reference/synthetic (M, old 3.3 hosted half), 4.4 README hosted and final push (S); old 4.2 deck task removed. Stale IDs fixed in contracts/synthetic-data.md (planned-implementation line), docs/synthetic-data-supplement.md and frontend/docs/plan.md; parts' essentials list conventions 1.2.
- Change requests settled: none open in release.

## 2026-10-20: Audit (delta, final phases)
- Reviewer (blueprint-reviewer, opus, high): 1 blocker, 6 major, 6 minor; all 13 accepted by the user and applied.
- Applied: B1 deploy guard (project number 872000338860 and the existing service URL checked before any mutation; .env parsed, not sourced); M1 every deploy sets SA, port 8080, ingress all, full env and secrets, traffic to latest, rollback note; M2 history path and blob checks plus review of tracked images; M3 strip-safe secret scan that skips empty values (new integration/check_repo.py); M4 d5 shows the reference/capability/synthetic nodes, 4.4 refreshes d8; M5 STOPs in 2.5 and 4.3, sizes L; M6 manual test split so CSV/research/BigQuery/GCS run right after 2.3; m1 stale IDs and PRD wording; m2 fetch, remote URL, declined files ignored, author emails shown; m3 all project values empty in .env.example; m4 README command rule and link check; m5 judges' access code, GCS reader role, hosted claims only where proven; m6 deck TBD decision in the 3.2 STOP, generated reference image.
- Checks: `blueprint.py lint` release 0 errors 0 warnings; `program` 0 problems.
- Left open: backend 11.8's latest entry asks the architect to rule on planner/provider compatibility; 2.5, 2.6 and 4.3 wait on it (and backend 12.x, frontend 10.1/11.1). 2.1-2.4 don't.
- Next: release 2.1 (start scripts) once its session can commit (uncommitted part work in the tree).

## 2026-10-20: Change frontend split gates and contract consistency (program)
- Status: done
- What changed: 2.5 `Needs:` frontend 10.1/11.1 -> frontend 10.3/11.2 (frontend's delta audit split 10.1 into 10.1-10.3 and 11.1 into 11.1-11.2). contracts/api.md 1.4 -> 1.5 (consistency only: cites dashboard-intent/synthetic-data 1.1, headings "(added in 1.3/1.4)", `node` list adds reference_extract, reference_delete, capability_check, synthetic_schema, synthetic_generate; mis-encoded `·`/`—` repaired). New example fixtures: dashboard-intent/feasibility.{alternatives,pending,stale}.json, synthetic-data/{dataset,job.succeeded}.json (dataset checksum/bytes from a real `dss.data.synthetic` run of request.json's spec); dashboard-intent.md and synthetic-data.md list them and the new task IDs, versions unchanged (shapes unchanged). program.md: Parts table (frontend consumes dashboard-intent, synthetic-data), Contracts table api 1.5, roadmap gates, decision-log row. Essentials Contracts row api 1.5 here, in backend and in frontend. docs/synthetic-data-supplement.md: frontend 11.1-11.2, API 1.5.
- Why: settles "Left open (program root)" (a)-(d) of frontend's 2026-10-20 delta audit entry; without (a) 2.5 could start before frontend finishes.
- Affects: release 2.5 gate only; 4.3 follows 2.5 unchanged.
- Checks: `lint` release 0 errors 0 warnings, engine 0/0, backend 0 errors (4 earlier size warnings), frontend 0 errors (2 earlier warnings); `program` 0 problems; `check_contracts.py` 9/9 PASS; frontend `npm test -- contract` 31/31; new fixtures' keys match their sibling fixtures and contract types.

## 2026-10-20: Retro
- Status: done
- Subject: the architect skill's audit loop (user: stuck in auditing, audits keep adding tasks). Evidence and proposals in docs/retro.md: 25 audit-fix tasks program-wide (backend 15, frontend 6, engine 4); frontend Phases 8-9 were P3-only fix phases from re-audits; every plan/delta audit applied all findings.
- Proposals: P1 severity bar and fix budget, P2 converging re-audit, P3 reviewer severity definitions, P4 change scope gate against the deadline, P5 script verdict fix. All five approved and applied.
- Applied to: ~/.claude/skills/blueprint-solution-architect/references/audit.md (new "Severity bar" section, plan-audit step 3, Re-audits, final brief, verdicts) and references/change.md (Scope gate); ~/.claude/agents/blueprint-reviewer.md; the same in the Codex copies ~/.agents/skills/blueprint-solution-architect/references/{audit,change}.md and ~/.codex/agents/blueprint-reviewer.toml; scripts/blueprint.py `final_audit_state` (heading must be "Audit (final" or "Final audit"; verdict read by leading word, then uppercase only), copied to all four copies (md5 identical).
- Checks: `program` now shows frontend "final audit DEFECTS" and release "not due" (were wrongly ACCEPTED); `lint` 0 errors 0 warnings; Codex reviewer TOML parses; no SKILL.md frontmatter touched; `claude` CLI not on PATH, so no plugin validate.
- Left open: open fix tasks (backend 13.2-13.8, frontend 12.1-12.2) predate the new bar; moving the non-blockers to Later is a change in each part, the user's call.

## 2026-10-20: Task 2.1 Start scripts
- Status: done
- Plan check: off
- What changed: new start.sh (Git Bash/Linux) and start.ps1 (PS 5.1): refuse if 8000/5173 already listen or frontend/node_modules missing; start backend (`uv run uvicorn dss.main:app --port 8000` in backend/) and frontend (`npm run dev` in frontend/); wait until both ports listen, print both URLs; Ctrl+C or either child exiting kills both process trees (taskkill /T /F on Windows), exit 1 on failure.
- Checks: start.ps1 (`powershell -ExecutionPolicy Bypass -File .\start.ps1`) and start.sh (Git Bash) each: both URLs printed, `curl -s localhost:8000/api/health` -> {"status":"ok"}, localhost:5173 -> 200, Ctrl+C -> "Stopped."; `netstat -ano | grep -E ":(8000|5173) "` printed nothing (after TIME_WAIT cleared) PASS; Test (all) `check_contracts.py` PASS 9/9.
- Decisions: readiness = both ports listening (netstat/ss or Get-NetTCPConnection), 90 s cap, abort early if a child dies; no auto-install (prints the install hint); user OK'd stopping a stray backend (PID 16496) on 8000 for the test; AGENTS.md: added the localhost-probe gotcha.
- Tried and failed: curl and Invoke-WebRequest probes (free localhost ports time out here, see Known gotchas).
- Gotchas: in AGENTS.md Known gotchas. npm.cmd prints "Terminate batch job (Y/N)?" on Ctrl+C in PowerShell; taskkill clears it, harmless.
- Left open: P3 start.sh untested on Linux/macOS (Unix stop uses pkill -P; bash 3.2 `set -u` on empty array) - start.sh; README (3.1) should give the `-ExecutionPolicy Bypass` form for start.ps1.
- Next: Task 2.2 End-to-end flow 1 and 3, dry-run engine.

## 2026-10-21: Task 2.2 End-to-end flow 1 and 3, dry-run engine
- Status: blocked
- Plan check: off
- What changed: API driver implemented and preserved in git stash `blueprint: task 2.2 failed attempt 2026-10-21 01:01`; no part files edited. Test services stopped; `.env` dry-run setting restored to 0.
- Checks: `uv run --project integration python integration/e2e_flow1.py --version2` FAIL at interview answer 1; CSV upload and interview start passed. Test (all) `check_contracts.py` PASS 9/9. Read-only reviewer: no findings. No benchmark generated.
- Decisions: follow task's If rule; preserve the driver with `blueprint.py restore 2.2` pending backend resolution.
- Tried and failed: removed unsupported profit request; retry still blocked for ordinary audience context and metric clarification.
- Gotchas: none.
- Left open: full flow and benchmark verification.
- Blocked because: (a) fixing backend feasibility behavior requires editing a separate part, forbidden here.
- Question: How should backend feasibility handle interview audience context and incomplete metrics before all three answers arrive?
- Options: A resolve in backend / B architect approves a different scripted interview / Recommend: A, audience context is classified as an unknown capability.
- Evidence: build `b_63e4d5fbd1df`, run `r_bb51e67be2ec`, node `interview`, trace status `error`, error `feasibility_blocked`; POST messages accepted 202, subsequent GET feasibility 200:
  `{"state":"blocked","issues":[{"requirement":"The audience is sales executives.","status":"unknown","reason":"No registered capability covers this requirement; clarify the requested behavior"}]}` (excerpt; remaining issues request explicit fields for order count, quantity and sales).
- Next: architect resolves backend interview feasibility; recover the named stash, then rerun task 2.2.

## 2026-10-21: Change interview feasibility recovery (release/program)
- Status: planning resolution complete; implementation and end-to-end verification remain.
- Ruling on release 2.2: option A, repair backend behavior. Ordinary audience context is not
  an unsupported feature; incomplete metrics must be clarified through the interview while
  readiness and planning/build side effects remain blocked. Do not evade the failure by
  deleting the audience answer or disabling feasibility.
- Evidence: read-only explorer identified the audience recognizer/source-coverage gap in
  backend/src/dss/spec/requirements.py and the graph route that skips interview on any
  blocked assessment. The failed driver is still in stash subject
  `blueprint: task 2.2 failed attempt 2026-10-21 01:01`; it was not restored or altered here.
- What changed: backend planning docs specify one M task 14.1 with offline API/graph,
  persisted-ledger recovery, negative enforcement and live-interview checks. Root plan gates
  2.2 on backend 14.1 and records driver recovery plus explicit metric definitions in later
  scripted answers. `blueprint.py reopen 2.2` changed blocked to todo; it is waiting on 14.1,
  not ready or passed. Program roadmap/decision log updated.
- Scope: existing core-flow blocker before the 2026-10-23 01:05 MPST deadline, one additional
  backend build session; no feature expansion, new dependency, transport/contract change or
  engine/frontend work. Architecture edits are planning-only under Program change mode.
  No delta audit required for this narrow POC correction; no fresh final audit claimed.
- Change requests settled: task 2.2's audience/incomplete-metric question planned as backend
  14.1. Existing release sequence and user acceptance/push/deploy STOPs remain.
- Checks: root check_contracts.py PASS 9/9; release lint 0 errors/0 warnings; backend stamp
  PASS and lint 0 errors/4 existing size warnings; program 0 problems and correctly waits
  release 2.2 on backend 14.1; scoped git diff --check PASS. No backend implementation tests
  or live integration rerun in this documentation-only session.
- Next: open backend/ for task 14.1, then this root for release 2.2 (M); restore the saved
  driver and rerun its Done when and root Test (all). All later release tasks stay in order.

## 2026-10-21: Task 2.2 End-to-end flow 1 and 3, dry-run engine
- Status: blocked
- Plan check: off
- What changed: recovered driver; later answers explicitly define all three aggregates and monthly order_date. Preserved in stash `blueprint: task 2.2 failed attempt 2026-10-21 02:11`; no part edits.
- Checks: `uv run --project integration python integration/e2e_flow1.py --version2` FAIL: upload, interview start and all three answers passed; planning rejected. Test (all) `check_contracts.py` PASS 9/9. Read-only reviewer: no findings. No benchmark. Services stopped; `.env` restored (`DSS_ENGINE_DRY_RUN=0`).
- Decisions: obey the part-failure rule; preserve audience context and feasibility enforcement.
- Tried and failed: explicit SUM(revenue), COUNT(DISTINCT order_id), SUM(quantity), monthly order_date did not clear feasibility after backend 14.1.
- Gotchas: none.
- Left open: full flow and benchmark verification.
- Blocked because: (a) backend repair requires forbidden part edits.
- Question: How should backend resolve these explicit metric definitions and the ordinary theme request?
- Options: A architect plans backend repair / B architect authorizes revised fixture/decision flow / Recommend: A.
- Evidence: build `b_04db6ec42f78`, POST `/plan` HTTP 409, body excerpts: `{"error":{"code":"feasibility_blocked","detail":{"assessment_id":"assessment_93df75178f30"}}}`; "proposed order_id is not an explicit definition"; "proposed quantity is not an explicit definition". GET `/feasibility` HTTP 200: seven unresolved issues, including explicit formulas, revenue sum confirmation and unknown blue-theme request.
- Next: architect resolves backend feasibility; recover the 02:11 stash with `git stash apply`, then rerun release 2.2.

## 2026-10-21: Change conversational definitions and styling (release/program)
- Status: planning resolution complete; backend implementation and release verification remain.
- Ruling: option A, one backend follow-up 14.2 (M). Repair the supported conversation rather
  than changing punctuation/theme wording or dropping feasibility issues to make the demo pass.
- Evidence: read-only blueprint_explorer traced the persisted b_04db6ec42f78 ledger and
  requirements.py: assignment boundaries omit comma/conjunction clauses; confirmed definitions
  only update earlier rows, leaving later revenue charts without provenance; blue-theme wording
  remains empty-needs/unknown. Monthly grain was already present. Task 14.1's live test used
  separate formula sentences and hex colors, so it did not prove the release transcript.
- What changed: backend architecture/essentials, PRD default and task 14.2 specify coordinated
  affirmative definitions, compatible forward reuse, supported qualitative blue styling and
  the exact three-answer/comment regression. Root plan gates 2.2 on 14.2 and corrects recovery
  to stash subject `blueprint: task 2.2 failed attempt 2026-10-21 02:11`; program roadmap updated.
  Script `reopen 2.2` changed blocked to todo, waiting on 14.2. Driver stash remains untouched.
- Decisions: one M repair to an observed core-flow blocker before the existing deadline,
  no feature/contract/dependency change. Preserve conflicting/unsupported-intent gates and
  existing budgets. No delta audit required for this narrow POC correction; no final audit claimed.
- Change requests settled: latest release 2.2 explicit-definitions/theme question planned as
  backend 14.2. All existing acceptance, push and deploy STOPs remain in their tasks.
- Checks: root Test (all) PASS 9/9; backend stamp PASS; release lint 0 errors/0 warnings;
  backend lint 0 errors/4 pre-existing size warnings; program 0 problems, backend 14.2 next
  and release 2.2 waiting; git diff --check PASS (line-ending notices only).
  Backend implementation/live tests were not run in this documentation-only session.
- Next: build backend 14.2 in backend/, then restore the 02:11 driver and rerun release 2.2
  at this root, including v1/v2 dry-run and benchmarks. Existing later release order is unchanged.

## 2026-10-21: Task 2.2 End-to-end flow 1 and 3, dry-run engine
- Status: done
- Plan check: off
- What changed: recovered `integration/e2e_flow1.py` from stash 02:11 (exact three answers and dark-blue comment kept). Comment target now a `data-kind="component"` (v1: label /trend/, as backend 14.2's live regression; v2: last other component); comment waits for its `revise` run ok, records `changed` (spec_version up) per comment, fails if no comment changed the spec; table gains "Spec changed". New `deck/data/bench-2026-10-20-dry-run.json` (UTC date). `.env` restored to `DSS_ENGINE_DRY_RUN=0`; services stopped.
- Checks: `uv run --project integration python integration/e2e_flow1.py --version2` PASS exit 0 (build b_e4b4c5ddbce3): every v1/v2 stage reached, both comments changed the spec, tokens input=77474 output=4925, plan/prototype 56.5 s; access code unset locally (redaction covers it). Test (all) `check_contracts.py` PASS 9/9. Reviewer: P1 + P2 below, P2 fixed; rerun PASS.
- Decisions: decoration target dropped: comment text says "preserve its ... data" and backend `Component.colors` is charts-only; old wait `spec_version > previous` hung 600 s on a valid "No change needed" revise. AGENTS.md: two gotchas (flaky live nodes, TaskStop leaves servers).
- Tried and failed: 4 of 7 runs failed in live model nodes, each passing on rerun: revise `llm_unavailable` (50 s), plan `invalid_source`, plan `llm_unavailable` (0 tokens), plan `invalid_request` (135 s); revise `invalid_request` on decoration `p1_header_title` (the old target).
- Gotchas: in AGENTS.md Known gotchas.
- Left open: P1 (cross-part, backend): contracts/api.md lets `Comment.component_id` name a decoration, but backend revise rejected the dark-blue accent on decoration `p1_header_title` with `invalid_request` ("Revision patch was rejected after one repair", build b_bfc3d33c9f3b, run r_af4884f172b5, step v1 comment); the architect decides backend fix or contract note. Backend plan nondeterminism (~1 in 3 runs) also for the architect. P3: with one data component v2 reuses v1's target (any-changed check still guards).
- Digest: `integration/e2e_flow1.py [--server URL] [--version2] [--mode dry-run|live]` -> exit 0/1; writes `deck/data/bench-<UTC date>-<mode>.json` {run_date, server_url, mode, build_id, version2, stages[{version, stage, seconds, run_id, input_tokens, output_tokens, changed?}], totals}.

## 2026-10-21: Task 2.3 End-to-end live build and UI walkthrough
- Status: blocked
- Plan check: off
- What changed: `integration/e2e_flow1.py` gained `--live` (= `--mode live`; refuses `.env` `DSS_ENGINE_DRY_RUN=1`; after each run prints `v<n>: report <url>`, requires an https datastudio/lookerstudio `report_url`, adds `report_urls` to the bench JSON). Set aside in stash `blueprint: task 2.3 failed attempt 2026-10-21 07:52`. No part edits; services stopped; `.env` unchanged (`DSS_ENGINE_DRY_RUN=0`).
- Checks: `DSS_ENGINE_DRY_RUN=0 uv run --project integration python integration/e2e_flow1.py --live` FAIL twice at v1 run (builds b_fb72b6479a8d, b_ae7f4bdaab30); every earlier stage passed. `dsengine check`: `{"chrome_running": true, "signed_in": true}`. Direct `dsengine run --screencast` on b_ae7f4bdaab30's recipe: same failure. No bench JSON; UI walkthrough not reached.
- Decisions: user chose to block (card) over waiting for an engine fix in this session.
- Tried and failed: rerun once per the flaky-live gotcha; same op, same timeout.
- Gotchas: AGENTS.md: screencast-frame diagnosis line.
- Left open: live e2e, bench JSON, manual link check, UI walkthrough at :5173.
- Blocked because: (a) the fix is in engine/ (release never edits parts).
- Question: Who fixes engine `_dismiss_access_review` for Data Studio's new "Review data access" dialog (Close/Acknowledge only, no "I understand and accept the risk." checkbox)?
- Options: A architect plans an engine task: treat `review_accept` as optional (click `review_acknowledge` when the dialog is visible), update knowledge/datastudio-ui/linking.md and the save-path twin at ops/report.py:321 / B architect pins a template or URL that avoids the dialog / Recommend: A, smallest and matches current UI.
- Evidence: engine events (b_ae7f4bdaab30 v1):
  `{"event": "op_finished", "op_id": "s001", "op": "open_report", "status": "failed", "message": "operation timed out", "screenshot": null, "duration_ms": 20031}`
  `{"event": "run_finished", "status": "failed", "report_url": null, "ok": 0, "failed": 1, "skipped": 16, "error_code": "open_report_failed"}`
  Last screencast frame: dialog "Review data access", "This report was designed by another user...", buttons Close and Acknowledge only. Engine waits for `review_accept: 'role=checkbox[name="I understand and accept the risk."]'` (knowledge/datastudio-ui/linking.md:8; ops/report.py:46-48 returns False when it is not visible), so the editor never becomes ready.
- Next: after the engine fix, `git stash apply` the 07:52 stash (by subject), start services, rerun the `--live` check, then the UI walkthrough.

## 2026-10-21: Change data-access review dialog without checkbox (program)
- What changed: task 2.3 reopened and gated `Needs: engine 3.1; engine 6.1; frontend 3.2`. Engine got task 6.1 (S): open/save accept the "Review data access" dialog with or without the risk checkbox; engine architecture conventions, decision log and essentials updated. No contract changed.
- Why: 2.3's block (a): engine `_dismiss_access_review` waits for a checkbox Data Studio no longer shows, so `open_report` times out.
- Ruling: user picked option A (engine task) over B (pin a template/URL avoiding the dialog).
- Tasks affected: 2.3 waits on engine 6.1; its 07:52 stash (`blueprint: task 2.3 failed attempt 2026-10-21 07:52`) still holds the `--live` work: `git stash apply` it by subject when 2.3 resumes. Later tasks unchanged.

## 2026-10-21: Task 2.3 End-to-end live build and UI walkthrough
- Status: blocked
- Plan check: off
- What changed: Recovered `--live` integration changes reviewed; preserved in stash `blueprint: task 2.3 failed attempt 2026-10-21 08:57`. No part edits or environment changes; pre-existing services left running.
- Checks: `uv run --project integration python integration/e2e_flow1.py --live` FAIL (exit 1, b_efb99ef68177): intake, all interview answers, plan, comment and recipe passed; engine version failed with `report_url: null`, no bench JSON. Execute trace status ok, latency 312368 ms, despite failed version. Test (all) `uv run --project integration python integration/check_contracts.py` PASS, all 9. `dsengine check`: Chrome running and signed in. UI b_c2efd21dc241 CSV intake passed; second answer failed twice with `interview` / `llm_unavailable` (40949/35583 ms). Link, charts and plan activity checks not reached. Reviewer: no findings.
- Decisions: User selected recording the blocker for backend follow-up. Restore preserved release changes; existing services belong to prior sessions.
- Tried and failed: UI answer retried once; same model failure.
- Gotchas: none new.
- Left open: live dashboard, benchmark and UI acceptance.
- Blocked because: (a) fixes require other parts, which release cannot edit.
- Question: Can backend diagnose the repeated interview `llm_unavailable` and failed engine version?
- Options: A backend follow-up using these build IDs, then rerun release 2.3 / B defer live acceptance / Recommend: A.
- Next: Backend follow-up first; then apply the 08:57 stash and rerun task 2.3.

## 2026-10-21: Change staged workflow (program)
- What changed: contracts/api.md 2.0 (breaking: stages context/outline/design/blueprint replace interview/plan; Build notes + artifacts; staged endpoints; artifact.updated; artifact_invalid), dashboard-intent.md 1.2 (requirements from structured artifacts), synthetic-data.md 1.2 (stage names); fixtures build*.json, events*.sse, messages.json, prototype.sample.html updated; new context/outline/design/design_presets/blueprint.json. docs/program.md goals, flow 1, contracts table, roadmap, integration checks and nine decision-log rows. Backend phase 15 (15.1-15.11), frontend phase 14 (14.1-14.5) planned in their folders. Release 2.3 rewritten for the staged driver (M, Needs backend 15.11, frontend 14.5); 2.5 Needs the same and checks KPI-card definitions instead of chat gross/net; 2.6 checks reference-prefilled outline/design.
- Why: per-message requirement extraction in the free-text interview kept failing (backend 14.1, 14.2; release 2.3 `llm_unavailable`), and the one large plan run failed about 1 in 3 live runs, sending users back to the interview. The user asked for a context-engineered, node-per-artifact workflow where the model gets only enough context and code generates the files.
- Ruling: user choices on cards: full workflow regardless of the deadline; OKF md + YAML frontmatter artifacts; design-time skill themes with a deterministic renderer; unjoinable sources stay one view (flag, one source or union); notes box + model draft; one outline proposal with tick/Other/suggest-more; pages picked in design (single or per section, at most 5); replace the old path; record as a change in place.
- Tasks affected: release 2.3 (reopened from blocked, rewritten), 2.5, 2.6; later tasks unchanged.
- Change requests settled: 2.2 P1 (revise rejected a color comment on a decoration) planned as backend 15.9; 2.2 backend plan nondeterminism superseded (plan removed; blueprint has bounded repairs, checked live in backend 15.11); 2.3 (08:57) interview `llm_unavailable` superseded (interview removed, backend 15.1); 2.3 failed engine version planned as 2.3's screencast diagnosis If: line.
- Decisions: the GPS sample files are not in the repo, so backend 15.5 adds small GPS-style fixture CSVs with their schemas; the deadline stays recorded but no longer cuts this scope (program roadmap).

## 2026-10-21: Audit (delta, staged workflow)
- Reviewer (blueprint-reviewer, opus, high): 1 P1, 10 P2, 5 P3; the user accepted all 16, applied in the docs.
- Applied: (A, P1) backend 15.1 now switches to the 2.0 build shape and removes the interview/plan path first so `uv run pytest` stays green; phase 15 renumbered 15.1-15.11 (old 15.9 split by moving removal to 15.1); gates now backend 15.11. (B) outline 3-5 sections, design prefills per_section only for 1-5 sections, >12 rows/page and question-without-row become issues. (C) re-confirm revalidates downstream artifacts; api.md adds `outline/propose`, `design/prefill`; blueprint redraft keeps unchanged rows. (D) no artifact edits in build/done; interview/plan stages read as context; legacy builds exempt from the four-confirmed rule. (E) ratio-only questions not recommended. (F) columns past 40 sent as name+type. (G) stdlib colorblind check. (H) live test PUTs a ratio KPI; 15.6 fake omits a question. (I) Prototype HTML page sections, new prototype.multipage.html, prototype.sample.html wrapped. (J) staged-ui.md layout per stage and states. (K) blueprint.blocked.json split from blueprint.json, events.sse order, stale wording, data model columns, preset fonts, activity path and presets, Review focus naming api.md 2.0, empty pages omitted, release bench and 2.5 CSV, removal comments.
- Rejected: none.

## 2026-10-21: Task 2.3 End-to-end live build and UI walkthrough
- Status: blocked
- Plan check: off
- What changed: `integration/e2e_flow1.py` ported to the 2.0 staged API (notes -> context draft, confirm unedited, recommended + one Other, archetype preset per_section, feasibility decisions, prototype, component + decoration comment each changing the spec, recipe, run; `--live` from the 08:57 stash). Set aside with both bench JSONs in stash `blueprint: task 2.3 failed attempt 2026-10-21 21:46`. `.env` unchanged; services stopped (Vite on 5173, PID 35892, predates this session).
- Checks: `DSS_ENGINE_DRY_RUN=1 ... e2e_flow1.py --version2` PASS (b_f5b7f65b5894, all stages with tokens, 47455/4363). `--live` exit 0 with link (b_31ee6bedd325) but engine `partial`: ok 19, failed 25. Manual chart check FAIL; UI walkthrough not run. Test (all) PASS, 9/9.
- Decisions: blocked row with no offered alternative is dropped (decision `drop`, recorded in bench `decisions`); bench rows carry `run_ids`; read backend tests/live/test_staged_flow.py for the flow (read-only). Typing delegated to a Sonnet worker.
- Tried and failed: narrowing `DSS_ALLOWED_TYPES` not applicable: every type fails, incl. scorecard 1/3, dropdown 3/3.
- Gotchas: AGENTS.md: env override, `--live` partial.
- Left open: live charts, UI walkthrough at :5173.
- Blocked because: (a) the fix is in engine/ (release never edits parts).
- Question: Who fixes engine add_chart/add_control field selection in Data Studio's current field picker?
- Options: A architect plans an engine task (pick metric/dimension in the picker; live test on this recipe) / B defer live charts, demo dry-run only / Recommend: A, every chart op fails.
- Evidence: `{"op_id": "s005", "op": "add_chart", "status": "failed", "message": "operation timed out", "duration_ms": 20155}` (scorecard, metric sum revenue); screencast of recipe s001-s005: Scorecard properties > Setup > Metric picker open, search empty, field list shown, `revenue` never chosen. Screens: data/builds/b_31ee6bedd325/v1/screens/s006_failed.png, s020_failed.png (chart inserted with default Record Count).
- Next: after the engine fix, `git stash apply` the 21:46 stash (by subject), drop 07:52/08:57 stashes, start backend, rerun `--live`, check events `failed: 0`, then the UI walkthrough.

## 2026-10-21: Change live chart fields and screenshot capability test (program)
- What changed: engine task 8.1 (M, Phase 8): diagnose with the screencast and fix chart/control field setting on a real compiled recipe, with a live replay test and the b_31ee6bedd325 recipe ending `failed: 0`. Release 2.3 reopened, gated `Needs: ... engine 8.1`, with an `If:` to apply the 21:46 stash. Release 2.6 rewritten (S to M, depends on 2.3 only): the user's electricity-access screenshot recreated from synthetic data through the UI, with a capability matrix. Program decision log row. No contract, PRD or architecture changed.
- Why: 2.3's block (a): live run ok 19, failed 25; all three dropdown controls and 9 of 11 charts time out with the default Record Count inserted and Setup never shown; the editor appears laid out at about half of 1920 x 1200 (s006_failed.png). Engine's own live suite passed at 20:02, so the gap is between the compiled recipe's sequence/environment and the engine's tests.
- Ruling: user picked the engine task. For the screenshot, the user wants to test the current version's capability (the globe is an SVG illustration, so background decoration), not extend contracts/recipe.md: gaps go into the matrix and change requests, no new part tasks.
- Alignment check: `integration/check_contracts.py` 9/9 PASS; backend emits only recipe 1.0 ops and types; the HTML decoration layer -> `background_p<n>.png` -> `set_background_image` -> charts path already exists (backend 15.9).
- Tasks affected: engine 8.1 first, then release 2.3, then 2.6 (`/blueprint-solution-builder 2.6`; first ready by order would be 2.4). The screenshot was moved from the repo root to data/references/electricity-access.jpg (gitignored) and is never committed.

## 2026-10-21: Task 2.3 End-to-end live build and UI walkthrough
- Status: blocked
- Plan check: off
- What changed: applied stash `blueprint: task 2.3 failed attempt 2026-10-21 21:46` (staged driver, no code change this session); attempt plus regenerated bench JSONs set aside again in stash `blueprint: task 2.3 failed attempt 2026-10-21 23:11`. `.env` unchanged; backend stopped (Vite 5173, PID 35892, predates this session).
- Checks: `DSS_ENGINE_DRY_RUN=1 ... e2e_flow1.py --version2` PASS (b_547ee66c85a8, every v1/v2 stage with tokens, 48378/4449). `--live`: run 1 FAIL revise `llm_unavailable` (b_60b0e5f13928); run 2 FAIL blueprint accept `409 artifact_invalid` (view failed SQL validation, 0 rows; b_b409c57aaa16); run 3 exit 0 with link https://datastudio.google.com/reporting/5d7469b1-11bc-4586-a622-60e95d52f909 (b_b2ac19ea6696) but `run_finished` partial, ok 36, failed 3. Engine 8.1's chart field fix holds (pages 1-2 all ok). Test (all) PASS, 9/9. `dsengine check` signed in. UI walkthrough not run (user chose block).
- Decisions: user chose to block on a card (over a UI walkthrough first). Stash drops of 07:52/08:57 were denied by the auto-mode classifier; both stashes still exist.
- Tried and failed: none at the engine step (rerunning is not a fix: the isolated replay reproduces all 3).
- Gotchas: AGENTS.md flaky-live line gained the blueprint 0-rows failure.
- Left open: live `failed: 0`, manual link check, UI walkthrough at :5173; drop stashes 07:52 and 08:57 by hand.
- Blocked because: (a) the fix is in engine/ (release never edits parts).
- Question: Who fixes engine set_background_image and add_chart on a page taller than the viewport (canvas 1200x1492)?
- Options: A architect plans an engine task: on a tall canvas, position/size and send-back the uploaded image, and scroll to place charts below the fold; live replay test on replay_p3.jsonl / B architect caps page height at 712 in the backend layout (backend task) / Recommend: A, tall per_section pages are the staged design.
- Evidence (b_b2ac19ea6696 v1, page 3 = s023 add_page, s024 set_canvas 1200x1492):
  `{"op_id": "s025", "op": "set_background_image", "status": "failed", "message": "operation timed out", "duration_ms": 20078}`
  `{"op_id": "s034", "op": "add_chart", "status": "failed", "message": "chart box did not match the requested position and size", "screenshot": "s034_failed.png"}` (table x24 y884 w1152 h304; drawn ~400 px wide)
  `{"op_id": "s036", "op": "add_chart", "status": "failed", "message": "operation timed out"}` (bar x24 y1204 w568 h264)
  `{"event": "run_finished", "status": "partial", "ok": 36, "failed": 3, "skipped": 0}`
  Isolated replay (data/builds/b_b2ac19ea6696/v1/replay_p3.jsonl: s001, s002, s023-s025, s034, s036): s025, s034, s036 all `operation timed out`. Frames (screens/replay_s025_stuck.jpg, replay_last.jpg): background_p3.png inserted at its natural size mid-canvas (top-left ~x420 y356), not at 0,0; Image properties open, Arrange menu open on Order; next add_chart leaves the image selected and opens a "Choose a field" filter chip instead of the chart's field picker.
- Next: after the engine fix, `git stash apply` the 23:11 stash (by subject), drop 07:52/08:57/21:46, start backend live, rerun `--live` until `failed: 0`, manual link check, then the UI walkthrough.
- Digest: e2e_flow1.py staged driver (stash 23:11): `--version2`, `--live`; bench deck/data/bench-<date>-{dry-run,live}.json with stages, tokens, decisions, run_ids, report_urls. Blocked on engine tall-canvas ops.

## 2026-10-21: Change tall canvas placement (program)
- What changed: engine task 9.1 (M, Phase 9): background image, charts, controls and text placed at their boxes on canvases taller than the viewport, with a live tall-canvas replay test and the b_b2ac19ea6696 recipe ending `failed: 0`; engine architecture Live editor conventions rule + decision row. Release 2.3 reopened, `Needs: ... engine 9.1`, resume `If:` now applies the 23:11 stash and drops 07:52/08:57/21:46; the stale 07:52/08:57 `If:` removed. Program decision log row. No contract, PRD or other part changed.
- Why: 2.3's block (a): live run b_b2ac19ea6696 partial, ok 36, failed 3, all page 3 (1200 x 1492): s025 set_background_image, s034 table at y884, s036 bar at y1204; isolated replay reproduces all three.
- Ruling: user picked the engine task over a backend page-height cap or accepting partial. Scope gate: fixes a blocker on the must-survive path (live build -> link); ~26 h to the deadline with release 2.3-4.4 left (M, L, L, M, M, S, M, S, M, S).
- Tasks affected: engine 9.1 first, then release 2.3. Change requests: none open.

## 2026-10-22: Task 2.3 End-to-end live build and UI walkthrough
- Status: done
- Plan check: off
- What changed: applied stash `blueprint: task 2.3 failed attempt 2026-10-21 23:11` (staged driver `integration/e2e_flow1.py` with `--version2`/`--live`; no code change this session); regenerated `deck/data/bench-2026-10-21-{dry-run,live}.json` (UTC date). `.env` unchanged; backend stopped after (Vite 5173, PID 35892, predates).
- Checks: `DSS_ENGINE_DRY_RUN=1 ... e2e_flow1.py --version2` run 1 FAIL (known blueprint-view 0-rows 409, b_ecb15bd55c0c), rerun PASS (b_942e60dcab38, all v1/v2 stages with tokens, 41676/3650). `--live` PASS exit 0, link printed (b_7fe221d7b5b1), events `run_finished` ok 38 failed 0. Manual link: yes, 4 pages with charts/controls over the background (viewed via engine Chrome CDP). UI walkthrough :5173 yes (b_96b8a37f4db8): strip phrase + elapsed + tokens (none -> 9k), checklist all ticked, comments spec_version 1 -> 2, run ok 36 failed 0, "Open in Data Studio" link. Test (all) PASS 9/9. Reviewer: no P0/P1.
- Decisions: blocked row without an offered alternative is dropped (as in the 21:46 entry; live bench q7). UI used the default executive preset `studio_light`. AGENTS.md: 3 gotchas (CSV upload in built-in browser, report view via CDP, stash drop denied).
- Digest: integration/e2e_flow1.py staged: `--version2`, `--live` (needs DSS_ENGINE_DRY_RUN=0); bench deck/data/bench-<UTC date>-{dry-run,live}.json: run_date, mode, build_id, stages[{version,stage,seconds,run_ids,input_tokens,output_tokens,changed?}], totals, decisions, report_urls.
- Tried and failed: none (one rerun per the flaky-live gotcha).
- Gotchas: in AGENTS.md Known gotchas.
- Left open: P2 `accept_alternative` branch never exercised and assumes `ready` after the decision POST - integration/e2e_flow1.py:237; P3 `partial` still exits 0 (API has no failed count; manual events check) - :168; P3 only `run()` retries 409 `wrong_stage` - :197/:240/:150; P3 `next()`/null context escape the FAIL handler - :161/:185; P3 accepts lookerstudio host - :23; P3 model runs poll /api/traces - :113. Outside: first report page named "Untitled Page", page-1 scorecard values tiny, UI decoration comment gave dark text on the blue band (engine/backend). User: drop stashes 07:52, 08:57, 21:46 by subject.
- Next: Task 2.4 Manual acceptance: CSV, research, BigQuery and GCS.

## 2026-10-22: Task 2.4 Manual acceptance: CSV, research, BigQuery and GCS
- Status: blocked
- Plan check: off
- What changed: docs/acceptance.md (4 rows, verdicts from the user's card), docs/img/acceptance-2.4-{csv,research,bigquery,gcs}.png (page 1, cropped); copied samples/ecommerce_sales.csv to `gs://$GCS_BUCKET/samples/`; AGENTS.md: 2 gotchas.
- Checks: rows 1 CSV PASS, 4 GCS PASS; rows 2 research FAIL, 3 BigQuery FAIL (user verdicts); `check_contracts.py` PASS (9/9).
- Decisions: builder drove the UI, user watched (card). Research prompt "Nominal GDP of the ASEAN member countries, latest year, in US dollars". BQ row: prototype comment set its table to 10 rows (avoid rows_per_page 15).
- Tried and failed: research prototype comment "exclude the ASEAN total row" -> feasibility "No registered capability covers this requirement"; dropped it.
- Gotchas: in AGENTS.md. GCS "Add source" returns 201 but the Connect list stays empty until reload.
- Left open: P2 every report: page 1 "Untitled Page", scorecard values tiny (engine/backend); P2 GCS add-source UI refresh (frontend).
- Blocked because: (b) the fixes are tasks in other parts (backend, engine) through the change flow.
- Question: Which part tasks fix row 2 (backend emits table `rows_per_page: 15`, engine: "Data Studio option 15 is unavailable"; scorecard titles quoted as `Total Population (M)','Total Nominal GDP (...`) and row 3 (engine: "field user_id not in data source" though the view has user_id; "control box did not match the requested position and size")?
- Options: A plan backend (rows_per_page limited to Data Studio's list; title quoting) and engine (field lookup, control placement) fixes, then rerun rows 2-3 only / B accept rows 2-3 as known limits and change 2.4's Done when / Recommend: A, both block a clean demo.
- Next: after the part fixes, rerun rows 2 and 3 only (same inputs), then a user verdict card.

## 2026-10-22: Change manual acceptance fixes (release/program)
- What changed: plan.md 2.4 gains `Needs: engine 10.1; backend 17.1` and a rerun note (rows 2 and 3 only, same inputs; rows 1 and 4 stand); program.md roadmap line and decision-log row; PRD Later: page 1 name and scorecard font (P2s). Engine plan 10.1, backend plan 17.1 added.
- Why: 2.4 blocked (b): row 2 research (`rows_per_page: 15` not in DS menu; list-fragment titles; ASEAN aggregate row summed), row 3 BigQuery (`user_id` below the picker fold; date control drawn at DS default size). Diagnosed from the builds' events.jsonl and failure screenshots.
- Affected: release 2.4 reopened, waits on engine 10.1 and backend 17.1; 2.5 unchanged (runs live after engine 10.1, shares the Chrome profile).
- Settled: 2.4's question -> option A (user card): planned as engine 10.1 and backend 17.1. Left open P2s (page 1 "Untitled Page", tiny scorecard values) -> deferred to PRD Later (user card). P2 GCS add-source list refresh (frontend) -> deferred to PRD Later, not a 2.4 blocker (row 4 PASS).

## 2026-10-22: Task 2.5 Reference, refusal and synthetic end-to-end, local
- Status: blocked
- Plan check: off
- What changed: new `integration/e2e_references.py` (5 cases: refusal, revenue, style, recreate, synthetic; `--live`, `--cases`, `--after-restart`, `--render-reference`; bench deck/data/bench-references-local.json), check_contracts.py (+4 checks: intent/synthetic fixture shapes, 26 error cases, samples, bench), samples/reference-dashboard.{html,png}, reference-expectations.json, gross_net_sales.csv. All in stash `blueprint: task 2.5 failed attempt 2026-10-22 05:08`. AGENTS.md: 3 gotchas.
- Checks: check_contracts PASS 13/13. Live: refusal PASS (b_80d765aaf575; planned view absent in BigQuery), revenue PASS (b_adc76e20b0f9), synthetic PASS in full twice (b_1fece69f4132, b_cb444e9fb081: 1,000 rows, typed intake, labeled prototype + report, 0 failed ops), CSV after restart same sha256 (b2fec68b…); style Done-when checks PASS, recovery FAIL 4/4; recreate PASS only with dropped observations (b_ecbab178ca86: 6/6 order, live 0 failed, v2, allowlist). Full command exit 1. Comparison/STOP not reached.
- Decisions: user chose block (card). Reference notes name no charts; recreate fails if an image observation is dropped (reviewer P1). Allowlist case edits root .env locally, restores bytes.
- Tried and failed: field definitions in reference instructions; KPI names = card labels. Flaky: 7 llm_unavailable, 2 view 0-rows, 1 engine save_report timeout.
- Gotchas: in AGENTS.md.
- Left open: P2 hosted allowlist path for 4.3 - e2e_references.py narrowed_allowlist; P3 .env write not atomic; P3 --after-restart can't detect the restart; GPS on a built v2 classifies `unknown` (outline_other budget). User: drop stashes 2.3 23:11, 2.5 05:08 after reapply.
- Blocked because: (a) the fixes are in backend/ (release never edits parts).
- Question: Which backend tasks fix (1) `prototype_stale` never cleared when a replan publishes, and (2) recreate image observations that stay needs_clarification even with explicit definitions?
- Options: A plan both backend fixes, then rerun 2.5 in full / B fix (1) only and change 2.5's Done when to accept dropped recreate observations as a recorded limit / Recommend: A; B leaves "recreate" proven by the outline, not the screenshot.
- Evidence: (1) b_24747c71b7e3 after DELETE reference -> check -> regenerate -> accept (stage prototype, spec_version 2, artifacts confirmed): GET feasibility `{state: ready, prototype_stale: true}`; POST recipe `409 {"code":"feasibility_blocked","message":"Feasibility needs attention. ","detail":{"assessment_id":"assessment_4aab90854927","issue_ids":[]}}` (requirements.py:1569, capability_check.py:118, outline.py:220 only set it). (2) b_b4319fb6113d: instructions "Revenue = SUM(revenue) in USD; ..." -> every observation `needs_clarification`, no alternatives: "Confirm aggregation sum for Revenue; it is not defined by the source" (without them: "Confirm which field defines Revenue; proposed revenue is not an explicit definition"); after drops, accept failed 2/5: run.finished "Candidate no longer fulfills the active requirements" (422 invalid_request, detail not exposed by the API).
- Next: after the backend fixes, `git stash apply` the 05:08 stash by subject, `./start.sh`, `e2e_references.py --live` (rerun failed cases with `--cases`), restart, `--after-restart`, report screenshots, comparison STOP card.

## 2026-10-22: Architect checkpoint for release 2.5
- Status: scope choice pending; task 2.5 remains blocked. No task markers, contracts or product code changed.
- Findings: program status reports backend 17.1 still pending and release 2.4 waiting on it. Release 2.5's latest evidence identifies stale prototype recovery and recreate metric-definition reconciliation as backend defects. Contract dashboard-intent.md already requires explicit replan recovery and preservation of confirmed metric meaning; no interface change is proposed.
- Proposed: two medium backend tasks, one for clearing artifact staleness only after validated candidate publication (with rollback and pending-comment gates preserved), one for reconciling image observations with confirmed Context KPI definitions while retaining ambiguity and provenance checks. Then gate and reopen release 2.5 for its full acceptance rerun; do not accept dropped image observations as proof of recreation.
- Decision pending: card offers both fixes (recommended), or stale recovery only with an explicit reduction of recreation acceptance. This checkpoint does not settle the earlier blocked-task question.
- Checks: blueprint status and program completed; program reports 0 problems. Read-only inspection of the relevant contract, architecture and backend publication/requirements paths; no tests run this session.
- Next: after the user's scope choice, write the affected planning docs, run stamp/lint and commit the doc changes before handing off to a backend build session.

## 2026-10-22: Change reference recovery (program)
- What changed: backend architecture/essentials/plan/progress specify 18.1 (M, validated replan freshness) and 18.2 (M, recreate definition reconciliation); program roadmap and decision log updated. Release 2.5 reopened through blueprint.py and gated on both tasks, with a stash-resume note, full five-case live rerun, restart persistence, zero failed engine operations and the existing comparison STOP.
- Ruling: user selected "Fix both defects (Recommended)". The prior 2.5 blocked-task question and architect checkpoint are settled as option A; no relaxation to dropped observations or recreation acceptance. These two tasks repair required behavior, with no new dependency, contract/API shape or product scope. Existing backend 17.1 remains first, then 18.1 -> 18.2 -> release 2.5. Release 2.6 remains separately ready; 2.4 still needs 17.1.
- Decisions: require atomic publication of freshness and proof after coverage; checks alone cannot bless old artifacts; pending comments keep their explicit lifecycle. Reconcile confirmed KPI cards and explicit user reference instructions with image provenance, retaining ambiguity and schema/definition invalidation. No product code or stash changed. POC delta audit is optional and was not run for this bounded corrective change.
- Checks: root Test (all), `uv run --project integration python integration/check_contracts.py`: PASS, all 9 checks (the 13-check extension remains in the unapplied 2.5 stash). Backend stamp completed; backend/release lint: 0 errors; program: 0 problems; git diff --check passed. Existing plan-size/older Spec and root AGENTS length warnings remain advisory. Backend product tests and live acceptance not run: implementation is pending.
- Left open: existing 2.5 hosted-allowlist runner concern remains for release 4.3; no additional task or acceptance waiver. Stash drops remain user cleanup. No new STOP or unverified dependency.
- Next: open backend/ for builder 17.1, then 18.1 and 18.2. Return to the root for 2.5's full live acceptance and user comparison card; 4.3 repeats the same standard on the hosted service.

## 2026-10-22: Task 2.4 Manual acceptance: CSV, research, BigQuery and GCS
- Status: done
- Plan check: off
- What changed: docs/acceptance.md rows 2 (research, b_ca4845ae0e0b) and 3 (BigQuery, b_a8ace098d03b) rerun after engine 10.1 / backend 17.1, both PASS (user card); docs/img/acceptance-2.4-{research,bigquery}.png replaced (page 1, cropped). AGENTS.md: 2 gotchas.
- Checks: row 2 run ok 45/45, row 3 ok 52/52; values match source (research PPP 13.3M = 13,256,570, 11 countries; BQ 10.9M/125.5K/182.0K/80.0K users/59.75 = direct query); user verdicts PASS, PASS; `check_contracts.py` PASS (9/9).
- Decisions: same inputs as the first runs, default outline/design, no prototype comments. Row 2 build title typed twice by a browser misfire (no rename endpoint; cosmetic, the report title comes from Context). Rows 1 and 4 stand.
- Digest: docs/acceptance.md: 4 rows PASS (csv b_ced0f5b4c491, research b_ca4845ae0e0b, bigquery b_a8ace098d03b, gcs b_9ec14b32752e) with Data Studio links; docs/img/acceptance-2.4-{csv,research,bigquery,gcs}.png for README.
- Tried and failed: first Build click silently did nothing (engine Chrome not running); see AGENTS.md.
- Gotchas: in AGENTS.md.
- Left open: P2 scorecard values tiny at box top-left (engine/backend, user flagged); P2 background PNGs low-definition, user suggests rendering the HTML background as HD PNG (backend); P2 page 1 "Untitled Page" (engine).
- Next: Task 2.5 (reference, refusal and synthetic e2e, local), per its stash-resume note.

## 2026-10-22: Change report quality (program)
- What changed: contracts/recipe.md 1.0 -> 1.1 (`rename_page` op; scorecard value rule `clamp(16, h - 28, 36)` px and hidden metric name when titled; `colors` apply in order to the swatches a chart has) and recipe.schema.json (`rename_page`); program.md contracts table, roadmap bullet, decision log; root essentials recipe 1.1; root PRD Later line on page 1 name and scorecard size removed (now planned). Engine plan Phase 11: 11.1 (M, STOP), 11.2 (S), 11.3 (S). Backend plan Phase 19: 19.1 (S, STOP), 19.2 (S, `Needs: engine 11.2`). Each part's architecture, essentials and progress updated.
- Ruling: user ticked all four on the scope card (scorecard size, HD backgrounds, page 1 name, chart palette colors). Audit evidence: b_a8ace098d03b scorecards h=84 get only title + compact_numbers (no value size); background.py captures at device_scale_factor=1 (1200 x 532); compiler emits `add_page` for pages 2+ only; 16/16 `set_style colors` skipped (palette 4 > swatches). Scorecard size is derived from the box (no new argument); `rename_page` is additive, header stays "1.0". No release gate: 2.5 stays the critical path.
- Decisions: two STOPs (engine 11.1 scorecard look, backend 19.1 sharpness) because both are visual judgments; evidence screenshots go to data/report-quality/ (git-ignored). Contract fixture recipe.sample.jsonl unchanged (inserting an op would renumber it); the parts' own tests cover `rename_page`. POC: delta audit optional, not run.
- Left open: release 2.6 screenshots and README images show the fixes only if these land first.
- Next: engine/ 11.1 -> 11.2 -> 11.3 (one Chrome; not during release 2.5 live runs); backend/ 19.1 any time, 19.2 after engine 11.2.

## 2026-10-23: Task 2.5 Reference, refusal and synthetic end-to-end, local
- Status: blocked
- Plan check: off
- What changed: 05:08 stash already applied (uncommitted, kept in the tree, not restored: the ruling doesn't invalidate it). e2e_references.py: Revenue assumption regex also takes "after deducting/net of discounts" (run 1 said "net sales ... after deducting discounts"); recreate refuses any drop (a check turns observations into rows like "Top products by revenue table"); RECREATE_TEXT adds `Quantity = SUM(quantity)` (the backend's own suggested instruction). AGENTS.md: 1 gotcha.
- Checks: check_contracts PASS 13/13. Live on 8ca0819 (dirty), engine signed in: refusal PASS b_b21118d626bf; style PASS b_23cecc246dcb (recovery after replan now compiles: 18.1 fixed); revenue PASS b_f66d9d8046e7 (run 1 FAIL on regex only); recreate FAIL x2, synthetic FAIL x2, all at POST /blueprint/accept. Full command exit 1; --after-restart and comparison STOP not reached.
- Decisions: blocked per the task's If (gate fails inside a part).
- Tried and failed: none in the driver; failure repeats at the same step.
- Gotchas: in AGENTS.md.
- Left open: P2/P3 from the 2026-10-22 entry stand.
- Blocked because: (a) the fix is in backend/ (release never edits parts).
- Question: Which backend task makes a recreate-mode prototype publish pass the coverage check (render.py:66) after the designer node (20.3)?
- Options: A backend task: expose the coverage `errors` in the API error and fix recreate coverage with designed pages, then rerun 2.5 / B accept recreate without a live build / Recommend: A; B leaves recreate unproven.
- Evidence: b_7ca302e800cc: 0 decisions, check -> ready, prototype_stale false; accept run r_db7feccb917b run.finished "Candidate no longer fulfills the active requirements" (422 invalid_request, `errors` not exposed); spans view, layout, designer p1-3, validate 0 errors, render, publish. Same on b_48ef72ff1bff (r_3245ba9235d0), b_dfb67c24f176, b_52b7b7be7e02 (r_79a663bc8b0e, 4 pages). Style mode publishes; recreate-mode only. 18.2 works: every image observation bound, no drops.
- Next: after the backend fix, `./start.sh`, `POST /api/engine/login`, `e2e_references.py --live --cases recreate,synthetic`, restart, `--after-restart`, comparison STOP card.

## 2026-10-23: Change recreate publication
- What changed: program root ruling on 2.5's block (entry 2026-10-23). Backend plan Phase 21, task 21.1 (coverage errors in the `publish` trace span; recreate and screenshot-only accepts publish with designed pages; fallback rule if a designed page breaks coverage); backend architecture.md#Designed pages coverage bullet + decision row, essentials, stamp. Release 2.5: `Needs: backend 21.1`, resume `If:` rewritten (stash 2026-10-23 09:30, full five-case rerun, read `coverage_errors` on a repeat), reopened. docs/program.md: deadline no longer binding, roadmap line, decision row; AGENTS.md program block deadline line.
- Why: since 18.2/20.x every recreate-mode accept fails publish coverage (422 "Candidate no longer fulfills the active requirements") with the errors invisible; style mode publishes. The deadline (2026-10-23 01:05 MPST) passed with 2.5 blocked; user kept the full scope and chose the backend fix (cards) over a designed-pages switch or a recorded limit.
- Tasks affected: backend 21.1 (new, M); release 2.5 (waits on it). 2.6 stays ready (Depends on 2.3 only); 3.x and 4.x unchanged.
- Change requests: none logged before this entry.
- Next: build backend 21.1 in backend/, then release 2.5 here.
