import json
import re
import time

import pytest
from pydantic import ValidationError

from dss.config import BACKEND_DIR
from dss.spec.capabilities import REGISTRY_PATH, Checker, Need, Registry, Requirement, evidence_kind, load_registry
from dss.spec.models import DashboardSpec, TYPES

CONTRACTS = BACKEND_DIR.parent / "contracts"
SCHEMA = json.loads((CONTRACTS / "recipe.schema.json").read_text(encoding="utf-8"))
RECIPE_MD = (CONTRACTS / "recipe.md").read_text(encoding="utf-8")
PLUMBING = {"open_report", "save_report", "get_link"}  # report lifecycle, not requestable features
ALL = set(TYPES)
SALES = {"order_date": "DATE", "region": "STRING", "revenue": "FLOAT64", "country": "GEOGRAPHY"}


def variants():
    for variant in SCHEMA["$defs"]["op"]["oneOf"]:
        yield variant["properties"]["op"]["const"], variant["properties"]


def chart_options():
    """{chart_type: {key: enumerated values or None}} parsed from recipe.md's options line."""
    para = RECIPE_MD.split("- `options` by chart type (all optional):", 1)[1].split("\n- ", 1)[0]
    found, alias = {}, {}
    # Chart types are separated by `;` outside parentheses (recipe 1.3 notes use `;` inside them).
    for chunk in re.split(r";(?![^()]*\))", para.strip().rstrip(".")):
        ctype, rest = re.match(r"\s*`(\w+)`:(.*)", chunk, re.S).groups()
        keys = re.findall(r"`(\w+)`", re.sub(r"\([^)]*\)", "", rest))
        found[ctype] = {}
        for key in keys:
            paren = re.search(r"\(([^)]*)\)", rest[rest.index(f"`{key}`"):])[1]
            if same := re.fullmatch(r"as `(\w+)`", paren.strip()):
                alias[ctype, key] = same[1]  # `(as `time_series`)`: that type's values for the same key
            # `(`a`\|`b`)` enumerates values; otherwise the first word is the type: bool, int or lists
            found[ctype][key] = re.findall(r"`(\w+)`", paren) if "\\|" in paren else re.match(r"\s*(\w+)", paren)[1]
    for (ctype, key), other in alias.items():
        found[ctype][key] = found[other][key]
    return found


def recipe_locators():
    """Every requestable recipe 1.0 type, argument, option and style key, derived from the contract."""
    locators = set()
    for op, props in variants():
        if op in PLUMBING:
            continue
        if op == "add_chart":
            locators |= {f"add_chart.chart_type={t}" for t in props["chart_type"]["enum"]}
            locators |= {f"add_chart.{k}" for k in props if k not in ("op", "component_id", "chart_type", "dimensions", "metrics", "options")}
            assert "agg" in SCHEMA["$defs"]["metric"]["properties"]
            locators.add("add_chart.metrics.agg")
        elif op == "add_control":
            locators |= {f"add_control.control_type={t}" for t in props["control_type"]["enum"]}
            locators |= {f"add_control.{k}" for k in props if k not in ("op", "component_id", "control_type")}
        elif op == "set_style":
            locators |= {f"set_style.style.{k}" for k in props["style"]["properties"]}
        else:
            locators.add(op)
            if op == "add_text":
                locators |= {f"add_text.{k}" for k in props if k not in ("op", "component_id", "text")}
    for ctype, keys in chart_options().items():
        locators |= {f"add_chart.options.{ctype}.{key}" for key in keys}
    return locators


@pytest.fixture(scope="module")
def registry():
    return load_registry()


def test_registry_classifies_exactly_the_recipe_surface(registry):
    derived = recipe_locators()
    assert {"add_chart.chart_type=geo_map", "set_style.style.border_color", "add_chart.options.bar.stacked", "add_text.align"} <= derived
    assert len(derived) >= 35
    classified = {loc for cap in registry.capabilities for loc in cap.recipe}
    assert classified == derived
    for t in SCHEMA["$defs"]["metric"]["properties"]["agg"]["enum"]:
        assert registry.at("add_chart.metrics.agg").values.count(t) == 1
    sort = next(p for op, p in variants() if op == "add_chart")["sort"]["properties"]["order"]["enum"]
    assert registry.at("add_chart.sort").values == sort


