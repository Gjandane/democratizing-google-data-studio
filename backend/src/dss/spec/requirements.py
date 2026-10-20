"""Version-local intent ledger and deterministic feasibility projection.

The extractor proposes needs, never verdicts or resolutions. This module owns IDs,
provenance, classification, input invalidation and the durable assessment commit point.
"""
import hashlib
import json
import re
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from dss.db import new_id
from dss.harness.guardrails import RunError
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


class Property(Strict):
    path: Literal['label', 'text', 'grid.col', 'grid.row', 'grid.w', 'grid.h',
                  'style.font_size', 'style.color', 'style.background_color']
    value: StrictStr | StrictInt

    @model_validator(mode='after')
    def typed(self):
        numeric = self.path.startswith('grid.') or self.path == 'style.font_size'
        if numeric and (type(self.value) is not int or not 1 <= self.value <= 10000):
            raise ValueError('Numeric properties need a positive integer')
        if not numeric and (not isinstance(self.value, str) or len(self.value) > 4000):
            raise ValueError('Text properties need a bounded string')
        if self.path.startswith('style.') and self.path != 'style.font_size' and not re.fullmatch(r'#[0-9a-fA-F]{6}', self.value):
            raise ValueError('Color properties need a hex color')
        return self


class Extracted(Strict):
    source_id: str = Field(min_length=1, max_length=240)
    text: str = Field(min_length=1, max_length=2000)
    needs: list[capabilities.Need] = Field(default_factory=list, max_length=20)
    mappings: list[Mapping] = Field(default_factory=list, max_length=20)
    component_ids: list[str] = Field(default_factory=list, max_length=24)
    properties: list[Property] = Field(default_factory=list, max_length=20,
        description='Exact requested item properties, including title text, layout and decoration styling. Preserve explicit values; vague changes stay unknown.')


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
    batch_id: str | None = None


class Requirement(Strict):
    id: str
    source: Source
    text: str
    needs: list[capabilities.Need] = Field(default_factory=list)
    mappings: list[Mapping] = Field(default_factory=list)
    component_ids: list[str] = Field(default_factory=list)
    resolution: Literal["unresolved", "accepted_alternative", "dropped"] = "unresolved"
    clarifications: list[Source] = Field(default_factory=list)
    properties: list[Property] = Field(default_factory=list)
    superseded: dict[str, str] = Field(default_factory=dict)


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


class DecisionInput(Strict):
    issue_id: str = Field(min_length=1)
    action: Literal["accept_alternative", "drop"]
    alternative_id: str | None

    @model_validator(mode="after")
    def check_action(self):
        if (self.action == "accept_alternative") != bool(self.alternative_id):
            raise ValueError("Accept needs an alternative id; drop needs null")
        if self.action == "drop" and self.alternative_id is not None:
            raise ValueError("Drop needs null")
        return self


class Decisions(Strict):
    assessment_id: str = Field(min_length=1)
    decisions: list[DecisionInput] = Field(min_length=1, max_length=MAX_ISSUES)

    @model_validator(mode="after")
    def distinct(self):
        if len({d.issue_id for d in self.decisions}) != len(self.decisions):
            raise ValueError("Choose each issue once")
        return self


