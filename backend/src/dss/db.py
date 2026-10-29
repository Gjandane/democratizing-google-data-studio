"""SQLite persistence for builds, episodic memory and one trace per agent run."""
import sqlite3
import asyncio
import logging
import shutil
import tempfile
import threading
from contextlib import contextmanager
from concurrent.futures import Future
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

BACKUP_INTERVAL_S = 30
IMMEDIATE_BACKUP_TIMEOUT_S = 3
logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_id(prefix):
    return f"{prefix}_{uuid4().hex[:12]}"


SCHEMA = """
CREATE TABLE IF NOT EXISTS builds (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, archetype TEXT NOT NULL,
 mode TEXT NOT NULL, stage TEXT NOT NULL, current_version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, notes TEXT, artifacts_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS versions (
 build_id TEXT NOT NULL REFERENCES builds(id), n INTEGER NOT NULL, status TEXT NOT NULL,
 spec_version INTEGER, report_url TEXT, created_at TEXT NOT NULL, PRIMARY KEY(build_id,n));
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY, build_id TEXT NOT NULL REFERENCES builds(id), kind TEXT NOT NULL,
 name TEXT NOT NULL, bq_table TEXT NOT NULL, row_count INTEGER NOT NULL, columns_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
 id TEXT PRIMARY KEY, build_id TEXT NOT NULL REFERENCES builds(id), role TEXT NOT NULL,
 text TEXT NOT NULL, node TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS messages_build ON messages(build_id);
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
CREATE TABLE IF NOT EXISTS synthetic_generations (
 generation_key TEXT NOT NULL, build_id TEXT NOT NULL REFERENCES builds(id), request_hash TEXT NOT NULL,
 run_id TEXT NOT NULL, source_id TEXT NOT NULL, bq_table TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('queued','generating','loading','succeeded','failed')),
 retry_ready INTEGER NOT NULL DEFAULT 0, error_json TEXT, created_at TEXT NOT NULL,
 spec_json TEXT NOT NULL, assumptions_json TEXT NOT NULL,
 generator_version TEXT, sha256 TEXT, bytes INTEGER, bq_location TEXT, PRIMARY KEY(build_id, generation_key));
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agent_tickets (
 run_id TEXT PRIMARY KEY, build_id TEXT NOT NULL REFERENCES builds(id), version INTEGER NOT NULL,
 code TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('waiting','running','finished','expired')),
 created_at TEXT NOT NULL, expires_at TEXT NOT NULL, claimed_at TEXT, token_sha256 TEXT,
 last_event_at TEXT, job_json TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS agent_tickets_live_code ON agent_tickets(code) WHERE state='waiting';
CREATE INDEX IF NOT EXISTS agent_tickets_build ON agent_tickets(build_id);
CREATE TABLE IF NOT EXISTS consolidation (
 id INTEGER PRIMARY KEY CHECK(id=1), last_run_at TEXT, chats_since INTEGER NOT NULL DEFAULT 0);
INSERT OR IGNORE INTO consolidation(id,chats_since) VALUES(1,0);
"""


class Database:
    def __init__(self, path: Path, data_dir: Path | None = None):
        self.path = Path(path).resolve()
        self.backup_path = None
        if data_dir is not None and not self.path.is_relative_to(Path(data_dir).resolve()):
            self.backup_path = Path(data_dir).resolve() / "dss.sqlite"
        self._generation = self._backed_up = 0
        self._dirty_lock = threading.Lock()
        self._backup_lock = threading.Lock()

    @property
    def dirty(self):
        with self._dirty_lock:
            return self._generation != self._backed_up

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            before = connection.total_changes
            with connection:
                yield connection
            if connection.total_changes != before:
                with self._dirty_lock:
                    self._generation += 1
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists() and self.backup_path and self.backup_path.is_file():
            shutil.copyfile(self.backup_path, self.path)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {row['name'] for row in connection.execute('PRAGMA table_info(builds)')}
            if 'notes' not in columns:
                connection.execute('ALTER TABLE builds ADD COLUMN notes TEXT')
            if 'artifacts_json' not in columns:
                connection.execute("ALTER TABLE builds ADD COLUMN artifacts_json TEXT NOT NULL DEFAULT '{}'")
            connection.execute("UPDATE builds SET stage='context' WHERE stage IN ('interview','plan')")
            if 'bq_location' not in {row['name'] for row in connection.execute('PRAGMA table_info(synthetic_generations)')}:
                connection.execute('ALTER TABLE synthetic_generations ADD COLUMN bq_location TEXT')

    def backup(self, *, force=False):
        """Snapshot locally with SQLite, then atomically replace the volume's copy."""
        if self.backup_path is None:
            return
        with self._backup_lock:
            with self._dirty_lock:
                generation = self._generation
                if not force and generation == self._backed_up:
                    return
            try:
                # The temporary database is always on local disk, never the data volume.
                with tempfile.TemporaryDirectory(prefix="dss-backup-") as local:
                    with self.connect() as source:
                        destination = sqlite3.connect(Path(local) / "dss.bak")
                        try:
                            source.backup(destination)
                        finally:
                            destination.close()
                    self.backup_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.backup_path.with_suffix(".sqlite.tmp")
                    shutil.copyfile(Path(local) / "dss.bak", temporary)
                    temporary.replace(self.backup_path)
                with self._dirty_lock:
                    self._backed_up = generation
            except Exception:
                # Paths and exception text may contain deployment secrets.
                logger.warning("Database backup failed; will retry")

    async def periodic_backup(self, stop):
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=BACKUP_INTERVAL_S)
            except TimeoutError:
                await self.async_backup()

    async def async_backup(self, *, force=False):
        if self.backup_path is None:
            return
        # A stalled volume must not trap asyncio's default-executor shutdown.
        # The snapshot lock still serializes a worker that outlives its awaiter.
        result = Future()

        def worker():
            if not result.set_running_or_notify_cancel():
                return
            try:
                self.backup(force=force)
                result.set_result(None)
            except BaseException as error:
                result.set_exception(error)

        threading.Thread(target=worker, name="dss-db-backup", daemon=True).start()
        await asyncio.wrap_future(result)

    async def immediate_backup(self):
        """Settle the best-effort durability boundary before propagating cancellation.

        The daemon snapshot can outlive a stalled volume attempt; its existing
        lock and dirty generation tracking still apply, without holding shutdown.
        """
        if self.backup_path is None:
            return

        async def attempt():
            try:
                async with asyncio.timeout(IMMEDIATE_BACKUP_TIMEOUT_S):
                    await self.async_backup()
            except TimeoutError:
                logger.warning('Database backup exceeded the immediate budget; will retry')

        backup = asyncio.create_task(attempt())
        cancelled = None
        while not backup.done():
            try:
                await asyncio.shield(backup)
            except asyncio.CancelledError as exc:
                cancelled = exc
        backup.result()
        if cancelled is not None:
            raise cancelled

    def build_exists(self, build_id):
        with self.connect() as connection:
            return connection.execute("SELECT 1 FROM builds WHERE id=?", (build_id,)).fetchone() is not None
