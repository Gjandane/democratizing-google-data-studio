"""Single-instance FIFO and the execute node's remote engine transport."""
import asyncio
from collections import deque
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import time

from dss.db import new_id, now
from dss.harness.guardrails import RunError
from dss.harness.nodes.execute import EngineEvents, environment
from dss.harness.nodes.publish import publish
from dss.harness.tracing import Trace

HEARTBEAT_TTL_S = 30
TIMEOUT_GRACE_S = 60


def safe_file(folder, name):
    root = folder.resolve()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name) or name in (".", ".."):
        raise RunError("invalid_name", "Invalid file name", 400)
    target = (root / name).resolve()
    if not target.is_relative_to(root) or target == root:
        raise RunError("invalid_name", "Invalid file name", 400)
    return target


@dataclass
class Job:
    data: dict
    folder: Path
    parser: EngineEvents
    completion: asyncio.Future
    settled: asyncio.Future
    last_activity: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active: bool = True
    published: bool = False


class AgentJobs:
    def __init__(self, state):
        self.state = state
        self.jobs = {}
        self.running = {}
        self.queue = deque()
        self.changed = asyncio.Condition()
        self.closed = False
        self.last_seen = None
        self.last_seen_clock = None
        self.chrome_running = self.signed_in = False

    @property
    def connected(self):
        return self.last_seen_clock is not None and time.monotonic() - self.last_seen_clock < HEARTBEAT_TTL_S

    def heartbeat(self, chrome_running, signed_in):
        self.last_seen, self.last_seen_clock = now(), time.monotonic()
        self.chrome_running, self.signed_in = chrome_running, signed_in

    def prepare(self, run_id, build_id, folder, version):
        names = ["recipe.jsonl"]
        try:
            recipe = safe_file(folder, "recipe.jsonl")
            ops = [json.loads(line) for line in recipe.read_text(encoding="utf-8").splitlines()][1:]
            for op in ops:
                if "path" in op:
                    name = op["path"]
                    if not isinstance(name, str):
                        raise ValueError("Invalid recipe path")
                    if name not in names:
                        names.append(name)
            for name in names:
                if not safe_file(folder, name).is_file():
                    raise ValueError("Missing recipe input")
        except (OSError, ValueError, TypeError):
            raise RunError("invalid_recipe", "Recipe inputs are missing or invalid", 422) from None
        env = environment()
        data = dict(run_id=run_id, build_id=build_id, version=version,
                    dry_run=env.get("DSS_ENGINE_DRY_RUN") == "1",
                    timeout_s=int(env.get("DSS_ENGINE_TIMEOUT_S") or 600), files=names)
        loop = asyncio.get_running_loop()
        return Job(data, folder, EngineEvents(self.state, folder), loop.create_future(), loop.create_future())

    async def enqueue(self, job):
        async with self.changed:
            self.jobs[job.data["run_id"]] = job
            self.running[job.data["run_id"]] = job
            self.queue.append(job.data["run_id"])
            self.changed.notify_all()

    async def next(self, wait):
        async with self.changed:
            try:
                async with asyncio.timeout(wait):
                    while not self.closed:
                        while self.queue:
                            job = self.jobs.get(self.queue.popleft())
                            if job and job.active:
                                return job.data
                        await self.changed.wait()
            except TimeoutError:
                pass
        return None

    def get(self, run_id):
        job = self.jobs.get(run_id)
        if not job or not job.active:
            raise RunError("job_not_found", "Job not found", 404)
        return job

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
            job.last_activity = time.monotonic()
            try:
                for value in events:
                    event = job.parser.parse(value)
                    if event and event.get("event") == "op_finished":
                        await self.state.harness.emit(job.data["build_id"], run_id, "build.op", event)
            except RunError as error:
                self.complete(job, 1, error)
        if not job.active:
            await asyncio.shield(job.settled)

    async def finish(self, run_id, exit_code):
        job = self.get(run_id)
        async with job.lock:
            self.get(run_id)
            self.complete(job, exit_code)
        await asyncio.shield(job.settled)

    async def execute(self, run_id):
        # A very fast agent can finish before the Workflow reaches this node.
        job = self.running[run_id]
        try:
            while not job.completion.done():
                remaining = job.last_activity + job.data["timeout_s"] + TIMEOUT_GRACE_S - time.monotonic()
                try:
                    await asyncio.wait_for(asyncio.shield(job.completion), max(0, remaining))
                except TimeoutError:
                    async with job.lock:
                        if job.active and time.monotonic() >= job.last_activity + job.data["timeout_s"] + TIMEOUT_GRACE_S:
                            self.complete(job, 1, RunError("agent_timeout", "Build agent timed out", 504))
            result, error = job.completion.result()
        except asyncio.CancelledError:
            result = {"status": "failed", "report_url": None}
            await publish(self.state, job.data["build_id"], run_id, job.data["version"], result)
            job.published = True
            raise
        await publish(self.state, job.data["build_id"], run_id, job.data["version"], result)
        job.published = True
        if error:
            raise error
        return json.dumps(result)

    async def recover(self):
        """Finalize interrupted persisted runs; never reissue their lost jobs."""
        with self.state.db.connect() as conn:
            interrupted = conn.execute("SELECT build_id,n FROM versions WHERE status='building'").fetchall()
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
        """Runs in the request's background finally, even if the Workflow fails."""
        async with job.lock:
            if job.active:
                self.complete(job, 1)
        try:
            if not job.published:
                await publish(self.state, job.data["build_id"], job.data["run_id"], job.data["version"],
                              {"status": "failed", "report_url": None})
        finally:
            self.running.pop(job.data["run_id"], None)
            if not job.settled.done():
                job.settled.set_result(None)

    async def close(self):
        async with self.changed:
            self.closed = True
            self.changed.notify_all()

