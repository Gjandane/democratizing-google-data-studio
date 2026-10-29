"""One-shot job tickets (api.md 3.4) and the execute node's remote engine transport."""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3

from dss.db import new_id
from dss.harness.guardrails import RunError
from dss.harness.nodes.execute import EngineEvents, environment
from dss.harness.nodes.publish import publish
from dss.harness.tracing import Trace

logger = logging.getLogger(__name__)
API_VERSION = "3.4"
TICKET_TTL_S = 30 * 60
TIMEOUT_GRACE_S = 60
SWEEP_INTERVAL_S = 15
MISS_DELAY_S = 1
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # A-Z and 2-9 without I, O, 0, 1
PLAIN = re.compile(r"[A-Za-z0-9._-]+")
# Compared when a run has no token hash, so a miss costs the same as a wrong token.
NO_HASH = hashlib.sha256(b"no job token").hexdigest()


def stamp(moment=None):
    """Ticket times: fixed width, so SQLite compares them as text."""
    return (moment or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_stamp(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def new_code():
    raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_code(value):
    """Case-insensitive, spaces and dashes dropped; None when it can't be a code."""
    raw = re.sub(r"[\s-]", "", value).upper()
    if len(raw) != 8 or any(char not in ALPHABET for char in raw):
        return None
    return f"{raw[:4]}-{raw[4:]}"


def digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def safe_file(folder, name):
    root = folder.resolve()
    if not PLAIN.fullmatch(name) or name in (".", ".."):
        raise RunError("invalid_name", "Invalid file name", 400)
    target = (root / name).resolve()
    if not target.is_relative_to(root) or target == root:
        raise RunError("invalid_name", "Invalid file name", 400)
    return target


def recipe_input(root, name):
    """A version-relative recipe path, resolved; absolute, traversal and escaping paths reject."""
    parts = re.split(r"[\\/]", name)
    if ":" in name or "\0" in name or any(part in ("", ".", "..") for part in parts):
        raise RunError("invalid_name", "Invalid recipe input path", 400)
    target = root.joinpath(*parts).resolve()
    if not target.is_relative_to(root) or target == root:
        raise RunError("invalid_name", "Invalid recipe input path", 400)
    return target


def package(folder):
    """Plain transport names for every recipe input, and a private recipe copy that uses them.

    Plain names travel unchanged; nested (or case-colliding) ones get a name derived from their
    version-relative path, so it is stable across runs and distinct for same-basename assets.
    Lines without a renamed input keep their canonical bytes; the version folder is untouched.
    """
    root = folder.resolve()
    recipe = safe_file(folder, "recipe.jsonl")
    text = recipe.read_bytes().decode("utf-8")  # no newline translation
    lines = text.split("\n")  # LF only: U+2028 may sit inside a line
    end = [lines.pop()] if lines[-1] == "" else []
    inputs, names, used = {"recipe.jsonl": None}, {recipe: "recipe.jsonl"}, {"recipe.jsonl"}
    for i, line in enumerate(lines[1:], 1):
        op = json.loads(line)
        if "path" not in op:
            continue
        name = op["path"]
        if not isinstance(name, str):
            raise ValueError("Invalid recipe path")
        source = recipe_input(root, name)
        if not source.is_file():
            raise ValueError("Missing recipe input")
        if source not in names:
            plain = name if PLAIN.fullmatch(name) and name.casefold() not in used else None
            if plain is None:
                relative = source.relative_to(root).as_posix()
                stem = re.sub(r"[^A-Za-z0-9._-]", "_", source.name)[-64:]
                plain = f"asset-{hashlib.sha256(os.fsencode(relative)).hexdigest()[:16]}-{stem}"
            if plain.casefold() in used:  # agent filesystems may ignore case
                raise ValueError("Colliding recipe inputs")
            names[source], inputs[plain] = plain, source
            used.add(plain.casefold())
        if names[source] != name:
            op["path"] = names[source]
            lines[i] = json.dumps(op, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    inputs["recipe.jsonl"] = "\n".join(lines + end).encode("utf-8")
    return inputs


@dataclass
class Job:
    data: dict
    folder: Path
    inputs: dict  # transport name -> source path, or the packaged recipe's bytes
    parser: EngineEvents
    completion: asyncio.Future
    settled: asyncio.Future
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active: bool = True
    published: bool = False


class AgentJobs:
    """Tickets live in SQLite (they survive a restart); the Job and its Workflow live here."""

    def __init__(self, state):
        self.state = state
        self.jobs = {}  # run_id -> Job while its routes still answer
        self.running = {}  # run_id -> Job until the run's background releases it
        self.closed = False

    def prepare(self, run_id, build_id, folder, version, data=None):
        try:
            inputs = package(folder)
        except (OSError, ValueError, TypeError, RuntimeError):  # RuntimeError: symlink loop
            raise RunError("invalid_recipe", "Recipe inputs are missing or invalid", 422) from None
        if data is None:
            env = environment()
            data = dict(run_id=run_id, build_id=build_id, version=version,
                        dry_run=env.get("DSS_ENGINE_DRY_RUN") == "1",
                        timeout_s=int(env.get("DSS_ENGINE_TIMEOUT_S") or 600), files=list(inputs))
        elif list(inputs) != data["files"]:  # a resumed ticket must ship what it promised
            raise RunError("invalid_recipe", "Recipe inputs changed", 422)
        loop = asyncio.get_running_loop()
        return Job(data, folder, inputs, EngineEvents(self.state, folder), loop.create_future(), loop.create_future())

    def issue(self, job):
        """Persist a waiting ticket with a fresh code; no await, so the caller's checks still hold."""
        data, created = job.data, datetime.now(timezone.utc)
        for attempt in range(8):
            try:
                with self.state.db.connect() as conn:
                    conn.execute("INSERT INTO agent_tickets(run_id,build_id,version,code,state,created_at,expires_at,job_json) "
                                 "VALUES(?,?,?,?,'waiting',?,?,?)",
                                 (data["run_id"], data["build_id"], data["version"], new_code(), stamp(created),
                                  stamp(created + timedelta(seconds=TICKET_TTL_S)), json.dumps(data)))
                break
            except sqlite3.IntegrityError:  # the code is live on another ticket
                if attempt == 7:
                    raise
        self.jobs[data["run_id"]] = self.running[data["run_id"]] = job

    def live(self, build_id):
        with self.state.db.connect() as conn:
            return conn.execute("SELECT 1 FROM agent_tickets WHERE build_id=? AND state IN ('waiting','running')",
                                (build_id,)).fetchone() is not None

    def ticket(self, build_id):
        with self.state.db.connect() as conn:
            row = conn.execute("SELECT run_id,build_id,version,code,state,expires_at,claimed_at FROM agent_tickets "
                               "WHERE build_id=? ORDER BY rowid DESC LIMIT 1", (build_id,)).fetchone()
        if not row:
            raise RunError("job_not_found", "This build has no job", 404)
        return dict(row)

    async def claim(self, code):
        normalized, token, row = normalize_code(code), secrets.token_urlsafe(32), None
        if normalized:
            moment = stamp()
            with self.state.db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT run_id,job_json FROM agent_tickets WHERE code=? AND state='waiting' "
                                   "AND expires_at>?", (normalized, moment)).fetchone()
                if row and row["run_id"] in self.jobs:
                    conn.execute("UPDATE agent_tickets SET state='running',claimed_at=?,last_event_at=?,token_sha256=? "
                                 "WHERE run_id=?", (moment, moment, digest(token), row["run_id"]))
                else:
                    row = None
        if row is None:
            await asyncio.sleep(MISS_DELAY_S)
            raise RunError("job_code_invalid", "Unknown, used or expired job code", 404)
        job = self.jobs[row["run_id"]]
        job.parser.secrets += (token,)  # an echoed token never reaches events.jsonl or SSE
        return {"job": json.loads(row["job_json"]), "job_token": token, "api_version": API_VERSION}

    def authorize(self, run_id, token):
        """Before the run is looked up: an unknown run is 401 like a wrong token."""
        with self.state.db.connect() as conn:
            row = conn.execute("SELECT token_sha256 FROM agent_tickets WHERE run_id=?", (run_id,)).fetchone()
        stored = row["token_sha256"] if row else None
        matched = hmac.compare_digest(digest(token or ""), stored or NO_HASH)
        if not (matched and stored and token):
            raise RunError("agent_unauthorized", "Job token required", 401)

    def get(self, run_id):
        job = self.jobs.get(run_id)
        if not job or not job.active:
            raise RunError("job_not_found", "Job not found", 404)
        return job

    def transition(self, run_id, old, new, condition="", *args):
        with self.state.db.connect() as conn:
            return conn.execute(f"UPDATE agent_tickets SET state=? WHERE run_id=? AND state=?{condition}",
                                (new, run_id, old, *args)).rowcount == 1

    def close_ticket(self, run_id):
        with self.state.db.connect() as conn:
            conn.execute("UPDATE agent_tickets SET state='finished' WHERE run_id=? AND state IN ('waiting','running')",
                         (run_id,))

    def complete(self, job, exit_code, error=None):
        # All callers hold job.lock; no await between removing and completing.
        job.active = False
        self.jobs.pop(job.data["run_id"], None)
        if error:
            job.parser.failure = error
        job.completion.set_result((job.parser.outcome(exit_code), job.parser.failure))

    async def events(self, run_id, events):
        job = self.get(run_id)
        async with job.lock:
            self.get(run_id)
            with self.state.db.connect() as conn:
                conn.execute("UPDATE agent_tickets SET last_event_at=? WHERE run_id=? AND state='running'",
                             (stamp(), run_id))
            try:
                for value in events:
                    event = job.parser.parse(value)
                    if event and event.get("event") == "op_finished":
                        await self.state.harness.emit(job.data["build_id"], run_id, "build.op", event)
            except RunError as error:
                self.close_ticket(run_id)
                self.complete(job, 1, error)
        if not job.active:
            await asyncio.shield(job.settled)

    async def finish(self, run_id, exit_code):
        job = self.get(run_id)
        async with job.lock:
            self.get(run_id)
            self.close_ticket(run_id)
            self.complete(job, exit_code)
        await asyncio.shield(job.settled)

    async def execute(self, run_id):
        # A very fast agent can finish before the Workflow reaches this node.
        job = self.running[run_id]
        try:
            result, error = await asyncio.shield(job.completion)
        except asyncio.CancelledError:
            if not self.closed:
                self.close_ticket(run_id)
                await publish(self.state, job.data["build_id"], run_id, job.data["version"],
                              {"status": "failed", "report_url": None})
            job.published = True  # at shutdown the ticket and version wait for the next start
            raise
        await publish(self.state, job.data["build_id"], run_id, job.data["version"], result)
        job.published = True
        if error:
            raise error
        return json.dumps(result)

    async def sweep(self):
        """Expire waiting tickets past expires_at; fail running ones silent for timeout_s + 60 s."""
        moment = datetime.now(timezone.utc)
        with self.state.db.connect() as conn:
            rows = conn.execute("SELECT run_id,build_id,version,state,expires_at,last_event_at,job_json "
                                "FROM agent_tickets WHERE state IN ('waiting','running') ORDER BY rowid").fetchall()
        for row in rows:
            if row["state"] == "waiting":
                if parse_stamp(row["expires_at"]) <= moment:
                    await self.fail(row, "expired", RunError("job_expired", "The job code expired before a build agent claimed it", 410),
                                    " AND expires_at=?", row["expires_at"])
            else:
                limit = json.loads(row["job_json"])["timeout_s"] + TIMEOUT_GRACE_S
                if parse_stamp(row["last_event_at"]) + timedelta(seconds=limit) <= moment:
                    await self.fail(row, "finished", RunError("agent_timeout", "Build agent timed out", 504),
                                    " AND last_event_at=?", row["last_event_at"])

    async def fail(self, row, new, error, condition="", *args):
        run_id = row["run_id"]
        if job := self.jobs.get(run_id):
            async with job.lock:  # events refresh last_event_at under this lock
                if self.transition(run_id, row["state"], new, condition, *args) and job.active:
                    self.complete(job, 1, error)
        elif self.transition(run_id, row["state"], new, condition, *args):
            await self.finalize(row["build_id"], run_id, row["version"], error.code)

    async def sweep_forever(self):
        while True:
            await asyncio.sleep(SWEEP_INTERVAL_S)
            try:
                await self.sweep()
            except Exception:
                logger.warning("Job ticket sweep failed; will retry")

    async def finalize(self, build_id, run_id, version, error):
        """End a run whose Workflow is gone (a restart); replaces the interrupted run's cancelled trace."""
        with self.state.db.connect() as conn:
            conn.execute("DELETE FROM traces WHERE run_id=? AND status='error' AND error='cancelled'", (run_id,))
            building = conn.execute("SELECT 1 FROM versions WHERE build_id=? AND n=? AND status='building'",
                                    (build_id, version)).fetchone()
            traced = conn.execute("SELECT 1 FROM traces WHERE run_id=?", (run_id,)).fetchone()
        if building:
            await publish(self.state, build_id, run_id, version, {"status": "failed", "report_url": None})
        if not traced:
            Trace(self.state.db, run_id, build_id, "execute").save("error", error)
            await self.state.harness.emit(build_id, run_id, "run.finished", {
                "run_id": run_id, "node": "execute", "status": "error", "error": error})

    async def recover(self):
        """At startup: running tickets fail (their instance is gone), expired ones end, waiting
        ones become claimable again; other interrupted runs fail and are never reissued."""
        from dss.api.run import launch
        with self.state.db.connect() as conn:
            tickets = conn.execute("SELECT * FROM agent_tickets WHERE state IN ('waiting','running') ORDER BY rowid").fetchall()
        moment = stamp()
        for row in tickets:
            run_id, bid, version = row["run_id"], row["build_id"], row["version"]
            if row["state"] == "running":
                await self.fail(row, "finished", RunError("agent_timeout", "Build agent timed out", 504))
                continue
            if row["expires_at"] <= moment:
                await self.fail(row, "expired", RunError("job_expired", "The job code expired", 410))
                continue
            folder = self.state.config.data_dir / "builds" / bid / f"v{version}"
            try:
                job = self.prepare(run_id, bid, folder, version, json.loads(row["job_json"]))
            except RunError as error:
                await self.fail(row, "finished", error)
                continue
            with self.state.db.connect() as conn:
                conn.execute("DELETE FROM traces WHERE run_id=? AND status='error' AND error='cancelled'", (run_id,))
            self.jobs[run_id] = self.running[run_id] = job
            launch(self.state, bid, folder, version, run_id, job)
        with self.state.db.connect() as conn:
            interrupted = conn.execute("SELECT build_id,n FROM versions v WHERE status='building' AND NOT EXISTS "
                "(SELECT 1 FROM agent_tickets t WHERE t.build_id=v.build_id AND t.version=v.n AND t.state='waiting')").fetchall()
        for row in interrupted:
            bid, version = row["build_id"], row["n"]
            with self.state.db.connect() as conn:
                started = conn.execute("SELECT run_id FROM events e WHERE build_id=? AND kind='run.started' "
                    "AND json_extract(payload_json,'$.node')='execute' "
                    "AND NOT EXISTS (SELECT 1 FROM traces t WHERE t.run_id=e.run_id) "
                    "ORDER BY rowid DESC LIMIT 1", (bid,)).fetchone()
                run_id = started[0] if started else new_id("r")
                traced = conn.execute("SELECT 1 FROM traces WHERE run_id=?", (run_id,)).fetchone()
            await publish(self.state, bid, run_id, version, {"status": "failed", "report_url": None})
            if not traced:
                Trace(self.state.db, run_id, bid, "execute").save("error", "agent_timeout")
            await self.state.harness.emit(bid, run_id, "run.finished", {
                "run_id": run_id, "node": "execute", "status": "error", "error": "agent_timeout"})

    async def release(self, job):
        """Runs in the run's background finally, even if the Workflow fails."""
        async with job.lock:
            if job.active:
                if not self.closed:
                    self.close_ticket(job.data["run_id"])
                self.complete(job, 1)
        try:
            if not job.published and not self.closed:
                await publish(self.state, job.data["build_id"], job.data["run_id"], job.data["version"],
                              {"status": "failed", "report_url": None})
        finally:
            self.running.pop(job.data["run_id"], None)
            if not job.settled.done():
                job.settled.set_result(None)

    async def close(self):
        """Shutdown: live tickets stay in the database for the next start (recover)."""
        self.closed = True


