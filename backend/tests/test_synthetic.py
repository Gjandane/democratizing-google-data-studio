"""Deterministic synthetic CSV generator and CLI (contracts/synthetic-data.md, Generator request)."""
import ast
import copy
import csv
import hashlib
import io
import json
import random
import subprocess
import sys
import time
import tracemalloc
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from dss.data import synthetic
from dss.data.synthetic import GENERATOR_VERSION, GenerationSpec, SyntheticError, generate_csv, parse_spec

HERE = Path(__file__).resolve().parent
SPEC_FILE = HERE / "data/synthetic-spec.json"
FIXTURES = HERE.parents[1] / "contracts/fixtures/synthetic-data"
SPEC = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
HEADER = ["order_id", "line_no", "store_code", "order_date", "region", "country", "region_rank",
          "quantity", "unit_price", "revenue", "discount", "priority", "returned", "channel"]
# Pinned output of tests/data/synthetic-spec.json under generator version dss-synthetic/1.
# A change here changes generated datasets: bump GENERATOR_VERSION instead of editing it.
GOLDEN_SHA256 = "b70c89f0289cc8bec4f373d90b51b096bb6a67488525030008a3b707af37f8b1"
GOLDEN_BYTES = 1529
GOLDEN_ROWS = [
    "ORD-1,10,001,2025-05-14,,,,8,35.07,280.56,-4.6,1,false,",
    'ORD-5,50,001,2025-08-29,"South, ""Central""",Chile,3,5,68.79,343.95,-4.9,1,false,',
    "ORD-20,200,001,2025-05-12,West,Spain,2,3,21.86,65.58,-2.3,1,false,",
]


def col(name, type_, generator, nullable=0):
    return {"name": name, "type": type_, "nullable_fraction": nullable, "generator": generator}


def spec_with(*columns, rows=50, seed=7):
    return {"schema_version": 1, "row_count": rows, "seed": seed, "columns": list(columns)}


def rows_of(path):
    data = path.read_bytes()
    return list(csv.reader(io.StringIO(data.decode("utf-8"), newline="")))


def run_cli(*args):
    return subprocess.run([sys.executable, "-m", "dss.data.synthetic", *args],
                          capture_output=True, text=True, timeout=120)


# CLI ------------------------------------------------------------------------------------------

def test_cli_generates_expected_header_rows_and_checksum(tmp_path):
    out = tmp_path / "new" / "sample.csv"
    result = run_cli("--request", str(SPEC_FILE), "--output", str(out))
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    data = out.read_bytes()
    assert summary == {"row_count": 20, "bytes": GOLDEN_BYTES, "sha256": GOLDEN_SHA256,
                       "generator_version": GENERATOR_VERSION}
    assert hashlib.sha256(data).hexdigest() == GOLDEN_SHA256 and len(data) == GOLDEN_BYTES
    assert not data.startswith(b"\xef\xbb\xbf") and b"\r" not in data and data.endswith(b"\n")
    lines = data.decode("utf-8").split("\n")[:-1]
    assert lines[0] == ",".join(HEADER) and len(lines) == 21
    assert [lines[1], lines[5], lines[20]] == GOLDEN_ROWS
    assert sorted(p.name for p in out.parent.iterdir()) == ["sample.csv"]


def test_cli_refuses_existing_output(tmp_path):
    out = tmp_path / "sample.csv"
    out.write_text("keep", encoding="utf-8")
    result = run_cli("--request", str(SPEC_FILE), "--output", str(out))
    assert result.returncode != 0 and "output" in result.stderr and "already exists" in result.stderr
    assert out.read_text(encoding="utf-8") == "keep"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["sample.csv"]


def test_cli_invalid_schema_fails_with_field_and_no_file(tmp_path):
    bad = copy.deepcopy(SPEC)
    bad["columns"][7]["generator"]["max"] = 0
    request = tmp_path / "request.json"
    request.write_text(json.dumps(bad), encoding="utf-8")
    out = tmp_path / "out" / "sample.csv"
    result = run_cli("--request", str(request), "--output", str(out))
    assert result.returncode != 0
    assert "columns[7].generator.max" in result.stderr and "Traceback" not in result.stderr
    assert not out.exists() and not out.parent.exists()


