"""Contract conformance check for the release part (Test (all)).

    uv run --project integration python integration/check_contracts.py

Validates the shared fixtures in contracts/ against contracts/recipe.md, recipe.schema.json and
api.md, and the root files that mirror contracts/conventions.md (.env.example, .gitignore).
Read-only. Prints one PASS/FAIL line per check and exits 1 if any check fails.
"""

import copy
import datetime as dt
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import best_match

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
FIXTURES = CONTRACTS / "fixtures"
API_FIXTURES = FIXTURES / "api"

SECRETS_EMPTY = ["GOOGLE_API_KEY", "DSS_ACCESS_CODE", "DSS_AGENT_TOKEN", "DSS_DB_PATH"]
# .gitignore requirement -> accepted spellings. /data/ is anchored so deck/data/ stays tracked.
GITIGNORE_REQUIRED = {
    ".env": {".env"},
    "/data/": {"/data/", "/data"},
    ".chrome-profile/": {".chrome-profile/", "/.chrome-profile/", ".chrome-profile",
                         "/.chrome-profile"},
    ".venv/": {".venv/", ".venv"},
    "node_modules/": {"node_modules/", "node_modules", "/node_modules/"},
    ".blueprint/": {".blueprint/", ".blueprint"},
    "screens/": {"screens/", "screens"},
    "~$*": {"~$*"},
    "deck/render/": {"deck/render/", "/deck/render/", "deck/render", "/deck/render"},
}
HTML_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
             "source", "track", "wbr"}
CID_PATTERN = re.compile(r"^[a-z0-9_]+$")
UTC_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


class CheckFailed(Exception):
    pass


def rel(path):
    return path.relative_to(ROOT).as_posix()


def read_text(path):
    if not path.exists():
        raise CheckFailed(f"{rel(path)} is missing")
    return path.read_text(encoding="utf-8")


# --- recipe schema --------------------------------------------------------------------------

FORMATS = FormatChecker(formats=())


@FORMATS.checks("date-time")
def _utc_timestamp(value):
    """contracts/conventions.md: times are ISO 8601 UTC with Z."""
    if not isinstance(value, str):
        return True
    if not UTC_TS.match(value):
        return False
    try:
        dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def load_validators():
    schema = json.loads(read_text(CONTRACTS / "recipe.schema.json"))
    Draft202012Validator.check_schema(schema)
    for name in ("header", "op", "event"):
        if name not in schema.get("$defs", {}):
            raise CheckFailed(f"recipe.schema.json has no $defs/{name}")
    # The root schema holds only $defs; a $ref at the root selects one of them.
    return {name: Draft202012Validator({**schema, "$ref": f"#/$defs/{name}"},
                                       format_checker=FORMATS)
            for name in ("header", "op", "event")}


def schema_error(validator, obj):
    err = best_match(validator.iter_errors(obj))
    if err is None:
        return None
    where = "/".join(str(p) for p in err.absolute_path) or "(root)"
    return f"{where}: {err.message[:200]}"


def jsonl_objects(path):
    """(line number, object) for each line; the contract allows no blank lines."""
    out = []
    for n, line in enumerate(read_text(path).splitlines(), start=1):
        if not line.strip():
            raise CheckFailed(f"{rel(path)}:{n} is blank (JSON Lines, no blank lines)")
        try:
            out.append((n, json.loads(line)))
        except json.JSONDecodeError as e:
            raise CheckFailed(f"{rel(path)}:{n} is not JSON: {e}")
    if not out:
        raise CheckFailed(f"{rel(path)} is empty")
    return out


def check_recipe_fixture(v):
    path = FIXTURES / "recipe.sample.jsonl"
    lines = jsonl_objects(path)
    errors = []
    _, header = lines[0]
    if (e := schema_error(v["header"], header)):
        errors.append(f"{rel(path)}:1 header: {e}")
    last_id = None
    for n, op in lines[1:]:
        if (e := schema_error(v["op"], op)):
            errors.append(f"{rel(path)}:{n} op: {e}")
        op_id = op.get("id") if isinstance(op, dict) else None
        if isinstance(op_id, str) and last_id is not None and op_id <= last_id:
            errors.append(f"{rel(path)}:{n} op id {op_id} is not after {last_id} "
                          "(ids are unique and increasing)")
        last_id = op_id if isinstance(op_id, str) else last_id
    if len(lines) < 2:
        errors.append(f"{rel(path)} has a header but no ops")
    if errors:
        raise CheckFailed("; ".join(errors))
    return f"{rel(path)}: header + {len(lines) - 1} ops valid"