def test_option_values_match_the_contract(registry):
    for ctype, keys in chart_options().items():
        for key, values in keys.items():
            cap = registry.at(f"add_chart.options.{ctype}.{key}")
            assert cap.requires == [f"chart.{ctype}"]
            if isinstance(values, list):
                assert cap.values == values, cap.id
            else:
                assert cap.values is None and cap.value_type == {"bool": "bool", "int": "int", "lists": "field_list"}[values], cap.id
    align = next(p for op, p in variants() if op == "add_text")["align"]["enum"]
    assert registry.get("argument.text_align").values == align


def _exists(item):
    """The cited file's text, or only the cited section's text when the citation has an anchor."""
    path, _, anchor = item.partition("#")
    target = BACKEND_DIR / path
    assert target.is_file(), item
    text = target.read_text(encoding="utf-8")
    if not anchor:
        return text
    slug = lambda heading: re.sub(r"\W+", "-", heading.lstrip("#").strip().lower()).strip("-")
    section = next((s for s in re.split(r"^(?=#+\s)", text, flags=re.M) if slug(s.split("\n", 1)[0]) == anchor.lower()), None)
    assert section is not None, item
    return section


def test_evidence_exists_and_app_support_cites_a_contract_that_exercises_it(registry):
    assert registry.verified.isoformat() >= "2026-10-19"
    for cap in registry.capabilities:
        for item in cap.app.evidence:
            _exists(item)
        for item in cap.native_product.evidence:
            assert evidence_kind(item) == "official", (cap.id, item)
        if cap.native_product.status != "unknown":
            assert cap.native_product.evidence and cap.native_product.verified
        if cap.app.status == "supported":
            cited = [_exists(e) for e in cap.app.evidence if evidence_kind(e) == "contract"]
            assert cited, cap.id
            for locator in cap.recipe:
                tokens = [t for t in re.split(r"[.=]", locator) if t not in ("add_chart", "options", "style")]
                assert any(all(t in text for t in tokens) for text in cited), (cap.id, locator)


def test_registry_covers_contract_negative_and_scope_cases(registry):
    kinds = {cap.kind for cap in registry.capabilities}
    assert {"geo_granularity", "interaction", "animation", "refresh", "extension", "layout", "control_type"} <= kinds
    assert registry.get("option.geo_map.geo_type").values == ["country", "region", "city"]
    assert registry.get("chart.pie").native_product.limits == {"max_slices": 10}
    assert registry.get("layout.canvas").app.limits == {"width": 1200}


def _raw():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _with(record_patch=None, top=None):
    raw = _raw()
    if record_patch:
        record_patch(raw["capabilities"][0])
    raw.update(top or {})
    return raw


@pytest.mark.parametrize("patch", [
    lambda r: r.update(animate=True),
    lambda r: r["app"].update(confidence="high"),
    lambda r: r["native_product"].update(status="probably"),
    lambda r: r.update(kind="widget"),
])
def test_undeclared_keys_and_values_reject(patch):
    with pytest.raises(ValidationError):
        Registry.model_validate(_with(patch))
    with pytest.raises(ValidationError):
        Registry.model_validate(_with(top={"extra": 1}))


@pytest.mark.parametrize("item", [
    "https://example.com/data-studio/blog", "The model confirmed this works", "../engine/src/maps.py",
    "../contracts/../engine/x.md", "../contracts/fixtures/", "src\\dss\\x.py", "https://docs.cloud.google.com/data-studio/",
])
def test_unknown_evidence_rejects(item):
    assert evidence_kind(item) is None
    with pytest.raises(ValidationError, match="unknown"):
        Registry.model_validate(_with(lambda r: r["app"]["evidence"].append(item)))
    with pytest.raises(ValidationError, match="unknown"):
        Registry.model_validate(_with(lambda r: r["native_product"]["evidence"].append(item)))


