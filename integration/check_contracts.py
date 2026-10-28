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
INTENT_FIXTURES = FIXTURES / "dashboard-intent"
SYNTHETIC_FIXTURES = FIXTURES / "synthetic-data"
STAGE_FIXTURES = FIXTURES / "stage-settings"
STAGE_IDS = ("interview", "routine", "reference_interpretation", "native_planning", "html_brief",
             "reference_html", "html_no_reference")   # api.md 3.0 StageId
SAMPLES = ROOT / "samples"
REFERENCE_SIZE = (1200, 750)    # samples/reference-dashboard.png, CSS px at device scale 1

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


def sse_errors(text, allowed, v):
    """(errors, event names) of an SSE stream: one event and one JSON data line per event, each
    name listed in contracts/api.md, and build.op data an engine op_finished event."""
    blocks, current = [], []
    for line in text.splitlines():
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
    return errors, seen


def check_events_sse(v):
    path = API_FIXTURES / "events.sse"
    errors, seen = sse_errors(read_text(path), api_event_names(), v)
    if not seen:
        errors.append(f"{rel(path)} holds no events")
    if errors:
        raise CheckFailed("; ".join(errors))
    return f"{rel(path)}: {len(seen)} events, {len(set(seen))} names, all in contracts/api.md"


def check_review_sse(v):
    """events.review.sse (api.md 3.0): every event in the api.md table; an unknown one fails."""
    path = STAGE_FIXTURES / "events.review.sse"
    text, allowed = read_text(path), api_event_names()
    errors, seen = sse_errors(text, allowed, v)
    if "brief.review" not in seen:
        errors.append(f"{rel(path)} has no brief.review event")
    mutated = text.rstrip("\n") + '\n\nevent: brief.reviewed\ndata: {"review_id": "br_7d1e2f3a4b5c"}\n'
    if not any("'brief.reviewed' is not listed" in e for e in sse_errors(mutated, allowed, v)[0]):
        errors.append("a copy with the unknown event brief.reviewed passed")
    if errors:
        raise CheckFailed("; ".join(errors))
    return (f"{rel(path)}: {len(seen)} events ({', '.join(dict.fromkeys(seen))}) in contracts/api.md; "
            "a copy with unknown event brief.reviewed is rejected")


# --- stage settings (api.md 3.0) and the e2e drivers -------------------------------------------

def check_stage_settings_fixtures():
    files = sorted(STAGE_FIXTURES.glob("*.json"))
    if not files:
        raise CheckFailed(f"no JSON fixtures in {rel(STAGE_FIXTURES)}")
    errors = []
    for f in files:
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            errors.append(f"{rel(f)}: {e}")
    if errors:
        raise CheckFailed("; ".join(errors))
    stages = json.loads(read_text(STAGE_FIXTURES / "settings.json")).get("stages") or {}
    if sorted(stages) != sorted(STAGE_IDS):
        errors.append(f"settings.json stages are {sorted(stages)}, not the StageIds")
    errors += [f"settings.json stages.{k}.timeout_s is not a positive int" for k, p in stages.items()
               if not (isinstance(p.get("timeout_s"), int) and p["timeout_s"] > 0)]
    if errors:
        raise CheckFailed("; ".join(errors))
    return f"{len(files)} JSON files in {rel(STAGE_FIXTURES)} parse; settings.json has all {len(STAGE_IDS)} stage clocks"


def _drivers():
    sys.path.insert(0, str(ROOT / "integration"))
    import e2e_flow1
    import e2e_references
    return e2e_flow1, e2e_references


