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

## Local, screenshot + synthetic data (task 2.6)

Recreate mode from the user's "Access to electricity" screenshot (not committed), no CSV:
Executive dashboard, reference analysis approved in the References panel, synthetic CSV
generated in the UI, outline and design as prefilled from the reference.

| # | Date | Source | Input | Build id | Last stage | Report link | Checked | Verdict |
|---|---|---|---|---|---|---|---|---|
| 5 | 2026-10-28 | Screenshot + synthetic data (user screenshot) | user screenshot (recreate); synthetic CSV 2,000 rows, seed 42, sha256 eb6e5770..., columns country, region, year (DATE, Jan 1 2000-2019), access_pct, urban_pct, rural_pct, people_without_access | b_236ae4aa34ee | done, engine `partial` (33 ok, 16 failed of 49) | https://datastudio.google.com/reporting/67390721-34a6-443f-96de-2f2428bcd1c9 | "Synthetic sample data" label once per page in the prototype and in the report; prototype designer spans `images: 1`, globe art `globe-europe-africa` on background_p1; recipe: 4 country `area` with `date_granularity: year`, region list `fixed_size_list`, split bar `stacked_percent` | PASS with findings (user, 2026-10-29: "Accept it now and add it to the report weaknesses") |

Reference split: Flash proposed 10 native (headline text, rural/urban bar, 4 country areas,
continent list, globe `geo_map`, 78 % scorecard, yearly bar) and 4 static (2 legends, bottom card
title, year slider). User changes: headline and globe to static. Approved: 8 native, 6 static.

Capability matrix (page 1 against the screenshot):

| Element | Result | On its panel |
|---|---|---|
| Headline | background decoration | yes |
| Region checkbox list | live `fixed_size_list` (shows an extra Record Count column) | yes |
| 78 % KPI and caption | KPI live `scorecard` AVG(access_pct) (55.11 on synthetic rows); caption missing; 2 extra scorecards added (total without access, countries) | yes |
| Globe | background decoration (static globe art) | yes |
| Color legend (map scale) | missing (not drawn on the background) | - |
| Year bar chart, 2011 highlighted | live `bar` on `year`; highlight missing (deferred); labels per day, top 10 + "Others" | yes |
| Year slider | substituted by a live `date_range` control | yes |
| Rural/urban split bar | live `bar` 100 % stacked; only 1 of 6 region rows visible | yes |
| Four country area charts | live `area` x4, wrong fields: each shows Record Count by region instead of the country's rural/urban % | yes |

Screenshot (page 1, report view): `docs/img/acceptance-2.6-synthetic.png`.

### Known weaknesses (2.6, to fix later)

Found in the run above; each names the part that owns the fix. Open until a task fixes it.

| ID | Part | Where | Symptom | Evidence |
|---|---|---|---|---|
| W1 | engine | `add_chart` area (s008, s013, s017, s020, s029) | Data Studio pre-fills a new area chart with breakdown `region` and metric Record Count; the engine can't remove them ("Data Studio does not expose a field removal control"), the chart keeps the wrong fields and its set_style fails | screencast rerun 2/2, last frame: Area chart properties with the auto fields |
| W2 | engine | box placement (s005 bar, s019 date_range, s038/s044 table) | "chart box did not match the requested position and size"; the split bar shows 1 of 6 rows | screencast rerun 2/2 (s005) |
| W3 | engine | `add_chart` area with breakdown (s033) | "field year not in data source" | events.jsonl |
| W4 | contract/backend | yearly `bar` on a DATE column (s015) | recipe 1.3 allows `date_granularity` only on time_series/area: bar labels "Jan 1, 2000" and groups beyond 10 into "Others" | recipe.jsonl s015 options |
| W5 | backend | prototype background | static legends (rural/urban, map scale) not drawn on background_p1 | background_p1.png |
| W6 | backend | prototype render | page-1 reference HTML failed validation 3x on the first run; retry passed | trace r_2051c7758120 |
| W7 | backend | scorecard pick | KPI caption missing; two non-reference scorecards on page 1 | report page 1 |
