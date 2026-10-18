"""One persisted trace, including failed runs, without prompts or secret values."""
import json
from time import perf_counter

from dss.db import now


class Trace:
    def __init__(self, db, run_id, build_id, action):
        self.db, self.run_id, self.build_id, self.action = db, run_id, build_id, action
        self.started_at, self.start = now(), perf_counter()
        self.spans = []
        self.model = None
        self.input_tokens = self.output_tokens = 0

    def span(self, node):
        self.spans.append({"node": node})

    def save(self, status, error):
        with self.db.connect() as connection:
            connection.execute("INSERT INTO traces VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                self.run_id, self.build_id, self.action, self.model, self.input_tokens,
                self.output_tokens, int((perf_counter()-self.start)*1000), getattr(self, "tool_calls", 0), status,
                error, json.dumps(self.spans), self.started_at))
