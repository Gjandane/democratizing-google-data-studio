"""Black-box conformance against the sibling contract, never a copied schema."""

import json
import shlex
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

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
