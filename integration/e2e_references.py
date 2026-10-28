"""Reference, refusal and synthetic end-to-end through the API (release 2.5 local, 4.3 hosted).

    uv run --project integration python integration/e2e_references.py --render-reference
    uv run --project integration python integration/e2e_references.py [--server URL] --live [--cases a,b]
    uv run --project integration python integration/e2e_references.py [--server URL] --after-restart

Cases, one build each (contracts/dashboard-intent.md 1.2, contracts/synthetic-data.md 1.2):
  refusal    ecommerce CSV + a moving-GPS outline Other text: blocked before any view, spec,
             recipe or engine run
  revenue    gross_net_sales.csv: the context's Revenue KPI states its assumption; a KPI edit to
             the other field reaches the regenerated blueprint
  style      reference PNG (style) + ecommerce CSV: bound components and the reference's theme;
             replacing, then removing the reference blocks recipe and run of the stale prototype
  recreate   reference PNG (recreate) + ecommerce CSV: bound components, theme and relative order,
             a live Data Studio build; then a new version and a changed DSS_ALLOWED_TYPES recheck
  synthetic  reference PNG only: proposed and edited schema, 1,000 generated rows, CSV download and
             reparse, typed BigQuery intake, labeled prototype and live report
--after-restart downloads the synthetic CSV again (restart the backend first) and compares checksums.
Writes deck/data/bench-references-<local|hosted>.json (merged per case; no secrets, no images).
--live refuses a local .env with DSS_ENGINE_DRY_RUN=1: dry-run builds are no evidence.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_flow1 import Flow, dumps, env_value  # noqa: E402
from render_diagrams import find_chrome, png_size  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
REFERENCE_HTML = SAMPLES / "reference-dashboard.html"
REFERENCE_PNG = SAMPLES / "reference-dashboard.png"
REFERENCE_SIZE = (1200, 750)
EXPECT = SAMPLES / "reference-expectations.json"
ECOMMERCE = SAMPLES / "ecommerce_sales.csv"
GROSS_NET = SAMPLES / "gross_net_sales.csv"
RENDER = ROOT / "deck" / "render" / "references"     # git-ignored: prototype snapshots for the manual review
CASES = ("refusal", "revenue", "style", "recreate", "synthetic")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
SYNTHETIC_LABEL = "Synthetic sample data"
CHART_TYPES = {"scorecard", "time_series", "bar", "pie", "table", "pivot_table", "geo_map", "scatter"}
SIDE_EFFECT_NODES = {"prototype", "recipe", "execute"}
# KPI names match the reference's card labels, so its observations bind to these explicit definitions.
NOTES = ("The sales director reviews revenue, orders and units sold by month, product category and product. "
         "KPIs: Revenue = SUM(revenue) in USD; Orders = COUNT(DISTINCT order_id); Units sold = SUM(quantity). "
         "Revenue trends are monthly by order_date.")
REVENUE_NOTES = ("The finance lead's headline KPI is called Revenue; keep that name. It is reviewed by region, "
                 "category and month. Each row is one order.")  # never names its field: the draft must assume one
# Reference builds name no charts or KPIs: their structure must come from the screenshot.
REFERENCE_NOTES = "The sales director reviews the online store's performance every week."
GPS_TEXT = ("Animate each delivery van's GPS points moving along its route on a map over the day, "
            "like a playback of the trip.")
STYLE_TEXT = "Borrow the colors, the header band and the card style of this dashboard."
# A screenshot never supplies the data definitions (dashboard-intent.md, Scope): the user states
# which field each observed label means, as explicit clauses that bind the observations.
RECREATE_TEXT = ("Recreate this dashboard with my sales data. Definitions: Revenue = SUM(revenue) in USD; "
                 "Orders = COUNT(DISTINCT order_id); Units sold = SUM(quantity); Quantity = SUM(quantity); "
                 "Revenue by month = SUM(revenue) "
                 "by month of order_date; Revenue by category = SUM(revenue) by category; Top products by revenue "
                 "= SUM(revenue) and SUM(quantity) by product_name.")
SYNTHETIC_TEXT = "Recreate this dashboard with generated sample data."
SPEC_TYPES = {"integer": "number", "number": "number", "string": "string", "date": "date", "boolean": "boolean"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def git_revision() -> dict:
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    # Untracked files count (a new driver is part of what ran); the bench files themselves don't.
    changed = git("status", "--porcelain", "--", ".", ":(exclude)deck/data/bench-references-*.json")
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(changed)}


def rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def distance(a: str, b: str) -> float:
    return sum((x - y) ** 2 for x, y in zip(rgb(a), rgb(b))) ** .5


def comp_fields(c: dict) -> list[str]:
    fields = list(c.get("dimensions") or []) + [m["field"] for m in c.get("metrics") or []]
    fields += [f for f in (c.get("date_dimension"), c.get("breakdown"), c.get("field")) if f]
    return fields


def spec_components(spec: dict) -> list[tuple[int, dict]]:
    return [(page["index"], c) for page in spec["pages"] for c in page.get("components", [])]


class Case(Flow):
    """One scenario on its own build: checks, timings, assessments and differences for the bench."""

    def __init__(self, client: httpx.Client, secrets: list[str], live: bool, name: str) -> None:
        super().__init__(client, secrets, live=live)
        self.name = name
        self.started = time.monotonic()
        self.out: dict = {"passed": False, "run_date": utc_now(), "seconds": 0.0, "build_id": None,
                          "checks": [], "assessments": [], "stages": self.rows, "decisions": self.decisions}

    # --- plumbing ---------------------------------------------------------------------------
    def check(self, ok, what: str, detail=None) -> None:
        entry = {"check": what, "ok": bool(ok)}
        if detail is not None:
            entry["detail"] = detail
        self.out["checks"].append(entry)
        print(f"{self.name}: {'ok  ' if ok else 'FAIL'} {what}", flush=True)
        if not ok:
            raise RuntimeError(self.redact(f"{self.name}: {what}" + ("" if detail is None else f": {dumps(detail)}")))

    def act(self, method: str, suffix: str, **kwargs) -> str:
        """Start a build action (202 + run_id) and wait for its trace; a trace error raises."""
        url = f"/api/builds/{self.build_id}{suffix}"
        for attempt in range(4):
            response = self.client.request(method, url, **kwargs)
            if response.status_code == 409 and "wrong_stage" in response.text and attempt < 3:
                time.sleep(1)  # the per-build lock is released a moment after the trace
                continue
            break
        if response.status_code != 202 or not response.json().get("run_id"):
            raise RuntimeError(self.redact(f"backend: {method} {url}: HTTP {response.status_code}: {response.text}"))
        run_id = response.json()["run_id"]
        self._run_ids.append(run_id)
        deadline = time.monotonic() + 600
        while True:
            trace = next((t for t in self.traces() if t["run_id"] == run_id), None)
            if trace:
                if trace["status"] == "error":
                    raise RuntimeError(self.redact(f"backend: {method} {suffix}: " + dumps(trace)))
                return run_id
            if time.monotonic() >= deadline:
                raise RuntimeError(f"backend: {method} {suffix} timed out after 600 s")
            time.sleep(2)

    def refused(self, method: str, suffix: str, status: int, codes: set[str], what: str, **kwargs) -> dict:
        """The call must fail with this status and one of these error codes; returns the error."""
        url = f"/api/builds/{self.build_id}{suffix}"
        for attempt in range(4):
            response = self.client.request(method, url, **kwargs)
            code = (response.json().get("error") or {}).get("code") if response.headers.get(
                "content-type", "").startswith("application/json") and not response.is_success else None
            if code == "wrong_stage" and "wrong_stage" not in codes and attempt < 3:
                time.sleep(1)
                continue
            break
        self.check(response.status_code == status and code in codes, what,
                   {"status": response.status_code, "code": code})
        return response.json()["error"]

    def assessment(self, at: str) -> dict:
        a = self.api("GET", "/feasibility")
        self.out["assessments"].append({"at": at, "state": a["state"], "prototype_stale": a["prototype_stale"],
            "issues": [{"status": i["status"], "requirement": i["requirement"], "resolution": i["resolution"],
                        "alternatives": [x["label"] for x in i["alternatives"]]} for i in a["issues"]],
            "pending_comments": bool(a.get("pending_comments"))})
        return a

    # --- the staged flow --------------------------------------------------------------------
    def create(self, title: str, archetype: str = "executive") -> None:
        build = self.request("POST", "/api/builds", json={"title": title, "archetype": archetype, "mode": "data"}).json()
        self.build_id = self.out["build_id"] = build["id"]
        print(f"{self.name}: build {self.build_id}", flush=True)

    def upload(self, path: Path) -> None:
        with path.open("rb") as fh:
            # Intake loads BigQuery synchronously (observed 97-120+ s): the 10-minute poll cap applies.
            self.request("POST", f"/api/builds/{self.build_id}/sources/upload",
                         files={"files": (path.name, fh, "text/csv")}, timeout=600)

    def reference(self, mode: str, instructions: str) -> dict:
        with self.stage(1, f"reference_{mode}"):
            self.act("POST", "/reference-images", data={"mode": mode, "instructions": instructions},
                     files={"files": (REFERENCE_PNG.name, REFERENCE_PNG.read_bytes(), "image/png")})
        ref = self.api("GET", "/reference-images")
        self.check(ref and ref["mode"] == mode and len(ref["images"]) == 1, f"reference set in {mode} mode",
                   {"mode": ref and ref["mode"], "summary": ref and ref["summary"][:200]})
        self.out["reference"] = {"mode": mode, "summary": ref["summary"]}
        if mode == "recreate":
            ref = self.approve(ref)
        return ref

    def approve(self, ref: dict) -> dict:
        """A recreate analysis gates design/confirm (dashboard-intent 1.3): approve it as analyzed.
        Its issues fail the case; the driver never edits the analysis to clear them."""
        analysis = ref["analysis"]
        self.check(analysis and analysis["state"] == "pending" and not analysis["issues"],
                   "recreate analysis pending without issues",
                   analysis and {"state": analysis["state"], "issues": analysis["issues"]})
        ref = self.api("POST", "/reference-images/analysis/approve", json={"revision": analysis["revision"]})
        self.check(ref["analysis"]["state"] == "approved" and ref["analysis"]["revision"] == analysis["revision"],
                   "recreate analysis approved", {k: ref["analysis"][k] for k in ("state", "revision")})
        self.out["reference"]["analysis"] = {"revision": analysis["revision"], "summary": analysis["summary"],
                                             "items": len(analysis["items"])}
        return ref

    def context(self, notes: str | None) -> dict:
        with self.stage(1, "context"):
            self.act("POST", "/context", json={"notes": notes} if notes else {})
        context = self.api("GET", "/context")
        self.check(context and not context["issues"], "context drafted without issues",
                   None if context is None else context["issues"])
        return context

    def outline(self, other: str | None = None) -> dict:
        with self.stage(1, "outline"):
            self.act("POST", "/context/confirm")
            outline = self.api("GET", "/outline")
            self.check(outline and outline["sections"], "outline proposed")
            if other:
                self.act("POST", "/outline/other", json={"section_id": outline["sections"][-1]["id"], "text": other})
                outline = self.api("GET", "/outline")
            questions = [q for s in outline["sections"] for q in s["questions"]]
            outline = self.api("PUT", "/outline/selection", json={"questions": [
                {"id": q["id"], "selected": bool(q["recommended"]) or q["origin"] == "other"} for q in questions]})
        self.out["outline_questions"] = [q["text"] for s in outline["sections"] for q in s["questions"] if q["selected"]]
        return outline

    def design(self) -> dict:
        """Confirm the outline and keep the Design the code prefilled (preset or reference)."""
        with self.stage(1, "design"):
            self.api("POST", "/outline/confirm")
            design = self.api("GET", "/design")
        self.check(design and not design["issues"], "design prefilled without issues",
                   None if design is None else design["issues"])
        self.out["design"] = {k: design[k] for k in ("preset_id", "source", "accent", "background", "palette",
                                                     "font_family", "page_structure")}
        return design

    def blueprint(self) -> dict:
        with self.stage(1, "blueprint"):
            self.act("POST", "/design/confirm")
        return self.api("GET", "/blueprint")

    def resolve(self, keep_observations: bool = False) -> dict:
        """Check (recreate image items reach the requirements only through a check), then take
        the offered alternative for each blocked requirement, or drop one offered none.
        keep_observations: a reference observation may not be dropped (recreate must keep them)."""
        assessment = self.assessment("blueprint")
        if assessment["state"] != "ready":
            with self.stage(self.api("GET")["current_version"], "check"):
                self.act("POST", "/feasibility/check")
            assessment = self.assessment("blueprint check")
        while assessment["state"] == "blocked":
            issue = next((i for i in assessment["issues"] if i["resolution"] == "unresolved"), None)
            if issue is None or len(self.decisions) >= 20:
                self.check(False, "a blocked assessment offers an unresolved issue (at most 20 decisions)",
                           [i["requirement"] for i in assessment["issues"]])
            alt = (issue["alternatives"] or [None])[0]
            # A check turns observations into rows ("Top products by revenue table"): any drop loses one.
            if keep_observations and not alt:
                self.check(False, "every reference observation binds without being dropped",
                           {"status": issue["status"], "reason": issue["reason"], "requirement": issue["requirement"][:200]})
            assessment = self.api("POST", "/feasibility/decisions", json={
                "assessment_id": assessment["id"], "decisions": [{
                    "issue_id": issue["id"], "action": "accept_alternative" if alt else "drop",
                    "alternative_id": alt["id"] if alt else None}]})
            self.decisions.append({"requirement": issue["requirement"], "status": issue["status"],
                                   "reason": issue["reason"], "action": "accept_alternative" if alt else "drop",
                                   "alternative": alt["label"] if alt else None})
        self.check(assessment["state"] == "ready", "assessment ready after decisions", assessment["state"])
        return assessment

    def prototype(self) -> dict:
        with self.stage(1, "prototype"):
            self.act("POST", "/blueprint/accept")
        build = self.api("GET")
        self.check(build["stage"] == "prototype", "prototype reached", build["stage"])
        return self.api("GET", "/spec")

    def live_build(self, version: int) -> None:
        """Recipe and engine run; a `partial` also publishes, so the engine's own run_finished
        (the version's events.jsonl) must report no failed op."""
        self.recipe_and_run(version)
        self.check(version in self.reports, f"v{version} published a Data Studio link", self.reports.get(version))
        lines = self.request("GET", f"/api/builds/{self.build_id}/files/events.jsonl").text.splitlines()
        finished = [json.loads(line) for line in lines if '"run_finished"' in line][-1:]
        result = {k: finished[0].get(k) for k in ("status", "ok", "failed", "skipped")} if finished else None
        self.out.setdefault("engine", {})[str(version)] = result
        self.check(result and result["status"] == "ok" and result["failed"] == 0,
                   f"v{version} engine run_finished ok with 0 failed ops", result)

    def snapshot(self, label: str) -> None:
        """Save the prototype HTML and a headless-Chrome PNG of it for the manual comparison."""
        RENDER.mkdir(parents=True, exist_ok=True)
        html = self.request("GET", f"/api/builds/{self.build_id}/prototype").text
        page = RENDER / f"{self.name}-{label}.html"
        page.write_text(html, encoding="utf-8")
        height = sum(p["height"] for p in self.api("GET", "/spec")["pages"])
        out = page.with_suffix(".png")
        out.unlink(missing_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="dss-render-", ignore_cleanup_errors=True) as profile:
                subprocess.run([find_chrome(), "--headless", f"--screenshot={out}", f"--window-size=1200,{height}",
                                "--hide-scrollbars", "--virtual-time-budget=8000", "--no-first-run",
                                f"--user-data-dir={profile}", page.as_uri()], capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired, SystemExit) as exc:
            print(f"{self.name}: prototype snapshot skipped: {exc}", flush=True)
        if out.is_file():  # an aid for the manual comparison, not a gate
            self.out.setdefault("snapshots", []).append(out.relative_to(ROOT).as_posix())

    def finish(self) -> dict:
        self.out["seconds"] = round(time.monotonic() - self.started, 3)
        traces = self.traces() if self.build_id else []
        for row in self.rows:
            ids = set(row["run_ids"])
            for key in ("input_tokens", "output_tokens"):
                row[key] = sum(t[key] for t in traces if t["run_id"] in ids)
        self.out["tokens"] = {k: sum(t[k] for t in traces) for k in ("input_tokens", "output_tokens")}
        if self.reports:
            self.out["report_urls"] = {str(n): u for n, u in self.reports.items()}
        return self.out

    # --- spec checks ------------------------------------------------------------------------
    def bound(self, spec: dict, columns: set[str]) -> None:
        """Every chart reads real fields: the datasource's fields are CSV columns or blueprint
        derived fields, and every field a component names is one of them."""
        derived = {f["name"] for f in (self.api("GET", "/blueprint") or {}).get("derived_fields", [])}
        names = {f["name"] for f in spec["datasource"]["fields"]}
        charts = [c for _, c in spec_components(spec) if c["type"] in CHART_TYPES]
        unknown = sorted({f for c in charts for f in comp_fields(c)} - names)
        unbound = [c["id"] for c in charts if not comp_fields(c)]
        self.check(charts and not unknown and not unbound and names <= columns | derived,
                   f"{len(charts)} charts bound to real fields",
                   {"unknown": unknown, "unbound": unbound, "not_columns": sorted(names - columns - derived)})
        self.out["components"] = [{"page": p, "type": c["type"], "label": c["label"], "fields": comp_fields(c),
                                   "grid": c["grid"]} for p, c in spec_components(spec)]

    def themed(self, spec: dict, design: dict, expect: dict) -> None:
        theme, ref = spec["theme"], expect["theme"]
        colors = [theme["accent"], *theme["palette"]]
        close = min(min(distance(c, ref["accent"]), distance(c, ref["band"])) for c in colors)
        self.check(design["source"] == "reference" and close <= ref["max_distance"],
                   "theme taken from the reference", {"design_source": design["source"], "accent": theme["accent"],
                   "palette": theme["palette"], "nearest_distance": round(close, 1)})
        self.out["theme"] = {"background": theme["background"], "accent": theme["accent"], "palette": theme["palette"],
                             "font_family": theme["font_family"], "nearest_distance": round(close, 1)}

    def compare(self, spec: dict, expect: dict, require_order: bool) -> None:
        """Match the expected reference items to spec components by label keyword, type and fields;
        record what is missing, substituted or added and check the relative order of the matches."""
        comps = [(p, c) for p, c in spec_components(spec) if c["type"] in CHART_TYPES]
        used, matches = set(), {}
        for item in expect["items"]:
            want = set(item.get("dimensions", [])) | {m["field"] for m in item.get("metrics", [])}
            want |= {item["date_dimension"]} if item.get("date_dimension") else set()
            best, best_score = None, 0
            for page, c in comps:
                if c["id"] in used:
                    continue
                label = c["label"].lower()
                score = 2 * any(k in label for k in item["keywords"]) + 2 * (c["type"] == item["type"])
                score += bool(want & set(comp_fields(c)))
                if score > best_score:
                    best, best_score = (page, c), score
            if best and best_score >= 3:
                used.add(best[1]["id"])
                matches[item["id"]] = best
        differences = [f"missing: {i['label']} ({i['type']})" for i in expect["items"] if i["id"] not in matches]
        substitutions = [f"{i['label']}: {i['type']} -> {matches[i['id']][1]['type']}"
                         for i in expect["items"] if i["id"] in matches and matches[i["id"]][1]["type"] != i["type"]]
        differences += [f"added: {c['label']} ({c['type']})" for _, c in comps if c["id"] not in used]
        items = {i["id"]: i for i in expect["items"]}
        violations = []
        for a, (pa, ca) in matches.items():
            for b, (pb, cb) in matches.items():
                ia, ib = items[a], items[b]
                if ia["band"] < ib["band"] and not (pa, ca["grid"]["row"]) < (pb, cb["grid"]["row"]):
                    violations.append(f"{ia['label']} is not above {ib['label']}")
                if ia["band"] == ib["band"] and ia["column"] < ib["column"] and pa == pb \
                        and ca["grid"]["row"] == cb["grid"]["row"] and not ca["grid"]["col"] < cb["grid"]["col"]:
                    violations.append(f"{ia['label']} is not left of {ib['label']}")
        pages = sorted({p for p, _ in matches.values()})
        self.out["comparison"] = {"matched": {k: {"label": c["label"], "type": c["type"], "page": p, "grid": c["grid"]}
                                              for k, (p, c) in matches.items()},
                                  "differences": differences, "substitutions": substitutions,
                                  "order_violations": violations, "pages": pages}
        if require_order:
            kpis = sum(items[k]["type"] == "scorecard" for k in matches)
            self.check(len(matches) >= 4 and kpis >= 2 and not violations,
                       f"recreated {len(matches)} of {len(items)} reference items in relative order",
                       {"violations": violations, "missing": [d for d in differences if d.startswith("missing")]})


# --- cases ------------------------------------------------------------------------------------

def columns_of(path: Path) -> set[str]:
    return set(path.read_text(encoding="utf-8").split("\n", 1)[0].split(","))


def case_refusal(c: Case, args) -> None:
    c.create("E2E refusal: moving GPS")
    c.upload(ECOMMERCE)
    c.context(NOTES)
    c.outline(GPS_TEXT)
    messages = c.api("GET", "/messages")
    said = [m["text"] for m in messages if m["role"] == "assistant" and m.get("node") == "outline_other"]
    c.check(said, "assistant explains the unsupported Other text at once", [t[:300] for t in said[-1:]])
    c.design()
    c.blueprint()
    assessment = c.assessment("blueprint")
    if assessment["state"] in ("unchecked", "stale"):
        c.act("POST", "/feasibility/check")
        assessment = c.assessment("blueprint check")
    gps = [i for i in assessment["issues"] if i["status"] == "unsupported_app" and i["resolution"] == "unresolved"
           and re.search(r"gps|animat|route|playback|moving", i["requirement"], re.I)]
    c.check(assessment["state"] == "blocked" and gps, "moving GPS blocks as unsupported_app",
            {"state": assessment["state"], "issues": [i["requirement"] for i in assessment["issues"]]})
    c.out["refusal"] = {"requirement": gps[0]["requirement"], "reason": gps[0]["reason"],
                        "alternatives": [a["label"] for a in gps[0]["alternatives"]]}
    error = c.refused("POST", "/blueprint/accept", 409, {"feasibility_blocked"}, "blueprint accept refused")
    c.check(gps[0]["id"] in (error.get("detail") or {}).get("issue_ids", []), "refusal names the GPS issue",
            error.get("detail"))
    c.refused("POST", "/feasibility/decisions", 409, {"feasibility_stale"}, "a stale assessment id is rejected",
              json={"assessment_id": "assessment_000000000000", "decisions": [
                  {"issue_id": gps[0]["id"], "action": "drop", "alternative_id": None}]})
    c.refused("POST", "/reference-images", 422, {"invalid_source"}, "an unreadable image is rejected",
              data={"mode": "style", "instructions": ""}, files={"files": ("broken.png", b"not an image", "image/png")})
    c.check(c.api("GET", "/reference-images") is None, "the rejected image left no reference set")
    c.refused("POST", "/recipe", 409, {"feasibility_blocked", "wrong_stage", "feasibility_stale"}, "recipe refused")
    c.refused("POST", "/run", 409, {"feasibility_blocked", "wrong_stage", "feasibility_stale"}, "run refused")
    # The view is created only by the prototype node (after accept's preflight); the blueprint
    # holds the name its dry run validated. No prototype, recipe or execute run means no view,
    # spec, recipe or engine side effect.
    build = c.api("GET")
    spec = c.client.get(f"/api/builds/{c.build_id}/spec")
    nodes = sorted({t["node"] for t in c.traces()})
    blueprint = c.api("GET", "/blueprint")
    c.check(build["stage"] == "blueprint" and build["spec_version"] is None and spec.status_code in (404, 409)
            and not SIDE_EFFECT_NODES & set(nodes) and build["versions"][0]["status"] == "draft"
            and not build["report_url"], "no view, spec, prototype, recipe or engine side effect",
            {"stage": build["stage"], "spec_version": build["spec_version"], "spec_status": spec.status_code,
             "nodes": nodes})
    c.out["refusal"]["planned_view"] = blueprint and blueprint["view_table"]


def case_revenue(c: Case, args) -> None:
    c.create("E2E revenue: gross or net")
    c.upload(GROSS_NET)
    context = c.context(REVENUE_NOTES)
    kpi = next((k for k in context["kpis"] if "revenue" in (k["name"] + " " + k["id"]).lower() and k["measure"]), None)
    c.check(kpi and kpi["measure"]["field"] in ("gross_sales", "net_sales"), "context has a Revenue KPI on a sales field",
            [{"id": k["id"], "name": k["name"], "measure": k["measure"]} for k in context["kpis"]])
    chosen = kpi["measure"]["field"]
    other = "gross_sales" if chosen == "net_sales" else "net_sales"
    text = (kpi["description"] + " " + " ".join(t["definition"] for t in context["glossary"]
                                                  if "revenue" in t["term"].lower())).lower()
    # The assumption: it names the field it picked and says why or what it set aside.
    names = chosen in text or chosen.replace("_", " ") in text
    reason = re.search(r"assum|instead|rather than|not (?:the )?(?:gross|net)|(?:after|before) (?:deducting |subtracting "
                       r"|applying )?discount|net of discount|exclud|includ|" + other.split("_")[0], text)
    c.check(names and reason, "Revenue KPI states its assumption", {"field": chosen, "description": kpi["description"]})
    c.out["revenue"] = {"kpi_id": kpi["id"], "assumed_field": chosen, "description": kpi["description"]}
    c.outline()
    c.design()
    before = c.blueprint()
    used = lambda bp: sorted({m["field"] for r in bp["rows"] for m in r["component"]["metrics"]})  # noqa: E731
    c.out["revenue"]["fields_before"] = used(before)
    # The user corrects the definition: Revenue is the other field (PUT edits a later-stage context).
    body = {k: v for k, v in c.api("GET", "/context").items() if k not in ("revision", "issues")}
    for k in body["kpis"]:
        if k["id"] == kpi["id"]:
            k["measure"] = {"field": other, "agg": "sum"}
            k["description"] = f"Revenue is the sum of {other} (the finance team's definition)."
    edited = c.api("PUT", "/context", json=body)
    build = c.api("GET")
    c.check(not edited["issues"] and build["stage"] == "context" and build["artifacts"]["blueprint"] == "stale",
            "KPI edit sets context draft and the blueprint stale", {"stage": build["stage"], "artifacts": build["artifacts"]})
    with c.stage(1, "reconfirm"):
        c.act("POST", "/context/confirm")
        c.api("POST", "/outline/confirm")
        c.act("POST", "/design/confirm")
        c.act("POST", "/blueprint/regenerate")
    after = c.api("GET", "/blueprint")
    fields = used(after)
    c.out["revenue"]["fields_after"] = fields
    revenue_rows = [r for r in after["rows"] if any(kpi["id"] in (q.get("kpi_refs") or []) for q in [
        next((q for s in c.api("GET", "/outline")["sections"] for q in s["questions"] if q["id"] == r["question_id"]), {})])]
    rev_fields = sorted({m["field"] for r in revenue_rows for m in r["component"]["metrics"]})
    c.check(revenue_rows and other in rev_fields and chosen not in rev_fields,
            f"regenerated blueprint uses {other} for Revenue", {"all": fields, "revenue_rows": rev_fields})


def staged_with_reference(c: Case, mode: str, instructions: str) -> tuple[dict, dict]:
    c.create(f"E2E reference: {mode}")
    c.upload(ECOMMERCE)
    c.reference(mode, instructions)
    c.context(REFERENCE_NOTES)
    c.outline()
    design = c.design()
    c.blueprint()
    c.resolve(keep_observations=mode == "recreate")
    return c.prototype(), design


def case_style(c: Case, args) -> None:
    expect = json.loads(EXPECT.read_text(encoding="utf-8"))
    spec, design = staged_with_reference(c, "style", STYLE_TEXT)
    c.bound(spec, columns_of(ECOMMERCE))
    c.themed(spec, design, expect)
    c.compare(spec, expect, require_order=False)
    c.snapshot("prototype")
    # Replacing the reference changes intent: the saved prototype may no longer be built.
    old = c.api("GET", "/reference-images")["id"]
    with c.stage(1, "reference_replace"):
        c.act("POST", "/reference-images", data={"mode": "recreate", "instructions": RECREATE_TEXT},
              files={"files": (REFERENCE_PNG.name, REFERENCE_PNG.read_bytes(), "image/png")})
    new = c.api("GET", "/reference-images")
    c.check(new and new["id"] != old and new["mode"] == "recreate", "replacement is the reference set on reload",
            {"old": old, "new": new and new["id"]})
    a = c.assessment("reference replaced")
    c.check(a["state"] != "ready" or a["prototype_stale"], "replacement invalidates the assessment", a["state"])
    c.refused("POST", "/recipe", 409, {"feasibility_blocked", "feasibility_stale"}, "recipe of the stale prototype refused")
    c.refused("POST", "/run", 409, {"feasibility_blocked", "feasibility_stale"}, "run of the stale prototype refused")
    response = c.client.delete(f"/api/builds/{c.build_id}/reference-images")
    c.check(response.status_code == 204 and c.api("GET", "/reference-images") is None, "reference removed",
            response.status_code)
    c.assessment("reference removed")
    c.refused("POST", "/recipe", 409, {"feasibility_blocked", "feasibility_stale"}, "recipe after removal refused")
    c.refused("POST", "/run", 409, {"feasibility_blocked", "feasibility_stale"}, "run after removal refused")
    # Recovery is explicit (oracle case 10): check, replan, accept; then the new prototype compiles.
    with c.stage(1, "replan"):
        c.act("POST", "/feasibility/check")
        c.act("POST", "/blueprint/regenerate")
    c.resolve()
    c.prototype()
    a = c.assessment("replanned prototype")
    c.check(a["state"] == "ready" and not a["prototype_stale"], "replanned prototype is ready and not stale",
            {"state": a["state"], "prototype_stale": a["prototype_stale"]})
    recipe = c.client.post(f"/api/builds/{c.build_id}/recipe")
    c.check(recipe.status_code == 200 and recipe.json().get("op_count"), "replanned prototype compiles a recipe",
            {"status": recipe.status_code, "error": None if recipe.is_success else recipe.json().get("error")})


@contextmanager
def narrowed_allowlist(server: str, drop: str):
    """Remove one type from DSS_ALLOWED_TYPES in the root .env the local backend reads on each
    check; always restores the file byte for byte. Values are never printed."""
    if httpx.URL(server).host not in LOCAL_HOSTS:
        raise RuntimeError("allowlist: changing DSS_ALLOWED_TYPES needs the server's .env (local server); "
                           "on a hosted server, deploy with the narrowed value and rerun this case")
    path = ROOT / ".env"
    original = path.read_bytes()
    text = original.decode("utf-8-sig")
    pattern = re.compile(r"(?m)^(\s*(?:export\s+)?DSS_ALLOWED_TYPES\s*=\s*)([^\r\n#]*)")
    match = pattern.search(text)
    if not match:
        raise RuntimeError("allowlist: DSS_ALLOWED_TYPES is not set in .env")
    kept = [t for t in match[2].strip().strip("\"'").split(",") if t.strip() and t.strip() != drop]
    path.write_bytes((text[:match.start(2)] + ",".join(kept) + text[match.end(2):]).encode("utf-8"))
    try:
        yield
    finally:
        path.write_bytes(original)


def case_recreate(c: Case, args) -> None:
    expect = json.loads(EXPECT.read_text(encoding="utf-8"))
    spec, design = staged_with_reference(c, "recreate", RECREATE_TEXT)
    c.bound(spec, columns_of(ECOMMERCE))
    c.themed(spec, design, expect)
    c.compare(spec, expect, require_order=True)
    c.snapshot("prototype")
    c.live_build(1)
    v1_id = c.assessment("v1 built")["id"]
    # A new version starts unchecked (no inherited proof): recipe and run wait for an explicit check.
    build = c.request("POST", f"/api/builds/{c.build_id}/versions").json()
    c.check(build["current_version"] == 2, "new version v2", build["current_version"])
    a = c.assessment("v2")
    c.check(a["state"] == "unchecked" and a["id"] != v1_id, "v2 starts unchecked, without v1's proof",
            {"state": a["state"], "id": a["id"]})
    c.refused("POST", "/recipe", 409, {"feasibility_blocked"}, "v2 recipe waits for a check")
    c.refused("POST", "/run", 409, {"feasibility_blocked"}, "v2 run waits for a check")
    with c.stage(2, "check"):
        c.act("POST", "/feasibility/check")
    a = c.assessment("v2 check")
    c.check(a["state"] == "ready" and not a["prototype_stale"] and a["id"] != v1_id, "v2 rechecked ready", a["state"])
    c.request("POST", f"/api/builds/{c.build_id}/recipe")
    ready_id = a["id"]
    # The least-used non-scorecard type: few requirements fail, so the check names the type
    # (over 20 issues collapse into one "reduce the request scope" summary).
    used = [comp["type"] for _, comp in spec_components(c.api("GET", "/spec")) if comp["type"] in CHART_TYPES]
    drop = min(sorted(set(used) - {"scorecard"} or set(used)), key=used.count)
    # The allowlist is part of the assessment digest: a change expires the proof until it matches again.
    # It also re-gates an approved native item of that type (dashboard-intent 1.3: reference_unapproved).
    narrowed = {"feasibility_blocked", "reference_unapproved"}
    with narrowed_allowlist(args.server, drop):
        a = c.assessment(f"allowlist without {drop}")
        c.check(a["state"] != "ready" or a["id"] != ready_id, "allowlist change expires the assessment", a["state"])
        c.refused("POST", "/recipe", 409, narrowed, f"recipe refused once {drop} leaves the allowlist")
        c.refused("POST", "/run", 409, narrowed, f"run refused once {drop} leaves the allowlist")
    a = c.assessment("allowlist restored")
    c.check(a["state"] == "ready" and a["id"] == ready_id, "restored allowlist matches the ready proof again", a["state"])
    recipe = c.request("POST", f"/api/builds/{c.build_id}/recipe").json()
    c.check(recipe["op_count"] > 0, "v2 recipe compiles with the restored allowlist", recipe["op_count"])
    # Last: a check under the narrowed allowlist names the disabled type (it also marks this
    # version's prototype stale, so nothing runs after it).
    with narrowed_allowlist(args.server, drop):
        with c.stage(2, "allowlist_check"):
            c.act("POST", "/feasibility/check")
        a = c.assessment(f"allowlist without {drop}, checked")
    disabled = [i["reason"] for i in a["issues"] if i["status"] == "unsupported_app" and "DSS_ALLOWED_TYPES" in i["reason"]]
    c.check(a["state"] == "blocked" and disabled, f"check blocks {drop} as unsupported_app (DSS_ALLOWED_TYPES)",
            {"state": a["state"], "reasons": [i["reason"] for i in a["issues"]][:5]})
    c.out["allowlist"] = {"dropped": drop, "reason": disabled[0]}


def case_synthetic(c: Case, args) -> None:
    c.create("E2E synthetic: screenshot only")
    ref = c.reference("recreate", SYNTHETIC_TEXT)
    c.check(c.api("GET")["sources"] == [], "no data source before generation")
    with c.stage(1, "synthetic_schema"):
        c.act("POST", "/synthetic-data/proposal", json={"reference_set_id": ref["id"]})
    proposal = c.api("GET", "/synthetic-data/proposal")
    c.check(proposal and proposal["assumptions"] and proposal["reference_set_id"] == ref["id"],
            "schema proposed from the reference", proposal and [col["name"] for col in proposal["spec"]["columns"]])
    spec = json.loads(json.dumps(proposal["spec"]))
    spec.update(row_count=1000, seed=42)
    if len(spec["columns"]) < 40 and all(col["name"] != "sales_channel" for col in spec["columns"]):
        spec["columns"].append({"name": "sales_channel", "type": "string", "nullable_fraction": 0,
                                "generator": {"kind": "choice", "values": ["Online", "Retail"]}})
    key = f"e2e_{uuid.uuid4().hex[:12]}"
    c.refused("POST", "/synthetic-data", 409, {"synthetic_proposal_stale"}, "a stale proposal id is rejected",
              json={"generation_key": key + "_stale", "proposal_id": "proposal_000000000000", "spec": spec})
    body = {"generation_key": key, "proposal_id": proposal["id"], "spec": spec}
    with c.stage(1, "synthetic_generate"):
        run_id = c.act("POST", "/synthetic-data", json=body)
    replay = c.request("POST", f"/api/builds/{c.build_id}/synthetic-data", json=body).json()
    job = c.api("GET", f"/synthetic-data/jobs/{key}")
    c.check(replay["run_id"] == run_id and job["state"] == "succeeded" and job["source_id"],
            "generation succeeded; a replay returns the same run", job)
    c.refused("POST", "/synthetic-data", 409, {"synthetic_request_conflict"}, "the same key with another spec conflicts",
              json={**body, "spec": {**spec, "seed": spec["seed"] + 1}})
    datasets = c.api("GET", "/synthetic-data")
    sources = c.api("GET")["sources"]
    c.check(len(datasets) == 1 and len(sources) == 1, "one dataset and one source after the replay",
            {"datasets": len(datasets), "sources": len(sources)})
    dataset, source = datasets[0], sources[0]
    c.check(any("edit" in a.lower() for a in dataset["assumptions"]), "assumptions note the user's edit",
            dataset["assumptions"])
    c.check(source["kind"] == "synthetic" and source["name"] == SYNTHETIC_LABEL and source["row_count"] == 1000,
            "typed intake: synthetic source with 1,000 rows", {k: source[k] for k in ("kind", "name", "row_count")})
    typed = {col["name"]: col["type"] for col in source["columns"]}
    want = {col["name"]: SPEC_TYPES[col["type"]] for col in spec["columns"]}
    c.check(typed == want, "source columns keep the declared types", {"source": typed, "spec": want})
    raw = c.request("GET", f"/api/builds/{c.build_id}/synthetic-data/{source['id']}/csv").content
    sha = hashlib.sha256(raw).hexdigest()
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"), newline="")))
    c.check(sha == dataset["sha256"] and len(raw) == dataset["bytes"] and b"\r" not in raw
            and rows[0] == [col["name"] for col in spec["columns"]] and len(rows) == 1001,
            "downloaded CSV reparses: header, 1,000 rows, checksum", {"sha256": sha, "rows": len(rows) - 1})
    c.refused("GET", "/synthetic-data/s_000000000000/csv", 404, {"not_found"}, "another source's download is refused")
    c.out["synthetic"] = {"generation_key": key, "source_id": source["id"], "sha256": sha, "bytes": len(raw),
                          "row_count": 1000, "columns": [col["name"] for col in spec["columns"]],
                          "assumptions": dataset["assumptions"], "generator_version": dataset["generator_version"]}
    c.context(None)
    outline = c.outline()
    c.check(any(q["selected"] for s in outline["sections"] for q in s["questions"]), "outline proposed after intake")
    design = c.design()
    c.blueprint()
    c.resolve()
    spec_doc = c.prototype()
    c.bound(spec_doc, {col["name"] for col in spec["columns"]})
    expect = json.loads(EXPECT.read_text(encoding="utf-8"))
    c.themed(spec_doc, design, expect)
    c.compare(spec_doc, expect, require_order=False)  # recorded: the generated fields differ from the CSV's
    html = c.request("GET", f"/api/builds/{c.build_id}/prototype").text
    deco = c.request("GET", f"/api/builds/{c.build_id}/prototype", params={"layer": "decoration"}).text
    c.check(SYNTHETIC_LABEL in html and SYNTHETIC_LABEL in deco, "prototype and its background layer say "
            f"{SYNTHETIC_LABEL!r}")
    c.snapshot("prototype")
    recipe = c.request("POST", f"/api/builds/{c.build_id}/recipe").json()
    c.check(c.api("GET", "/spec")["datasource"]["synthetic"] and any(
        SYNTHETIC_LABEL in op["line"] for op in recipe["ops"]) is False,
        f"recipe places no {SYNTHETIC_LABEL!r} text (the background layer holds the only copy)")
    c.live_build(1)
    # Generated data resolves needs_data, never a capability: moving GPS still refuses (v2, last).
    c.request("POST", f"/api/builds/{c.build_id}/versions")
    sections = c.api("GET", "/outline")["sections"]
    with c.stage(2, "outline_other_gps"):
        c.act("POST", "/outline/other", json={"section_id": sections[-1]["id"], "text": GPS_TEXT})
    a = c.assessment("v2 moving GPS")
    # Refused means blocked and unresolved; a v2 ledger past the outline_other extraction budget
    # classifies it `unknown` rather than unsupported_app (recorded, never a pass to build).
    gps = [i["status"] for i in a["issues"] if i["resolution"] == "unresolved" and i["status"] in (
        "unsupported_app", "unknown") and re.search(r"gps|animat|route|playback|moving", i["requirement"], re.I)]
    c.check(a["state"] == "blocked" and gps, "synthetic data still refuses moving GPS", {"state": a["state"], "status": gps})
    c.out["synthetic"]["gps_refusal_status"] = gps[0]
    c.refused("POST", "/recipe", 409, {"feasibility_blocked", "wrong_stage"}, "v2 recipe refused after the GPS request")


RUNNERS ={"refusal": case_refusal, "revenue": case_revenue, "style": case_style,
           "recreate": case_recreate, "synthetic": case_synthetic}


# --- entry points -----------------------------------------------------------------------------

def render_reference() -> int:
    """samples/reference-dashboard.html -> .png with headless Chrome, as render_diagrams.py does
    (throwaway profile, no network), at device scale 1 so the upload stays small."""
    chrome = find_chrome()
    with tempfile.TemporaryDirectory(prefix="dss-render-", ignore_cleanup_errors=True) as tmp:
        shot = Path(tmp) / "reference.png"  # the committed PNG is replaced only by a good render
        proc = subprocess.run([
            chrome, "--headless", f"--screenshot={shot}",
            f"--window-size={REFERENCE_SIZE[0]},{REFERENCE_SIZE[1]}", "--force-device-scale-factor=1",
            "--hide-scrollbars", "--virtual-time-budget=5000", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions", "--disable-background-networking",
            "--disable-component-update", "--disable-sync", "--font-render-hinting=none",
            f"--user-data-dir={Path(tmp) / 'profile'}", REFERENCE_HTML.as_uri()],
            capture_output=True, text=True, timeout=120)
        if not shot.is_file():
            print(f"FAIL render: Chrome wrote no screenshot (exit {proc.returncode})", file=sys.stderr)
            return 1
        size = png_size(shot)
        if size != REFERENCE_SIZE:
            print(f"FAIL render: {size[0]}x{size[1]}, want {REFERENCE_SIZE[0]}x{REFERENCE_SIZE[1]}", file=sys.stderr)
            return 1
        REFERENCE_PNG.write_bytes(shot.read_bytes())
    print(f"ok   {REFERENCE_PNG.relative_to(ROOT).as_posix()}  {size[0]}x{size[1]}")
    return 0


def bench_path(server: str) -> Path:
    target = "local" if httpx.URL(server).host in LOCAL_HOSTS else "hosted"
    return ROOT / "deck" / "data" / f"bench-references-{target}.json"


def after_restart(flow: Case, server: str) -> int:
    path = bench_path(server)
    bench = json.loads(path.read_text(encoding="utf-8"))
    case = bench["cases"].get("synthetic") or {}
    data = case.get("synthetic")
    if not case.get("passed") or not data:
        print(f"FAIL after-restart: no passed synthetic case in {path.relative_to(ROOT)}", file=sys.stderr)
        return 1
    # The operator restarts the backend (local: ./start.sh again; hosted: a new revision) first;
    # the API exposes no boot id, so the restart itself is the operator's record.
    flow.build_id = case["build_id"]
    job = flow.api("GET", f"/synthetic-data/jobs/{data['generation_key']}")
    sources = [s for s in flow.api("GET")["sources"] if s["id"] == data["source_id"]]
    raw = flow.request("GET", f"/api/builds/{flow.build_id}/synthetic-data/{data['source_id']}/csv").content
    sha = hashlib.sha256(raw).hexdigest()
    ok = (sha == data["sha256"] and job["state"] == "succeeded" and job["source_id"] == data["source_id"]
          and len(sources) == 1 and sources[0]["kind"] == "synthetic")
    bench["restart_check"] = {"checked_at": utc_now(), "build_id": flow.build_id, "sha256": sha,
                              "same_checksum": sha == data["sha256"], "job_state": job["state"],
                              "same_source": job["source_id"] == data["source_id"] and len(sources) == 1,
                              "passed": ok, "git_revision": git_revision()}
    path.write_text(json.dumps(bench, indent=2) + "\n", encoding="utf-8")
    print(f"synthetic CSV after restart: {sha} ({'same' if sha == data['sha256'] else 'DIFFERENT'} checksum), "
          f"job {job['state']}, source {'kept' if bench['restart_check']['same_source'] else 'CHANGED'}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", default="http://localhost:8000")
    parser.add_argument("--live", action="store_true", help="real engine builds (required for the bench)")
    parser.add_argument("--cases", default=",".join(CASES), help="comma-separated subset of " + ", ".join(CASES))
    parser.add_argument("--after-restart", action="store_true",
                        help="download the recorded synthetic CSV again and compare its checksum")
    parser.add_argument("--render-reference", action="store_true", help="re-render samples/reference-dashboard.png")
    args = parser.parse_args()
    if args.render_reference:
        return render_reference()
    cases = [n.strip() for n in args.cases.split(",") if n.strip()]
    if not set(cases) <= set(CASES):
        parser.error(f"--cases takes {', '.join(CASES)}")
    args.server = args.server.rstrip("/")
    url = httpx.URL(args.server)
    if url.scheme not in {"http", "https"} or not url.host or url.userinfo or url.query or url.fragment or url.path not in {"", "/"}:
        parser.error("--server must be an http(s) origin without credentials, query or fragment")
    if not args.after_restart and not args.live:
        parser.error("--live is required: dry-run engine builds are not evidence of a recreation")
    if args.live and url.host in LOCAL_HOSTS and env_value("DSS_ENGINE_DRY_RUN", "0") == "1":
        parser.error("--live needs DSS_ENGINE_DRY_RUN=0 in .env (restart the backend after changing it)")
    access_code = env_value("DSS_ACCESS_CODE")
    secrets = [access_code, env_value("GOOGLE_API_KEY"), env_value("DSS_AGENT_TOKEN")]
    with httpx.Client(base_url=args.server, timeout=120, trust_env=False,
                      headers={"X-DSS-Access-Code": access_code} if access_code else {}) as client:
        if args.after_restart:
            try:
                return after_restart(Case(client, secrets, False, "synthetic"), args.server)
            except (RuntimeError, httpx.HTTPError, OSError, KeyError, ValueError) as exc:
                print(Flow(client, secrets).redact(f"FAIL after-restart: {exc}"), file=sys.stderr)
                return 1
        path = bench_path(args.server)
        bench = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"cases": {}}
        revision = git_revision()
        bench.update(run_date=utc_now(), server_url=args.server, git_revision=revision, live=True)
        try:
            Flow(client, secrets).request("GET", "/api/health")
            bench["engine"] = client.get("/api/engine/status").json()
        except (RuntimeError, httpx.HTTPError, ValueError) as exc:
            print(f"FAIL preflight: {exc}", file=sys.stderr)
            return 1
        failed = []
        for name in cases:
            case = Case(client, secrets, True, name)
            case.out["git_revision"] = revision  # cases merge across runs: each keeps its own revision
            try:
                RUNNERS[name](case, args)
                case.out["passed"] = True
            except (RuntimeError, httpx.HTTPError, OSError, KeyError, ValueError, TypeError, IndexError) as exc:
                case.out["error"] = case.redact(f"{type(exc).__name__}: {exc}")[:2000]
                print(f"FAIL {name} ({case.build_id or 'preflight'}): {case.out['error']}", file=sys.stderr)
                failed.append(name)
            try:
                bench["cases"][name] = case.finish()
            except (RuntimeError, httpx.HTTPError) as exc:
                case.out["finish_error"] = str(exc)[:300]
                bench["cases"][name] = case.out
            bench.pop("restart_check", None) if name == "synthetic" else None
            bench["all_passed"] = all(bench["cases"].get(n, {}).get("passed") for n in CASES)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(bench, indent=2) + "\n", encoding="utf-8")
        print("\nCase       Passed  Seconds   Build")
        for name in cases:
            out = bench["cases"][name]
            print(f"{name:10} {'yes' if out['passed'] else 'NO':6} {out['seconds']:8.1f}   {out['build_id']}")
        print(f"Benchmark: {path.relative_to(ROOT).as_posix()}")
        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