@pytest.mark.parametrize("patch, message", [
    (lambda r: r["app"].update(evidence=["src/dss/recipe/compiler.py"]), "must cite"),
    (lambda r: r["native_product"].update(evidence=[]), "dated evidence"),
    (lambda r: r["app"].pop("verified"), "dated evidence"),
    (lambda r: r["native_product"].update(status="unsupported"), "contradictory"),
    (lambda r: r.update(requires=["chart.unicorn"]), "unknown requirement"),
])
def test_unsupported_evidence_combinations_reject(patch, message):
    with pytest.raises(ValidationError, match=message):
        Registry.model_validate(_with(patch))


def test_duplicate_locator_and_cycles_reject():
    raw = _raw()
    raw["capabilities"][1]["recipe"] = list(raw["capabilities"][0]["recipe"])
    with pytest.raises(ValidationError, match="classified twice"):
        Registry.model_validate(raw)
    raw = _raw()
    first, second = raw["capabilities"][:2]
    first["requires"], second["requires"] = [second["id"]], [first["id"]]
    with pytest.raises(ValidationError, match="cycle"):
        Registry.model_validate(raw)


def geo(**options):
    return {"id": "p1_map", "type": "geo_map", "options": options, "dimensions": ["country"],
            "metrics": [{"field": "revenue", "agg": "sum"}]}


def test_animation_hidden_under_an_allowed_geo_map_rejects(registry):
    checker = Checker(registry, allowed=ALL)
    assert checker.component(geo(geo_type="country")) == []
    for options in ({"geo_type": "country", "animate": True}, {"animation": {"playback": "route"}}, {"geo_type": "gps_point"}):
        issues = checker.component(geo(**options))
        assert issues and {v.status for v in issues} == {"unsupported_app"}
    hidden = [geo(geo_type="country") | {"animate": True},
              geo(geo_type="country") | {"metrics": [{"field": "revenue", "agg": "sum", "animation": {"route": True}}]},
              geo(geo_type="country") | {"sort": {"field": "revenue", "order": "desc", "playback": True}},
              geo(geo_type="country") | {"options": ["animate"]}, geo(geo_type=None), geo(geo_type="country", animate=None)]
    for component in hidden:
        assert [v.status for v in checker.component(component)] == ["unsupported_app"], component
    assert not checker.assess([], [{k: v for k, v in hidden[0].items() if k != "id"}], SALES).ready
    gps = Requirement(id="r1", needs=[Need(capability="animation.temporal_playback"), Need(capability="geo.lat_long_points")])
    verdicts = checker.requirement(gps, SALES)
    assert [v.status for v in verdicts] == ["unsupported_app", "unsupported_app"]
    assert "../contracts/recipe.md#Ops" in verdicts[0].evidence
    assert not checker.assess([gps], [geo(geo_type="country")], SALES).ready


def test_component_checks_types_options_values_and_arguments(registry):
    checker = Checker(registry, allowed=ALL)
    bar = {"id": "p1_bar", "type": "bar", "dimensions": ["region"], "metrics": [{"field": "revenue", "agg": "sum"}],
           "sort": {"field": "revenue", "order": "desc"}, "options": {"orientation": "horizontal", "stacked": True}}
    assert checker.component(bar) == []
    for bad in ({"options": {"orientation": "diagonal"}}, {"options": {"stacked": "yes"}}, {"options": {"orientation": None}},
                {"options": {"stacked": None}}, {"sort": {"field": "revenue"}}, {"options": {"donut": True}},
                {"metrics": [{"field": "revenue", "agg": "median"}]}, {"sort": {"field": "revenue", "order": "random"}},
                {"type": "sparkline"}):
        assert checker.component({**bar, **bad}), bad
    assert checker.component({"id": "p1_t", "type": "table", "options": {"rows_per_page": True}})
    assert checker.component({"id": "p1_t", "type": "table", "options": {"rows_per_page": 10}}) == []
    assert checker.component({"id": "p1_x", "type": "text", "options": {"font_size": 20}})


