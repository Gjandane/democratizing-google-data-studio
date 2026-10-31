"""Share data (api.md 3.4/3.5, tasks 29.4, 30.1): one run's view rows as one CSV on the mounted share bucket.

Rows go only to `<DSS_SHARE_DIR>/<32 hex>/data.csv`: never to logs, traces, events or prompts.
"""
import csv
from datetime import date, datetime, timezone
import io
import json
import logging
import os
from pathlib import Path
import secrets
import shutil

from dss.data.bigquery import quoted, table_uri
from dss.data.profile import NUMBERS
from dss.harness.guardrails import RunError
from dss.recipe.compiler import share_header

logger = logging.getLogger(__name__)
MAX_ROWS = 1_000_000
MAX_BYTES = 100_000_000  # 100 MB, header included
RECORDS = "share"  # version subfolder of per-run records; no route serves it


class TooLarge(Exception):
    pass


def cell(value) -> str:
    """DATE `YYYY-MM-DD`; DATETIME/TIMESTAMP `YYYY-MM-DD HH:MM:SS` in UTC; NULL empty;
    booleans `true`/`false`; numbers and the rest via str()."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        if value.tzinfo is not None:  # TIMESTAMP; a naive DATETIME has no zone to convert
            value = value.astimezone(timezone.utc)
        # Not strftime: %Y drops the zero padding of years before 1000 on some platforms.
        return (f"{value.year:04d}-{value.month:02d}-{value.day:02d} "
                f"{value.hour:02d}:{value.minute:02d}:{value.second:02d}")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def summed(recipe: str, fields) -> set[str]:
    """Sum-only numeric columns (api.md 3.5): NULL is written `0` so Data Studio types them Number.

    A numeric, non-repeated column qualifies when the compiled ops name it in at least one
    `metrics` entry with `agg: sum` and otherwise only in sorts; any other reference (another
    agg, a dimension, breakdown, date dimension, control field, or any string in `options`)
    keeps NULL empty, so every sum is unchanged and nothing else is.
    """
    numeric = {field.name for field in fields if field.field_type in NUMBERS and field.mode != "REPEATED"}
    sums, other = set(), set()
    for line in recipe.split("\n")[1:]:  # the header names the source, never a column
        if not line.strip():
            continue
        op = json.loads(line)
        if op.get("op") == "add_chart":
            for metric in op.get("metrics") or []:
                (sums if metric.get("agg") == "sum" else other).add(metric.get("field"))
            other.update(op.get("dimensions") or [])
            other.update({op.get("date_dimension"), op.get("breakdown")})
            other.update(strings(op.get("options")))
        elif op.get("op") == "add_control":
            other.add(op.get("field"))
    return numeric & sums - other


def strings(value):
    """Every string key and value in an options object: a possible field reference."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def query(bq, table):
    """`SELECT * FROM <view>` through the existing client: schema fields and a row iterator."""
    result = bq.client.query(f"SELECT * FROM {quoted(table_uri(table))}",
                             location=bq.config.bq_location, timeout=30).result(timeout=300)
    if (getattr(result, "total_rows", None) or 0) > MAX_ROWS:  # known up front: nothing is written
        raise TooLarge
    return list(result.schema), result


def write(target: Path, names, rows, zero=frozenset()):
    """Stream rows to target/data.csv.tmp, renamed to data.csv when complete; counts rows and
    bytes while writing and removes the folder on any failure. Columns in `zero` write NULL as
    `0`. Returns (rows, bytes)."""
    target.mkdir()  # the share dir is the mount: never created here
    temporary, count, size = target / "data.csv.tmp", 0, 0
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    zeros = {index for index, name in enumerate(names) if name in zero}
    try:
        with open(temporary, "wb") as handle:
            writer.writerow(names)
            for row in rows:
                count += 1
                if count > MAX_ROWS:
                    raise TooLarge
                values = row.values() if hasattr(row, "values") else row
                writer.writerow([cell(value) if value is not None or index not in zeros else "0"
                                 for index, value in enumerate(values)])
                if buffer.tell() >= 65536:
                    size = flush(buffer, handle, size)
            size = flush(buffer, handle, size)
        os.replace(temporary, target / "data.csv")
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return count, size


def flush(buffer, handle, size):
    data = buffer.getvalue().encode("utf-8")
    buffer.seek(0)
    buffer.truncate()
    size += len(data)
    if size > MAX_BYTES:
        raise TooLarge
    handle.write(data)
    return size


def export(factory, config, table, recipe, folder: Path, run_id, share_dir: Path, bucket):
    """Export the view for one run and record it with the version; blocking (run it in a thread).

    `recipe` is the version's compiled text, the one the job ships: the shared header is checked
    before BigQuery is touched, and its ops decide the sum-only columns. Returns the record {folder, path, rows, bytes}; errors leave no file and no record.
    """
    name = secrets.token_hex(16)
    path = f"{bucket}/{name}/data.csv"
    target = share_dir / name
    try:
        share_header(recipe, path)
        fields, rows = query(factory(config), table)
        count, size = write(target, [field.name for field in fields], rows, summed(recipe, fields))  # removes its own folder on failure
        record = dict(folder=name, path=path, rows=count, bytes=size)
        try:
            records = folder / RECORDS
            records.mkdir(exist_ok=True)
            temporary = records / f"{run_id}.json.tmp"
            temporary.write_text(json.dumps(record), encoding="utf-8")
            temporary.replace(records / f"{run_id}.json")
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            raise
        return record
    except TooLarge:
        raise RunError("share_too_large", "The data is over 1,000,000 rows or 100 MB", 422) from None
    except Exception as error:
        logger.warning("Share data export failed (%s)", type(error).__name__)  # never the rows
        raise RunError("share_export_failed", "The data could not be shared", 503) from None


def discard(folder: Path, run_id, share_dir: Path):
    """Remove a run's export and its record (the job it was made for was never issued)."""
    record = folder / RECORDS / f"{run_id}.json"
    try:
        name = json.loads(record.read_text(encoding="utf-8"))["folder"]
    except (OSError, ValueError, KeyError, TypeError):
        return
    shutil.rmtree(share_dir / name, ignore_errors=True)
    record.unlink(missing_ok=True)


def recorded(folder: Path, run_id):
    """The run's shared CSV path for its recipe header, or None (no export: BigQuery header)."""
    record = folder / RECORDS / f"{run_id}.json"
    if not record.is_file():
        return None
    return json.loads(record.read_text(encoding="utf-8"))["path"]
