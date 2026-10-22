"""Apply exposed component styles, warning about unsupported keys."""

import re
from typing import Any, Iterator

from dsengine.ops import OpContext, OpResult, OperationError
from dsengine.ops.charts import _locator, _poll, _visible, _set_switch
from dsengine.ops import pages

HANDLED_OPS = {"set_style"}
_STYLE_WAIT_MS = 5000
_SERIES_POLLS = 12  # 3 s for a picked series' Line color before picking again


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
        return control.evaluate("e => getComputedStyle(e).backgroundColor",
                                timeout=ctx.timeout_ms())
    return control.locator(ctx.selectors["color_preview"]).evaluate(
        "e => getComputedStyle(e).backgroundColor", timeout=ctx.timeout_ms()
    )


def _series_color(page: Any, ctx: OpContext, number: int) -> Any:
    """Series number's Line color picker on a time series (Select metric shows one)."""
    return page.locator(ctx.selectors["series_color"].format(n=number))


def _series_shown(page: Any, ctx: OpContext, limit: int) -> int | None:
    """The series (1..limit) whose Line color shows alone, if one does."""
    shown = [n for n in range(1, limit + 1) if _visible(_series_color(page, ctx, n))]
    if len(shown) == 1 and not _visible(_locator(page, ctx, "series_color_all")):
        return shown[0]
    return None


def _show_series(page: Any, ctx: OpContext, select: Any, options: Any, index: int,
                 number: int, limit: int) -> None:
    """Pick option index in Select metric until series number's Line color shows alone.

    The combobox text changes before the cell does, and in 1 of 6 live runs a
    picked series' cell never showed (2026-10-22): wait for the cell itself, and
    pick again after _SERIES_POLLS polls.
    """
    while True:
        if not _visible(options.first):
            if _series_shown(page, ctx, limit) == number:
                return
            select.click(timeout=ctx.timeout_ms())
            _poll(page, ctx, lambda: _visible(options.first), "Select metric did not open")
        options.nth(index).click(timeout=ctx.timeout_ms())
        # Reopening while the list still closes clicks the closing list, to no effect.
        _poll(page, ctx, lambda: not _visible(options.first), "Select metric did not close")
        for _ in range(_SERIES_POLLS):
            if _series_shown(page, ctx, limit) == number:
                return
            if ctx.remaining_s() <= 0:
                raise OperationError(f"series {number} Line color did not show")
            page.wait_for_timeout(min(250, ctx.timeout_ms()))


def _series_count(creator: Any) -> int | None:
    """A time series' series count from its recipe op: one per metric, unless broken down."""
    if getattr(creator, "chart_type", None) != "time_series" or getattr(creator, "breakdown", None):
        return None
    return len(getattr(creator, "metrics", None) or []) or None


def _swatches(page: Any, ctx: OpContext, prepare: bool,
              series: int | None = None) -> Iterator[tuple[int, Any]]:
    """Yield the selected chart's series swatches as (series position, control), ready to click.

    Bars list theirs in the multiColor cell. A pie colors slices by dimension value
    until Color by is Slice order (with prepare, switch it), which lists the slice
    swatches there. A time series shows one series' Line color at a time, picked in
    Select metric: with several series "All metrics" (one shared color) leads the
    list, then series 1, 2, ... in order. series: the time series' count, if known.
    """
    controls = _locator(page, ctx, "style_colors")
    by_position = _locator(page, ctx, "color_by_position")
    if prepare and controls.count() == 0 and _visible(by_position):
        by_position.check(timeout=ctx.timeout_ms())
        _poll(page, ctx, lambda: controls.count() > 0, "pie slice colors did not appear")
    if controls.count():
        for index in range(controls.count()):
            yield index, controls.nth(index)
        return
    select = _locator(page, ctx, "series_select")
    # One series already shows its Line color: skip the list, whose sole option took
    # 16 s to take a click while its chart loaded (release replay, 2026-10-22).
    if not _visible(select) or (series == 1 and _series_shown(page, ctx, 1) == 1):
        if _visible(_series_color(page, ctx, 1)):
            yield 0, _series_color(page, ctx, 1)
        return
    options = _locator(page, ctx, "option_overlay").locator(ctx.selectors["dropdown_option"])
    try:
        select.click(timeout=ctx.timeout_ms())
        _poll(page, ctx, lambda: _visible(options.first), "Select metric did not open")
        labels = options.evaluate_all("es => es.map(e => e.innerText.trim())")
        first = 1 if len(labels) > 1 else 0
        for index in range(first, len(labels)):
            number = max(1, index)
            _show_series(page, ctx, select, options, index, number, len(labels))
            yield number - 1, _series_color(page, ctx, number)
    except Exception:
        # An open list's backdrop intercepts every later click, and the retry's
        # cleanup skips Escape once the budget is spent (release replay 2026-10-22).
        if _visible(options.first):
            page.keyboard.press("Escape")
        raise


