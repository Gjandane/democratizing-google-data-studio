#!/usr/bin/env python3
"""blueprint.py v2.6 - task status, checks and checkpoints for the blueprint-solution skills.

One file for both tools: the same copy ships in the architect and builder skills of Claude Code
(~/.claude/skills/) and of Codex (~/.agents/skills/); keep all four copies identical. It names
the skills the way the tool running it expects (/name in Claude Code, $name in Codex), and both
tools read and write exactly the same files, so a build started in either can continue in the
other. v2.2 adds versions (`archive`), connected parts (`Needs:` gates and `program`), and keeps
projects nested inside this folder out of its checks and checkpoints. v2.3 adds the `Spec:` task
field (status prints the doc sections it names, lint checks they exist) and shows the Decisions
of the tasks a task builds on indirectly, not only of its direct dependencies. v2.4 has lint warn
when a project outgrows one plan (too many tasks, or too long a PRD). v2.5 tracks an interview
that spans sessions: `status` and `program` list the `- Round:` lines a draft PRD or program.md
still holds, and lint reports any left once the plan exists. v2.6 keeps a build session's reading
flat as a project grows: each done entry carries a one-line `Digest:` (at most 280 bytes, which
`done` checks), `status` shows a direct dependency's entry cut to what a later task needs and the
tasks further back as digests within a fixed budget, and `recall` fetches anything else on demand
(a task, a doc section, or the lines matching a regex) instead of a whole doc.

Run it from the project root (the folder that holds AGENTS.md, CLAUDE.md and docs/):

    python blueprint.py status [--task ID]       next task + everything a build session must read
    python blueprint.py start ID [--owner NAME]  mark [~] and take a checkpoint
    python blueprint.py diff [ID]                what changed since the task's checkpoint
    python blueprint.py restore ID               undo a failed attempt (recoverable, never deletes)
    python blueprint.py done ID                  mark [x]; needs a "Status: done" entry in progress.md
    python blueprint.py block ID                 mark [!]; needs a "Status: blocked" entry
    python blueprint.py reopen ID                mark [ ] again (architect, after a ruling or audit)
    python blueprint.py lint                     check the planning docs against the spec
    python blueprint.py deps [--write]           look dependencies up on npm / PyPI
    python blueprint.py stamp                    record which architecture.md the essentials match
    python blueprint.py retro                    metrics for a post-project retrospective
    python blueprint.py archive LABEL [--to DIR] close a version: its docs go to docs/archive/LABEL/
    python blueprint.py program                  every part of the program this folder belongs to
    python blueprint.py recall QUERY             a task ID, a doc (outline), path#Heading, or a regex

Works in a git repo (checkpoint = last commit) or a plain folder (checkpoint = a zip snapshot in
.blueprint/). Standard library only. Exit codes: 0 ok, 1 problems found, 2 usage error.
"""

import argparse
import datetime
import difflib
import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

PLAN = "docs/plan.md"
PROGRESS = "docs/progress.md"
PRD = "docs/PRD.md"
ARCH = "docs/architecture.md"
ESSENTIALS = "docs/architecture-essentials.md"
RETRO_DOC = "docs/retro.md"
PROGRAM = "docs/program.md"  # at a program root: the parts, their folders, contracts and gates
ARCHIVE = "docs/archive"  # closed versions: docs/archive/<label>/ holds that version's docs
ARCHIVED = (PRD, ARCH, ESSENTIALS, PLAN, PROGRESS, RETRO_DOC)  # what `archive` moves
AGENTS = "AGENTS.md"
CLAUDE_FILES = ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md")  # stop Claude reading AGENTS.md
STATE_DIR = ".blueprint"
WORKTREES = ".claude/worktrees"  # Claude Code session worktrees, at the repo root: never "dirty"
VERSION = "2.6"
IN_CLAUDE = os.environ.get("CLAUDECODE") == "1"  # set in the shells Claude Code starts

# Bookkeeping files survive a restore: the failure record and the markers must not be undone.
BOOKKEEPING = {PLAN, PROGRESS}
EXCLUDE_DIRS = {
    ".git", STATE_DIR, "node_modules", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", "dist", "build", ".next", ".nuxt", "target", ".gradle",
    ".idea", "coverage", ".cache", ".parcel-cache", ".turbo", ".svelte-kit",
}
MAX_SNAPSHOT_FILE = 5 * 1024 * 1024
MAX_DIFF_NEW_FILE = 256 * 1024  # a new file bigger than this gets a one-line note in `diff`
TARGETS = ("poc", "mvp", "production")
REQUIRED_FIELDS = ("goal", "files", "depends on", "done when")
KNOWN_FIELDS = set(REQUIRED_FIELDS) | {"size", "review focus", "if", "stop", "needs", "spec"}
MAX_SPEC = 8000  # chars of Spec sections status prints for one task before lint warns
MAX_INDIRECT = 12  # indirect dependencies whose Decisions status prints
MAX_TASKS = 20  # tasks in one plan before lint suggests splitting into parts or a new version
MAX_PRD = 15000  # chars of PRD before lint suggests the same
MAX_DIGEST = 280  # bytes in a done entry's 'Digest:' line: one line, as dense as an OptMem note
HISTORY_BUDGET = 4000  # chars of older tasks' records status prints past the direct dependencies
RECALL_CHARS = 12000  # chars recall prints before it asks for a narrower query
RECALL_LINE = 400  # chars of one matching line recall prints
CONDENSED = ("what changed", "decisions", "gotchas")  # a direct dependency's entry, in status

TASK_RE = re.compile(r"^- \[(?P<mark>[ ~xX!])\] (?P<id>\d+\.\d+)(?P<title>.*)$")
LOOSE_TASK_RE = re.compile(r"^[-*]\s*\[[^\]]{0,2}\]")  # column 0 only; nested checklists are fine
TASK_FIELD_RE = re.compile(r"^\s+[-*]\s*(?P<key>[A-Za-z][A-Za-z ]*?)\s*:\s*(?P<val>.*)$")
ENTRY_FIELD_RE = re.compile(r"^[-*]\s*(?P<key>[A-Za-z][A-Za-z ]*?)\s*:\s*(?P<val>.*)$")
ENTRY_RE = re.compile(r"^## (?P<date>\d{4}-\d{2}-\d{2})\s*:?\s*(?P<rest>.*)$")
HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
OWNER_RE = re.compile(r"\s*\(@[^)]*\)\s*$")
TASK_ID_RE = re.compile(r"\b\d+\.\d+\b")
ESS_MARKER_RE = re.compile(r"^<!-- essentials-of:.*-->[ \t]*\n?", re.M)
BLOCK_RE = re.compile(r"<!--\s*blueprint-solution:start.*?<!--\s*blueprint-solution:end\s*-->", re.S)
NEED_RE = re.compile(r"(?P<part>[A-Za-z][\w-]*)\s+(?P<id>\d+\.\d+)")  # one "Needs:" item: api 2.3
LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")  # a version label: v1, phase-1, 2026.1
ROUND_RE = re.compile(r"^[-*]\s*Round\s*:\s*(?P<round>.+?)\s*$", re.I)  # an interview round left

_META = {}  # path -> (had_bom, crlf), so rewrites keep the file's own conventions


# ----------------------------------------------------------------------------- file helpers

def load(root, rel):
    path = Path(root) / rel
    if not path.is_file():
        return None
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    _META[str(path.resolve())] = (bom, b"\r\n" in raw)
    text = raw.decode("utf-8-sig", errors="replace")
    return text.replace("\r\n", "\n")


def save(root, rel, text):
    path = Path(root) / rel
    bom, crlf = _META.get(str(path.resolve()), (False, False))
    if crlf:
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    data = text.encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)


def die(msg, code=1):
    print(f"ERROR: {msg}")
    sys.exit(code)


def skill(role):
    """How to invoke a blueprint-solution skill in the tool running this script."""
    return f"{'/' if IN_CLAUDE else '$'}blueprint-solution-{role}"


def effort_note():
    """The effort in force when Claude Code runs this script through its Bash tool (which sets
    CLAUDE_EFFORT), so a session can see whether a skill's effort setting still holds."""
    effort = os.environ.get("CLAUDE_EFFORT", "")
    return f"  (effort: {effort})" if effort else ""


def id_key(task_id):
    return tuple(int(p) for p in task_id.split("."))


def shown(path, base):
    """`path` for messages: relative to `base` with forward slashes, or absolute when it is on
    another drive."""
    try:
        return Path(os.path.relpath(Path(path), Path(base))).as_posix()
    except ValueError:
        return Path(path).as_posix()


def section(text, pattern):
    """Return the heading matching `pattern` plus its body, up to the next heading of the
    same or a higher level; None if absent."""
    if not text:
        return None
    lines = text.split("\n")
    rx = re.compile(pattern, re.I)
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m and rx.search(m.group("title")):
            level = len(m.group("hashes"))
            end = len(lines)
            for j in range(i + 1, len(lines)):
                n = HEADING_RE.match(lines[j])
                if n and len(n.group("hashes")) <= level:
                    end = j
                    break
            return "\n".join(lines[i:end]).rstrip()
    return None


def body_of(sec):
    if not sec:
        return ""
    lines = [l for l in sec.split("\n")[1:] if l.strip() and not l.strip().startswith("<!--")]
    return "\n".join(lines).strip()


# ----------------------------------------------------------------------------- plan parsing

class Task:
    def __init__(self, tid, mark, title, line_no, phase):
        self.id = tid
        self.mark = mark.lower() if mark in "xX" else mark
        self.title = OWNER_RE.sub("", title).strip(" -—:")
        self.owner = (OWNER_RE.search(title).group(0).strip() if OWNER_RE.search(title) else "")
        self.line_no = line_no
        self.phase = phase
        self.block = []
        self.fields = {}
        self.field_indent = None  # the indentation of this task's first field line
        self.unknown = []  # (line number, key, the field it was read into) for lint

    @property
    def deps(self):
        raw = self.fields.get("depends on", "")
        return TASK_ID_RE.findall(raw)

    @property
    def need_items(self):
        """The raw items of 'Needs: api 2.3, web 1.4' (empty for 'none', a '<...>' template
        placeholder, or no field)."""
        raw = self.fields.get("needs", "").strip()
        if not raw or raw.lower().startswith("none") or raw.startswith("<"):
            return []
        return [p.strip() for p in re.split(r"[,;]", raw) if p.strip()]

    @property
    def needs(self):
        """[(part, task id)] for the items that parse; lint reports the others."""
        return [(m.group("part").lower(), m.group("id"))
                for m in map(NEED_RE.fullmatch, self.need_items) if m]

    @property
    def spec_refs(self):
        """[(path, heading or None)] from 'Spec: docs/architecture.md#Ranking; contracts/api.md'
        (empty for 'none', a '<...>' template placeholder, or no field)."""
        raw = self.fields.get("spec", "").strip()
        if not raw or raw.lower().startswith("none") or raw.startswith("<"):
            return []
        out = []
        for item in re.split(r"\s*;\s*", raw):
            item = item.strip().strip("`").strip()
            if not item:
                continue
            path, _, heading = item.partition("#")
            out.append((path.strip(), heading.strip().lstrip("#").strip() or None))
        return out