def test_scorecard_colors_reject_per_chart_type(registry):
    checker = Checker(registry, allowed=ALL)
    card = {"id": "p1_card", "type": "scorecard", "metrics": [{"field": "revenue", "agg": "sum"}]}
    assert checker.component(card) == []
    verdicts = checker.component({**card, "colors": ["#172554"]})
    assert [v.status for v in verdicts] == ["unsupported_app"]
    assert "Scorecards" in verdicts[0].reason and "colors" in verdicts[0].reason
    bar = {"id": "p1_bar", "type": "bar", "dimensions": ["region"], "metrics": [{"field": "revenue", "agg": "sum"}]}
    assert checker.component({**bar, "colors": ["#172554"]}) == []
    assert checker.component({**bar, "colors": ["#172554"] * 20}) == []
    assert checker.component({**bar, "colors": ["#172554"] * 21})
    text = checker.component({"id": "p1_t", "type": "text", "colors": ["#172554"]})
    assert [v.reason for v in text] == ["Only chart components support colors"]


@pytest.mark.parametrize("name", ["golden_spec.json", "thin_spec.json"])
def test_existing_golden_specs_stay_supported(registry, name):
    spec = DashboardSpec.model_validate_json((BACKEND_DIR / "tests/data" / name).read_text(encoding="utf-8"))
    schema = {f.name: f.type for f in spec.datasource.fields}
    result = Checker(registry, allowed=ALL).assess([], spec.pages[0].components, schema)
    assert result.ready, result.issues


def test_native_support_without_app_evidence_is_unsupported_app(registry):
    checker = Checker(registry, allowed=ALL)
    for cid in ("extension.community_visualization", "interaction.cross_filter", "interaction.drill_down",
                "layout.multi_page", "style.border_color", "refresh.data_freshness"):
        cap = registry.get(cid)
        assert cap.native_product.status == "supported" and cap.app.status != "supported"
        assert checker.capability(cid).status == "unsupported_app"
    raw = _raw()
    record = next(r for r in raw["capabilities"] if r["id"] == "chart.scatter")
    record["app"] = {"status": "unknown"}
    assert Checker(Registry.model_validate(raw), allowed=ALL).capability("chart.scatter").status == "unsupported_app"


def test_documented_product_exclusion_is_unsupported_product(registry):
    # 24.1: the fixed-size list became app-supported (recipe 1.3); shapes have no recipe op.
    raw = _raw()
    record = next(r for r in raw["capabilities"] if r["id"] == "element.shape")
    record["native_product"] = {"status": "unsupported", "evidence": ["https://docs.cloud.google.com/data-studio/date-range-control"], "verified": "2026-10-20"}
    checker = Checker(Registry.model_validate(raw), allowed=ALL)
    assert checker.capability("element.shape").status == "unsupported_product"
    assert Checker(registry, allowed=ALL).capability("element.shape").status == "unsupported_app"


RECIPE_13 = {"chart.area": "add_chart.chart_type=area", "option.area.stacked": "add_chart.options.area.stacked",
             "option.area.stacked_percent": "add_chart.options.area.stacked_percent",
             "option.area.date_granularity": "add_chart.options.area.date_granularity",
             "option.bar.stacked_percent": "add_chart.options.bar.stacked_percent",
             "control.fixed_size_list": "add_control.control_type=fixed_size_list"}


@pytest.mark.parametrize("cid", RECIPE_13)
def test_recipe_13_records_are_app_supported(registry, cid):
    """24.1: release 2.6's area charts, rural/urban split bar and region list stop being stand-ins."""
    cap = registry.get(cid)
    assert cap.recipe == [RECIPE_13[cid]]
    assert cap.app.status == cap.native_product.status == "supported"
    assert "../contracts/recipe.md#Ops" in cap.app.evidence
    assert [evidence_kind(e) for e in cap.native_product.evidence] == ["official"]
    assert cap.native_product.verified.isoformat() == cap.app.verified.isoformat() == "2026-10-24"
    checker = Checker(registry, allowed=ALL)
    assert checker.capability(cid).ok
    assert checker.capability("option.area.date_granularity", "month").ok
    assert checker.capability("option.area.date_granularity", "hour").status == "unsupported_app"
    narrow = Checker(registry, allowed=ALL - {"area", "fixed_size_list"})
    assert narrow.capability(cid).status == ("supported" if cid == "option.bar.stacked_percent" else "unsupported_app")


