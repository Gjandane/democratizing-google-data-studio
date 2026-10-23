# Contract: recipe and engine events
Version 1.2 · Change log: 1.0 (2026-10-18) first version, revised by the plan audit before any build
(`--timeout`, `error_code: timeout`, background file name); 1.1 (2026-10-22, change report quality)
`rename_page` op, scorecard value sizing and `colors` series order stated. Header `recipe_version`
stays "1.0" (the op is additive); 1.2 (2026-10-23, change live date buckets) `time_series` option
`date_granularity` and its rule; header still "1.0" (the option is additive, and engines before it
ignore unknown options).
Provider: backend writes recipes (its recipe compiler); engine writes events. Consumers: engine
reads recipes; backend reads events; release validates both. Machine-readable schema:
`contracts/recipe.schema.json` (JSON Schema 2020-12, `$defs`: `header`, `op`, `event`).
Fixtures: `contracts/fixtures/recipe.sample.jsonl`, `contracts/fixtures/events.sample.jsonl`
(the events fixture is abridged: it shows each event kind, not one event pair per op).

## Recipe file
UTF-8 JSON Lines, one JSON object per line, no blank lines.
- Line 1 is the **header**:
  `{"recipe_version": "1.0", "build_id": "b_...", "version": 1, "report_name": "...",
  "canvas": {"width": 1200, "height": 900}, "datasource": {"connector": "bigQuery",
  "project_id": "...", "dataset_id": "...", "table_id": "dash_b_..._v1"}}`.
- Every later line is one **op**: `{"id": "s001", "op": "<name>", ...args}`. IDs are unique and
  increasing. Ops run in file order.
- The engine always passes `GCP_PROJECT_ID` (contracts/conventions.md) as the BigQuery billing
  project, so `project_id` may name another project's table (e.g. `bigquery-public-data`).
- Paths in ops are relative to the recipe file's folder (e.g. `background_p1.png`).
- Colors are `#RRGGBB`. Geometry is integer px on the page canvas (contracts/conventions.md).

## Ops
| op | Args (required unless marked ?) | What the engine does |
|---|---|---|
| `open_report` | — (uses the header) | opens the Linking API create URL in edit mode with the header's BigQuery table as data source and `report_name`; ends on an editable page 1 |
| `set_canvas` | `width`, `height` | sets the current page's canvas size |
| `set_background_image` | `path`, `x`, `y`, `w`, `h` | inserts the image, sends it to the back, and locks it if the UI allows |
| `add_page` | `name` | adds a page and makes it current |
| `rename_page` | `name` | renames the current page (the backend names page 1 with it; `open_report` leaves it "Untitled Page") |
| `go_to_page` | `index` (1-based) | makes that page current |
| `add_chart` | `component_id`, `chart_type`, `x`, `y`, `w`, `h`, `dimensions` (list of field names), `metrics` (list of `{field, agg}`), `date_dimension`?, `breakdown`?, `sort`? (`{field, order: asc\|desc}`), `title`?, `options`? (object) | adds the chart, sets its fields, places it at the box |
| `add_control` | `component_id`, `control_type` (`date_range`\|`dropdown`), `x`, `y`, `w`, `h`, `field`? (dropdown) | adds the control at the box |
| `add_text` | `component_id`, `text`, `x`, `y`, `w`, `h`, `font_size`?, `color`?, `bold`?, `align`? (`left`\|`center`\|`right`) | adds a text box |
| `add_image` | `component_id`, `path`, `x`, `y`, `w`, `h` | uploads and places an image |
| `set_style` | `component_id`, `style` (object: `colors`? list, `show_title`?, `font_size`?, `background`?, `border_color`?) | styles an existing component; `colors` apply in order to the chart's series swatches, extra colors ignored; unsupported keys are skipped with a message |
| `save_report` | — | makes sure the report is saved in the user's account ("Edit and share" if shown) |
| `get_link` | — | reads the report's view URL; returned in `run_finished.report_url` |