def check_driver_waits():
    """The drivers' per-action waits from Settings: 2 x (html_brief + the larger HTML profile) + 300
    for blueprint accept and comments, the stage clock + 300 for design confirm and reference
    upload, never under 600 s."""
    flow1, _ = _drivers()
    settings = json.loads(read_text(STAGE_FIXTURES / "settings.json"))
    waits = flow1.action_waits(settings)
    want = {"/blueprint/accept": 3900, "/comments": 3900, "/design/confirm": 1500,
            "/blueprint/regenerate": 1500, "/reference-images": 900}
    errors = [f"{rel(STAGE_FIXTURES / 'settings.json')}: {a} waits {waits.get(a)} s, expected {s} s"
              for a, s in want.items() if waits.get(a) != s]
    short = copy.deepcopy(settings)
    for profile in short["stages"].values():
        profile["timeout_s"] = 30
    if set(flow1.action_waits(short).values()) != {600}:
        errors.append(f"30 s clocks wait {flow1.action_waits(short)}, not the 600 s floor")
    larger = copy.deepcopy(settings)
    larger["stages"]["reference_html"]["timeout_s"] = 300
    larger["stages"]["html_no_reference"]["timeout_s"] = 1500
    if flow1.action_waits(larger)["/blueprint/accept"] != 2 * (600 + 1500) + 300:
        errors.append("blueprint accept does not take the larger HTML profile's timeout_s")
    if errors:
        raise CheckFailed("; ".join(errors))
    return (f"waits for {rel(STAGE_FIXTURES / 'settings.json')}: blueprint accept and comments "
            f"{waits['/blueprint/accept']:,} s, design confirm {waits['/design/confirm']:,} s, "
            f"reference upload {waits['/reference-images']:,} s; 600 s floor; larger HTML profile")


def check_bench_server_url():
    """Both drivers' bench records name a non-local --server "hosted", never its URL."""
    flow1, refs = _drivers()
    started, errors = dt.datetime.now(dt.timezone.utc), []
    for server, want in (("https://example.run.app", "hosted"),
                         ("http://localhost:8000", "http://localhost:8000")):
        records = {"e2e_flow1": flow1.bench_record(flow1.Flow(None, []), server, "dry-run", False,
                                                   started, {"input_tokens": 0, "output_tokens": 0}),
                   "e2e_references": refs.bench_header(server, {"commit": "0" * 40, "dirty": False})}
        for driver, record in records.items():
            if record.get("server_url") != want:
                errors.append(f"{driver} --server {server}: server_url {record.get('server_url')!r}, expected {want!r}")
            if want == "hosted" and "example.run.app" in json.dumps(record):
                errors.append(f"{driver} --server {server}: the bench record holds the URL")
    if errors:
        raise CheckFailed("; ".join(errors))
    return 'e2e_flow1 and e2e_references bench records hold server_url "hosted" for --server https://example.run.app'


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


# --- dashboard-intent and synthetic-data fixtures --------------------------------------------
# Shapes from contracts/dashboard-intent.md (ReferenceSet, Assessment, Issue) and
# contracts/synthetic-data.md (GenerationSpec, Proposal, SyntheticDataset, GenerationStatus).

def _obj(props, required=None, extra=False):
    return {"type": "object", "properties": props, "required": required or list(props),
            "additionalProperties": extra}


_STR = {"type": "string"}
_ID = {"type": "string", "minLength": 1}
_NULL_STR = {"type": ["string", "null"]}
_INT12 = {"type": "integer", "minimum": -10**12, "maximum": 10**12}
_NUM12 = {"type": "number", "minimum": -10**12, "maximum": 10**12}
_DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
_PROB = {"type": "number", "minimum": 0, "maximum": 1}
_SCALAR = {"type": ["string", "number", "boolean"]}

