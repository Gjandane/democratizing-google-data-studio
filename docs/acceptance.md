# Manual acceptance

The user's manual acceptance of real dashboards built through the local UI (`./start.sh`, the
engine's signed-in Chrome profile). One row per source; a row is PASS only on the user's verdict.

## Local, per data source (task 2.4)

Reference values are computed from the source itself, outside the app. Every build: Executive
dashboard, default outline and design, driven by the builder in the browser pane while the user
watched.

| # | Date | Source | Input | Build id | Last stage | Report link | Checked | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | 2026-10-22 | CSV upload | `samples/ecommerce_sales.csv` (2,000 rows) | b_ced0f5b4c491 | done (50/50 ops ok) | https://datastudio.google.com/reporting/8974f3ff-9a65-4aea-8520-3be0a6741aef | Total Revenue 436.6K = CSV revenue sum 436,628.79; orders 2.0K = 2,000; units 6.9K = 6,924; report opens with 4 pages | PASS |
| 2 | 2026-10-22 | Research mode | Prompt: "Nominal GDP of the ASEAN member countries, latest year, in US dollars" | b_568901c19819 | done, partial (35 ok, 6 failed) | https://datastudio.google.com/reporting/9e1d97e1-8435-48ad-b1f2-0a72fe5f4133 | Sources file `data/builds/b_568901c19819/v1/docs/sources.md` (Wikipedia "List of ASEAN countries by GDP", 12 rows). Nominal GDP 8.3M = sum of all 12 rows (8,339,090) incl. the "ASEAN" total row; members only 4,171,400; member count 12 vs 11; scorecard titles garbled. 3 tables: `add_chart` failed "Data Studio option 15 is unavailable" (`rows_per_page: 15`) | FAIL |
| 3 | 2026-10-22 | BigQuery table | `bigquery-public-data.thelook_ecommerce.order_items` (US, 181,995 rows), picked in Connect | b_b17ad783d730 | done, partial (42 ok, 3 failed) | https://datastudio.google.com/reporting/71856657-dbd2-4d0c-ac00-0439b06be136 | Direct query: gross 10,873,982.05 / orders 125,470 / items 181,995 / avg price 59.75, all match the report (10.9M, 125.5K, 182.0K, 59.75). Failed: "Active Customers" scorecard "field user_id not in data source" (the view has `user_id`; a default "Record Count" scorecard is left in its place); p1 date control "control box did not match the requested position and size" | FAIL |
| 4 | 2026-10-22 | CSV in GCS | `gs://$GCS_BUCKET/samples/ecommerce_sales.csv` (copy of row 1's file), picked in Connect (source kind `gcs`) | b_9ec14b32752e | done (48/48 ops ok) | https://datastudio.google.com/reporting/a55f3bc4-5a3b-4f6f-909f-a166743efce5 | Total Revenue 436.6K = 436,628.79; orders 2.0K = 2,000; units 6.9K = 6,924 | PASS |

Seen on every report (user accepted rows 1 and 4 with them): page 1 is named "Untitled Page";
scorecard values render in a tiny font at the box's top-left.

Screenshots (page 1, cropped to the canvas): `docs/img/acceptance-2.4-csv.png`,
`docs/img/acceptance-2.4-research.png`, `docs/img/acceptance-2.4-bigquery.png`,
`docs/img/acceptance-2.4-gcs.png`.
