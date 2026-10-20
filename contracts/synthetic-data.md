# Contract: synthetic CSV generation
Version 1.1 (2026-10-20). Provider: backend. Consumers: frontend, release.
Change log: 1.1 (2026-10-20) durability uses the generation table plus immediate DB backups
instead of immutable manifests and startup reconciliation; HTTP shapes unchanged. 1.0 (2026-10-19)
initial planned contract.
Planned implementation: backend 12.1-12.5, frontend 11.1, release 2.5/2.6 (local) and 4.3 (hosted) acceptance.
Transport: api.md 1.4. Source.kind adds `synthetic`; existing Source keys stay unchanged.

## Purpose and flow
Reference screenshot, no CSV -> extract visual observations -> propose a sample-data schema ->
show schema/assumptions and editable row count/seed -> user chooses Generate sample data ->
Python generates CSV -> ordinary BigQuery intake/profiling -> interview/feasibility -> prototype
and real Data Studio report. No need to upload a CSV before reference extraction/schema proposal.
Manual schemas also work without a screenshot or model call.

Sample rows are explicitly invented, never represented as recovered original data. Extracted
labels/units can inform a proposal; unseen definitions and distributions are recorded assumptions.
Missing real data is resolvable through this path; unsupported chart behavior still blocks.
Generate is explicit opt-in, never triggered automatically by failed intake or missing data.

## Generator request
The reusable Python function is `generate_csv(spec, output_path) -> GenerationResult`.
CLI: `uv run python -m dss.data.synthetic --request schema.json --output sample.csv`.
Both are local and network-free; they neither call an LLM nor load BigQuery. CLI exits nonzero
with a field-specific error and no partial final CSV on failure; it refuses an existing output.

```text
GenerationSpec = { schema_version: 1, row_count: int, seed: int, columns: ColumnSpec[] }
ColumnSpec = { name: string, type: "integer"|"number"|"string"|"boolean"|"date",
               nullable_fraction: number, generator: Generator }
Generator = tagged union:
  {kind:"sequence", start:int, step:int, prefix:string}        # integer or string; prefix empty for integer
  {kind:"integer", min:int, max:int}                          # integer, inclusive
  {kind:"decimal", min:number, max:number, decimals:int}       # number, inclusive representable ticks
  {kind:"choice", values:(string|number|boolean)[]}            # scalar values of column's type
  {kind:"boolean", true_probability:number}                  # boolean
  {kind:"date", start:string, end:string}                    # date, ISO YYYY-MM-DD inclusive
  {kind:"product", fields:string[], decimals:int}             # number; 2 earlier numeric columns
  {kind:"lookup", field:string, mapping:object}               # categorical relation to earlier string choice/lookup
GenerationResult = {row_count:int, bytes:int, sha256:string, generator_version:string}
```

Bounds: 1-100,000 rows (UI default 1,000), 1-40 columns, <=1,000,000 cells; seed uint32
(UI default 42); request <=64 KiB. Names unique snake_case, <=64 chars; probabilities 0..1.
Integers and sequence results within +/-10^12; decimals 0..6 and finite bounds within +/-10^12;
products must fit those bounds. Dates 1900-01-01..2100-12-31; start<=end. Choice: 1-100 distinct
non-null typed values, strings <=120 chars. Prefix <=32 chars. Lookup keys exactly cover every
possible non-null value of the referenced earlier string category, with typed bounded outputs.
No dangling/forward dependencies or cycles. Product/lookup propagate null inputs; reject a
dependent nullable_fraction other than zero to keep its null semantics unambiguous.
Reject unknown fields/kinds, mismatched types, invalid numeric/date ranges, empty choices and
impossible dependencies before writing. No arbitrary Python, expressions, imports or eval.

