"""Deterministic, code-produced recipe JSON Lines and their engine-free preview."""
import json
import shlex
from functools import lru_cache
from jsonschema import Draft202012Validator, ValidationError
from dss.config import BACKEND_DIR
from dss.spec.layout import layout_box
from dss.spec.models import Component, DashboardSpec, Theme, image_paths, reference_image


@lru_cache(maxsize=1)
def _recipe_validators():
    schema = json.loads((BACKEND_DIR.parent / 'contracts/recipe.schema.json').read_text(encoding='utf-8'))
    return tuple(Draft202012Validator({**schema, '$ref': '#/$defs/' + kind}) for kind in ('header', 'op'))


def compile_recipe(spec: DashboardSpec, version: int) -> str:
    """Compile the current spec without consulting settings or mutating the spec."""
    from dss.spec.layout import require_synthetic_label
    from dss.spec.models import SYNTHETIC_LABEL_ID, SYNTHETIC_LABEL
    # A legacy/constructed/mutated model must obey the same color rules as new model output,
    # including theme colors flattened into the background rather than emitted as ops.
    Theme.model_validate(spec.theme.model_dump(warnings=False))
    require_synthetic_label(spec)
    # Logos are flattened into background_p<n>.png, so they are checked like image components.
    if any(reference_image(path) for _, path in image_paths(spec)):
        raise ValueError('Reference screenshots cannot be recipe images or backgrounds')
    project, dataset, table = spec.datasource.table.split(".")
    grains = {f.name: f.date_granularity for f in spec.datasource.fields if f.date_granularity}
    lines = [dict(recipe_version="1.0", build_id=spec.build_id, version=version,
                  report_name=spec.title, canvas=spec.canvas.model_dump(),
                  datasource=dict(connector="bigQuery", project_id=project, dataset_id=dataset, table_id=table))]
    def op(name, /, **args):
        lines.append(dict(id=f"s{len(lines):03d}", op=name, **args))
    op("open_report")
    # open_report leaves page 1 "Untitled Page" (recipe 1.1).
    op("rename_page", name=spec.pages[0].name)
    for page_number, page in enumerate(spec.pages):
        if page_number:
            op("add_page", name=page.name)
        op("set_canvas", width=spec.canvas.width, height=page.height)
        op("set_background_image", path=f"background_p{page.index}.png", x=0, y=0, w=spec.canvas.width, h=page.height)
        placed = [(c, layout_box(spec, page, c)) for c in page.components]
        for c, bounds in sorted(placed, key=lambda item: (item[1]["y"], item[1]["x"])):
            Component.model_validate(c.model_dump(warnings=False))
            if c.colors is not None and c.type in ("date_range", "dropdown", "text", "image"):
                raise ValueError("Only chart components support colors")
            args = dict(component_id=c.id, **bounds)
            if c.type in ("date_range", "dropdown"):
                op("add_control", control_type=c.type, **args, **({"field": c.field} if c.field else {}))
            elif c.type == "text":
                op("add_text", text=c.text or c.label, **args)
            elif c.type == "image":
                if not c.image_path:
                    raise ValueError("Image component needs image_path")
                op("add_image", path=c.image_path, **args)
            else:
                optional = {key: getattr(c, key) for key in ("date_dimension", "breakdown") if getattr(c, key) is not None}
                if c.sort is not None:
                    optional["sort"] = c.sort.model_dump()
                # The bucket grain is code's (spec datasource field), never a model-written option.
                options = {key: value for key, value in c.options.items() if key != "date_granularity"}
                if c.type == "time_series" and grains.get(c.date_dimension):
                    options["date_granularity"] = grains[c.date_dimension]
                op("add_chart", chart_type=c.type, dimensions=c.dimensions, metrics=[m.model_dump() for m in c.metrics], title=c.label, options=options, **optional, **args)
                # A scorecard has no series swatch: the engine would skip `colors` with a warning.
                if c.type != "scorecard":
                    op("set_style", component_id=c.id, style=dict(colors=c.colors if c.colors is not None else spec.theme.palette))
        # The reserved label lives on page 1 only (require_synthetic_label checks it).
        label = next((d for d in page.decorations if d.id == SYNTHETIC_LABEL_ID), None)
        if spec.datasource.synthetic and label is not None:
            bounds = layout_box(spec, page, label)
            # Native text also makes provenance visible in recipe preview and editable reports.
            op('add_text', component_id=label.id, text=SYNTHETIC_LABEL, x=bounds['x']+16,
               y=bounds['y']+16, w=bounds['w']-32, h=bounds['h']-32,
               font_size=16, color='#0F172A')
    op("save_report")
    op("get_link")
    if len(lines) > 1000:
        raise ValueError("Recipe exceeds three-digit op id capacity")
    header_validator, op_validator = _recipe_validators()
    try:
        header_validator.validate(lines[0])
        for line in lines[1:]:
            op_validator.validate(line)
    except ValidationError:
        # Never expose raw spec values through a provider/JSON Schema diagnostic.
        raise ValueError('Compiled recipe does not match recipe contract 1.0') from None
    return ''.join(json.dumps(line, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                              allow_nan=False) + "\n" for line in lines)


# `dsengine print` convention (contracts/api.md), recorded in tests/data/recipe_preview.json:
# arguments in sorted key order, these keys renamed, other underscores as hyphens.
FLAGS = {"component_id": "id", "chart_type": "type", "control_type": "type", "dimensions": "dim", "metrics": "metric"}


def _quote(text: str) -> str:
    if any(ch in text for ch in "\n\r\t"):
        for raw, escaped in (("\\", r"\\"), ("'", r"\'"), ("\n", r"\n"), ("\r", r"\r"), ("\t", r"\t")):
            text = text.replace(raw, escaped)
        return f"$'{text}'"
    return shlex.quote(text)


def _words(value) -> list[str]:
    if isinstance(value, str):
        return [_quote(value)]
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return [json.dumps(value)]
    if isinstance(value, dict):
        return [_quote(json.dumps(value, sort_keys=True, separators=(",", ":")))]
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return [_quote(item) for item in value]
        if all(isinstance(item, dict) and item.keys() == {"field", "agg"} for item in value):
            return [_quote(f"{item['field']}:{item['agg']}") for item in value]
    raise ValueError("Recipe argument has no print form")


def print_line(op: dict) -> str:
    """One op as the CLI line `dsengine print` shows, without launching the engine."""
    parts = ["dsengine", op["op"].replace("_", "-")]
    for key in sorted(set(op) - {"id", "op"}):
        flag = "--" + FLAGS.get(key, key.replace("_", "-"))
        for word in _words(op[key]):
            parts += [flag, word]
    return " ".join(parts)


def preview(text: str) -> list[dict]:
    """Preview ops of a compiled recipe; split on LF only (U+2028 may appear inside a line)."""
    return [{"op_id": op["id"], "line": print_line(op)} for op in map(json.loads, text.split("\n")[1:-1])]