class Reapply(Strict):
    assessment_id: str = Field(min_length=1)
    batch_id: str = Field(min_length=1)


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
    scope_batch_id: str | None = None
    verification: dict[str, list[dict]] = Field(default_factory=dict)
    pending_comments: PendingComments | None = None
    retired_sources: list[str] = Field(default_factory=list)


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
            if r['node'] == 'comment_batch':
                continue  # Pending/applied batch sources already retain this intent.
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
                   "decisions": ledger.decisions, "scope_error": ledger.scope_error,
                   "pending_comments": ledger.pending_comments.model_dump() if ledger.pending_comments else None,
                   "retired_sources": ledger.retired_sources, "registry_allowed": checker.digest()})


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
    incoming = {s["id"]: s for s in snapshot["incoming"]}
    if ledger.pending_comments:
        batch = ledger.pending_comments
        for i, comment in enumerate(batch.comments):
            s = Source(id=f"{batch.id}:{i}", kind="comment", batch_id=batch.id, **comment.model_dump()).model_dump()
            incoming[s["id"]] = s
    return [s for s in incoming.values() if s["id"] not in ledger.retired_sources
            and ledger.processed_sources.get(s["id"]) != digest(s)]


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
        if source.batch_id and source.component_id:
            if item.component_ids and item.component_ids != [source.component_id]:
                raise ValueError('Comment extraction must preserve its target')
            item = item.model_copy(update={'component_ids': [source.component_id]})
        rid = "req_" + digest({"source": source.model_dump(), "text": item.text})[:24]
        existing = next((r for r in updated.requirements if r.id == rid), None)
        if existing is not None:
            # Repeated descriptions must not hide a second (possibly unsupported)
            # need. Preserve the union instead of retaining only the first row.
            if bool(existing.needs) != bool(item.needs):
                # An unclassified row cannot disappear into a supported row with
                # an identical description. Code owns this unknown sentinel.
                unknown = capabilities.Need(capability='unknown.unclassified')
                if unknown not in existing.needs:
                    existing.needs.append(unknown)
            existing.needs += [n for n in item.needs if n not in existing.needs]
            existing.mappings += [m for m in item.mappings if m not in existing.mappings]
            existing.properties += [p for p in item.properties if p not in existing.properties]
            existing.component_ids = list(dict.fromkeys(existing.component_ids + item.component_ids))
            continue
        updated.requirements.append(Requirement(id=rid, source=source, **item.model_dump(exclude={"source_id"})))
    covered = {r.source_id for r in extraction.requirements}
    # Fail closed when extraction omits an entire message or observed chart.
    for sid, source in sources.items():
        if sid not in covered:
            updated.requirements.append(Requirement(id="req_" + digest(source)[:24], source=Source.model_validate(source), text=source["text"]))
    # A later explicit field definition can clarify an earlier ambiguity, but
    # cannot remove its capabilities or provenance. Model suggestions alone do not.
    for item in extraction.requirements:
        source = Source.model_validate(sources[item.source_id])
        clarified, previous_needs = set(), []
        for mapping in item.mappings:
            proposed = Requirement(id='', source=source, text=item.text, mappings=[mapping])
            if mapping_verdict(mapping, proposed, schema(snapshot)) or not _assignment(source.text, mapping):
                continue
            for previous in updated.requirements:
                if previous.source.id == source.id:
                    continue
                for i, old in enumerate(previous.mappings):
                    if _normal(old.label) != _normal(mapping.label):
                        continue
                    values = old.model_dump()
                    values.update({k: v for k, v in mapping.model_dump().items() if v is not None})
                    previous.mappings[i] = Mapping.model_validate(values)
                    if source not in previous.clarifications:
                        previous.clarifications.append(source)
                    clarified.add(mapping.label)
                    previous_needs.extend(previous.needs)
        rid = 'req_' + digest({'source': source.model_dump(), 'text': item.text})[:24]
        merged = next((r for r in updated.requirements if r.id == rid), None)
        definition_only = len(item.mappings) == 1 and (assignment := _assignment(source.text, item.mappings[0])) and not source.text[assignment.end():].strip(' .;\r\n\t')
        if (merged and definition_only and merged.mappings and all(m.label in clarified for m in merged.mappings)
                and all(n in previous_needs for n in merged.needs)):
            # A definition-only reply refines the original requirement. Keep its
            # original grain/unit/aggregation instead of making an unconstrained
            # duplicate that would demand a different chart binding.
            updated.requirements = [r for r in updated.requirements if r.id != rid]
    if len(updated.requirements) > MAX_REQUIREMENTS:
        raise ValueError("Requirement scope exceeded")
    updated.processed_sources.update({sid: digest(s) for sid, s in sources.items()})
    _supersede_comments(updated, snapshot, sources)
    updated.scope_error = None
    updated.scope_batch_id = None
    return updated


def _supersede_comments(ledger, snapshot, sources):
    """Later assignments override the same property, never an unrelated/unsupported behavior."""
    checker = capabilities.Checker(capabilities.load_registry())
    def slots(r):
        result = {f'property:{i}': 'property:' + p.path for i, p in enumerate(r.properties)}
        for i, n in enumerate(r.needs):
            cap = checker.registry.get(n.capability)
            if cap and checker.need(n, schema(snapshot)).ok:
                if cap.component_type:
                    result[f'need:{i}'] = 'component.type'
                elif n.value is not None and len(cap.recipe) == 1:
                    result[f'need:{i}'] = 'recipe:' + cap.recipe[0]
        return result
    order = {sid: i for i, sid in enumerate(sources)}
    incoming = sorted((r for r in ledger.requirements if r.source.id in sources and r.source.batch_id), key=lambda r: order[r.source.id])
    previous = [r for r in ledger.requirements if r.source.id not in sources]
    for r in incoming:
        keys = (set(slots(r).values()) if r.needs and all(checker.need(n, schema(snapshot)).ok for n in r.needs)
                and not any(mapping_verdict(m, r, schema(snapshot)) for m in r.mappings) else set())
        for old in previous:
            if old.source.kind == 'comment' and old.source.id != r.source.id and old.component_ids == r.component_ids:
                old.superseded.update({slot: r.id for slot, key in slots(old).items() if key in keys and slot not in old.superseded})
        previous.append(r)


