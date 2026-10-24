"""Evidence-backed capability registry and deterministic checks.

Code owns every classification: no model output and no runtime web search can grant support.
Checks are pure and in-memory; only `load_registry` and `allowed_types` touch the disk.
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from dss.config import BACKEND_DIR
from dss.spec.models import CHART_TYPES, CONTROL_TYPES, Component, Metric, Sort

REGISTRY_PATH = BACKEND_DIR / "knowledge/datastudio/capabilities.json"
# Native product evidence: official documentation only. Documentation silence means unknown.
OFFICIAL = ("https://docs.cloud.google.com/data-studio/", "https://developers.google.com/data-studio/")
# App support evidence: the recipe contract, its schema or a contract fixture that exercises it.
CONTRACT = ("../contracts/recipe.md", "../contracts/recipe.schema.json", "../contracts/fixtures/")
# App exclusions may also cite this backend's own code, knowledge or tests.
LOCAL = ("src/dss/", "knowledge/", "tests/")
SCORECARD_COLORS = "Scorecards take no colors (no series swatch in Data Studio): use another chart type to set colors"

Status = Literal["supported", "unsupported", "unknown"]
Outcome = Literal["supported", "unsupported_product", "unsupported_app", "needs_data", "needs_clarification", "unknown"]
Value = bool | int | str
NO_VALUE = object()  # distinct from None: an explicit null option value is still checked


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Layer(Model):
    """One scope's evidence. Product limits and engine/app limits live in separate layers."""
    status: Status
    evidence: list[str] = Field(default_factory=list)
    verified: date | None = None
    limits: dict[str, Value] = Field(default_factory=dict)
    note: str = ""


class Prerequisite(Model):
    """A data field the capability needs; empty types accept any field."""
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    types: list[str] = Field(default_factory=list)


class Capability(Model):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")
    kind: Literal["chart_type", "control_type", "element", "argument", "option", "style", "layout",
                  "geo_granularity", "interaction", "animation", "refresh", "extension"]
    label: str = Field(min_length=1)
    recipe: list[str] = Field(default_factory=list)
    component_type: str | None = None
    requires: list[str] = Field(default_factory=list)
    values: list[Value] | None = None
    value_type: Literal["bool", "int", "string", "field_list", "color", "color_list"] | None = None
    native_product: Layer
    app: Layer
    data: list[Prerequisite] = Field(default_factory=list)


def evidence_kind(item: str) -> str | None:
    """official | contract | local, or None for anything else (a model's assertion is not evidence)."""
    if any(ch.isspace() for ch in item):
        return None
    if item.startswith(OFFICIAL) and item not in OFFICIAL:
        return "official"
    path = item.split("#", 1)[0]
    parts = path.split("/")
    if "\\" in path or any(p in ("", ".") for p in parts) or parts.count("..") != (parts[0] == ".."):
        return None
    if path in CONTRACT[:2] or path.startswith(CONTRACT[2]):
        return "contract"
    if path.startswith(LOCAL):
        return "local"
    return None


