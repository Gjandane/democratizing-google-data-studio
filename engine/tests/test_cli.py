import io
import json
import shlex
import subprocess
from pathlib import Path

import pytest

from dsengine.cli import main
from dsengine.events import EventWriter
from dsengine.recipe import load_recipe

SAMPLE = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "recipe.sample.jsonl"


@pytest.fixture
def records():
    return [json.loads(line) for line in SAMPLE.read_text(encoding="utf-8").splitlines()]


def write_recipe(tmp_path, records):
    path = tmp_path / "recipe.jsonl"
    path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
                    encoding="utf-8")
    return path


def test_validate_is_quiet(capsys):
    assert main(["validate", str(SAMPLE)]) == 0
    assert capsys.readouterr() == ("", "")


def test_header_only_is_successful_zero_op_run(tmp_path, records, capsys):
    path = write_recipe(tmp_path, records[:1])
    assert main(["run", str(path), "--dry-run"]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["event"] for event in events] == ["run_started", "run_finished"]
    assert events[0]["total_ops"] == 0
    assert events[-1]["status"] == "ok"
    assert events[-1]["ok"] == events[-1]["failed"] == events[-1]["skipped"] == 0
    assert main(["print", str(path)]) == 0
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("problem", [
    "empty", "blank", "broken_json", "duplicate_key", "nonfinite", "header_missing",
    "invalid_utf8", "duplicate_id", "decreasing_id", "bad_id", "unknown_op",
    "bad_header", "negative_geometry", "missing_metric", "bad_agg", "bad_color",
    "dropdown_without_field", "unknown_header_key",
])
def test_invalid_recipe_rejected_before_any_op(tmp_path, records, capsys, problem):
    if problem == "duplicate_id":
        records[2]["id"] = records[1]["id"]
    elif problem == "decreasing_id":
        records[1]["id"], records[2]["id"] = records[2]["id"], records[1]["id"]
    elif problem == "bad_id":
        records[1]["id"] = "s1"
    elif problem == "unknown_op":
        records[1]["op"] = "invented"
    elif problem == "bad_header":
        records[0]["recipe_version"] = "2.0"
    elif problem == "negative_geometry":
        records[3]["x"] = -1
    elif problem == "missing_metric":
        del records[5]["metrics"]
    elif problem == "bad_agg":
        records[5]["metrics"][0]["agg"] = "total"
    elif problem == "bad_color":
        records[11]["color"] = "red"
    elif problem == "dropdown_without_field":
        records[4]["control_type"] = "dropdown"
    elif problem == "unknown_header_key":
        records[0]["unexpected"] = "private-value-must-not-appear"
    path = write_recipe(tmp_path, records)
    corruptions = {
        "empty": b"", "blank": b"\n", "broken_json": b'{"private-value-must-not-appear"',
        "duplicate_key": b'{"recipe_version":"1.0","recipe_version":"1.0"}',
        "nonfinite": b'{"version":NaN}', "header_missing": b'{"id":"s001","op":"get_link"}',
        "invalid_utf8": b"\xff\xfe",
    }
    if problem in corruptions:
        path.write_bytes(corruptions[problem])
    assert main(["run", str(path), "--dry-run"]) == 2
    output = capsys.readouterr()
    events = [json.loads(line) for line in output.out.splitlines()]
    assert len(events) == 1
    assert events[0]["event"] == "log"
    assert events[0]["level"] == "error"
    assert output.err
    assert "private-value-must-not-appear" not in output.out + output.err


def test_blank_line_at_end_is_not_ignored(tmp_path, records, capsys):
    path = write_recipe(tmp_path, records)
    with path.open("a", encoding="utf-8") as file:
        file.write("\n")
    assert main(["validate", str(path)]) == 2
    assert "line 16: blank" in capsys.readouterr().err