def test_cli_rejects_oversized_and_invalid_json(tmp_path):
    out = tmp_path / "sample.csv"
    big = tmp_path / "big.json"
    big.write_text(json.dumps(SPEC) + " " * synthetic.MAX_REQUEST_BYTES, encoding="utf-8")
    broken = tmp_path / "broken.json"
    broken.write_text('{"schema_version": 1,', encoding="utf-8")
    nested = tmp_path / "nested.json"
    nested.write_text("[" * 5000, encoding="utf-8")
    for request in (big, broken, nested, tmp_path / "missing.json"):
        result = run_cli("--request", str(request), "--output", str(out))
        assert result.returncode != 0 and result.stderr.startswith("error:"), result.stderr
    assert not out.exists()


# Generator kinds and relationships ------------------------------------------------------------

def test_every_kind_and_relationship(tmp_path):
    spec = copy.deepcopy(SPEC)
    spec["row_count"] = 3000
    out = tmp_path / "sample.csv"
    result = generate_csv(spec, out)
    rows = rows_of(out)
    assert rows[0] == HEADER and len(rows) == 3001 and result.row_count == 3000
    records = [dict(zip(HEADER, r)) for r in rows[1:]]
    mapping = spec["columns"][5]["generator"]["mapping"]
    rank = spec["columns"][6]["generator"]["mapping"]
    nulls = {name: sum(1 for r in records if r[name] == "") for name in HEADER}
    for i, r in enumerate(records):
        assert r["order_id"] == f"ORD-{i + 1}" and r["line_no"] == str(10 + 10 * i)
        assert r["store_code"] in {"001", "002", "010"}
        if r["order_date"]:
            assert date(2025, 1, 1) <= date.fromisoformat(r["order_date"]) <= date(2025, 12, 31)
        if r["region"]:
            assert r["country"] == mapping[r["region"]] and r["region_rank"] == str(rank[r["region"]])
        else:  # lookups propagate null inputs
            assert r["country"] == "" and r["region_rank"] == ""
        if r["quantity"]:
            q = int(r["quantity"])
            assert 1 <= q <= 8
            expected = (Decimal(q) * Decimal(r["unit_price"])).quantize(Decimal("0.01"), ROUND_HALF_UP)
            assert r["revenue"] == f"{expected:.2f}"
        else:  # products propagate null inputs
            assert r["revenue"] == ""
        price = r["unit_price"]
        assert len(price.split(".")[1]) == 2 and Decimal("10") <= Decimal(price) <= Decimal("100")
        discount = Decimal(r["discount"])
        assert len(r["discount"].split(".")[1]) == 1 and Decimal("-5") <= discount <= 0
        assert r["priority"] in {"1", "2.5", "4"}
        assert r["returned"] in {"true", "false"}
        assert r["channel"] in {"web", "store", ""}
    for name in ("order_id", "line_no", "store_code", "unit_price", "discount", "priority", "returned"):
        assert nulls[name] == 0
    assert 150 <= nulls["order_date"] <= 450 and 1200 <= nulls["channel"] <= 1800
    assert 450 <= nulls["quantity"] <= 750 and nulls["revenue"] == nulls["quantity"]
    assert nulls["country"] == nulls["region"] > 0
    assert 600 <= sum(r["returned"] == "true" for r in records) <= 900
    assert {r["discount"] for r in records} >= {"-5.0", "0.0"}  # inclusive bounds
    assert {r["quantity"] for r in records} == {"", *map(str, range(1, 9))}
    assert {"2025-01-01", "2025-12-31"} <= {r["order_date"] for r in records}
    assert min(Decimal(r["unit_price"]) for r in records) < 11 and max(Decimal(r["unit_price"]) for r in records) > 99