class Registry(Model):
    registry_version: str = Field(pattern=r"^\d+\.\d+$")
    verified: date
    capabilities: list[Capability] = Field(min_length=1)
    _by_id: dict = PrivateAttr(default_factory=dict)
    _by_locator: dict = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _check(self):
        by_id, by_locator = {}, {}
        for cap in self.capabilities:
            if cap.id in by_id:
                raise ValueError(f"duplicate capability id {cap.id}")
            by_id[cap.id] = cap
            for locator in cap.recipe:
                if locator in by_locator:
                    raise ValueError(f"recipe locator {locator} is classified twice")
                by_locator[locator] = cap
            for scope, layer, kinds in (("native_product", cap.native_product, {"official"}),
                                        ("app", cap.app, {"contract", "local"})):
                for item in layer.evidence:
                    if evidence_kind(item) not in kinds:
                        raise ValueError(f"{cap.id}: unknown {scope} evidence {item!r}")
                if layer.status != "unknown" and not (layer.evidence and layer.verified):
                    raise ValueError(f"{cap.id}: {scope} {layer.status} needs dated evidence")
            if cap.app.status == "supported" and not any(evidence_kind(e) == "contract" for e in cap.app.evidence):
                raise ValueError(f"{cap.id}: app support must cite the recipe contract or a contract fixture")
            if cap.native_product.status == "unsupported" and cap.app.status == "supported":
                raise ValueError(f"{cap.id}: contradictory product and app evidence")
            if cap.values is not None and (not cap.values or len(set(map(repr, cap.values))) != len(cap.values)):
                raise ValueError(f"{cap.id}: values must be distinct and non-empty")
            if len({p.name for p in cap.data}) != len(cap.data):
                raise ValueError(f"{cap.id}: duplicate prerequisite names")
        for cap in self.capabilities:
            for dep in cap.requires:
                if dep not in by_id or dep == cap.id:
                    raise ValueError(f"{cap.id}: unknown requirement {dep}")
        state = {}
        def visit(cid):
            if state.get(cid) == 1:
                raise ValueError(f"requirement cycle through {cid}")
            if cid not in state:
                state[cid] = 1
                for dep in by_id[cid].requires:
                    visit(dep)
                state[cid] = 2
        for cid in by_id:
            visit(cid)
        self._by_id, self._by_locator = by_id, by_locator
        return self

    def get(self, cap_id: str) -> Capability | None:
        return self._by_id.get(cap_id)

    def at(self, locator: str) -> Capability | None:
        return self._by_locator.get(locator)

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()


