"""Page creation and one-based navigation in the owned report."""

import re
from typing import Any

from dsengine.ops import OpContext, OpResult, OperationError
from dsengine.ops.charts import _locator, _poll, _visible

HANDLED_OPS = {"add_page", "go_to_page"}


def current(page: Any, ctx: OpContext) -> tuple[int, int]:
    control = _locator(page, ctx, "manage_pages")
    if not control.count():
        return 1, 1
    match = re.search(r"Page (\d+) of (\d+)", control.inner_text())
    if not match:
        raise OperationError("current report page could not be read")
    return tuple(map(int, match.groups()))


def remember_components(page: Any, ctx: OpContext) -> None:
    """Record actual ownership before leaving a page, including partial creations."""
    active, _ = current(page, ctx)
    for creator in ctx.recipe.ops:
        if creator.op not in {"add_chart", "add_control", "add_text", "add_image"}:
            continue
        state = ctx.state.get(creator.id, {})
        if any(k in state for k in ("chart_index", "control_index", "component_index")):
            state.setdefault("page_index", active)


def _rows(page: Any, ctx: OpContext) -> Any:
    return _locator(page, ctx, "pages_panel").locator(ctx.selectors["page_rows"])


def _manager(page: Any, ctx: OpContext) -> None:
    if not _visible(_locator(page, ctx, "pages_close")):
        _locator(page, ctx, "manage_pages").click(timeout=ctx.timeout_ms())
    _locator(page, ctx, "pages_close").wait_for(state="visible", timeout=ctx.timeout_ms())


def switch(page: Any, ctx: OpContext, index: int) -> None:
    remember_components(page, ctx)
    active, count = current(page, ctx)
    if not 1 <= index <= count:
        raise OperationError(f"page index {index} is outside the report's {count} pages")
    if active != index:
        _manager(page, ctx)
        _rows(page, ctx).nth(index - 1).click(timeout=ctx.timeout_ms())
    _poll(page, ctx, lambda: current(page, ctx)[0] == index, "page navigation did not verify")
    if _visible(_locator(page, ctx, "pages_close")):
        _locator(page, ctx, "pages_close").click(timeout=ctx.timeout_ms())
    canvas = _locator(page, ctx, "canvas")
    ctx.canvas_dimensions = tuple(canvas.evaluate("e => [e.offsetWidth, e.offsetHeight]"))


def run(page: Any, op: Any, ctx: OpContext) -> OpResult:
    remember_components(page, ctx)
    if op.op == "go_to_page":
        switch(page, ctx, int(op.index))
        ctx.state[op.id] = {"index": int(op.index)}
        return OpResult()
    state = ctx.state.setdefault(op.id, {"index": current(page, ctx)[1] + 1})
    target = state["index"]
    if current(page, ctx)[1] == target - 1:
        switch(page, ctx, target - 1)
        if _visible(_locator(page, ctx, "add_page_button")):
            _locator(page, ctx, "add_page_button").click(timeout=ctx.timeout_ms())
        else:
            _manager(page, ctx)
            _locator(page, ctx, "page_add").click(timeout=ctx.timeout_ms())
    _poll(page, ctx, lambda: current(page, ctx) == (target, target),
          "page creation did not increase the page count by one")
    _manager(page, ctx)
    row = _rows(page, ctx).nth(target - 1)
    row.locator(ctx.selectors["page_row_menu"]).click(timeout=ctx.timeout_ms())
    _locator(page, ctx, "page_rename").click(timeout=ctx.timeout_ms())
    name = _locator(page, ctx, "page_name")
    name.fill(op.name, timeout=ctx.timeout_ms())
    name.press("Enter", timeout=ctx.timeout_ms())
    page.keyboard.press("Escape")
    _poll(page, ctx, lambda: row.inner_text().strip() == op.name,
          "new page name did not verify")
    state["name"] = row.inner_text().strip()
    switch(page, ctx, target)
    return OpResult()


def verify(page: Any, op: Any, ctx: OpContext) -> None:
    state = ctx.state[op.id]
    if current(page, ctx)[0] != state["index"]:
        raise OperationError("current page did not match the recipe")
    if op.op == "add_page" and (current(page, ctx)[1] != state["index"]
                                 or state.get("name") != op.name):
        raise OperationError("page count or name did not match the recipe")
