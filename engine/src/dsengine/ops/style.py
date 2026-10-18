"""Apply exposed component styles, warning about unsupported keys."""

import re
from typing import Any

from dsengine.ops import OpContext, OpResult, OperationError
from dsengine.ops.charts import _locator, _poll, _visible, _set_switch
from dsengine.ops import pages

HANDLED_OPS = {"set_style"}


def rgb(color: str) -> str:
    return "rgb({}, {}, {})".format(*(int(color[i:i + 2], 16) for i in (1, 3, 5)))


def set_color(page: Any, button: Any, color: str, ctx: OpContext) -> None:
    button.click(timeout=ctx.timeout_ms())
    _locator(page, ctx, "custom_color").click(timeout=ctx.timeout_ms())
    field = _locator(page, ctx, "color_hex")
    field.fill(color, timeout=ctx.timeout_ms())
    _locator(page, ctx, "color_done").click(timeout=ctx.timeout_ms())
    field.wait_for(state="hidden", timeout=ctx.timeout_ms())


def _preview(control: Any, ctx: OpContext) -> str:
    if control.locator(ctx.selectors["color_preview"]).count() == 0:
        return control.evaluate("e => getComputedStyle(e).backgroundColor")
    return control.locator(ctx.selectors["color_preview"]).evaluate(
        "e => getComputedStyle(e).backgroundColor"
    )


def component_for(page: Any, op: Any, ctx: OpContext) -> tuple[Any, Any]:
    pages.remember_components(page, ctx)
    for creator in ctx.recipe.ops:
        if creator.id == op.id:
            break
        if creator.op not in {"add_chart", "add_control", "add_text", "add_image"}:
            continue
        if creator.component_id != op.component_id:
            continue
        state = ctx.state.get(creator.id, {})
        index = next((state[k] for k in ("chart_index", "control_index", "component_index")
                      if k in state), None)
        if index is None or "target" not in state:
            raise OperationError(f"component {op.component_id} was not created")
        pages.switch(page, ctx, state["page_index"])
        key = "chart_components" if creator.op == "add_chart" else "components"
        component = _locator(page, ctx, key).nth(index)
        component.wait_for(state="visible", timeout=ctx.timeout_ms())
        return component, creator
    raise OperationError(f"component {op.component_id} was not created")


def run(page: Any, op: Any, ctx: OpContext) -> OpResult:
    component, creator = component_for(page, op, ctx)
    component.click(position={"x": 10, "y": 10}, timeout=ctx.timeout_ms())
    page.keyboard.press("Escape")
    tab = _locator(page, ctx, "style_tab")
    if _visible(tab):
        tab.click(timeout=ctx.timeout_ms())
    applied = {}
    for key, value in op.style.items():
        if key in {"background", "border_color"}:
            control = _locator(page, ctx, f"style_{key}")
            if _visible(control):
                set_color(page, control.locator(ctx.selectors["color_button"]), value, ctx)
                _poll(page, ctx, lambda: _preview(control, ctx) == rgb(value),
                      f"style {key} did not apply")
                applied[key] = value
                continue
        elif key == "colors":
            controls = _locator(page, ctx, "style_colors")
            if len(value) <= controls.count():
                for index, color in enumerate(value):
                    control = controls.nth(index)
                    button = (control if control.evaluate("(e, selector) => e.matches(selector)", ctx.selectors["series_swatch"])
                              else control.locator(ctx.selectors["color_button"]))
                    set_color(page, button, color, ctx)
                    _poll(page, ctx, lambda: _preview(control, ctx) == rgb(color),
                          "chart series color did not apply")
                applied[key] = value
                continue
        elif key == "show_title" and _visible(_locator(page, ctx, "show_title_switch")):
            _set_switch(page, ctx, "show_title_switch", value, "show title")
            applied[key] = value
            continue
        elif key == "font_size" and creator.op == "add_text":
            from dsengine.ops.text import _format
            from types import SimpleNamespace
            _format(page, component, SimpleNamespace(font_size=value), ctx)
            applied[key] = value
            continue
        elif key == "font_size" and _visible(_locator(page, ctx, "style_title_size")):
            control = _locator(page, ctx, "style_title_size")
            control.click(timeout=ctx.timeout_ms())
            choice = _locator(page, ctx, "font_size_option").filter(has_text=re.compile(rf"^\s*{value}px\s*$"))
            if _visible(choice):
                choice.click(timeout=ctx.timeout_ms())
                applied[key] = value
                continue
            page.keyboard.press("Escape")
        ctx.warn(f"{op.id}: unsupported style key {key} for this component")
    ctx.state[op.id] = {"applied": applied, "creator": creator.id}
    return OpResult()


def verify(page: Any, op: Any, ctx: OpContext) -> None:
    applied = ctx.state[op.id]["applied"]
    for key, value in applied.items():
        if key in {"background", "border_color"}:
            if _preview(_locator(page, ctx, f"style_{key}"), ctx) != rgb(value):
                raise OperationError(f"style {key} did not verify")
        elif key == "colors":
            controls = _locator(page, ctx, "style_colors")
            if any(_preview(controls.nth(i), ctx) != rgb(c) for i, c in enumerate(value)):
                raise OperationError("chart series colors did not verify")
        elif key == "show_title":
            if (_locator(page, ctx, "show_title_switch").get_attribute("aria-checked") == "true") != value:
                raise OperationError("show_title did not verify")
        elif key == "font_size":
            creator = next(c for c in ctx.recipe.ops if c.id == ctx.state[op.id]["creator"])
            if creator.op == "add_text":
                from dsengine.ops.text import text_styles
                component, _ = component_for(page, op, ctx)
                _poll(page, ctx, lambda: bool(text_styles(component, ctx)) and all(
                    s["size"] == value for s in text_styles(component, ctx)),
                    "text font_size did not verify")
            elif _locator(page, ctx, "style_title_size").inner_text().strip() != f"{value}px":
                raise OperationError("title font_size did not verify")
