"""Read the shared JSONL contract before any execution can begin."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict

ENGINE_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ENGINE_ROOT.parent / "contracts" / "recipe.schema.json"


class RecipeError(ValueError):
    """A safe, human-readable error that does not echo recipe values."""


class Canvas(BaseModel):
    width: int
    height: int


class Datasource(BaseModel):
    connector: Literal["bigQuery"]
    project_id: str
    dataset_id: str
    table_id: str


class Header(BaseModel):
    recipe_version: Literal["1.0"]
    build_id: str
    version: int
    report_name: str
    canvas: Canvas
    datasource: Datasource


class Operation(BaseModel):
    # The shared schema owns argument validation; retain every validated argument.
    model_config = ConfigDict(extra="allow")
    id: str
    op: Literal[
        "open_report", "set_canvas", "set_background_image", "add_page",
        "rename_page", "go_to_page", "add_chart", "add_control", "add_text", "add_image",
        "set_style", "save_report", "get_link",
    ]


class Recipe(BaseModel):
    path: Path
    header: Header
    ops: list[Operation]

    def asset_path(self, relative_path: str) -> Path:
        """Resolve assets against the recipe directory, never the caller's cwd."""
        return self.path.parent / relative_path


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise RecipeError("cannot read the shared recipe schema") from None


def _validate(value: Any, kind: str, line: int) -> None:
    schema = _schema()
    validator = Draft202012Validator({**schema, "$ref": f"#/$defs/{kind}"})
    error = next(validator.iter_errors(value), None)
    if error is None:
        return
    # oneOf errors otherwise hide the actual bad chart argument among other ops.
    if kind == "op" and isinstance(value, dict) and error.validator == "oneOf":
        branches = schema["$defs"]["op"]["oneOf"]
        for index, branch in enumerate(branches):
            if branch["properties"]["op"]["const"] == value.get("op"):
                error = next(
                    (child for child in error.context if child.schema_path[0] == index),
                    error,
                )
                break
    # Report schema-owned field names only, not user-supplied keys or values.
    location = ".".join(str(p) for p in error.schema_path if isinstance(p, str)
                        and p not in {"properties", "allOf", "oneOf", "$defs"})
    raise RecipeError(f"line {line}: invalid {kind} ({location or error.validator})")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def load_recipe(path: Path) -> Recipe:
    path = path.resolve()
    header = None
    ops: list[Operation] = []
    previous_id = ""
    try:
        with path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    raise RecipeError(f"line {line_number}: blank lines are not allowed")
                try:
                    value = json.loads(line, object_pairs_hook=_unique_object,
                                       parse_constant=_reject_constant)
                except ValueError:
                    raise RecipeError(f"line {line_number}: invalid JSON or duplicate key") from None
                kind = "header" if line_number == 1 else "op"
                _validate(value, kind, line_number)
                if kind == "header":
                    header = Header.model_validate(value)
                    continue
                if value["id"] <= previous_id:
                    raise RecipeError(f"line {line_number}: op IDs must be unique and increasing")
                if value["op"] == "add_control" and value["control_type"] in {
                        "dropdown", "fixed_size_list"}:
                    if not value.get("field"):
                        raise RecipeError(
                            f"line {line_number}: {value['control_type']} requires a field")
                if value["op"] == "add_chart" and value["chart_type"] in {"bar", "area"}:
                    # The schema leaves options open; recipe 1.3 types its stacking as bool.
                    options = value.get("options") or {}
                    for key in ("stacked", "stacked_percent"):
                        if not isinstance(options.get(key, False), bool):
                            raise RecipeError(f"line {line_number}: {key} must be true or false")
                previous_id = value["id"]
                ops.append(Operation.model_validate(value))
    except OSError:
        raise RecipeError("cannot read recipe file") from None
    except UnicodeError:
        raise RecipeError("recipe must be UTF-8") from None
    if header is None:
        raise RecipeError("line 1: missing recipe header")
    return Recipe(path=path, header=header, ops=ops)
