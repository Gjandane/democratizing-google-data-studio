"""Deterministic, code-produced recipe JSON Lines."""
import json
from dss.spec.layout import box


def compile_recipe(spec, version):
    project, dataset, table = spec.datasource.table.split(".")
    lines = [dict(recipe_version="1.0", build_id=spec.build_id, version=version,
                  report_name=spec.title, canvas=spec.canvas.model_dump(),
                  datasource=dict(connector="bigQuery", project_id=project, dataset_id=dataset, table_id=table))]
    def op(name, **args):
        lines.append(dict(id=f"s{len(lines):03d}", op=name, **args))
    op("open_report")
    for page in spec.pages:
        if page.index > 1:
            op("add_page", name=page.name)
        op("set_canvas", width=spec.canvas.width, height=page.height)
        op("set_background_image", path=f"background_p{page.index}.png", x=0, y=0, w=spec.canvas.width, h=page.height)
        ordered = sorted(page.components, key=lambda c: (box(spec.canvas, spec.grid, c.grid, height=page.height)["y"], box(spec.canvas, spec.grid, c.grid, height=page.height)["x"]))
        for c in ordered:
            args = dict(component_id=c.id, **box(spec.canvas, spec.grid, c.grid, height=page.height))
            if c.type in ("date_range", "dropdown"):
                op("add_control", control_type=c.type, **args, **({"field": c.field} if c.field else {}))
            elif c.type == "text":
                op("add_text", text=c.text or c.label, **args)
            elif c.type == "image":
                if not c.image_path:
                    raise ValueError("Image component needs image_path")
                op("add_image", path=c.image_path, **args)
            else:
                optional = {key: getattr(c, key) for key in ("date_dimension", "breakdown", "sort") if getattr(c, key) is not None}
                op("add_chart", chart_type=c.type, dimensions=c.dimensions, metrics=[m.model_dump() for m in c.metrics], title=c.label, options=c.options, **optional, **args)
                op("set_style", component_id=c.id, style=dict(colors=spec.theme.palette))
    op("save_report")
    op("get_link")
    if len(lines) > 1000:
        raise ValueError("Recipe exceeds three-digit op id capacity")
    return ''.join(json.dumps(line, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n" for line in lines)
