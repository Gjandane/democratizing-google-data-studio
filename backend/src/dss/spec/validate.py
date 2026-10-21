"""Catalog-backed validation. Errors contain paths and messages, never input values."""
import os
import re
from collections import Counter
from dotenv import dotenv_values
from pydantic import ValidationError
from dss.config import BACKEND_DIR
from dss.memory.semantic import parse_concept
from dss.spec.models import DashboardSpec, image_paths, reference_image
from dss.spec.layout import box, synthetic_errors, decoration_text_errors


def synthetic_participation(db, build_id, folder):
    """Same first-source + declared joins rule as the deterministic view builder."""
    with db.connect() as conn:
        sources = [dict(r) for r in conn.execute('SELECT kind,bq_table FROM sources WHERE build_id=? ORDER BY rowid', (build_id,))]
    path = folder / 'docs/derived-fields.md'
    if not path.is_file():
        return any(s['kind'] == 'synthetic' for s in sources)
    derived = parse_concept(path.name, path.read_text(encoding='utf-8')).metadata
    joined = {j['table'] for j in derived.get('joins', [])}
    selected = sources[:1] + [s for s in sources[1:] if s['bq_table'] in joined]
    return any(s['kind'] == 'synthetic' for s in selected)


def catalog(root=None):
    root = root or BACKEND_DIR / "knowledge/catalog"
    return {c.metadata["component_type"]: c.metadata for path in sorted(root.glob("*.md"))
            if (c := parse_concept(path.name, path.read_text(encoding="utf-8"))).metadata.get("component_type")}


def allowed_types():
    env = {**dotenv_values(BACKEND_DIR.parent / ".env"), **os.environ}
    configured = env.get("DSS_ALLOWED_TYPES")
    return set(catalog()) if configured is None else {s.strip() for s in configured.split(",") if s.strip()}


def high_questions(text):
    blocks = re.finditer(r"(?ms)^-\s+(q\d+):\s*(.*?)(?=^-\s+q\d+:|\Z)", text)
    return [m[1] for m in blocks if re.search(r"\(priority:\s*high\)\s*$", m[2])]


