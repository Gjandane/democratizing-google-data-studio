"""Code-only compile node; publish a complete UTF-8 recipe for the current version."""
from pathlib import Path

from dss.harness.guardrails import RunError
from dss.recipe.compiler import compile_recipe
from dss.spec.models import DashboardSpec


def perform(spec: DashboardSpec, version: int, folder: Path) -> str:
    try:
        text = compile_recipe(spec, version)
        if spec.datasource.synthetic:
            # Rebuild the code-owned background for legacy copies, never trust stale pixels.
            from dss.render import background
            background.write_pages(spec, folder)
    except ValueError:
        raise RunError("invalid_recipe", "Spec could not be compiled into a recipe", 422) from None
    target = folder / "recipe.jsonl"
    # Unchanged bytes are left alone so a no-op refresh never rewrites the file.
    if not target.is_file() or target.read_bytes() != text.encode("utf-8"):
        temporary = folder / "recipe.jsonl.tmp"
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(target)
    return text