_GENERATORS = {
    "sequence": {"start": _INT12, "step": _INT12, "prefix": {"type": "string", "maxLength": 32}},
    "integer": {"min": _INT12, "max": _INT12},
    "decimal": {"min": _NUM12, "max": _NUM12, "decimals": {"type": "integer", "minimum": 0, "maximum": 6}},
    "choice": {"values": {"type": "array", "minItems": 1, "maxItems": 100, "uniqueItems": True,
                          "items": _SCALAR}},
    "boolean": {"true_probability": _PROB},
    "date": {"start": _DATE, "end": _DATE},
    "product": {"fields": {"type": "array", "minItems": 2, "maxItems": 2, "items": _STR},
                "decimals": {"type": "integer", "minimum": 0, "maximum": 6}},
    "lookup": {"field": _STR, "mapping": {"type": "object"}},
}
GENERATION_SPEC = _obj({
    "schema_version": {"const": 1},
    "row_count": {"type": "integer", "minimum": 1, "maximum": 100_000},
    "seed": {"type": "integer", "minimum": 0, "maximum": 2**32 - 1},
    "columns": {"type": "array", "minItems": 1, "maxItems": 40, "items": _obj({
        "name": {"type": "string", "pattern": r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$", "maxLength": 64},
        "type": {"enum": ["integer", "number", "string", "boolean", "date"]},
        "nullable_fraction": _PROB,
        "generator": {"oneOf": [_obj({"kind": {"const": kind}, **props})
                                for kind, props in _GENERATORS.items()]},
    })},
})
_ASSUMPTIONS = {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 240}}
_DISPOSITION = {"enum": ["native", "static"]}
_UNIT = {"type": "number", "minimum": 0, "maximum": 1}
REFERENCE_ANALYSIS = _obj({   # dashboard-intent.md 1.3
    "revision": {"type": "integer", "minimum": 1},
    "state": {"enum": ["pending", "approved"]},
    "summary": _STR,
    "items": {"type": "array", "minItems": 1, "maxItems": 24, "items": _obj({
        "id": {"type": "string", "pattern": r"^r[1-9][0-9]*$"},
        "label": {"type": "string", "minLength": 1, "maxLength": 120},
        "kind": {"enum": ["chart", "control", "kpi", "text", "image", "legend", "other"]},
        "box": _obj({"x": _UNIT, "y": _UNIT, "w": _UNIT, "h": _UNIT}),
        "disposition": _DISPOSITION, "type": _NULL_STR,
        "shows": {"type": "string", "maxLength": 300},
        "reason": {"type": "string", "maxLength": 300},
        "proposed": _obj({"disposition": _DISPOSITION, "type": _NULL_STR})})},
    "note": {"type": "string", "maxLength": 1000},
    "allowed_types": {"type": "array", "uniqueItems": True, "items": _ID},
    "issues": {"type": "array", "items": _obj({"path": _STR, "message": _STR})},   # api.md ValidationIssue
})
CONTROL_TYPES = {"date_range", "dropdown", "fixed_size_list"}   # recipe.md 1.3 controls
FIXTURE_SCHEMAS = {
    "ReferenceSet": _obj({
        "id": _ID, "mode": {"enum": ["style", "recreate"]},
        "instructions": {"type": "string", "maxLength": 2000},
        "images": {"type": "array", "minItems": 1, "maxItems": 3,
                   "items": _obj({"id": _ID, "name": _ID,
                                  "file": {"type": "string", "pattern": r"^reference_[A-Za-z0-9_-]+\.(png|jpg)$"}})},
        "summary": _STR,
        "analysis": {"oneOf": [{"type": "null"}, REFERENCE_ANALYSIS]}}),
    "Assessment": _obj({
        "id": _NULL_STR, "state": {"enum": ["unchecked", "blocked", "ready", "stale"]},
        "input_digest": _NULL_STR, "prototype_stale": {"type": "boolean"},
        "issues": {"type": "array", "items": _obj({
            "id": _ID, "requirement": _ID,
            "status": {"enum": ["unsupported_product", "unsupported_app", "needs_data",
                                "needs_clarification", "unknown"]},
            "reason": _ID, "evidence": {"type": "array", "items": _STR},
            "alternatives": {"type": "array", "items": _obj({"id": _ID, "label": _ID})},
            "resolution": {"enum": ["unresolved", "accepted_alternative", "dropped"]}})},
        "pending_comments": {"oneOf": [{"type": "null"}, _obj({
            "id": _ID, "comments": {"type": "array", "minItems": 1, "maxItems": 20,
                                    "items": _obj({"component_id": _ID, "text": _ID})}})]}}),
    "GenerationRequest": _obj({
        "generation_key": {"type": "string", "pattern": r"^[A-Za-z0-9_-]{1,64}$"},
        "proposal_id": _NULL_STR, "spec": GENERATION_SPEC}),
    "Proposal": _obj({"id": _ID, "reference_set_id": _ID, "spec": GENERATION_SPEC,
                      "assumptions": _ASSUMPTIONS}),
    "SyntheticDataset": _obj({
        "source_id": _ID, "generation_key": {"type": "string", "pattern": r"^[A-Za-z0-9_-]{1,64}$"},
        "synthetic": {"const": True}, "spec": GENERATION_SPEC, "assumptions": _ASSUMPTIONS,
        "generator_version": _ID, "sha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
        "bytes": {"type": "integer", "minimum": 1, "maximum": 50 * 2**20},
        "created_at": {"type": "string", "format": "date-time"}}),
    "GenerationStatus": _obj({
        "generation_key": {"type": "string", "pattern": r"^[A-Za-z0-9_-]{1,64}$"}, "run_id": _ID,
        "state": {"enum": ["queued", "generating", "loading", "succeeded", "failed"]},
        "source_id": _NULL_STR, "retry_ready": {"type": "boolean"},
        "error": {"oneOf": [{"type": "null"}, _obj({"code": _ID, "message": _ID})]}}),
    "Source": _obj({
        "id": _ID, "kind": {"enum": ["upload", "gcs", "bigquery", "research", "synthetic"]},
        "name": _ID, "bq_table": {"type": "string", "pattern": r"^[^.\s]+\.[^.\s]+\.[^.\s]+$"},
        "row_count": {"type": "integer", "minimum": 0},
        "columns": {"type": "array", "items": _obj({
            "name": _ID, "type": {"enum": ["string", "number", "date", "datetime", "boolean", "geo"]},
            "sample": {"type": "array", "items": _STR}})}}),
}
FIXTURE_FILES = {   # fixture -> type (contracts/api.md 1.3/1.4 sections name them)
    INTENT_FIXTURES / "reference_set.json": "ReferenceSet",
    INTENT_FIXTURES / "reference_set.pending.json": "ReferenceSet",
    INTENT_FIXTURES / "feasibility.json": "Assessment",
    INTENT_FIXTURES / "feasibility.alternatives.json": "Assessment",
    INTENT_FIXTURES / "feasibility.pending.json": "Assessment",
    INTENT_FIXTURES / "feasibility.stale.json": "Assessment",
    SYNTHETIC_FIXTURES / "request.json": "GenerationRequest",
    SYNTHETIC_FIXTURES / "proposal.json": "Proposal",
    SYNTHETIC_FIXTURES / "dataset.json": "SyntheticDataset",
    SYNTHETIC_FIXTURES / "job.succeeded.json": "GenerationStatus",
    SYNTHETIC_FIXTURES / "job.failed.json": "GenerationStatus",
    SYNTHETIC_FIXTURES / "source.json": "Source",
}
FORMULA_PREFIX = re.compile(r"^\s*[=+\-@\t\r]")
SYNTHETIC_LABEL = "Synthetic sample data"
_KIND_TYPES = {"sequence": {"integer", "string"}, "integer": {"integer"}, "decimal": {"number"},
               "choice": {"integer", "number", "string", "boolean", "date"}, "boolean": {"boolean"},
               "date": {"date"}, "product": {"number"}, "lookup": {"integer", "number", "string", "boolean", "date"}}