def parse_plan(text):
    tasks, malformed, header = [], [], {}
    lines = text.split("\n")
    first_task = next((i for i, l in enumerate(lines) if TASK_RE.match(l)), len(lines))
    head = "\n".join(lines[:first_task])
    m = re.search(r"Target\s*:\s*\**\s*([A-Za-z]+)", head)
    header["target"] = m.group(1).lower() if m else None
    m = re.search(r"Audit\s*:\s*\**\s*([^\n·|]+)", head)
    header["audit"] = m.group(1).strip().strip("*").strip() if m else None
    # Optional, in the header lines only: the version this plan builds ("Version: v2").
    m = re.search(r"Version\s*:\s*\**\s*([^\n·|]+)", "\n".join(lines[:min(first_task, 6)]))
    header["version"] = m.group(1).strip().strip("*").strip() if m else None

    phase, current, last_key = "", None, None
    for i, line in enumerate(lines):
        h = HEADING_RE.match(line)
        tm = TASK_RE.match(line)
        if h:
            phase, current = h.group("title"), None
            continue
        if tm:
            current = Task(tm.group("id"), tm.group("mark"), tm.group("title"), i, phase)
            current.block.append(line)
            tasks.append(current)
            last_key = None
            continue
        if LOOSE_TASK_RE.match(line):
            malformed.append((i + 1, line.strip()))
            current = None
            continue
        if current is None:
            continue
        if line.strip() == "":
            current.block.append(line)
            continue
        if not line.startswith((" ", "\t")):
            current = None
            continue
        current.block.append(line)
        fm = TASK_FIELD_RE.match(line)
        key = fm.group("key").strip().lower() if fm else None
        indent = len(line) - len(line.lstrip(" \t"))
        if key in KNOWN_FIELDS:
            if current.field_indent is None:
                current.field_indent = indent
            val = fm.group("val").strip()
            if key in current.fields and key in ("if", "stop", "spec"):
                current.fields[key] += ("; " if key == "spec" else " | ") + val
            else:
                current.fields[key] = val
            last_key = key
        else:
            # A "- Key:" line at the fields' own indentation that isn't a field: it is read as
            # part of the field above it (or dropped), which lint points out.
            if key and indent == (current.field_indent if current.field_indent is not None
                                  else indent):
                current.unknown.append((i + 1, fm.group("key").strip(), last_key))
            if last_key:
                current.fields[last_key] += " " + line.strip()
    for t in tasks:
        while t.block and not t.block[-1].strip():
            t.block.pop()
    return tasks, malformed, header


def load_plan(root, required=True):
    text = load(root, PLAN)
    if text is None:
        if required:
            die(no_plan_message(root))
        return None, [], [], {}
    tasks, malformed, header = parse_plan(text)
    return text, tasks, malformed, header


def archived_versions(root):
    """{label: [task ids]} for each closed version in docs/archive/<label>/plan.md."""
    out = {}
    base = Path(root) / ARCHIVE
    if base.is_dir():
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            text = load(d, "plan.md")
            if text is not None:
                out[d.name] = [t.id for t in parse_plan(text)[0]]
    return out


def open_rounds(text):
    """The '- Round: ...' lines under a doc's 'Open questions' heading: the interview rounds (or
    grilled branches) still to ask. A draft PRD or program.md holds them only while its
    interview runs."""
    body = body_of(section(text, r"^open questions\b"))
    return [m.group("round") for m in (ROUND_RE.match(l.strip()) for l in body.split("\n")) if m]


def interview_rounds(root):
    """[(doc, [rounds])] for program.md and the PRD here, where they still list rounds."""
    out = []
    for rel in (PROGRAM, PRD):
        rounds = open_rounds(load(root, rel))
        if rounds:
            out.append((rel, rounds))
    return out


def no_plan_message(root):
    if (Path(root) / PROGRAM).is_file():
        return (f"no {PLAN} here: this is a program root ({PROGRAM}). Run 'program' for every "
                f"part's status, or plan with {skill('architect')}.{effort_note()}")
    versions = archived_versions(root)
    if versions:
        return (f"no {PLAN} here; earlier versions are archived in {ARCHIVE}/ "
                f"({', '.join(versions)}). Plan the next version with {skill('architect')}."
                f"{effort_note()}")
    return (f"no {PLAN} here. Run from the project root, or plan first with "
            f"{skill('architect')}.{effort_note()}")


def print_interview(root, pending):
    """status with no plan yet, while an interview is saved in rounds."""
    print(f"Blueprint status (v{VERSION})  no {PLAN} yet: interview in progress{effort_note()}")
    for rel, rounds in pending:
        print(f"{rel} still lists {len(rounds)} round(s) to ask:")
        for r in rounds:
            print(f"  - Round: {r}")
    grilled = any("grill" in r.lower() for _, rounds in pending for r in rounds)
    print(f"Resume with {skill('architect')}{' grill' if grilled else ''}: it asks only what "
          f"these docs leave open, then writes the plan once no round is left.")


def find_task(tasks, tid):
    for t in tasks:
        if t.id == tid:
            return t
    die(f"task {tid} is not in {PLAN}.")


def set_mark(text, task, mark, owner=None):
    lines = text.split("\n")
    line = lines[task.line_no]
    m = TASK_RE.match(line)
    title = OWNER_RE.sub("", m.group("title")).rstrip()
    if owner:
        title += f" (@{owner})"
    lines[task.line_no] = f"- [{mark}] {m.group('id')}{title}"
    return "\n".join(lines)


# ----------------------------------------------------------------------------- progress parsing

class Entry:
    def __init__(self, date, head, text):
        self.date, self.head, self.text = date, head.strip(), text.rstrip()
        m = re.match(r"Task\s+(\d+\.\d+)", self.head, re.I)
        self.task = m.group(1) if m else None
        word = (self.head.split() or ["other"])[0].lower().strip(":")
        self.kind = "task" if self.task else word
        self.fields = {}
        for line in self.text.split("\n")[1:]:
            fm = ENTRY_FIELD_RE.match(line)
            if fm:
                self.fields[fm.group("key").strip().lower()] = fm.group("val").strip()

    @property
    def status(self):
        raw = self.fields.get("status", "")
        if "|" in raw or not raw:
            return ""  # template left unfilled
        return raw.split()[0].lower().strip(".,;:")

    def filled(self, key):
        val = self.fields.get(key, "").strip()
        return bool(val) and not val.startswith(("...", "<")) and val.lower() not in ("tbd", "todo")


def parse_progress(text):
    """Entries are '## YYYY-MM-DD: ...' sections; any other '#'/'##' heading closes one."""
    entries, start, head, date = [], None, None, None
    lines = (text or "").split("\n")
    for i, line in enumerate(lines):
        if line.startswith(("## ", "# ")):
            if start is not None:
                entries.append(Entry(date, head, "\n".join(lines[start:i])))
                start = None
            m = ENTRY_RE.match(line)
            if m:
                start, head, date = i, m.group("rest"), m.group("date")
    if start is not None:
        entries.append(Entry(date, head, "\n".join(lines[start:])))
    return entries


def task_entries(entries, tid):
    return [e for e in entries if e.task == tid]


def entry_field_text(entry, key):
    """A field of a progress entry with its indented continuation lines ('- Decisions: a' plus
    '  - b'), or '' when it is missing or says none."""
    lines = entry.text.split("\n")
    for i, line in enumerate(lines):
        fm = ENTRY_FIELD_RE.match(line)
        if fm and fm.group("key").strip().lower() == key:
            out = [fm.group("val").strip()]
            for more in lines[i + 1:]:
                if not more.startswith((" ", "\t")) or not more.strip():
                    break
                out.append(more.strip())
            text = "\n".join(x for x in out if x).strip()
            if not text or text.lower().rstrip(".") in NO_VALUE or text.startswith("<"):
                return ""
            return text
    return ""


def digest_problem(entry):
    """Why a done entry's 'Digest:' line won't do, or None: it is missing, a placeholder, more
    than one line, or longer than MAX_DIGEST bytes."""
    val = entry_field_text(entry, "digest")
    if not val or val.startswith("..."):
        return "has no 'Digest:' line"
    if "\n" in val:
        return "has a 'Digest:' that runs over several lines; keep it to one"
    size = len(val.encode("utf-8"))
    if size > MAX_DIGEST:
        return f"has a 'Digest:' of {size} bytes; keep it to {MAX_DIGEST}"
    return None


def condensed(entry, keys=CONDENSED):
    """A task entry cut to what a later task needs: its heading and the given fields."""
    out = [entry.text.split("\n")[0]]
    for key in keys:
        val = entry_field_text(entry, key)
        if val:
            out.append(f"- {key.capitalize()}: " + val.replace("\n", "\n  "))
    return "\n".join(out)


def shorten(text, limit, more=""):
    """`text` on one line, cut at a word boundary to about `limit` chars, ending with `more`."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{cut} ...{' ' + more if more else ''}"


def spec_sections(root, task):
    """[(label, text or None, problem)] for each doc section the task's Spec: names."""
    out = []
    for path, heading in task.spec_refs:
        label = f"{path}: {heading}" if heading else path
        text = load(root, path) if path else None
        if text is None:
            out.append((label, None, f"{path or '(no path)'} not found"))
            continue
        if heading is None:
            out.append((label, text.strip(), None))
            continue
        sec = section(text, r"^\s*" + re.escape(heading) + r"\s*$")
        if sec is None:
            out.append((label, None, f"{path} has no heading '{heading}'"))
        else:
            out.append((label, sec, None))
    return out


def indirect_deps(tasks, task):
    """{task id: distance} for the tasks `task` builds on through its dependencies' own
    dependencies (2 = a dependency of a dependency), excluding its direct dependencies."""
    by_id = {t.id: t for t in tasks}
    direct = set(task.deps)
    dist, frontier, d = {}, list(direct), 1
    seen = set(direct) | {task.id}
    while frontier:
        d += 1
        nxt = []
        for tid in frontier:
            for up in (by_id[tid].deps if tid in by_id else []):
                if up not in seen:
                    seen.add(up)
                    dist[up] = d
                    nxt.append(up)
        frontier = nxt
    return dist


NO_VALUE = ("none", "n/a", "-")


def pending_change_requests(entries):
    """Task entries whose 'Change request:' no later Change entry has settled (planned, deferred
    or declined by the architect)."""
    out = []
    for i, e in enumerate(entries):
        if e.task and e.filled("change request") and \
                e.fields["change request"].lower() not in NO_VALUE:
            if not any(x.kind == "change" for x in entries[i + 1:]):
                out.append(e)
    return out


def final_audit_state(tasks, entries):
    """The final audit's state for this version: ACCEPTED or DEFECTS when a final audit follows
    the last task entry, 'due' when every task is done without one, otherwise 'not due'."""
    last_task = max((i for i, e in enumerate(entries) if e.task), default=-1)
    after = [e for i, e in enumerate(entries)
             if i > last_task and e.kind == "audit"
             and re.search(r"audit \(final\b|final audit", e.head, re.I)]
    if after:
        verdict = after[-1].fields.get("verdict") or after[-1].fields.get("status") or after[-1].text
        lead = re.match(r"\W*(accepted|defects?)\b", verdict, re.I)
        if lead:
            return "ACCEPTED" if lead.group(1).lower() == "accepted" else "DEFECTS"
        if re.search(r"\bDEFECTS?\b", verdict):
            return "DEFECTS"
        return "ACCEPTED" if re.search(r"\bACCEPTED\b", verdict) else "recorded"
    if tasks and all(t.mark == "x" for t in tasks):
        return "due"
    return "not due"


# ----------------------------------------------------------------------------- git / folder mode

def git(root, *args):
    try:
        # core.quotepath=off: non-ASCII paths come back as text, not as quoted octal escapes
        r = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=root,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.returncode, r.stdout.strip("\n"), r.stderr.strip()
    except OSError as exc:
        return 1, "", str(exc)


