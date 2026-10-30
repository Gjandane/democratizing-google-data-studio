"""Report setup, page canvas and save/link operations for Data Studio."""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from dsengine.ops import OpContext, OpResult, OperationError
from dsengine.ops.charts import _click_canvas, _click_workspace, _drag_to

HANDLED_OPS = {"open_report", "set_canvas", "set_background_image", "save_report", "get_link"}
_VIEWPORT = (1920, 1200)
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


def _accept_access_review(page: Any, dialog: Any, ctx: OpContext, button_key: str) -> None:
    # The dialog can precede its controls. Never let a disabled-button click
    # consume the shared deadline while a required checkbox renders later.
    accept = _locator(dialog, ctx, "review_accept")
    button = _locator(dialog, ctx, button_key)
    while True:
        if ctx.remaining_s() <= 0:
            raise OperationError("data-access review controls did not become ready")
        if _visible(accept) and not accept.is_checked():
            accept.check(timeout=ctx.timeout_ms())
        if _visible(button) and button.is_enabled():
            button.click(timeout=ctx.timeout_ms())
            break
        remaining = ctx.remaining_s()
        if remaining <= 0:
            raise OperationError("data-access review controls did not become ready")
        page.wait_for_timeout(min(250, max(1, int(remaining * 1000))))
    dialog.wait_for(state="hidden", timeout=ctx.timeout_ms())


def _dismiss_access_review(page: Any, ctx: OpContext) -> bool:
    dialog = _locator(page, ctx, "review_dialog")
    if not _visible(dialog):
        return False
    _accept_access_review(page, dialog, ctx, "review_acknowledge")
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


def _check_layout(page: Any) -> None:
    # Viewport emulation absorbs the Windows display scale, but not Chrome's
    # per-site zoom, which the profile persists and CDP cannot reset. At 50%
    # zoom the editor lays out at 3840 x 2400 CSS px and its pickers differ.
    width, height, ratio = page.evaluate("[innerWidth, innerHeight, devicePixelRatio]")
    if abs(width - _VIEWPORT[0]) > 1 or abs(height - _VIEWPORT[1]) > 1:
        raise OperationError(
            f"editor laid out at {width} x {height} CSS px (devicePixelRatio {ratio:g}), "
            f"not {_VIEWPORT[0]} x {_VIEWPORT[1]}; set Chrome zoom to 100% in the dedicated "
            "Chrome window (Ctrl+0 resets to the default, Settings > Appearance > Page zoom) "
            "and retry"
        )


def _default_report(ctx: OpContext) -> bool:
    # Recipe 1.5: un-aliased ds.* params mean no template, so Data Studio's default report.
    return "ds.connector" in parse_qs(urlsplit(ctx.open_url or "").query)


def _clear_default_components(page: Any, ctx: OpContext, canvas: Any) -> int:
    """Delete the default report's starter components; the recipe places every component."""
    components = _locator(page, ctx, "components")
    # They render together with the canvas (live 2026-10-31); allow a short settle for them.
    settle = min(ctx.op_deadline, time.monotonic() + 2)
    while components.count() == 0 and time.monotonic() < settle:
        page.wait_for_timeout(250)
    found = components.count()
    if found:
        _click_workspace(page, ctx, canvas)
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.press("Delete")
        _poll(page, ctx, lambda: components.count() == 0,
              "default report components were not deleted")
    return found


def _run_open_report(page: Any, op: Any, ctx: OpContext) -> OpResult:
    from dsengine.ops.charts import _source_fields

    if not ctx.open_url:
        raise OperationError("report creation URL was not prepared")
    page.goto(ctx.open_url, wait_until="domcontentloaded",
              timeout=ctx.timeout_ms())
    page.set_viewport_size({"width": _VIEWPORT[0], "height": _VIEWPORT[1]})
    _wait_for_editor(page, ctx)
    _check_layout(page)
    # Images and source-less controls can clear the Data panel. Capture the
    # report's immutable source while editor readiness guarantees field chips.
    _source_fields(page, ctx)

    zoom_menu = _locator(page, ctx, "zoom_menu")
    zoom_menu.click(timeout=ctx.timeout_ms())
    _locator(page, ctx, "zoom_100").click(timeout=ctx.timeout_ms())
    canvas = _locator(page, ctx, "canvas")
    _wait_visible(canvas, ctx)
    ctx.state[op.id] = {"opened_url": page.url}
    ctx.canvas_dimensions = (ctx.recipe.header.canvas.width, ctx.recipe.header.canvas.height)
    if _default_report(ctx):
        cleared = _clear_default_components(page, ctx, canvas)
        ctx.state[op.id]["cleared"] = cleared
        ctx.events.emit("log", level="info",
                        message=f"{op.id}: deleted {cleared} default report components")
    return OpResult()


