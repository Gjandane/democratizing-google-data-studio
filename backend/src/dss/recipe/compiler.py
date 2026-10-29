"""Deterministic, code-produced recipe JSON Lines and their engine-free preview."""
import json
import shlex
from functools import lru_cache
from jsonschema import Draft202012Validator, ValidationError
from dss.config import BACKEND_DIR
from dss.spec.layout import layout_box
from dss.spec.models import CONTROL_TYPES, DATE_AXIS_TYPES, Component, DashboardSpec, Theme, image_paths, reference_image


@lru_cache(maxsize=1)
def _recipe_validators():
    schema = json.loads((BACKEND_DIR.parent / 'contracts/recipe.schema.json').read_text(encoding='utf-8'))
    header, operation = (Draft202012Validator({**schema, '$ref': '#/$defs/' + kind}) for kind in ('header', 'op'))
    return header, operation, _op_validators(schema)


def _op_validators(schema):
    """Index disjoint op branches without dropping any wrapper/branch constraints.

    With a present string `op`, every other const branch necessarily fails. Narrow
    oneOf only when every alternative has a unique string const; otherwise retain
    the full union validator. The code-owned schema and validators are immutable.
    """
    operation = schema['$defs']['op']
    branches = operation.get('oneOf', [])
    if any(not isinstance(branch, dict) or not isinstance(branch.get('properties'), dict)
           or not isinstance(branch['properties'].get('op'), dict) for branch in branches):
        return {}
    names = [branch.get('properties', {}).get('op', {}).get('const') for branch in branches]
    if any(not isinstance(name, str) for name in names) or len(set(names)) != len(names):
        return {}
    selected = '__dss_op_case'
    while selected in schema['$defs']:
        selected += '_'
    return {name: Draft202012Validator({
        **schema, '$ref': '#/$defs/' + selected,
        '$defs': {**schema['$defs'], selected: {**operation, 'oneOf': [branch]}},
    }) for name, branch in zip(names, branches)}


def compile_recipe(spec: DashboardSpec, version: int) -> str:
    """Compile the current spec without consulting settings or mutating the spec."""
    from dss.spec.layout import require_synthetic_label
    # A legacy/constructed/mutated model must obey the same color rules as new model output,
    # including theme colors flattened into the background rather than emitted as ops.
    Theme.model_validate(spec.theme.model_dump(warnings=False))
    # The label is a page-1 decoration, so background_p1.png is its one copy: no op draws it
    # again over the background (change 2026-10-23).
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
            if c.colors is not None and c.type in (*CONTROL_TYPES, "text", "image"):
                raise ValueError("Only chart components support colors")
            args = dict(component_id=c.id, **bounds)
            if c.type in CONTROL_TYPES:
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
                # The bucket grain is code's (spec datasource field: a TRUNC derivation's or a base
                # DATE column's profiled bucket start), never a model-written option; one rule for
                # every chart drawn over a date dimension (time series, area).
                options = {key: value for key, value in c.options.items() if key != "date_granularity"}
                if c.type in DATE_AXIS_TYPES and grains.get(c.date_dimension):
                    options["date_granularity"] = grains[c.date_dimension]
                op("add_chart", chart_type=c.type, dimensions=c.dimensions, metrics=[m.model_dump() for m in c.metrics], title=c.label, options=options, **optional, **args)
                # A scorecard has no series swatch: the engine would skip `colors` with a warning.
                if c.type != "scorecard":
                    op("set_style", component_id=c.id, style=dict(colors=c.colors if c.colors is not None else spec.theme.palette))
    op("save_report")
    op("get_link")
    if len(lines) > 1000:
        raise ValueError("Recipe exceeds three-digit op id capacity")
    header_validator, op_validator, op_validators = _recipe_validators()
    try:
        header_validator.validate(lines[0])
        for line in lines[1:]:
            op_validators.get(line['op'], op_validator).validate(line)
    except ValidationError:
        # Never expose raw spec values through a provider/JSON Schema diagnostic.
        raise ValueError('Compiled recipe does not match recipe contract 1.0') from None
    return ''.join(_line(line) for line in lines)


def _line(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"


def share_header(text: str, path: str) -> str:
    """A compiled recipe with the 1.4 `googleCloudStorage` header for one shared CSV
    (`<bucket>/<folder>/data.csv`, no gs://); every op line keeps its bytes."""
    first, rest = text.split("\n", 1)
    header = json.loads(first)
    header["datasource"] = dict(connector="googleCloudStorage", path_type="FILE", path=path)
    try:
        _recipe_validators()[0].validate(header)
    except ValidationError:
        raise ValueError('Shared recipe header does not match recipe contract 1.4') from None
    return _line(header) + rest


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