Output: UTF-8 without BOM, header once, schema order, csv.writer quoting, LF newlines; exactly
row_count data records; null is empty, booleans true/false, dates ISO, decimal text fixed scale.
Use Decimal/integer ticks, not binary float arithmetic for products/money. Reject formula-like
string values beginning (after whitespace) with =,+,-,@, tab or CR; negative numeric values are
valid numeric cells. This is a synthetic value restriction, not rewriting real imported data.
Determinism: identical canonical spec + seed + generator_version produces identical bytes;
record the version and checksum. No wall-clock defaults or global RNG state. Stream rows;
CSV <=50 MiB, generation <=30 s (excluding model/intake/storage); fail rather than truncate.
Tests measure 100,000x10 on the supported dev machine and report time/peak memory (<=128 MiB
additional allocation). Use stdlib csv/random/decimal/datetime/hashlib, existing Pydantic.

## HTTP workflow and provenance
Auth, existing action lock and normal error shape apply. Writes allowed only at connect/interview,
with no active action and no existing sources. Otherwise `409 wrong_stage` or
`409 synthetic_requires_empty_build`: offer New dashboard, never replace/merge real sources.
This is a POC policy; the reusable local generator has no build-stage restrictions.

| Method and suffix under `/api/builds/{id}` | Request | Response |
|---|---|---|
| `POST /synthetic-data/proposal` | `{reference_set_id:string}` | `202 {run_id}`; requires current reference set, no data source required |
| `GET /synthetic-data/proposal` | none | `200 Proposal|null` |
| `POST /synthetic-data` | `{generation_key:string, proposal_id:string|null, spec:GenerationSpec}` | `202 {run_id}`; explicit generate action |
| `GET /synthetic-data` | none | `200 SyntheticDataset[]` (successful datasets) |
| `GET /synthetic-data/jobs` | none | `200 GenerationStatus[]`, latest 20 jobs, newest first |
| `GET /synthetic-data/jobs/{generation_key}` | none | `200 GenerationStatus` or 404; durable retry/reload recovery |
| `GET /synthetic-data/{source_id}/csv` | none | authenticated CSV attachment for this build/source, filename `synthetic-sample.csv` |

```text
GenerationStatus = {generation_key:string, run_id:string,
  state:"queued"|"generating"|"loading"|"succeeded"|"failed", source_id:string|null,
  retry_ready:boolean, error:{code:string,message:string}|null}
Proposal = {id:string, reference_set_id:string, spec:GenerationSpec, assumptions:string[]}
SyntheticDataset = {source_id:string, generation_key:string, synthetic:true, spec:GenerationSpec,
  assumptions:string[], generator_version:string, sha256:string, bytes:int, created_at:string}
```
Automatic proposal requires a recreate-mode reference; style-only observations do not describe
a dataset. Otherwise return `422 synthetic_schema_unavailable` and offer Recreate mode or manual
schema entry. Proposal is locally validated, max 20 assumptions of <=240 chars; not a factual reconstruction.
One worker schema-proposal call, <=12k counted input/6k output, no repair; use existing extracted
reference observations, not another image upload. No actual generated rows in model context.
The generator API works without a proposal (`proposal_id:null`); for a supplied proposal require
the current proposal and reference ID, else `409 synthetic_proposal_stale`. User may edit the
schema; keep original assumptions plus an "edited by user" note. Store the accepted exact spec.

generation_key: client-created opaque [A-Za-z0-9_-]{1,64}, reused for retry. Same key+same canonical
request returns original run_id, even after success; same key+different request ->
`409 synthetic_request_conflict`. Check replay before rejecting existing sources. A failed run
is shown as failed; explicit Retry uses a new key after cleanup, never silently succeeds.
Durability: the backend's generation table (key, request hash, run_id, source_id, table
identity, state, retry_ready, error) is the only job record; there are no manifest files.
Reserve key/hash/run_id/source_id/table identity in one transaction, then run an immediate DB
backup through the existing backup path and lock (conventions.md, Cloud deployment) before
acknowledging 202 or starting work. Registration commits Source, profile, provenance and
state=succeeded in one transaction, then runs another immediate backup before run.finished.
A failed immediate backup follows the existing rule: it logs a warning, never fails the request,
and the dirty flag lets the periodic backup retry. Where no separate backup exists (DSS_DB_PATH
inside DSS_DATA_DIR) the immediate backup is a no-op. At startup, before serving requests, every
queued/generating/loading row (no worker survives a restart) becomes failed with error code
`generation_interrupted`; clean only that job's own generated prefix and BigQuery table
(identities from its row), then set retry_ready=true. A crash between the registration commit
and its backup restores the reserved row, which recovers the same way; the lost registration
never reappears, so no second source. Duplicate requests cannot register two sources; persist
failure/cleanup readiness as well.

