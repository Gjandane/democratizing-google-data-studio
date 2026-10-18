"""Report setup, page canvas and save/link operations for Data Studio."""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from dsengine.ops import OpContext, OpResult, OperationError

HANDLED_OPS = {"open_report", "set_canvas", "set_background_image", "save_report", "get_link"}
_SAVED_REPORT = re.compile(
    r"https://(?:data|looker)studio\.google\.com/reporting/(?!create/)[^/]+/.+"
)


def _locator(page: Any, ctx: OpContext, key: str) -> Any:
    return ctx.locator(page, key)


def _visible(locator: Any) -> bool:
    try:
        return any(locator.nth(index).is_visible() for index in range(locator.count()))
    except Exception:
        return False


def _wait_visible(locator: Any, ctx: OpContext) -> None:
    locator.wait_for(state="visible", timeout=ctx.timeout_ms())


def _poll(page: Any, ctx: OpContext, predicate, failure: str) -> None:
    while True:
        if predicate():
            return
        remaining = ctx.remaining_s()
        if remaining <= 0:
            raise OperationError(failure)
        page.wait_for_timeout(min(250, max(1, int(remaining * 1000))))


def _dismiss_access_review(page: Any, ctx: OpContext) -> bool:
    accept = _locator(page, ctx, "review_accept")
    if not _visible(accept):
        return False
    if not accept.is_checked():
        accept.check(timeout=ctx.timeout_ms())
    acknowledge = _locator(page, ctx, "review_acknowledge")
    acknowledge.click(timeout=ctx.timeout_ms())
    acknowledge.wait_for(state="hidden", timeout=ctx.timeout_ms())
    return True


def _wait_for_editor(page: Any, ctx: OpContext) -> None:
    add_chart = _locator(page, ctx, "add_chart")
    first_field = _locator(page, ctx, "first_field")
    linking_error = _locator(page, ctx, "linking_error")

    while True:
        if _visible(linking_error):
            raise OperationError("Data Studio rejected the report creation link")
        if _dismiss_access_review(page, ctx):
            continue
        if _visible(add_chart) and _visible(first_field):
            return
        remaining = ctx.op_deadline - time.monotonic()
        if remaining <= 0:
            raise OperationError("Data Studio editor did not become ready")
        page.wait_for_timeout(min(250, max(1, int(remaining * 1000))))


def _run_open_report(page: Any, op: Any, ctx: OpContext) -> OpResult:
    if not ctx.open_url:
        raise OperationError("report creation URL was not prepared")
    page.goto(ctx.open_url, wait_until="domcontentloaded",
              timeout=ctx.timeout_ms())
    page.set_viewport_size({"width": 1920, "height": 1200})
    _wait_for_editor(page, ctx)

    zoom_menu = _locator(page, ctx, "zoom_menu")
    zoom_menu.click(timeout=ctx.timeout_ms())
    _locator(page, ctx, "zoom_100").click(timeout=ctx.timeout_ms())
    canvas = _locator(page, ctx, "canvas")
    _wait_visible(canvas, ctx)
    ctx.state[op.id] = {"opened_url": page.url}
    ctx.canvas_dimensions = (ctx.recipe.header.canvas.width, ctx.recipe.header.canvas.height)
    return OpResult()


def _verify_open_report(page: Any, op: Any, ctx: OpContext) -> None:
    add_chart = _locator(page, ctx, "add_chart")
    first_field = _locator(page, ctx, "first_field")
    canvas = _locator(page, ctx, "canvas")
    if not (_visible(add_chart) and _visible(first_field) and _visible(canvas)):
        raise OperationError("Data Studio editor readiness check failed")
    if urlsplit(page.url).hostname not in {"datastudio.google.com", "lookerstudio.google.com"}:
        raise OperationError("Data Studio opened an unexpected page")


def _run_set_canvas(page: Any, op: Any, ctx: OpContext) -> OpResult:
    width, height = int(op.width), int(op.height)
    if not 10 <= width <= 2000 or not 10 <= height <= 10000:
        raise OperationError("canvas dimensions must be between 10x10 and 2000x10000")

    _locator(page, ctx, "page_menu").click(timeout=ctx.timeout_ms())
    _locator(page, ctx, "current_page_settings").click(timeout=ctx.timeout_ms())
    _locator(page, ctx, "page_style_tab").click(timeout=ctx.timeout_ms())

    size = _locator(page, ctx, "canvas_size")
    if size.count() == 0:
        size = _locator(page, ctx, "canvas_size_auto")
    size.click(timeout=ctx.timeout_ms())
    custom = _locator(page, ctx, "canvas_size_custom")
    custom.click(timeout=ctx.timeout_ms())

    width_input = _locator(page, ctx, "canvas_width")
    height_input = _locator(page, ctx, "canvas_height")
    width_input.fill(str(width), timeout=ctx.timeout_ms())
    width_input.press("Enter", timeout=ctx.timeout_ms())
    height_input.fill(str(height), timeout=ctx.timeout_ms())
    height_input.press("Enter", timeout=ctx.timeout_ms())
    height_input.press("Tab", timeout=ctx.timeout_ms())
    ctx.state[op.id] = {"canvas": (width, height)}
    return OpResult()


