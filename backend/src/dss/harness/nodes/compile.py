"""Code-only compile node; publish a complete UTF-8 recipe for the current version."""
from pathlib import Path

from dss.harness.guardrails import RunError
from dss.recipe.compiler import compile_recipe
from dss.spec.models import DashboardSpec


def perform(spec: DashboardSpec, version: int, folder: Path) -> str:
    try:
        text = compile_recipe(spec, version)
    except ValueError:
        raise RunError("invalid_recipe", "Spec could not be compiled into a recipe", 422) from None
    temporary = folder / "recipe.jsonl.tmp"
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(folder / "recipe.jsonl")
    return text