def _typed(value, kind):
    if kind == "string" or kind == "date":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def generation_spec_errors(spec):
    """The synthetic-data.md rules JSON Schema can't express: types per generator, ranges,
    dependencies (earlier columns only), lookup coverage, cell budget, formula-like strings."""
    errors, seen = [], {}
    columns = spec["columns"]
    if spec["row_count"] * len(columns) > 1_000_000:
        errors.append(f"{spec['row_count']} rows x {len(columns)} columns exceed 1,000,000 cells")
    for i, col in enumerate(columns):
        name, kind, gen = col["name"], col["type"], col["generator"]
        where = f"columns/{i} ({name})"
        if name in seen:
            errors.append(f"{where}: duplicate name")
        if kind not in _KIND_TYPES[gen["kind"]]:
            errors.append(f"{where}: generator {gen['kind']} can't produce type {kind}")
        if gen["kind"] in ("integer", "decimal") and gen["min"] > gen["max"]:
            errors.append(f"{where}: min > max")
        if gen["kind"] == "sequence" and kind == "integer" and gen["prefix"]:
            errors.append(f"{where}: an integer sequence has an empty prefix")
        if gen["kind"] == "date":
            try:
                start, end = dt.date.fromisoformat(gen["start"]), dt.date.fromisoformat(gen["end"])
            except ValueError as e:
                errors.append(f"{where}: {e}")
            else:
                if not dt.date(1900, 1, 1) <= start <= end <= dt.date(2100, 12, 31):
                    errors.append(f"{where}: dates must satisfy 1900-01-01 <= start <= end <= 2100-12-31")
        values = gen["values"] if gen["kind"] == "choice" else (
            list(gen["mapping"].values()) if gen["kind"] == "lookup" else [])
        for value in values:
            if not _typed(value, kind):
                errors.append(f"{where}: value {value!r} is not of type {kind}")
            elif isinstance(value, str) and (len(value) > 120 or FORMULA_PREFIX.match(value)):
                errors.append(f"{where}: string value {value[:20]!r} is too long or formula-like")
        if gen["kind"] == "sequence" and FORMULA_PREFIX.match(gen["prefix"] or "x"):
            errors.append(f"{where}: sequence prefix is formula-like")
        if gen["kind"] in ("product", "lookup"):
            if col["nullable_fraction"] != 0:
                errors.append(f"{where}: a dependent column needs nullable_fraction 0")
            refs = gen["fields"] if gen["kind"] == "product" else [gen["field"]]
            for ref in refs:
                source = seen.get(ref)
                if source is None:
                    errors.append(f"{where}: depends on {ref!r}, not an earlier column")
                elif gen["kind"] == "product" and source["type"] not in ("integer", "number"):
                    errors.append(f"{where}: product of non-numeric column {ref}")
                elif gen["kind"] == "lookup":
                    if source["type"] != "string" or source["generator"]["kind"] not in ("choice", "lookup"):
                        errors.append(f"{where}: lookup needs an earlier string choice or lookup")
                    else:
                        g = source["generator"]
                        keys = set(g["values"]) if g["kind"] == "choice" else set(g["mapping"].values())
                        if set(gen["mapping"]) != keys:
                            errors.append(f"{where}: mapping keys must cover exactly {sorted(keys)}")
        seen[name] = col
    return errors


