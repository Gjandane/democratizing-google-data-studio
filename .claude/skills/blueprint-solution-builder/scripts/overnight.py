#!/usr/bin/env python3
"""overnight.py - build docs/plan.md task after task while nobody watches.

Each task runs in its own fresh headless session (`claude -p`, or `codex exec`) of the
blueprint-solution-builder skill in `headless` mode. So every task starts from a clean context
built from the docs, exactly as if you typed /clear and the command yourself. The runner picks
the model and effort for each task's tier (references/models.md), and stops at the first thing
that needs a person.

Run it from the project root (the folder that holds docs/plan.md):

    python overnight.py --dry-run              show the next task, its model and the command
    python overnight.py                        Claude Code, up to 8 tasks
    python overnight.py --until 07:00 --max-tasks 12
    python overnight.py --tool codex           drive Codex instead (Codex models per tier)

It stops when every task is done, or before a task with a STOP: field, a Size: L task (unless
--include-l), or a `STOP` warning from `status`. It also stops when a task is blocked, when a task
ends unfinished in two sessions, when a session ends with no new progress entry or leaves
uncommitted changes, and when --max-tasks or --until is reached.

Sessions run with --permission-mode auto and --permission-prompts none: anything that would ask
for permission is denied, and the builder blocks the task instead of waiting. Each session also
gets a dollar cap and a timeout. The runner keeps a Windows PC awake while it runs (on a laptop,
set closing the lid to do nothing). Work stays local: the builder commits each task, nothing is
pushed. Logs and a summary go to .blueprint/overnight/<run>/.

Exit codes: 0 all done or a limit reached, 1 stopped on something that needs you, 2 setup error.
Standard library only; it imports blueprint.py from its own folder.
"""

import argparse
import datetime
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import blueprint as bp  # noqa: E402  (same folder; v2.3 or later)

SKILL = "blueprint-solution-builder"
HEADLESS_RULES = HERE.parent / "references" / "headless.md"
CODEX_SKILL = Path.home() / ".agents" / "skills" / SKILL
LOG_DIR = Path(bp.STATE_DIR) / "overnight"

