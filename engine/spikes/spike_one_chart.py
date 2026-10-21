"""Live task 1.3 spike: creates a new report and leaves its saved view open."""
from contextlib import contextmanager
import json
import os
import re
import struct
import sys
import time
import zlib
from dotenv import load_dotenv
from playwright.sync_api import expect
import yaml
from dsengine.chrome import ChromeConfig, attached, ensure_browser, _has_google_session
from dsengine.linking import build_url
from dsengine.recipe import ENGINE_ROOT, Header


def load_selectors():
    selectors = {}
    for source in (ENGINE_ROOT / "knowledge/datastudio-ui").glob("*.md"):
        content = source.read_text(encoding="utf-8")
        if content.startswith("---"):
            frontmatter = yaml.safe_load(content.split("---", 2)[1]) or {}
            assert frontmatter["type"] == "UI Selector Set", source.name
            selectors.update(frontmatter.get("selectors", {}))
    return selectors


def background_png(path):
    """Deterministic upload fixture made with stdlib only."""
    def chunk(kind, data):
        return (struct.pack("!I", len(data)) + kind + data
                + struct.pack("!I", zlib.crc32(kind + data)))
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 1200, 900, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\xe8\xef\xf7" * 1200) * 900))
        + chunk(b"IEND", b""))


def geometry(component):
    return component.evaluate("e => [e.offsetLeft, e.offsetTop, e.offsetWidth, e.offsetHeight]")


def drag(page, start, end):
    page.mouse.move(*start)
    page.mouse.down()
    # Cross CDK's drag activation threshold before moving to the target.
    page.mouse.move(start[0] + 10, start[1] + 10, steps=2)
    page.mouse.move(*end, steps=12)
    page.mouse.up()


def place(page, component, target, image=False):
    x, y, w, h = geometry(component)
    rect = component.bounding_box()
    offset = (w / 2, h / 2) if image else (10, 10)
    start = (rect["x"] + offset[0], rect["y"] + offset[1])
    page.mouse.click(*start)
    if (x, y) != tuple(target[:2]):
        drag(page, start, (start[0] + target[0] - x, start[1] + target[1] - y))
    rect = component.bounding_box()
    if (w, h) != tuple(target[2:]):
        drag(page, (rect["x"] + rect["width"], rect["y"] + rect["height"]),
             (rect["x"] + target[2], rect["y"] + target[3]))
    expect(component).to_have_js_property("offsetLeft", target[0], timeout=20000)
    actual = geometry(component)
    errors = [abs(a - b) for a, b in zip(actual, target)]
    assert max(errors) <= 4, f"Geometry mismatch: {actual}; expected {target}"
    return {"target": target, "actual": actual, "error_px": errors}


