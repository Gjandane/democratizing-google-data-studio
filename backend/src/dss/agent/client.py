"""dss-agent run: claims one hosted build by its code, runs it on this machine's engine, then exits."""
import argparse
from collections import deque
from importlib.metadata import PackageNotFoundError, version as package_version
import json
import logging
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

import httpx

from dss.agent.jobs import API_VERSION, normalize_code
from dss.config import BACKEND_DIR, Config
from dss.harness.nodes.execute import engine_command, start_engine, terminate_tree

HTTP_TIMEOUT_S = 40
CONNECT_TIMEOUT_S = 10
FLUSH_S = 1
RETRY_BUDGET_S = 60
CLEANUP_S = .4  # one allowance for close, engine reaping, readers and main-loop teardown
BACKOFF_S, BACKOFF_MAX_S = 1, 10
KILL_GRACE_S = 5  # as the local backend: the engine's own --timeout ends the run first
STDERR_TAIL = 4000
LOOPBACK = ("localhost", "127.0.0.1", "::1")
REPORT_HOSTS = ("datastudio.google.com", "lookerstudio.google.com")
RUN_ID, BUILD_ID = re.compile(r"r_[0-9a-f]{12}"), re.compile(r"b_[0-9a-f]{12}")
NAME = re.compile(r"[A-Za-z0-9._-]+")
ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
USAGE = "usage: dss-agent run --server <URL> --job <CODE> [--dry-run]"
CODE_INVALID = "That code was used or has expired. Click Build again for a new code."
UPDATE = "Rerun the setup command with -Update"
logger = logging.getLogger(__name__)