def test_recipe_13_components_check(registry):
    checker = Checker(registry, allowed=ALL)
    area = {"id": "p1_area", "type": "area", "date_dimension": "order_date", "breakdown": "region",
            "metrics": [{"field": "revenue", "agg": "sum"}], "options": {"stacked": True, "stacked_percent": True}}
    bar = {"id": "p1_bar", "type": "bar", "dimensions": ["region"], "metrics": [{"field": "revenue", "agg": "sum"}],
           "options": {"stacked_percent": True}}
    listed = {"id": "p1_list", "type": "fixed_size_list", "field": "region"}
    assert [checker.component(c) for c in (area, bar, listed)] == [[], [], []]
    for bad in ({**area, "options": {"stacked_percent": "yes"}}, {**area, "options": {"orientation": "vertical"}},
                {**bar, "options": {"stacked_percent": None}}, {**listed, "colors": ["#172554"]},
                {**listed, "options": {"stacked": True}}):
        assert checker.component(bad), bad
    assert SALES["order_date"] in registry.get("chart.area").data[0].types


def test_missing_data_is_needs_data_and_ambiguity_needs_clarification(registry):
    checker = Checker(registry, allowed=ALL)
    trend = lambda **fields: Need(capability="chart.time_series", fields=fields)
    assert checker.need(trend(date_field="order_date"), SALES).ok
    assert checker.need(trend(), {"region": "STRING"}).status == "needs_data"
    assert checker.need(trend(date_field="shipped_at"), SALES).status == "needs_data"
    assert checker.need(trend(date_field="region"), SALES).status == "needs_data"
    ambiguous = checker.need(trend(), {**SALES, "shipped_at": "TIMESTAMP"})
    assert ambiguous.status == "needs_clarification" and ambiguous.candidates == ("order_date", "shipped_at")
    assert checker.need(trend(date_field="order_date", latitude="revenue"), SALES).status == "needs_clarification"
    assert checker.need(Need(capability="chart.geo_map", fields={"geo_field": "region"}), SALES).status == "needs_data"
    assert checker.need(Need(capability="option.geo_map.geo_type", value="city", fields={"geo_field": "country"}), SALES).ok
    no_geo = {"region": "STRING", "revenue": "FLOAT64"}
    for fields in ({}, {"geo_field": "region"}):
        verdict = checker.need(Need(capability="option.geo_map.geo_type", value="city", fields=fields), no_geo)
        assert verdict.status == "needs_data", fields


def test_unknowns_cannot_become_ready(registry):
    checker = Checker(registry, allowed=ALL)
    supported = Requirement(id="r1", needs=[Need(capability="chart.bar"), Need(capability="option.bar.orientation", value="vertical")])
    assert checker.assess([supported], [], SALES).ready
    for requirement in (Requirement(id="r2", needs=[Need(capability="chart.hologram")]), Requirement(id="r3"),
                        Requirement(id="r4", needs=[Need(capability="animation.temporal_playback")]),
                        Requirement(id="r5", needs=[Need(capability="chart.bar", value="anything")])):
        result = checker.assess([supported, requirement], [], SALES)
        assert not result.ready and [i for i, _ in result.issues] == [requirement.id]
    assert checker.capability("chart.hologram").status == "unknown"
    assert checker.capability("extension.embedded_content").status == "unsupported_app"
    raw = _raw()
    record = next(r for r in raw["capabilities"] if r["id"] == "chart.bar")
    record["native_product"] = {"status": "unknown"}
    narrowed = Checker(Registry.model_validate(raw), allowed=ALL)
    assert narrowed.capability("chart.bar").status == "unknown"
    assert narrowed.capability("option.bar.stacked", True).status == "unknown"
    assert not narrowed.assess([supported], [], SALES).ready


def test_allowed_types_only_narrow(registry, monkeypatch):
    full = Checker(registry, allowed=ALL)
    narrow = Checker(registry, allowed={"bar", "unicorn"})
    assert narrow.capability("chart.bar").ok
    assert narrow.capability("chart.pie").status == "unsupported_app"
    assert "DSS_ALLOWED_TYPES" in narrow.capability("option.pie.donut", True).reason
    assert narrow.component({"id": "p1_pie", "type": "pie", "options": {"donut": True}})
    assert narrow.capability("chart.unicorn").status == "unknown"
    assert narrow.component({"id": "p1_u", "type": "unicorn"})
    for cid in ("animation.temporal_playback", "extension.community_visualization"):
        assert full.capability(cid).status == narrow.capability(cid).status == "unsupported_app"
    widened = {cid for cid in (c.id for c in registry.capabilities) if narrow.capability(cid).ok and not full.capability(cid).ok}
    assert widened == set()
    assert full.digest() != narrow.digest() and full.digest() == Checker(registry, allowed=sorted(ALL)).digest()
    monkeypatch.setenv("DSS_ALLOWED_TYPES", "bar, table")
    assert Checker(registry).allowed == {"bar", "table"}