def _normal(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def audience_requirement(requirement):
    """Code-owned, bounded interview metadata; never downgrade free-form behavior.

    Match the ENTIRE original message. A suffix requesting an unknown feature
    cannot become audience metadata merely because its prefix names a role.
    """
    if requirement.needs or requirement.mappings or requirement.source.kind != 'message':
        return False
    role = (r'(?:(?:sales|finance|marketing|operations|product|engineering|executive|leadership)\s+'
            r'(?:director|manager|team|leaders?|analysts?)|ceo|cfo|cto|coo|executives?|analysts?|leadership)')
    prefix = r'(?:(?:help|for|this is for|the dashboard is for|(?:the )?audience (?:is|:))\s+)?(?:our\s+|my\s+|the\s+|a\s+|an\s+)?'
    return bool(re.fullmatch(prefix + role + r'[.!]?', ' '.join(requirement.source.text.strip().split()), re.I))


def _assignment(text, mapping):
    if not mapping.field:
        return None
    field_pattern, label_pattern = re.escape(mapping.field), re.escape(mapping.label)
    return re.search(r"(?:^|[.;\n])\s*(?:please\s+)?(?:use\s+" + field_pattern + r"\s+(?:for|as)\s+" + label_pattern
        + r"|" + label_pattern + r"\s*(?:means|is|uses|=|:)\s*" + field_pattern + r")(?=\s*(?:$|[,.;\n]))", text, re.I)


def mapping_verdict(mapping, requirement, fields):
    field, label = mapping.field, _normal(mapping.label)
    if field is None:
        return capabilities.Verdict("needs_clarification" if fields else "needs_data", f"Define {mapping.label} and its field, aggregation, unit and date grain")
    if field not in fields:
        return capabilities.Verdict("needs_data", f"Field {field} is not in the connected data")
    # Merely listing available fields is not a definition. Accept a direct positive
    # assignment clause, never an incidental mention (or a negated instruction).
    text = "\n".join(s.text for s in [requirement.source, *requirement.clarifications])
    explicit = _assignment(text, mapping)
    if label != _normal(field) and not explicit:
        return capabilities.Verdict("needs_clarification", f"Confirm which field defines {mapping.label}; proposed {field} is not an explicit definition")
    terms = {"sum": ("sum", "summed", "total", "totals"), "avg": ("avg", "average", "mean"),
             "count_distinct": ("count_distinct", "distinct", "unique")}
    for name in ("aggregation", "unit", "date_grain"):
        value = getattr(mapping, name)
        if value is None:
            continue
        candidates = terms.get(value, (value, value + "ly")) if name != "unit" else (value,)
        if not any(re.search(r"(?<![a-z0-9_])" + re.escape(v) + r"(?![a-z0-9_])", text, re.I) for v in candidates):
            return capabilities.Verdict("needs_clarification", f"Confirm {name.replace('_', ' ')} {value} for {mapping.label}; it is not defined by the source")
    return None


def meaning(requirement):
    """Authorization follows requested meaning, not a generated assessment or registry version."""
    # Empty optional provenance must not revoke pre-11.6 durable choices.
    excluded = {'resolution', 'superseded'} | ({'clarifications'} if not requirement.clarifications else set()) | ({'properties'} if not requirement.properties else set())
    return digest(requirement.model_dump(exclude=excluded))


def _prerequisites(snapshot, needs, mappings):
    fields = schema(snapshot)
    names = {f for n in needs for f in n.fields.values()} | {m.field for m in mappings if m.field}
    origins = {}
    for source in snapshot["sources"]:
        for col, name in zip(source["columns"], snake_names([c["name"] for c in source["columns"]])):
            if name in names:
                origins.setdefault(name, {"table": source.get("table"), "column": col})
    if not snapshot["sources"]:
        projection = (snapshot["spec"] or {}).get("datasource", {})
        origins = {n: {"table": projection.get("table")} for n in names}
    # Only a relevant derived definition binds a choice; unrelated definitions do not revoke it.
    text = snapshot["definitions"].get("derived-fields.md", "")
    metadata = yaml.safe_load(text.split("---", 2)[1]) if text.startswith("---") else {}
    derived = {f["name"]: f for f in (metadata or {}).get("fields", []) if f["name"] in names}
    return digest({"fields": {n: fields.get(n) for n in sorted(names)}, "origins": origins, "derived": derived})


def _offers(requirement, slot, snapshot, checker):
    """Small curated substitutions. Every field binding is named in the explicit choice."""
    if not slot.startswith("need:"):
        return []  # Undefined metrics need data/text through the interview, never an inferred definition.
    need = requirement.needs[int(slot.split(":")[1])]
    if need.capability not in {"animation.temporal_playback", "geo.lat_long_points", "refresh.realtime_streaming"}:
        return []
    fields, candidates = schema(snapshot), []
    for field, kind in sorted(fields.items()):
        if kind in {"DATE", "DATETIME", "TIMESTAMP"}:
            candidates.append((f"Time series using {field} (no point playback or streaming)",
                               [capabilities.Need(capability="chart.time_series", fields={"date_field": field})]))
        if field in {"country", "region", "city"} and kind in {"GEO", "GEOGRAPHY"}:
            candidates.append((f"Static {field} aggregate map using {field} (no point playback)", [
                capabilities.Need(capability="chart.geo_map", fields={"geo_field": field}),
                capabilities.Need(capability="option.geo_map.geo_type", value=field, fields={"geo_field": field})]))
    offered = []
    for label, needs in candidates:
        if all(checker.need(n, fields).ok for n in needs):
            payload = [n.model_dump() for n in needs]
            aid = "alt_" + digest([requirement.id, meaning(requirement), slot, payload])[:24]
            offered.append({"id": aid, "label": label, "needs": payload})
    return offered[:MAX_ISSUES]


def _bindings(snapshot, requirement):
    return {c["id"]: {k: c.get(k) for k in ("type", "dimensions", "metrics", "date_dimension", "field", "options")}
            for page in (snapshot["spec"] or {}).get("pages", []) for c in page.get("components", [])
            if c["id"] in requirement.component_ids}


def _matches(snapshot, requirement, needs, checker):
    if not requirement.component_ids:
        return any(_component_fulfills(c, requirement, needs, checker, snapshot)
                   for p in (snapshot['spec'] or {}).get('pages', []) for c in p.get('components', []))
    bindings = _bindings(snapshot, requirement)
    if set(bindings) != set(requirement.component_ids):
        return False
    for c in bindings.values():
        for n in needs:
            cap = checker.registry.get(n.capability)
            if cap is None:
                return False
            expected = cap.component_type or next((checker.registry.get(dep).component_type for dep in cap.requires
                                                  if checker.registry.get(dep).component_type), None)
            if expected and c["type"] != expected:
                return False
            for key, field in n.fields.items():
                bound = c["date_dimension"] if key == "date_field" else (c["dimensions"] or [None])[0]
                if bound != field:
                    return False
            if cap.id == "option.geo_map.geo_type" and (c["options"] or {}).get("geo_type") != n.value:
                return False
        bound = set(c["dimensions"] or []) | {m["field"] for m in c["metrics"] or []} | {c["date_dimension"], c["field"]}
        for mapping in requirement.mappings:
            if mapping.field and mapping.field not in bound:
                return False
            if mapping.aggregation and any(m["field"] == mapping.field and m["agg"] != mapping.aggregation for m in c["metrics"] or []):
                return False
    return True


def revalidate_decisions(snapshot, ledger, checker):
    """Seal a fulfilled choice so the superseded prototype cannot authorize a later mapping change."""
    updated = ledger.model_copy(deep=True)
    requirements = {r.id: r for r in updated.requirements}
    for d in updated.decisions:
        r = requirements.get(d.get("requirement_id"))
        if not r or d["action"] != "accept_alternative" or d.get("applied") or d["meaning"] != meaning(r):
            continue
        needs = [capabilities.Need.model_validate(n) for n in d["alternative"]["needs"]]
        if _matches(snapshot, r, needs, checker):
            d["applied"] = True
    return updated


def _choice(requirement, slot, snapshot, ledger, checker):
    for d in reversed(ledger.decisions):
        if d.get("requirement_id") != requirement.id or d.get("meaning") != meaning(requirement):
            continue
        if d["action"] == "drop":
            return d
        if d["slot"] != slot:
            continue
        needs = [capabilities.Need.model_validate(n) for n in d["alternative"]["needs"]]
        if not all(checker.need(n, schema(snapshot)).ok for n in needs):
            return None
        if d["prerequisites"] != _prerequisites(snapshot, needs, requirement.mappings):
            return None
        # A fresh choice authorizes repairing exactly its old prototype, without
        # claiming that prototype already fulfills it. Once fulfilled, only the
        # selected binding is authorized on subsequent spec revalidation.
        if not _matches(snapshot, requirement, needs, checker):
            if d.get("applied") or d.get("baseline") != _bindings(snapshot, requirement):
                return None
        return d
    return None


def _requirement_issues(snapshot, ledger, checker):
    """Internal issue targets never come from client/model claims."""
    fields, rows = schema(snapshot), []
    for r in ledger.requirements:
        verdicts = [(f"need:{i}", checker.need(n, fields)) for i, n in enumerate(r.needs) if f'need:{i}' not in r.superseded]
        if not r.needs and not audience_requirement(r):
            verdicts.append(("unknown", capabilities.Verdict("unknown", "No registered capability covers this requirement")))
        verdicts += [(f"mapping:{i}", v) for i, m in enumerate(r.mappings) if (v := mapping_verdict(m, r, fields))]
        for slot, v in verdicts:
            if v.ok:
                continue
            reason = v.reason + ("; clarify the requested behavior" if v.status == "unknown" else "")
            iid = "issue_" + digest([r.id, meaning(r), slot, v.capability, v.status, reason])[:24]
            choice = _choice(r, slot, snapshot, ledger, checker)
            resolution = ("dropped" if choice["action"] == "drop" else "accepted_alternative") if choice else "unresolved"
            offers = _offers(r, slot, snapshot, checker)
            rows.append((Issue(id=iid, requirement=r.text, status=v.status, reason=reason,
                evidence=list(v.evidence), alternatives=[Alternative(id=o["id"], label=o["label"]) for o in offers],
                resolution=resolution), r, slot, offers))
            if len(rows) > MAX_ISSUES:
                return rows  # Full verification retains all needs; public assessment is a scope refusal.
    return rows


def evaluate(snapshot, ledger, checker, *, check_components=True):
    """Pure bounded recomputation; does not call a model, write SQL or publish artifacts."""
    fields = schema(snapshot)
    found = [row[0] for row in _requirement_issues(snapshot, ledger, checker)]
    def add(rid, text, verdict):
        if verdict.ok:
            return
        # Unknown behavior explicitly asks for clarification, retaining unknown classification.
        reason = verdict.reason + ("; clarify the requested behavior" if verdict.status == "unknown" else "")
        found.append(Issue(id="issue_" + digest([rid, verdict.capability, verdict.status, reason])[:24], requirement=text,
                           status=verdict.status, reason=reason, evidence=list(verdict.evidence)))
    for page in ((snapshot["spec"] or {}).get("pages", []) if check_components else []):
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
    if len(found) > MAX_ISSUES or sum(len(i.alternatives) for i in found) > MAX_ISSUES:
        # No silent truncation: one scope issue represents the entire refusal; full ledger retained.
        found = [Issue(id="issue_scope", requirement="Assessment scope", status="needs_clarification",
                       reason="More than 20 issues; reduce the request scope and check again")]
    return Assessment(id=new_id("assessment"), state="blocked" if any(i.resolution == "unresolved" for i in found) else "ready",
        input_digest=input_digest(snapshot, ledger, checker), prototype_stale=ledger.prototype_stale or bool(ledger.pending_comments),
        issues=found, pending_comments=ledger.pending_comments)


def blocked(assessment):
    return RunError("feasibility_blocked", explanation(assessment), 409,
                    {"assessment_id": assessment.id,
                     "issue_ids": [i.id for i in assessment.issues if i.resolution == "unresolved"]})


def explanation(assessment):
    parts = []
    for issue in assessment.issues:
        if issue.resolution != "unresolved":
            continue
        text = f"{issue.requirement}: {issue.reason}."
        if issue.alternatives:
            text += " Supported alternatives: " + "; ".join(a.label for a in issue.alternatives) + ". Choose explicitly before planning."
        if issue.status in {"needs_clarification", "unknown"}:
            text += " Please clarify the requested behavior or definition."
        parts.append(text)
    return "Feasibility needs attention. " + " ".join(parts)


def plan_preflight(db, build_id, folder):
    """Deterministic API gate; new intent is extracted inside the accepted Workflow."""
    snapshot, ledger, checker = inputs(db, build_id, folder), load(folder), capabilities.Checker(capabilities.load_registry())
    ledger = revalidate_decisions(snapshot, ledger, checker)
    assessment = evaluate(snapshot, ledger, checker, check_components=False)
    if assessment.state == "blocked":
        current = get(snapshot, ledger, checker)
        if current.state == 'blocked' and current.issues == assessment.issues:
            raise blocked(current)
        ledger.verification = verification(snapshot, ledger, checker)
        save(folder, ledger, assessment)
        raise blocked(assessment)


def coverage_errors(snapshot, ledger, checker, *, bindings=None):
    """Verify original intent against the candidate, never against a reduced model ledger."""
    errors = []
    assessment = evaluate(snapshot, ledger, checker)
    for issue in assessment.issues:
        if issue.resolution == "unresolved":
            errors.append({"path": "requirements", "message": issue.reason})
    components = [c for p in (snapshot["spec"] or {}).get("pages", []) for c in p.get("components", [])]
    from dss.recipe.compiler import compile_recipe
    from dss.spec.models import DashboardSpec
    ops = [json.loads(line) for line in compile_recipe(DashboardSpec.model_validate(snapshot['spec']), 1).split('\n')[1:-1]]
    for r in ledger.requirements:
        if audience_requirement(r):
            continue
        choice = _choice(r, 'unknown', snapshot, ledger, checker)
        if choice and choice['action'] == 'drop':
            continue
        needs = []
        dropped = False
        for i, need in enumerate(r.needs):
            if f'need:{i}' in r.superseded:
                continue
            choice = _choice(r, f"need:{i}", snapshot, ledger, checker)
            if choice and choice["action"] == "drop":
                dropped = True
                break
            needs.extend([capabilities.Need.model_validate(n) for n in choice["alternative"]["needs"]]
                         if choice else [need])
        if dropped:
            continue
        properties = [p for i, p in enumerate(r.properties) if f'property:{i}' not in r.superseded]
        if not needs and not properties and r.superseded and not r.mappings:
            continue
        active = r.model_copy(update={'properties': properties})
        candidates = [c for c in components if not r.component_ids or c["id"] in r.component_ids]
        matches = [c for c in candidates if _component_fulfills(c, active, needs, checker, snapshot) and
                   all(_recipe_fulfills(n, checker, [op for op in ops if op.get('component_id') in (None, c['id'])]) for n in needs)]
        decorations = {c['id']: c for p in (snapshot['spec'] or {}).get('pages', []) for c in p.get('decorations', [])}
        decoration_proven = (r.component_ids and set(r.component_ids) <= decorations.keys() and properties
                             and all(_properties_match(decorations[cid], properties) for cid in r.component_ids))
        if (not r.component_ids or decoration_proven) and not r.mappings and needs and all(
                n.capability.startswith('layout.') and _recipe_fulfills(n, checker, ops) for n in needs):
            continue
        if not matches or (r.component_ids and {c["id"] for c in matches} != set(r.component_ids)):
            errors.append({"path": "requirements." + r.id, "message": "Candidate spec does not fulfill requirement: " + r.text})
        elif bindings is not None:
            bindings[r.id] = [c['id'] for c in matches]
    return errors


def _recipe_fulfills(need, checker, ops):
    """A registry capability must actually survive the deterministic compiler."""
    cap = checker.registry.get(need.capability)
    if cap is None or not cap.recipe:
        return False
    for locator in cap.recipe:
        path, _, fixed = locator.partition('=')
        keys = path.split('.')
        operation, keys = keys[0], keys[1:]
        if path == 'add_chart.sort':
            keys.append('order')
        if len(keys) > 1 and keys[0] == 'options':
            keys = [keys[0], *keys[2:]]  # Registry options include their chart type.
        expected = fixed if '=' in locator else need.value
        found = False
        for op in ops:
            if op['op'] != operation:
                continue
            values = [op]
            for key in keys:
                values = [v[key] for value in values for v in (value if isinstance(value, list) else [value])
                          if isinstance(v, dict) and key in v]
            if not keys:
                found = expected is None
            else:
                found = any(expected is None or (type(v) is type(expected) and v == expected) for v in values)
            if found:
                break
        if not found:
            return False
    return True


def _component_fulfills(component, requirement, needs, checker, snapshot):
    """Check type, typed options, real bindings and metric semantics on the same component."""
    if (not needs and not requirement.properties) or checker.component(component) or not _properties_match(component, requirement.properties):
        return False
    for need in needs:
        cap = checker.registry.get(need.capability)
        if cap is None:
            return False
        expected = cap.component_type or next((checker.registry.get(dep).component_type for dep in cap.requires
                                              if checker.registry.get(dep).component_type), None)
        if expected and component["type"] != expected:
            return False
        for key, field in need.fields.items():
            bound = component.get("date_dimension") if key == "date_field" else (component.get("dimensions") or [None])[0]
            bucketed = key == 'date_field' and any(m.date_grain and _date_bucket(snapshot, bound, m.date_grain, field)
                                                 for m in requirement.mappings)
            if field != bound and not bucketed:
                return False
        for locator in cap.recipe:
            if locator.startswith("add_chart.options."):
                _, _, kind, key = locator.split(".")
                if component["type"] != kind or key not in component.get("options", {}):
                    return False
                value = component["options"][key]
                if need.value is not None and (type(value) is not type(need.value) or value != need.value):
                    return False
            elif locator == "add_chart.metrics.agg":
                if not any(m["agg"] == need.value for m in component.get("metrics", [])):
                    return False
            elif locator.startswith("add_chart.") and "=" not in locator:
                key = locator.split(".")[1]
                value = component.get("label" if key == "title" else key)
                if value is None or (need.value is not None and value != need.value and
                                     not (key == "sort" and value.get("order") == need.value)):
                    return False
    bound = set(component.get("dimensions", [])) | {m["field"] for m in component.get("metrics", [])}
    bound |= {component.get("date_dimension"), component.get("field"), component.get("breakdown")}
    for mapping in requirement.mappings:
        if mapping.field not in bound:
            return False
        metrics = [m for m in component.get("metrics", []) if m["field"] == mapping.field]
        if mapping.aggregation and (not metrics or any(m["agg"] != mapping.aggregation for m in metrics)):
            return False
        if mapping.date_grain:
            # Recipe 1.0 exposes no bucketing option: prove it in the selected
            # derived date dimension, never by a chart label or planner prose.
            date_field = component.get('date_dimension')
            if (component['type'] != 'time_series' and date_field not in component.get('dimensions', [])) or not _date_bucket(snapshot, date_field, mapping.date_grain):
                return False
        # Unit is a source-defined metric meaning kept in the ledger; recipe 1.0
        # has no display-unit setting. Never infer a currency conversion here.
    return True


def _properties_match(item, properties):
    for p in properties:
        value = item
        for key in p.path.split('.'):
            value = value.get(key) if isinstance(value, dict) else None
        if value != p.value or type(value) is not type(p.value):
            return False
    return True


def _date_bucket(snapshot, field, grain, source=None):
    text = snapshot['definitions'].get('derived-fields.md', '')
    metadata = yaml.safe_load(text.split('---', 2)[1]) if text.startswith('---') else {}
    if not isinstance(metadata, dict) or metadata.get('view') != (snapshot['spec'] or {}).get('datasource', {}).get('table'):
        return False
    derived = next((f for f in metadata.get('fields', []) if f['name'] == field), None)
    grain = {'daily': 'day'}.get(grain.lower(), grain.lower().removesuffix('ly'))
    match = re.fullmatch(r'(?:date|timestamp|datetime)_trunc\s*\(\s*(?:`?t\d+`?\s*\.\s*)?`?([a-z_][a-z0-9_]*)`?\s*,\s*' + re.escape(grain) + r'\s*\)', derived['sql'], re.I) if derived else None
    return bool(match and (source is None or match[1] == source))


def verification(snapshot, ledger, checker):
    """Retain the full code-owned proof, including support (the public issues omit it)."""
    fields, proof = schema(snapshot), {}
    resolved = {}
    for issue, target, slot, _ in _requirement_issues(snapshot, ledger, checker):
        if issue.resolution != "unresolved":
            resolved.setdefault(target.id, []).append((issue, slot))
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
        if r.properties or r.superseded:
            rows.append({'properties': [p.model_dump() for p in r.properties], 'superseded': r.superseded})
        for issue, slot in resolved.get(r.id, []):
            rows.append({"slot": slot, "resolution": issue.resolution,
                         "decision": _choice(r, slot, snapshot, ledger, checker)})
        proof[r.id] = rows or ([{'status': 'context', 'kind': 'audience', 'reason': 'Recognized audience metadata; no capability assertion', 'source_id': r.source.id}]
                              if audience_requirement(r) else [{"status": "unknown", "reason": "No registered capability covers this requirement"}])
    return proof


def get(snapshot, ledger, checker):
    """GET is a read-only projection. Expired IDs cannot authorize later actions."""
    assessment = ledger.assessment.model_copy(deep=True) if ledger.assessment else Assessment()
    changed = assessment.input_digest is not None and assessment.input_digest != input_digest(snapshot, ledger, checker)
    if changed or ledger.invalidated:
        assessment.state, assessment.id = "stale", None
    assessment.prototype_stale = artifact_stale(snapshot, ledger, checker) or bool(ledger.pending_comments)
    assessment.pending_comments = ledger.pending_comments
    return assessment


def artifact_stale(snapshot, ledger, checker):
    """General artifact staleness, separate from the removable pending-batch reason."""
    previous = ledger.assessment.input_digest if ledger.assessment else None
    return ledger.prototype_stale or bool(previous and previous != input_digest(snapshot, ledger, checker) and snapshot["spec"])


def require_current(snapshot, ledger, checker, assessment_id):
    current = get(snapshot, ledger, checker)
    if not current.id or current.id != assessment_id or current.state in {"unchecked", "stale"}:
        raise RunError("feasibility_stale", "Feasibility changed; check it again", 409)
    return current


def decide(snapshot, ledger, checker, body):
    """Validate the entire request before changing a copy; never trust client alternative payloads."""
    current = require_current(snapshot, ledger, checker, body.assessment_id)
    targets = {i.id: (i, r, slot, offers) for i, r, slot, offers in _requirement_issues(snapshot, ledger, checker)}
    visible = {i.id for i in current.issues if i.resolution == "unresolved"}
    selected = []
    for item in body.decisions:
        if item.issue_id not in visible or item.issue_id not in targets:
            raise RunError("invalid_request", "Choose an unresolved requirement issue from this assessment", 422)
        issue, r, slot, offers = targets[item.issue_id]
        alternative = next((o for o in offers if o["id"] == item.alternative_id), None)
        if item.action == "accept_alternative" and alternative is None:
            raise RunError("invalid_request", "Choose an offered alternative from this assessment", 422)
        # Two issues of one requirement cannot simultaneously drop and substitute its intent.
        if any(other[1].id == r.id and other[0].action != item.action and
               "drop" in (other[0].action, item.action) for other in selected):
            raise RunError("invalid_request", "Drop a requirement once, or choose its individual alternatives", 422)
        selected.append((item, r, slot, alternative))
    updated = ledger.model_copy(deep=True)
    updated.prototype_stale |= artifact_stale(snapshot, ledger, checker)
    for item, r, slot, alternative in selected:
        needs = [capabilities.Need.model_validate(n) for n in alternative["needs"]] if alternative else []
        updated.decisions = [d for d in updated.decisions if d.get("requirement_id") != r.id or
                             (item.action != "drop" and d.get("slot") != slot and d.get("action") != "drop")]
        updated.decisions.append({"requirement_id": r.id, "meaning": meaning(r), "slot": slot,
            "action": item.action, "alternative": alternative,
            "prerequisites": _prerequisites(snapshot, needs, r.mappings),
            "evidence": [e for n in needs for e in checker.need(n, schema(snapshot)).evidence],
            "issue_id": item.issue_id, "baseline": _bindings(snapshot, r),
            "applied": _matches(snapshot, r, needs, checker) if alternative else False})
        batch_owned = updated.pending_comments and r.source.batch_id == updated.pending_comments.id
        if alternative and not _matches(snapshot, r, needs, checker) and snapshot["spec"] and not batch_owned:
            updated.prototype_stale = True
    updated.verification = verification(snapshot, updated, checker)
    return updated, evaluate(snapshot, updated, checker)


def abandon_pending(ledger):
    """Remove exactly the pending batch, retaining unrelated intent, choices and stale reasons."""
    updated = ledger.model_copy(deep=True)
    if not updated.pending_comments:
        return updated
    batch_id = updated.pending_comments.id
    removed = {r.id for r in updated.requirements if r.source.batch_id == batch_id or r.source.id.startswith(batch_id + ":")}
    source_ids = {r.source.id for r in updated.requirements if r.id in removed}
    source_ids |= {f"{batch_id}:{i}" for i in range(len(updated.pending_comments.comments))}
    updated.retired_sources = list(dict.fromkeys(updated.retired_sources + sorted(source_ids)))
    updated.requirements = [r for r in updated.requirements if r.id not in removed]
    for r in updated.requirements:
        r.superseded = {slot: rid for slot, rid in r.superseded.items() if rid not in removed}
    updated.decisions = [d for d in updated.decisions if d.get("requirement_id") not in removed]
    updated.verification = {rid: rows for rid, rows in updated.verification.items() if rid not in removed}
    if updated.scope_batch_id == batch_id:
        updated.scope_error, updated.scope_batch_id = None, None
    updated.pending_comments = None
    return updated


def stage_comments(ledger, comments):
    """11.7's revision preflight uses this copy before extraction; save only after assessment."""
    # Use the same validation as POST /comments, including bounds and component ID syntax.
    from dss.api.prototype import Comments
    values = Comments.model_validate({"comments": comments})
    updated = abandon_pending(ledger)
    updated.pending_comments = PendingComments(id=new_id("batch"), comments=[PendingComment(**c.model_dump()) for c in values.comments])
    return updated


def validate_reapply(snapshot, ledger, checker, body):
    current = require_current(snapshot, ledger, checker, body.assessment_id)
    batch = ledger.pending_comments
    if not batch or batch.id != body.batch_id:
        raise RunError("feasibility_stale", "The pending comment batch changed; reload feasibility", 409)
    if current.state != "ready":
        raise RunError("feasibility_blocked", "Resolve pending intent before reapplying comments", 409,
            {"assessment_id": current.id, "issue_ids": [i.id for i in current.issues if i.resolution == "unresolved"]})
    ids = {c["id"] for p in (snapshot["spec"] or {}).get("pages", []) for c in p.get("components", []) + p.get("decorations", [])}
    if any(c.component_id not in ids for c in batch.comments):
        raise RunError("invalid_request", "A pending comment target no longer exists in the spec", 422)
    return batch


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
