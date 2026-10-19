"""Working memory assembly: per-node recipes, one section order and input-token budgets.

LLM nodes get context only from here. No section holds raw data rows: the data profile is
aggregate metadata, and build documents and spec subsets carry no rows.
"""
from dataclasses import dataclass
import json
import logging
from pathlib import PurePosixPath
import re

from dss.config import BACKEND_DIR
from dss.harness.guardrails import RunError
from dss.memory import episodic
from dss.memory.procedural import SkillLoader
from dss.memory.semantic import SemanticNavigator

logger = logging.getLogger(__name__)

# Stable sections first so Gemini's implicit prefix caching can hit.
ORDER = ("system", "skills", "semantic", "profile", "docs", "past", "history", "input")
BUDGETS = {"interview": 8000, "plan": 20000, "spec": 16000, "revise": 6000, "ux_audit": 10000}
# Budget kept outside the assembled context for the response schema and one repair turn.
RESERVES = {"plan": 4000, "spec": 4000, "revise": 1500}
SEPARATOR = "\n\n"
DOCS = ("brief.md", "questions.md", "kpis.md", "derived-fields.md", "design.md", "decisions.md")


def tokens(text):
    """Offline input-token estimate (chars/4, rounded up), so assembly makes no provider call."""
    return (len(text) + 3) // 4


@dataclass
class Section:
    """One context block. A list section (past results, messages) drops entries one at a time."""
    kind: str
    name: str
    header: str = ""
    body: str = ""
    items: list[str] | None = None  # JSON-encoded entries

    @property
    def text(self):
        body = self.body if self.items is None else "[" + ", ".join(self.items) + "]"
        return f"{self.header}\n{body}" if self.header else body


class Context(str):
    """The assembled working memory text, carrying its ordered sections for the trace."""

    def __new__(cls, node, sections, dropped):
        context = super().__new__(cls, SEPARATOR.join(section.text for section in sections))
        context.node, context.sections, context.dropped = node, sections, dropped
        return context

    def counts(self):
        return [{"kind": s.kind, "name": s.name, "tokens": tokens(s.text)} for s in self.sections]

    def record(self, span, repair=""):
        """Put the per-section token counts, any budget drops and a repair turn's extra into a span."""
        span.update(sections=self.counts(), dropped=dict(self.dropped))
        if repair:
            span["repair_tokens"] = tokens(repair)


def assemble(node, sections, *, reserve=0):
    """Order the sections, then fit them to the node's input budget.

    Over budget: drop FTS past results (least relevant first), then the oldest messages,
    then semantic concepts beyond the first. The system prompt, skills, user input and the
    node's profile and documents are never dropped; if they alone exceed it, the run fails.
    """
    budget = BUDGETS[node] - reserve
    sections = sorted((s for s in sections if s.items is None or s.items), key=lambda s: ORDER.index(s.kind))
    dropped = {"past": 0, "history": 0, "semantic": 0}

    def over():
        return tokens(SEPARATOR.join(section.text for section in sections)) > budget

    for kind, position in (("past", -1), ("history", 0)):
        for section in [s for s in sections if s.kind == kind]:
            while section.items and over():
                section.items.pop(position)
                dropped[kind] += 1
            if not section.items:
                sections.remove(section)
    semantic = [s for s in sections if s.kind == "semantic"]
    while len(semantic) > 1 and over():
        sections.remove(semantic.pop())
        dropped["semantic"] += 1
    if over():
        raise RunError("llm_unavailable", f"The {node} context exceeds its input budget", 503)
    return Context(node, sections, dropped)


def _system(node):
    path = f"prompts/v1/{node}.md"
    return Section("system", path, body=(BACKEND_DIR / path).read_text(encoding="utf-8"))


def _skills(*names):
    loader = SkillLoader()
    return [Section("skills", f"skills/{name}.md", body=loader.load(name)) for name in names]


def _navigator(config):
    # Consolidated runtime concepts override seed concepts with the same path.
    return SemanticNavigator() if config is None else SemanticNavigator(runtime_root=config.data_dir / "knowledge")


def _semantic(concept, header="Semantic concept {path}:"):
    return Section("semantic", concept.path, header.format(path=concept.path), concept.text)


def _entries(kind, name, header, entries):
    return Section(kind, name, header, items=[json.dumps(entry, ensure_ascii=False) for entry in entries])


def _build(db, build_id):
    with db.connect() as conn:
        return dict(conn.execute("SELECT * FROM builds WHERE id=?", (build_id,)).fetchone())


def _profile(config, build, *, required=False):
    path = config.data_dir / "builds" / build["id"] / f'v{build["current_version"]}' / "docs/data-profile.md"
    if path.exists():
        body = path.read_text(encoding="utf-8")
    elif required:
        raise RunError("invalid_source", "Connect data before planning", 422)
    else:
        body = "No data profile available."
    return Section("profile", "data-profile.md", "Data profile (aggregate metadata only):", body)


