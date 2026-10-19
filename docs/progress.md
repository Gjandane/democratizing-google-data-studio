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
