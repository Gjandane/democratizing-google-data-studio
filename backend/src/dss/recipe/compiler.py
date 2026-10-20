"""Deterministic, code-produced recipe JSON Lines and their engine-free preview."""
import json
import shlex
from dss.spec.layout import box
from dss.spec.models import DashboardSpec, image_paths, reference_image


def compile_recipe(spec: DashboardSpec, version: int) -> str:
    """Compile the current spec without consulting settings or mutating the spec."""
    from dss.spec.layout import require_synthetic_label
    from dss.spec.models import SYNTHETIC_LABEL_ID, SYNTHETIC_LABEL
    require_synthetic_label(spec)
    # Logos are flattened into background_p<n>.png, so they are checked like image components.
    if any(reference_image(path) for _, path in image_paths(spec)):
        raise ValueError('Reference screenshots cannot be recipe images or backgrounds')
    project, dataset, table = spec.datasource.table.split(".")
    lines = [dict(recipe_version="1.0", build_id=spec.build_id, version=version,
                  report_name=spec.title, canvas=spec.canvas.model_dump(),
                  datasource=dict(connector="bigQuery", project_id=project, dataset_id=dataset, table_id=table))]
    def op(name, /, **args):
        lines.append(dict(id=f"s{len(lines):03d}", op=name, **args))
    op("open_report")
    for page_number, page in enumerate(spec.pages):
        if page_number:
            op("add_page", name=page.name)
        op("set_canvas", width=spec.canvas.width, height=page.height)
        op("set_background_image", path=f"background_p{page.index}.png", x=0, y=0, w=spec.canvas.width, h=page.height)
        placed = [(c, box(spec.canvas, spec.grid, c.grid, height=page.height)) for c in page.components]
        for c, bounds in sorted(placed, key=lambda item: (item[1]["y"], item[1]["x"])):
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
                op("add_chart", chart_type=c.type, dimensions=c.dimensions, metrics=[m.model_dump() for m in c.metrics], title=c.label, options=c.options, **optional, **args)
                op("set_style", component_id=c.id, style=dict(colors=spec.theme.palette))
        if spec.datasource.synthetic:
            label = next(d for d in page.decorations if d.id == SYNTHETIC_LABEL_ID)
            bounds = box(spec.canvas, spec.grid, label.grid, height=page.height)
            # Native text also makes provenance visible in recipe preview and editable reports.
            op('add_text', component_id=label.id, text=SYNTHETIC_LABEL, x=bounds['x']+16,
               y=bounds['y']+16, w=bounds['w']-32, h=bounds['h']-32,
               font_size=16, color='#0F172A')
    op("save_report")
    op("get_link")
    if len(lines) > 1000:
        raise ValueError("Recipe exceeds three-digit op id capacity")
    return ''.join(json.dumps(line, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n" for line in lines)


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
