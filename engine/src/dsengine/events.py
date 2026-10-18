"""Flushed, UTC-stamped JSONL event output."""

import json
import sys
from datetime import datetime, timezone
from typing import Any, TextIO


class EventWriter:
    def __init__(self, stream: TextIO | None = None):
        self.stream = stream if stream is not None else sys.stdout

    def emit(self, event: str, **fields: Any) -> None:
        payload = {
            "event": event,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            **fields,
        }
        print(json.dumps(payload, ensure_ascii=True, allow_nan=False), file=self.stream, flush=True)

    def error(self, message: str) -> None:
        # The contract has no separate `error` event; errors use its log variant.
        self.emit("log", level="error", message=message)
