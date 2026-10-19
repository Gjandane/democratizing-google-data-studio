"""Local engine invocation: Popen and pipe reads live in worker threads."""
import asyncio
import json
import os
import shlex
import subprocess
import signal
import threading
from urllib.parse import urlparse

from dotenv import dotenv_values
from dss.config import BACKEND_DIR
from dss.harness.guardrails import RunError
from dss.harness.nodes.publish import publish


def environment():
    return {**dotenv_values(BACKEND_DIR.parent / ".env"), **os.environ}


def engine_command():
    # Windows Popen needs unquoted individual arguments, including executable paths.
    args = shlex.split(environment().get("DSS_ENGINE_CMD") or "uv run --project ../engine dsengine", posix=os.name != "nt")
    return [arg[1:-1] if len(arg) > 1 and arg[0] == arg[-1] and arg[0] in ('"', "'") else arg for arg in args]


def terminate_tree(process):
    """Stop the wrapper and engine together so inherited pipes reach EOF."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()


class EngineEvents:
    """The shared engine stdout/agent event parser and credential boundary."""

    def __init__(self, state, folder):
        config = state.settings.get()
        env = environment()
        self.secrets = tuple(filter(None, (config.google_api_key.get_secret_value(),
            config.access_code.get_secret_value(), config.agent_token.get_secret_value(),
            env.get("DSS_ACCESS_CODE"), env.get("DSS_AGENT_TOKEN"))))
        self.path = folder / "events.jsonl"
        self.path.write_text("", encoding="utf-8")
        self.result = None
        self.failure = None

    def redact(self, value):
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[redacted]")
        elif isinstance(value, dict):
            value = {self.redact(key): self.redact(item) for key, item in value.items()}
        elif isinstance(value, list):
            value = [self.redact(item) for item in value]
        return value

    def parse(self, line):
        try:
            event = json.loads(line) if isinstance(line, str) else line
        except (ValueError, TypeError):
            return None
        if not isinstance(event, dict):
            return None
        # Validate before either the raw event or its URL can reach disk or SSE.
        def check_urls(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "report_url" and item is not None:
                        try:
                            url = urlparse(item) if isinstance(item, str) else None
                            valid = (url and url.scheme == "https" and url.hostname in
                                ("datastudio.google.com", "lookerstudio.google.com")
                                and not url.username and not url.password and url.port in (None, 443))
                        except ValueError:
                            valid = False
                        if not valid:
                            self.failure = RunError("invalid_report_url", "Engine returned an invalid report URL", 422)
                            raise self.failure
                    check_urls(item)
            elif isinstance(value, list):
                for item in value:
                    check_urls(item)
        check_urls(event)
        event = self.redact(event)
        with self.path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(event) + "\n")
        if event.get("event") == "run_finished":
            self.result = event
        return event

    def outcome(self, exit_code):
        if exit_code == 3 and self.failure is None:
            self.failure = RunError("engine_not_signed_in", "Sign in to Data Studio before building", 424)
        if self.failure or exit_code != 0 or not self.result or self.result.get("status") not in ("ok", "partial"):
            return {"status": "failed", "report_url": None}
        return {"status": self.result["status"], "report_url": self.result.get("report_url")}


async def execute(state, build_id, run_id, folder, version):
    if state.config.engine_mode == "agent":
        return await state.agent_jobs.execute(run_id)
    env = environment()
    timeout = int(env.get("DSS_ENGINE_TIMEOUT_S") or 600)
    parser = EngineEvents(state, folder)
    args = engine_command() + ["run", str(folder / "recipe.jsonl"), "--screens", str(folder / "screens"), "--timeout", str(timeout)]
    if env.get("DSS_ENGINE_DRY_RUN") == "1":
        args.append("--dry-run")
    loop = asyncio.get_running_loop()
    cancelled = threading.Event()
    processes = []
    def worker():
        process = subprocess.Popen(args, cwd=BACKEND_DIR, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", start_new_session=os.name != "nt")
        processes.append(process)
        expired = threading.Event()
        def kill():
            expired.set()
            terminate_tree(process)
        if cancelled.is_set():
            kill()
        timer = threading.Timer(timeout + 5, kill)
        timer.start()
        try:
            for line in process.stdout:
                event = parser.parse(line)
                if event and event.get("event") == "op_finished":
                    asyncio.run_coroutine_threadsafe(state.harness.emit(build_id, run_id, "build.op", event), loop).result()
            code = process.wait()
            return parser.outcome(-1 if expired.is_set() else code)
        finally:
            timer.cancel()
            if process.poll() is None:
                terminate_tree(process)
            process.wait()
            process.stdout.close()
    work = asyncio.create_task(asyncio.to_thread(worker))
    was_cancelled = False
    try:
        result = await asyncio.shield(work)
    except asyncio.CancelledError:
        was_cancelled = True
        cancelled.set()
        if processes:
            await asyncio.to_thread(terminate_tree, processes[0])
        await work
        result = {"status": "failed", "report_url": None}
    except Exception:
        result = {"status": "failed", "report_url": None}
    await publish(state, build_id, run_id, version, result)
    if was_cancelled:
        raise asyncio.CancelledError
    if parser.failure:
        raise parser.failure
    return json.dumps(result)
