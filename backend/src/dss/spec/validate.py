"""Catalog-backed validation. Errors contain paths and messages, never input values."""
import os
import re
from dotenv import dotenv_values
from pydantic import ValidationError
from dss.config import BACKEND_DIR
from dss.memory.semantic import parse_concept
from dss.spec.models import DashboardSpec
from dss.spec.layout import box


def catalog(root=None):
    root = root or BACKEND_DIR / "knowledge/catalog"
    return {c.metadata["component_type"]: c.metadata for path in sorted(root.glob("*.md"))
            if (c := parse_concept(path.name, path.read_text(encoding="utf-8"))).metadata.get("component_type")}


def allowed_types():
    env = {**dotenv_values(BACKEND_DIR.parent / ".env"), **os.environ}
    configured = env.get("DSS_ALLOWED_TYPES")
    return set(catalog()) if configured is None else {s.strip() for s in configured.split(",") if s.strip()}


def high_questions(text):
    return re.findall(r"(?m)^-\s+(q\d+):[^\n]*\(priority:\s*high\)", text)


def validate_spec(value, *, allowed=None, high_priority=(), catalog_root=None):
    try:
        spec = value if isinstance(value, DashboardSpec) else DashboardSpec.model_validate(value)
    except ValidationError as exc:
        return [{"path": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors(include_input=False)]
    rules = catalog(catalog_root)
    allowed = allowed_types() if allowed is None else set(allowed)
    errors = []
    def error(path, message):
        errors.append({"path": path, "message": message})
    fields = {}
    for i, field in enumerate(spec.datasource.fields):
        if field.name in fields:
            error(f"datasource.fields.{i}.name", "Field names must be unique")
        fields[field.name] = field
    ids, refs = set(), set()
    page = spec.pages[0]
    if page.index != 1:
        error("pages.0.index", "The single page must have index 1")
    if page.height != spec.canvas.height:
        error("pages.0.height", "Page height must equal canvas height")
    boxes = []
    for group in ("decorations", "components"):
        for i, item in enumerate(getattr(page, group)):
            path = f"pages.0.{group}.{i}"
            if item.id in ids:
                error(path + ".id", "IDs must be unique")
            ids.add(item.id)
            if not item.id.startswith("p1_"):
                error(path + ".id", "ID must use the page prefix p1_")
            try:
                b = box(spec.canvas, spec.grid, item.grid, height=min(page.height, spec.canvas.height))
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
                refs.add(item.question_ref)
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
                    if field.role not in rule['slot_roles'][slot]:
                        error(fp, "Field role is not allowed in this slot")
                    if slot == "date_dimension" and field.type.upper() not in ("DATE", "DATETIME", "TIMESTAMP"):
                        error(fp, "Date dimension must have a date or timestamp type")
                    if slot == "metrics" and binding.agg in ("sum", "avg") and field.type.upper() not in ("INTEGER", "INT64", "FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC", "DECIMAL", "BIGDECIMAL", "NUMBER"):
                        error(fp, "sum/avg require a numeric field")
                    if slot == "dimensions" and item.type == "geo_map" and field.type.upper() not in ("GEO", "GEOGRAPHY"):
                        error(fp, "Geo map requires a geographic field")
            if item.sort and item.sort.get("field") not in fields:
                error(path + ".sort.field", "Unknown datasource field")
    for ref in high_priority:
        if ref not in refs:
            error("pages.0.components", f"High-priority question {ref} must be referenced")
    return errors
