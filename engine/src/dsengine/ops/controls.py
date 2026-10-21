"""Date range and dimension dropdown controls in the owned report."""

from typing import Any

from dsengine.ops import OpContext, OpResult, OperationError
from dsengine.ops.charts import (
    _chart_box, _click_canvas, _field_names, _geometry, _locator, _matches_field,
    _place_chart, _poll, _require_source_field, _set_fields, _source_fields, _wait_visible,
)

HANDLED_OPS = {"add_control"}
_TYPES = {"date_range": "date_range_control", "dropdown": "dropdown_control"}


def run(page: Any, op: Any, ctx: OpContext) -> OpResult:
    if op.control_type not in _TYPES:
        raise OperationError(f"unsupported control type {op.control_type}")
    _source_fields(page, ctx)
    field = getattr(op, "field", None) if op.control_type == "dropdown" else None
    if op.control_type == "dropdown":
        if not field:
            raise OperationError("dropdown requires a field")
        _require_source_field(page, ctx, field)
    target, clamped = _chart_box(op, ctx)
    if clamped:
        ctx.warn(f"{op.id}: control box was clamped to the canvas")
    components = _locator(page, ctx, "components")
    state = ctx.state.setdefault(op.id, {"control_index": components.count()})
    before = state["control_index"]
    canvas = _locator(page, ctx, "canvas")
    if components.count() == before:
        _locator(page, ctx, "add_control").click(timeout=ctx.timeout_ms())
        menuitem = _locator(page, ctx, _TYPES[op.control_type])
        menuitem.click(timeout=ctx.timeout_ms())
        menuitem.wait_for(state="hidden", timeout=ctx.timeout_ms())
        _wait_visible(_locator(page, ctx, "drawing"), ctx, "control drawing mode did not open")
        if canvas.bounding_box() is None:
            raise OperationError("report canvas is not visible")
        _click_canvas(page, ctx, canvas, 24, 24)
        _poll(page, ctx, lambda: components.count() == before + 1,
              "control insertion did not add exactly one component")
    component = components.nth(before)
    _place_chart(page, ctx, component, canvas, target, dismiss_popup=True)
    page.keyboard.press("Escape")
    _locator(page, ctx, "setup_tab").click(timeout=ctx.timeout_ms())
    if field:
        group = _locator(page, ctx, "control_field_group")
        _wait_visible(group, ctx, "control field Setup group is unavailable")
        _require_source_field(page, ctx, field)
        _set_fields(page, ctx, group, [field])
    state.update(target=target, field=field)
    return OpResult()


def verify(page: Any, op: Any, ctx: OpContext) -> None:
    state = ctx.state[op.id]
    components = _locator(page, ctx, "components")
    if components.count() != state["control_index"] + 1:
        raise OperationError("control component count did not increase by one")
    component = components.nth(state["control_index"])
    if component.locator(ctx.selectors[f"component_{op.control_type}_control"]).count() != 1:
        raise OperationError("inserted control type did not match the recipe")
    if not all(abs(a - e) <= 4 for a, e in zip(_geometry(component), state["target"])):
        raise OperationError("control box did not match the requested position and size")
    _locator(page, ctx, "setup_tab").click(timeout=ctx.timeout_ms())
    if state["field"]:
        labels = _field_names(_locator(page, ctx, "control_field_group"), ctx)
        if len(labels) != 1 or not _matches_field(labels[0], state["field"]):
            raise OperationError("dropdown field did not match the recipe")
    else:
        _wait_visible(_locator(page, ctx, "date_control_default"), ctx,
                      "date range control Setup is unavailable")