def _verify_set_canvas(page: Any, op: Any, ctx: OpContext) -> None:
    canvas = _locator(page, ctx, "canvas")
    expected = (int(op.width), int(op.height))
    while True:
        actual = tuple(canvas.evaluate("e => [e.offsetWidth, e.offsetHeight]"))
        if all(abs(found - target) <= 4 for found, target in zip(actual, expected)):
            ctx.canvas_dimensions = expected
            return
        remaining = ctx.remaining_s()
        if remaining <= 0:
            raise OperationError("canvas size did not match the requested dimensions")
        page.wait_for_timeout(min(200, max(1, int(remaining * 1000))))


def _geometry(component: Any) -> tuple[int, int, int, int]:
    return tuple(component.evaluate("e => [e.offsetLeft, e.offsetTop, e.offsetWidth, e.offsetHeight]"))


def _drag(page: Any, start: tuple[float, float], end: tuple[float, float]) -> None:
    page.mouse.move(*start)
    page.mouse.down()
    # Cross the CDK drag activation threshold before moving to the destination.
    page.mouse.move(start[0] + 10, start[1] + 10, steps=2)
    page.mouse.move(*end, steps=12)
    page.mouse.up()


def _place_component(page: Any, component: Any, canvas: Any,
                     target: tuple[int, int, int, int]) -> None:
    x, y, width, height = _geometry(component)
    bounds = component.bounding_box()
    canvas_bounds = canvas.bounding_box()
    if bounds is None or canvas_bounds is None:
        raise OperationError("image component or canvas is not visible")

    start = (bounds["x"] + bounds["width"] / 2,
             bounds["y"] + bounds["height"] / 2)
    page.mouse.click(*start)
    if (x, y) != target[:2]:
        destination = (start[0] + target[0] - x, start[1] + target[1] - y)
        _drag(page, start, destination)

    if (width, height) != target[2:]:
        bounds = component.bounding_box()
        if bounds is None:
            raise OperationError("image component disappeared while placing it")
        resize_start = (bounds["x"] + bounds["width"], bounds["y"] + bounds["height"])
        resize_end = (canvas_bounds["x"] + target[0] + target[2],
                      canvas_bounds["y"] + target[1] + target[3])
        _drag(page, resize_start, resize_end)


def _background_box(op: Any, dimensions: tuple[int, int]) -> tuple[tuple[int, int, int, int], bool]:
    canvas_width, canvas_height = dimensions
    x, y = int(op.x), int(op.y)
    width, height = int(op.w), int(op.h)
    x = min(max(0, x), canvas_width - 1)
    y = min(max(0, y), canvas_height - 1)
    width = min(width, canvas_width - x)
    height = min(height, canvas_height - y)
    clamped = (x, y, width, height) != (op.x, op.y, op.w, op.h)
    return (x, y, width, height), clamped


def _run_set_background_image(page: Any, op: Any, ctx: OpContext) -> OpResult:
    path = ctx.recipe.asset_path(op.path)
    if not path.is_file():
        raise OperationError("background image asset was not found")

    dimensions = ctx.canvas_dimensions or (ctx.recipe.header.canvas.width,
                                          ctx.recipe.header.canvas.height)
    target, clamped = _background_box(op, dimensions)
    if clamped:
        ctx.warn(f"{op.id}: background image box was clamped to the canvas")

    components = _locator(page, ctx, "components")
    before = components.count()
    _locator(page, ctx, "image").click(timeout=ctx.timeout_ms())
    with page.expect_file_chooser(timeout=ctx.timeout_ms()) as chooser:
        _locator(page, ctx, "upload_image").click(timeout=ctx.timeout_ms())
    chooser.value.set_files(str(path), timeout=ctx.timeout_ms())

    image_component = _locator(page, ctx, "image_component")
    image_component.wait_for(state="visible", timeout=ctx.timeout_ms())
    components_count = components.count()
    if components_count != before + 1:
        raise OperationError("background upload did not add exactly one image")
    image_content = _locator(page, ctx, "image_content")
    image_content.wait_for(state="visible", timeout=ctx.timeout_ms())
    image_deadline = time.monotonic() + ctx.remaining_s()
    while image_content.evaluate("e => e.naturalWidth") <= 0:
        remaining = image_deadline - time.monotonic()
        if remaining <= 0:
            raise OperationError("background image did not finish loading")
        page.wait_for_timeout(min(200, max(1, int(remaining * 1000))))

    canvas = _locator(page, ctx, "canvas")
    _place_component(page, image_component, canvas, target)
    _locator(page, ctx, "arrange").click(timeout=ctx.timeout_ms())
    _locator(page, ctx, "order").hover(timeout=ctx.timeout_ms())
    _locator(page, ctx, "send_back").click(timeout=ctx.timeout_ms())
    ctx.state[op.id] = {"target": target, "before": before}
    return OpResult()


