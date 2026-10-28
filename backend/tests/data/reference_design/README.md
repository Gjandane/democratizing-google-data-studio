# Electricity reference acceptance fixture (task 26.6; retained from 24.11/25.7-25.11)

The image is the existing user-supplied electricity dashboard reference, retained by
the earlier backend live run. It is a visual reference, not a data source.

- `electricity-access.jpg`: copied unchanged from
  `.blueprint/qa/task-24.5/reference/20261025-001939-30a57d57/build/reference_img_bfc820b06597.jpg`.
  SHA256 `1c30b41832d16d21fcb74827d5b13aa6bd2861a978c647761ee07200f05e32a9`.
- `sample.csv`: the previous synthetic electricity dataset, copied unchanged from
  `../data/generated/b_697880743b4f/sd_be69ee97-1e8d-47d6-9ded-58e65a9e295d/sample.csv`.
  SHA256 `eb6e57703776bd8f4514922733a9ef1c21525ce1f6f00cdbc57c702331820c82`.
- `generation.json`: the exact `spec` from that source's `metadata.json`;
  SHA256 `413051729b9ced475b43102abdb42de59c9f529993024db0b933b59ab52816ab`.
  dss-synthetic/1, seed 42, 2,000 invented rows, originally generated
  2026-10-23T16:02:23.974381Z. The original provenance says:
  "Manual schema entered by the user; every row is invented sample data."

The live test regenerates this schema through the synthetic-data API and requires
byte equality with the retained CSV. This establishes genuine synthetic provenance
and the protected sample-data footer, rather than uploading invented data as real.
All runtime inputs are in this directory. No other part's files or old build is
needed to reproduce it. Full hashes for every fixture are also saved per run.

Run from backend: `uv run pytest -m live tests/live/test_reference_design.py`.
Real configured models and BigQuery are required. The test sets dry engine and the
current native type catalog explicitly, and PUTs the contract default stage Settings
(`GET /api/settings/capabilities` defaults, api.md 3.2) so no stored or `.env`-migrated profile
applies. The `none` case also turns `review_briefs` on before its accept: it edits
one treatment of page 1's brief, approves each page and checks that the published
`brief_p1.json` hashes to the edited brief. Outputs, spans, StageCalls, cost
estimates and screenshots go to `.blueprint/qa/task-26.6/<mode>/` (`task-24.7/` with
`DSS_LIVE_STAGE=24.7`, readiness-only `task-24.9/` with `DSS_LIVE_STAGE=24.9`);
created BigQuery tables/views are cleaned after each case. Earlier task evidence
(including `task-24.11/`) is preserved unchanged.

Since task 26.6 (api.md 3.2, change 2026-10-28) a recreate upload gets a Flash
reference analysis: every visible item is proposed as a native catalog component or
static art, and nothing downstream runs until the split is approved. The harness
plays the user at that gate on the split the user agreed (by position):

- the yearly bar (bottom) native `bar`, the urban/rural panel (right) native
  `area` and the region list (left) native `fixed_size_list`, each found by kind,
  type candidates and box region (`play_gate`), never by item order or id;
- when the analysis splits the right panel into several charts (26.6 run 1: four
  country panels), every right-hand chart is native `area` (user card 2026-10-28);
- the globe and every legend static;
- every other native or static choice Flash makes is kept and named at the STOP.

It PUTs only those changes and approves; `analysis-proposed.json`,
`analysis-approved.json` and `runs.json` (`analysis`, `gate`) record the proposal,
the changes and the approved split. If the yearly bar or the region list can't be
identified (none, or more than one candidate), or no right-hand chart exists, the
case blocks with the analysis. No feasibility drop or alternative is played; an issue
after planning blocks. The earlier observation drops, Region Selector offer and
year-slider rules (25.10/25.11) are retired.

INSTRUCTIONS and RECREATE_NOTES are unchanged from the earlier campaigns; since
1.3 they reach the analysis and the planner as untrusted text, not as definition
clauses. Style and no-reference interview inputs are unchanged; style mode has no
analysis and no gate. The public workflow still chooses its Outline and Blueprint;
the test never edits rows or moves generated components.

Each run retains full fixture and INSTRUCTIONS/effective notes SHA256 hashes,
the exact workflow inputs, each native item's Blueprint rows and component ids,
publish coverage, compiled recipes, per-stage model/image/token/time evidence
(StageCalls) and sanitized failed drafts when available. `runs.json`
distinguishes a failed check from an actually published prototype. Passing
technical checks does not constitute the user's visual acceptance. All earlier
evidence (`.blueprint/qa/task-24.x` through `task-25.11/`) stays unchanged.
