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


async def execute(state, build_id, run_id, folder, version):
    env = environment()
    timeout = int(env.get("DSS_ENGINE_TIMEOUT_S") or 600)
    secrets = tuple(filter(None, (state.settings.get().google_api_key.get_secret_value(), env.get("DSS_ACCESS_CODE"), env.get("DSS_AGENT_TOKEN"))))
    def redact(value):
        if isinstance(value, str):
            for secret in secrets:
                value = value.replace(secret, "[redacted]")
            return value
        if isinstance(value, dict):
            return {key: redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value
    args = engine_command() + ["run", str(folder / "recipe.jsonl"), "--screens", str(folder / "screens"), "--timeout", str(timeout)]
    if env.get("DSS_ENGINE_DRY_RUN") == "1":
        args.append("--dry-run")
    loop = asyncio.get_running_loop()
    cancelled = threading.Event()
    processes = []
    failure = []
    def worker():
        result = None
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
            with (folder / "events.jsonl").open("w", encoding="utf-8") as log:
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(event, dict):
                        continue
                    # Drop unexpected text and redact credentials before persisting or emitting.
                    event = redact(event)
                    log.write(json.dumps(event) + "\n")
                    log.flush()
                    if event.get("event") == "op_finished":
                        asyncio.run_coroutine_threadsafe(state.harness.emit(build_id, run_id, "build.op", event), loop).result()
                    elif event.get("event") == "run_finished":
                        result = event
            code = process.wait()
            if code == 3:
                failure.append(RunError("engine_not_signed_in", "Sign in to Data Studio before building", 424))
            if expired.is_set() or code != 0 or not result or result.get("status") not in ("ok", "partial"):
                return {"status": "failed", "report_url": None}
            url = result.get("report_url")
            if url and (urlparse(url).scheme != "https" or urlparse(url).hostname not in ("datastudio.google.com", "lookerstudio.google.com")):
                failure.append(RunError("invalid_report_url", "Engine returned an invalid report URL", 422))
                return {"status": "failed", "report_url": None}
            return {"status": result["status"], "report_url": url}
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
    if failure:
        raise failure[0]
    return json.dumps(result)
