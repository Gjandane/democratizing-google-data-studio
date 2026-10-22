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
| 2 | 2026-10-22 | Research mode | Prompt: "Nominal GDP of the ASEAN member countries, latest year, in US dollars" | b_ca4845ae0e0b | done (45/45 ops ok) | https://datastudio.google.com/reporting/99e01bfb-2a28-44bd-b3b2-2951bfab9685 | Sources file `data/builds/b_ca4845ae0e0b/v1/docs/sources.md` (Wikipedia "List of ASEAN countries by GDP"; the "ASEAN" aggregate row left out, 11 rows). Total GDP (PPP) 13.3M = CSV sum 13,256,570; population 700.0 = 700.025; Reporting Countries 11; nominal GDP pie Indonesia 34.5% = 1,440,000 / 4,171,400. Scorecard titles clean; tables `rows_per_page` 15 applied as 10 | PASS (user: scorecard text size needs an audit; background images look low-definition, maybe render the HTML background to an HD PNG) |
| 3 | 2026-10-22 | BigQuery table | `bigquery-public-data.thelook_ecommerce.order_items` (US, 181,995 rows), picked in Connect | b_a8ace098d03b | done (52/52 ops ok) | https://datastudio.google.com/reporting/fa9cf040-9e02-4a90-bfac-05620ac5c1a1 | Direct query: gross 10,873,982.05 / orders 125,470 / items 181,995 / distinct users 80,028 / avg price 59.75, all match the report (10.9M, 125.5K, 182.0K, Total Customers 80.0K, 59.75); p1 date range control beside the status dropdown, no overlap | PASS |
| 4 | 2026-10-22 | CSV in GCS | `gs://$GCS_BUCKET/samples/ecommerce_sales.csv` (copy of row 1's file), picked in Connect (source kind `gcs`) | b_9ec14b32752e | done (48/48 ops ok) | https://datastudio.google.com/reporting/a55f3bc4-5a3b-4f6f-909f-a166743efce5 | Total Revenue 436.6K = 436,628.79; orders 2.0K = 2,000; units 6.9K = 6,924 | PASS |

Rows 2 and 3 are the reruns of 2026-10-22 after engine 10.1 and backend 17.1 (the first runs,
b_568901c19819 and b_b17ad783d730, failed: aggregate row counted, table rows-per-page, `user_id`
field lookup, date control box). Builder observation on every report: page 1 is named "Untitled
Page" and scorecard values render in a tiny font at the box's top-left (the user passed rows 1 and 4
with them; on row 2 the user flagged the scorecard text size and low-definition backgrounds).

Screenshots (page 1, cropped to the canvas): `docs/img/acceptance-2.4-csv.png`,
`docs/img/acceptance-2.4-research.png`, `docs/img/acceptance-2.4-bigquery.png`,
`docs/img/acceptance-2.4-gcs.png`.
