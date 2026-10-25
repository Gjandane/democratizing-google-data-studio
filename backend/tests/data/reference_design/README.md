# Electricity reference acceptance fixture (task 24.7)

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
current native type catalog explicitly. Outputs, spans and screenshots go to
`.blueprint/qa/task-24.7/`; created BigQuery tables/views are cleaned after each case.

No unsupported alternatives have been approved for this fixture yet. The test
records unresolved feasibility issues and refuses to select or drop them itself.
Passing technical checks does not constitute the user's visual acceptance.
