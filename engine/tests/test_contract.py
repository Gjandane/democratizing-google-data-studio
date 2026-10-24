"""Black-box conformance against the sibling contract, never a copied schema."""

import json
import re
import shlex
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dsengine.ops import OperationError, charts
from dsengine.recipe import load_recipe

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT.parent / "contracts"
SAMPLE = CONTRACTS / "fixtures" / "recipe.sample.jsonl"


def run_cli(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["dsengine", *map(str, args)], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8", timeout=20)


def test_sample_dry_run_conforms_to_event_schema():
    result = run_cli("run", "../contracts/fixtures/recipe.sample.jsonl", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    events = [json.loads(line) for line in result.stdout.splitlines()]
    schema = json.loads((CONTRACTS / "recipe.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator({**schema, "$ref": "#/$defs/event"},
                                    format_checker=FormatChecker())
    for event in events:
        validator.validate(event)
        assert event["ts"].endswith("Z")
    recipe = [json.loads(line) for line in SAMPLE.read_text(encoding="utf-8").splitlines()]
    ops = recipe[1:]
    assert len(ops) == 14
    assert len(events) == 2 + 2 * len(ops)
    assert events[0]["event"] == "run_started"
    assert events[0]["build_id"] == recipe[0]["build_id"]
    assert events[0]["version"] == recipe[0]["version"]
    assert events[0]["total_ops"] == len(ops)
    for index, op in enumerate(ops):
        started, finished = events[1 + 2 * index:3 + 2 * index]
        assert started["event"] == "op_started"
        assert finished["event"] == "op_finished"
        assert started["op_id"] == finished["op_id"] == op["id"]
        assert started["op"] == finished["op"] == op["op"]
        assert finished["status"] == "skipped"
        assert finished["screenshot"] is None
    final = events[-1]
    assert final["event"] == "run_finished"
    assert final["status"] == "ok"
    assert final["report_url"] is None
    assert (final["ok"], final["failed"], final["skipped"]) == (0, 0, 14)
    assert final["error_code"] is None


def test_donut_chart_type_is_invalid(tmp_path):
    records = [json.loads(line) for line in SAMPLE.read_text(encoding="utf-8").splitlines()]
    next(record for record in records if record.get("op") == "add_chart")["chart_type"] = "donut"
    path = tmp_path / "invalid.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    result = run_cli("validate", path)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "chart_type" in result.stderr


def test_print_sample_has_fourteen_commands():
    result = run_cli("print", "../contracts/fixtures/recipe.sample.jsonl")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert len(lines) == 14
    assert all(line.startswith("dsengine ") for line in lines)
    assert lines[0] == "dsengine open-report"
    assert "--type bar" in lines[7]
    assert "--dim region" in lines[7]
    assert "--metric revenue:sum" in lines[7]
    assert lines[-2:] == ["dsengine save-report", "dsengine get-link"]


def _with_op(records, op):
    """Insert op right after open_report and renumber IDs to stay increasing."""
    ops = [records[1], dict(op), *records[2:]]
    return [records[0], *({**record, "id": f"s{index:03d}"} for index, record in enumerate(ops, 1))]


def test_rename_page_validates_prints_and_dry_runs(tmp_path):
    # Contract 1.1 adds rename_page; the header keeps recipe_version "1.0".
    records = [json.loads(line) for line in SAMPLE.read_text(encoding="utf-8").splitlines()]
    name = 'Q&A "Top" \'picks\''
    records = _with_op(records, {"op": "rename_page", "name": name})
    assert records[0]["recipe_version"] == "1.0"
    path = tmp_path / "rename.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    result = run_cli("validate", path)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    result = run_cli("print", path)
    assert result.returncode == 0, result.stderr
    line = result.stdout.splitlines()[1]
    assert line.startswith("dsengine rename-page --name ")
    assert shlex.split(line) == ["dsengine", "rename-page", "--name", name]
    result = run_cli("run", path, "--dry-run")
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    schema = json.loads((CONTRACTS / "recipe.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator({**schema, "$ref": "#/$defs/event"},
                                    format_checker=FormatChecker())
    for event in events:
        validator.validate(event)
    renamed = [event for event in events if event.get("op") == "rename_page"]
    assert [(event["event"], event.get("status")) for event in renamed] == [
        ("op_started", None), ("op_finished", "skipped")]
    assert events[-1]["skipped"] == 15


def test_rename_page_requires_a_nonempty_name(tmp_path):
    records = [json.loads(line) for line in SAMPLE.read_text(encoding="utf-8").splitlines()]
    path = tmp_path / "valid.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in
                              _with_op(records, {"op": "rename_page", "name": "x"})),
                    encoding="utf-8")
    assert run_cli("validate", path).returncode == 0
    for op, problem in (({"op": "rename_page"}, "(required)"),
                        ({"op": "rename_page", "name": ""}, "(name.minLength)")):
        path = tmp_path / "invalid.jsonl"
        path.write_text("\n".join(json.dumps(record) for record in _with_op(records, op)),
                        encoding="utf-8")
        result = run_cli("validate", path)
        assert result.returncode == 2
        assert f"line 3: invalid op {problem}" in result.stderr, result.stderr
        assert "invalid op" in result.stderr


def _contract_granularities():
    """The time_series date_granularity values recipe.md lists, in its order."""
    text = (CONTRACTS / "recipe.md").read_text(encoding="utf-8")
    listed = re.search(r"`time_series`:\s+`date_granularity` \(([^)]*)\)", text)
    assert listed, "recipe.md no longer lists time_series date_granularity"
    return re.findall(r"`(\w+)`", listed.group(1))


def _sample_time_series(records):
    return next(record for record in records if record.get("chart_type") == "time_series")


def test_date_granularity_check_accepts_exactly_the_contract_values():
    # Contract 1.2: the engine checks the value before any UI action, like geo_type.
    values = _contract_granularities()
    assert values == ["day", "week", "month", "quarter", "year"]
    assert list(charts._DATE_GRANULARITIES) == values
    recipe = load_recipe(SAMPLE)
    op = next(op for op in recipe.ops if getattr(op, "chart_type", None) == "time_series")
    for value in values:
        op.options = {"date_granularity": value}
        assert charts._granularity(op) == value
    for value in ("hour", "Monthly", ""):
        op.options = {"date_granularity": value}
        with pytest.raises(OperationError,
                           match="^date_granularity must be day, week, month, quarter or year$"):
            charts._granularity(op)


@pytest.mark.parametrize("value", ["day", "week", "month", "quarter", "year"])
def test_time_series_date_granularity_validates_prints_and_dry_runs(tmp_path, value):
    records = [json.loads(line) for line in SAMPLE.read_text(encoding="utf-8").splitlines()]
    _sample_time_series(records)["options"] = {"date_granularity": value}
    assert records[0]["recipe_version"] == "1.0"  # 1.2 adds the option; the header stays
    path = tmp_path / "granularity.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    result = run_cli("validate", path)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    result = run_cli("print", path)
    assert result.returncode == 0, result.stderr
    line = next(line for line in result.stdout.splitlines() if "--type time_series" in line)
    assert shlex.split(line)[-2:] == ["--options", json.dumps({"date_granularity": value},
                                                              separators=(",", ":"))]
    result = run_cli("run", path, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["skipped"] == len(records) - 1


def test_sample_time_series_without_date_granularity_keeps_its_inferred_type(tmp_path):
    # Without the option nothing changes: no option to print, no type change to make.
    records = [json.loads(line) for line in SAMPLE.read_text(encoding="utf-8").splitlines()]
    assert "options" not in _sample_time_series(records)
    result = run_cli("print", SAMPLE)
    line = next(line for line in result.stdout.splitlines() if "--type time_series" in line)
    assert "--options" not in line
    recipe = load_recipe(SAMPLE)
    op = next(op for op in recipe.ops if getattr(op, "chart_type", None) == "time_series")
    assert charts._granularity(op) is None

    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError(f"page.{name} used")

    charts._date_granularity(Untouchable(), None, op, change=True)


def _area_op(**options):
    return {"op": "add_chart", "component_id": "p1_area", "chart_type": "area",
            "x": 24, "y": 100, "w": 560, "h": 280, "dimensions": [],
            "date_dimension": "order_date", "metrics": [{"field": "revenue", "agg": "sum"}],
            "breakdown": "region", "options": options}


def _write(tmp_path, records, name="recipe.jsonl"):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    return path


@pytest.mark.parametrize("options", [{}, {"date_granularity": "month"},
                                     {"stacked": True, "date_granularity": "month"},
                                     {"stacked_percent": True}, {"stacked": False}])
def test_area_chart_validates_prints_and_dry_runs(tmp_path, options):
    # Recipe 1.3 adds chart_type area; the header keeps recipe_version "1.0".
    records = [json.loads(line) for line in SAMPLE.read_text(encoding="utf-8").splitlines()]
    records = _with_op(records, _area_op(**options))
    path = _write(tmp_path, records)
    result = run_cli("validate", path)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    result = run_cli("print", path)
    assert result.returncode == 0, result.stderr
    assert "--type area" in result.stdout.splitlines()[1]
    result = run_cli("run", path, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["skipped"] == len(records) - 1


def test_bar_stacked_percent_validates(tmp_path):
    records = [json.loads(line) for line in SAMPLE.read_text(encoding="utf-8").splitlines()]
    bar = next(record for record in records if record.get("chart_type") == "bar")
    bar["options"] = {**bar.get("options", {}), "stacked_percent": True}
    result = run_cli("validate", _write(tmp_path, records))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


@pytest.mark.parametrize("key, value", [("stacked_percent", "true"), ("stacked_percent", 1),
                                        ("stacked_percent", None), ("stacked", "yes")])
@pytest.mark.parametrize("chart_type", ["area", "bar"])
def test_non_bool_stacking_is_rejected_by_validate(tmp_path, chart_type, key, value):
    # The schema leaves options open, so the engine's own check owns the bool type.
    records = [json.loads(line) for line in SAMPLE.read_text(encoding="utf-8").splitlines()]
    op = _area_op(**{key: value})
    if chart_type == "bar":
        op.update(chart_type="bar", dimensions=["region"], date_dimension=None, breakdown=None)
    records = _with_op(records, op)
    schema = json.loads((CONTRACTS / "recipe.schema.json").read_text(encoding="utf-8"))
    assert Draft202012Validator({**schema, "$ref": "#/$defs/op"}).is_valid(records[2])
    result = run_cli("validate", _write(tmp_path, records))
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip().endswith(f"line 3: {key} must be true or false"), result.stderr


@pytest.mark.parametrize("control_type", ["dropdown", "fixed_size_list"])
def test_field_controls_need_a_field_in_validate(tmp_path, control_type):
    # Recipe 1.3 adds fixed_size_list (release 2.6's region checkbox list); the
    # schema leaves field optional, so the engine requires it, as for dropdown.
    records = [json.loads(line) for line in SAMPLE.read_text(encoding="utf-8").splitlines()]
    op = {"op": "add_control", "component_id": "p1_region", "control_type": control_type,
          "x": 24, "y": 100, "w": 200, "h": 220, "field": "region"}
    result = run_cli("validate", _write(tmp_path, _with_op(records, op)))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    del op["field"]
    records = _with_op(records, op)
    schema = json.loads((CONTRACTS / "recipe.schema.json").read_text(encoding="utf-8"))
    assert Draft202012Validator({**schema, "$ref": "#/$defs/op"}).is_valid(records[2])
    result = run_cli("validate", _write(tmp_path, records))
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip().endswith(f"line 3: {control_type} requires a field"), result.stderr
