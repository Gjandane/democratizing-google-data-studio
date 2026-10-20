"""Exercise CSV -> interview -> prototype -> recipe -> engine, optionally twice.

The engine mode is configured on the server. --mode labels the benchmark; it
does not turn a live server into a dry-run server.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]


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


class Components(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("data-cid"):
            self.items.append((values["data-cid"], values.get("data-kind") or "", values.get("data-label") or ""))

    def target(self, version: int) -> str:
        # The accent comment needs a data component ("preserve its data"). v1 takes the revenue
        # trend the interview asked for, as in backend 14.2's live regression; v2 takes the last
        # other component, so the repeated comment is a real change.
        components = [item for item in self.items if item[1] == "component"]
        trends = [item for item in components if re.search(r"trend", item[2], re.I)]
        ordered = trends + [item for item in reversed(components) if item not in trends]
        if not ordered:
            raise RuntimeError("backend: prototype contains no commentable data component")
        return ordered[(version - 1) % len(ordered)][0]


class Flow:
    def __init__(self, client: httpx.Client, secrets: list[str]) -> None:
        self.client = client
        self.secrets = [s for s in secrets if s]
        self.build_id = ""
        self.rows: list[dict] = []
        self.run_ids: set[str] = set()

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

    def traces(self) -> list[dict]:
        return self.request("GET", "/api/traces", params={"build_id": self.build_id}).json()

    def action(self, version: int, label: str, method: str, suffix: str,
               *, until=None, **kwargs):
        started = time.monotonic()
        path = f"/api/builds/{self.build_id}{suffix}"
        result = self.request(method, path, **kwargs).json()
        run_id = result.get("run_id")
        if run_id:
            self.run_ids.add(run_id)
        if until:
            deadline = time.monotonic() + 600
            while True:
                build = self.request("GET", f"/api/builds/{self.build_id}").json()
                traces = self.traces()
                errors = [t for t in traces if t["run_id"] == run_id and t["status"] == "error"]
                if errors:
                    raise RuntimeError(self.redact(f"backend: v{version} {label}: " + json.dumps(errors)))
                if until(build, traces, run_id):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"backend: v{version} {label} timed out after 600 s; stage={build['stage']}")
                time.sleep(2)
        seconds = round(time.monotonic() - started, 3)
        self.rows.append({"version": version, "stage": label, "seconds": seconds, "run_id": run_id})
        print(f"v{version}: {label} reached ({seconds:.3f} s)", flush=True)
        return result

    def interview_done(self, previous: set[str]):
        def done(build, traces, run_id):
            messages = self.request("GET", f"/api/builds/{self.build_id}/messages").json()
            return any(m["role"] == "assistant" and m["id"] not in previous for m in messages)
        return done

    def interview(self, label: str, suffix: str, **kwargs) -> None:
        messages = self.request("GET", f"/api/builds/{self.build_id}/messages").json()
        self.action(1, label, "POST", suffix,
                    until=self.interview_done({m["id"] for m in messages}), **kwargs)

    def revise_and_run(self, version: int) -> None:
        previous = self.request("GET", f"/api/builds/{self.build_id}").json()["spec_version"]
        parser = Components()
        parser.feed(self.request("GET", f"/api/builds/{self.build_id}/prototype").text)
        # Wait for the revise run itself: a comment the spec already satisfies keeps spec_version.
        self.action(version, "comment", "POST", "/comments", json={"comments": [{
            "component_id": parser.target(version),
            "text": "Use a dark blue accent for this component; preserve its position and data.",
        }]}, until=lambda b, t, r: b["stage"] == "prototype" and any(
            x["run_id"] == r and x["node"] == "revise" and x["status"] == "ok" for x in t))
        current = self.request("GET", f"/api/builds/{self.build_id}").json()["spec_version"]
        self.rows[-1]["changed"] = current > previous
        recipe = self.action(version, "recipe", "POST", "/recipe")
        if not recipe.get("op_count") or len(recipe.get("ops", [])) != recipe["op_count"]:
            raise RuntimeError("backend: recipe is empty or op_count does not match ops")

        def finished(build, traces, run_id):
            current = next(v for v in build["versions"] if v["n"] == version)
            if current["status"] == "failed":
                raise RuntimeError(f"backend: v{version} engine failed: {json.dumps(current)}")
            return build["stage"] == "done" and current["status"] == "published"

        self.action(version, "run", "POST", "/run", until=finished)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://localhost:8000")
    parser.add_argument("--version2", action="store_true")
    parser.add_argument("--mode", choices=["dry-run", "live"],
                        default="dry-run" if env_value("DSS_ENGINE_DRY_RUN", "0") == "1" else "live")
    args = parser.parse_args()
    server = args.server.rstrip("/")
    url = httpx.URL(server)
    if url.scheme not in {"http", "https"} or not url.host or url.userinfo or url.query or url.fragment or url.path not in {"", "/"}:
        parser.error("--server must be an http(s) origin without credentials, query or fragment")
    access_code = env_value("DSS_ACCESS_CODE")
    secrets = [access_code, env_value("GOOGLE_API_KEY"), env_value("DSS_AGENT_TOKEN")]
    started = datetime.now(timezone.utc)
    with httpx.Client(base_url=server, timeout=120, trust_env=False,
                      headers={"X-DSS-Access-Code": access_code} if access_code else {}) as client:
        flow = Flow(client, secrets)
        try:
            flow.request("GET", "/api/health")
            build = flow.request("POST", "/api/builds", json={
                "title": "E2E ecommerce sales", "archetype": "executive", "mode": "data",
            }).json()
            flow.build_id = build["id"]
            print(f"v1: connect reached ({flow.build_id})", flush=True)
            with (ROOT / "samples/ecommerce_sales.csv").open("rb") as sample:
                flow.action(1, "upload", "POST", "/sources/upload",
                            files={"files": ("ecommerce_sales.csv", sample, "text/csv")})
            flow.interview("interview start", "/interview/start")
            for n, answer in enumerate([
                "The audience is sales executives. Track total revenue, order count, quantity sold and sales trends using only the uploaded columns.",
                "Compare regions and product categories over the full available date range; revenue is SUM(revenue), order count is COUNT(DISTINCT order_id), and quantity sold is SUM(quantity).",
                "Use one executive overview page with KPI scorecards, a revenue trend grouped by order_date at monthly grain, and revenue by region. Use a clean blue theme; proceed with these choices.",
            ], 1):
                flow.interview(f"interview answer {n}", "/messages", json={"text": answer})
            flow.action(1, "plan/prototype", "POST", "/plan",
                        until=lambda b, t, r: b["stage"] == "prototype" and b["spec_version"] is not None)
            flow.revise_and_run(1)
            if args.version2:
                version = flow.action(2, "new version", "POST", "/versions")
                if version["current_version"] != 2 or version["stage"] != "prototype":
                    raise RuntimeError("backend: new version did not enter v2 prototype")
                flow.revise_and_run(2)
            if not any(row.get("changed") for row in flow.rows):
                raise RuntimeError("backend: no comment changed the spec (every revise answered no change)")
            traces = flow.traces()
            # Keep only this invocation's action runs (including their child node traces).
            traces = [t for t in traces if t["run_id"] in flow.run_ids]
            totals = {key: sum(t[key] for t in traces) for key in ("input_tokens", "output_tokens")}
            for row in flow.rows:
                for key in totals:
                    row[key] = sum(t[key] for t in traces if t["run_id"] == row["run_id"])
            bench = {"run_date": started.isoformat().replace("+00:00", "Z"),
                     "server_url": server, "mode": args.mode, "build_id": flow.build_id,
                     "version2": args.version2, "stages": flow.rows, "totals": totals}
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