def _verify_open_report(page: Any, op: Any, ctx: OpContext) -> None:
    add_chart = _locator(page, ctx, "add_chart")
    first_field = _locator(page, ctx, "first_field")
    canvas = _locator(page, ctx, "canvas")
    if not (_visible(add_chart) and _visible(first_field) and _visible(canvas)):
        raise OperationError("Data Studio editor readiness check failed")
    if urlsplit(page.url).hostname not in {"datastudio.google.com", "lookerstudio.google.com"}:
        raise OperationError("Data Studio opened an unexpected page")
    if _default_report(ctx) and _locator(page, ctx, "components").count():
        raise OperationError("default report still holds components the recipe didn't place")


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


def _place_component(page: Any, ctx: OpContext, component: Any, canvas: Any,
                     target: tuple[int, int, int, int]) -> None:
    x, y, width, height = _geometry(component)
    if component.bounding_box() is None or canvas.bounding_box() is None:
        raise OperationError("image component or canvas is not visible")

    # Resize where the resized box stays on the canvas, so its handle never
    # leaves it: in place when it fits (edge-clamped boxes, where moving first
    # would hide the handle), else from the nearest fitting position (large
    # boxes such as a full-canvas background, uploaded smaller mid-canvas).
    if (width, height) != target[2:]:
        canvas_width, canvas_height = ctx.canvas_dimensions or (
            ctx.recipe.header.canvas.width, ctx.recipe.header.canvas.height)
        fit = (min(x, canvas_width - target[2]), min(y, canvas_height - target[3]))
        if fit != (x, y):
            _drag_to(page, ctx, canvas, component, (*fit, width, height), handle="center")
        x, y, _, _ = _geometry(component)
        _click_canvas(page, ctx, canvas, x + width / 2, y + height / 2)
        _drag_to(page, ctx, canvas, component, target, handle="resize")
    _drag_to(page, ctx, canvas, component, target, handle="center")


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


def _prepare_image(page: Any, component: Any, ctx: OpContext) -> None:
    """Select this image's Setup panel and allow arbitrary recipe rectangles."""
    _locator(page, ctx, "selection_mode").click(timeout=ctx.timeout_ms())
    _click_workspace(page, ctx, _locator(page, ctx, "canvas"))
    component.click(position={"x": 10, "y": 10}, timeout=ctx.timeout_ms())
    setup = _locator(page, ctx, "setup_tab")
    setup.wait_for(state="visible", timeout=ctx.timeout_ms())
    setup.click(timeout=ctx.timeout_ms())
    ratio = _locator(page, ctx, "image_preserve_ratio")
    ratio.wait_for(state="visible", timeout=ctx.timeout_ms())
    if ratio.get_attribute("aria-checked") == "true":
        ratio.click(timeout=ctx.timeout_ms())


def _component_index(components: Any, retained: Any) -> int:
    index = components.evaluate_all("(elements, retained) => elements.indexOf(retained)", retained)
    if index < 0:
        raise OperationError("retained component is no longer on its owning page")
    return index


def _send_background_back(page: Any, component: Any, ctx: OpContext) -> None:
    from dsengine.ops import pages

    pages.remember_components(page, ctx)
    active, _ = pages.current(page, ctx)
    # Indices are page-local paint order. Capture identity before changing that order,
    # then refresh every affected registry entry, even if a menu action fails.
    retained = []
    for state in ctx.state.values():
        if not isinstance(state, dict) or state.get("page_index") != active:
            continue
        for key in ("component_index", "control_index", "chart_index"):
            if key in state:
                collection = _locator(page, ctx, "chart_components" if key == "chart_index" else "components")
                retained.append((state, key, collection, collection.nth(state[key]).element_handle(
                    timeout=ctx.timeout_ms())))
    components = _locator(page, ctx, "components")
    try:
        _locator(page, ctx, "arrange").click(timeout=ctx.timeout_ms())
        _locator(page, ctx, "order").hover(timeout=ctx.timeout_ms())
        _locator(page, ctx, "send_back").click(timeout=ctx.timeout_ms())
        _poll(page, ctx, lambda: _component_index(components, component) == 0,
              "background was not sent to the back")
    finally:
        for state, key, collection, handle in retained:
            state[key] = _component_index(collection, handle)
            handle.dispose()