def _color_button(control: Any, ctx: OpContext) -> Any:
    if control.evaluate("(e, selector) => e.matches(selector)", ctx.selectors["series_swatch"],
                        timeout=ctx.timeout_ms()):
        return control
    return control.locator(ctx.selectors["color_button"])


def _apply_colors(page: Any, ctx: OpContext, colors: list[str],
                  series: int | None = None) -> int | None:
    """Color the first min(len(colors), swatches) swatches in order and return how many.

    None: the component has no series swatch.
    """
    applied = None
    for position, control in _swatches(page, ctx, bool(colors), series):
        applied = applied or 0
        if position < len(colors):
            color = colors[position]
            set_color(page, _color_button(control, ctx), color, ctx)
            _poll(page, ctx, lambda: _preview(control, ctx) == rgb(color),
                  "chart series color did not apply")
            applied += 1
        if applied == len(colors):
            break
    return applied


def _read_colors(page: Any, ctx: OpContext, count: int,
                 series: int | None = None) -> list[str | None]:
    """The colors (rgb()) of the swatches at series positions 0..count-1."""
    read: dict[int, str] = {}
    for position, control in _swatches(page, ctx, False, series):
        if position < count:
            read[position] = _preview(control, ctx)
        if len(read) == count:
            break
    return [read.get(position) for position in range(count)]


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
        elif key == "colors" and creator.op == "add_chart":
            # Count swatches once the Style cells render (every chart observed has
            # Background); a chart without one only skips the key.
            try:
                _locator(page, ctx, "style_background").first.wait_for(
                    state="visible", timeout=min(ctx.timeout_ms(), _STYLE_WAIT_MS))
            except Exception:
                pass
            count = _apply_colors(page, ctx, list(value), _series_count(creator))
            if count is not None:
                applied[key] = list(value[:count])
                ctx.events.emit("log", level="info",
                                message=f"{op.id}: colors applied {count} of {len(value)}")
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
    creator = next(c for c in ctx.recipe.ops if c.id == ctx.state[op.id]["creator"])
    for key, value in applied.items():
        if key in {"background", "border_color"}:
            if _preview(_locator(page, ctx, f"style_{key}"), ctx) != rgb(value):
                raise OperationError(f"style {key} did not verify")
        elif key == "colors":
            if _read_colors(page, ctx, len(value), _series_count(creator)) != [rgb(c) for c in value]:
                raise OperationError("chart series colors did not verify")
        elif key == "show_title":
            if (_locator(page, ctx, "show_title_switch").get_attribute("aria-checked") == "true") != value:
                raise OperationError("show_title did not verify")
        elif key == "font_size":
            if creator.op == "add_text":
                from dsengine.ops.text import text_styles
                component, _ = component_for(page, op, ctx)
                _poll(page, ctx, lambda: bool(text_styles(component, ctx)) and all(
                    s["size"] == value for s in text_styles(component, ctx)),
                    "text font_size did not verify")
            else:
                # The combobox can include its closing option list briefly.
                _poll(page, ctx, lambda: _locator(page, ctx, "style_title_size").inner_text(
                    timeout=ctx.timeout_ms()).strip()
                      == f"{value}px", "title font_size did not verify")