def is_git(root):
    if not shutil.which("git"):
        return False
    code, out, _ = git(root, "rev-parse", "--is-inside-work-tree")
    return code == 0 and out.strip() == "true"


def has_head(root):
    return git(root, "rev-parse", "--verify", "--quiet", "HEAD")[0] == 0


_NESTED = {}  # resolved project root -> its nested projects, found once per run


def nested_projects(root):
    """Folders below the project root that hold their own docs/plan.md: other projects, such as
    the parts of a program nested in a part. Their files, changes and commits are never this
    project's, so every check and checkpoint here leaves them out."""
    base = Path(root).resolve()
    if base not in _NESTED:
        found, worktrees = [], base / WORKTREES
        for dirpath, dirnames, _ in os.walk(base):
            here = Path(dirpath)
            if here == worktrees:
                dirnames[:] = []
                continue
            if here != base and (here / PLAN).is_file():
                found.append(here.relative_to(base).as_posix())
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        _NESTED[base] = sorted(found)
    return _NESTED[base]


def in_nested(rel, nested):
    return any(rel == p or rel.startswith(p + "/") for p in nested)


def nested_spec(root):
    """git pathspecs (after '.') that leave out the nested projects."""
    return [f":(exclude,literal){p}" for p in nested_projects(root)]


def exclude_spec(root):
    """The pathspecs (after '.') for a task's own changes: no bookkeeping files, no nested
    projects and no Claude Code session worktrees."""
    return ([f":(exclude){p}" for p in sorted(BOOKKEEPING)] + [f":(top,exclude){WORKTREES}"]
            + nested_spec(root))


def dirty_lines(root):
    """Uncommitted changes in the project folder (the whole repo when the project is the repo
    root; a sibling or nested project's work never counts), as `git status --porcelain` lines,
    leaving out Claude Code's session worktrees, which are not part of any task."""
    _, out, _ = git(root, "status", "--porcelain", "--", ".", f":(top,exclude){WORKTREES}",
                    *nested_spec(root))
    return [l for l in out.split("\n") if l.strip()]


def walk_files(root, skipped=None):
    """Project files for a folder-mode snapshot, skipping dependency/build folders, nested
    projects and files over 5 MB (collected in `skipped` when a list is passed)."""
    root = Path(root)
    nested = {root / p for p in nested_projects(root)}
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and here / d not in nested]
        for name in filenames:
            p = Path(dirpath) / name
            rel = p.relative_to(root).as_posix()
            try:
                if p.stat().st_size > MAX_SNAPSHOT_FILE:
                    if skipped is not None:
                        skipped.append(rel)
                    continue
            except OSError:
                continue
            yield rel, p


def snapshots(root, tid):
    d = Path(root) / STATE_DIR / "snapshots"
    found = []
    for p in d.glob(f"task-{tid}-*.zip"):
        m = re.search(r"-(\d+)\.zip$", p.name)
        if m:
            found.append((int(m.group(1)), p))
    return [p for _, p in sorted(found)]


def take_snapshot(root, tid):
    d = Path(root) / STATE_DIR / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    n = len(snapshots(root, tid)) + 1
    path = d / f"task-{tid}-{n}.zip"
    count, skipped = 0, []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, p in walk_files(root, skipped):
            z.write(p, rel)
            count += 1
    if skipped:
        print(f"NOTE: {len(skipped)} file(s) over 5 MB are not checkpointed, e.g. {skipped[0]}")
    return path, count


def compare_snapshot(root, zpath):
    changed, added, deleted = [], [], []
    nested = nested_projects(root)  # a v2.1 snapshot may hold them: they are never restored
    with zipfile.ZipFile(zpath) as z:
        old = {n for n in z.namelist() if n not in BOOKKEEPING and not in_nested(n, nested)}
        now = {}
        for rel, p in walk_files(root):
            if rel not in BOOKKEEPING:
                now[rel] = p
        for rel in sorted(now):
            if rel not in old:
                added.append(rel)
            elif z.read(rel) != now[rel].read_bytes():
                changed.append(rel)
        deleted = sorted(old - set(now))
    return changed, added, deleted


def active_task_id(tasks, tid):
    if tid:
        return tid
    inprog = [t.id for t in tasks if t.mark == "~"]
    if not inprog:
        die("no task is in progress; pass the task ID.")
    return inprog[0]


# ----------------------------------------------------------------------------- programs and parts

def table_rows(text, heading):
    """The Markdown table under the heading matching `heading`: (header cells in lower case,
    [{column: cell}], the raw table lines)."""
    sec = section(text, heading)
    if not sec:
        return [], [], []
    rows, header = [], []
    lines = [l for l in sec.split("\n") if l.strip().startswith("|")]
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        if not header:
            header = [c.lower() for c in cells]
            continue
        rows.append(dict(zip(header, cells)))
    return header, rows, lines


def program_parts(proot, text):
    """{part name (lower case): resolved folder} from program.md's Parts table, in table order."""
    parts = {}
    for rec in table_rows(text, r"^parts\b")[1]:
        name = rec.get("part", "").strip("` ").lower()
        folder = rec.get("folder", "").strip("` ")
        if name and folder and not name.startswith("<") and not folder.startswith("<"):
            parts[name] = (Path(proot) / folder).resolve()
    return parts


_PROGRAMS = {}


def find_program(root):
    """The program this folder belongs to: the nearest docs/program.md at or above it whose
    Parts table lists this folder (a program root itself counts too). None when there is none.
    Parts in separate git repos work too, as long as they sit inside the program's folder."""
    here = Path(root).resolve()
    if here not in _PROGRAMS:
        _PROGRAMS[here] = None
        for d in [here, *here.parents]:
            text = load(d, PROGRAM)
            if text is None:
                continue
            parts = program_parts(d, text)
            mine = next((n for n, f in parts.items() if f == here), None)
            if mine is not None or d == here:
                _PROGRAMS[here] = {"root": d, "parts": parts, "self": mine, "text": text}
                break
    return _PROGRAMS[here]


_PART_TASKS = {}


def part_tasks(folder):
    """The tasks in another part's docs/plan.md (as it is on disk), or None if it has none."""
    if folder not in _PART_TASKS:
        text = load(folder, PLAN)
        _PART_TASKS[folder] = parse_plan(text)[0] if text is not None else None
    return _PART_TASKS[folder]


def need_state(program, root, part, tid):
    """(marker, problem) for one 'Needs:' item: the other part's marker for that task, or None
    and the reason it can't be checked."""
    folder = program["parts"].get(part)
    where = shown(program["root"] / PROGRAM, root)
    if folder is None:
        names = ", ".join(program["parts"]) or "none"
        return None, f"{where} has no part '{part}' (parts: {names})"
    if folder == Path(root).resolve():
        return None, f"'{part}' is this part; use 'Depends on' for its own tasks"
    tasks = part_tasks(folder)
    if tasks is None:
        return None, f"part '{part}' ({shown(folder, root)}/) has no {PLAN} yet"
    t = next((x for x in tasks if x.id == tid), None)
    if t is None:
        return None, f"part '{part}' ({shown(folder, root)}/) has no task {tid}"
    return t.mark, ""


def unmet_needs(root, task):
    """The task's 'Needs:' items that aren't done, as text such as
    "api 2.3 ([ ] in ../api/docs/plan.md)"; empty when the task may go ahead."""
    items = task.need_items
    if not items:
        return []
    program = find_program(root)
    if program is None:
        return [f"{', '.join(items)} (no {PROGRAM} above this folder lists it as a part)"]
    out = [f"'{p}' (write it as '<part> <task id>', e.g. 'api 2.3')"
           for p in items if not NEED_RE.fullmatch(p)]
    for part, tid in task.needs:
        mark, problem = need_state(program, root, part, tid)
        if mark != "x":
            out.append(f"{part} {tid} ({problem})" if problem else
                       f"{part} {tid} ([{mark}] in "
                       f"{shown(program['parts'][part] / PLAN, root)})")
    return out


# ----------------------------------------------------------------------------- lint

def import_targets(text):
    """The @-import paths Claude Code expands in a memory file: outside HTML comments, fenced
    code and code spans."""
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
    text = re.sub(r"^(`{3,}|~{3,}).*?^\1", "", text, flags=re.S | re.M)
    text = re.sub(r"`[^`\n]*`", "", text)
    return [t.rstrip(".,;:!?") for t in re.findall(r"(?<![\w@])@([^\s`'\"<>()\[\]]+)", text)]


def imports_agents(root, rel, text):
    """True when the file at `rel` imports this project's AGENTS.md. Imports resolve relative to
    the importing file, so .claude/CLAUDE.md needs @../AGENTS.md."""
    target = os.path.normcase(str((Path(root) / AGENTS).resolve()))
    base = (Path(root) / rel).parent
    for ref in import_targets(text):
        p = Path(os.path.expanduser(ref))
        p = p if p.is_absolute() else base / p
        try:
            if os.path.normcase(str(p.resolve())) == target:
                return True
        except (OSError, ValueError):
            continue
    return False


def import_line(rel):
    return "@../AGENTS.md" if rel == ".claude/CLAUDE.md" else "@AGENTS.md"


def claude_files_above(root):
    """A CLAUDE.md, .claude/CLAUDE.md or CLAUDE.local.md in a folder above the project also stops
    Claude Code reading AGENTS.md by itself. The user's own ~/.claude/CLAUDE.md doesn't count."""
    own = os.path.normcase(str(Path.home() / ".claude" / "CLAUDE.md"))
    for d in Path(root).resolve().parents:
        for rel in CLAUDE_FILES:
            p = d / rel
            if p.is_file() and os.path.normcase(str(p)) != own:
                return str(p)
    return None


def norm_block(text):
    return "\n".join(l.rstrip() for l in text.replace("\r\n", "\n").strip().split("\n"))


def instructions_checks(root, agents):
    """The rules live in AGENTS.md, which Codex reads. Claude Code reads CLAUDE.md files, and reads
    AGENTS.md by itself only when none exists here or above (v2.1.277+). So a CLAUDE.md must
    import AGENTS.md (or carry an identical copy of the blueprint block)."""
    errors, warns = [], []
    if agents is None:
        return errors, warns
    found = [(p, load(root, p)) for p in CLAUDE_FILES if (Path(root) / p).is_file()]
    if any(imports_agents(root, p, text) for p, text in found):
        return errors, warns
    if not found:
        # Without a CLAUDE.md here, only Claude Code sessions miss the rules: an error there, a
        # note for a Codex run (a teammate may use Claude Code), and silence in a Codex-only repo.
        above = claude_files_above(root)
        if above:
            (errors if IN_CLAUDE else warns).append(
                f"Claude Code reads {above} instead of {AGENTS} here, so it never sees the "
                f"rules; add a CLAUDE.md to this folder whose first line is @AGENTS.md")
        elif IN_CLAUDE:
            warns.append("no CLAUDE.md: Claude Code reads AGENTS.md by itself only from v2.1.277, and "
                         "not while a CLAUDE.md or CLAUDE.local.md exists here or above; add a "
                         "CLAUDE.md whose first line is @AGENTS.md")
        return errors, warns
    ours = BLOCK_RE.search(agents)
    copies = [(p, m) for p, m in ((p, BLOCK_RE.search(t)) for p, t in found) if m]
    if ours and copies:
        for p, m in copies:
            if norm_block(m.group(0)) != norm_block(ours.group(0)):
                errors.append(f"the blueprint blocks in {AGENTS} and {p} differ; replace the copy in "
                              f"{p} with the line {import_line(p)}")
        return errors, warns
    shared = [p for p, _ in found if p != "CLAUDE.local.md"]
    fix = (f"add the line {import_line(shared[0])} at the top of {shared[0]}" if shared else
           "add a CLAUDE.md whose first line is @AGENTS.md")
    errors.append(f"{', '.join(p for p, _ in found)} {'does' if len(found) == 1 else 'do'} not import "
                  f"{AGENTS}, so Claude Code never reads the rules; {fix}")
    return errors, warns


