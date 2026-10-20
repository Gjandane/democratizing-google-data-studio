"""Deterministic, network-free synthetic CSV generation (contracts/synthetic-data.md 1.1).

`generate_csv(spec, output_path)` validates a GenerationSpec completely, streams exactly
row_count records to a temporary file beside the output, and publishes it only when the whole
file was written within the byte and time budgets. Values come from per-column RNG streams
derived from (generator version, seed, column index, name): no global RNG state, no wall
clock, no model, no network. Run as `python -m dss.data.synthetic --request R --output O`.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from collections.abc import Mapping
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from random import Random
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError

GENERATOR_VERSION = "dss-synthetic/1"
MAX_ROWS = 100_000
MAX_COLUMNS = 40
MAX_CELLS = 1_000_000
MAX_REQUEST_BYTES = 64 * 1024
MAX_CSV_BYTES = 50 * 1024 * 1024
MAX_SECONDS = 30
LIMIT = 10**12
MAX_DECIMALS = 6
MAX_STRING = 120
MIN_DATE, MAX_DATE = date(1900, 1, 1), date(2100, 12, 31)
ALWAYS = 1 << 53  # probability thresholds compare against 53 random bits
NAME = re.compile(r"[a-z][a-z0-9_]*")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
NUMERIC = ("integer", "number")
ALLOWED_TYPES = {
    "sequence": ("integer", "string"), "integer": ("integer",), "decimal": ("number",),
    "boolean": ("boolean",), "date": ("date",), "product": ("number",),
}


class SyntheticError(ValueError):
    """A rejected request or a failed generation; `field` is the JSON path at fault."""

    def __init__(self, field, message):
        super().__init__(f"{field}: {message}")
        self.field, self.message = field, message


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, allow_inf_nan=False)


Scalar = Union[str, int, float, bool]
Bound = Union[int, float]


class SequenceGenerator(_Strict):
    kind: Literal["sequence"]
    start: int
    step: int
    prefix: str = Field(max_length=32)


class IntegerGenerator(_Strict):
    kind: Literal["integer"]
    min: int
    max: int


class DecimalGenerator(_Strict):
    kind: Literal["decimal"]
    min: Bound
    max: Bound
    decimals: int = Field(ge=0, le=MAX_DECIMALS)


class ChoiceGenerator(_Strict):
    kind: Literal["choice"]
    values: list[Scalar] = Field(min_length=1, max_length=100)


class BooleanGenerator(_Strict):
    kind: Literal["boolean"]
    true_probability: float = Field(ge=0, le=1)


class DateGenerator(_Strict):
    kind: Literal["date"]
    start: str
    end: str


class ProductGenerator(_Strict):
    kind: Literal["product"]
    fields: list[str] = Field(min_length=2, max_length=2)
    decimals: int = Field(ge=0, le=MAX_DECIMALS)


class LookupGenerator(_Strict):
    kind: Literal["lookup"]
    field: str
    mapping: dict[str, Scalar] = Field(min_length=1, max_length=100)


Generator = Annotated[
    Union[SequenceGenerator, IntegerGenerator, DecimalGenerator, ChoiceGenerator,
          BooleanGenerator, DateGenerator, ProductGenerator, LookupGenerator],
    Field(discriminator="kind"),
]


class ColumnSpec(_Strict):
    name: str = Field(min_length=1, max_length=64)
    type: Literal["integer", "number", "string", "boolean", "date"]
    nullable_fraction: float = Field(ge=0, le=1)
    generator: Generator


class GenerationSpec(_Strict):
    schema_version: int = Field(ge=1, le=1)
    row_count: int = Field(ge=1, le=MAX_ROWS)
    seed: int = Field(ge=0, le=2**32 - 1)
    columns: list[ColumnSpec] = Field(min_length=1, max_length=MAX_COLUMNS)


class GenerationResult(BaseModel):
    row_count: int
    bytes: int
    sha256: str
    generator_version: str


def canonical_json(spec):
    """Key-sorted compact JSON of a validated spec: the identity of a generation request."""
    return json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def parse_spec(request):
    """Validate a GenerationSpec given as JSON text/bytes, a mapping or a model; raise SyntheticError."""
    if isinstance(request, (bytes, str)):
        try:
            raw = request.encode("utf-8") if isinstance(request, str) else request
        except UnicodeEncodeError:
            raise SyntheticError("request", "must be valid Unicode text") from None
        _check_size(len(raw))
        data = _load_json(raw)
    elif isinstance(request, GenerationSpec):
        data = request.model_dump(mode="json")
        _check_size(len(canonical_json(request).encode("utf-8", "surrogatepass")))
    elif isinstance(request, Mapping):
        data = request
        try:
            # NaN/inf and lone surrogates are measured here and rejected per field below.
            size = len(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8", "surrogatepass"))
        except (TypeError, ValueError) as exc:
            raise SyntheticError("request", f"not JSON-serializable ({exc})") from None
        _check_size(size)
    else:
        raise SyntheticError("request", "must be a JSON object")
    try:
        spec = GenerationSpec.model_validate(data)
    except ValidationError as exc:
        errors = exc.errors(include_url=False)
        first = _path(errors[0]["loc"])
        detail = "; ".join(f"{_path(e['loc'])}: {e['msg']}" for e in errors[:5])
        raise SyntheticError(first, detail.split(": ", 1)[1] if len(errors) == 1 else detail) from None
    _compile(spec)
    return spec


def generate_csv(spec, output_path):
    """Write the spec's CSV to output_path (which must not exist); return its size and checksum."""
    spec = parse_spec(spec)
    plans = _compile(spec)
    out = Path(output_path)
    if os.path.lexists(out):
        raise SyntheticError("output", f"{out} already exists")
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{out.name}.", suffix=".partial", dir=out.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            sink = _Sink(handle)
            _write(csv.writer(sink, lineterminator="\n"), spec, plans)
        _publish(tmp, out)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return GenerationResult(row_count=spec.row_count, bytes=sink.bytes,
                            sha256=sink.hash.hexdigest(), generator_version=GENERATOR_VERSION)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m dss.data.synthetic",
                                     description="Generate a deterministic synthetic CSV from a GenerationSpec.")
    parser.add_argument("--request", required=True, help="GenerationSpec JSON file")
    parser.add_argument("--output", required=True, help="CSV path to create (must not exist)")
    args = parser.parse_args(argv)
    try:
        with open(args.request, "rb") as handle:
            raw = handle.read(MAX_REQUEST_BYTES + 1)
        result = generate_csv(raw, args.output)
    except SyntheticError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc.filename or ''}: {exc.strerror or exc}", file=sys.stderr)
        return 1
    print(json.dumps(result.model_dump()))
    return 0


