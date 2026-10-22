<!-- essentials-of: docs/architecture.md sha256:92d76fdd968a (regenerate this page when architecture.md changes, then run stamp) -->
# Architecture essentials: engine
One page, read at the start of every build session. A summary of docs/architecture.md, which
wins if the two disagree.

## Stack
- Python 3.12 + uv; Playwright for Python attached over CDP (`connect_over_cdp`) to the installed
  Google Chrome started with `--user-data-dir=<DSS_CHROME_PROFILE> --remote-debugging-port=<DSS_CDP_PORT> --app=<url>`;
  argparse CLI; pydantic + jsonschema for recipes; pyyaml for selector files; pytest.

## Folder map
```text
src/dsengine/            cli, recipe, events, linking, chrome, selectors, executor, printer, ops/
knowledge/datastudio-ui/ OKF bundle: index.md, log.md, one selector concept per UI area
spikes/                  throwaway spike scripts
tests/                   offline tests (fake driver); tests/live/ marked `live`
```

## Conventions
- Events go to stdout only (one JSON per line, `flush=True`); human logs go to stderr.
- `.env` is read from `../.env` (python-dotenv), real env vars win. Names: ../contracts/conventions.md.
- Selectors are looked up by key from `knowledge/datastudio-ui/*.md` frontmatter `selectors:`;
  code never hard-codes a locator string. A selector change adds a line to that bundle's `log.md`.
- Every op module exposes `run(page, op, ctx) -> OpResult` and a `verify`; the executor owns retry,
  screenshots, events and status (docs/architecture.md#Recipe executor).
- Screenshots: `<recipe dir>/screens/<op_id>_failed.png` unless `--screens` is given.
- Live tests read `DSS_TEST_TABLE` (default `bigquery-public-data.thelook_ecommerce.order_items`).
- Editor mechanics: docs/architecture.md#Live editor conventions. Use 1920 x 1200 at 100% zoom,
  mouse geometry with ±4 px readback, reuse creations on retry and record their actual page.
  Retain pending background uploads and refresh owning-page indices after reordering. Registry
  walks filter dictionary entries because state also holds the source-field list.
  Append pages from the last page; exclude images from chart enumeration.
- Canvases can be taller than the viewport: bring each target region into view before mouse
  geometry and read boxes back in canvas coordinates; a background ends behind all, deselected.
- Start the owned browser before checking sign-in; `check` stays read-only. Retry keyboard/mouse
  cleanup has no timeout keyword: check its budget first and bound canvas lookup by time left.
- Cache source fields at editor readiness, before image/control selection clears the Data panel.
  Poll exact title-font readback and saved image loading within their existing budgets.
- Data-access review dialogs (create, first save): detect the dialog by exact name; the risk
  checkbox is optional (tick only if present); click the dialog's Acknowledge, never Close.
  Controls may render after the dialog: poll the checkbox/button every 250 ms until acknowledgement
  is enabled, bounded by the existing budget. A disabled-button timeout leaves no retry budget.
  Same for spike.
- Schema extension fields are op-specific: read chart-only arguments only on `add_chart`.
  Wait for rendered charts/loaded images; preserve text blank lines through block/BR readback.
- Screencast is opt-in JPEG quality 60 at most once per 500 ms; acknowledge dropped CDP frames
  and stop/remove/detach before closing the owned page.

## Never do
- Never call an LLM or send screenshots anywhere.
- Never type passwords or automate Google sign-in; never touch tabs the engine didn't open.
- Never edit ../contracts/; a needed change is a blocked task.
- Never sleep more than 1 s at a time; wait on conditions.

## Contracts
| Contract | Version | Role | Conformance check |
|---|---|---|---|
| ../contracts/recipe.md (+ recipe.schema.json, fixtures/) | 1.1 | consumes recipes; provides events | `uv run pytest tests/test_contract.py` |
| ../contracts/conventions.md | 1.2 | consumes | manual: env names, ports and paths match (1.1 and 1.2 add nothing the engine reads; the engine stays local) |

## Dependencies
| Package | Registry | Version | Why | Verified |
| --- | --- | --- | --- | --- |
| playwright | pypi | >=1.48 | browser control over CDP | 2026-10-18 (1.64.0) |
| python-dotenv | pypi | >=1.0 | read ../.env | 2026-10-18 (1.2.4) |
| pydantic | pypi | >=2.8 | typed recipe ops | 2026-10-18 (2.14.1) |
| jsonschema | pypi | >=4.23 | validate against the contract schema | 2026-10-18 (4.26.0) |
| pyyaml | pypi | >=6.0 | selector frontmatter | 2026-10-18 (6.0.3) |
| pytest | pypi | >=8.0 | tests | 2026-10-18 (9.1.1) |
| uv_build | pypi | >=0.9.7,<0.10 | build backend for the installed dsengine CLI (task 1.1, approved by user) | 2026-10-18 (0.13.1) |