def reference_set_errors(ref):
    """dashboard-intent.md rules JSON Schema can't express: images per mode, analysis per mode,
    and the 1.3 analysis checks (unique ids, boxes inside the image, types per disposition)."""
    errors, analysis = [], ref["analysis"]
    if ref["mode"] == "recreate" and len(ref["images"]) != 1:
        errors.append("recreate takes exactly one image")
    if ref["mode"] == "style" and analysis is not None:
        errors.append("a style set has analysis null")
    if analysis is None:
        return errors
    allowed, ids = set(analysis["allowed_types"]), set()
    for i, item in enumerate(analysis["items"]):
        where, box, proposed = f"analysis/items/{i} ({item['id']})", item["box"], item["proposed"]
        if item["id"] in ids:
            errors.append(f"{where}: duplicate id")
        ids.add(item["id"])
        if box["w"] <= 0 or box["h"] <= 0 or box["x"] + box["w"] > 1 or box["y"] + box["h"] > 1:
            errors.append(f"{where}: box is not inside the image")
        for name, choice in (("", item), ("proposed ", proposed)):
            if choice["disposition"] == "static" and choice["type"] is not None:
                errors.append(f"{where}: {name}static item has a type")
        # proposed was checked against allowed_types at upload; allowed_types may narrow since
        if proposed["disposition"] == "native":
            if proposed["type"] is None:
                errors.append(f"{where}: proposed native item has no type")
            elif proposed["type"] in CONTROL_TYPES and item["kind"] != "control":
                errors.append(f"{where}: a control type is only for a control")
        if (item["disposition"] == "native" and item["type"] not in allowed
                and not analysis["issues"]):
            errors.append(f"{where}: native type {item['type']!r} not in allowed_types and no issue")
    if analysis["state"] == "approved" and analysis["issues"]:
        errors.append("an approved analysis has issues")
    return errors