def validate_spec(value, *, allowed=None, high_priority=(), question_refs=(), catalog_root=None):
    """`question_refs`: one entry per ok blueprint row, checked on the code layout output only;
    a revise patch may remove a component, so revise never passes them."""
    try:
        # Revalidate mutable model instances too; assignment/list mutation bypasses Pydantic.
        spec = DashboardSpec.model_validate(value.model_dump(warnings=False) if isinstance(value, DashboardSpec) else value)
    except ValidationError as exc:
        return [{"path": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors(include_input=False)]
    rules = catalog(catalog_root)
    allowed = allowed_types() if allowed is None else set(allowed)
    errors = []
    errors.extend({'path': 'pages.0.decorations', 'message': message} for message in synthetic_errors(spec))
    errors.extend(decoration_text_errors(spec))
    def error(path, message):
        errors.append({"path": path, "message": message})
    fields = {}
    for i, field in enumerate(spec.datasource.fields):
        if field.name in fields:
            error(f"datasource.fields.{i}.name", "Field names must be unique")
        fields[field.name] = field
    ids, refs = set(), Counter()
    for path, image in image_paths(spec):
        if reference_image(image):
            error(path, "Reference screenshots are evidence, never dashboard images or backgrounds")
    for p, page in enumerate(spec.pages):
        _validate_page(spec, p, page, rules, allowed, fields, ids, refs, error)
    for ref in high_priority:
        if ref not in refs:
            error("pages.0.components", f"High-priority question {ref} must be referenced")
    needed = Counter(question_refs)
    for ref in needed:
        if refs[ref] < needed[ref]:
            error("pages", f"Blueprint question {ref} needs {needed[ref]} component(s) with question_ref {ref}")
    return errors


def _validate_page(spec, p, page, rules, allowed, fields, ids, refs, error):
    if page.index != p + 1:
        error(f"pages.{p}.index", "Page indexes must be 1..n in order")
    if p == 0 and page.height != spec.canvas.height:
        error("pages.0.height", "Page height must equal canvas height")
    # Page 1 is the report canvas; later pages carry their own canvas height.
    height = min(page.height, spec.canvas.height) if p == 0 else page.height
    prefix = f"p{p + 1}_"
    boxes = []
    for group in ("decorations", "components"):
        for i, item in enumerate(getattr(page, group)):
            path = f"pages.{p}.{group}.{i}"
            if item.id in ids:
                error(path + ".id", "IDs must be unique")
            ids.add(item.id)
            if not item.id.startswith(prefix):
                error(path + ".id", f"ID must use the page prefix {prefix}")
            try:
                b = box(spec.canvas, spec.grid, item.grid, height=height)
                if group == "components":
                    for other in boxes:
                        if b['x'] < other['x'] + other['w'] and other['x'] < b['x'] + b['w'] and b['y'] < other['y'] + other['h'] and other['y'] < b['y'] + b['h']:
                            error(path + ".grid", "Components must not overlap")
                            break
                    boxes.append(b)
            except ValueError:
                error(path + ".grid", "Grid box is outside the canvas or has no area")
            if group != "components":
                continue
            if item.question_ref:
                refs[item.question_ref] += 1
            rule = rules.get(item.type)
            if rule is None or item.type not in allowed:
                error(path + ".type", "Component type is not allowed by the catalog and DSS_ALLOWED_TYPES")
            if rule is None:
                continue
            for slot in ("dimensions", "metrics"):
                if not rule['min_' + slot] <= len(getattr(item, slot)) <= rule['max_' + slot]:
                    error(path + "." + slot, f"Expected {rule['min_' + slot]}..{rule['max_' + slot]} {slot}")
            for axis in ("w", "h"):
                if getattr(item.grid, axis) < rule['min_' + axis]:
                    error(path + ".grid." + axis, f"Minimum {axis} is {rule['min_' + axis]}")
            if rule['requires_date_dimension'] and not item.date_dimension:
                error(path + ".date_dimension", "A date dimension is required")
            if item.type == "dropdown" and not item.field:
                error(path + ".field", "A dropdown field is required")
            if item.type == "image" and not item.image_path:
                error(path + ".image_path", "An image path is required")
            for slot in ("dimensions", "metrics", "date_dimension", "breakdown", "field"):
                values = getattr(item, slot)
                values = values if isinstance(values, list) else ([] if values is None else [values])
                for j, binding in enumerate(values):
                    name = binding.field if slot == "metrics" else binding
                    fp = path + "." + slot + (f".{j}" if slot in ("dimensions", "metrics") else "")
                    field = fields.get(name)
                    if field is None:
                        error(fp, "Unknown datasource field")
                        continue
                    counting_dimension = (slot == 'metrics' and field.role == 'dimension'
                                          and binding.agg in ('count', 'count_distinct'))
                    if field.role not in rule['slot_roles'][slot] and not counting_dimension:
                        error(fp, "Field role is not allowed in this slot")
                    if slot == "date_dimension" and field.type.upper() not in ("DATE", "DATETIME", "TIMESTAMP"):
                        error(fp, "Date dimension must have a date or timestamp type")
                    if slot == "metrics" and binding.agg in ("sum", "avg") and field.type.upper() not in ("INTEGER", "INT64", "FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC", "DECIMAL", "BIGDECIMAL", "NUMBER"):
                        error(fp, "sum/avg require a numeric field")
                    if slot == "dimensions" and item.type == "geo_map" and field.type.upper() not in ("GEO", "GEOGRAPHY"):
                        error(fp, "Geo map requires a geographic field")
            if item.sort and item.sort.field not in fields:
                error(path + ".sort.field", "Unknown datasource field")