def check_mutated_op_rejected(v):
    path = FIXTURES / "recipe.sample.jsonl"
    charts = [op for _, op in jsonl_objects(path)[1:] if op.get("op") == "add_chart"]
    if not charts:
        raise CheckFailed(f"{rel(path)} has no add_chart op to mutate")
    mutated = copy.deepcopy(charts[0])
    mutated["chart_type"] = "donut"
    if v["op"].is_valid(mutated):
        raise CheckFailed(f"op {mutated.get('id')} with chart_type \"donut\" passed the schema")
    return f"op {mutated.get('id')} with chart_type \"donut\" is rejected"


def check_events_fixture(v):
    path = FIXTURES / "events.sample.jsonl"
    lines = jsonl_objects(path)
    errors = [f"{rel(path)}:{n}: {e}" for n, ev in lines if (e := schema_error(v["event"], ev))]
    if errors:
        raise CheckFailed("; ".join(errors))
    kinds = sorted({ev["event"] for _, ev in lines})
    return f"{rel(path)}: {len(lines)} events valid ({', '.join(kinds)})"


# --- API fixtures ---------------------------------------------------------------------------

def check_api_json():
    files = sorted(API_FIXTURES.glob("*.json"))
    if not files:
        raise CheckFailed(f"no JSON fixtures in {rel(API_FIXTURES)}")
    errors = []
    for f in files:
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            errors.append(f"{rel(f)}: {e}")
    if errors:
        raise CheckFailed("; ".join(errors))
    return f"{len(files)} JSON files in {rel(API_FIXTURES)} parse"


def api_event_names():
    """Event names from the table under '## Event stream' in contracts/api.md."""
    text = read_text(CONTRACTS / "api.md")
    m = re.search(r"^## Event stream.*?(?=^## |\Z)", text, flags=re.M | re.S)
    if not m:
        raise CheckFailed("contracts/api.md has no '## Event stream' section")
    names = set(re.findall(r"^\|\s*`([a-z][a-z0-9_.]*)`\s*\|", m.group(0), flags=re.M))
    if not names:
        raise CheckFailed("no event names found in contracts/api.md '## Event stream'")
    return names


def check_events_sse(v):
    path = API_FIXTURES / "events.sse"
    allowed = api_event_names()
    blocks, current = [], []
    for line in read_text(path).splitlines():
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    errors, seen = [], []
    for i, block in enumerate(blocks, start=1):
        fields = [l for l in block if not l.startswith(":")]   # ':' lines are comments (ping)
        if not fields:
            continue
        names = [l[len("event:"):].strip() for l in fields if l.startswith("event:")]
        datas = [l[len("data:"):].strip() for l in fields if l.startswith("data:")]
        if len(names) != 1 or len(datas) != 1:
            errors.append(f"event {i}: needs one 'event:' and one 'data:' line")
            continue
        name = names[0]
        seen.append(name)
        if name not in allowed:
            errors.append(f"event {i}: '{name}' is not listed in contracts/api.md")
        try:
            data = json.loads(datas[0])
        except json.JSONDecodeError as e:
            errors.append(f"event {i} ({name}): data is not JSON: {e}")
            continue
        if name == "build.op" and (e := schema_error(v["event"], data)):
            errors.append(f"event {i} (build.op): not an engine event: {e}")
        if name == "build.op" and data.get("event") != "op_finished":
            errors.append(f"event {i} (build.op): data.event is not op_finished")
    if not seen:
        errors.append(f"{rel(path)} holds no events")
    if errors:
        raise CheckFailed("; ".join(errors))
    return f"{rel(path)}: {len(seen)} events, {len(set(seen))} names, all in contracts/api.md"