def test_product_propagates_either_null_input_and_hits_range_ends(tmp_path):
    out = tmp_path / "sample.csv"
    generate_csv(spec_with(
        col("a", "integer", {"kind": "integer", "min": 2, "max": 4}),
        col("b", "number", {"kind": "choice", "values": [0.5, 1.25]}, 0.5),
        col("p", "number", {"kind": "product", "fields": ["a", "b"], "decimals": 1}),
        col("d", "date", {"kind": "date", "start": "2024-02-28", "end": "2024-03-01"}),
        rows=400), out)
    rows = rows_of(out)[1:]
    for a, b, p, _ in rows:  # the second operand is the nullable one here
        expected = "" if not b else f"{(int(a) * Decimal(b)).quantize(Decimal('0.1'), ROUND_HALF_UP):.1f}"
        assert p == expected
    assert {r[0] for r in rows} == {"2", "3", "4"} and "" in {r[1] for r in rows}
    assert {r[3] for r in rows} == {"2024-02-28", "2024-02-29", "2024-03-01"}
    assert "3.8" in {r[2] for r in rows}  # 3 x 1.25 = 3.75 rounds half up


def test_explicit_types_and_all_null_columns(tmp_path):
    spec = spec_with(
        col("id_text", "string", {"kind": "choice", "values": ["001", "0002"]}),
        col("empty_int", "integer", {"kind": "integer", "min": 1, "max": 9}, nullable=1),
        col("whole", "number", {"kind": "decimal", "min": 1.5, "max": 3.5, "decimals": 0}),
        col("tiny", "number", {"kind": "decimal", "min": 0.000001, "max": 0.000002, "decimals": 6}),
        col("flag", "boolean", {"kind": "choice", "values": [True]}),
        col("day", "date", {"kind": "choice", "values": ["1900-01-01", "2100-12-31"]}),
        col("score", "integer", {"kind": "choice", "values": [-3, 0]}),
        col("down", "integer", {"kind": "sequence", "start": 5, "step": -2, "prefix": ""}),
        rows=40)
    out = tmp_path / "sample.csv"
    generate_csv(spec, out)
    rows = rows_of(out)[1:]
    assert len(rows) == 40
    assert {r[0] for r in rows} == {"001", "0002"} and {r[1] for r in rows} == {""}
    assert {r[2] for r in rows} <= {"2", "3"} and {r[3] for r in rows} <= {"0.000001", "0.000002"}
    assert {r[4] for r in rows} == {"true"} and {r[5] for r in rows} <= {"1900-01-01", "2100-12-31"}
    assert {r[6] for r in rows} <= {"-3", "0"} and rows[-1][7] == str(5 - 2 * 39)


def test_entirely_null_dataset_keeps_exact_row_count(tmp_path):
    single = spec_with(col("only", "number", {"kind": "decimal", "min": 0, "max": 1, "decimals": 2}, 1), rows=25)
    double = spec_with(col("a", "string", {"kind": "choice", "values": ["x"]}, 1),
                       col("b", "date", {"kind": "date", "start": "2024-01-01", "end": "2024-01-02"}, 1), rows=25)
    for spec, cells in ((single, [""]), (double, ["", ""])):
        out = tmp_path / f"{len(cells)}.csv"
        generate_csv(spec, out)
        rows = rows_of(out)
        assert len(rows) == 26 and all(r == cells for r in rows[1:])
        assert out.read_bytes().count(b"\n") == 26


def test_csv_quoting_round_trips(tmp_path):
    values = ["comma, inside", 'quote "here"', "line\nbreak", "carriage\rreturn", "semi;colon", "ünïcode ✓"]
    out = tmp_path / "sample.csv"
    generate_csv(spec_with(col("text", "string", {"kind": "choice", "values": values}), rows=300), out)
    data = out.read_bytes().decode("utf-8")
    assert {r[0] for r in rows_of(out)[1:]} == set(values)
    assert '"quote ""here"""' in data and '"comma, inside"' in data and '"line\nbreak"' in data