def fixture_errors(kind, obj, validators):
    """Schema errors, then the per-type rules from the contracts."""
    if (e := schema_error(validators[kind], obj)):
        return [e]
    errors = []
    if kind == "ReferenceSet":
        errors += reference_set_errors(obj)
    if "spec" in obj and kind in ("GenerationRequest", "Proposal", "SyntheticDataset"):
        errors += [f"spec/{e}" for e in generation_spec_errors(obj["spec"])]
    if kind == "GenerationRequest" and len(json.dumps(obj).encode()) > 64 * 1024:
        errors.append("request body exceeds 64 KiB")
    if kind == "GenerationStatus":
        state = obj["state"]
        if state == "succeeded" and (obj["source_id"] is None or obj["error"] or obj["retry_ready"]):
            errors.append("succeeded needs source_id, no error and retry_ready false")
        if state == "failed" and (obj["source_id"] is not None or not obj["error"]):
            errors.append("failed needs an error and no source_id")
        if state in ("queued", "generating", "loading") and (obj["retry_ready"] or obj["error"]):
            errors.append("an in-flight job never permits retry and has no error")
    if kind == "Source" and obj["kind"] == "synthetic" and obj["name"] != SYNTHETIC_LABEL:
        errors.append(f"a synthetic source is named {SYNTHETIC_LABEL!r}")
    if kind == "Assessment" and obj["state"] == "ready" and any(
            i["resolution"] == "unresolved" for i in obj["issues"]):
        errors.append("ready with an unresolved issue")
    return errors


def fixture_validators():
    return {name: Draft202012Validator(schema, format_checker=FORMATS)
            for name, schema in FIXTURE_SCHEMAS.items()}


def check_intent_synthetic_fixtures():
    validators = fixture_validators()
    errors = []
    for path, kind in FIXTURE_FILES.items():
        try:
            obj = json.loads(read_text(path))
        except json.JSONDecodeError as e:
            errors.append(f"{rel(path)}: not JSON: {e}")
            continue
        errors += [f"{rel(path)} ({kind}): {e}" for e in fixture_errors(kind, obj, validators)]
    style = _mutate(INTENT_FIXTURES / "reference_set.json", lambda o: o.update(mode="style", analysis=None))
    errors += [f"style ReferenceSet with analysis null: {e}"
               for e in fixture_errors("ReferenceSet", style, validators)]
    if errors:
        raise CheckFailed("; ".join(errors))
    return f"{len(FIXTURE_FILES)} dashboard-intent and synthetic-data fixtures match their contract shapes"


def _mutate(path, change):
    obj = json.loads(read_text(path))
    change(obj)
    return obj


def _set(path, value):
    """A change that sets obj[a][b]... = value (path is a tuple of keys/indexes)."""
    def change(obj):
        target = obj
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return change


