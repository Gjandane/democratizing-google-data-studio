# v2 handoff: dashboards in each visitor's own Looker Studio

Written 2026-10-29 by the release architect, at the user's request, while v1 finishes phase 4.
Not a plan: v2 gets its own interview. Open the v2 session at the new repo's root and run
`/blueprint-solution-architect` (new version, program mode); this file is its starting brief.
Facts marked **verify** come from memory, not a check; confirm them before relying on them.

## Contents
1. v2 goal
2. Where v1 ends
3. Why v1 can't do it (constraints)
4. Design space for the interview
5. New repo: the builder's first task
6. Carried over from v1 (deferred work)
7. Open questions for the v2 interview
8. v1 files to read

## 1. v2 goal
In the user's words (2026-10-29): anyone opens the hosted link and signs in with Google, gives
access to their Looker Studio (Data Studio) account, and the agent builds the dashboard **on their
own machine, in their own account**. They never install Python: the cloud backend and the build
agent do the work.

So, v2 must deliver:
- Per-visitor builds: the report, its data source and its data belong to (or are readable by)
  the visitor's Google account, not the owner's.
- No dependency on the owner's computer: v1 builds only on the owner's machine (local app and
  signed-in Chrome); the hosted v1 stops at the recipe.
- A zero-Python agent on the visitor's machine, paired with their signed-in app session.
- Per-user isolation: history, engine lock/queue, data, settings and spend.

## 2. Where v1 ends
- Parts: engine (`dsengine`, Python Playwright driving Data Studio's UI), backend (ADK 2.0,
  staged workflow, BigQuery intake, compiler, API, `dss-agent`), frontend (React/Vite), release
  (e2e drivers, Dockerfile, `deploy/deploy.sh`, README, deck). Contracts in `contracts/`
  (recipe 1.3, api 3.3, conventions 1.5, dashboard-intent 1.3, synthetic-data 1.3).
- Release plan at handoff: phases 1-3 done; 4.1 deploy, 4.2 hosted e2e, 4.3 hosted acceptance (both up to the recipe),
  4.4 README + final push still to do. Tag v1 (e.g. `v1.0`) after 4.4; v2 starts from that tag.