def _run_set_background_image(page: Any, op: Any, ctx: OpContext) -> OpResult:
    from dsengine.ops import pages

    path = ctx.recipe.asset_path(op.path)
    if not path.is_file():
        raise OperationError("background image asset was not found")
    state = ctx.state.setdefault(op.id, {"page_index": pages.current(page, ctx)[0]})
    if pages.current(page, ctx)[0] != state["page_index"]:
        pages.switch(page, ctx, state["page_index"])
    dimensions = ctx.canvas_dimensions or (ctx.recipe.header.canvas.width,
                                          ctx.recipe.header.canvas.height)
    target, clamped = _background_box(op, dimensions)
    if clamped:
        ctx.warn(f"{op.id}: background image box was clamped to the canvas")
    state["target"] = target
    components = _locator(page, ctx, "components")
    state.setdefault("before", components.count())
    before = state["before"]
    if "component" not in state:
        if not state.get("upload_started"):
            _locator(page, ctx, "image").click(timeout=ctx.timeout_ms())
            with page.expect_file_chooser(timeout=ctx.timeout_ms()) as chooser:
                _locator(page, ctx, "upload_image").click(timeout=ctx.timeout_ms())
            # Retain the pending creation too: an upload can succeed before its API
            # call raises, so retry must wait for it rather than upload a duplicate.
            state["upload_started"] = True
            chooser.value.set_files(str(path), timeout=ctx.timeout_ms())
        _poll(page, ctx, lambda: components.count() == before + 1,
              "background upload did not add exactly one image")
        state["component"] = components.nth(before).element_handle(timeout=ctx.timeout_ms())
        state["component_index"] = before
    component = state["component"]
    _component_index(components, component)
    image = component.wait_for_selector(ctx.selectors["image_content"],
                                        state="visible", timeout=ctx.timeout_ms())
    _poll(page, ctx, lambda: image.evaluate("e => e.naturalWidth") > 0,
          "background image did not finish loading")
    if not (state.get("placed") and _geometry(component) == target
            and _component_index(components, component) == 0):
        _prepare_image(page, component, ctx)
        _place_component(page, ctx, component, _locator(page, ctx, "canvas"), target)
        state["placed"] = True
        _send_background_back(page, component, ctx)
    _settle(page, ctx)
    return OpResult()


def _clean(page: Any, ctx: OpContext) -> bool:
    return not (_visible(_locator(page, ctx, "open_menu"))
                or _visible(_locator(page, ctx, "selected_component")))


def _settle(page: Any, ctx: OpContext) -> None:
    """Close menus and deselect the background, so the next op starts clean."""
    canvas = _locator(page, ctx, "canvas")

    # A workspace click while Send to back's menu is still closing only closes
    # it (live 2026-10-21), so act again on whatever is still open each poll.
    def settled() -> bool:
        if _visible(_locator(page, ctx, "open_menu")):
            page.keyboard.press("Escape")
        elif _visible(_locator(page, ctx, "selected_component")):
            _click_workspace(page, ctx, canvas)
        else:
            return True
        return False

    _poll(page, ctx, settled, "background left a menu open or a component selected")


def _verify_set_background_image(page: Any, op: Any, ctx: OpContext) -> None:
    state = ctx.state.get(op.id, {})
    if "component" not in state or "target" not in state:
        raise OperationError("background image placement was not recorded")
    component = state["component"]
    image = component.wait_for_selector(ctx.selectors["image_content"],
                                        state="visible", timeout=ctx.timeout_ms())
    components = _locator(page, ctx, "components")
    _poll(page, ctx, lambda: (
        all(abs(a - e) <= 4 for a, e in zip(_geometry(component), state["target"]))
        and _component_index(components, component) == 0
        and image.evaluate("e => e.naturalWidth") > 0
        and components.count() == state["before"] + 1
        and _clean(page, ctx)
    ), "background image placement did not verify")


def _run_save_report(page: Any, op: Any, ctx: OpContext) -> OpResult:
    _locator(page, ctx, "save_share").click(timeout=ctx.timeout_ms())
    review = _locator(page, ctx, "review_save_dialog")
    _wait_visible(review, ctx)
    _accept_access_review(page, review, ctx, "acknowledge_save")
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