# Validation and compilation ------------------------------------------------------------------

class _Plan:
    """One column ready to draw: its null threshold and a draw(row_index, raw_row) function."""

    __slots__ = ("null_threshold", "null_bits", "draw", "dependent", "bounds", "categories")

    def __init__(self, draw, dependent=False, bounds=None, categories=None):
        self.draw, self.dependent, self.bounds, self.categories = draw, dependent, bounds, categories
        self.null_threshold, self.null_bits = 0, None


def _compile(spec):
    plans, index = [], {}
    for i, column in enumerate(spec.columns):
        path = f"columns[{i}]"
        if not NAME.fullmatch(column.name):
            raise SyntheticError(f"{path}.name", "must be snake_case: a lowercase letter, then lowercase letters, digits or _")
        if column.name in index:
            raise SyntheticError(f"{path}.name", f"duplicate column name {column.name!r}")
        gen = column.generator
        allowed = ALLOWED_TYPES.get(gen.kind)
        if allowed and column.type not in allowed:
            raise SyntheticError(f"{path}.generator.kind",
                                 f"{gen.kind!r} requires type {' or '.join(allowed)}, not {column.type!r}")
        plan = _COMPILERS[gen.kind](spec, column, gen, f"{path}.generator", plans, index)
        if plan.dependent and column.nullable_fraction != 0:
            raise SyntheticError(f"{path}.nullable_fraction",
                                 f"must be 0 for {gen.kind!r}: nulls propagate from its inputs")
        plan.null_threshold = int(column.nullable_fraction * ALWAYS)
        if 0 < plan.null_threshold < ALWAYS:
            plan.null_bits = _rng(spec.seed, i, column.name, "null").getrandbits
        plans.append(plan)
        index[column.name] = i
    if spec.row_count * len(spec.columns) > MAX_CELLS:
        raise SyntheticError("row_count", f"row_count x columns must be <= {MAX_CELLS:,} cells")
    return plans


