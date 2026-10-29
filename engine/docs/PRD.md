# PRD: engine
Target: POC · Written 2026-10-18 · Kind: a part of a program (../docs/program.md)

## Problem
Data Studio has no API that creates charts or layout (only the Linking API, which opens a report
with a data source). Having an LLM look at the screen and click is slow and burns tokens. The
engine replays a compiled recipe of UI ops deterministically, with no LLM in the loop.

## Users
- backend: runs `dsengine run` as a subprocess and relays its events to the UI.
- the demo user: watches the light Chrome window build the dashboard, and signs in once by hand.

## Goals
1. `dsengine run recipe.jsonl` builds the recipe's dashboard in the signed-in account and prints
   the report link, with each op's result as an event (contracts/recipe.md).
2. Every op in contracts/recipe.md is implemented; at least 90% of the ops in the live golden
   recipe finish `ok`.
3. A 20-op recipe finishes in under 5 minutes.
4. A failed op never stops the run (except `open_report`): it is reported, screenshotted and skipped.

## Non-goals
- No LLM or vision calls inside the engine (token budget; the recipe is complete).
- No automated Google sign-in and no password handling: the user signs in by hand once.
- No editing of reports the engine didn't create in this run.
- No Data Studio blends or calculated fields (the backend's BigQuery view holds them).
- No headless/Cloud Run mode: the engine always runs on the user's machine; for the hosted app the
  backend's `dss-agent` runs `dsengine run` locally (change 2026-10-19). The engine CLI is unchanged.
- No CI.

## Core flows
1. backend runs `dsengine run data/builds/<id>/v1/recipe.jsonl` -> engine attaches to Chrome
   (starts it if needed) -> opens the Linking API URL in edit mode -> runs each op -> saves ->
   prints `run_finished` with `report_url`.
2. First use: `dsengine login` opens Chrome with the dedicated profile at the Google sign-in page;
   the user signs in; `dsengine check` then reports `signed_in: true`.

## Features
| Must | Should | Won't (this version) |
|---|---|---|
| CLI: run, validate, print, browser, login, check; `--dry-run` | `--screencast` frames | headless Cloud Run mode |
| ops: open_report, set_canvas, set_background_image, add_chart (8 types), add_control, add_text, save_report, get_link | add_image, set_style, add_page, go_to_page | theme editing |
| selectors in an OKF bundle (`knowledge/datastudio-ui/`) | read-back verification of boxes | self-healing selectors via LLM |

## Constraints
- Hard deadline 2026-10-23 01:05 MPST (the whole program; current program guide).
- Windows 11 machine with Google Chrome installed; Python 3.12 + uv.
- Data Studio UI can change; selectors live in data files so a fix is a data edit.

## Success criteria
- The golden live recipe produces a report link that opens in Data Studio with the charts at the
  recipe's boxes (manual check against the recipe).
- `uv run pytest` passes; `--dry-run` output validates against contracts/recipe.schema.json.

## Decided by default
- CLI framework: argparse (stdlib), no extra dependency (10-hour deadline).
- Live tests use the public table `bigquery-public-data.thelook_ecommerce.order_items`, billed to
  `GCP_PROJECT_ID`, so the engine never waits on the backend's intake.
- Chrome: the installed Google Chrome, started normally with `--user-data-dir` and
  `--remote-debugging-port`, then attached with Playwright `connect_over_cdp` (Google often refuses
  sign-in in automation-launched browsers).

## Open questions
- none (the spike, task 1.3, answers the UI unknowns and stops for the user)

## Later
- Intermittent editor insertion/verification timeouts remain: one 20-op audit run timed out
  inserting page-2 text (18/20 ok), while its focused repeat and final full suite passed; the
  final screencast reported a table timeout despite all five saved charts rendering (9/10 ok,
  within the golden criterion). Causes remain unconfirmed; retain failed evidence alongside
  passing reruns (audit 2026-10-21, task 7.1 re-audit).
- The exact-dialog selector regression checks selector strings rather than accessible-name
  behavior; live acceptance remains the semantic check (audit 2026-10-21).
- Headless mode with a stored session for Cloud Run (program, next version).
- LLM-assisted selector repair on failure (plan).
- Successful geo-map rendering on a compatible geographic source remains unverified; the
  current public source exercises the explicitly permitted incompatible-field failure (audit 2026-10-19).
- Full report-building coverage, including native calculated fields and persistent filters,
  requires separate scope/contract planning; docs/coverage-audit.md records the proposals
  (audit 2026-10-19).
- Clarify timeout lifecycle wording with the architect at the program root: the engine emits
  skipped event pairs for remaining ops while suppressing their UI execution, as task 2.1
  decided and current tests require; the contract says remaining ops are not started
  (audit 2026-10-19).
- Release 2.6 weaknesses (change 2026-10-29, deferred; ../docs/acceptance.md, build
  b_236ae4aa34ee, report 67390721-...): W1 a new `area` chart on a source Data Studio pre-fills
  (breakdown `region`, metric Record Count) keeps those fields ("Data Studio does not expose a
  field removal control"), so its set_style fails (s008 s013 s017 s020 s029); W2 boxes miss the
  requested position/size for a 100% stacked bar (s005, 1 of 6 rows shown), date_range (s019)
  and tables (s038, s044); W3 `area` with a breakdown: "field year not in data source" (s033).
  Oracle for the fix: replay those ops from that build's recipe live with failed 0. Also W4
  (contract): applying `date_granularity` on `bar` (a recipe version after 1.4), before the backend emits it.
