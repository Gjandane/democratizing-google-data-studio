"""Repo-readiness check before a push (task 3.2).

    git fetch origin
    uv run --project integration python integration/check_repo.py

Checks the remote, .gitattributes, every tracked .env.example, the tracked paths, every path and
blob in history, the history text for key patterns and for the .env secret values, HEAD's tracked
files for the private .env values (hosted URL, project number), nested repositories and that
origin/main is an ancestor of HEAD. Read-only. Never prints a secret value:
a hit names the commit and file only. Prints one PASS/FAIL line per check and exits 1 if any fails.
"""

import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = "https://github.com/Gjandane/democratizing-google-data-studio"
PARTS = ["engine", "backend", "frontend"]
ATTRIBUTES_REQUIRED = ["samples/*.csv -text", "*.sh text eol=lf"]
EXAMPLE_EMPTY = ["GOOGLE_API_KEY", "DSS_ACCESS_CODE", "DSS_AGENT_TOKEN", "GCP_PROJECT_ID",
                 "GCS_BUCKET", "DSS_TEMPLATE_REPORT_ID", "DSS_AGENT_SERVER", "DSS_CHROME_PATH",
                 "DSS_DB_PATH"]
SECRET_NAMES = ["GOOGLE_API_KEY", "DSS_ACCESS_CODE", "DSS_AGENT_TOKEN"]
# Private, not secret (change 2026-10-29): kept out of HEAD's tracked files; history predates the rule.
PRIVATE_NAMES = ["DSS_AGENT_SERVER", "GCP_PROJECT_NUMBER"]
# Split literals so this file never matches its own patterns once committed.
KEY_PATTERNS = {
    "Google API key": re.compile(rb"AIza[0-9A-Za-z_-]{35}"),
    "private key": re.compile(rb"BEGIN (RSA |EC )?PRIVATE KEY"),
    "OAuth client secret": re.compile(rb"GOCSPX" + rb"-"),
    "OAuth refresh token": re.compile(rb'"refresh' + rb'_token"'),
}
# Only these matches are bare prefixes, so a `quoted` one is the plan text, never a secret.
DOC_MENTION_LABELS = {"OAuth client secret", "OAuth refresh token"}
BLOB_LIMIT = 100 * 1024 * 1024
BLOB_WARN = 10 * 1024 * 1024
SKIP_DIRS = {"node_modules", ".venv"}


class CheckFailed(Exception):
    pass


def git(*args, check=True):
    proc = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=ROOT, capture_output=True)
    if check and proc.returncode != 0:
        raise CheckFailed(f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc


def git_lines(*args):
    return [line for line in git(*args).stdout.decode("utf-8", errors="replace").splitlines() if line]


def is_env_file(path):
    name = PurePosixPath(path).name
    return (name == ".env" or name.startswith(".env.")) and name != ".env.example"


def check_remote():
    url = git("remote", "get-url", "origin").stdout.decode().strip()
    if url not in (ORIGIN, ORIGIN + ".git"):
        raise CheckFailed(f"origin is {re.sub(r'//[^/@]*@', '//', url)}, expected {ORIGIN}(.git)")
    return url


def check_gitattributes():
    path = ROOT / ".gitattributes"
    if not path.exists():
        raise CheckFailed(".gitattributes is missing")
    lines = {" ".join(line.split()) for line in path.read_text(encoding="utf-8").splitlines()}
    missing = [rule for rule in ATTRIBUTES_REQUIRED if rule not in lines]
    if missing:
        raise CheckFailed(f"missing: {', '.join(missing)}")
    return ", ".join(ATTRIBUTES_REQUIRED)


def parse_env(text):
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1].strip()
        values[name] = value
    return values


def check_env_examples():
    examples = [p for p in git_lines("ls-files") if PurePosixPath(p).name == ".env.example"]
    if ".env.example" not in examples:
        raise CheckFailed("root .env.example is not tracked")
    problems = []
    for path in examples:
        values = parse_env((ROOT / path).read_text(encoding="utf-8"))
        for name in EXAMPLE_EMPTY:
            if name in values and values[name]:
                problems.append(f"{path}: {name} has a value")
            elif name not in values and path == ".env.example":
                problems.append(f"{path}: {name} is missing")
    if problems:
        raise CheckFailed("; ".join(problems))
    return f"{len(examples)} file(s), {len(EXAMPLE_EMPTY)} names empty: {', '.join(examples)}"