def _sequence(spec, column, gen, path, plans, index):
    start, step = gen.start, gen.step
    last = start + step * (spec.row_count - 1)
    if max(abs(start), abs(last)) > LIMIT:
        raise SyntheticError(path, f"sequence values must stay within +/-{LIMIT}")
    if column.type == "integer":
        if gen.prefix:
            raise SyntheticError(f"{path}.prefix", "must be empty for an integer sequence")
        return _Plan(lambda i, row: ((start + step * i, 0), str(start + step * i)),
                     bounds=(Decimal(min(start, last)), Decimal(max(start, last))))
    prefix = gen.prefix
    _check_text(prefix, f"{path}.prefix", allow_empty=True, formula=False)
    for value in (start, last):  # values are monotonic: the two ends decide the sign
        _check_text(prefix + str(value), f"{path}.prefix", allow_empty=False, length=False)

    def draw(i, row):
        text = prefix + str(start + step * i)
        return text, text
    return _Plan(draw)


def _integer(spec, column, gen, path, plans, index):
    low, high = gen.min, gen.max
    for name, value in (("min", low), ("max", high)):
        if abs(value) > LIMIT:
            raise SyntheticError(f"{path}.{name}", f"must be within +/-{LIMIT}")
    if low > high:
        raise SyntheticError(f"{path}.max", "must be >= min")
    below = _below(_rng(spec.seed, len(plans), column.name, "value"), high - low + 1)

    def draw(i, row):
        value = low + below()
        return (value, 0), str(value)
    return _Plan(draw, bounds=(Decimal(low), Decimal(high)))


def _decimal(spec, column, gen, path, plans, index):
    scale = gen.decimals
    for name, value in (("min", gen.min), ("max", gen.max)):
        if not math.isfinite(value) or abs(value) > LIMIT:
            raise SyntheticError(f"{path}.{name}", f"must be finite and within +/-{LIMIT}")
    low, high = _decimal_of(gen.min), _decimal_of(gen.max)
    if low > high:
        raise SyntheticError(f"{path}.max", "must be >= min")
    first = int((low.scaleb(scale)).to_integral_value(ROUND_CEILING))
    last = int((high.scaleb(scale)).to_integral_value(ROUND_FLOOR))
    if first > last:
        raise SyntheticError(f"{path}.decimals", f"no value with {scale} decimals lies between min and max")
    below = _below(_rng(spec.seed, len(plans), column.name, "value"), last - first + 1)

    def draw(i, row):
        ticks = first + below()
        return (ticks, scale), _fmt(ticks, scale)
    return _Plan(draw, bounds=(Decimal(first).scaleb(-scale), Decimal(last).scaleb(-scale)))


def _choice(spec, column, gen, path, plans, index):
    options, seen = [], set()
    for k, value in enumerate(gen.values):
        raw, text, key = _typed(column.type, value, f"{path}.values[{k}]")
        if key in seen:
            raise SyntheticError(f"{path}.values[{k}]", f"duplicate value {value!r}")
        seen.add(key)
        options.append((raw, text))
    below = _below(_rng(spec.seed, len(plans), column.name, "value"), len(options))
    return _Plan(lambda i, row: options[below()], bounds=_bounds(column.type, seen),
                 categories=frozenset(seen) if column.type == "string" else None)


def _boolean(spec, column, gen, path, plans, index):
    threshold = int(gen.true_probability * ALWAYS)
    bits = _rng(spec.seed, len(plans), column.name, "value").getrandbits
    true, false = (True, "true"), (False, "false")
    return _Plan(lambda i, row: true if bits(53) < threshold else false)


def _date(spec, column, gen, path, plans, index):
    start = _parse_date(gen.start, f"{path}.start").toordinal()
    end = _parse_date(gen.end, f"{path}.end").toordinal()
    if start > end:
        raise SyntheticError(f"{path}.end", "must be on or after start")
    below = _below(_rng(spec.seed, len(plans), column.name, "value"), end - start + 1)

    def draw(i, row):
        text = date.fromordinal(start + below()).isoformat()
        return text, text
    return _Plan(draw)