def marker_checks(tasks, entries):
    """Markers change only through this script, which first requires the matching entry."""
    errors = []
    for t in tasks or []:
        mine = task_entries(entries, t.id)
        last = mine[-1] if mine else None
        if t.mark == "x" and not (last and last.status == "done" and last.filled("checks")):
            errors.append(f"task {t.id} is [x] without a latest 'Status: done' entry with Checks; "
                          f"was the marker edited by hand? ('done' sets it; the architect's "
                          f"'reopen' resets it)")
        elif t.mark == "!" and not (last and last.status == "blocked" and last.filled("question")):
            errors.append(f"task {t.id} is [!] without a latest 'Status: blocked' entry with a "
                          f"Question; was the marker edited by hand? ('block' sets it)")
    return errors


def lint_docs(root):
    errors, warns = [], []
    text, tasks, malformed, header = load_plan(root, required=False)
    if text is None:
        if (Path(root) / PROGRAM).is_file():
            return [f"{PLAN} is missing (this is a program root: run 'program')"], warns, None
        return [f"{PLAN} is missing"], warns, None

    target = header.get("target")
    if target not in TARGETS:
        errors.append(f"{PLAN}: header needs 'Target: POC | MVP | production' (found {target!r})")
    if not header.get("audit"):
        warns.append(f"{PLAN}: header has no 'Audit:' line (pending | done <date>)")
    if not tasks:
        errors.append(f"{PLAN}: no task lines like '- [ ] 1.1 Name'")
    for line_no, line in malformed:
        errors.append(f"{PLAN}:{line_no}: malformed task line (use '- [ ] 1.2 Name'): {line}")

    seen, prev = set(), None
    for t in tasks:
        if t.id in seen:
            errors.append(f"task {t.id}: duplicate ID")
        seen.add(t.id)
        if prev and id_key(t.id) < id_key(prev):
            warns.append(f"task {t.id}: listed after {prev}; keep IDs in execution order")
        prev = t.id
    for t in tasks:
        for field in REQUIRED_FIELDS:
            if not t.fields.get(field):
                errors.append(f"task {t.id}: missing '{field.title()}:'")
        done_when = t.fields.get("done when", "")
        if done_when and "`" not in done_when and not done_when.lower().startswith("manual:"):
            errors.append(f"task {t.id}: 'Done when' needs a runnable command in backticks, "
                          f"or 'manual:' followed by yes/no items")
        size = t.fields.get("size")
        if size and size.strip().upper()[:1] not in ("S", "M", "L"):
            warns.append(f"task {t.id}: Size should be S, M or L")
        for d in t.deps:
            if d not in seen:
                errors.append(f"task {t.id}: depends on unknown task {d}")
            elif id_key(d) >= id_key(t.id):
                warns.append(f"task {t.id}: depends on {d}, which is not earlier in the plan")
        raw_dep = t.fields.get("depends on", "").strip().lower()
        if raw_dep and not t.deps and not raw_dep.startswith("none"):
            warns.append(f"task {t.id}: 'Depends on' should be 'none' or task IDs like 1.2")
    if len([t for t in tasks if t.mark == "~"]) > 1:
        warns.append("more than one task is [~] in progress; tasks run one at a time")
    if len(tasks) > MAX_TASKS:
        warns.append(f"{PLAN} has {len(tasks)} tasks; past {MAX_TASKS} a project has usually "
                     f"outgrown one plan: split it into connected parts, or move the later "
                     f"phases to a new version ({skill('architect')})")
    for t in tasks:
        for line_no, key, into in t.unknown:
            warns.append(f"{PLAN}:{line_no}: task {t.id}: '{key}:' is not a task field, so it is "
                         + (f"read as part of '{into.title()}'; indent it further if it belongs "
                            f"there" if into else "ignored"))
    for t in tasks:
        size = 0
        for label, text, problem in spec_sections(root, t):
            if problem:
                errors.append(f"task {t.id}: 'Spec: {label}': {problem} (name a doc section as "
                              f"'path#Heading', e.g. docs/architecture.md#Ranking)")
            else:
                size += len(text)
        if size > MAX_SPEC:
            warns.append(f"task {t.id}: its Spec sections are {size} chars, printed in every "
                         f"session of the task; keep them under {MAX_SPEC:,} (point at a "
                         f"narrower heading, or split the task)")
    more_errors, more_warns = needs_checks(root, tasks)
    errors += more_errors
    warns += more_warns
    archived = archived_versions(root)
    if archived:
        old = {tid: label for label, ids in archived.items() for tid in ids}
        clash = [t.id for t in tasks if t.id in old]
        if clash:
            start = max(id_key(tid)[0] for tid in old) + 1
            warns.append(f"task(s) {', '.join(clash[:5])}{' ...' if len(clash) > 5 else ''} "
                         f"repeat IDs from {ARCHIVE}/{old[clash[0]]}/plan.md: number this "
                         f"version's phases from {start}, so 'task <id>:' commits stay unique")

    prd = load(root, PRD)
    if prd is None:
        errors.append(f"{PRD} is missing")
    else:
        if not body_of(section(prd, r"non-?goals")):
            errors.append(f"{PRD}: needs a 'Non-goals' section with at least one item")
        if len(prd) > MAX_PRD:
            warns.append(f"{PRD} is {len(prd):,} chars; past {MAX_PRD:,} it usually covers more "
                         f"than one part: split the project into connected parts, or move "
                         f"detail into architecture.md")
    for rel, rounds in interview_rounds(root):
        errors.append(f"{rel}: 'Open questions' still lists {len(rounds)} interview round(s) "
                      f"(e.g. 'Round: {rounds[0]}'), but {PLAN} exists: ask them, or put each "
                      f"point under 'Decided by default', then delete the Round lines")

    ess = load(root, ESSENTIALS)
    arch = load(root, ARCH)
    if ess is None:
        errors.append(f"{ESSENTIALS} is missing")
    else:
        if len(ess) > 6000:
            warns.append(f"{ESSENTIALS} is {len(ess)} chars; keep it to one page (<= 6,000)")
        if not section(ess, r"dependenc"):
            warns.append(f"{ESSENTIALS}: no 'Dependencies' table (write 'none' if there are none)")
        else:
            for name, cells in dep_rows(ess)[1]:
                verified = cells.get("verified", "")
                if not re.match(r"\d{4}-\d{2}-\d{2}", verified):
                    warns.append(f"dependency {name}: not verified ({verified or 'blank'}); "
                                 f"run 'deps --write'")
        if arch is not None:
            marker = re.search(r"<!-- essentials-of:.*sha256:([0-9a-f]+)", ess)
            if not marker:
                errors.append(f"{ESSENTIALS}: no source stamp; run 'blueprint.py stamp'")
            elif marker.group(1) != arch_hash(arch):
                errors.append(f"{ESSENTIALS} is stale: {ARCH} changed since it was stamped. "
                              f"Update the essentials to match, then run 'stamp'")
    if target in ("mvp", "production") and arch is None:
        errors.append(f"{ARCH} is required for target {target.upper()}")
    if target == "production" and arch is not None:
        heads = " ".join(h.group("title").lower() for h in map(HEADING_RE.match, arch.split("\n")) if h)
        for need, words in (("Security", ("security",)), ("Data & migrations", ("migration",)),
                            ("Observability", ("observability", "monitoring")),
                            ("Rollback", ("rollback", "roll back"))):
            if not any(w in heads for w in words):
                errors.append(f"{ARCH}: production needs a '{need}' section")
    if target in ("mvp", "production"):
        blob = " ".join(f"{t.title} {t.fields.get('goal', '')}" for t in tasks)
        if not re.search(r"\bCI\b", blob):
            warns.append("no CI task found (MVP/production plans should run tests on every push)")
        if target == "production" and not re.search(r"release", blob, re.I):
            warns.append("no release task found (production plans end with one)")

    agents = load(root, AGENTS)
    if agents is None:
        errors.append(f"{AGENTS} is missing")
    else:
        size = len(agents.encode("utf-8"))
        if size > 32768:
            errors.append(f"{AGENTS} is {size} bytes; Codex stops reading at 32 KiB")
        elif len(agents) > 8000:
            warns.append(f"{AGENTS} is {len(agents)} chars; it loads every session, keep it < 8,000")
        m = re.search(r"Target\s*:\s*\**\s*(POC|MVP|production)", agents, re.I)
        if m and target and m.group(1).lower() != target:
            warns.append(f"{AGENTS} says target {m.group(1)} but {PLAN} says {target}")
    more_errors, more_warns = instructions_checks(root, agents)
    errors += more_errors
    warns += more_warns
    progress = load(root, PROGRESS)
    if progress is None:
        warns.append(f"{PROGRESS} is missing")
    entries = parse_progress(progress)
    errors += marker_checks(tasks, entries)
    dated = [e for e in entries if e.date]
    for prev, cur in [(a, b) for a, b in zip(dated, dated[1:]) if b.date < a.date][:3]:
        warns.append(f"{PROGRESS}: '## {cur.date}: {cur.head[:48]}' is dated before the entry "
                     f"above it ({prev.date}); entries are appended in order, so check the date")
    # Entries from before v2.6 have no Digest, and status falls back to their Decisions; a
    # Digest that is there must still fit, because status prints it to every later task.
    for e in entries:
        problem = digest_problem(e) if e.task and "digest" in e.fields else None
        if problem:
            warns.append(f"{PROGRESS}: task {e.task}'s entry ({e.date}) {problem}")
    return errors, warns, tasks


def needs_checks(root, tasks):
    """'Needs:' must name another part of this folder's program and one of its tasks. A part
    that isn't planned yet is only a warning: the task waits until it is."""
    errors, warns = [], []
    program = None
    for t in tasks:
        items = t.need_items
        if not items:
            continue
        for p in items:
            if not NEED_RE.fullmatch(p):
                errors.append(f"task {t.id}: 'Needs: {p}' should be '<part> <task id>', "
                              f"e.g. 'api 2.3'")
        program = program or find_program(root)
        if program is None:
            errors.append(f"task {t.id}: 'Needs:' waits on another part, but no {PROGRAM} at or "
                          f"above this folder lists it as a part")
            continue
        for part, tid in t.needs:
            folder = program["parts"].get(part)
            if folder is not None and folder != Path(root).resolve() and part_tasks(folder) is None:
                warns.append(f"task {t.id}: 'Needs: {part} {tid}': part '{part}' isn't planned "
                             f"yet, so this task waits until it is")
                continue
            _, problem = need_state(program, root, part, tid)
            if problem:
                errors.append(f"task {t.id}: 'Needs: {part} {tid}': {problem}")
    return errors, warns


def cmd_lint(args):
    errors, warns, tasks = lint_docs(args.root)
    for e in errors:
        print(f"[ERROR] {e}")
    for w in warns:
        print(f"[WARN]  {w}")
    n = len(tasks or [])
    print(f"\n{n} task(s): {len(errors)} error(s), {len(warns)} warning(s){effort_note()}")
    return 1 if errors else 0


# ----------------------------------------------------------------------------- essentials stamp

def arch_hash(arch_text):
    norm = arch_text.replace("\r\n", "\n").strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]