def forbidden_tracked(path):
    parts = PurePosixPath(path).parts
    if is_env_file(path):
        return "env file"
    if parts[0] == "data":
        return "root data/"
    for bad in (".chrome-profile", "node_modules", ".venv", ".blueprint"):
        if bad in parts[:-1]:
            return f"{bad}/"
    if path.startswith("deck/render/"):
        return "deck/render/"
    if parts[-1].startswith("~$"):
        return "Office lock file"
    return None


def check_tracked_paths():
    files = git_lines("ls-files")
    hits = [f"{p} ({why})" for p in files if (why := forbidden_tracked(p))]
    if hits:
        raise CheckFailed("tracked: " + "; ".join(hits))
    return f"{len(files)} tracked files, none forbidden"


def forbidden_history(path):
    parts = PurePosixPath(path).parts
    if is_env_file(path):
        return "env file"
    if ".chrome-profile" in parts[:-1]:
        return ".chrome-profile/"
    if parts[0] == "data" and len(parts) > 1:
        return "root data/"
    if "screens" in parts[:-1]:
        return "screens/"
    if parts[-1].endswith(".sqlite"):
        return "*.sqlite"
    return None


def check_history_paths():
    paths = set(git_lines("log", "--all", "--name-only", "--format="))
    hits = []
    for path in sorted(paths):
        why = forbidden_history(path)
        if why:
            commit = git_lines("log", "--all", "-1", "--format=%h", "--", path)
            hits.append(f"{path} ({why}, commit {commit[0] if commit else '?'})")
    if hits:
        raise CheckFailed("in history: " + "; ".join(hits))
    return f"{len(paths)} paths ever committed, none forbidden"


def check_blob_sizes():
    objects = git("rev-list", "--objects", "--all").stdout
    proc = subprocess.run(
        ["git", "cat-file", "--batch-check=%(objecttype) %(objectname) %(objectsize) %(rest)"],
        cwd=ROOT, input=objects, capture_output=True, check=True)
    big, too_big = [], []
    for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
        kind, _, size, *rest = line.split(" ", 3)
        if kind != "blob":
            continue
        size = int(size)
        name = rest[0] if rest else "?"
        if size > BLOB_LIMIT:
            too_big.append(f"{name} ({size / 2**20:.1f} MB)")
        elif size > BLOB_WARN:
            big.append(f"{name} ({size / 2**20:.1f} MB)")
    if too_big:
        raise CheckFailed("over 100 MB: " + "; ".join(too_big))
    if big:
        return "none over 100 MB; over 10 MB, for the user: " + "; ".join(big)
    return "no blob over 10 MB"


def read_env_values(names):
    env_path = ROOT / ".env"
    values = parse_env(env_path.read_text(encoding="utf-8-sig")) if env_path.exists() else {}
    return {name: values.get(name, "") for name in names}


def private_needle(name, value):
    """The URL's host (scheme and trailing slash dropped, so a bare host also hits); else the value."""
    if name == "DSS_AGENT_SERVER":
        value = re.sub(r"^[a-z]+://", "", value, flags=re.I).rstrip("/")
    return value


def check_head_private(private_values):
    hits, checked, skipped = [], [], []
    for name, value in private_values.items():
        needle = private_needle(name, value)
        if not needle:
            skipped.append(f"{name} skipped (empty)")
            continue
        checked.append(name)
        proc = git("grep", "-l", "-F", "-i", "-e", needle, "HEAD", check=False)
        if proc.returncode not in (0, 1):
            raise CheckFailed(f"git grep failed for {name}")
        files = [line.split(":", 1)[1] for line in proc.stdout.decode("utf-8", errors="replace").splitlines() if line]
        if files:
            hits.append(f".env {name} value in " + ", ".join(files))
    if hits:
        raise CheckFailed("; ".join(hits))
    note = f".env values not in HEAD's tracked files: {', '.join(checked) or 'none'}"
    if skipped:
        note += "; " + "; ".join(skipped)
    return note


def doc_mention(line, match):
    """A pattern quoted as `code` in Markdown (the plan's own Done when): not a secret."""
    return line[match.start() - 1:match.start()] == b"`" and line[match.end():match.end() + 1] == b"`"