def _product(spec, column, gen, path, plans, index):
    if gen.fields[0] == gen.fields[1]:
        raise SyntheticError(f"{path}.fields", "must name two different columns")
    refs = [_reference(spec, name, f"{path}.fields[{k}]", index, len(plans)) for k, name in enumerate(gen.fields)]
    for k, ref in enumerate(refs):
        if spec.columns[ref].type not in NUMERIC:
            raise SyntheticError(f"{path}.fields[{k}]", f"{gen.fields[k]!r} is not an integer or number column")
    scale = gen.decimals
    (a_low, a_high), (b_low, b_high) = plans[refs[0]].bounds, plans[refs[1]].bounds
    quantum = Decimal(1).scaleb(-scale)
    with localcontext(prec=60):  # corners reach 10^24 before the bound check
        corners = [(x * y).quantize(quantum, ROUND_HALF_UP) for x in (a_low, a_high) for y in (b_low, b_high)]
    if max(abs(c) for c in corners) > LIMIT:
        raise SyntheticError(f"{path}.fields", f"product of these columns can exceed +/-{LIMIT}")
    a_ref, b_ref = refs

    def draw(i, row):
        a, b = row[a_ref], row[b_ref]
        if a is None or b is None:
            return None
        ticks, have = a[0] * b[0], a[1] + b[1]
        if have > scale:  # round half away from zero, in integer ticks
            factor = 10 ** (have - scale)
            whole, rest = divmod(abs(ticks), factor)
            whole += 2 * rest >= factor
            ticks = whole if ticks >= 0 else -whole
        elif have < scale:
            ticks *= 10 ** (scale - have)
        return (ticks, scale), _fmt(ticks, scale)
    return _Plan(draw, dependent=True, bounds=(min(corners), max(corners)))


def _lookup(spec, column, gen, path, plans, index):
    ref = _reference(spec, gen.field, f"{path}.field", index, len(plans))
    categories = plans[ref].categories
    if categories is None:
        raise SyntheticError(f"{path}.field",
                             f"{gen.field!r} must be an earlier string column with a choice or lookup generator")
    missing, extra = categories - gen.mapping.keys(), gen.mapping.keys() - categories
    if missing or extra:
        detail = "; ".join(part for part in (
            missing and f"missing {sorted(missing)[:5]}", extra and f"unknown {sorted(extra)[:5]}") if part)
        raise SyntheticError(f"{path}.mapping", f"keys must exactly cover the values of {gen.field!r}: {detail}")
    table, keys = {}, set()
    for source, value in gen.mapping.items():
        raw, text, key = _typed(column.type, value, f"{path}.mapping[{json.dumps(source, ensure_ascii=False)}]")
        table[source] = (raw, text)
        keys.add(key)

    def draw(i, row):
        source = row[ref]
        return None if source is None else table[source]
    return _Plan(draw, dependent=True, bounds=_bounds(column.type, keys),
                 categories=frozenset(keys) if column.type == "string" else None)


_COMPILERS = {
    "sequence": _sequence, "integer": _integer, "decimal": _decimal, "choice": _choice,
    "boolean": _boolean, "date": _date, "product": _product, "lookup": _lookup,
}


def _reference(spec, name, path, index, position):
    if name in index:
        return index[name]
    if any(c.name == name for c in spec.columns):
        raise SyntheticError(path, f"{name!r} must be an earlier column (no forward or self references)")
    raise SyntheticError(path, f"unknown column {name!r}")


def _typed(column_type, value, path):
    """Check one scalar against the column type; return (raw, csv text, distinctness key)."""
    if column_type == "string":
        if not isinstance(value, str):
            raise SyntheticError(path, "must be a string")
        _check_text(value, path)
        return value, value, value
    if column_type == "boolean":
        if not isinstance(value, bool):
            raise SyntheticError(path, "must be a boolean")
        return value, "true" if value else "false", value
    if column_type == "date":
        if not isinstance(value, str):
            raise SyntheticError(path, "must be an ISO date string")
        _parse_date(value, path)
        return value, value, value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (column_type == "integer" and not isinstance(value, int)):
        raise SyntheticError(path, f"must be {'an integer' if column_type == 'integer' else 'a number'}")
    if not math.isfinite(value) or abs(value) > LIMIT:
        raise SyntheticError(path, f"must be finite and within +/-{LIMIT}")
    number = _decimal_of(value)
    scale = max(0, -number.as_tuple().exponent)
    if scale > MAX_DECIMALS:
        raise SyntheticError(path, f"must have at most {MAX_DECIMALS} decimals")
    ticks = int(number.scaleb(scale))
    return (ticks, scale), _fmt(ticks, scale), number


def _bounds(column_type, keys):
    return (min(keys), max(keys)) if column_type in NUMERIC else None