def _verify_set_background_image(page: Any, op: Any, ctx: OpContext) -> None:
    state = ctx.state.get(op.id)
    if not state:
        raise OperationError("background image placement was not recorded")
    component = _locator(page, ctx, "image_component")
    image = _locator(page, ctx, "image_content")
    components = _locator(page, ctx, "components")
    deadline = min(ctx.op_deadline, time.monotonic() + max(0, ctx.timeout_ms() / 1000))
    while True:
        actual = _geometry(component)
        target = state["target"]
        first_is_image = components.first.locator(ctx.selectors["image_content"]).count() == 1
        natural_width = image.evaluate("e => e.naturalWidth")
        if (all(abs(found - expected) <= 4 for found, expected in zip(actual, target))
                and first_is_image and natural_width > 0
                and components.count() == state["before"] + 1):
            return
        remaining = min(deadline - time.monotonic(), ctx.remaining_s())
        if remaining <= 0:
            raise OperationError("background image placement did not verify")
        page.wait_for_timeout(min(200, max(1, int(remaining * 1000))))


def _run_save_report(page: Any, op: Any, ctx: OpContext) -> OpResult:
    _locator(page, ctx, "save_share").click(timeout=ctx.timeout_ms())
    review = _locator(page, ctx, "review_save_dialog")
    _wait_visible(review, ctx)
    accept = _locator(page, ctx, "review_accept")
    if not accept.is_checked():
        accept.check(timeout=ctx.timeout_ms())
    acknowledge = _locator(page, ctx, "acknowledge_save")
    acknowledge.click(timeout=ctx.timeout_ms())
    acknowledge.wait_for(state="hidden", timeout=ctx.timeout_ms())
    page.wait_for_url(_SAVED_REPORT, timeout=ctx.timeout_ms())

    current = page.url
    if not _SAVED_REPORT.fullmatch(current):
        raise OperationError("saved report URL was not available")
    ctx.report_url = current.removesuffix("/edit")
    ctx.report_saved = True
    return OpResult()


def _verify_save_report(page: Any, op: Any, ctx: OpContext) -> None:
    if not ctx.report_url or not _SAVED_REPORT.fullmatch(page.url):
        raise OperationError("report save could not be confirmed")


def _run_get_link(page: Any, op: Any, ctx: OpContext) -> OpResult:
    current = page.url
    if _SAVED_REPORT.fullmatch(current):
        ctx.report_url = current.removesuffix("/edit")
    elif ctx.report_url:
        # The save operation may already have captured the link before a later UI change.
        pass
    else:
        raise OperationError("saved report link is not available")
    parsed = urlsplit(ctx.report_url)
    if (parsed.hostname not in {"datastudio.google.com", "lookerstudio.google.com"}
            or "/reporting/create" in parsed.path or parsed.path.endswith("/edit")):
        raise OperationError("report view link could not be confirmed")
    return OpResult()


def _verify_get_link(page: Any, op: Any, ctx: OpContext) -> None:
    if not ctx.report_url:
        raise OperationError("report view link was not returned")
    parsed = urlsplit(ctx.report_url)
    if parsed.hostname not in {"datastudio.google.com", "lookerstudio.google.com"}:
        raise OperationError("report view link has an unexpected host")


_RUNNERS = {
    "open_report": _run_open_report,
    "set_canvas": _run_set_canvas,
    "set_background_image": _run_set_background_image,
    "save_report": _run_save_report,
    "get_link": _run_get_link,
}
_VERIFIERS = {
    "open_report": _verify_open_report,
    "set_canvas": _verify_set_canvas,
    "set_background_image": _verify_set_background_image,
    "save_report": _verify_save_report,
    "get_link": _verify_get_link,
}


def run(page: Any, op: Any, ctx: OpContext) -> OpResult:
    return _RUNNERS[op.op](page, op, ctx)


def verify(page: Any, op: Any, ctx: OpContext) -> None:
    _VERIFIERS[op.op](page, op, ctx)