- v1 hosted behavior (contracts/conventions.md, Cloud deployment and Build agent):
  - One Cloud Run service `dss-frontend` (backend + built frontend, no engine), one instance,
    SQLite restored from a GCS volume, secrets in Secret Manager.
  - In-app Google sign-in (basic scopes, identity only; frontend 18.1, backend 27.1); access code
    for scripts. Any Google account unless `DSS_SIGNIN_ALLOW` narrows it.
  - Everyone shares one history, one engine lock, the owner's Gemini key and BigQuery project.
  - Hosted v1 stops at the recipe (change 2026-10-29 hosted scope): no agent connects, Build answers
    `424 agent_offline`. `dss-agent` against the hosted URL (backend 5.2/5.3, one shared
    `DSS_AGENT_TOKEN`, the owner's `.chrome-profile`) is built but never accepted hosted, and the
    hosted Build panel still shows its command, which visitors can't run without the token.
  - The report lands in the owner's Data Studio; nothing shares it with the visitor, so they most
    likely can't open the `report_url` unless the owner shares it by hand.

## 3. Why v1 can't do it (constraints)
- No API builds report content: Looker Studio has no public API to create or edit charts and
  pages (**verify**: the Looker Studio API covers asset search and permissions; the Linking API
  creates a report from a template by URL). So the build stays UI automation, and it must run in a
  browser session signed in as the visitor.
- Sign-in is identity, not access: Google sign-in (or IAP, a v1 non-goal) proves who the visitor
  is; it lets no server act inside their Looker Studio.
- No automated Google sign-in and no password handling: a cloud browser signing in as each visitor
  is out (Google blocks it; handling passwords is off-limits). The visitor's own browser, already
  signed in, is the only place the build can run.
- Data must be readable by the visitor's account: v1 loads every source into the owner's BigQuery
  dataset and the report's data source reads its views. Options in section 4.
- Chrome remote debugging: since Chrome 136, `--remote-debugging-port` is ignored on the default
  user-data dir (**verify**). v1 already uses a dedicated profile (`.chrome-profile`) the user signs
  into once; an exe agent would do the same.
- Hosted spend: every signed-in visitor spends the owner's Gemini and BigQuery; v2 needs per-user
  quotas or bring-your-own key.

## 4. Design space for the interview
Not decided; each needs a card in the v2 interview.

**A. The zero-Python agent**
| Option | How | Cost / risk |
|---|---|---|
| A1 Chrome extension (MV3) | Runs in the visitor's own signed-in Chrome; content scripts and/or `chrome.debugger` drive Looker Studio; talks to the backend with a per-user token | Engine is Python Playwright today: port ops/selectors to TypeScript (largest rewrite). Chrome Web Store review or unlisted listing. No separate profile or sign-in |
| A2 Packaged agent exe | `dss-agent` + engine frozen into one binary (PyInstaller/Nuitka, **verify** Playwright support), attaches to the visitor's installed Chrome (`channel="chrome"`, dedicated profile) | Keeps the Python engine. Download of an unsigned exe (SmartScreen, macOS notarization), per-OS builds, auto-update; visitor signs into Google once in that profile |
| A3 Hosted build + copy link | Owner-side agent builds, visitor gets a Linking API URL that copies the report into their account (**verify** it keeps generated layouts and can repoint data sources) | No visitor install, but the owner's machine/agent stays in the loop: misses the "on their own machine" goal; spike first |

**B. Pairing and tokens**: the visitor signs in on the web app, then pairs the agent (one-time code
or link), getting a per-user, revocable agent token; the shared `DSS_AGENT_TOKEN` goes away. Jobs
route to the requesting user's agent only.

**C. Visitor data access**
- C1 Owner's BigQuery, per-user dataset, IAM grant (BigQuery Data Viewer + Job User) to the
  visitor's email: no new OAuth scope; owner pays storage and queries.
- C2 Visitor's own BigQuery project: OAuth BigQuery scope (sensitive -> Google app verification),
  visitor pays; their project needs billing.
- C3 Looker Studio-native sources (Google Sheets, file upload connector): joins/derived fields lose
  the SQL-view approach; recipe and engine changes.

**D. Multi-user backend**: per-user history, memory and settings; per-user engine lock (a queue per
agent); BigQuery/GCS paths per user; more than one Cloud Run instance means SQLite on a volume no
longer works (Cloud SQL or Firestore; backend PRD Later). Lifts v1 non-goals: per-user accounts,
data isolation, more than one instance.

**E. Spend**: per-user daily caps, or bring-your-own Gemini key in Settings.

## 5. New repo: the builder's first task
The user wants v2 in a new GitHub repo, set up by the builder (plan it as v2's task 1.1, with a
STOP before anything is created or pushed). Points to settle in the interview:
- Name and owner (e.g. `Gjandane/democratizing-google-data-studio-v2`), public or private.
- Seed: a copy of v1 at its final tag with history (`git clone` + new remote) or a fresh history
  from that tree. Keep the four-part layout and `contracts/`.
- v1 docs: move each part's docs into `docs/archive/v1/` (blueprint new-version flow) so v2 plans
  start clean but keep the record; carry this file in as the v2 brief.
- Never copied: `.env`, `data/`, `.chrome-profile/`, `.venv/`, `node_modules/`, `.blueprint/`.
  `.env.example` names only. Repo stays free of the hosted URL and project number.
- Cloud: a new Cloud Run service (or project) so v1's submitted URL keeps serving v1; new secrets,
  OAuth client and origins.
- `.claude/` skill copies refreshed from `~/.claude` as in v1.

## 6. Carried over from v1 (deferred work)
Release (docs/PRD.md, Later):
- **2.7** (deferred 2026-10-29): full local live pass of `e2e_references.py --cases synthetic,recreate`.
  Code is in (recipe places no label text; recreate analysis approved before design/confirm;
  `.env.example` names). Open point: after an outline Other on a built version the synthetic GPS
  assessment reads `stale`, not `blocked`; v1 4.3 accepts `stale` with unresolved GPS issues and a
  refused recipe. Backend should return `blocked` there.
- **2.8** (deferred 2026-10-29): drivers wait per action from `GET /api/settings` stage clocks
  (blueprint/comments 2 x (html_brief + larger HTML profile timeout) + 300 s, design confirm
  native_planning + 300 s, reference upload reference_interpretation + 300 s, never under 600 s;
  3,900/900/900 s on the fixture) instead of a fixed 600 s; check_contracts parses every
  stage-settings fixture and checks every event in events.review.sse against api.md. (Its bench
  `server_url: "hosted"` mask moved into v1 4.2/4.3.)
- Multi-instance Cloud Run with a managed database; CI for every part.
- Connect stage: a 201 GCS source shows without reload; slider control, per-chart filters, single
  highlighted bar; frontend dead end after Remove references.

Known weaknesses W1-W7 (docs/acceptance.md, build b_236ae4aa34ee):
- Engine W1-W3: pre-filled `area` fields can't be removed; boxes miss position/size (100% stacked
  bar, date_range, tables); `area` with breakdown "field year not in data source".
