"""Read developer-authored procedural memory; never mutate it."""
from pathlib import Path
import re
from dss.config import BACKEND_DIR


class SkillLoader:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else BACKEND_DIR / "skills"

    def load(self, name: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
            raise ValueError("Invalid skill name")
        path = (self.root / f"{name}.md").resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("Skill path escapes root")
        return path.read_text(encoding="utf-8")