def cmd_stamp(args):
    ess = load(args.root, ESSENTIALS)
    if ess is None:
        die(f"no {ESSENTIALS} to stamp.")
    arch = load(args.root, ARCH)
    if arch is None:
        marker = "<!-- essentials-of: none (no architecture.md; this page is the architecture) -->"
    else:
        marker = (f"<!-- essentials-of: {ARCH} sha256:{arch_hash(arch)} "
                  f"(regenerate this page when architecture.md changes, then run stamp) -->")
    body = ESS_MARKER_RE.sub("", ess, count=1)
    save(args.root, ESSENTIALS, marker + "\n" + body.lstrip("\n"))
    print(f"Stamped {ESSENTIALS}: {marker}")
    return 0


# ----------------------------------------------------------------------------- deps

def dep_rows(ess):
    """Parse the Dependencies table: returns (header cells, [(name, {col: value})], raw lines)."""
    header, recs, lines = table_rows(ess, r"dependenc")
    rows = []
    for rec in recs:
        name_col = next((h for h in header if h in ("package", "name", "library", "dependency")),
                        header[0])
        rec["verified"] = next((rec.get(h, "") for h in header if "verified" in h), "")
        rec["registry"] = next((rec.get(h, "") for h in header if h in ("registry", "ecosystem")),
                               "")
        name = rec.get(name_col, "").strip("` ")
        if name and name.lower() not in ("none", "-"):
            rows.append((name, rec))
    return header, rows, lines


