# Electricity reference acceptance fixture (task 25.10; retained from 24.11/25.7/25.8)

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
(`GET /api/settings/capabilities` defaults) so no stored or `.env`-migrated profile
applies. The `none` case also turns `review_briefs` on before its accept: it edits
one treatment of page 1's brief, approves each page and checks that the published
`brief_p1.json` hashes to the edited brief. Outputs, spans, StageCalls, cost
estimates and screenshots go to `.blueprint/qa/task-25.10/<mode>/` (`task-24.7/` with
`DSS_LIVE_STAGE=24.7`, readiness-only `task-24.9/` with `DSS_LIVE_STAGE=24.9`);
created BigQuery tables/views are cleaned after each case. Earlier task evidence
(including `task-24.11/`) is preserved unchanged.

The user approved these substitutions on 2026-10-25:

- Drop geo_map; the real-geography globe remains static artwork.
- Drop the Rural/Urban legend whether extracted as a dropdown, control or chart
  (including `Location (%)`, user card 2026-10-27), and any extracted year slider.
- Replace four per-country small multiples with one native urban/rural area chart,
  expressed through the test's INSTRUCTIONS.
- Use a native fixed_size_list for the region selector.

For recreate, INSTRUCTIONS contain only definition clauses, with no periods inside
their labels. The four country definitions specify the same two metrics and area
chart. RECREATE_NOTES hold the approved alias/substitution and composition prose
(user ruling 2026-10-26). The additional recreate interview notes
group the reference observations on the first Outline section/page and reserve
a later section/page for extra analysis. The public workflow still chooses its
Outline and Blueprint; the test never edits rows or moves generated components.
Style and no-reference interview inputs are unchanged.

The test records each applied drop by observation and issue id. Any other
unsupported item blocks the check; it never selects an arbitrary alternative.
Each run retains full fixture and INSTRUCTIONS/effective notes SHA256 hashes,
the exact workflow inputs, native slot ids/bindings, compiled recipes, coverage,
per-stage model/image/token/time evidence and sanitized failed drafts when available.
`runs.json` distinguishes a failed check from an actually published prototype.
Passing technical checks does not constitute the user's visual acceptance.

Task 25.9 repairs the offline binding and recomputation checks before this live
acceptance. No live acceptance is claimed by that repair. The 25.10 harness checks
Region Selector authorization before planning, before accept and against the same
observation's published page-1 native control. Its one approved clause acceptance
is scoped to the complete campaign, including later assessments; duplicate reads
do not submit or record another acceptance. Originally blank image labels still
require a currently applying explicit decision, even if a worker filled the field.
All earlier evidence, including `.blueprint/qa/task-25.9/`, stays unchanged.
