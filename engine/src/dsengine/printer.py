"""Human-readable Bash command descriptions, one physical line per op."""

import json
import shlex

from dsengine.recipe import Operation, Recipe


def _quote(value: str) -> str:
    if any(char in value for char in "\n\r\t"):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        escaped = escaped.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        return "$'" + escaped + "'"
    return shlex.quote(value)


def _value(value: object) -> str:
    if isinstance(value, (dict, list, bool)) or value is None:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return str(value)


def op_command(op: Operation) -> str:
    args = ["dsengine", op.op.replace("_", "-")]
    values = op.model_dump()
    for key, value in values.items():
        if key in {"op", "id"}:
            continue
        if op.op == "add_chart" and key == "dimensions":
            for dimension in value:
                args.extend(["--dim", dimension])
        elif op.op == "add_chart" and key == "metrics":
            for metric in value:
                args.extend(["--metric", f"{metric['field']}:{metric['agg']}"])
        else:
            flag = {"component_id": "id", "chart_type": "type", "control_type": "type"}.get(key, key)
            args.extend(["--" + flag.replace("_", "-"), _value(value)])
    return " ".join(_quote(arg) for arg in args)


def recipe_commands(recipe: Recipe) -> list[str]:
    return [op_command(op) for op in recipe.ops]