MANUAL_URLS = {
    "crates": "https://crates.io/crates/{}", "cargo": "https://crates.io/crates/{}",
    "rubygems": "https://rubygems.org/gems/{}", "gem": "https://rubygems.org/gems/{}",
    "nuget": "https://www.nuget.org/packages/{}", "go": "https://pkg.go.dev/{}",
    "maven": "https://central.sonatype.com/search?q={}",
    "packagist": "https://packagist.org/packages/{}", "composer": "https://packagist.org/packages/{}",
}


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "blueprint-solution-deps/1.0",
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def lookup(name, registry):
    """Return (status, latest, released, note)."""
    reg = registry.lower().strip("` ")
    try:
        if reg in ("npm", "node", "yarn", "pnpm"):
            # /latest is small; the full packument of a popular package can be many MB.
            data = fetch_json("https://registry.npmjs.org/"
                              + urllib.parse.quote(name, safe="@") + "/latest")
            latest = data.get("version", "")
            dep = data.get("deprecated")
            released = ""
            try:
                found = fetch_json("https://registry.npmjs.org/-/v1/search?size=5&text="
                                   + urllib.parse.quote(name))
                for obj in found.get("objects", []):
                    pkg = obj.get("package", {})
                    if pkg.get("name") == name:
                        released = (pkg.get("date") or "")[:10]
                        break
            except Exception:
                pass  # the date is a nice-to-have; existence is already proven
            status = "DEPRECATED" if dep else "FOUND"
            return status, latest, released, (str(dep)[:80] if dep else "")
        if reg in ("pypi", "pip", "python", "uv", "poetry"):
            data = fetch_json(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json")
            latest = data.get("info", {}).get("version", "")
            files = data.get("urls") or data.get("releases", {}).get(latest, [])
            released = (files[0].get("upload_time_iso_8601") or files[0].get("upload_time", ""))[:10] \
                if files else ""
            return "FOUND", latest, released, ""
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return "NOT FOUND", "", "", "the registry has no package with this exact name"
        return "UNVERIFIED", "", "", f"HTTP {exc.code}"
    except Exception as exc:  # network blocked, DNS, timeout, proxy
        return "UNVERIFIED", "", "", f"{type(exc).__name__}: {str(exc)[:60]}"
    url = MANUAL_URLS.get(reg, "")
    return "MANUAL", "", "", (url.format(name) if url else f"check the official '{registry}' registry")


def cmd_deps(args):
    ess = load(args.root, ESSENTIALS)
    if ess is None:
        die(f"no {ESSENTIALS}; the Dependencies table lives there.")
    header, rows, lines = dep_rows(ess)
    if not rows:
        print("No dependencies listed (Dependencies table empty or 'none'). Nothing to check.")
        return 0
    today = datetime.date.today()
    results, bad = {}, 0
    for name, rec in rows:
        status, latest, released, note = lookup(name, rec.get("registry", ""))
        if status == "FOUND" and released:
            try:
                age = (today - datetime.date.fromisoformat(released)).days
                if age > 730:
                    status, note = "STALE", f"no release for {age // 365} years"
            except ValueError:
                pass
        bad += status == "NOT FOUND"
        results[name] = (status, latest, released)
        detail = f"latest {latest} ({released})" if latest else ""
        print(f"{status:<11} {rec.get('registry', '?'):<7} {name:<32} {detail} {note}".rstrip())

    if args.write:
        new_ess = write_verified(ess, header, rows, lines, results, today.isoformat())
        save(args.root, ESSENTIALS, new_ess)
        print(f"\nWrote the Verified column in {ESSENTIALS}. Only FOUND rows get a date; "
              f"anything else must not be installed until it is resolved.")
    if bad:
        print(f"\n{bad} dependency name(s) do not exist. Do not install them; pick a real package.")
    print("MANUAL rows: open the link, confirm the package and its maintenance, then write the date "
          "yourself. Never date a row you did not check.")
    return 1 if bad else 0


def write_verified(ess, header, rows, lines, results, today):
    vcol = next((i for i, h in enumerate(header) if "verified" in h), None)
    add_col = vcol is None
    if add_col:
        vcol = len(header)
    out_lines, seen_header = {}, False
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            if add_col:
                cells.append("---")
        elif not seen_header:
            seen_header = True
            if add_col:
                cells.append("Verified")
        else:
            name_idx = next((i for i, h in enumerate(header)
                             if h in ("package", "name", "library", "dependency")), 0)
            name = cells[name_idx].strip("` ") if name_idx < len(cells) else ""
            if name in results:
                status, latest, released = results[name]
                while len(cells) <= vcol:
                    cells.append("")
                if status == "FOUND":
                    cells[vcol] = f"{today} ({latest})"
                elif status == "STALE":
                    cells[vcol] = f"STALE: last release {released}"
                elif status in ("NOT FOUND", "UNVERIFIED", "DEPRECATED"):
                    cells[vcol] = status
        out_lines[line] = "| " + " | ".join(cells) + " |"
    return "\n".join(out_lines.get(l, l) for l in ess.split("\n"))


# ----------------------------------------------------------------------------- status

def git_warnings(root, tasks, nxt, resume):
    warns = []
    dirty = dirty_lines(root)
    if dirty and not resume:
        warns.append("STOP: uncommitted changes before a new task. Commit or stash them first:\n    "
                     + "\n    ".join(dirty[:10]) + ("\n    ..." if len(dirty) > 10 else ""))
    elif dirty and resume:
        warns.append("uncommitted changes from an earlier session of this task; review them with "
                     "'diff' before continuing")
    if has_head(root):
        # "-- ." keeps only commits touching this project's folder, and the nested projects'
        # own commits are left out: in a repo that holds several projects, another project's
        # "task 6.1" is not this one's.
        mine = ["--", ".", *nested_spec(root)]
        _, subjects, _ = git(root, "log", "HEAD", "--format=%s", *mine)
        subjects = subjects.split("\n")
        missing = [t.id for t in tasks if t.mark == "x"
                   and not any(re.match(rf"task {re.escape(t.id)}\b", s) for s in subjects)]
        if missing:
            warns.append(f"done task(s) with no 'task <id>:' commit on this branch: {', '.join(missing)}")
        if nxt is not None and not resume:
            pat = rf"^task {re.escape(nxt.id)}[ :(]"
            _, here, _ = git(root, "log", "HEAD", "-E", f"--grep={pat}", "--format=%h", *mine)
            _, anywhere, _ = git(root, "log", "--all", "-E", f"--grep={pat}", "--format=%h %D",
                                 *mine)
            if anywhere.strip() and not here.strip():
                warns.append(f"STOP: task {nxt.id} was already committed on another branch "
                             f"({anywhere.split(chr(10))[0]}). Merge or switch to that branch first.")
    return warns


def env_warnings(root, git_mode):
    warns = []
    for rel, _ in walk_files(root):
        name = rel.rsplit("/", 1)[-1]
        if re.fullmatch(r"\.env(\..+)?", name) and not re.search(r"\.(example|sample|template)$", name):
            if git_mode:
                if git(root, "check-ignore", "-q", rel)[0] != 0:
                    warns.append(f"STOP: {rel} holds secrets and is NOT git-ignored. Add it to "
                                 f".gitignore before any commit.")
            else:
                warns.append(f"{rel} holds secrets: never print it, and leave it out of copies you share")
    return warns


def pick_next(tasks, wanted=None, root=None, waits=None):
    """The task to build: the one named, the one in progress, or the first to-do task whose
    dependencies are done and, with `root`, whose 'Needs:' on other parts are done too. The
    to-do tasks held back only by 'Needs:' go into `waits` as (task, [unmet items])."""
    if wanted:
        t = find_task(tasks, wanted)
        return t, t.mark == "~"
    inprog = [t for t in tasks if t.mark == "~"]
    if inprog:
        return inprog[0], True
    done = {t.id for t in tasks if t.mark == "x"}
    for t in tasks:
        if t.mark == " " and all(d in done for d in t.deps):
            unmet = unmet_needs(root, t) if root else []
            if not unmet:
                return t, False
            if waits is not None:
                waits.append((t, unmet))
    return None, False


def print_history(tasks, nxt, entries, mine):
    """What earlier tasks left for `nxt`, sized so that a late task reads about as much as an
    early one: each direct dependency's entry cut to what a later task needs, then, nearest
    first and within HISTORY_BUDGET, one Digest line per task it builds on indirectly (the
    Decisions, shortened, for an entry from before Digests), then the latest entry, cut the same
    way. The tasks left out are named for 'recall'. `mine` (this task's own earlier sessions)
    was printed in full already."""
    shown = {id(e) for e in mine}
    dep_entries = [te[-1] for te in (task_entries(entries, d) for d in nxt.deps) if te]
    if dep_entries:
        print("\n=== DECISIONS FROM TASKS THIS ONE DEPENDS ON ===")
        print("\n\n".join(condensed(e) for e in dep_entries))
        shown |= {id(e) for e in dep_entries}
    far = []
    for tid, dist in indirect_deps(tasks, nxt).items():
        te = task_entries(entries, tid)
        digest = entry_field_text(te[-1], "digest") if te else ""
        if digest:
            far.append((dist, tid, shorten(digest, MAX_DIGEST, f"(recall {tid})")))
            continue
        decided = entry_field_text(te[-1], "decisions") if te else ""
        if decided:
            far.append((dist, tid, shorten(decided, 2 * MAX_DIGEST, f"(recall {tid})")))
    far.sort(key=lambda x: (x[0], tuple(-n for n in id_key(x[1]))))
    budget, kept, left_out = HISTORY_BUDGET, [], []
    for _, tid, line in far:
        row = f"- Task {tid}: {line}"
        if len(kept) < MAX_INDIRECT and len(row) < budget:
            kept.append((tid, row))
            budget -= len(row) + 1
        else:
            left_out.append(tid)
    if kept:
        print("\n=== DIGESTS OF TASKS THIS ONE BUILDS ON INDIRECTLY ===")
        print("\n".join(row for _, row in sorted(kept, key=lambda x: id_key(x[0]))))
    if left_out:
        print(f"(further back, not shown: {', '.join(sorted(left_out, key=id_key))})")
    if entries and id(entries[-1]) not in shown:
        latest = entries[-1]
        cut = condensed(latest, CONDENSED + ("next",))
        print(f"\n=== LATEST ENTRY  ({PROGRESS}) ===")
        print(cut if "\n" in cut else latest.text)  # no such fields: an entry of another shape
    print(f"\nMore, without reading a doc whole: 'recall <task id>', 'recall docs/<file>.md' "
          f"(its outline), 'recall docs/<file>.md#<Heading>', 'recall <regex>'.")


def cmd_status(args):
    root = args.root
    if load(root, PLAN) is None:
        pending = interview_rounds(root)
        if pending:
            print_interview(root, pending)
            return 0
    text, tasks, malformed, header = load_plan(root)
    entries = parse_progress(load(root, PROGRESS))
    git_mode = is_git(root)
    errors, lint_warns, _ = lint_docs(root)

    counts = {m: len([t for t in tasks if t.mark == m]) for m in (" ", "~", "x", "!")}
    effort = os.environ.get("CLAUDE_EFFORT", "")
    print(f"Blueprint status (v{VERSION})  mode: {'git' if git_mode else 'folder (no git)'}  "
          f"target: {header.get('target') or '?'}"
          + (f"  version: {header['version']}" if header.get("version") else "")
          + f"  audit: {header.get('audit') or '?'}"
          + (f"  effort: {effort}" if effort else ""))
    print(f"Progress: {counts['x']}/{len(tasks)} done, {counts['~']} in progress, "
          f"{counts['!']} blocked, {counts[' ']} to do")
    done_ids = [t.id for t in tasks if t.mark == "x"]
    if done_ids:  # by ID only: a done task's title is in recall, and the list grows every task
        print(f"  [x] {', '.join(done_ids)}")
    for t in tasks:
        if t.mark == "x":
            continue
        size = t.fields.get("size", "")
        print(f"  [{t.mark}] {t.id:<6} {t.title}{'  (' + size + ')' if size else ''}"
              f"{'  ' + t.owner if t.owner else ''}")
    nested = nested_projects(root)
    if nested:
        print("Nested projects (their own plans, left out of every check here): "
              + ", ".join(p + "/" for p in nested))

    warns = []
    if errors:
        warns.append(f"lint: {len(errors)} error(s), e.g. {errors[0]} (run 'lint')")
    if (header.get("audit") or "").lower().startswith("pending") or not header.get("audit"):
        warns.append("STOP: the plan is not audited yet. Finish planning with "
                     f"{skill('architect')} first.")
    blocked = [t for t in tasks if t.mark == "!"]
    for t in blocked:
        warns.append(f"task {t.id} is BLOCKED; " + (
            f"/clear, then {skill('architect')} resolves it" if IN_CLAUDE else
            f"a new high-effort session with {skill('architect')} resolves it"))
    for e in pending_change_requests(entries):
        req = e.fields["change request"]
        warns.append(f"task {e.task}'s entry ({e.date}) holds a change request no Change entry has "
                     f"settled yet: \"{req[:90]}{'...' if len(req) > 90 else ''}\". Tell the user: "
                     f"{skill('architect')} plans it, defers it or declines it")

    if tasks and counts["x"] == len(tasks):
        if warns:  # v2 returned here without them; a hand-ticked last marker must still show
            print("\n=== WARNINGS ===")
            print("\n".join(f"- {w}" for w in warns))
        then = "/clear, then " if IN_CLAUDE else "a new high-effort session, then "
        if final_audit_state(tasks, entries) == "ACCEPTED":
            print(f"\nALL TASKS DONE, and the final audit accepted them. For a change or a new "
                  f"version: {then}{skill('architect')}.")
        else:
            print(f"\nALL TASKS DONE. Next: {then}{skill('architect')} for the final audit.")
        return 0

    waits = []
    nxt, resume = pick_next(tasks, args.task, root=root, waits=waits)
    warns += env_warnings(root, git_mode)
    if IN_CLAUDE and not any((Path(root) / p).is_file() for p in CLAUDE_FILES):
        warns.append("no CLAUDE.md here (a plan made in Codex?): AGENTS.md may not be loaded in this "
                     "session, so read it now; offer to add a CLAUDE.md whose only line is "
                     "@AGENTS.md (it loads from the next session)")
    if git_mode:
        warns += git_warnings(root, tasks, nxt, resume)
    else:
        print("Folder mode: 'start' saves a zip checkpoint in .blueprint/, 'restore' returns to it.")

    if nxt is None and waits:
        print("\nNo task is ready here: " + ("the next task waits" if len(waits) == 1 else
              "the next tasks wait") + " on another part's work.")
        for t, unmet in waits:
            print(f"  {t.id} {t.title} needs {'; '.join(unmet)}")
        print("Build those tasks first, each in a session opened in its part's folder; then "
              "come back here.")
    elif nxt is None:
        print("\nNo task is ready: the remaining tasks wait on blocked or unfinished tasks.")
    else:
        mode = "RESUME (in progress)" if resume else "NEW"
        print(f"\nNEXT: task {nxt.id} {nxt.title}   [{mode}]")
        print(f"\n=== TASK {nxt.id}  ({PLAN}, phase: {nxt.phase}) ===")
        print("\n".join(nxt.block))
        for label, text, problem in spec_sections(root, nxt):
            print(f"\n=== SPEC  ({label}) ===")
            if problem:
                print(f"(missing: {problem})")
                warns.append(f"task {nxt.id}'s Spec names {label}, but {problem}: something the "
                             f"task names doesn't exist (Stop early, case c)")
            else:
                print(text)
        ess = load(root, ESSENTIALS)
        print(f"\n=== ESSENTIALS  ({ESSENTIALS}) ===")
        print(ESS_MARKER_RE.sub("", ess).strip() if ess else "(missing)")
        nongoals = section(load(root, PRD), r"non-?goals")
        print(f"\n=== NON-GOALS  ({PRD}) ===")
        print(body_of(nongoals) or "(missing)")
        mine = task_entries(entries, nxt.id)
        if mine:
            print(f"\n=== EARLIER SESSIONS OF THIS TASK ({len(mine)}) - read 'Tried and failed' ===")
            print("\n\n".join(e.text for e in mine))
        print_history(tasks, nxt, entries, mine)
        if nxt.fields.get("size", "").upper().startswith("L"):
            warns.append(f"task {nxt.id} is size L: give it this whole session, run it supervised")
        if nxt.fields.get("stop"):
            warns.append(f"task {nxt.id} has a STOP point: {nxt.fields['stop']}")
        unmet = unmet_needs(root, nxt) if nxt.mark == " " else []
        if unmet:
            warns.append(f"task {nxt.id} waits on another part: {'; '.join(unmet)}. 'start' "
                         f"refuses it until then")

    print("\n=== WARNINGS ===")
    print("\n".join(f"- {w}" for w in warns) if warns else "none")
    return 0


# ----------------------------------------------------------------------------- start / done / block / reopen

def cmd_start(args):
    root = args.root
    text, tasks, _, _ = load_plan(root)
    t = find_task(tasks, args.id)
    if t.mark == "x":
        die(f"task {t.id} is already done. Use 'reopen' (architect) if it must be redone.")
    if t.mark == "!":
        die(f"task {t.id} is blocked. Resolve it with {skill('architect')} first.")
    resume = t.mark == "~"
    others = [x.id for x in tasks if x.mark == "~" and x.id != t.id]
    if others and not args.force:
        die(f"task(s) {', '.join(others)} already in progress; finish or record them first "
            f"(or --force).")
    done = {x.id for x in tasks if x.mark == "x"}
    missing = [d for d in t.deps if d not in done]
    if missing and not args.force:
        die(f"task {t.id} depends on unfinished task(s): {', '.join(missing)} (or --force).")
    unmet = [] if resume else unmet_needs(root, t)
    if unmet and not args.force:
        die(f"task {t.id} waits on another part: {'; '.join(unmet)}. Build that first, in a "
            f"session opened in its part's folder (or --force).")

    if is_git(root):
        if dirty_lines(root) and not resume and not args.force:
            die("uncommitted changes; commit or stash them so this task starts from a clean "
                "checkpoint (or --force).")
        _, head, _ = git(root, "rev-parse", "--short", "HEAD")
        checkpoint = f"git HEAD {head or '(no commits yet)'}"
    else:
        path, n = take_snapshot(root, t.id)
        checkpoint = f"snapshot {Path(path).relative_to(root).as_posix()} ({n} files)"

    save(root, PLAN, set_mark(text, t, "~", owner=args.owner))
    print(f"Task {t.id} {'resumed' if resume else 'started'} [~]. Checkpoint: {checkpoint}"
          f"{effort_note()}")
    return 0


def cmd_done(args):
    root = args.root
    text, tasks, _, _ = load_plan(root)
    t = find_task(tasks, args.id)
    if t.mark == "x":
        die(f"task {t.id} is already done.")
    if t.mark != "~":
        die(f"task {t.id} is not in progress; run 'start {t.id}' before building it.")
    mine = task_entries(parse_progress(load(root, PROGRESS)), t.id)
    if not mine or mine[-1].status != "done":
        die(f"add the progress entry first: '## <date>: Task {t.id} ...' with 'Status: done' "
            f"as the latest entry for this task in {PROGRESS}.")
    if not mine[-1].filled("checks"):
        die(f"the entry for task {t.id} needs a 'Checks:' line with the real results.")
    problem = digest_problem(mine[-1])
    if problem:
        die(f"the entry for task {t.id} {problem}: one line of at most {MAX_DIGEST} bytes saying "
            f"what later tasks consume (names, signatures, paths, shapes). status shows it to "
            f"every task that builds on this one.")
    text = set_mark(text, t, "x")
    save(root, PLAN, text)
    print(f"Task {t.id} marked done [x].{effort_note()}")
    nxt, _ = pick_next(parse_plan(text)[0], root=root)
    if nxt is not None:
        # The handoff names the next task's tier (references/models.md), which these fields
        # decide; printing them saves the session a read of plan.md.
        fields = [f"Size {nxt.fields.get('size') or '?'}"]
        fields += ["Spec"] if nxt.spec_refs else []
        fields += ["STOP"] if nxt.fields.get("stop") else []
        print(f"Next: task {nxt.id} {nxt.title} ({', '.join(fields)})")
    if is_git(root):
        paths = [l[3:] for l in dirty_lines(root)]
        print("Commit it now (review the list; never stage secrets):")
        print(f"  changed: {', '.join(paths[:15])}{' ...' if len(paths) > 15 else ''}")
        print(f'  git commit -m "task {t.id}: {t.title}"')
    else:
        print("Folder mode: no commit needed; the next task's 'start' takes a fresh checkpoint.")
    return 0


def cmd_block(args):
    root = args.root
    text, tasks, _, _ = load_plan(root)
    t = find_task(tasks, args.id)
    mine = task_entries(parse_progress(load(root, PROGRESS)), t.id)
    if not mine or mine[-1].status != "blocked":
        die(f"add the progress entry first: latest entry for task {t.id} with 'Status: blocked'.")
    if not mine[-1].filled("question"):
        die(f"the blocked entry for task {t.id} needs a 'Question:' line (one answerable sentence).")
    save(root, PLAN, set_mark(text, t, "!"))
    print(f"Task {t.id} marked blocked [!]. Next: " + ("/clear, then " if IN_CLAUDE else
          "a new high-effort session and ") + f"{skill('architect')} to resolve it.")
    return 0


def cmd_reopen(args):
    root = args.root
    text, tasks, _, _ = load_plan(root)
    t = find_task(tasks, args.id)
    if t.mark == "x" and not args.force:
        mine = task_entries(parse_progress(load(root, PROGRESS)), t.id)
        if mine and mine[-1].status == "done" and mine[-1].filled("checks"):
            # Its done entry would let 'done' pass again without a new session's entry.
            die(f"task {t.id} is done, with its done entry. Rework on finished work is a new task "
                f"(the change flow); --force reopens it anyway, and its next session must then "
                f"write a new entry before 'done'.")
    save(root, PLAN, set_mark(text, t, " "))
    print(f"Task {t.id} reopened [ ].")
    return 0


# ----------------------------------------------------------------------------- diff / restore

def print_file_diff(rel, old_bytes, new_bytes):
    try:
        old = old_bytes.decode("utf-8").splitlines(keepends=True) if old_bytes is not None else []
        new = new_bytes.decode("utf-8").splitlines(keepends=True) if new_bytes is not None else []
    except UnicodeDecodeError:
        print(f"Binary file changed: {rel}")
        return
    a = f"a/{rel}" if old_bytes is not None else "/dev/null"
    b = f"b/{rel}" if new_bytes is not None else "/dev/null"
    sys.stdout.writelines(difflib.unified_diff(old, new, fromfile=a, tofile=b))
    if new and not new[-1].endswith("\n"):
        print()


def print_new_file(root, rel):
    """A new file as a diff from nothing; a big one (a lockfile, a fixture) as a one-line note."""
    p = Path(root) / rel
    if not p.is_file():
        return
    size = p.stat().st_size
    if size > MAX_DIFF_NEW_FILE:
        print(f"New file {rel} ({size // 1024} KB): too big to show here; open it if the review "
              f"needs it.")
    else:
        print_file_diff(rel, None, p.read_bytes())


def cmd_diff(args):
    root = args.root
    _, tasks, _, _ = load_plan(root)
    tid = active_task_id(tasks, args.id)
    if is_git(root):
        print(f"Changes for task {tid} since the last commit (docs/plan.md and docs/progress.md "
              f"omitted):\n")
        spec = exclude_spec(root)
        _, st, _ = git(root, "status", "--short", "--", ".", *spec)
        print(st or "(no changes)")
        if has_head(root):
            _, d, _ = git(root, "diff", "HEAD", "--", ".", *spec)
        else:
            _, d, _ = git(root, "diff", "--", ".", *spec)
        if d:
            print("\n" + d)
        # -z: names exactly as on disk (git quotes unusual names otherwise, and the file was missed)
        _, untracked, _ = git(root, "ls-files", "-z", "--others", "--exclude-standard", "--", ".",
                              *spec)
        for rel in [u for u in untracked.split("\0") if u.strip()]:
            print_new_file(root, rel)
        return 0
    snaps = snapshots(root, tid)
    if not snaps:
        die(f"no checkpoint for task {tid}; 'start {tid}' takes one.")
    changed, added, deleted = compare_snapshot(root, snaps[-1])
    print(f"Changes for task {tid} since {snaps[-1].name} "
          f"({len(changed)} changed, {len(added)} added, {len(deleted)} deleted):\n")
    with zipfile.ZipFile(snaps[-1]) as z:
        for rel in changed:
            print_file_diff(rel, z.read(rel), (Path(root) / rel).read_bytes())
        for rel in added:
            print_new_file(root, rel)
        for rel in deleted:
            print(f"Deleted: {rel}")
    if not (changed or added or deleted):
        print("(no changes)")
    return 0


def cmd_restore(args):
    root = args.root
    _, tasks, _, _ = load_plan(root)
    tid = args.id
    find_task(tasks, tid)
    if is_git(root):
        if not has_head(root):
            die("no commit yet, so there is no checkpoint to return to. Commit the plan first.")
        msg = f"blueprint: task {tid} failed attempt {datetime.datetime.now():%Y-%m-%d %H:%M}"
        code, out, err = git(root, "stash", "push", "--include-untracked", "-m", msg, "--",
                             ".", *exclude_spec(root))
        if code != 0:
            die(f"git stash failed: {err or out}")
        if "No local changes" in out or not out:
            print("Nothing to restore: no changes since the last commit.")
            return 0
        print(f"Attempt set aside ({out}). The work is recoverable: 'git stash list', then "
              f"'git stash apply stash@{{0}}'. docs/plan.md and docs/progress.md were kept.")
        return 0
    snaps = snapshots(root, tid)
    if not snaps:
        die(f"no checkpoint for task {tid} in {STATE_DIR}/snapshots.")
    changed, added, deleted = compare_snapshot(root, snaps[-1])
    if not (changed or added or deleted):
        print("Nothing to restore: no changes since the checkpoint.")
        return 0
    aside = Path(root) / STATE_DIR / "attempts" / f"task-{tid}-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    for rel in changed + added:
        dst = aside / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(root) / rel, dst)
    for rel in added:
        (Path(root) / rel).unlink()
    with zipfile.ZipFile(snaps[-1]) as z:
        for rel in changed + deleted:
            dst = Path(root) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(z.read(rel))
    print(f"Restored {len(changed) + len(deleted)} file(s) and set aside {len(added)} new file(s) "
          f"from {snaps[-1].name}.")
    print(f"The failed attempt is kept in {aside.relative_to(root).as_posix()}/ "
          f"(docs/plan.md and docs/progress.md untouched).")
    return 0


