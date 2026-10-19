"""Version-local intent ledger and deterministic feasibility projection.

The extractor proposes needs, never verdicts or resolutions. This module owns IDs,
provenance, classification, input invalidation and the durable assessment commit point.
"""
import hashlib
import json
import re
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from dss.db import new_id
from dss.data.bigquery import snake_names
from dss.spec import capabilities, references

MAX_REQUIREMENTS = 40
MAX_ISSUES = 20


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Mapping(Strict):
    label: str = Field(min_length=1, max_length=240)
    field: str | None = Field(default=None, max_length=240)
    unit: str | None = Field(default=None, max_length=120)
    aggregation: Literal["sum", "avg", "count", "count_distinct", "min", "max", "none"] | None = None
    date_grain: str | None = Field(default=None, max_length=120)


class Extracted(Strict):
    source_id: str = Field(min_length=1, max_length=240)
    text: str = Field(min_length=1, max_length=2000)
    needs: list[capabilities.Need] = Field(default_factory=list, max_length=20)
    mappings: list[Mapping] = Field(default_factory=list, max_length=20)
    component_ids: list[str] = Field(default_factory=list, max_length=24)


class Extraction(Strict):
    requirements: list[Extracted] = Field(max_length=MAX_REQUIREMENTS)


class Source(Strict):
    id: str
    kind: Literal["message", "comment", "image", "reference"]
    text: str
    reference_id: str | None = None
    image_id: str | None = None
    item_id: str | None = None
    component_id: str | None = None


class Requirement(Strict):
    id: str
    source: Source
    text: str
    needs: list[capabilities.Need] = Field(default_factory=list)
    mappings: list[Mapping] = Field(default_factory=list)
    component_ids: list[str] = Field(default_factory=list)
    resolution: Literal["unresolved", "accepted_alternative", "dropped"] = "unresolved"


class Alternative(Strict):
    id: str
    label: str


class Issue(Strict):
    id: str
    requirement: str
    status: Literal["unsupported_product", "unsupported_app", "needs_data", "needs_clarification", "unknown"]
    reason: str
    evidence: list[str] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)
    resolution: Literal["unresolved", "accepted_alternative", "dropped"] = "unresolved"


class PendingComment(Strict):
    component_id: str
    text: str


class PendingComments(Strict):
    id: str
    comments: list[PendingComment]


class Assessment(Strict):
    id: str | None = None
    state: Literal["unchecked", "blocked", "ready", "stale"] = "unchecked"
    input_digest: str | None = None
    prototype_stale: bool = False
    issues: list[Issue] = Field(default_factory=list, max_length=MAX_ISSUES)
    pending_comments: PendingComments | None = None


class Ledger(Strict):
    requirements: list[Requirement] = Field(default_factory=list, max_length=MAX_REQUIREMENTS)
    processed_sources: dict[str, str] = Field(default_factory=dict)
    decisions: list[dict] = Field(default_factory=list)
    assessment: Assessment | None = None
    prototype_stale: bool = False
    invalidated: bool = False
    scope_error: str | None = None
    verification: dict[str, list[dict]] = Field(default_factory=dict)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load(folder):
    path = folder / "requirements.json"
    return Ledger.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else Ledger()


def _json(folder, name):
    path = folder / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def inputs(db, build_id, folder):
    """Metadata only: never load rows, caches, credentials or reference image bytes."""
    with db.connect() as conn:
        sources = [{"id": r["id"], "table": r["bq_table"],
                    "columns": [{k: c[k] for k in ("name", "type", "bq_type", "date_like") if k in c} for c in json.loads(r["columns_json"])]}
                   for r in conn.execute("SELECT * FROM sources WHERE build_id=? ORDER BY rowid", (build_id,))]
        messages = []
        for r in conn.execute("SELECT * FROM messages WHERE build_id=? AND role='user' ORDER BY rowid", (build_id,)):
            try:
                comments = json.loads(r["text"]) if r["node"] == "revise" else None
            except ValueError:
                comments = None
            if isinstance(comments, list) and comments and all(isinstance(c, dict) and isinstance(c.get("text"), str) and isinstance(c.get("component_id"), str) for c in comments):
                messages.extend(Source(id=f'{r["id"]}:{i}', kind="comment", text=c["text"], component_id=c["component_id"]).model_dump()
                                for i, c in enumerate(comments))
            else:
                messages.append(Source(id=r["id"], kind="message", text=r["text"]).model_dump())
    reference = references.load(folder)
    incoming = list(messages)
    if reference:
        rid = reference["id"]
        if reference.get("instructions"):
            incoming.append(Source(id=rid + ":instructions", kind="reference", text=reference["instructions"], reference_id=rid).model_dump())
        if reference["mode"] == "recreate":
            for item in reference["interpretation"]["items"]:
                if item["kind"] in ("chart", "control", "unknown") or item.get("metric_label"):
                    incoming.append(Source(id=rid + ":" + item["id"], kind="image", text=json.dumps(item, ensure_ascii=False),
                        reference_id=rid, image_id=reference["images"][0]["id"], item_id=item["id"]).model_dump())
    definitions = {}
    for name in ("derived-fields.md", "kpis.md", "decisions.md"):
        path = folder / "docs" / name
        if path.is_file():
            definitions[name] = path.read_text(encoding="utf-8")
    return {"sources": sources, "incoming": incoming, "reference": reference,
            "definitions": definitions, "spec": _json(folder, "spec.json")}