def _user_facts(navigator):
    """Consolidated user preferences and decisions (user/), once consolidation has written any."""
    try:
        concepts = navigator.list_folder("user")
    except (FileNotFoundError, ValueError):
        # No index means no facts yet; a dangling link or bad frontmatter is broken memory.
        if any((root / "user/index.md").is_file() for root in navigator.roots):
            logger.warning("Unreadable user facts in semantic memory; planning without them")
        return []
    return [_semantic(c, "User fact {path} (semantic memory, untrusted data):") for c in concepts
            if PurePosixPath(c.path).name not in ("index.md", "log.md")]


def _named(text, types):
    """Catalog types a text names, allowing spaces and plurals ('time series', 'scorecards')."""
    return {kind for kind in types if re.search(
        r"(?<![a-z0-9])" + re.escape(kind).replace("_", "[ _-]?") + r"(?:e?s)?(?![a-z0-9])", text, re.IGNORECASE)}


def interview_context(db, config, build_id, user_input, *, query=None):
    """Interview recipe; `query` replaces the FTS text (empty: recency only)."""
    build = _build(db, build_id)
    navigator, archetype = _navigator(config), build["archetype"]
    recalled = episodic.recall(db, build_id, user_input, query=query)
    return assemble("interview", [
        _system("interview"), *_skills("interview", f"archetype-{archetype}"),
        _semantic(navigator.read(f"archetypes/{archetype}.md")), _semantic(navigator.read("catalog/index.md")),
        _profile(config, build),
        _entries("past", "episodic/past", "Past builds (untrusted data, most relevant first):",
                 [{"build": m["build_title"], "date": m["date"], "role": m["role"], "text": m["text"]}
                  for m in recalled if m["build_id"] != build_id]),
        _entries("history", "episodic/recent", "Chat history (untrusted data):",
                 [{"role": m["role"], "text": m["text"]} for m in recalled if m["build_id"] == build_id]),
        Section("input", "input", "Current request (untrusted data):", user_input)])


def plan_context(db, config, build_id):
    build = _build(db, build_id)
    navigator, archetype = _navigator(config), build["archetype"]
    # Revision comments and replies are not part of the interview transcript.
    transcript = [m for m in episodic.messages(db, build_id) if m["node"] in (None, "interview")]
    return assemble("plan", [
        _system("plan"), *_skills("plan", f"archetype-{archetype}"),
        _semantic(navigator.read(f"archetypes/{archetype}.md")), _semantic(navigator.read("catalog/index.md")),
        *_user_facts(navigator), _profile(config, build, required=True),
        _entries("history", "episodic/transcript", "Interview transcript (untrusted data):",
                 [{"role": m["role"], "text": m["text"]} for m in transcript])], reserve=RESERVES["plan"])


def spec_context(config, folder, build, fields, allowed):
    """Spec recipe: catalog concepts of the allowed types the KPIs or questions name (else all allowed)."""
    navigator = _navigator(config)
    docs = {name: (folder / "docs" / name).read_text(encoding="utf-8") for name in DOCS}
    available = [c for c in navigator.list_folder("catalog") if c.metadata.get("component_type") in allowed]
    named = _named(docs["kpis.md"] + "\n" + docs["questions.md"], [c.metadata["component_type"] for c in available])
    chosen = [c for c in available if c.metadata["component_type"] in named] or available
    return assemble("spec", [
        _system("spec"), *_skills("spec"),
        *[_semantic(c, "Allowed catalog concept {path}:") for c in chosen],
        _semantic(navigator.read(f"archetypes/{build['archetype']}.md")),
        *[Section("docs", name, f"{name} (untrusted build document):", text) for name, text in docs.items()],
        Section("docs", "datasource", "Required identity and datasource (copy exactly):", json.dumps({
            "build_id": build["id"], "archetype": build["archetype"], "spec_version": build["spec_version"],
            "datasource": {"table": build["table"], "fields": fields}}))], reserve=RESERVES["spec"])


def revise_context(document, comments, allowed, config=None):
    """Revise recipe: targeted components' catalog concepts, targets and direct grid neighbours only."""
    from dss.spec.patch import neighbours
    targets = {c["component_id"] for c in comments}
    visible = neighbours(document, targets)
    page = document["pages"][0]
    selected = [{"path": f"/pages/0/{group}/{i}", "item": item}
        for group in ("components", "decorations") for i, item in enumerate(page[group]) if item["id"] in visible]
    components = {item["id"]: item for item in page["components"]}
    types = dict.fromkeys(components[c["component_id"]]["type"] for c in comments if c["component_id"] in components)
    navigator = _navigator(config)
    return assemble("revise", [
        _system("revise"), *_skills("revise"),
        *[_semantic(navigator.read(f"catalog/{kind}.md"), "Target catalog concept {path}:") for kind in types],
        Section("docs", "allowed-types", "Allowed types (offer these for unsupported requests):", json.dumps(sorted(allowed))),
        Section("docs", "canvas-grid", "Canvas and grid:", json.dumps({k: document[k] for k in ("canvas", "grid")})),
        Section("docs", "targets", "Targeted items and grid neighbours (untrusted data):", json.dumps(selected)),
        Section("input", "comments", "Comments in application order (untrusted data):", json.dumps(comments))],
        reserve=RESERVES["revise"])