def test_stable_bytes_and_seed_variation(tmp_path):
    first, again, other = tmp_path / "a.csv", tmp_path / "b.csv", tmp_path / "c.csv"
    random.seed(1)
    r1 = generate_csv(SPEC, first)
    random.seed(999)  # global RNG state never leaks into the output
    r2 = generate_csv(json.dumps(SPEC), again)
    r3 = generate_csv({**SPEC, "seed": 43}, other)
    assert first.read_bytes() == again.read_bytes() and r1 == r2
    assert r1.sha256 == hashlib.sha256(first.read_bytes()).hexdigest() == GOLDEN_SHA256
    assert r1.bytes == first.stat().st_size and r1.generator_version == GENERATOR_VERSION
    assert r3.sha256 != r1.sha256
    base, changed = rows_of(first), rows_of(other)
    assert [r[0] for r in base] == [r[0] for r in changed]  # sequences are not random
    assert [r[8] for r in base] != [r[8] for r in changed]  # random values change with the seed


def test_canonical_spec_is_order_independent():
    shuffled = json.loads(json.dumps(SPEC), object_pairs_hook=lambda pairs: dict(reversed(pairs)))
    assert synthetic.canonical_json(parse_spec(shuffled)) == synthetic.canonical_json(parse_spec(SPEC))