def test_registry_digest_tracks_content(registry):
    raw = _raw()
    raw["capabilities"][0]["label"] += " (changed)"
    assert Registry.model_validate(raw).digest() != registry.digest() == load_registry().digest()


def test_forty_requirements_and_twenty_four_components_within_100ms(registry):
    kinds = [Need(capability="chart.time_series", fields={"date_field": "order_date"}), Need(capability="option.geo_map.geo_type", value="region"),
             Need(capability="argument.metric_agg", value="sum"), Need(capability="animation.temporal_playback"), Need(capability="chart.hologram")]
    requirements = [Requirement(id=f"r{i}", needs=[kinds[i % 5], kinds[(i + 1) % 5]]) for i in range(40)]
    components = [geo(geo_type="country", animate=bool(i % 2)) | {"id": f"p1_c{i}"} for i in range(24)]
    schema = {**SALES, **{f"col_{i}": "STRING" for i in range(60)}}
    best = float("inf")
    for _ in range(5):
        start = time.perf_counter()
        result = Checker(registry, allowed=ALL).assess(requirements, components, schema)
        best = min(best, time.perf_counter() - start)
    assert not result.ready and len(result.issues) >= 40
    assert best <= 0.100, best


def test_capability_context_compacts_staged_artifacts():
    """Live 15.11: one comment's capability check overran 12k with every staged artifact in it."""
    from dss.harness.context import capability_context
    from dss.spec.requirements import Ledger
    context = {'title': 'T', 'goal': 'G', 'datasets': [{'source_id': 's', 'summary': 'x' * 400}], 'derived_fields': [],
               'kpis': [{'id': 'net_revenue'}], 'thresholds': [], 'glossary': [], 'issues': []}
    snapshot = {'sources': [], 'reference': None, 'definitions': {}, 'spec': {'pages': []}, 'incoming': [],
                'context': context, 'outline': {'sections': 'OUTLINE'}, 'design': {'d': 'DESIGN'},
                'blueprint': {'rows': 'BLUEPRINT'}, 'blueprint_errors': ['ERRORS']}
    memory = capability_context(snapshot, Ledger(), Checker(load_registry()), [])
    [section] = [s for s in memory.sections if s.name == 'metadata']
    metadata = json.loads(section.body)
    assert sorted(metadata) == ['context', 'definitions', 'reference', 'sources', 'spec']
    assert metadata['context'] == {'derived_fields': [], 'kpis': [{'id': 'net_revenue'}], 'thresholds': [], 'glossary': []}
    assert not re.search('OUTLINE|DESIGN|BLUEPRINT|ERRORS', str(memory))


def test_capability_context_omits_designed_page_html():
    """Live 20.5: a move comment on a 3-page designed build sent every page's design.html (15.5k > 12k)."""
    from dss.harness.context import capability_context
    from dss.spec.requirements import Ledger
    spec = json.loads((BACKEND_DIR / 'tests/data/designed_spec.json').read_text(encoding='utf-8'))
    html = next(p['design']['html'] for p in spec['pages'] if p.get('design'))
    snapshot = {'sources': [], 'reference': None, 'definitions': {}, 'spec': spec, 'incoming': [], 'context': None}
    memory = capability_context(snapshot, Ledger(), Checker(load_registry()), [])
    [section] = [s for s in memory.sections if s.name == 'metadata']
    pages = json.loads(section.body)['spec']['pages']
    assert [p['index'] for p in pages] == [p['index'] for p in spec['pages']]
    assert all('design' not in p for p in pages) and html not in str(memory)
    assert any(d['kind'] == 'design' for p in pages for d in p['decorations'])
    assert any(p.get('design') for p in spec['pages'])  # the snapshot itself keeps its designs
