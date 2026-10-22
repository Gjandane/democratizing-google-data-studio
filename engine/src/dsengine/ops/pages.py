"""Page creation, renaming and one-based navigation in the owned report."""

import re
from typing import Any

from dsengine.ops import OpContext, OpResult, OperationError
from dsengine.ops.charts import _locator, _poll, _visible

HANDLED_OPS = {"add_page", "rename_page", "go_to_page"}


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


def _close_manager(page: Any, ctx: OpContext) -> None:
    if _visible(_locator(page, ctx, "pages_close")):
        _locator(page, ctx, "pages_close").click(timeout=ctx.timeout_ms())


def _single_page_manager(page: Any, ctx: OpContext, state: dict[str, Any]) -> None:
    """Open Manage pages on a one-page report, where Data Studio disables it.

    Add page opens the manager; deleting that temporary page leaves it open on
    the single row. ``state["temporary"]`` lets a retry delete it, never twice.
    """
    if state.get("temporary") and current(page, ctx)[1] == 1:
        state["temporary"] = False  # deleted before the failure
    if not state.get("temporary"):
        if _visible(_locator(page, ctx, "pages_close")):
            return
        state["temporary"] = True
        _locator(page, ctx, "add_page_button").click(timeout=ctx.timeout_ms())
        _poll(page, ctx, lambda: current(page, ctx) == (2, 2),
              "temporary page for Manage pages was not added")
    _manager(page, ctx)
    rows = _rows(page, ctx)
    _poll(page, ctx, lambda: rows.count() == 2, "temporary page did not appear in Manage pages")
    rows.nth(1).locator(ctx.selectors["page_row_menu"]).click(timeout=ctx.timeout_ms())
    _locator(page, ctx, "page_delete").click(timeout=ctx.timeout_ms())
    _poll(page, ctx, lambda: rows.count() == 1 and current(page, ctx)[1] == 1,
          "temporary page for Manage pages was not deleted")
    state["temporary"] = False


def _rename(page: Any, ctx: OpContext, index: int, name: str, message: str) -> str:
    """Rename one page through Manage pages: the step add_page and rename_page share."""
    _manager(page, ctx)
    row = _rows(page, ctx).nth(index - 1)
    row.locator(ctx.selectors["page_row_menu"]).click(timeout=ctx.timeout_ms())
    _locator(page, ctx, "page_rename").click(timeout=ctx.timeout_ms())
    field = _locator(page, ctx, "page_name")
    field.fill(name, timeout=ctx.timeout_ms())
    field.press("Enter", timeout=ctx.timeout_ms())
    page.keyboard.press("Escape")
    _poll(page, ctx, lambda: row.inner_text().strip() == name, message)
    return row.inner_text().strip()


def switch(page: Any, ctx: OpContext, index: int) -> None:
    remember_components(page, ctx)
    active, count = current(page, ctx)
    if not 1 <= index <= count:
        raise OperationError(f"page index {index} is outside the report's {count} pages")
    if active != index:
        _manager(page, ctx)
        _rows(page, ctx).nth(index - 1).click(timeout=ctx.timeout_ms())
    _poll(page, ctx, lambda: current(page, ctx)[0] == index, "page navigation did not verify")
    _close_manager(page, ctx)
    canvas = _locator(page, ctx, "canvas")
    ctx.canvas_dimensions = tuple(canvas.evaluate("e => [e.offsetWidth, e.offsetHeight]"))


def run(page: Any, op: Any, ctx: OpContext) -> OpResult:
    remember_components(page, ctx)
    if op.op == "go_to_page":
        switch(page, ctx, int(op.index))
        ctx.state[op.id] = {"index": int(op.index)}
        return OpResult()
    if op.op == "rename_page":
        # A retry renames the page that was current when the op first ran.
        state = ctx.state.setdefault(op.id, {"index": current(page, ctx)[0]})
        if current(page, ctx)[1] == 1 or state.get("temporary"):
            _single_page_manager(page, ctx, state)
        elif current(page, ctx)[0] != state["index"]:
            switch(page, ctx, state["index"])
        state["name"] = _rename(page, ctx, state["index"], op.name, "page name did not verify")
        # Manage pages stays open for verify: a one-page report cannot reopen it.
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
    state["name"] = _rename(page, ctx, target, op.name, "new page name did not verify")
    switch(page, ctx, target)
    return OpResult()


def verify(page: Any, op: Any, ctx: OpContext) -> None:
    state = ctx.state[op.id]
    if current(page, ctx)[0] != state["index"]:
        raise OperationError("current page did not match the recipe")
    if op.op == "add_page" and (current(page, ctx)[1] != state["index"]
                                 or state.get("name") != op.name):
        raise OperationError("page count or name did not match the recipe")
    if op.op == "rename_page":
        # Read the row itself: the name Data Studio kept, not the one typed.
        try:
            if not _visible(_locator(page, ctx, "pages_close")) and current(page, ctx)[1] == 1:
                raise OperationError("Manage pages closed before the page name was read")
            _manager(page, ctx)
            name = _rows(page, ctx).nth(state["index"] - 1).inner_text().strip()
        finally:
            _close_manager(page, ctx)
        if name != op.name:
            raise OperationError("page name did not match the recipe")