def test_contract_fixture_specs_generate(tmp_path):
    for name in ("request.json", "proposal.json"):
        spec = json.loads((FIXTURES / name).read_text(encoding="utf-8"))["spec"]
        out = tmp_path / name.replace(".json", ".csv")
        result = generate_csv(spec, out)
        rows = rows_of(out)
        assert result.row_count == spec["row_count"] == len(rows) - 1
        assert rows[0] == [c["name"] for c in spec["columns"]] == ["region", "quantity", "unit_price", "revenue"]
        for region, quantity, price, revenue in rows[1:]:
            assert region in {"East", "West"} and 1 <= int(quantity) <= 8
            assert Decimal(revenue) == (int(quantity) * Decimal(price)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        assert isinstance(parse_spec(spec), GenerationSpec)


# Rejection ------------------------------------------------------------------------------------

def sales(**overrides):
    spec = copy.deepcopy(json.loads((FIXTURES / "request.json").read_text(encoding="utf-8"))["spec"])
    spec.update(overrides)
    return spec


def mutate(path, value):
    spec = copy.deepcopy(SPEC)
    target = spec
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return spec


def gen(i, **fields):
    spec = copy.deepcopy(SPEC)
    spec["columns"][i]["generator"].update(fields)
    return spec


def single(type_, generator, nullable=0, rows=10):
    return spec_with(col("value", type_, generator, nullable), rows=rows)


def big_product(decimals, top=10**12):
    return sales(columns=[col("a", "integer", {"kind": "integer", "min": 0, "max": top}),
                          col("b", "number", {"kind": "decimal", "min": 0, "max": top, "decimals": 0}),
                          col("c", "number", {"kind": "product", "fields": ["a", "b"], "decimals": decimals})])


FORMULAS = ["=SUM(A1)", " +1", "-x", "@cmd", "\tlead", "\rlead", "  =x"]
INVALID = [
    ({**SPEC, "extra": 1}, "extra"),
    (mutate(["columns", 0, "colour"], "red"), "columns[0].colour"),
    (gen(7, kind="random"), "columns[7].generator"),
    (gen(7, step=1), "columns[7].generator.step"),
    ({**SPEC, "schema_version": 2}, "schema_version"),
    ({**SPEC, "schema_version": True}, "schema_version"),
    ({**SPEC, "row_count": 0}, "row_count"),
    ({**SPEC, "row_count": 100_001}, "row_count"),
    ({**SPEC, "row_count": 20.0}, "row_count"),
    ({**SPEC, "row_count": True}, "row_count"),
    ({**SPEC, "seed": -1}, "seed"),
    ({**SPEC, "seed": 2**32}, "seed"),
    ({**SPEC, "columns": []}, "columns"),
    ({**SPEC, "columns": [col(f"c{i}", "boolean", {"kind": "boolean", "true_probability": 0.5}) for i in range(41)]}, "columns"),
    ({**SPEC, "row_count": 100_000, "columns": [col(f"c{i}", "boolean", {"kind": "boolean", "true_probability": 0.5}) for i in range(11)]}, "row_count"),
    (mutate(["columns", 0, "name"], "Order ID"), "columns[0].name"),
    (mutate(["columns", 0, "name"], "1st"), "columns[0].name"),
    (mutate(["columns", 0, "name"], "a" * 65), "columns[0].name"),
    (mutate(["columns", 1, "name"], "order_id"), "columns[1].name"),
    (mutate(["columns", 0, "type"], "text"), "columns[0].type"),
    (mutate(["columns", 3, "nullable_fraction"], 1.5), "columns[3].nullable_fraction"),
    (mutate(["columns", 3, "nullable_fraction"], -0.1), "columns[3].nullable_fraction"),
    (gen(7, min=9), "columns[7].generator.max"),
    (gen(7, max=10**12 + 1), "columns[7].generator.max"),
    (gen(7, min="1"), "columns[7].generator.min"),
    (gen(8, decimals=7), "columns[8].generator.decimals"),
    (gen(8, min=0.001, max=0.002, decimals=2), "columns[8].generator.decimals"),
    (gen(8, min=101), "columns[8].generator.max"),
    (gen(8, max=10.0**13), "columns[8].generator.max"),
    (gen(8, max=float("inf")), "columns[8].generator.max"),
    (gen(2, values=[]), "columns[2].generator.values"),
    (gen(2, values=["a", "a"]), "columns[2].generator.values[1]"),
    (gen(2, values=["a", 1]), "columns[2].generator.values[1]"),
    (gen(2, values=[""]), "columns[2].generator.values[0]"),
    (gen(2, values=["x" * 121]), "columns[2].generator.values[0]"),
    (gen(2, values=[f"v{i}" for i in range(101)]), "columns[2].generator.values"),
    (gen(2, values=["\ud800"]), "columns[2].generator.values[0]"),
    (gen(11, values=[1, 1.0]), "columns[11].generator.values[1]"),
    (gen(11, values=[True]), "columns[11].generator.values[0]"),
    (gen(11, values=[0.1234567]), "columns[11].generator.values[0]"),
    (gen(6, mapping={"East": 1, "West": 2.5, 'South, "Central"': 3}), "columns[6].generator.mapping"),
    (single("boolean", {"kind": "choice", "values": [True, False, True]}), "columns[0].generator.values[2]"),
    (single("date", {"kind": "choice", "values": ["2024/01/01"]}), "columns[0].generator.values[0]"),
    (gen(12, true_probability=1.01), "columns[12].generator.true_probability"),
    (mutate(["columns", 8, "type"], "integer"), "columns[8].generator.kind"),
    (mutate(["columns", 12, "type"], "string"), "columns[12].generator.kind"),
    (mutate(["columns", 3, "type"], "string"), "columns[3].generator.kind"),
    (mutate(["columns", 9, "type"], "integer"), "columns[9].generator.kind"),
    (gen(1, prefix="L"), "columns[1].generator.prefix"),
    (gen(0, prefix="x" * 33), "columns[0].generator.prefix"),
    (gen(1, start=10**12, step=1), "columns[1].generator"),
    (gen(0, prefix="", start=-1), "columns[0].generator.prefix"),
    (gen(0, prefix=" ", start=5, step=-1), "columns[0].generator.prefix"),
    (gen(3, start="2025-1-01"), "columns[3].generator.start"),
    (gen(3, start="20250101"), "columns[3].generator.start"),
    (gen(3, start="2025-02-30"), "columns[3].generator.start"),
    (gen(3, start="1899-12-31"), "columns[3].generator.start"),
    (gen(3, end="2101-01-01"), "columns[3].generator.end"),
    (gen(3, start="2025-12-31", end="2025-01-01"), "columns[3].generator.end"),
    (gen(9, fields=["quantity"]), "columns[9].generator.fields"),
    (gen(9, fields=["quantity", "quantity"]), "columns[9].generator.fields"),
    (gen(9, fields=["quantity", "missing"]), "columns[9].generator.fields[1]"),
    (gen(9, fields=["quantity", "discount"]), "columns[9].generator.fields[1]"),
    (gen(9, fields=["quantity", "region"]), "columns[9].generator.fields[1]"),
    (gen(9, fields=["quantity", "revenue"]), "columns[9].generator.fields[1]"),
    (mutate(["columns", 9, "nullable_fraction"], 0.1), "columns[9].nullable_fraction"),
    (big_product(2, top=10**7), "columns[2].generator.fields"),
    (big_product(6), "columns[2].generator.fields"),  # 10^24 corners exceed default Decimal precision
    (gen(5, mapping={"East": "Japan", "West": "Spain"}), "columns[5].generator.mapping"),
    (gen(5, mapping={"East": "Japan", "West": "Spain", 'South, "Central"': "Chile", "North": "x"}), "columns[5].generator.mapping"),
    (gen(5, field="store_code_x"), "columns[5].generator.field"),
    (gen(5, field="channel"), "columns[5].generator.field"),
    (gen(5, field="order_id"), "columns[5].generator.field"),
    (gen(5, field="quantity"), "columns[5].generator.field"),
    (gen(5, mapping={"East": 1, "West": "Spain", 'South, "Central"': "Chile"}), 'columns[5].generator.mapping["East"]'),
    (gen(5, mapping={"East": None, "West": "Spain", 'South, "Central"': "Chile"}), "columns[5].generator.mapping"),
    (mutate(["columns", 5, "nullable_fraction"], 0.5), "columns[5].nullable_fraction"),
    *[(gen(2, values=["ok", text]), "columns[2].generator.values[1]") for text in FORMULAS],
    (gen(5, mapping={"East": "=HYPERLINK()", "West": "Spain", 'South, "Central"': "Chile"}), 'columns[5].generator.mapping["East"]'),
    (gen(0, prefix="=ID"), "columns[0].generator.prefix"),
    (gen(0, prefix="@"), "columns[0].generator.prefix"),
    ([1, 2], "request"),
]


@pytest.mark.parametrize("request_, field", INVALID, ids=[f"{i}:{f}" for i, (_, f) in enumerate(INVALID)])
def test_invalid_specs_reject_before_writing(tmp_path, request_, field):
    out = tmp_path / "sample.csv"
    with pytest.raises(SyntheticError) as caught:
        generate_csv(request_, out)
    assert caught.value.field.startswith(field), (caught.value.field, str(caught.value))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("text, field", [
    ('{"schema_version": 1, "schema_version": 1}', "schema_version"),
    ('{"schema_version": NaN}', "request"),
    ('{"row_count": 1' + "0" * 5000 + "}", "request"),
    ("not json", "request"),
    (b"\xff\xfe", "request"),
    (json.dumps(SPEC) + " " * (64 * 1024), "request"),
    ("[" * 5000, "request"),
    ('{"schema_version": "\ud800"}', "request"),
], ids=["duplicate-key", "nan", "huge-int", "not-json", "not-utf8", "oversized", "deep-nesting", "lone-surrogate"])
def test_invalid_request_text(tmp_path, text, field):
    with pytest.raises(SyntheticError) as caught:
        generate_csv(text, tmp_path / "sample.csv")
    assert caught.value.field == field
    assert list(tmp_path.iterdir()) == []


def test_oversized_model_request_rejects(tmp_path):
    columns = [col(f"c{i}", "string", {"kind": "choice", "values": [f"{i}-{k}-{'x' * 100}" for k in range(20)]})
               for i in range(40)]
    model = GenerationSpec.model_validate(spec_with(*columns, rows=10))
    with pytest.raises(SyntheticError) as caught:
        generate_csv(model, tmp_path / "sample.csv")
    assert caught.value.field == "request"


def test_negative_numeric_values_are_not_formulas(tmp_path):
    out = tmp_path / "sample.csv"
    generate_csv(spec_with(col("delta", "number", {"kind": "choice", "values": [-1.5, -2]}),
                           col("code", "string", {"kind": "sequence", "start": 1, "step": 1, "prefix": "A-"})), out)
    assert {r[0] for r in rows_of(out)[1:]} == {"-1.5", "-2"}


# Limits and atomicity -------------------------------------------------------------------------

def test_function_refuses_existing_output(tmp_path):
    out = tmp_path / "sample.csv"
    out.write_bytes(b"keep")
    with pytest.raises(SyntheticError) as caught:
        generate_csv(SPEC, out)
    assert caught.value.field == "output" and out.read_bytes() == b"keep"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["sample.csv"]


def test_byte_limit_fails_without_truncation(tmp_path):
    values = [f"{chr(97 + i)}{'x' * 119}" for i in range(3)]
    columns = [col(f"c{i}", "string", {"kind": "choice", "values": values}) for i in range(10)]
    out = tmp_path / "sample.csv"
    with pytest.raises(SyntheticError) as caught:
        generate_csv(spec_with(*columns, rows=100_000), out)
    assert "MiB" in caught.value.message
    assert list(tmp_path.iterdir()) == []


def test_time_limit_fails_without_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(synthetic, "MAX_SECONDS", -1)
    with pytest.raises(SyntheticError) as caught:
        generate_csv(SPEC, tmp_path / "sample.csv")
    assert "exceeded" in caught.value.message
    assert list(tmp_path.iterdir()) == []


def test_100k_by_10_meets_time_and_memory_budget(tmp_path):
    spec = spec_with(
        col("order_id", "string", {"kind": "sequence", "start": 1, "step": 1, "prefix": "ORD-"}),
        col("order_date", "date", {"kind": "date", "start": "2020-01-01", "end": "2025-12-31"}, 0.05),
        col("region", "string", {"kind": "choice", "values": ["East", "West", "North", "South"]}),
        col("country", "string", {"kind": "lookup", "field": "region",
                                  "mapping": {"East": "Japan", "West": "Spain", "North": "Norway", "South": "Chile"}}),
        col("quantity", "integer", {"kind": "integer", "min": 1, "max": 50}, 0.1),
        col("unit_price", "number", {"kind": "decimal", "min": 0.5, "max": 999.99, "decimals": 2}),
        col("revenue", "number", {"kind": "product", "fields": ["quantity", "unit_price"], "decimals": 2}),
        col("returned", "boolean", {"kind": "boolean", "true_probability": 0.1}),
        col("channel", "string", {"kind": "choice", "values": ["web", "store", "phone"]}, 0.2),
        col("line_no", "integer", {"kind": "sequence", "start": 1, "step": 1, "prefix": ""}),
        rows=100_000, seed=42)
    out = tmp_path / "sample.csv"
    tracemalloc.start()
    started = time.perf_counter()
    try:
        result = generate_csv(spec, out)
        elapsed = time.perf_counter() - started
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    print(f"\n100,000x10 synthetic CSV: {elapsed:.2f} s (under tracemalloc), "
          f"peak {peak / 2**20:.1f} MiB, {result.bytes / 2**20:.1f} MiB file")
    assert result.row_count == 100_000 and out.read_bytes().count(b"\n") == 100_001
    assert elapsed <= 30 and peak <= 128 * 2**20


def test_generator_imports_only_stdlib_and_pydantic():
    tree = ast.parse(Path(synthetic.__file__).read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported <= {"argparse", "collections", "csv", "datetime", "decimal", "hashlib", "json", "math", "os",
                        "pathlib", "pydantic", "random", "re", "sys", "tempfile", "time", "typing"}
    calls = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not calls & {"eval", "exec", "compile", "__import__"}
