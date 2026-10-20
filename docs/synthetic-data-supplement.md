# Supplement: recreate a dashboard without an uploaded dataset
Written 2026-10-20. Supplements the current architect review; no new task markers or scope
approval. The authoritative contract is contracts/synthetic-data.md 1.1 with API 1.4, and the
current backend/frontend/release plans determine implementation order.

## User requirement
A user may provide only a dashboard screenshot. The app must offer to generate a fake CSV using
a reusable Python script/API whose inputs include schema and number of rows. It must work from
a local folder and within the existing GCP deployment.

## Expected experience
1. Create a dashboard and attach a reference in Recreate dashboard mode, without uploading CSV.
2. Choose Generate sample data. The model proposes field names, types, generation rules and
   assumptions from the reference observations. This step must work with zero connected sources.
3. Review/edit the proposed schema, row count and seed. Defaults are 1,000 rows and seed 42.
   A manually specified schema also works without an image or a model call.
4. Click Generate sample data. Python creates the CSV; the app loads it into BigQuery using
   declared types, verifies the row count, and registers a source labeled Synthetic sample data.
5. Download the CSV or continue through the interview, feasibility review and dashboard build.
   Source UI, prototype and final report retain the Synthetic sample data label.

The model proposes the schema; Python produces the rows. The user is accepting an invented sample
dataset, not recovery of the original screenshot's underlying records. A screenshot's Revenue
label can inspire a field or formula, but an assumed definition must be shown as an assumption.

## Concrete request example
Illustrative body for the planned `POST /api/builds/{id}/synthetic-data` route. It uses a manual
schema (`proposal_id: null`); a screenshot-derived proposal supplies its current proposal ID.

```json
{
  "generation_key": "sales_demo_001",
  "proposal_id": null,
  "spec": {
    "schema_version": 1,
    "row_count": 1000,
    "seed": 42,
    "columns": [
      {
        "name": "region",
        "type": "string",
        "nullable_fraction": 0,
        "generator": {"kind": "choice", "values": ["East", "West"]}
      },
      {
        "name": "quantity",
        "type": "integer",
        "nullable_fraction": 0,
        "generator": {"kind": "integer", "min": 1, "max": 8}
      },
      {
        "name": "unit_price",
        "type": "number",
        "nullable_fraction": 0,
        "generator": {"kind": "decimal", "min": 10, "max": 100, "decimals": 2}
      },
      {
        "name": "revenue",
        "type": "number",
        "nullable_fraction": 0,
        "generator": {"kind": "product", "fields": ["quantity", "unit_price"], "decimals": 2}
      }
    ]
  }
}
```

For the planned standalone CLI, save only the `spec` object as schema.json and run from backend:
`uv run python -m dss.data.synthetic --request schema.json --output sample.csv`.
The reusable function is `generate_csv(spec, output_path)`. These are planned interfaces, not a
claim that this session has implemented or executed the script. The CLI does not need BigQuery
or Gemini; the HTTP workflow adds storage, intake, provenance and job tracking.

## Storage and recovery alignment
- Local service: DSS_DATA_DIR/generated/<build_id>/<generation_key>/sample.csv plus metadata.
- Hosted service: the same logical location under the existing GCS-backed /data volume. Generate
  in local temporary storage first; no new bucket, storage SDK or browser-selected gs:// path.
- Keep the other architect's v1.1 generation-table and best-effort immediate-backup decision.
  The earlier v1.0 immutable-manifest proposal is superseded and must not be restored by this
  supplement. Job status and cleanup readiness govern retries; missed SSE events are recoverable.
- Exact field types and record counts must survive intake, including null columns/all-empty
  records and string IDs such as 001. Use the current typed-loading/null-marker design from the
  backend plan, not the ordinary upload normalizer that drops empty rows.

## Current ownership and gates
| Part/task | Existing responsibility |
|---|---|
| backend 12.1 | Parameterized deterministic CSV generator and CLI |
| backend 12.2 | Generation API, typed intake, job status and download |
| backend 12.3 | Screenshot schema proposal |
| backend 12.4 | Immediate backups and interrupted-job recovery |
| backend 12.5 | Synthetic label through prototype/report and live flow |
| frontend 11.1 | Schema review, count/seed controls, generation and download; needs backend 12.3 |
| release 2.5, 2.6, 4.3 | End-to-end and manual acceptance, local then hosted (release plan, change 2026-10-20 final phases) |

## Acceptance reminders for the existing tasks
- Begin with only an image, no CSV and no preexisting source; complete a labeled real report.
- Change row_count and verify that both the downloaded CSV and BigQuery contain exactly that
  number of records. Same schema/seed/generator version gives identical CSV bytes.
- Preserve declared numeric/date/string types and configured relationships such as revenue =
  quantity * unit_price. Reject invalid schemas before generation; never execute generated code.
- Validate download/reload/retry behavior locally and hosted using the current v1.1 recovery rules.
- Generating sample data resolves missing data, not unsupported Data Studio/app behavior:
  moving GPS animation still goes through the same capability gate.

## Review status
No duplicate review or approval round requested. This document is an explanatory supplement for
the architect already reviewing the plans. It adds no implementation tasks and overrides no
contract, task split, storage decision or release deadline. The embedded request was checked as
valid JSON; no product code or live-generation test was run for this supplement.