# references/models.md, "The session": the model and effort for each tier.
ROUTES = {
    "deep": ("opus", "high"),
    "routine M": ("opus", "medium"),  # the session plans it and a Sonnet worker types it out
    "routine S": ("sonnet", "medium"),
}
# The Codex copies' references/models.md, "The session". "low" is the app's "Light".
CODEX_ROUTES = {
    "frontier": ("gpt-6-astra", "high"),
    "deep": ("gpt-6.1-sol", "high"),
    "routine": ("gpt-6.1-sol", "low"),
}
# Set by a Claude Code session in the shells it starts; a child session must not inherit them.
SESSION_VARS = (
    "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_JOB_DIR", "CLAUDE_CODE_BRIDGE_SESSION_ID",
    "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
)
# User settings that silently override the per-tier routing.
ROUTING_OVERRIDES = ("CLAUDE_CODE_EFFORT_LEVEL", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE")
RESULT_RE = re.compile(r"HEADLESS RESULT:\s*(?P<line>.+)")
MAX_SESSIONS_PER_TASK = 2  # the builder blocks a task whose second session fails too


class Stop(Exception):
    """Ends the run. `code` is the exit code: 0 done or a limit, 1 needs you, 2 setup error."""

    def __init__(self, reason, code=1, next_step=""):
        super().__init__(reason)
        self.reason, self.code, self.next_step = reason, code, next_step


# ---------- the plan

def plan_state(root):
    try:
        _, tasks, _, header = bp.load_plan(root)
    except SystemExit:
        raise Stop("no docs/plan.md here. Run the runner from the project root, or pass --root.",
                   2)
    return tasks, header


def size_of(task):
    return (task.fields.get("size", "").strip()[:1] or "M").upper()


def tier_of(task):
    """references/models.md, "Tiers": deep if it has a Spec or a STOP, is Size L, or is 1.1."""
    deep = task.spec_refs or task.fields.get("stop") or size_of(task) == "L" or task.id == "1.1"
    return "deep" if deep else f"routine {'S' if size_of(task) == 'S' else 'M'}"


def codex_tier_of(task):
    """The Codex models.md, "Tiers": frontier is a Spec with a STOP or Size L; then as above."""
    tier = tier_of(task)
    if tier != "deep":
        return "routine"
    frontier = task.spec_refs and (task.fields.get("stop") or size_of(task) == "L")
    return "frontier" if frontier else "deep"


def tier_for(args, task):
    return codex_tier_of(task) if args.tool == "codex" else tier_of(task)


def entry_count(root, tid):
    return len(bp.task_entries(bp.parse_progress(bp.load(root, bp.PROGRESS) or ""), tid))


def status_warnings(root, tid):
    """The warnings `status --task ID` prints: the same ones the builder session will see."""
    out = subprocess.run([sys.executable, str(HERE / "blueprint.py"), "--root", root, "status",
                          "--task", tid], capture_output=True, text=True, encoding="utf-8",
                         errors="replace").stdout
    tail = out.split("=== WARNINGS ===")[-1]
    return [l[2:].strip() for l in tail.splitlines() if l.startswith("- ")]


def next_task(root, args, sessions):
    """The next task the runner may hand to a session, or Stop."""
    tasks, header = plan_state(root)
    if not tasks:
        raise Stop("docs/plan.md has no tasks.", 2)
    if all(t.mark == "x" for t in tasks):
        raise Stop("ALL TASKS DONE.", 0, f"Run /blueprint-solution-architect for the final "
                                         f"audit.")
    waits = []
    task, _ = bp.pick_next(tasks, root=root, waits=waits)
    if task is None:
        held = "; ".join(f"{t.id} needs {', '.join(u)}" for t, u in waits)
        blocked = [t.id for t in tasks if t.mark == "!"]
        raise Stop("no task is ready: " + (held or "the rest wait on " + (
            f"blocked task(s) {', '.join(blocked)}" if blocked else "unfinished tasks")) + ".",
            1, "Resolve blocked tasks with /blueprint-solution-architect.")
    if task.fields.get("stop"):
        raise Stop(f"task {task.id} has a STOP point for you: {task.fields['stop']}", 1,
                   f"Build it supervised: /blueprint-solution-builder {task.id}")
    if size_of(task) == "L" and not args.include_l:
        raise Stop(f"task {task.id} is Size L, which runs supervised.", 1,
                   f"Build it supervised (/blueprint-solution-builder {task.id}), or rerun "
                   f"with --include-l.")
    if sessions.get(task.id, 0) >= MAX_SESSIONS_PER_TASK:
        raise Stop(f"task {task.id} ended unfinished in {sessions[task.id]} sessions tonight.",
                   1, "Read its partial entries in docs/progress.md, then "
                      "/blueprint-solution-builder or /blueprint-solution-architect.")
    for w in status_warnings(root, task.id):
        if w.startswith("STOP") or w.startswith("lint:") or "change request" in w:
            raise Stop(f"status warns before task {task.id}: {w}", 1)
    return task


# ---------- the sessions

def version_key(path):
    m = re.search(r"claude-code[\\/](\d+(?:\.\d+)*)", path)
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


def find_tool(args):
    if args.tool == "claude":
        found = args.claude or shutil.which("claude")
        if not found and os.environ.get("APPDATA"):  # the copy the Claude desktop app installs
            hits = glob.glob(os.path.join(os.environ["APPDATA"], "Claude", "claude-code", "*", "*",
                                          "claude.exe"))
            found = max(hits, key=version_key) if hits else None
    else:
        found = args.codex or shutil.which("codex")
        if not found and os.environ.get("LOCALAPPDATA"):
            exe = Path(os.environ["LOCALAPPDATA"]) / "OpenAI" / "Codex" / "bin" / "codex.exe"
            found = str(exe) if exe.is_file() else None
    if not found:
        raise Stop(f"can't find the {args.tool} CLI. Put it on PATH or pass --{args.tool} PATH.", 2)
    return found


def session_command(args, exe, root, task, last_msg):
    """(argv, stdin text, model label) for one headless session of this task."""
    if args.tool == "claude":
        model, effort = (args.model, args.effort or "high") if args.model else ROUTES[tier_of(task)]
        argv = [exe, "-p", f"/{SKILL} {task.id} headless", "--model", model, "--effort", effort,
                "--permission-mode", args.permission_mode, "--permission-prompts", "none",
                "--output-format", "json"]
        if args.task_budget_usd:
            argv += ["--max-budget-usd", str(args.task_budget_usd)]
        return argv, None, f"{model}/{effort}"
    # Codex reads the prompt from stdin ("-"): the headless rules go inline, because the Codex
    # copy of the skill has no references/headless.md.
    prompt = (f"${SKILL} {task.id} headless\n\nHeadless rules (they replace every question the "
              f"skill would ask):\n\n" + HEADLESS_RULES.read_text(encoding="utf-8"))
    model, effort = ((args.codex_model, args.codex_effort or "high") if args.codex_model
                     else CODEX_ROUTES[codex_tier_of(task)])
    argv = [exe, "exec", "-C", root, "-s", "workspace-write", "-c", 'approval_policy="never"',
            "-m", model, "-c", f'model_reasoning_effort="{effort}"', "-o", str(last_msg)]
    if args.codex_network:
        argv += ["-c", "sandbox_workspace_write.network_access=true"]
    if not bp.is_git(root):
        argv.append("--skip-git-repo-check")
    return argv + ["-"], prompt, f"{model}/{effort}"


def child_env():
    env = {k: v for k, v in os.environ.items() if k not in SESSION_VARS}
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def kill_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":  # the session's own children (test runners, dev servers) go too
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        os.killpg(proc.pid, signal.SIGTERM)


def run_session(argv, stdin_text, root, out_path, err_path, timeout_s):
    """Runs one session; returns (exit code or None on timeout, minutes)."""
    started = time.monotonic()
    extra = {"start_new_session": True} if os.name != "nt" else {}
    with open(out_path, "wb") as out, open(err_path, "wb") as err:
        proc = subprocess.Popen(argv, cwd=root, env=child_env(), stdout=out, stderr=err,
                                stdin=subprocess.PIPE if stdin_text else subprocess.DEVNULL,
                                **extra)
        try:
            if stdin_text:
                proc.stdin.write(stdin_text.encode("utf-8"))
                proc.stdin.close()
            code = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            code = None
        except BaseException:
            kill_tree(proc)
            raise
    return code, (time.monotonic() - started) / 60


def read_report(tool, out_path, last_msg):
    """(the HEADLESS RESULT line or a fallback, cost in USD or None) from a session's output."""
    text, cost = "", None
    raw = out_path.read_text(encoding="utf-8", errors="replace") if out_path.exists() else ""
    if tool == "claude":
        data = None
        for candidate in (raw.strip(), (raw.strip().splitlines() or [""])[-1]):
            try:
                data = json.loads(candidate)
                break
            except ValueError:
                continue
        if isinstance(data, dict):
            text, cost = data.get("result") or "", data.get("total_cost_usd")
            if data.get("is_error") and not text:
                text = f"session error: {data.get('subtype', 'unknown')}"
        else:
            text = raw
    else:
        text = last_msg.read_text(encoding="utf-8", errors="replace") if last_msg.exists() else raw
    found = RESULT_RE.findall(text)
    if found:
        return found[-1].strip(), cost
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return (lines[-1][:200] if lines else "(no output)"), cost


# ---------- the run

def keep_awake(on):
    if os.name != "nt":
        return
    import ctypes
    es_continuous, es_system_required = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(
        es_continuous | (es_system_required if on else 0))


def deadline_from(hhmm):
    if not hhmm:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", hhmm)
    if not m:
        raise Stop(f"--until wants HH:MM, got {hhmm!r}", 2)
    now = datetime.datetime.now()
    at = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    return at if at > now else at + datetime.timedelta(days=1)


def commit_line(root):
    if not bp.has_head(root):
        return ""
    _, out, _ = bp.git(root, "log", "-1", "--format=%h %s")
    return out.strip()


def write_summary(path, args, rows, stop=None):
    lines = [f"# Overnight run {path.parent.name}", "",
             f"Tool: {args.tool} · permission mode: {args.permission_mode} · max tasks: "
             f"{args.max_tasks}" + (f" · until {args.until}" if args.until else ""), "",
             "| # | Task | Tier | Model | Result | Minutes | Cost | Commit |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        cost = f"${r['cost']:.2f}" if isinstance(r.get("cost"), (int, float)) else "-"
        lines.append(f"| {r['n']} | {r['id']} {r['title']} | {r['tier']} | {r['model']} | "
                     f"{r['result']} | {r['minutes']:.0f} | {cost} | {r['commit']} |")
    if stop:
        lines += ["", f"**Stopped:** {stop.reason}"]
        if stop.next_step:
            lines.append(f"**Next:** {stop.next_step}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def say(msg):
    print(f"[{datetime.datetime.now():%H:%M}] {msg}", flush=True)


def preflight(root, args):
    exe = find_tool(args)
    if args.tool == "claude" and not HEADLESS_RULES.is_file():
        raise Stop(f"{HEADLESS_RULES} is missing: this builder skill has no headless mode.", 2)
    if args.tool == "codex" and not CODEX_SKILL.is_dir():
        raise Stop(f"the Codex builder skill isn't at {CODEX_SKILL}.", 2)
    for var in ROUTING_OVERRIDES:
        if os.environ.get(var):
            say(f"note: {var}={os.environ[var]} overrides the per-task model or effort.")
    return exe


def build_loop(root, args, exe, run_dir, rows):
    deadline = deadline_from(args.until)
    sessions = {}
    for n in range(1, args.max_tasks + 1):
        if deadline and datetime.datetime.now() >= deadline:
            raise Stop(f"reached --until {args.until}.", 0)
        task = next_task(root, args, sessions)
        tier = tier_for(args, task)
        base = run_dir / f"{n:02d}-{task.id}"
        last_msg = base.with_suffix(".last.txt")
        argv, stdin_text, model = session_command(args, exe, root, task, last_msg)
        if args.dry_run:
            say(f"next: task {task.id} {task.title} [{tier}] on {model}")
            say("command: " + subprocess.list2cmdline(argv))
            raise Stop("dry run: nothing was started.", 0)

        before = entry_count(root, task.id)
        say(f"task {task.id} {task.title} [{tier}] on {model}: started")
        code, minutes = run_session(argv, stdin_text, root, base.with_suffix(".out"),
                                    base.with_suffix(".err"), args.task_timeout_min * 60)
        report, cost = read_report(args.tool, base.with_suffix(".out"), last_msg)
        sessions[task.id] = sessions.get(task.id, 0) + 1

        tasks, _ = plan_state(root)
        mark = next((t.mark for t in tasks if t.id == task.id), "?")
        new_entry = entry_count(root, task.id) > before
        result = {"x": "done", "!": "blocked", "~": "partial" if new_entry else "unfinished",
                  " ": "not started"}.get(mark, "missing")
        if code is None:
            result += f" (timed out after {args.task_timeout_min} min)"
        rows.append({"n": n, "id": task.id, "title": task.title, "tier": tier, "model": model,
                     "result": result, "minutes": minutes, "cost": cost,
                     "commit": commit_line(root) if bp.is_git(root) else "folder checkpoint"})
        write_summary(run_dir / "summary.md", args, rows)
        say(f"task {task.id}: {result} in {minutes:.0f} min. {report}")

        if mark == "!":
            raise Stop(f"task {task.id} is blocked: {report}", 1,
                       "Resolve it with /blueprint-solution-architect, then rerun the runner.")
        if mark == " ":
            raise Stop(f"the session for task {task.id} stopped before starting it: {report}", 1)
        if mark == "~" and not new_entry:
            raise Stop(f"the session for task {task.id} ended without a progress entry "
                       f"(exit {code}): {report}", 1,
                       f"Check {base.with_suffix('.err')}, then /blueprint-solution-builder "
                       f"resumes the task.")
        if bp.is_git(root) and bp.dirty_lines(root):
            raise Stop(f"task {task.id}'s session left uncommitted changes.", 1,
                       "Look at git status, then /blueprint-solution-builder.")
    raise Stop(f"reached --max-tasks {args.max_tasks}.", 0)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="project root (default: current folder)")
    ap.add_argument("--tool", choices=("claude", "codex"), default="claude")
    ap.add_argument("--max-tasks", type=int, default=8, help="sessions to run at most (default 8)")
    ap.add_argument("--until", metavar="HH:MM", help="start no task after this local time")
    ap.add_argument("--include-l", action="store_true", help="run Size: L tasks too")
    ap.add_argument("--task-timeout-min", type=int, default=120,
                    help="minutes before a session is stopped (default 120)")
    ap.add_argument("--task-budget-usd", type=float, default=15.0,
                    help="claude: dollar cap per session (default 15; 0 for none)")
    ap.add_argument("--permission-mode", choices=("auto", "acceptEdits", "dontAsk"),
                    default="auto", help="claude: permission mode; prompts are always denied")
    ap.add_argument("--model", help="claude: one model for every task instead of per tier")
    ap.add_argument("--effort", help="claude: the effort that goes with --model (default high)")
    ap.add_argument("--claude", metavar="PATH", help="the claude CLI, if not on PATH")
    ap.add_argument("--codex", metavar="PATH", help="the codex CLI, if not on PATH")
    ap.add_argument("--codex-model", help="codex: one model for every task instead of per tier")
    ap.add_argument("--codex-effort",
                    help="codex: the effort that goes with --codex-model (default high)")
    ap.add_argument("--codex-network", action="store_true",
                    help="codex: allow network access in the sandbox (installs, live tests)")
    ap.add_argument("--dry-run", action="store_true", help="show the next session; run nothing")
    args = ap.parse_args()
    root = str(Path(args.root).resolve())

    rows, run_dir = [], None
    try:
        exe = preflight(root, args)
        plan_state(root)
        if not args.dry_run:
            run_dir = Path(root) / LOG_DIR / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            run_dir.mkdir(parents=True)
            ignore = Path(root) / bp.STATE_DIR / ".gitignore"
            if not ignore.exists():  # keeps the logs out of git status, so tasks start clean
                ignore.write_text("*\n", encoding="utf-8")
            keep_awake(True)
            say(f"run logs: {run_dir}")
        build_loop(root, args, exe, run_dir or Path(root), rows)
    except Stop as stop:
        if run_dir:
            write_summary(run_dir / "summary.md", args, rows, stop)
        say(f"stopped: {stop.reason}")
        if stop.next_step:
            say(f"next: {stop.next_step}")
        if run_dir:
            say(f"summary: {run_dir / 'summary.md'}")
        return stop.code
    except KeyboardInterrupt:
        stop = Stop("interrupted (Ctrl+C); the current task's session was stopped.", 1,
                    "/blueprint-solution-builder resumes the task.")
        if run_dir:
            write_summary(run_dir / "summary.md", args, rows, stop)
        say(stop.reason)
        return 1
    finally:
        keep_awake(False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