def load_registry(path: Path | None = None) -> Registry:
    return Registry.model_validate_json(Path(path or REGISTRY_PATH).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Verdict:
    status: Outcome
    reason: str
    capability: str | None = None
    evidence: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()  # fields that could satisfy an unbound prerequisite

    @property
    def ok(self) -> bool:
        return self.status == "supported"


class Need(Model):
    """What a requirement asks of the registry: a capability, an optional value and field bindings."""
    capability: str
    value: Value | list[str] | None = None
    fields: dict[str, str] = Field(default_factory=dict)


class Requirement(Model):
    id: str = Field(min_length=1)
    needs: list[Need] = Field(default_factory=list)


@dataclass(frozen=True)
class Result:
    ready: bool
    issues: tuple[tuple[str, Verdict], ...]  # (requirement or component id, non-supported verdict)


def _typed(value, value_type) -> bool:
    if value_type == "bool":
        return isinstance(value, bool)
    if value_type == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type == "string":
        return isinstance(value, str) and bool(value)
    if value_type == "color":
        return isinstance(value, str) and len(value) == 7 and value[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in value[1:])
    if value_type == "field_list":
        return isinstance(value, list) and all(isinstance(v, str) and v for v in value)
    if value_type == "color_list":
        return isinstance(value, list) and all(_typed(v, "color") for v in value)
    return False


def _undeclared(c: dict) -> str | None:
    """The first key a raw component dict carries outside the typed spec shapes (top level, metric, sort)."""
    for key in c:
        if key not in Component.model_fields:
            return key
    if not isinstance(c.get("options") or {}, dict):
        return "options"
    for metric in c.get("metrics") or ():
        if not isinstance(metric, dict) or set(metric) - set(Metric.model_fields):
            return "metrics"
    sort = c.get("sort")
    if sort is not None and (not isinstance(sort, dict) or set(sort) - set(Sort.model_fields)):
        return "sort"
    return None


class Checker:
    """An effective registry: the curated records narrowed (never widened) by DSS_ALLOWED_TYPES."""

    def __init__(self, registry: Registry, allowed=None):
        if allowed is None:
            from dss.spec.validate import allowed_types
            allowed = allowed_types()
        self.registry = registry
        self.allowed = frozenset(allowed)
        self._base: dict[str, Verdict] = {}
        for cap in registry.capabilities:
            self._resolve(cap.id)

    def digest(self) -> str:
        """Changes with registry content or the allowlist; both invalidate an assessment."""
        return hashlib.sha256(f"{self.registry.digest()}|{','.join(sorted(self.allowed))}".encode()).hexdigest()

    def _resolve(self, cid: str) -> Verdict:
        if cid in self._base:
            return self._base[cid]
        cap = self.registry.get(cid)
        product, app = cap.native_product, cap.app
        if product.status == "unsupported":
            verdict = Verdict("unsupported_product", product.note or f"{cap.label} is not available in Data Studio", cid, tuple(product.evidence))
        elif cap.component_type is not None and cap.component_type not in self.allowed:
            verdict = Verdict("unsupported_app", f"{cap.label} is disabled by DSS_ALLOWED_TYPES", cid)
        elif app.status != "supported":
            verdict = Verdict("unsupported_app", app.note or f"{cap.label} is not implemented by this app's recipe and engine", cid, tuple(app.evidence))
        elif product.status != "supported":
            verdict = Verdict("unknown", f"Data Studio documentation does not establish {cap.label}", cid)
        else:
            verdict = Verdict("supported", "", cid, tuple(product.evidence + app.evidence))
            for dep in cap.requires:
                inner = self._resolve(dep)
                if not inner.ok:
                    verdict = Verdict(inner.status, f"{cap.label} needs {inner.reason[:1].lower()}{inner.reason[1:]}", cid, inner.evidence)
                    break
        self._base[cid] = verdict
        return verdict

    def capability(self, cid: str, value=NO_VALUE) -> Verdict:
        cap = self.registry.get(cid)
        if cap is None:
            return Verdict("unknown", "The request matches no capability in the registry", cid)
        verdict = self._resolve(cid)
        if not verdict.ok or value is NO_VALUE:
            return verdict
        if cap.values is not None:
            if not any(type(value) is type(v) and value == v for v in cap.values):
                return Verdict("unsupported_app", f"{cap.label} supports only {', '.join(map(str, cap.values))}", cid, tuple(cap.app.evidence))
        elif cap.value_type is None:
            return Verdict("unsupported_app", f"{cap.label} takes no value", cid, tuple(cap.app.evidence))
        elif not _typed(value, cap.value_type):
            return Verdict("unsupported_app", f"{cap.label} needs a {cap.value_type.replace('_', ' ')} value", cid, tuple(cap.app.evidence))
        return verdict

    def need(self, need: Need, schema: dict[str, str]) -> Verdict:
        """Classify one need against the effective registry and the connected schema {field: type}."""
        verdict = self.capability(need.capability, NO_VALUE if need.value is None else need.value)
        if not verdict.ok:
            return verdict
        cap = self.registry.get(need.capability)
        prerequisites = self._prerequisites(cap.id)
        names = {p.name for p in prerequisites}
        extra = sorted(set(need.fields) - names)
        if extra:
            return Verdict("needs_clarification", f"{cap.label} has no data input named {extra[0]}", cap.id)
        for pre in prerequisites:
            accepts = {t.upper() for t in pre.types}
            bound = need.fields.get(pre.name)
            if bound is not None:
                if bound not in schema:
                    return Verdict("needs_data", f"Field {bound} for {pre.name} is not in the connected data", cap.id)
                if accepts and schema[bound].upper() not in accepts:
                    return Verdict("needs_data", f"Field {bound} cannot supply {pre.name}: it needs {'/'.join(pre.types)}", cap.id)
                continue
            candidates = tuple(sorted(f for f, t in schema.items() if not accepts or t.upper() in accepts))
            if not candidates:
                kind = "/".join(pre.types) if pre.types else "any"
                return Verdict("needs_data", f"{cap.label} needs a {pre.name} field ({kind}) that the connected data lacks", cap.id)
            return Verdict("needs_clarification", f"Choose which field supplies {pre.name} for {cap.label}", cap.id, candidates=candidates)
        return verdict

    def _prerequisites(self, cid: str) -> list[Prerequisite]:
        """A capability's own data prerequisites plus those of everything it requires (first name wins)."""
        found, seen, stack = [], set(), [cid]
        while stack:
            cap = self.registry.get(stack.pop(0))
            found += [p for p in cap.data if p.name not in {f.name for f in found}]
            stack += [d for d in cap.requires if d not in seen]
            seen.update(cap.requires)
        return found

    def requirement(self, requirement: Requirement, schema: dict[str, str]) -> list[Verdict]:
        """Non-supported verdicts; a requirement no capability covers stays unknown."""
        if not requirement.needs:
            return [Verdict("unknown", "No registered capability covers this requirement")]
        return [v for v in (self.need(n, schema) for n in requirement.needs) if not v.ok]

    def component(self, component) -> list[Verdict]:
        """Non-supported verdicts for one spec component: its type, every option key/value and arguments.

        An option the registry does not declare for that type (e.g. `animate` on a geo_map) rejects;
        it is never stripped.
        """
        c = component if isinstance(component, dict) else component.model_dump()
        shape = _undeclared(c)
        if shape:
            return [Verdict("unsupported_app", f"Component key {shape} is not declared by the spec")]
        ctype = c.get("type")
        if ctype in CHART_TYPES:
            locator = f"add_chart.chart_type={ctype}"
        elif ctype in CONTROL_TYPES:
            locator = f"add_control.control_type={ctype}"
        else:
            locator = {"text": "add_text", "image": "add_image"}.get(ctype)
        cap = self.registry.at(locator) if locator else None
        if cap is None:
            return [Verdict("unsupported_app", f"Component type {ctype} has no registry record")]
        found = [self._resolve(cap.id)]
        for key, value in (c.get("options") or {}).items():
            option = self.registry.at(f"add_chart.options.{ctype}.{key}") if ctype in CHART_TYPES else None
            if option is None:
                found.append(Verdict("unsupported_app", f"Option {key} is not declared for {ctype}"))
            else:
                found.append(self.capability(option.id, value))
        def arg(locator, value=NO_VALUE):
            argument = self.registry.at(locator)
            found.append(self.capability(argument.id, value) if argument else
                         Verdict("unsupported_app", f"Argument {locator} has no registry record"))
        if ctype in CHART_TYPES:
            if c.get("colors") is not None:
                if ctype == "scorecard":
                    # The recipe sends no set_style for scorecards (no series swatch), so coverage could never verify it.
                    found.append(Verdict("unsupported_app", SCORECARD_COLORS))
                elif not isinstance(c["colors"], list) or not 1 <= len(c["colors"]) <= 20:
                    found.append(Verdict("unsupported_app", "Chart colors need 1 to 20 colors"))
                else:
                    arg("set_style.style.colors", c["colors"])
            for metric in c.get("metrics") or ():
                arg("add_chart.metrics.agg", metric.get("agg"))
            for key in ("date_dimension", "breakdown"):
                if c.get(key) is not None:
                    arg(f"add_chart.{key}")
            if c.get("sort") is not None:
                arg("add_chart.sort", (c["sort"] or {}).get("order"))
        elif ctype in CONTROL_TYPES and c.get("field") is not None:
            arg("add_control.field")
        if ctype not in CHART_TYPES and c.get("colors") is not None:
            found.append(Verdict("unsupported_app", "Only chart components support colors"))
        return [v for v in found if not v.ok]

    def assess(self, requirements, components, schema: dict[str, str]) -> Result:
        """Ready only when every requirement and component is supported; unknowns always block."""
        issues = []
        for requirement in requirements:
            requirement = requirement if isinstance(requirement, Requirement) else Requirement.model_validate(requirement)
            issues += [(requirement.id, v) for v in self.requirement(requirement, schema)]
        for component in components:
            cid = component.get("id", "") if isinstance(component, dict) else component.id
            issues += [(cid, v) for v in self.component(component)]
        return Result(not issues, tuple(issues))