def scan_history(needles, key_labels):
    """Stream `git log -p --all` (messages included). Return (hits, mentions): {label: [(commit, file)]} for each
    needle that hits, and the key-pattern hits that are only `code` mentions in .md files.
    needles maps label -> compiled bytes regex."""
    hits, mentions = {}, {}
    proc = subprocess.Popen(["git", "-c", "core.quotePath=false", "log", "-p", "--all",
                             "--format=commit %H%n%B"],
                            cwd=ROOT, stdout=subprocess.PIPE)
    commit, file = "?", "?"
    for line in proc.stdout:
        if line.startswith(b"commit ") and len(line.strip()) == 47:
            commit, file = line[7:15].decode(), "(commit message)"
            continue
        if line.startswith(b"diff --git "):
            file = line.rstrip().split(b" b/", 1)[-1].decode("utf-8", errors="replace")
            continue
        for label, pattern in needles.items():
            for match in pattern.finditer(line):
                quoted = label in key_labels and file.endswith(".md") and doc_mention(line, match)
                bucket = (mentions if quoted else hits).setdefault(label, [])
                if (commit, file) not in bucket:
                    bucket.append((commit, file))
    proc.wait()
    if proc.returncode != 0:
        raise CheckFailed("git log -p --all failed")
    return hits, mentions


def check_history_text(secret_values):
    needles = dict(KEY_PATTERNS)
    skipped = []
    for name, value in secret_values.items():
        if value:
            needles[f".env {name} value"] = re.compile(re.escape(value.encode("utf-8")))
        else:
            skipped.append(f"{name} skipped (empty)")
    hits, mentions = scan_history(needles, DOC_MENTION_LABELS)

    def where(found):
        return "; ".join(f"{label} in " + ", ".join(f"{c} {f}" for c, f in places)
                         for label, places in found.items())

    if hits:
        raise CheckFailed(where(hits))
    checked = [n for n, v in secret_values.items() if v]
    note = f"no key pattern; .env values not in history: {', '.join(checked) or 'none'}"
    if skipped:
        note += "; " + "; ".join(skipped)
    if mentions:
        note += "; `code` mentions in docs only: " + where(mentions)
    return note


def check_nested_repos():
    gitlinks = [line.split("\t", 1)[1] for line in git_lines("ls-files", "-s")
                if line.startswith("160000 ")]
    if gitlinks:
        raise CheckFailed("gitlinks (submodules) tracked: " + ", ".join(gitlinks))
    repos, pointers = [], []
    for part in PARTS:
        base = ROOT / part
        if not base.is_dir():
            continue
        stack = [base]
        while stack:
            folder = stack.pop()
            for child in folder.iterdir():
                if child.name == ".git":
                    # A .git file (a worktree of this repo, a tool cache) is not a nested repo.
                    (repos if child.is_dir() else pointers).append(child.parent.relative_to(ROOT).as_posix())
                elif child.is_dir() and not child.is_symlink() and child.name not in SKIP_DIRS:
                    stack.append(child)
    if repos:
        raise CheckFailed("nested .git folders: " + ", ".join(repos))
    note = "no nested .git under " + ", ".join(PARTS)
    if pointers:
        note += f"; .git files only (not repositories): {', '.join(pointers)}"
    return note


def check_ancestor():
    if git("rev-parse", "--verify", "--quiet", "origin/main", check=False).returncode != 0:
        raise CheckFailed("origin/main not found: run `git fetch origin` first")
    if git("merge-base", "--is-ancestor", "origin/main", "HEAD", check=False).returncode != 0:
        raise CheckFailed("origin/main is not an ancestor of HEAD (no force-push: STOP)")
    head = git("rev-parse", "--short", "HEAD").stdout.decode().strip()
    base = git("rev-parse", "--short", "origin/main").stdout.decode().strip()
    return f"origin/main {base} is an ancestor of HEAD {head}"


def main():
    results = []

    def run(name, fn, *args):
        try:
            results.append((True, name, fn(*args)))
        except CheckFailed as e:
            results.append((False, name, str(e)))
        except Exception as e:   # unforeseen input: still a FAIL line, never a traceback with data
            results.append((False, name, type(e).__name__))

    run("remote", check_remote)
    run(".gitattributes", check_gitattributes)
    run(".env.example files", check_env_examples)
    run("tracked paths", check_tracked_paths)
    run("history paths", check_history_paths)
    run("blob sizes", check_blob_sizes)
    try:
        secret_values = read_env_values(SECRET_NAMES)
        private_values = read_env_values(PRIVATE_NAMES)
    except Exception as e:
        secret_values = private_values = None
        results.append((False, "history text", f".env unreadable: {type(e).__name__}"))
    if secret_values is not None:
        run("history text", check_history_text, secret_values)
        run("HEAD private values", check_head_private, private_values)
    run("nested repos", check_nested_repos)
    run("origin/main ancestor", check_ancestor)

    for ok, name, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    failed = sum(not ok for ok, _, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