- `chart_type`: `scorecard`, `time_series`, `bar`, `pie`, `table`, `pivot_table`, `geo_map`,
  `scatter`.
- `agg`: `sum`, `avg`, `count`, `count_distinct`, `min`, `max`, `none`.
- `options` by chart type (all optional): `bar`: `orientation` (`vertical`\|`horizontal`),
  `stacked` (bool); `pie`: `donut` (bool); `pivot_table`: `row_dimensions`, `column_dimensions`
  (lists, which replace `dimensions`); `geo_map`: `geo_type` (`country`\|`region`\|`city`);
  `table`: `rows_per_page` (int); `scorecard`: `compact_numbers` (bool); `time_series`:
  `date_granularity` (`day`\|`week`\|`month`\|`quarter`\|`year`).
- Time series granularity: with `date_granularity` the engine sets the chart's date dimension
  (`date_dimension`) to that granularity in the chart (Data type -> Date & Time), so a bucket
  field such as `DATE_TRUNC(order_date, MONTH)` draws one point per bucket instead of a daily axis
  with zeros between the buckets. Without it the field keeps the type Data Studio infers (a DATE
  column draws per day). The backend sets it from the view's derivation, never from model output.
- Scorecards (engine behaviour, no argument): the value is sized to the box like the prototype,
  `clamp(16, h - 28, 36)` px (Data Studio's largest offered size not above it), and the metric
  name is hidden when `title` is set, since the title carries the label.
- Field names are BigQuery column names of the header's table, exactly.

## Engine CLI (provided by engine)
- `dsengine run <recipe.jsonl> [--dry-run] [--screens <dir>] [--screencast] [--timeout <s>]`: runs the recipe and
  writes **events** to stdout, one JSON object per line, flushed per line. Human logs go to stderr.
  `--dry-run` validates and emits the same event sequence without a browser (every op `skipped`,
  `run_finished.status` `ok`, `report_url` null).
- `dsengine validate <recipe.jsonl>`: exit 0 if valid, else exit 2 with the first error on stderr.
- `dsengine print <recipe.jsonl>`: prints one CLI line per op, e.g.
  `dsengine add-chart --id p1_rev_by_region --type bar --x 24 --y 120 --w 560 --h 300 --dim region --metric revenue:sum`.
- `dsengine browser`: starts Chrome with the dedicated profile and remote debugging (no-op if running).
- `dsengine login`: opens the Google sign-in page in that Chrome and waits until signed in (or 5 min).
- `dsengine check`: prints `{"chrome_running": bool, "signed_in": bool}` and exits 0.

Exit codes of `run`: 0 = finished with status `ok` or `partial`; 1 = `failed`; 2 = invalid recipe
(no events after the error event); 3 = not signed in (`run_finished.error_code: "not_signed_in"`).
`--timeout` (default `DSS_ENGINE_TIMEOUT_S`, 600) ends the run: remaining ops are not started,
`save_report` and `get_link` are still attempted, then `run_finished` with `error_code: "timeout"`.

## Events (stdout of `dsengine run`)
Every event has `event` and `ts` (ISO 8601 UTC).
| event | Fields |
|---|---|
| `run_started` | `build_id`, `version`, `total_ops` |
| `op_started` | `op_id`, `op` |
| `op_finished` | `op_id`, `op`, `status` (`ok`\|`failed`\|`skipped`), `message` (string, empty when ok), `screenshot` (path relative to the screens dir, or null), `duration_ms` |
| `frame` | `data` (base64 JPEG), only with `--screencast` |
| `log` | `level` (`info`\|`warn`\|`error`), `message` |
| `run_finished` | `status` (`ok`\|`partial`\|`failed`), `report_url` (string or null), `ok`, `failed`, `skipped` (counts), `error_code` (string or null) |

- `partial`: at least one op failed but `open_report`, `save_report` and `get_link` succeeded.
- `failed`: `open_report`, `save_report` or `get_link` failed, or the run aborted.
- A failed op never stops the run, except `open_report` (the run ends `failed`).