class _PrototypeParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []          # (tag, has data-cid)
        self.canvas = 0
        self.cids = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id") == "dss-canvas":
            self.canvas += 1
        is_cid = "data-cid" in a
        if is_cid:
            cid = a.get("data-cid") or ""
            self.cids.append(cid)
            if not CID_PATTERN.match(cid):
                self.errors.append(f"data-cid '{cid}' is not lowercase snake case")
            if not (a.get("data-label") or "").strip():
                self.errors.append(f"data-cid '{cid}' has no data-label")
            if a.get("data-kind") not in ("component", "decoration"):
                self.errors.append(f"data-cid '{cid}' has data-kind {a.get('data-kind')!r}, "
                                   "not component or decoration")
            if any(has_cid for _, has_cid in self.stack):
                self.errors.append(f"data-cid '{cid}' is nested inside another data-cid element")
        if tag not in HTML_VOID:
            self.stack.append((tag, is_cid))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in HTML_VOID and self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def check_prototype_html():
    path = API_FIXTURES / "prototype.sample.html"
    p = _PrototypeParser()
    p.feed(read_text(path))
    p.close()
    errors = list(p.errors)
    if p.canvas != 1:
        errors.append(f"expected one #dss-canvas element, found {p.canvas}")
    if not p.cids:
        errors.append("no data-cid elements")
    dupes = sorted({c for c in p.cids if p.cids.count(c) > 1})
    if dupes:
        errors.append(f"duplicate data-cid: {', '.join(dupes)}")
    if errors:
        raise CheckFailed(f"{rel(path)}: " + "; ".join(errors))
    return f"{rel(path)}: #dss-canvas and {len(p.cids)} data-cid elements with label and kind"


# --- root files ----------------------------------------------------------------------------

def conventions_env_names():
    """Names from the table under '## Environment variables' in contracts/conventions.md."""
    text = read_text(CONTRACTS / "conventions.md")
    m = re.search(r"^## Environment variables.*?(?=^## |\Z)", text, flags=re.M | re.S)
    if not m:
        raise CheckFailed("contracts/conventions.md has no '## Environment variables' section")
    names = re.findall(r"^\|\s*`([A-Z][A-Z0-9_]*)`\s*\|", m.group(0), flags=re.M)
    if not names:
        raise CheckFailed("no env names found in contracts/conventions.md")
    return names


def parse_env_file(path):
    values, errors = {}, []
    for n, line in enumerate(read_text(path).splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", s)
        if not m:
            errors.append(f"{rel(path)}:{n} is not NAME=value")
            continue
        name, value = m.group(1), m.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name in values:
            errors.append(f"{rel(path)}:{n} repeats {name}")
        values[name] = value
    return values, errors


def check_env_example():
    path = ROOT / ".env.example"
    names = conventions_env_names()
    values, errors = parse_env_file(path)
    missing = [n for n in names if n not in values]
    if missing:
        errors.append(f"missing {', '.join(missing)}")
    filled = [n for n in SECRETS_EMPTY if values.get(n)]
    if filled:
        errors.append(f"must be empty: {', '.join(filled)}")
    if errors:
        raise CheckFailed(f"{rel(path)}: " + "; ".join(errors))
    return (f"{rel(path)}: all {len(names)} names from contracts/conventions.md, "
            f"{', '.join(SECRETS_EMPTY)} empty")


def check_gitignore():
    path = ROOT / ".gitignore"
    lines = {l.strip() for l in read_text(path).splitlines()
             if l.strip() and not l.strip().startswith("#")}
    missing = [req for req, spellings in GITIGNORE_REQUIRED.items() if not lines & spellings]
    errors = [f"does not ignore {', '.join(missing)}"] if missing else []
    if any(l.startswith(".env") and l != ".env" for l in lines) and "!.env.example" not in lines:
        errors.append("a .env* pattern also ignores .env.example; add !.env.example")
    if errors:
        raise CheckFailed(f"{rel(path)}: " + "; ".join(errors))
    return f"{rel(path)}: ignores {', '.join(GITIGNORE_REQUIRED)}"


def main():
    results = []

    def run(name, fn, *args):
        try:
            results.append((True, name, fn(*args)))
        except CheckFailed as e:
            results.append((False, name, str(e)))
        except Exception as e:   # malformed input the check didn't foresee: still a FAIL line
            results.append((False, name, f"{type(e).__name__}: {e}"))

    try:
        validators = load_validators()
        results.append((True, "recipe schema", "contracts/recipe.schema.json is valid 2020-12"))
    except Exception as e:   # missing, not JSON or not a valid schema: the checks below need it
        validators = None
        results.append((False, "recipe schema", f"{type(e).__name__}: {e}"))
    if validators:
        run("recipe fixture", check_recipe_fixture, validators)
        run("mutated op", check_mutated_op_rejected, validators)
        run("events fixture", check_events_fixture, validators)
        run("events.sse", check_events_sse, validators)
    run("api JSON fixtures", check_api_json)
    run("prototype HTML", check_prototype_html)
    run(".env.example", check_env_example)
    run(".gitignore", check_gitignore)

    for ok, name, msg in results:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {msg}")
    failed = sum(1 for ok, _, _ in results if not ok)
    if failed:
        print(f"\n{failed} of {len(results)} checks failed")
        return 1
    print(f"\nAll {len(results)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
