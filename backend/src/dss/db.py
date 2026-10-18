"""SQLite persistence for builds, episodic memory and one trace per agent run."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_id(prefix):
    return f"{prefix}_{uuid4().hex[:12]}"


SCHEMA = """
CREATE TABLE IF NOT EXISTS builds (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, archetype TEXT NOT NULL,
 mode TEXT NOT NULL, stage TEXT NOT NULL, current_version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, ready_for_plan INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS versions (
 build_id TEXT NOT NULL REFERENCES builds(id), n INTEGER NOT NULL, status TEXT NOT NULL,
 spec_version INTEGER, report_url TEXT, created_at TEXT NOT NULL, PRIMARY KEY(build_id,n));
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY, build_id TEXT NOT NULL REFERENCES builds(id), kind TEXT NOT NULL,
 name TEXT NOT NULL, bq_table TEXT NOT NULL, row_count INTEGER NOT NULL, columns_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
 id TEXT PRIMARY KEY, build_id TEXT NOT NULL REFERENCES builds(id), role TEXT NOT NULL,
 text TEXT NOT NULL, node TEXT, created_at TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(text, content='messages', content_rowid='rowid');
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
 INSERT INTO messages_fts(rowid,text) VALUES(new.rowid,new.text); END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
 INSERT INTO messages_fts(messages_fts,rowid,text) VALUES('delete',old.rowid,old.text); END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
 INSERT INTO messages_fts(messages_fts,rowid,text) VALUES('delete',old.rowid,old.text);
 INSERT INTO messages_fts(rowid,text) VALUES(new.rowid,new.text); END;
CREATE TABLE IF NOT EXISTS events (
 id TEXT PRIMARY KEY, build_id TEXT REFERENCES builds(id), run_id TEXT, kind TEXT NOT NULL,
 payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS traces (
 run_id TEXT PRIMARY KEY, build_id TEXT REFERENCES builds(id), node TEXT NOT NULL, model TEXT,
 input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, latency_ms INTEGER NOT NULL,
 tool_calls INTEGER NOT NULL, status TEXT NOT NULL, error TEXT, spans_json TEXT NOT NULL,
 started_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS consolidation (
 id INTEGER PRIMARY KEY CHECK(id=1), last_run_at TEXT, chats_since INTEGER NOT NULL DEFAULT 0);
INSERT OR IGNORE INTO consolidation(id,chats_since) VALUES(1,0);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def build_exists(self, build_id):
        with self.connect() as connection:
            return connection.execute("SELECT 1 FROM builds WHERE id=?", (build_id,)).fetchone() is not None