# ----------------------------------------------------------------------------- recall

def outline(text):
    """[(line index, indent, title, level)] for each heading of a doc, and each task line of a
    plan (level 7: below every heading)."""
    out, level = [], 1
    for i, line in enumerate(text.split("\n")):
        m = HEADING_RE.match(line)
        if m:
            level = len(m.group("hashes"))
            out.append((i, level - 1, line.strip(), level))
        elif TASK_RE.match(line):
            out.append((i, level, line.strip(), 7))  # a task sits under its phase heading
    return out


def labelled_lines(text, newest_first=False):
    """[(label, line)] for each line of a doc, labelled with the heading or task it is under.
    `newest_first` reverses the order of the labelled groups (progress.md is appended)."""
    groups, label = [[None, []]], None
    for line in text.split("\n"):
        h, t = HEADING_RE.match(line), TASK_RE.match(line)
        if h or t:
            label = (h.group("title") if h else
                     f"task {t.group('id')} {OWNER_RE.sub('', t.group('title')).strip(' -—:')}")
            groups.append([label, []])
        groups[-1][1].append(line)
    if newest_first:
        groups = groups[:1] + groups[1:][::-1]
    return [(label, line) for label, lines in groups for line in lines]


def around(line, m):
    """`line` cut to RECALL_LINE chars around the match `m`."""
    if len(line) <= RECALL_LINE:
        return line
    start = max(0, min(m.start() - RECALL_LINE // 3, len(line) - RECALL_LINE))
    end = start + RECALL_LINE
    return ("..." if start else "") + line[start:end] + ("..." if end < len(line) else "")


def recall_task(root, tid):
    text, tasks, _, _ = load_plan(root, required=False)
    t = next((x for x in tasks if x.id == tid), None)
    mine = task_entries(parse_progress(load(root, PROGRESS)), tid)
    if t is None and not mine:
        die(f"task {tid} is in neither {PLAN} nor {PROGRESS}.")
    if t is not None:
        print(f"=== TASK {t.id}  ({PLAN}, phase: {t.phase}) [{t.mark}] ===")
        print("\n".join(t.block))
    print(f"\n=== ENTRIES FOR TASK {tid} ({len(mine)}) ===")
    print("\n\n".join(e.text for e in mine) if mine else "none yet")
    return 0


def recall_doc(root, rel, heading):
    text = load(root, rel)
    items = outline(text)
    if heading is None:
        lines = text.split("\n")
        print(f"=== OUTLINE  ({rel}, {len(text):,} chars) ===")
        for k, (i, indent, title, level) in enumerate(items):
            end = next((j for j, _, _, lv in items[k + 1:] if lv <= level), len(lines))
            size = len("\n".join(lines[i:end]))
            print(f"{'  ' * indent}{title}  ({size:,} chars)")
        if not items:
            print("(no headings)")
        print(f"Open one with: recall '{rel}#<Heading>'")
        return 0
    sec = section(text, r"^\s*" + re.escape(heading) + r"\s*$") or \
        section(text, re.escape(heading))
    if sec is None:
        die(f"{rel} has no heading like '{heading}'. Its outline: recall {rel}")
    if len(sec) > RECALL_CHARS:
        sec = sec[:RECALL_CHARS].rsplit("\n", 1)[0] + (
            f"\n... (cut at {RECALL_CHARS:,} chars: recall '{rel}' shows its sub-headings)")
    print(f"=== {rel}#{heading} ===")
    print(sec)
    return 0


def recall_regex(root, query):
    try:
        rx = re.compile(query, re.I)
    except re.error:
        rx = re.compile(re.escape(query), re.I)
    docs = [PROGRESS, PLAN] + sorted(
        f"docs/{p.name}" for p in (Path(root) / "docs").glob("*.md")
        if f"docs/{p.name}" not in (PROGRESS, PLAN))
    hits = []
    for rel in docs:
        text = load(root, rel)
        for label, line in labelled_lines(text or "", newest_first=(rel == PROGRESS)):
            m = rx.search(line)
            if m:
                hits.append((f"{rel}" + (f" · {label}" if label else ""), around(line.strip(), m)))
    if not hits:
        print(f"No match for '{query}' in docs/*.md.")
        return 1
    size, shown, last = 0, 0, None
    for where, line in hits:
        add = len(line) + 3 + (len(where) + 1 if where != last else 0)
        if shown and size + add > RECALL_CHARS:
            break
        if where != last:
            print(where)
            last = where
        print(f"  {line}")
        size, shown = size + add, shown + 1
    if shown < len(hits):
        print(f"({shown} of {len(hits)} matching lines; narrow the regex, or recall a task ID "
              f"or a doc section)")
    return 0


def cmd_recall(args):
    """One thing from the docs, instead of a whole doc in the session's context: a task (its
    plan block and every progress entry), a doc's outline, one section of it, or the lines
    that match a regex, each labelled with the heading or task it sits under."""
    root, q = args.root, args.query.strip()
    if re.fullmatch(r"\d+\.\d+", q):
        return recall_task(root, q)
    path, hash_, heading = q.partition("#")
    if (Path(root) / path).is_file():
        return recall_doc(root, path.replace("\\", "/"), heading.strip() or None if hash_ else None)
    return recall_regex(root, q)


# ----------------------------------------------------------------------------- retro

def cmd_retro(args):
    root = args.root
    _, tasks, _, header = load_plan(root)
    entries = parse_progress(load(root, PROGRESS))
    git_mode = is_git(root)
    subjects = []
    if git_mode and has_head(root):
        subjects = git(root, "log", "HEAD", "--format=%s", "--", ".",
                       *nested_spec(root))[1].split("\n")

    print(f"# Retro metrics  (target {header.get('target')}, {len(tasks)} tasks, "
          f"{'git' if git_mode else 'folder'} mode)\n")
    counts = {m: len([t for t in tasks if t.mark == m]) for m in (" ", "~", "x", "!")}
    print(f"Done {counts['x']} · in progress {counts['~']} · blocked {counts['!']} · "
          f"to do {counts[' ']}")
    kinds = {}
    for e in entries:
        kinds[e.kind] = kinds.get(e.kind, 0) + 1
    print("Entries by kind: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    fix_tasks = [t.id for t in tasks if re.search(r"fix", t.phase, re.I)]
    print(f"Tasks added by audits (phases named '...fix...'): {len(fix_tasks)} "
          f"{', '.join(fix_tasks)}")

    rows = []
    for t in tasks:
        mine = task_entries(entries, t.id)
        sessions = len(mine)
        partial = len([e for e in mine if e.status == "partial"])
        blocked = len([e for e in mine if e.status == "blocked"])
        corrected = [e.fields.get("plan check", "") for e in mine
                     if e.fields.get("plan check", "").lower().startswith("corrected")]
        commits = len([s for s in subjects if re.match(rf"task {re.escape(t.id)}\b", s)])
        score = max(sessions - 1, 0) + 2 * blocked + len(corrected)
        rows.append((score, t, sessions, partial, blocked, corrected, commits))

    print("\n## Per task (sessions = progress entries)\n")
    print("| Task | Size | Sessions | Partial | Blocked | Plan corrected | Commits |")
    print("|---|---|---|---|---|---|---|")
    for score, t, s, p, b, c, k in rows:
        print(f"| {t.id} {t.title[:40]} | {t.fields.get('size', '-')} | {s} | {p} | {b} | "
              f"{len(c)} | {k if git_mode else '-'} |")

    worst = sorted([r for r in rows if r[0] > 0], key=lambda r: -r[0])[:5]
    print("\n## Bottlenecks (score = extra sessions + 2 x blocked + plan corrections)\n")
    if not worst:
        print("none: every task finished in one session with no plan correction")
    for score, t, s, p, b, c, k in worst:
        print(f"- {t.id} {t.title}: score {score} ({s} sessions, {b} blocked, {len(c)} corrected)")
        for note in c:
            print(f"    plan check: {note}")

    print("\n## Raw notes for the retrospective\n")
    for key in ("tried and failed", "gotchas", "left open", "blocked because", "question",
                "change request"):
        items = [(e.task or e.kind, e.fields[key]) for e in entries
                 if e.filled(key) and e.fields[key].lower() not in NO_VALUE]
        if items:
            print(f"### {key.title()}")
            for who, val in items:
                print(f"- [{who}] {val}")
            print()
    changes = [e for e in entries if e.kind in ("change", "audit")]
    if changes:
        print("### Change and audit entries")
        for e in changes:
            print(f"- {e.date}: {e.head}")
    return 0


# ----------------------------------------------------------------------------- archive

def cmd_archive(args):
    """Close a version: its planning docs go to docs/archive/LABEL/ (a move here, or a copy into
    another folder with --to), so the next version starts fresh docs at the standard paths."""
    root = args.root
    label = args.label
    if not LABEL_RE.fullmatch(label):
        die(f"'{label}' isn't a usable label: use a short name such as v1 or phase-1 "
            f"(letters, digits, '.', '_' or '-').", 2)
    _, tasks, _, header = load_plan(root)
    entries = parse_progress(load(root, PROGRESS))
    still_open = [t.id for t in tasks if t.mark != "x"]
    if still_open and not args.force:
        die(f"task(s) {', '.join(still_open)} aren't done. Finish them, or have "
            f"{skill('architect')} drop the unstarted ones into the PRD's Later list, before "
            f"closing this version (or --force).")
    state = final_audit_state(tasks, entries)
    if state != "ACCEPTED" and not args.force:
        die(f"no accepted final audit follows the last task entry (final audit: {state}). Run "
            f"it with {skill('architect')} before closing this version (or --force).")
    base = Path(args.to).resolve() if args.to else Path(root)
    dest = base / ARCHIVE / label
    if dest.exists():
        die(f"{shown(dest, root)} already exists; pick another label.")
    present = [rel for rel in ARCHIVED if (Path(root) / rel).is_file()]
    if not present:
        die("no planning docs to archive here.")
    git_mode = is_git(root) and not args.to
    dest.mkdir(parents=True)
    for rel in present:
        src, dst = Path(root) / rel, dest / Path(rel).name
        if args.to:
            shutil.copy2(src, dst)
        elif git_mode and git(root, "ls-files", "--error-unmatch", "--", rel)[0] == 0:
            code, out, err = git(root, "mv", "--", rel, f"{ARCHIVE}/{label}/{Path(rel).name}")
            if code != 0:
                die(f"git mv {rel} failed: {err or out}")
        else:
            shutil.move(str(src), str(dst))
    ids = [t.id for t in tasks]
    start = max((id_key(i)[0] for i in ids), default=0) + 1
    print(f"{'Copied' if args.to else 'Moved'} {len(present)} file(s) to {shown(dest, root)}/: "
          + ", ".join(Path(rel).name for rel in present) + ".")
    print(f"Version {label}" + (f" (plan header: {header['version']})" if header.get("version")
                                else "")
          + (f": tasks {ids[0]}-{ids[-1]}" if ids else "") + f", final audit {state}"
          + (f", still open: {', '.join(still_open)}" if still_open else "") + ".")
    print(f"Number the next version's phases from {start} (first task {start}.1), so task IDs "
          f"and 'task <id>:' commits stay unique.")
    if git_mode:
        print(f'Commit it now: git commit -m "plan: <project> {label} archived"')
    if args.to:
        print(f"Next: open a session in {base.as_posix()}, then {skill('architect')} to plan the "
              f"next version there.")
    else:
        print(f"Next: plan the next version here with {skill('architect')}.")
    return 0


# ----------------------------------------------------------------------------- program

def cmd_program(args):
    """Every part of the program this folder belongs to: progress, audits, next task, waits."""
    root = args.root
    program = find_program(root)
    if program is None:
        die(f"no {PROGRAM} at or above this folder lists it as a part. A program root holds "
            f"{PROGRAM} with a Parts table (Part, Folder, ...); plan one with "
            f"{skill('architect')}.")
    proot = program["root"]
    print(f"Program: {shown(proot / PROGRAM, root)}  ({len(program['parts'])} part(s))"
          + (f"  this folder: {program['self']}" if program["self"] else ""))
    rounds = open_rounds(program["text"])
    if rounds:
        print(f"Program interview in progress: {len(rounds)} round(s) still to ask: "
              + "; ".join(rounds))
    if not program["parts"]:
        print("No parts: the Parts table needs rows with a Part and a Folder.")
        return 1
    problems = 0
    for name, folder in program["parts"].items():
        where = shown(folder, root) + "/"
        if not folder.is_dir():
            print(f"\n- {name} ({where}): FOLDER MISSING")
            problems += 1
            continue
        text = load(folder, PLAN)
        if text is None:
            left = open_rounds(load(folder, PRD))
            print(f"\n- {name} ({where}): "
                  + (f"interview in progress ({len(left)} round(s) still to ask)" if left
                     else "not planned yet"))
            continue
        tasks, _, header = parse_plan(text)
        entries = parse_progress(load(folder, PROGRESS))
        counts = {m: len([t for t in tasks if t.mark == m]) for m in (" ", "~", "x", "!")}
        print(f"\n- {name} ({where}): {counts['x']}/{len(tasks)} done, {counts['~']} in progress, "
              f"{counts['!']} blocked; target {header.get('target') or '?'}"
              + (f", version {header['version']}" if header.get("version") else "")
              + f"; plan audit {header.get('audit') or '?'}; final audit "
              f"{final_audit_state(tasks, entries)}")
        waits = []
        nxt, resume = pick_next(tasks, root=str(folder), waits=waits)
        if nxt is not None:
            print(f"    next: {nxt.id} {nxt.title}{'  (in progress)' if resume else ''}")
        for t, unmet in waits:
            print(f"    waiting: {t.id} {t.title} needs {'; '.join(unmet)}")
        for t in tasks:
            if t.mark == "!":
                print(f"    blocked: {t.id} {t.title}")
        errors, _ = needs_checks(str(folder), tasks)
        for e in errors:
            print(f"    problem: {e}")
            problems += 1
    _, contracts, _ = table_rows(program["text"], r"^contracts\b")
    if contracts:
        print("\nContracts:")
        for rec in contracts:
            path = next(iter(rec.values()), "").strip("` ")
            if not path or path.startswith("<"):
                continue
            ok = (proot / path).is_file()
            problems += not ok
            print(f"  {'ok     ' if ok else 'MISSING'} {path}  "
                  + "  ".join(f"{k}: {v}" for k, v in list(rec.items())[1:] if v))
    print(f"\n{problems} problem(s).")
    return 1 if problems else 0


# ----------------------------------------------------------------------------- main

def stdout_closed(exc):
    """True when `exc` came from writing to a stdout the reader closed (`blueprint.py diff |
    head`): a BrokenPipeError, or on Windows an OSError EINVAL that a flush raises again."""
    if isinstance(exc, BrokenPipeError):
        return True
    if exc.errno not in (errno.EPIPE, errno.EINVAL):
        return False
    try:
        sys.stdout.flush()
    except OSError:
        return True
    return False


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="project root (default: current folder)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status", help="progress, next task and its kickoff bundle")
    s.add_argument("--task", help="show this task instead of the next one")
    s = sub.add_parser("start", help="mark a task [~] and checkpoint")
    s.add_argument("id")
    s.add_argument("--owner", help="name to show as the task's claim")
    s.add_argument("--force", action="store_true")
    for name, hlp in (("done", "mark [x]"), ("block", "mark [!]"), ("reopen", "mark [ ]"),
                      ("restore", "undo a failed attempt")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("id")
        if name == "reopen":
            s.add_argument("--force", action="store_true",
                           help="reopen a task that is done with its done entry")
    s = sub.add_parser("diff", help="changes since the task's checkpoint")
    s.add_argument("id", nargs="?")
    sub.add_parser("lint", help="check the planning docs")
    s = sub.add_parser("deps", help="look up dependencies on npm / PyPI")
    s.add_argument("--write", action="store_true", help="fill the Verified column")
    sub.add_parser("stamp", help="stamp the essentials with architecture.md's hash")
    sub.add_parser("retro", help="metrics for a retrospective")
    s = sub.add_parser("archive", help="close a version: move its docs to docs/archive/LABEL/")
    s.add_argument("label", help="the version's name, e.g. v1")
    s.add_argument("--to", metavar="DIR",
                   help="copy the docs into DIR/docs/archive/LABEL/ instead (the next version "
                        "lives in a new folder); this project stays as it is")
    s.add_argument("--force", action="store_true",
                   help="archive with open tasks or without an accepted final audit")
    sub.add_parser("program", help="every part of the program this folder belongs to")
    s = sub.add_parser("recall", help="one thing from the docs: a task, an outline, a section, "
                                      "or the lines matching a regex")
    s.add_argument("query", help="a task ID (2.3), a doc (docs/architecture.md), a section "
                                 "(docs/architecture.md#Ranking), or a regex")
    args = ap.parse_args()
    args.root = str(Path(args.root).resolve())
    handlers = {"status": cmd_status, "start": cmd_start, "done": cmd_done, "block": cmd_block,
                "reopen": cmd_reopen, "diff": cmd_diff, "restore": cmd_restore, "lint": cmd_lint,
                "deps": cmd_deps, "stamp": cmd_stamp, "retro": cmd_retro,
                "archive": cmd_archive, "program": cmd_program, "recall": cmd_recall}
    return handlers[args.cmd](args)


if __name__ == "__main__":
    try:
        code = main() or 0
        sys.stdout.flush()
    except OSError as exc:  # BrokenPipeError included
        if not stdout_closed(exc):
            raise
        try:  # the reader is gone: say nothing more, and don't fail on the final flush
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except OSError:
            pass
        code = 0
    sys.exit(code)
