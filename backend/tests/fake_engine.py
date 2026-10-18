"""Offline CLI with the recipe/event contract, plus failure modes for tests."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

command, path, *flags = sys.argv[1:]
lines = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
if command == "print":
    for op in lines[1:]:
        print("dsengine " + op["op"].replace("_", "-"), flush=True)
    sys.exit(0)

if os.environ.get("DSS_FAKE_HANG") == "1":
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    Path(path).with_name("fake-child-started").touch()
    time.sleep(60)

def emit(event, **args):
    print(json.dumps(dict(event=event, ts=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), **args)), flush=True)
if "--slow" in flags:
    time.sleep(0.3)
if "--broken" in flags:
    sys.exit(1)
emit("run_started", build_id=lines[0]["build_id"], version=lines[0]["version"], total_ops=len(lines)-1)
for op in lines[1:]:
    emit("op_started", op_id=op["id"], op=op["op"])
    emit("op_finished", op_id=op["id"], op=op["op"], status="skipped", message="", screenshot=None, duration_ms=0)
status = "partial" if "--partial" in flags else "ok"
emit("run_finished", status=status, report_url=None, ok=0, failed=0, skipped=len(lines)-1, error_code=None)