class AgentExit(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


class Stopped(Exception):
    pass


class JobGone(Exception):
    """404 job_not_found: the server no longer holds the job (restart, expiry or timeout)."""


class JobError(Exception):
    pass


def describe(error):
    # Only our own messages; library errors are named by type so nothing they carry is logged.
    return str(error) if isinstance(error, (AgentExit, JobError)) else type(error).__name__


def say(message):
    print(message, flush=True)


def report_link(url):
    """The server's report_url rule (EngineEvents.parse): only such a link is printed."""
    try:
        parsed = urlparse(url) if isinstance(url, str) else None
        return bool(parsed and parsed.scheme == "https" and parsed.hostname in REPORT_HOSTS
                    and not parsed.username and not parsed.password and parsed.port in (None, 443))
    except ValueError:
        return False


class Agent:
    def __init__(self, server, token, data_dir, command, dry_run=False):
        # token: the claimed job's token (None until the claim); it and the code are never logged.
        self.server, self.token, self.data_dir = server.rstrip("/"), token, data_dir
        self.command, self.dry_run = command, dry_run
        self.secrets = ()
        self.outcome = None  # the engine's run_finished event
        self.stop = threading.Event()
        self.clock = time.monotonic  # the retry deadline's clock (tests inject a fake)
        self.cleanup_deadline = None
        self.closing = {}
        try:
            self.version = package_version("dss-backend")
        except PackageNotFoundError:
            self.version = "unknown"

    @classmethod
    def from_env(cls, server, dry_run=False):
        """No .env needed: DSS_DATA_DIR and DSS_ENGINE_CMD resolve from backend/ as the backend's do
        (env vars first, then the root .env if there is one, then the defaults), whatever the cwd."""
        server = (server or "").strip().rstrip("/")
        url = urlparse(server)
        if url.scheme not in ("http", "https") or not url.hostname:
            raise AgentExit("Pass --server <URL>: the hosted app's http(s) address", 2)
        if url.path or url.query or url.fragment:
            raise AgentExit("The server URL is the hosted app's base URL, without a path", 2)
        if url.scheme == "http" and url.hostname not in LOOPBACK:
            raise AgentExit("Use an https server URL: the job token must not cross the network in clear text", 2)
        return cls(server, None, Config.from_env().data_dir.resolve(), engine_command(), dry_run)

    def http(self):
        headers = {"X-DSS-Job-Token": self.token} if self.token else {}
        return httpx.Client(base_url=self.server, headers=headers,
                            timeout=httpx.Timeout(HTTP_TIMEOUT_S, connect=CONNECT_TIMEOUT_S))

    def call(self, http, method, path, *, retry=True, **kwargs):
        """One agent request; network errors, 429 and 5xx retry with backoff until RETRY_BUDGET_S after
        the first failure. Backoff and every later attempt, stalled I/O included, share that deadline."""
        deadline, delay, reason = None, BACKOFF_S, None
        while True:
            if self.cleanup_deadline is not None:
                raise self.expired("retry deadline expired", http)
            try:
                if deadline is None:
                    response = http.request(method, "/api/agent" + path, **kwargs)
                else:
                    response = self.attempt(http, method, path, deadline, reason, kwargs)
                if response.status_code < 500 and response.status_code != 429:
                    break
                reason = f"HTTP {response.status_code}"
            except httpx.TransportError as error:
                reason = type(error).__name__
            if not retry:
                raise AgentExit(f"Server unavailable ({reason})")
            deadline = deadline or self.clock() + RETRY_BUDGET_S
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise self.expired(reason, http)
            logger.warning("Server unavailable (%s); retrying in %.1f s", reason, min(delay, remaining))
            if self.stop.wait(min(delay, remaining)):
                raise Stopped()
            delay = min(delay * 2, BACKOFF_MAX_S)
        if response.status_code == 401:
            raise AgentExit("The server refused the agent (HTTP 401); check the server URL", 2)
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

    def expired(self, reason, http):
        if self.cleanup_deadline is None:
            self.cleanup_deadline = time.monotonic() + CLEANUP_S
        self.stop.set()
        self.close_http(http)
        return AgentExit(f"Server unavailable for {RETRY_BUDGET_S} s ({reason}); exiting")

    def remaining_cleanup(self):
        return max(0, self.cleanup_deadline - time.monotonic())

    def close_http(self, http):
        """Close once, off-thread: a transport close must never delay engine termination."""
        if http not in self.closing:
            done = threading.Event()
            self.closing[http] = done
            def close():
                try:
                    http.close()
                except Exception:
                    logger.warning("HTTP client cleanup failed")
                finally:
                    done.set()
            threading.Thread(target=close, name="dss-agent-close", daemon=True).start()
        return self.closing[http]

    def release(self, http):
        if self.cleanup_deadline is None:
            http.close()
        else:
            self.close_http(http).wait(self.remaining_cleanup())

    def attempt(self, http, method, path, deadline, reason, kwargs):
        """A retry ends by the deadline whatever the server does: none starts at or after it, and one
        that is still waiting then (connect, DNS or a trickling answer) is abandoned in its thread and
        the client closed, so its connection goes; the caller's AgentExit then stops any engine."""
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise self.expired(reason, http)
        timeout = httpx.Timeout(min(HTTP_TIMEOUT_S, remaining), connect=min(CONNECT_TIMEOUT_S, remaining))
        outcome, done = {}, threading.Event()
        def send():
            try:
                if self.clock() >= deadline or self.stop.is_set():
                    return
                outcome["response"] = http.request(method, "/api/agent" + path, timeout=timeout, **kwargs)
            except BaseException as error:  # handed to the caller's thread
                outcome["error"] = error
            finally:
                done.set()
        threading.Thread(target=send, name="dss-agent-retry", daemon=True).start()
        # Short waits keep Ctrl+C responsive on Windows.
        while not done.wait(max(0.0, min(.5, deadline - self.clock()))):
            if self.clock() >= deadline:
                raise self.expired("no answer in time", http)
            if self.stop.is_set():
                raise Stopped()
        if self.clock() >= deadline:
            raise self.expired("no answer in time", http)
        if self.stop.is_set():
            raise Stopped()
        if "error" in outcome:
            raise outcome["error"]
        return outcome["response"]

    def run(self, code):
        """Claim the job the code names, run it, report it; returns the exit code (the engine's when it ran)."""
        normalized = normalize_code(code) or ""
        self.secrets = tuple(secret for secret in {code, normalized, normalized.replace("-", "")} if secret)
        logger.info("dss-agent %s: server %s, jobs in %s%s", self.version, self.server,
                    self.data_dir / "agent", ", dry run" if self.dry_run else "")
        try:
            http = self.http()
            try:
                claimed = self.claim(http, code)
            finally:
                self.release(http)
            job = claimed.get("job")
            http = self.http()
            try:
                # Before the shape: another API version may name or shape a claim differently.
                if claimed.get("api_version") not in (None, API_VERSION):
                    # Best effort, so the build's ticket ends now instead of at the server's timeout.
                    if self.token and isinstance(job, dict) and RUN_ID.fullmatch(str(job.get("run_id"))):
                        self.report(http, job["run_id"], 2, "the build agent's API version differs", retry=False)
                    raise AgentExit(f"This agent speaks API {API_VERSION}, the server another version. {UPDATE}", 2)
                if not self.token or not isinstance(job, dict):
                    raise AgentExit("The server's answer is not a claimed job; check the server URL", 2)
                return self.run_job(http, job)
            finally:
                self.release(http)
        except Stopped:
            say("Stopped")
            return 1
        except AgentExit as error:
            say(str(error))
            return error.code
        finally:
            self.stop.set()

    def claim(self, http, code):
        try:
            response = self.call(http, "POST", "/claim", json={"code": code, "agent_version": self.version})
        except JobGone:
            raise AgentExit("The server does not take job codes; check the server URL", 2) from None
        except JobError as error:
            if str(error) == "job_code_invalid":
                raise AgentExit(CODE_INVALID) from None
            raise AgentExit(f"The server refused the code ({error})") from None
        try:
            claimed = response.json()
        except ValueError:
            claimed = None
        if not isinstance(claimed, dict):
            raise AgentExit("The server's answer is not a claimed job; check the server URL", 2)
        token = claimed.get("job_token")
        if isinstance(token, str) and token:
            self.secrets += (token,)
            if token.isascii() and token.isprintable():
                self.token = token  # else run() refuses the claim: an httpx header must be printable ASCII
        return claimed

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
        """The 5.3 job path for the one claimed job; returns the exit code."""
        run_id = job.get("run_id") if isinstance(job, dict) else None
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            say("The server sent a job without a valid run_id")
            return 2
        try:
            folder = self.folder(job)
        except ValueError as error:
            say(f"Job {run_id} is invalid ({error})")
            self.report(http, run_id, 2, "the build agent rejected an invalid job")
            return 2
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
            return 1
        except (JobError, OSError) as error:
            say(f"Job {run_id} could not run ({describe(error)})")
            self.report(http, run_id, 1, "the build agent could not run the job", folder)
            return 1
        except (KeyboardInterrupt, Stopped):
            self.report(http, run_id, 1, "the build agent stopped", folder, retry=False)
            raise
        if not self.report(http, run_id, code, tail, folder):
            return 1
        logger.info("Job %s finished (exit code %s)", run_id, code)
        self.summary(code, job)
        return code if code >= 0 else 1

    def summary(self, code, job):
        event = self.outcome or {}
        url, error = event.get("report_url"), event.get("error_code")
        if report_link(url):
            say(f"Report: {url}")
        elif code == 0:
            say("Dry run finished: no report was created" if self.dry_run or job["dry_run"]
                else "The build finished without a report link")
        if code != 0:
            reason = error if isinstance(error, str) and ERROR_CODE.fullmatch(error) else f"exit code {code}"
            say(f"The build failed ({reason})")

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
        say(f"Job {run_id} no longer exists on the server; stopped it and removed {folder}")

    def engine_args(self, job, folder):
        args = self.command + ["run", str(folder / "recipe.jsonl"), "--timeout", str(job["timeout_s"])]
        if self.dry_run or job["dry_run"]:
            args.append("--dry-run")
        return args + ["--screens", str(folder / "screens")]

    def run_engine(self, http, run_id, job, folder):
        """Stream one run's events in batches; a 404 or exit here stops the engine tree."""
        process = start_engine(self.engine_args(job, folder), cwd=BACKEND_DIR, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
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
            # Native job/group termination has no command-launch or socket timeout. It also
            # kills inherited-pipe descendants whose wrapper has already exited.
            terminate_tree(process)
            cleanup_deadline = self.cleanup_deadline or time.monotonic() + 5
            cleaned = threading.Event()
            def cleanup():
                try:
                    process.wait(timeout=max(0, cleanup_deadline - time.monotonic()))
                    for reader in readers:
                        reader.join(timeout=max(0, cleanup_deadline - time.monotonic()))
                    process.stdout.close()
                    process.stderr.close()
                except Exception:
                    logger.warning("Engine cleanup failed")
                finally:
                    if owned := getattr(process, "_dss_job", None):
                        owned.close()
                    cleaned.set()
            threading.Thread(target=cleanup, name="dss-agent-engine-cleanup", daemon=True).start()
            if not cleaned.wait(max(0, cleanup_deadline - time.monotonic())):
                logger.warning("Engine pipe cleanup did not finish in time")
            if self.cleanup_deadline is not None:
                self.close_http(http).wait(self.remaining_cleanup())
        return (-1 if expired.is_set() else code), self.redact("".join(tail))[-STDERR_TAIL:]

    def event(self, line):
        try:
            value = json.loads(line)
        except ValueError:
            return None
        if not isinstance(value, dict):
            return None
        value = self.redact(value)
        if value.get("event") == "run_finished":
            self.outcome = value
        return value

    def redact(self, value):
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[redacted]")
            return value
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


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse would echo the offending values, which may be the job code.
        say(USAGE)
        raise SystemExit(2)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(levelname)s backend.agent: %(message)s")
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    parser = Parser(prog="dss-agent", usage=USAGE.removeprefix("usage: "),
                    description="Run one hosted build on this machine's engine.")
    commands = parser.add_subparsers(dest="command")
    run = commands.add_parser("run", usage=USAGE.removeprefix("usage: "),
                              help="claim the job a code names, run it and exit")
    run.add_argument("--server", required=True, help="the hosted app's URL")
    run.add_argument("--job", required=True, help="the code the Build stage shows")
    run.add_argument("--dry-run", action="store_true", help="add --dry-run to the engine run (rehearsals)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return error.code
    if args.command != "run":
        say(USAGE)  # the bare form was the retired polling agent
        return 2
    try:
        agent = Agent.from_env(args.server, args.dry_run)
    except AgentExit as error:
        say(str(error))
        return error.code
    try:
        return agent.run(args.job)
    except KeyboardInterrupt:
        say("Stopped")
        return 130


if __name__ == "__main__":
    sys.exit(main())