- W4 (contract): recipe 1.4 `date_granularity` on `bar` with a DATE dimension (engine first,
  backend emits after).
- Backend W5-W7: static legends missing from background_p1; page-1 reference HTML failed
  validation 3x before a retry passed; KPI caption missing and two extra scorecards on page 1.

Per part (read each part's docs/PRD.md `## Later` in full; headlines here):
- engine: headless mode with a stored session (v1 non-goal, rethink for v2); LLM-assisted selector
  repair; intermittent insert/verify timeouts; geo-map on a compatible source unverified; full
  coverage (native calculated fields, persistent filters; engine/docs/coverage-audit.md); canvas
  placement above ~1380 px; time_series "Too Many Rows" timeouts.
- backend: Cloud SQL/Firestore and more than one instance; date-grain parity; designer canvas
  clamp to 1200; one view per page for unjoinable sources; document upload as context;
  Eval -> Gate -> Release loop; calculated fields; consolidated-index bounds; many P2/P3 audit items.
- frontend: real per-step progress; live view of the agent's Chrome in the hosted app (fits v2's
  visitor agent); responsive layout; audit P2/P3 lists.
- program root (docs/program.md): reconcile Outline Other preservation vs dashboard-intent; engine
  timeout-lifecycle wording.

## 7. Open questions for the v2 interview
1. Agent form: Chrome extension (A1), packaged exe (A2), or a copy-link spike first (A3)?
2. Whose data and whose bill: owner's BigQuery with per-user grants (C1), visitor's project (C2),
   or native sources (C3)? Who pays Gemini (owner caps or bring-your-own key)?
3. Who may sign in: anyone, an allowlist, or invites; is Google app verification acceptable
   (needed for a BigQuery scope)?
4. Per-user isolation depth: history and settings only, or memory/consolidation per user too?
5. Scale: one instance plus a queue, or several instances with a managed database?
6. Does v1's "owner agent" mode stay as a fallback (demo, offline judges)?
7. Target: POC again or MVP (tests, CI, a Web Store listing or signed binaries)?
8. Which deferred items in section 6 are in v2 scope, and which carry forward again?
9. New repo details (section 5): name, visibility, history, new Cloud Run service or project.

## 8. v1 files to read
- docs/program.md (parts, roadmap, decision log, research facts), docs/PRD.md (release goals, Later).
- contracts/conventions.md (Build agent, Cloud deployment), contracts/api.md (Access, Agent
  endpoints), contracts/recipe.md.
- engine/AGENTS.md and engine/docs (how the Playwright engine drives Data Studio; the port cost
  for A1).
- backend/docs/PRD.md and its Later list; frontend/docs/PRD.md Later.
- docs/acceptance.md (W1-W7), docs/progress.md (latest entries), AGENTS.md Known gotchas.