def check_fixture_error_cases():
    """Each mutation breaks one contract rule and must be rejected (shape or rule)."""
    validators = fixture_validators()
    req, gen = SYNTHETIC_FIXTURES / "request.json", ("spec", "columns")
    ref, item = INTENT_FIXTURES / "reference_set.json", ("analysis", "items", 1)
    cases = [
        ("Assessment state maybe", "Assessment", INTENT_FIXTURES / "feasibility.json", _set(("state",), "maybe")),
        ("Issue status impossible", "Assessment", INTENT_FIXTURES / "feasibility.json",
         _set(("issues", 0, "status"), "impossible")),
        ("Issue resolution accepted", "Assessment", INTENT_FIXTURES / "feasibility.json",
         _set(("issues", 0, "resolution"), "accepted")),
        ("ready with an unresolved issue", "Assessment", INTENT_FIXTURES / "feasibility.json",
         _set(("state",), "ready")),
        ("pending batch of 21 comments", "Assessment", INTENT_FIXTURES / "feasibility.pending.json",
         lambda o: o["pending_comments"].update(comments=o["pending_comments"]["comments"] * 11)),
        ("ReferenceSet mode copy", "ReferenceSet", INTENT_FIXTURES / "reference_set.json", _set(("mode",), "copy")),
        ("reference file is a path", "ReferenceSet", ref, _set(("images", 0, "file"), "../secrets.png")),
        ("analysis disposition hybrid", "ReferenceSet", ref, _set(item + ("disposition",), "hybrid")),
        ("analysis state done", "ReferenceSet", ref, _set(("analysis", "state"), "done")),
        ("analysis item box outside the image", "ReferenceSet", ref, _set(item + ("box", "x"), 0.9)),
        ("static item with a type", "ReferenceSet", ref, _set(item + ("disposition",), "static")),
        ("native type outside allowed_types", "ReferenceSet", ref, _set(item + ("type",), "donut")),
        ("approved analysis with issues", "ReferenceSet", ref,
         _set(("analysis", "issues"), [{"path": "/items/1/type", "message": "x"}])),
        ("duplicate analysis item id", "ReferenceSet", ref, _set(("analysis", "items", 2, "id"), "r2")),
        ("25 analysis items", "ReferenceSet", ref,
         lambda o: o["analysis"].update(items=[dict(o["analysis"]["items"][0], id=f"r{i}") for i in range(1, 26)])),
        ("style set with an analysis", "ReferenceSet", ref, _set(("mode",), "style")),
        ("row_count 0", "GenerationRequest", req, _set(("spec", "row_count"), 0)),
        ("row_count 100001", "GenerationRequest", req, _set(("spec", "row_count"), 100_001)),
        ("seed above uint32", "GenerationRequest", req, _set(("spec", "seed"), 2**32)),
        ("unknown generator kind", "GenerationRequest", req, _set(gen + (0, "generator"), {"kind": "python", "code": "1"})),
        ("unknown field", "GenerationRequest", req, _set(gen + (0, "generator", "eval"), "x")),
        ("formula-like choice", "GenerationRequest", req, _set(gen + (0, "generator", "values"), ["=HYPERLINK(1)", "West"])),
        ("forward product dependency", "GenerationRequest", req,
         _set(gen + (3, "generator", "fields"), ["quantity", "later_column"])),
        ("dependent nullable product", "GenerationRequest", req, _set(gen + (3, "nullable_fraction"), 0.2)),
        ("decimal min above max", "GenerationRequest", req, _set(gen + (2, "generator", "min"), 500)),
        ("choice value of the wrong type", "GenerationRequest", req, _set(gen + (0, "generator", "values"), ["East", 7])),
        ("cell budget", "GenerationRequest", req,
         lambda o: o["spec"].update(row_count=100_000, columns=o["spec"]["columns"][:3] + [
             {"name": f"c{i}", "type": "integer", "nullable_fraction": 0,
              "generator": {"kind": "integer", "min": 0, "max": 1}} for i in range(8)])),
        ("generation_key with a space", "GenerationRequest", req, _set(("generation_key",), "bad key")),
        ("succeeded with an error", "GenerationStatus", SYNTHETIC_FIXTURES / "job.succeeded.json",
         _set(("error",), {"code": "x", "message": "y"})),
        ("failed with a source", "GenerationStatus", SYNTHETIC_FIXTURES / "job.failed.json",
         _set(("source_id",), "s_000000000001")),
        ("in-flight job ready to retry", "GenerationStatus", SYNTHETIC_FIXTURES / "job.failed.json",
         lambda o: o.update(state="loading", error=None)),
        ("dataset not synthetic", "SyntheticDataset", SYNTHETIC_FIXTURES / "dataset.json", _set(("synthetic",), False)),
        ("dataset checksum not sha256", "SyntheticDataset", SYNTHETIC_FIXTURES / "dataset.json", _set(("sha256",), "abc")),
        ("21 assumptions", "Proposal", SYNTHETIC_FIXTURES / "proposal.json", _set(("assumptions",), ["a"] * 21)),
        ("synthetic source without the label", "Source", SYNTHETIC_FIXTURES / "source.json",
         _set(("name",), "Sales data")),
    ]
    accepted = []
    for name, kind, path, change in cases:
        if not fixture_errors(kind, _mutate(path, change), validators):
            accepted.append(name)
    if accepted:
        raise CheckFailed("accepted invalid input: " + ", ".join(accepted))
    return f"{len(cases)} invalid reference, assessment and synthetic-data variants are rejected"


# --- task 2.5 samples and reference bench ------------------------------------------------------

