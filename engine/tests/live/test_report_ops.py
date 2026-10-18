import json
import os
import struct
import uuid
import zlib
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from dsengine.cli import main

pytestmark = pytest.mark.live


def _png(path: Path) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack("!I", len(data)) + kind + data
                + struct.pack("!I", zlib.crc32(kind + data)))

    pixels = (b"\0" + b"\xe8\xef\xf7" * 1200) * 900
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 1200, 900, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def test_five_report_operations_save_a_view_link(tmp_path, capsys):
    table = os.environ.get("DSS_TEST_TABLE", "bigquery-public-data.thelook_ecommerce.order_items")
    project, dataset, table_name = table.split(".")
    build_id = f"b_{uuid.uuid4().hex[:12]}"
    background = tmp_path / "background.png"
    _png(background)
    recipe_path = tmp_path / "recipe.jsonl"
    header = {
        "recipe_version": "1.0",
        "build_id": build_id,
        "version": 1,
        "report_name": f"Engine report ops {build_id}",
        "canvas": {"width": 1200, "height": 900},
        "datasource": {
            "connector": "bigQuery",
            "project_id": project,
            "dataset_id": dataset,
            "table_id": table_name,
        },
    }
    ops = [
        {"id": "s001", "op": "open_report"},
        {"id": "s002", "op": "set_canvas", "width": 1200, "height": 900},
        {"id": "s003", "op": "set_background_image", "path": background.name,
         "x": 0, "y": 0, "w": 1200, "h": 900},
        {"id": "s004", "op": "save_report"},
        {"id": "s005", "op": "get_link"},
    ]
    recipe_path.write_text(
        "\n".join(json.dumps(record) for record in [header, *ops]) + "\n",
        encoding="utf-8",
    )

    exit_code = main(["run", str(recipe_path), "--screens", str(tmp_path / "screens")])

    output = capsys.readouterr()
    assert exit_code == 0, output.err
    assert output.err == ""
    events = [json.loads(line) for line in output.out.splitlines()]
    finished = [event for event in events if event["event"] == "op_finished"]
    assert len(finished) == 5
    assert [event["status"] for event in finished] == ["ok"] * 5, [
        (event["op_id"], event["status"], event["message"]) for event in finished
    ]
    run_finished = events[-1]
    assert run_finished["event"] == "run_finished"
    assert run_finished["status"] == "ok"
    assert (run_finished["ok"], run_finished["failed"], run_finished["skipped"]) == (5, 0, 0)
    parsed = urlsplit(run_finished["report_url"])
    assert parsed.hostname in {"datastudio.google.com", "lookerstudio.google.com"}
    assert "/reporting/" in parsed.path
    assert "/create" not in parsed.path
    assert not parsed.path.endswith("/edit")