def input_digest(snapshot, ledger, checker):
    return digest({"inputs": snapshot, "requirements": [r.model_dump() for r in ledger.requirements],
                   "decisions": ledger.decisions, "scope_error": ledger.scope_error, "registry_allowed": checker.digest()})


def schema(snapshot):
    fields = {}
    # Match the view builder's normalization, first-source collision rule and date
    # parsing. API display types (e.g. 'number') are not BigQuery physical types.
    for source in snapshot["sources"]:
        names = snake_names([c["name"] for c in source["columns"]])
        for col, name in zip(source["columns"], names):
            kind = col.get("bq_type", col["type"])
            fields.setdefault(name, "DATE" if col.get("date_like") and kind == "STRING" else kind)
    projection = (snapshot["spec"] or {}).get("datasource", {})
    if not snapshot["sources"]:
        # Legacy versions can carry only their published view schema.
        return {f["name"]: f["type"] for f in projection.get("fields", [])}
    # Only the existing view pipeline can establish a derived field. A stale spec
    # alone cannot invent a connected field or resurrect a removed prerequisite.
    text = snapshot["definitions"].get("derived-fields.md", "")
    metadata = yaml.safe_load(text.split("---", 2)[1]) if text.startswith("---") else {}
    if not isinstance(metadata, dict) or metadata.get("view") != projection.get("table"):
        return fields
    derived = {f["name"]: f for f in metadata.get("fields", [])}
    previous_base = {f["name"] for f in projection.get("fields", [])} - derived.keys()
    missing = previous_base - fields.keys()
    for name, definition in derived.items():
        normalized_sql = re.sub(r"`([^`]+)`", lambda m: snake_names([m[1]])[0], definition["sql"])
        if not any(re.search(r"(?<![a-z0-9_])" + re.escape(f) + r"(?![a-z0-9_])", normalized_sql, re.I) for f in missing):
            fields.setdefault(name, definition["type"])
    return fields


def new_sources(snapshot, ledger):
    return [s for s in snapshot["incoming"] if ledger.processed_sources.get(s["id"]) != digest(s)]


def merge(ledger, snapshot, extraction):
    """Append code-identified requirements. A model cannot delete earlier intent or spoof a source."""
    updated = ledger.model_copy(deep=True)
    sources = {s["id"]: s for s in new_sources(snapshot, ledger)}
    if any(r.source_id not in sources for r in extraction.requirements):
        raise ValueError("Extraction cites an unknown source")
    current_ref = (snapshot["reference"] or {}).get("id")
    updated.requirements = [r for r in updated.requirements if not r.source.reference_id or r.source.reference_id == current_ref]
    for item in extraction.requirements:
        source = Source.model_validate(sources[item.source_id])
        rid = "req_" + digest({"source": source.model_dump(), "text": item.text})[:24]
        existing = next((r for r in updated.requirements if r.id == rid), None)
        if existing is not None:
            # Repeated descriptions must not hide a second (possibly unsupported)
            # need. Preserve the union instead of retaining only the first row.
            existing.needs += [n for n in item.needs if n not in existing.needs]
            existing.mappings += [m for m in item.mappings if m not in existing.mappings]
            existing.component_ids = list(dict.fromkeys(existing.component_ids + item.component_ids))
            continue
        updated.requirements.append(Requirement(id=rid, source=source, **item.model_dump(exclude={"source_id"})))
    covered = {r.source_id for r in extraction.requirements}
    # Fail closed when extraction omits an entire message or observed chart.
    for sid, source in sources.items():
        if sid not in covered:
            updated.requirements.append(Requirement(id="req_" + digest(source)[:24], source=Source.model_validate(source), text=source["text"]))
    if len(updated.requirements) > MAX_REQUIREMENTS:
        raise ValueError("Requirement scope exceeded")
    updated.processed_sources.update({sid: digest(s) for sid, s in sources.items()})
    updated.scope_error = None
    return updated