def main():
    load_dotenv(ENGINE_ROOT.parent / ".env")
    table = os.environ.get("DSS_TEST_TABLE", "bigquery-public-data.thelook_ecommerce.order_items")
    project, dataset, name = table.split(".")
    header = Header(recipe_version="1.0", build_id="b_000000000001", version=1,
        report_name="Engine spike one chart", canvas={"width": 1200, "height": 900},
        datasource={"connector": "bigQuery", "project_id": project,
                    "dataset_id": dataset, "table_id": name})
    url = build_url(header)
    selectors = load_selectors()
    output = ENGINE_ROOT / "spikes/screens"
    output.mkdir(parents=True, exist_ok=True)
    evidence = {"template_configured": bool(os.environ.get("DSS_TEMPLATE_REPORT_ID")),
                "timings_s": {}, "geometry_method": "mouse drag at 100% editor zoom"}

    @contextmanager
    def step(label):
        started = time.monotonic()
        try:
            yield
        finally:
            elapsed = round(time.monotonic() - started, 3)
            evidence["timings_s"][label] = elapsed
            print(f"{label}: {elapsed:.3f}s", file=sys.stderr, flush=True)

    config = ChromeConfig.from_env()
    ensure_browser(config)
    with attached(config) as context:
        page = context.new_page()
        page.set_default_timeout(20000)
        page.set_viewport_size({"width": 1920, "height": 1200})
        locate = lambda key: page.locator(selectors[key])

        def accept_review(dialog, button_key):
            # The risk checkbox is optional since 2026-10-21; never click Close.
            accept = dialog.locator(selectors["review_accept"])
            if accept.count() and accept.is_visible() and not accept.is_checked():
                accept.check()
            dialog.locator(selectors[button_key]).click()
            dialog.wait_for(state="hidden")
        try:
            with step("open_report"):
                evidence["signed_in_at_start"] = _has_google_session(context)
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                review = locate("review_dialog")
                review.wait_for()
                accept_review(review, "review_acknowledge")
                locate("add_chart").wait_for()
                locate("status_field").wait_for()
                assert not locate("linking_error").is_visible(), "Linking API creation failed"
            with step("set_zoom"):
                locate("zoom_menu").click()
                locate("zoom_100").click()
                expect(locate("canvas")).to_have_js_property("offsetWidth", 1200)
                assert abs(locate("canvas").bounding_box()["width"] - 1200) < 1
            with step("add_bar_chart"):
                locate("add_chart").click()
                locate("bar_chart").click()
                locate("drawing").wait_for()
                rect = locate("canvas").bounding_box()
                page.mouse.click(rect["x"] + 142, rect["y"] + 284)
                expect(locate("chart_component")).to_have_count(1)
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if locate("consent_dialog").is_visible():
                        locate("consent_allow").click()
                    if locate("dimension_group").is_visible() and not locate("consent_dialog").is_visible():
                        break
                    page.wait_for_timeout(200)
                locate("setup_tab").click()
                expect(locate("dimension_group").locator(selectors["status_field"])).to_be_visible()
                expect(locate("metric_group").locator(selectors["count_field"])).to_be_visible()
                expect(page.frame_locator(selectors["chart_frame"]).locator(selectors["document"])).to_contain_text("Record Count", timeout=20000)
                evidence["fields"] = {"dimension": "status", "metric": "Record Count"}
            with step("place_chart"):
                evidence["chart_box"] = place(page, locate("chart_component"), [24, 120, 560, 300])
            with step("upload_background"):
                image_path = output / "background.png"
                background_png(image_path)
                locate("image").click()
                with page.expect_file_chooser() as choice:
                    locate("upload_image").click()
                choice.value.set_files(str(image_path))
                expect(locate("image_component")).to_have_count(1, timeout=20000)
                expect(locate("image_content")).to_have_js_property("naturalWidth", 1200, timeout=20000)
            with step("place_background"):
                evidence["background_box"] = place(page, locate("image_component"), [0, 0, 1200, 900], image=True)
            with step("send_background_to_back"):
                locate("arrange").click()
                locate("order").hover()
                locate("send_back").click()
                expect(locate("components").first.locator(selectors["image_content"])).to_have_count(1)
                evidence["background_first_in_paint_order"] = True
            with step("save_report"):
                locate("save_share").click()
                review = locate("review_save_dialog")
                review.wait_for()
                accept_review(review, "acknowledge_save")
                page.wait_for_url(re.compile(r"https://(?:data|looker)studio\.google\.com/reporting/(?!create)[^/]+/.*"), timeout=20000)
                locate("view").wait_for()
                evidence["explicit_save_required"] = True
                evidence["report_url"] = page.url.removesuffix("/edit")
            with step("saved_screenshot"):
                expect(page.frame_locator(selectors["chart_frame"]).locator(selectors["document"])).to_contain_text("Record Count", timeout=20000)
                page.keyboard.press("Escape")
                rect = locate("canvas").bounding_box()
                page.mouse.click(rect["x"] - 15, rect["y"] + 50)
                page.screenshot(path=str(output / "report.png"), full_page=True)
            with step("verify_saved_view"):
                locate("view").click()
                page.wait_for_url(evidence["report_url"], timeout=20000)
                page.reload(wait_until="domcontentloaded", timeout=20000)
                expect(locate("components")).to_have_count(2)
                assert geometry(locate("chart_component")) == [24, 120, 560, 300]
                assert geometry(locate("image_component")) == [0, 0, 1200, 900]
                expect(locate("image_content")).to_have_js_property("naturalWidth", 1200, timeout=20000)
                expect(page.frame_locator(selectors["chart_frame"]).locator(selectors["document"])).to_contain_text("Record Count", timeout=20000)
                page.screenshot(path=str(output / "saved_view.png"), full_page=True)
                evidence["saved_view_verified"] = True
                evidence["signed_in_at_end"] = _has_google_session(context)
            (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            print(evidence["report_url"], flush=True)
            return 0
        except Exception as error:
            # Tracebacks can include source URLs or account data; keep diagnostics local.
            evidence["failure_type"] = type(error).__name__
            page.screenshot(path=str(output / "failed.png"), full_page=True)
            (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            print(f"Spike failed ({type(error).__name__}); inspect spikes/screens/failed.png", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