GET job status reads persisted state, never launches work. After replay, lost response, reload or
missed SSE completion the UI reads jobs/status; a failed job permits explicit retry only when
retry_ready=true (cleanup finished). Succeeded has source_id and no error; in-flight jobs never
permit retry. Poll active status every 2 seconds while mounted; stop when terminal/unmounted.

Run nodes: `synthetic_schema` and `synthetic_generate`; existing run.started/run.finished,
build.updated and docs.updated events, no new event shapes. Generate includes CSV creation,
durable storage, BigQuery load with explicit types from the accepted schema, profiling and source
registration. Use a typed synthetic loader that preserves header names and EVERY generated
record, bypassing real-upload prepare_csv empty-row filtering/renaming. Do not use autodetect for
synthetic columns (all-null/date/numeric-string cases). Verify loaded row count equals requested
count before registering, including files/rows with all values null; mismatch fails cleanly.
On success Source.kind=synthetic, name="Synthetic sample data". Failure registers no Source;
preserve earlier build state and provide retry information. Normal readiness/feasibility rechecks
after registration. Generated data can resolve needs_data; it cannot enable animation or a chart
that the engine cannot build.

Keep provenance keyed by source, and copy its reference/label through new versions. Store
`synthetic-data.md` in build docs with seed, row count, checksum, schema, version and assumptions.
UI source list, prototype and final dashboard must visibly say "Synthetic sample data". The
final dashboard label is a deterministic decoration in the existing background pipeline, required
while any participating source is synthetic; never removable through a model patch or image style.
No extra mutable Source keys; metadata is fetched through the synthetic-data endpoint.

## Storage
Local: `<DSS_DATA_DIR>/generated/<build_id>/<generation_key>/sample.csv` plus metadata.json;
server derives all paths, accepts no HTTP output path/bucket/gs:// URI. Keep runtime data ignored.
Local CLI output_path is caller-controlled, separate from the HTTP service's generated paths.
Hosted: same logical path under the existing `/data` GCS volume (conventions.md). Generate in
local temporary storage, close/hash/check byte budget, then copy CSV and metadata into a unique
generation prefix; write metadata last as the completion record. Never rely on a cross-file GCS
rename being atomic. Only registered successful records can be downloaded/used; validate checksum
on recovery. SQLite remains on its existing local disk/backup path.
Use the existing BigQuery client to load the completed file with explicit schema; no direct GCS
upload API, new bucket, signed public URL or additional storage dependency is needed in this POC.
The backend's configured state-bucket mount is the storage choice, not a browser setting.

## Acceptance oracle
- Schema+seed produces exact row count, types/ranges/relationships and stable bytes/checksum;
  different seeds change random values. Repeated runs do not depend on current date.
- All-null numeric columns and string IDs like "001" retain their declared BigQuery types;
  an entirely null dataset and mixed all-empty records retain the exact requested row count.
- Invalid/cyclic schemas, unknown generators, resource limits and existing CLI outputs reject;
  failures leave no usable partial dataset. Formula-like string values reject before generation.
- Screenshot only: proposal is available at connect with zero sources; edit count to 1,000,
  Generate -> CSV download -> synthetic Source -> interview -> recreation -> labeled real report.
- Replayed requests do not duplicate sources; changed-key payload conflicts are clear; wrong
  build/source download rejects; stale proposals reject; crash/upload/load failure is recoverable.
- Container replacement right after the 202 or after registration restores job/source identity
  from the immediate backup; an interrupted job reads failed with retry_ready once its own
  artifacts are cleaned; response loss, missed completion and failed-job reload show durable
  status/retry readiness, and repeated requests never create a second source.
- Hosted generated CSV is downloadable after restart through the existing persisted volume;
  neither source nor UI/report claims values were recovered from the screenshot.
- Synthetic input still refuses moving GPS animation and unsupported capabilities.