def _normal(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def mapping_verdict(mapping, requirement, fields):
    field, label = mapping.field, _normal(mapping.label)
    if field is None:
        return capabilities.Verdict("needs_clarification" if fields else "needs_data", f"Define {mapping.label} and its field, aggregation, unit and date grain")
    if field not in fields:
        return capabilities.Verdict("needs_data", f"Field {field} is not in the connected data")
    # Merely listing available fields is not a definition. Accept a direct positive
    # assignment clause, never an incidental mention (or a negated instruction).
    field_pattern, label_pattern = re.escape(field), re.escape(mapping.label)
    explicit = re.search(r"(?:^|[.;\n])\s*(?:please\s+)?(?:use\s+" + field_pattern + r"\s+(?:for|as)\s+" + label_pattern
        + r"|" + label_pattern + r"\s*(?:means|is|uses|=|:)\s*" + field_pattern + r")(?=\s*(?:$|[,.;\n]))", requirement.source.text, re.I)
    if label != _normal(field) and not explicit:
        return capabilities.Verdict("needs_clarification", f"Confirm which field defines {mapping.label}; proposed {field} is not an explicit definition")
    terms = {"sum": ("sum", "summed", "total", "totals"), "avg": ("avg", "average", "mean"),
             "count_distinct": ("count_distinct", "distinct", "unique")}
    for name in ("aggregation", "unit", "date_grain"):
        value = getattr(mapping, name)
        if value is None:
            continue
        candidates = terms.get(value, (value, value + "ly")) if name != "unit" else (value,)
        if not any(re.search(r"(?<![a-z0-9_])" + re.escape(v) + r"(?![a-z0-9_])", requirement.source.text, re.I) for v in candidates):
            return capabilities.Verdict("needs_clarification", f"Confirm {name.replace('_', ' ')} {value} for {mapping.label}; it is not defined by the source")
    return None


def evaluate(snapshot, ledger, checker):
    """Pure bounded recomputation; does not call a model, write SQL or publish artifacts."""
    fields, found = schema(snapshot), []
    def add(rid, text, verdict):
        if verdict.ok:
            return
        # Unknown behavior explicitly asks for clarification, retaining unknown classification.
        reason = verdict.reason + ("; clarify the requested behavior" if verdict.status == "unknown" else "")
        found.append(Issue(id="issue_" + digest([rid, verdict.capability, verdict.status, reason])[:24], requirement=text,
                           status=verdict.status, reason=reason, evidence=list(verdict.evidence)))
    for r in ledger.requirements:
        # Resolutions are written by code in the explicit decision API, never by extraction.
        if r.resolution == "dropped":
            continue
        for v in checker.requirement(capabilities.Requirement(id=r.id, needs=r.needs), fields):
            add(r.id, r.text, v)
        for m in r.mappings:
            verdict = mapping_verdict(m, r, fields)
            if verdict:
                add(r.id, r.text, verdict)
    for page in (snapshot["spec"] or {}).get("pages", []):
        for component in page.get("components", []):
            for verdict in checker.component(component):
                add(component["id"], component.get("label", component["id"]), verdict)
            bound = list(component.get("dimensions", [])) + [m["field"] for m in component.get("metrics", [])]
            bound += [component[k] for k in ("date_dimension", "breakdown", "field") if component.get(k)]
            if component.get("sort"):
                bound.append(component["sort"]["field"])
            for field in sorted(set(bound) - fields.keys()):
                add(component["id"], component.get("label", component["id"]),
                    capabilities.Verdict("needs_data", f"Field {field} is not in the connected data"))
    if sum(len(p.get("components", [])) for p in (snapshot["spec"] or {}).get("pages", [])) > 24:
        add("scope", "Assessment scope", capabilities.Verdict("needs_clarification", "More than 24 components; reduce the request scope"))
    if ledger.scope_error:
        add("scope", "Assessment scope", capabilities.Verdict("needs_clarification", ledger.scope_error))
    if len(found) > MAX_ISSUES:
        # No silent truncation: one scope issue represents the entire refusal; full ledger retained.
        found = [Issue(id="issue_scope", requirement="Assessment scope", status="needs_clarification",
                       reason="More than 20 issues; reduce the request scope and check again")]
    return Assessment(id=new_id("assessment"), state="blocked" if found else "ready",
        input_digest=input_digest(snapshot, ledger, checker), prototype_stale=ledger.prototype_stale, issues=found,
        pending_comments=ledger.assessment.pending_comments if ledger.assessment else None)


def verification(snapshot, ledger, checker):
    """Retain the full code-owned proof, including support (the public issues omit it)."""
    fields, proof = schema(snapshot), {}
    for r in ledger.requirements:
        rows = []
        for need in r.needs:
            verdict = checker.need(need, fields)
            rows.append({"capability": need.capability, "status": verdict.status, "reason": verdict.reason,
                         "evidence": list(verdict.evidence), "fields": need.fields, "value": need.value,
                         "component_ids": r.component_ids})
        for mapping in r.mappings:
            verdict = mapping_verdict(mapping, r, fields)
            rows.append({"mapping": mapping.model_dump(), "status": verdict.status if verdict else "supported",
                         "reason": verdict.reason if verdict else "Original source defines this binding",
                         "source_id": r.source.id, "schema_type": fields.get(mapping.field), "component_ids": r.component_ids})
        proof[r.id] = rows or [{"status": "unknown", "reason": "No registered capability covers this requirement"}]
    return proof


def get(snapshot, ledger, checker):
    """GET is a read-only projection. Expired IDs cannot authorize later actions."""
    assessment = ledger.assessment.model_copy(deep=True) if ledger.assessment else Assessment()
    changed = assessment.input_digest is not None and assessment.input_digest != input_digest(snapshot, ledger, checker)
    if changed or ledger.invalidated:
        assessment.state, assessment.id = "stale", None
    assessment.prototype_stale = ledger.prototype_stale or bool(changed and snapshot["spec"])
    return assessment


def save(folder, ledger, assessment=None):
    """Stage OKF summary and ledger with rollback. requirements.json is the commit point."""
    from dss.harness.nodes.intake import write_doc
    folder.mkdir(parents=True, exist_ok=True)
    docs = folder / "docs"
    docs.mkdir(exist_ok=True)
    if assessment is not None:
        ledger = ledger.model_copy(deep=True)
        ledger.assessment, ledger.invalidated = assessment, False
    targets = [folder / "requirements.json", docs / "feasibility.md", docs / "index.md", docs / "log.md"]
    backup = {p: p.read_bytes() for p in targets if p.is_file()}
    try:
        a = ledger.assessment.model_copy(deep=True) if ledger.assessment else Assessment()
        if ledger.invalidated:
            a.state, a.id = "stale", None
        body = "# Feasibility\n\nState: " + a.state + "\n\n## Requirements and mappings\n\n"
        body += "\n".join("- " + json.dumps(r.model_dump(), ensure_ascii=False) for r in ledger.requirements)
        body += "\n\n## Issues\n\n" + "\n".join("- " + i.reason for i in a.issues) + "\n"
        body += "\n## Verification evidence\n\n" + json.dumps(ledger.verification, ensure_ascii=False, indent=2) + "\n"
        write_doc(docs / "feasibility.md", {"type": "Feasibility Assessment", "title": "Feasibility", "state": a.state}, body)
        references._index(docs, {"feasibility.md": "Feasibility"}, write_doc)
        references._log(docs, "feasibility " + a.state, write_doc)
        temporary = folder / "requirements.json.tmp"
        temporary.write_text(ledger.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(folder / "requirements.json")
    except BaseException:
        for p in targets:
            if p in backup:
                p.write_bytes(backup[p])
            else:
                p.unlink(missing_ok=True)
        (folder / "requirements.json.tmp").unlink(missing_ok=True)
        raise


def reference_changed(folder):
    ledger = load(folder)
    ledger.invalidated = True
    ledger.prototype_stale |= (folder / "spec.json").is_file()
    save(folder, ledger)