def _check_text(value, path, allow_empty=False, formula=True, length=True):
    if not value and not allow_empty:
        raise SyntheticError(path, "must not be empty (an empty cell means null)")
    if length and len(value) > MAX_STRING:
        raise SyntheticError(path, f"must be at most {MAX_STRING} characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise SyntheticError(path, "must be valid Unicode text") from None
    if formula and value and (value[0] in "\t\r" or value.lstrip()[:1] in ("=", "+", "-", "@")):
        raise SyntheticError(path, f"formula-like value {value!r}: must not start with =, +, -, @, tab or CR")


def _parse_date(value, path):
    try:
        if not ISO_DATE.fullmatch(value):
            raise ValueError
        parsed = date.fromisoformat(value)
    except ValueError:
        raise SyntheticError(path, f"{value!r} is not an ISO YYYY-MM-DD date") from None
    if not MIN_DATE <= parsed <= MAX_DATE:
        raise SyntheticError(path, f"must be between {MIN_DATE} and {MAX_DATE}")
    return parsed


def _decimal_of(value):
    return Decimal(value) if isinstance(value, int) else Decimal(repr(value))


def _rng(seed, position, name, stream):
    material = f"{GENERATOR_VERSION}\0{seed}\0{position}\0{name}\0{stream}".encode()
    return Random(int.from_bytes(hashlib.sha256(material).digest(), "big"))


def _below(rng, n):
    """Uniform 0..n-1 by rejection sampling on getrandbits: fixed here, not by stdlib internals."""
    bits, getrandbits = (n - 1).bit_length(), rng.getrandbits
    if n == 1:
        return lambda: 0

    def draw():
        value = getrandbits(bits)
        while value >= n:
            value = getrandbits(bits)
        return value
    return draw


def _fmt(ticks, scale):
    if not scale:
        return str(ticks)
    whole, frac = divmod(abs(ticks), 10**scale)
    return f"{'-' if ticks < 0 else ''}{whole}.{frac:0{scale}d}"


# Output ---------------------------------------------------------------------------------------

class _Sink:
    """csv.writer target: UTF-8 encodes, hashes and counts every row, failing past the byte budget."""

    def __init__(self, handle):
        self.handle, self.bytes, self.hash = handle, 0, hashlib.sha256()

    def write(self, text):
        data = text.encode("utf-8")
        self.bytes += len(data)
        if self.bytes > MAX_CSV_BYTES:
            raise SyntheticError("row_count", f"generated CSV would exceed {MAX_CSV_BYTES // (1024 * 1024)} MiB; "
                                              "reduce row_count, columns or value lengths")
        self.hash.update(data)
        self.handle.write(data)


def _write(writer, spec, plans):
    writer.writerow([column.name for column in spec.columns])
    deadline = time.monotonic() + MAX_SECONDS
    width = len(plans)
    raw, text = [None] * width, [""] * width
    columns = list(enumerate(plans))
    for i in range(spec.row_count):
        if not i & 1023 and time.monotonic() > deadline:
            raise SyntheticError("row_count", f"generation exceeded {MAX_SECONDS} s")
        for j, plan in columns:
            threshold = plan.null_threshold
            if threshold and (threshold >= ALWAYS or plan.null_bits(53) < threshold):
                cell = None
            else:
                cell = plan.draw(i, raw)
            if cell is None:
                raw[j], text[j] = None, ""
            else:
                raw[j], text[j] = cell
        writer.writerow(text)


def _publish(tmp, out):
    """Move the finished file into place without ever replacing an existing output."""
    try:
        os.link(tmp, out)
    except FileExistsError:
        raise SyntheticError("output", f"{out} already exists") from None
    except OSError:  # filesystems without hard links
        if os.path.lexists(out):
            raise SyntheticError("output", f"{out} already exists") from None
        os.replace(tmp, out)
        return
    os.unlink(tmp)


def _check_size(size):
    if size > MAX_REQUEST_BYTES:
        raise SyntheticError("request", f"must be at most {MAX_REQUEST_BYTES // 1024} KiB")


def _load_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise SyntheticError(key, "duplicate JSON key")
            result[key] = value
        return result

    def constant(name):
        raise SyntheticError("request", f"{name} is not valid JSON")
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs, parse_constant=constant)
    except SyntheticError:
        raise
    except (ValueError, RecursionError) as exc:  # JSONDecodeError, UnicodeDecodeError, huge ints, deep nesting
        raise SyntheticError("request", f"invalid JSON ({exc})") from None


def _path(loc):
    parts = []
    for k, item in enumerate(loc):
        if isinstance(item, int):
            parts.append(f"[{item}]")
        elif k and loc[k - 1] == "generator" and item in _COMPILERS:
            continue  # discriminated-union tag, not a field
        else:
            parts.append(f".{item}" if parts else str(item))
    return "".join(parts) or "request"


if __name__ == "__main__":
    sys.exit(main())
