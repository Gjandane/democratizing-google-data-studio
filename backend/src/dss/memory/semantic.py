"""Read-only OKF navigation across seed and consolidated semantic memory.

Paths are relative to either root. Runtime concepts override seed concepts with the
same path. Reads and searches refresh from disk so consolidation is visible.
"""
from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import unquote
import yaml
from dss.config import BACKEND_DIR, Config


@dataclass(frozen=True)
class Concept:
    path: str
    metadata: dict
    text: str


def parse_concept(path: str, text: str) -> Concept:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"{path}: missing frontmatter")
    try:
        end = lines.index("---", 1)
        metadata = yaml.safe_load("\n".join(lines[1:end]))
    except (ValueError, yaml.YAMLError) as exc:
        raise ValueError(f"{path}: invalid frontmatter") from exc
    if not isinstance(metadata, dict) or not isinstance(metadata.get("type"), str) or not metadata["type"].strip():
        raise ValueError(f"{path}: non-empty type required")
    tags = metadata.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError(f"{path}: tags must be strings")
    return Concept(path, metadata, text)


class SemanticNavigator:
    def __init__(self, seed_root: Path | None = None, runtime_root: Path | None = None):
        self.roots = (Path(seed_root) if seed_root is not None else BACKEND_DIR / "knowledge",
                      Path(runtime_root) if runtime_root is not None else Config.from_env().data_dir / "knowledge")

    def _path(self, root: Path, relative: str) -> Path:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts or "\\" in relative or ":" in relative:
            raise ValueError("Knowledge path must be relative and confined to its root")
        resolved = (root / candidate).resolve()
        if not resolved.is_relative_to(root.resolve()):
            raise ValueError("Knowledge path escapes root")
        return resolved

    def read(self, path: str) -> Concept:
        if not path.endswith(".md"):
            raise ValueError("Knowledge concepts must be Markdown")
        for root in reversed(self.roots):
            file = self._path(root, path)
            if file.is_file():
                return parse_concept(path, file.read_text(encoding="utf-8"))
        raise FileNotFoundError(path)

    def list_folder(self, folder: str = "") -> list[Concept]:
        """Follow local Markdown links in the folder's index, in document order."""
        base = Path(folder)
        index = self.read((base / "index.md").as_posix())
        result = []
        seen = set()
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", index.text):
            target = unquote(target.split("#", 1)[0])
            if not target:
                continue
            # External references are citations, not knowledge navigation.
            if ":" in target or target.startswith("//"):
                continue
            relative = (base / target).as_posix()
            if relative.endswith("/") or not Path(relative).suffix:
                relative = relative.rstrip("/") + "/index.md"
            if relative not in seen:
                result.append(self.read(relative))
                seen.add(relative)
        return result

    def search(self, *, type: str | None = None, tags: list[str] | None = None,
               text: str | None = None) -> list[Concept]:
        paths = set()
        for root in self.roots:
            if root.exists():
                paths.update(file.relative_to(root).as_posix() for file in root.rglob("*.md"))
        results = []
        for path in sorted(paths):
            concept = self.read(path)
            if type is not None and concept.metadata["type"] != type:
                continue
            if tags and not set(tags).issubset(concept.metadata.get("tags", [])):
                continue
            if text and text.casefold() not in concept.text.casefold():
                continue
            results.append(concept)
        return results
