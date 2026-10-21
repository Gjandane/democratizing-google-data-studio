"""Exercise CSV -> staged artifacts (context, outline, design, blueprint) -> prototype -> comments -> recipe -> engine, optionally twice.

The engine mode is configured on the server. --mode labels the benchmark; it
does not turn a live server into a dry-run server. --live labels it live, refuses a
.env with DSS_ENGINE_DRY_RUN=1 and requires each published version's Data Studio link.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from urllib.parse import urlsplit
import os
from pathlib import Path
import re
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
REPORT_HOSTS = {"datastudio.google.com", "lookerstudio.google.com"}
NOTES = ("The sales director reviews net revenue weekly by region and category. Revenue is the revenue "
         "column; sum revenue and quantity; count distinct order_id for orders.")
OTHER = "Which product categories sell the most units?"
CHART_TYPES = ("bar", "time_series", "pie", "scatter")
COMPONENT_TEXT = "Use #B91C1C as the color of this chart."
DECORATION_TEXT = "Use a dark blue accent (#1E3A8A) for this component."
V2_TEXT = "Use #0F766E as the color of this chart."


def env_value(name: str, default: str = "") -> str:
    if name in os.environ:
        return os.environ[name]
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            match = re.match(r"\s*(?:export\s+)?" + re.escape(name) + r"\s*=\s*(.*)", line)
            if match:
                value = match[1].strip()
                if value.startswith(('"', "'")):
                    end = value.find(value[0], 1)
                    return value[1:end] if end >= 1 else value[1:]
                return re.split(r"\s+#", value, maxsplit=1)[0].strip()
    return default


def dumps(value) -> str:
    return json.dumps(value)


def items_of(spec: dict) -> dict[str, dict]:
    return {item["id"]: item for page in spec["pages"]
            for item in page.get("components", []) + page.get("decorations", [])}


def components_of(spec: dict) -> list[dict]:
    return [c for page in spec["pages"] for c in page.get("components", [])]


def chart_candidates(spec: dict) -> list[dict]:
    comps = components_of(spec)
    return [c for c in comps if c.get("type") in CHART_TYPES] or comps


class Flow:
    def __init__(self, client: httpx.Client, secrets: list[str], live: bool = False) -> None:
        self.client = client
        self.live = live
        self.reports: dict[int, str] = {}
        self.secrets = [s for s in secrets if s]
        self.build_id = ""
        self.rows: list[dict] = []
        self.decisions: list[dict] = []
        self._run_ids: list[str] = []

    def redact(self, value: str) -> str:
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")
        return value

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = self.client.request(method, path, **kwargs)
        if not response.is_success:
            raise RuntimeError(self.redact(
                f"backend: {method} {path}: HTTP {response.status_code}: {response.text}"
            ))
        return response

    def api(self, method: str, suffix: str = "", **kwargs):
        return self.request(method, f"/api/builds/{self.build_id}{suffix}", **kwargs).json()

    def traces(self) -> list[dict]:
        return self.request("GET", "/api/traces", params={"build_id": self.build_id}).json()

    def run(self, path: str, json=None) -> str:
        """POST a model run, wait for its single trace, return the run id."""
        url = f"/api/builds/{self.build_id}{path}"
        for attempt in range(4):
            response = self.client.request("POST", url, json=json)
            if response.status_code == 409 and "wrong_stage" in response.text and attempt < 3:
                time.sleep(1)  # the per-build lock is released a moment after the trace
                continue
            break
        if response.status_code != 202:
            raise RuntimeError(self.redact(
                f"backend: POST {url}: HTTP {response.status_code}: {response.text}"))
        run_id = response.json().get("run_id")
        if not run_id:
            raise RuntimeError(f"backend: POST {url}: no run_id in 202 response")
        self._run_ids.append(run_id)
        deadline = time.monotonic() + 600
        while True:
            trace = next((t for t in self.traces() if t["run_id"] == run_id), None)
            if trace:
                if trace["status"] == "error":
                    raise RuntimeError(self.redact(f"backend: {path}: " + dumps(trace)))
                return run_id
            if time.monotonic() >= deadline:
                stage = self.api("GET")["stage"]
                raise RuntimeError(f"backend: {path} timed out after 600 s; stage={stage}")
            time.sleep(2)

    @contextmanager
    def stage(self, version: int, label: str):
        started = time.monotonic()
        row = {"version": version, "stage": label, "seconds": 0.0, "run_ids": []}
        self.rows.append(row)
        self._run_ids = row["run_ids"]
        yield row
        row["seconds"] = round(time.monotonic() - started, 3)
        print(f"v{version}: {label} reached ({row['seconds']:.3f} s)", flush=True)

    def comment(self, text: str, target: str) -> bool:
        """One comment run; True when spec_version went up and the target item changed."""
        before_v = self.api("GET")["spec_version"]
        before = items_of(self.api("GET", "/spec")).get(target)
        self.run("/comments", {"comments": [{"component_id": target, "text": text}]})
        after_v = self.api("GET")["spec_version"]
        after = items_of(self.api("GET", "/spec")).get(target)
        return (after_v or 0) > (before_v or 0) and after != before

    def comment_checked(self, text: str, target: str) -> None:
        if not self.comment(text, target):
            raise RuntimeError(f"backend: comment on {target} did not change the spec")

    def recipe_and_run(self, version: int) -> None:
        with self.stage(version, "recipe"):
            recipe = self.request("POST", f"/api/builds/{self.build_id}/recipe").json()
            if not recipe.get("op_count") or len(recipe.get("ops", [])) != recipe["op_count"]:
                raise RuntimeError("backend: recipe is empty or op_count does not match ops")
        with self.stage(version, "run") as row:
            result = self.request("POST", f"/api/builds/{self.build_id}/run").json()
            run_id = result.get("run_id")
            if run_id:
                row["run_ids"].append(run_id)
            deadline = time.monotonic() + 600
            while True:
                build = self.api("GET")
                current = next(v for v in build["versions"] if v["n"] == version)
                if current["status"] == "failed":
                    raise RuntimeError(self.redact(f"backend: v{version} engine failed: {dumps(current)}"))
                errors = [t for t in self.traces()
                          if run_id and t["run_id"] == run_id and t["status"] == "error"]
                if errors:
                    raise RuntimeError(self.redact(f"backend: v{version} run: " + dumps(errors)))
                if build["stage"] == "done" and current["status"] == "published":
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"backend: v{version} run timed out after 600 s; stage={build['stage']}")
                time.sleep(2)
        report_url = current.get("report_url") or ""
        parts = urlsplit(report_url)
        if parts.scheme == "https" and parts.hostname in REPORT_HOSTS:
            self.reports[version] = report_url
            print(f"v{version}: report {report_url}", flush=True)
        elif self.live:
            raise RuntimeError(f"backend: v{version} published without a Data Studio report_url: {report_url!r}")

    def stage_context(self) -> None:
        with self.stage(1, "context"):
            self.run("/context", {"notes": NOTES})
            context = self.api("GET", "/context")
            if context.get("issues"):
                raise RuntimeError(f"backend: drafted context has issues: {dumps(context['issues'])}")

    def stage_outline(self) -> None:
        with self.stage(1, "outline"):
            self.run("/context/confirm")  # confirmed unedited; proposes the outline
            sections = self.api("GET", "/outline")["sections"]
            if not sections:
                raise RuntimeError("backend: outline has no sections")
            self.run("/outline/other", {"section_id": sections[-1]["id"], "text": OTHER})
            outline = self.api("GET", "/outline")
            questions = [q for s in outline["sections"] for q in s["questions"]]
            outline = self.api("PUT", "/outline/selection", json={"questions": [
                {"id": q["id"], "selected": bool(q.get("recommended")) or q.get("origin") == "other"}
                for q in questions]})
            questions = [q for s in outline["sections"] for q in s["questions"]]
            if not any(q["selected"] and q.get("origin") == "other" for q in questions):
                raise RuntimeError("backend: no selected question with origin other")
            if not all(q["selected"] for q in questions if q.get("recommended")):
                raise RuntimeError("backend: a recommended question is not selected")

    def stage_design(self, archetype: str) -> None:
        with self.stage(1, "design"):
            self.api("POST", "/outline/confirm")
            preset = next((p for p in self.api("GET", "/design/presets")
                           if archetype in p["archetypes"]), None)
            if preset is None:
                raise RuntimeError(f"backend: no design preset for archetype {archetype}")
            design = self.api("GET", "/design")
            if design.get("preset_id") != preset["id"] or design.get("page_structure") != "per_section":
                body = {k: v for k, v in design.items() if k not in ("revision", "issues")}
                for key in ("background", "surface", "text", "accent", "palette", "font_family"):
                    body[key] = preset[key]
                body.update(preset_id=preset["id"], source="preset", page_structure="per_section")
                self.api("PUT", "/design", json=body)
                design = self.api("GET", "/design")
            if design.get("issues") or design.get("page_structure") != "per_section":
                raise RuntimeError(f"backend: design not ready: {dumps(design.get('issues'))}")

    def stage_blueprint(self) -> None:
        with self.stage(1, "blueprint"):
            self.run("/design/confirm")
            assessment = self.api("GET", "/feasibility")
            if assessment["state"] in ("unchecked", "stale"):
                self.run("/feasibility/check")
                assessment = self.api("GET", "/feasibility")
            while assessment["state"] == "blocked":
                if len(self.decisions) >= 20:
                    raise RuntimeError("backend: feasibility still blocked after 20 decisions")
                issue = next((i for i in assessment["issues"] if i.get("resolution") == "unresolved"), None)
                if issue is None:
                    raise RuntimeError("backend: feasibility blocked without an unresolved issue")
                # Take the offered alternative; a row the code offers none for (e.g. a question
                # whose KPIs the drafted row covers only in part) is dropped, the user's other choice.
                alt = (issue.get("alternatives") or [None])[0]
                assessment = self.api("POST", "/feasibility/decisions", json={
                    "assessment_id": assessment["id"],
                    "decisions": [{"issue_id": issue["id"],
                                   "action": "accept_alternative" if alt else "drop",
                                   "alternative_id": alt["id"] if alt else None}]})
                self.decisions.append({"issue_id": issue["id"], "requirement": issue.get("requirement"),
                                       "action": "accept_alternative" if alt else "drop",
                                       "alternative": alt.get("label") if alt else None,
                                       "reason": issue.get("reason")})
            if assessment["state"] != "ready":
                raise RuntimeError(f"backend: feasibility state is {assessment['state']}, expected ready")

    def stage_prototype(self) -> None:
        with self.stage(1, "prototype"):
            self.run("/blueprint/accept")
            build = self.api("GET")
            if build["stage"] != "prototype":
                raise RuntimeError(f"backend: stage is {build['stage']} after blueprint accept")
            artifacts = build.get("artifacts") or {}
            if len(artifacts) != 4 or any(s != "confirmed" for s in artifacts.values()):
                raise RuntimeError(f"backend: artifacts not all confirmed: {dumps(artifacts)}")
            if not self.api("GET", "/spec")["pages"]:
                raise RuntimeError("backend: spec has no pages")

    def stage_comments(self) -> None:
        with self.stage(1, "comments") as row:
            spec = self.api("GET", "/spec")
            charts = chart_candidates(spec)
            if not charts:
                raise RuntimeError("backend: spec has no component to comment on")
            decorations = [d for p in spec["pages"] for d in p.get("decorations", [])]
            deco = next((d for kind in ("band", "panel", "title")
                         for d in decorations if d.get("kind") == kind), None)
            if deco is None:
                raise RuntimeError("backend: spec has no band, panel or title decoration")
            self.comment_checked(COMPONENT_TEXT, next(
                (c for c in components_of(spec) if c.get("type") in CHART_TYPES), charts[0])["id"])
            self.comment_checked(DECORATION_TEXT, deco["id"])
            row["changed"] = True

    def stage_v2(self) -> None:
        build = self.request("POST", f"/api/builds/{self.build_id}/versions").json()
        if build["current_version"] != 2 or build["stage"] != "prototype":
            raise RuntimeError("backend: new version did not enter v2 prototype")
        with self.stage(2, "comment") as row:
            charts = chart_candidates(self.api("GET", "/spec"))
            if not charts:
                raise RuntimeError("backend: v2 spec has no component to comment on")
            row["changed"] = self.comment(V2_TEXT, charts[-1]["id"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://localhost:8000")
    parser.add_argument("--version2", action="store_true")
    parser.add_argument("--mode", choices=["dry-run", "live"],
                        default="dry-run" if env_value("DSS_ENGINE_DRY_RUN", "0") == "1" else "live")
    parser.add_argument("--live", action="store_true",
                        help="real engine: same as --mode live, plus a Data Studio link per version")
    args = parser.parse_args()
    if args.live:
        if env_value("DSS_ENGINE_DRY_RUN", "0") == "1":
            parser.error("--live needs DSS_ENGINE_DRY_RUN=0 in .env (restart the backend after changing it)")
        args.mode = "live"
    server = args.server.rstrip("/")
    url = httpx.URL(server)
    if url.scheme not in {"http", "https"} or not url.host or url.userinfo or url.query or url.fragment or url.path not in {"", "/"}:
        parser.error("--server must be an http(s) origin without credentials, query or fragment")
    access_code = env_value("DSS_ACCESS_CODE")
    secrets = [access_code, env_value("GOOGLE_API_KEY"), env_value("DSS_AGENT_TOKEN")]
    started = datetime.now(timezone.utc)
    with httpx.Client(base_url=server, timeout=120, trust_env=False,
                      headers={"X-DSS-Access-Code": access_code} if access_code else {}) as client:
        flow = Flow(client, secrets, live=args.live)
        try:
            flow.request("GET", "/api/health")
            build = flow.request("POST", "/api/builds", json={
                "title": "E2E ecommerce sales", "archetype": "executive", "mode": "data",
            }).json()
            flow.build_id = build["id"]
            print(f"v1: connect reached ({flow.build_id})", flush=True)
            with (ROOT / "samples/ecommerce_sales.csv").open("rb") as sample:
                flow.request("POST", f"/api/builds/{flow.build_id}/sources/upload",
                             files={"files": ("ecommerce_sales.csv", sample, "text/csv")})
            flow.stage_context()
            flow.stage_outline()
            flow.stage_design("executive")
            flow.stage_blueprint()
            flow.stage_prototype()
            flow.stage_comments()
            flow.recipe_and_run(1)
            if args.version2:
                flow.stage_v2()
                flow.recipe_and_run(2)
            traces = flow.traces()
            totals = {"input_tokens": 0, "output_tokens": 0}
            for row in flow.rows:
                ids = set(row["run_ids"])
                for key in totals:
                    row[key] = sum(t[key] for t in traces if t["run_id"] in ids)
                    totals[key] += row[key]
            bench = {"run_date": started.isoformat().replace("+00:00", "Z"),
                     "server_url": server, "mode": args.mode, "build_id": flow.build_id,
                     "version2": args.version2, "stages": flow.rows, "totals": totals,
                     "decisions": flow.decisions,
                     "report_urls": {str(n): u for n, u in flow.reports.items()}}
            target = ROOT / "deck/data" / f"bench-{started:%Y-%m-%d}-{args.mode}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(bench, indent=2) + "\n", encoding="utf-8")
            print("\nVersion  Stage                    Seconds    Input tokens  Output tokens  Spec changed")
            for row in flow.rows:
                changed = {True: "yes", False: "no"}.get(row.get("changed"), "-")
                print(f"{row['version']:7}  {row['stage']:24} {row['seconds']:8.3f} {row['input_tokens']:15} {row['output_tokens']:14}  {changed}")
            print(f"TOTAL tokens: input={totals['input_tokens']} output={totals['output_tokens']}")
            print(f"Benchmark: {target.relative_to(ROOT)}")
            return 0
        except (RuntimeError, httpx.HTTPError, OSError, KeyError, ValueError) as exc:
            print(flow.redact(f"FAIL ({flow.build_id or 'preflight'}): {exc}"), file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
