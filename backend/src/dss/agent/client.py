"""dss-agent: runs the local engine for the builds an agent-mode backend queues."""
import argparse
from collections import deque
from importlib.metadata import PackageNotFoundError, version as package_version
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

import httpx

from dss.config import BACKEND_DIR, Config
from dss.harness.nodes.execute import engine_command, environment, terminate_tree

HEARTBEAT_S = 10
CHECK_S = 60
CHECK_TIMEOUT_S = 30
POLL_WAIT_S = 25
HTTP_TIMEOUT_S = 40  # longer than the long poll's wait + 10 s
CONNECT_TIMEOUT_S = 10
FLUSH_S = 1
RETRY_BUDGET_S = 60
BACKOFF_S, BACKOFF_MAX_S = 1, 10
KILL_GRACE_S = 5  # as the local backend: the engine's own --timeout ends the run first
STDERR_TAIL = 4000
LOOPBACK = ("localhost", "127.0.0.1", "::1")
RUN_ID, BUILD_ID = re.compile(r"r_[0-9a-f]{12}"), re.compile(r"b_[0-9a-f]{12}")
NAME = re.compile(r"[A-Za-z0-9._-]+")
logger = logging.getLogger(__name__)


class AgentExit(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


class Stopped(Exception):
    pass


class JobGone(Exception):
    """404 job_not_found: the server no longer holds the job (restart or timeout)."""


class JobError(Exception):
    pass


def describe(error):
    # Only our own messages; library errors are named by type so nothing they carry is logged.
    return str(error) if isinstance(error, (AgentExit, JobError)) else type(error).__name__


class Agent:
    def __init__(self, server, token, data_dir, command, dry_run=False):
        self.server, self.token, self.data_dir = server.rstrip("/"), token, data_dir
        self.command, self.dry_run = command, dry_run
        self.status = {"chrome_running": False, "signed_in": False}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.next_check = 0.0
        try:
            self.version = package_version("dss-backend")
        except PackageNotFoundError:
            self.version = "unknown"

    @classmethod
    def from_env(cls, server=None, dry_run=False):
        """The root .env, DSS_DATA_DIR and DSS_ENGINE_CMD resolve from backend/, whatever the cwd."""
        env, config = environment(), Config.from_env()
        server = (server or env.get("DSS_AGENT_SERVER") or "").strip().rstrip("/")
        url = urlparse(server)
        if url.scheme not in ("http", "https") or not url.hostname:
            raise AgentExit("Set DSS_AGENT_SERVER in the root .env or pass --server <URL>", 2)
        if url.path or url.query or url.fragment:
            raise AgentExit("The server URL is the hosted app's base URL, without a path", 2)
        if url.scheme == "http" and url.hostname not in LOOPBACK:
            raise AgentExit("Use an https server URL: the agent token must not cross the network in clear text", 2)
        token = config.agent_token.get_secret_value()
        if not token:
            raise AgentExit("Set DSS_AGENT_TOKEN in the root .env", 2)
        if not (token.isascii() and token.isprintable()):
            raise AgentExit("DSS_AGENT_TOKEN must be printable ASCII", 2)
        return cls(server, token, config.data_dir.resolve(), engine_command(), dry_run)

    def http(self):
        return httpx.Client(base_url=self.server, headers={"X-DSS-Agent-Token": self.token},
                            timeout=httpx.Timeout(HTTP_TIMEOUT_S, connect=CONNECT_TIMEOUT_S))

    def call(self, http, method, path, *, retry=True, **kwargs):
        """One agent request; network errors, 429 and 5xx retry with backoff for RETRY_BUDGET_S."""
        failing_since, delay = None, BACKOFF_S
        while True:
            try:
                response = http.request(method, "/api/agent" + path, **kwargs)
                if response.status_code < 500 and response.status_code != 429:
                    break
                reason = f"HTTP {response.status_code}"
            except httpx.TransportError as error:
                reason = type(error).__name__
            if not retry:
                raise AgentExit(f"Server unavailable ({reason})")
            failing_since = failing_since or time.monotonic()
            remaining = failing_since + RETRY_BUDGET_S - time.monotonic()
            if remaining <= 0:
                raise AgentExit(f"Server unavailable for {RETRY_BUDGET_S} s ({reason}); exiting")
            logger.warning("Server unavailable (%s); retrying in %.1f s", reason, min(delay, remaining))
            if self.stop.wait(min(delay, remaining)):
                raise Stopped()
            delay = min(delay * 2, BACKOFF_MAX_S)
        if response.status_code == 401:
            raise AgentExit("The server rejected DSS_AGENT_TOKEN", 2)
        if response.status_code >= 400:
            try:
                code = response.json()["error"]["code"]
            except (ValueError, KeyError, TypeError):
                code = f"HTTP {response.status_code}"
            if code == "agent_mode_off":
                raise AgentExit("The server is not in agent mode (DSS_ENGINE_MODE=agent)", 2)
            if code == "job_not_found":
                raise JobGone()
            raise JobError(code)
        return response

    def check(self):
        """`dsengine check` feeds the heartbeat; only the idle main loop calls it, never during a run."""
        status = {"chrome_running": False, "signed_in": False}
        try:
            process = subprocess.Popen(self.command + ["check"], cwd=BACKEND_DIR, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                start_new_session=os.name != "nt")
        except OSError as error:
            logger.warning("dsengine check could not start (%s)", describe(error))
        else:
            try:
                output, _ = process.communicate(timeout=CHECK_TIMEOUT_S)
                value = json.loads(output) if process.returncode == 0 else {}
                status = {key: isinstance(value, dict) and value.get(key) is True for key in status}
            except (ValueError, subprocess.TimeoutExpired):
                logger.warning("dsengine check returned no status")
            finally:
                if process.poll() is None:
                    terminate_tree(process)
                process.wait()
                process.stdout.close()
        with self.lock:
            self.status = status
        self.next_check = time.monotonic() + CHECK_S

    def heartbeats(self):
        """Own thread and client, so heartbeats continue during long polls and engine runs."""
        connected = None
        with self.http() as http:
            while True:
                with self.lock:
                    body = {**self.status, "agent_version": self.version}
                try:
                    self.call(http, "POST", "/heartbeat", retry=False, json=body)
                    if not connected:
                        logger.info("Connected to %s", self.server)
                    connected = True
                except Exception as error:  # keep beating; the main loop decides when to exit
                    if connected is not False:
                        logger.warning("Heartbeat failed: %s", describe(error))
                    connected = False
                if self.stop.wait(HEARTBEAT_S):
                    return

    def run(self):
        logger.info("dss-agent %s: server %s, jobs in %s%s", self.version, self.server,
                    self.data_dir / "agent", ", dry run" if self.dry_run else "")
        self.check()
        beat = threading.Thread(target=self.heartbeats, name="dss-agent-heartbeat", daemon=True)
        beat.start()
        try:
            with self.http() as http:
                while not self.stop.is_set():
                    if time.monotonic() >= self.next_check:
                        self.check()
                    wait = max(0.0, min(POLL_WAIT_S, self.next_check - time.monotonic()))
                    try:
                        response = self.call(http, "GET", "/jobs/next", params={"wait": round(wait, 2)})
                    except JobError as error:
                        raise AgentExit(f"The server refused the job poll ({error})") from None
                    if response.status_code == 200:
                        try:
                            job = response.json()
                        except ValueError:
                            raise AgentExit("The server answered the job poll without JSON; check the server URL") from None
                        self.run_job(http, job)  # one job at a time: no poll until it is reported
            return 0
        except Stopped:
            return 0
        except AgentExit as error:
            logger.error("%s", error)
            return error.code
        finally:
            self.stop.set()
            beat.join(timeout=1)

    def folder(self, job):
        """Validate a job before any of its fields reaches a path or a command line."""
        if not isinstance(job.get("build_id"), str) or not BUILD_ID.fullmatch(job["build_id"]):
            raise ValueError("build_id")
        for key, low in (("version", 1), ("timeout_s", 0)):
            if type(job.get(key)) is not int or job[key] < low:
                raise ValueError(key)
        if type(job.get("dry_run")) is not bool:
            raise ValueError("dry_run")
        files = job.get("files")
        if not isinstance(files, list) or not files or files[0] != "recipe.jsonl" or not all(
                isinstance(name, str) and NAME.fullmatch(name) and name not in (".", "..", "screens")
                for name in files):
            raise ValueError("files")
        return self.data_dir / "agent" / job["build_id"] / f"v{job['version']}"

    def run_job(self, http, job):
        run_id = job.get("run_id") if isinstance(job, dict) else None
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            logger.error("Ignored a job without a valid run_id")
            return
        try:
            folder = self.folder(job)
        except ValueError as error:
            logger.error("Job %s is invalid (%s)", run_id, error)
            self.report(http, run_id, 2, "the build agent rejected an invalid job")
            return
        logger.info("Job %s: build %s v%s", run_id, job["build_id"], job["version"])
        try:
            if folder.exists():
                shutil.rmtree(folder)  # a retried version starts from a clean copy
            (folder / "screens").mkdir(parents=True)
            for name in job["files"]:
                (folder / name).write_bytes(self.call(http, "GET", f"/jobs/{run_id}/files/{name}").content)
            code, tail = self.run_engine(http, run_id, job, folder)
        except JobGone:
            self.forget(run_id, folder)
            return
        except (JobError, OSError) as error:
            logger.error("Job %s could not run (%s)", run_id, describe(error))
            self.report(http, run_id, 1, "the build agent could not run the job", folder)
            return
        except (KeyboardInterrupt, Stopped):
            self.report(http, run_id, 1, "the build agent stopped", folder, retry=False)
            raise
        if self.report(http, run_id, code, tail, folder):
            logger.info("Job %s finished (exit code %s)", run_id, code)

    def report(self, http, run_id, code, tail, folder=None, retry=True):
        try:
            self.call(http, "POST", f"/jobs/{run_id}/finished", retry=retry,
                      json={"exit_code": code, "stderr_tail": tail})
            return True
        except JobGone:
            if folder:
                self.forget(run_id, folder)
        except (JobError, AgentExit) as error:
            if retry and isinstance(error, AgentExit):
                raise
            logger.warning("Job %s: the server did not take the result (%s)", run_id, describe(error))
        return False

    def forget(self, run_id, folder):
        shutil.rmtree(folder, ignore_errors=True)
        logger.warning("Job %s no longer exists on the server; stopped it and removed %s", run_id, folder)

    def engine_args(self, job, folder):
        args = self.command + ["run", str(folder / "recipe.jsonl"), "--timeout", str(job["timeout_s"])]
        if self.dry_run or job["dry_run"]:
            args.append("--dry-run")
        return args + ["--screens", str(folder / "screens")]

    def run_engine(self, http, run_id, job, folder):
        """Stream one run's events in batches; a 404 or exit here stops the engine tree."""
        process = subprocess.Popen(self.engine_args(job, folder), cwd=BACKEND_DIR, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            start_new_session=os.name != "nt")
        lines, tail, expired = queue.Queue(), deque(maxlen=200), threading.Event()
        def read_stdout():
            for line in process.stdout:
                lines.put(line)
            lines.put(None)
        def read_stderr():
            for line in process.stderr:
                tail.append(line)
        def kill():
            expired.set()
            terminate_tree(process)
        readers = [threading.Thread(target=read, daemon=True) for read in (read_stdout, read_stderr)]
        for reader in readers:
            reader.start()
        timer = threading.Timer(job["timeout_s"] + KILL_GRACE_S, kill)
        timer.daemon = True
        timer.start()
        try:
            batch, deadline, done = [], None, False
            while not done:
                if self.stop.is_set():
                    raise Stopped()
                try:
                    # Short waits keep Ctrl+C responsive on Windows.
                    line = lines.get(timeout=.5 if deadline is None else max(0, min(.5, deadline - time.monotonic())))
                    if line is None:
                        done = True
                    elif (event := self.event(line)) is not None:
                        batch.append(event)
                        deadline = deadline or time.monotonic() + FLUSH_S
                except queue.Empty:
                    pass
                if batch and (done or time.monotonic() >= deadline):
                    self.send(http, run_id, folder, batch)
                    batch, deadline = [], None
            code = process.wait()
        finally:
            timer.cancel()
            if process.poll() is None:
                terminate_tree(process)
            process.wait()
            for reader in readers:
                reader.join(timeout=5)
            process.stdout.close()
            process.stderr.close()
        return (-1 if expired.is_set() else code), self.redact("".join(tail))[-STDERR_TAIL:]

    def event(self, line):
        try:
            value = json.loads(line)
        except ValueError:
            return None
        return self.redact(value) if isinstance(value, dict) else None

    def redact(self, value):
        if isinstance(value, str):
            return value.replace(self.token, "[redacted]")
        if isinstance(value, dict):
            return {self.redact(key): self.redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        return value

    def send(self, http, run_id, folder, batch):
        # Screenshots go first, so a build.op the UI receives can already show its screenshot.
        for event in batch:
            if event.get("event") == "op_finished":
                logger.info("Job %s: %s %s %s", run_id, event.get("op_id"), event.get("op"), event.get("status"))
                if event.get("screenshot"):
                    self.upload(http, run_id, folder, event["screenshot"])
        try:
            self.call(http, "POST", f"/jobs/{run_id}/events", json={"events": batch})
        except JobError as error:
            logger.warning("Job %s: the server refused %d events (%s)", run_id, len(batch), error)

    def upload(self, http, run_id, folder, name):
        path = folder / "screens" / name if isinstance(name, str) and NAME.fullmatch(name) \
            and name.endswith(".png") and name != ".png" else None
        if not path or not path.is_file():
            logger.warning("Job %s: skipped a screenshot with an invalid name or no file", run_id)
            return
        try:
            self.call(http, "PUT", f"/jobs/{run_id}/screens/{name}", content=path.read_bytes())
        except JobError as error:
            logger.warning("Job %s: the server refused screenshot %s (%s)", run_id, name, error)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(levelname)s backend.agent: %(message)s")
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="dss-agent",
        description="Run the builds a hosted backend queues on this machine's engine.")
    parser.add_argument("--server", help="hosted app URL (default: DSS_AGENT_SERVER from the root .env)")
    parser.add_argument("--dry-run", action="store_true", help="add --dry-run to every engine run (rehearsals)")
    # Rejected without echoing: argparse would print an unknown option's value.
    parser.add_argument("--token", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.token is not None:
        logger.error("The agent token comes only from DSS_AGENT_TOKEN in the root .env, never from a flag")
        return 2
    try:
        agent = Agent.from_env(args.server, args.dry_run)
    except AgentExit as error:
        logger.error("%s", error)
        return error.code
    try:
        return agent.run()
    except KeyboardInterrupt:
        logger.info("Stopped")
        return 130


if __name__ == "__main__":
    sys.exit(main())