def check_reference_samples():
    errors = []
    html = read_text(SAMPLES / "reference-dashboard.html")
    if re.search(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//|url\(\s*["']?(?:https?:)?//|@import""", html, re.I):
        errors.append("reference-dashboard.html makes a network request")
    png = SAMPLES / "reference-dashboard.png"
    if not png.exists():
        errors.append(f"{rel(png)} is missing")
    else:
        head = png.read_bytes()[:24]
        size = tuple(int.from_bytes(head[i:i + 4], "big") for i in (16, 20))
        if head[:8] != b"\x89PNG\r\n\x1a\n" or size != REFERENCE_SIZE:
            errors.append(f"{rel(png)} is not a {REFERENCE_SIZE[0]}x{REFERENCE_SIZE[1]} PNG")
        if png.stat().st_size > 5 * 2**20:
            errors.append(f"{rel(png)} exceeds the 5 MiB reference limit")
    expect = json.loads(read_text(SAMPLES / "reference-expectations.json"))
    columns = read_text(SAMPLES / "ecommerce_sales.csv").split("\n", 1)[0].split(",")
    hexes = [expect["theme"][k] for k in ("background", "accent", "band")]
    if not all(re.match(r"^#[0-9A-F]{6}$", h) for h in hexes):
        errors.append("reference-expectations.json theme colors are not #RRGGBB")
    for item in expect["items"]:
        fields = item.get("dimensions", []) + [m["field"] for m in item.get("metrics", [])]
        fields += [item["date_dimension"]] if item.get("date_dimension") else []
        unknown = [f for f in fields if f not in columns]
        if unknown or item.get("band") not in (1, 2, 3) or not item.get("keywords"):
            errors.append(f"expectation {item.get('id')}: unknown fields {unknown}, band or keywords")
    gross = read_text(SAMPLES / "gross_net_sales.csv")
    header = gross.split("\n", 1)[0].split(",")
    if "\r" in gross or not {"gross_sales", "net_sales"} <= set(header) or "revenue" in header:
        errors.append("gross_net_sales.csv needs LF endings, gross_sales and net_sales, and no revenue column")
    if errors:
        raise CheckFailed("; ".join(errors))
    return (f"reference mock {REFERENCE_SIZE[0]}x{REFERENCE_SIZE[1]} PNG, "
            f"{len(expect['items'])} expected items, gross/net CSV {len(gross.splitlines()) - 1} rows")


BENCH_KEYS = {"run_date", "server_url", "git_revision", "live", "cases", "all_passed"}
SECRET_PATTERNS = re.compile(r"AIza[0-9A-Za-z_-]{20,}|data:image/|ya29\.|-----BEGIN|\"(?:access_code|api_key|token)\"")


def check_reference_bench():
    benches = sorted((ROOT / "deck" / "data").glob("bench-references-*.json"))
    if not benches:
        return "no deck/data/bench-references-*.json yet (written by e2e_references.py)"
    errors = []
    for path in benches:
        text = read_text(path)
        bench = json.loads(text)
        missing = BENCH_KEYS - set(bench)
        if missing:
            errors.append(f"{rel(path)}: missing {', '.join(sorted(missing))}")
        if SECRET_PATTERNS.search(text):
            errors.append(f"{rel(path)}: holds a secret-like value or an embedded image")
        for name, case in bench.get("cases", {}).items():
            if not {"passed", "seconds", "run_date"} <= set(case):
                errors.append(f"{rel(path)}: case {name} lacks passed, seconds or run_date")
    if errors:
        raise CheckFailed("; ".join(errors))
    return ", ".join(f"{rel(p)}: {len(json.loads(read_text(p))['cases'])} cases" for p in benches)


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
        run("events.review.sse", check_review_sse, validators)
    run("api JSON fixtures", check_api_json)
    run("prototype HTML", check_prototype_html)
    run("stage-settings fixtures", check_stage_settings_fixtures)
    run("e2e waits", check_driver_waits)
    run("bench server_url", check_bench_server_url)
    run("intent/synthetic fixtures", check_intent_synthetic_fixtures)
    run("intent/synthetic error cases", check_fixture_error_cases)
    run("reference samples", check_reference_samples)
    run("reference bench", check_reference_bench)
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
