"""Load UI locators from the Data Studio knowledge bundle."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from dsengine.recipe import ENGINE_ROOT


class SelectorError(ValueError):
    """The selector knowledge bundle is malformed or ambiguous."""


@lru_cache(maxsize=4)
def _load(directory: str) -> dict[str, str]:
    root = Path(directory)
    if not root.is_dir():
        raise SelectorError("selector knowledge directory is missing")
    combined: dict[str, str] = {}
    for source in sorted(root.glob("*.md")):
        try:
            content = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise SelectorError("cannot read selector knowledge file") from None
        if not content.startswith("---"):
            continue
        parts = content.split("---", 2)
        if len(parts) != 3:
            raise SelectorError("selector knowledge frontmatter is malformed")
        try:
            frontmatter: Any = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            raise SelectorError("selector knowledge frontmatter is malformed") from None
        if not isinstance(frontmatter, dict) or frontmatter.get("type") != "UI Selector Set":
            continue
        declared = frontmatter.get("selectors", {})
        if not isinstance(declared, dict):
            raise SelectorError("selector map must be an object")
        for name, locator in declared.items():
            if not isinstance(name, str) or not name or not isinstance(locator, str) or not locator:
                raise SelectorError("selector names and locators must be non-empty strings")
            if name in combined and combined[name] != locator:
                raise SelectorError("selector key is defined more than once")
            combined[name] = locator
    if not combined:
        raise SelectorError("selector knowledge bundle contains no locators")
    return combined


def load_selectors(directory: Path | None = None) -> dict[str, str]:
    """Return the merged selectors from the local UI knowledge bundle."""
    root = directory or ENGINE_ROOT / "knowledge" / "datastudio-ui"
    return dict(_load(str(root.resolve())))