def test_missing_file_is_clean_error(tmp_path, capsys):
    assert main(["validate", str(tmp_path / "missing.jsonl")]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "cannot read recipe file" in output.err
    assert "Traceback" not in output.err


@pytest.mark.parametrize("value", ["0", "-2", "nan", "inf", "not-a-number"])
def test_bad_timeout_argument(value, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["run", str(SAMPLE), "--dry-run", "--timeout", value])
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""


def test_env_timeout_and_cli_override(monkeypatch, capsys):
    monkeypatch.setenv("DSS_ENGINE_TIMEOUT_S", "invalid-private-value")
    with pytest.raises(SystemExit) as exc:
        main(["run", str(SAMPLE), "--dry-run"])
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert "invalid-private-value" not in output.err
    assert main(["run", str(SAMPLE), "--dry-run", "--timeout", "0.001"]) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["skipped"] == 14
    # Non-run subcommands do not need a usable browser timeout.
    assert main(["validate", str(SAMPLE)]) == 0


def test_run_options_are_passed_to_executor(monkeypatch, tmp_path, capsys):
    import dsengine.cli as cli

    captured = {}

    def capture(recipe, events, **kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "run_recipe", capture)
    monkeypatch.setenv("DSS_ENGINE_TIMEOUT_S", "17")
    assert main(["run", str(SAMPLE), "--dry-run"]) == 0
    assert captured == {"dry_run": True, "screens": SAMPLE.parent / "screens",
                        "screencast": False, "timeout": 17}
    assert main(["run", str(SAMPLE), "--screens", str(tmp_path), "--screencast", "--timeout", "3"]) == 0
    assert captured == {"dry_run": False, "screens": tmp_path,
                        "screencast": True, "timeout": 3}


def test_dry_run_does_not_create_screens(tmp_path, capsys):
    screens = tmp_path / "screens"
    assert main(["run", str(SAMPLE), "--dry-run", "--screens", str(screens), "--screencast"]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(events) == 30
    assert not screens.exists()


def test_live_execution_delegates_to_executor(monkeypatch, capsys):
    import dsengine.cli as cli

    captured = {}

    def capture(recipe, events, **kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "run_recipe", capture)
    assert main(["run", str(SAMPLE)]) == 0
    assert captured == {"dry_run": False, "screens": SAMPLE.parent / "screens",
                        "screencast": False, "timeout": 600}
    assert capsys.readouterr() == ("", "")


def test_asset_paths_are_recipe_relative(tmp_path, records, monkeypatch):
    path = write_recipe(tmp_path, records)
    monkeypatch.chdir(tmp_path.parent)
    recipe = load_recipe(path)
    assert recipe.asset_path("background_p1.png") == tmp_path / "background_p1.png"
    bar = next(op for op in recipe.ops if op.id == "s008")
    assert bar.model_dump()["options"] == {"orientation": "horizontal"}


def test_print_quotes_shell_metacharacters_and_preserves_nested_values(tmp_path, records, capsys):
    text = "Revenue's $(do-not-run) & # details"
    records[11]["text"] = text
    path = write_recipe(tmp_path, records)
    assert main(["print", str(path)]) == 0
    lines = capsys.readouterr().out.splitlines()
    args = shlex.split(lines[10])
    assert args[args.index("--text") + 1] == text
    args = shlex.split(lines[7])
    assert json.loads(args[args.index("--sort") + 1]) == {"field": "revenue", "order": "desc"}
    assert json.loads(args[args.index("--options") + 1]) == {"orientation": "horizontal"}


def test_multiline_unicode_text_prints_one_line(tmp_path, records):
    records[11]["text"] = "Café 東京\n第二行\t'quoted'\\end"
    path = write_recipe(tmp_path, records)
    result = subprocess.run(["dsengine", "print", str(path)], capture_output=True,
                            text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) == 14
    assert "Café 東京\\n第二行\\t" in result.stdout


def test_print_preserves_allowed_extension_fields(tmp_path, records, capsys):
    records[1].update(metrics=None, dimensions=1)
    path = write_recipe(tmp_path, records)
    assert main(["validate", str(path)]) == 0
    assert main(["print", str(path)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 14
    assert lines[0] == "dsengine open-report --metrics null --dimensions 1"


def test_event_writer_flushes_each_json_line():
    class RecordingStream(io.StringIO):
        flush_count = 0

        def flush(self):
            self.flush_count += 1

    stream = RecordingStream()
    writer = EventWriter(stream)
    writer.emit("log", level="info", message="two\nlines 東京")
    assert stream.flush_count == 1
    assert len(stream.getvalue().splitlines()) == 1
    assert json.loads(stream.getvalue())["message"] == "two\nlines 東京"
