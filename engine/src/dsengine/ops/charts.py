"""Chart insertion and setup operations for Data Studio."""

from __future__ import annotations

import math
from typing import Any

from dsengine.ops import OpContext, OpResult, OperationError

HANDLED_OPS = {"add_chart"}

_CHART_BUTTONS = {
    "scorecard": "scorecard_chart",
    "time_series": "time_series_chart",
    "bar": "bar_chart",
    "pie": "pie_chart",
    "table": "table_chart",
    "pivot_table": "pivot_table_chart",
    "geo_map": "geo_map_chart",
    "scatter": "scatter_chart",
}

_CHART_COMPONENTS = {name: f"component_{name}" for name in _CHART_BUTTONS}

_AGGREGATIONS = {
    "sum": "Sum",
    "avg": "Average",
    "count": "Count",
    "count_distinct": "Count Distinct",
    "min": "Min",
    "max": "Max",
    "none": "None",
}

_GEO_TYPES = {"country": "Country", "region": "Country subdivision (1st level)", "city": "City"}


def _dimensions(op: Any) -> tuple[list[str], list[str]]:
    dimensions = list(op.dimensions)
    columns: list[str] = []
    if op.chart_type == "pivot_table":
        options = getattr(op, "options", {}) or {}
        dimensions = options.get("row_dimensions", dimensions)
        columns = options.get("column_dimensions", [])
        if any(not isinstance(fields, list) or any(not isinstance(f, str) or not f for f in fields)
               for fields in (dimensions, columns)):
            raise OperationError("pivot row_dimensions and column_dimensions must be lists of field names")
    if op.chart_type == "time_series" and getattr(op, "date_dimension", None):
        dimensions = [op.date_dimension] + [f for f in dimensions if f != op.date_dimension]
    return dimensions, columns


def _metric_groups(page: Any, ctx: OpContext, op: Any, metrics: list) -> list[tuple[Any, list]]:
    if op.chart_type == "scatter":
        keys = ["scatter_x_group", "scatter_y_group", "scatter_size_group"]
        return [(_locator(page, ctx, key), metrics[i:i + 1]) for i, key in enumerate(keys)]
    return [(_locator(page, ctx, "metric_group_any"), metrics)]


def _geo_type(page: Any, ctx: OpContext, op: Any, *, change: bool) -> None:
    value = (getattr(op, "options", {}) or {}).get("geo_type")
    if value is None:
        return
    if not isinstance(value, str) or value not in _GEO_TYPES:
        raise OperationError("geo_type must be country, region or city")
    group = _locator(page, ctx, "dimension_group_any")
    group.locator(ctx.selectors["dimension_type_button"]).first.click(timeout=ctx.timeout_ms())
    control = _locator(page, ctx, "data_type_control")
    _wait_visible(control, ctx, "geo dimension data type is unavailable")
    label = _GEO_TYPES[value]
    if change and control.inner_text().strip() != label:
        control.click(timeout=ctx.timeout_ms())
        _locator(page, ctx, "geo_type_menu").hover(timeout=ctx.timeout_ms())
        _locator(page, ctx, "last_overlay").get_by_role("menuitem", name=label, exact=True).click(timeout=ctx.timeout_ms())
    actual = control.inner_text().strip()
    page.keyboard.press("Escape")
    if actual != label:
        raise OperationError(f"geo dimension could not map to {value}")


def _locator(page: Any, ctx: OpContext, key: str) -> Any:
    return ctx.locator(page, key)


def _value(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _visible(locator: Any) -> bool:
    try:
        return any(locator.nth(index).is_visible() for index in range(locator.count()))
    except Exception:
        return False


def _wait_visible(locator: Any, ctx: OpContext, message: str) -> None:
    try:
        locator.wait_for(state="visible", timeout=ctx.timeout_ms())
    except Exception:
        raise OperationError(message) from None


def _poll(page: Any, ctx: OpContext, predicate, message: str) -> None:
    while True:
        if predicate():
            return
        remaining = ctx.remaining_s()
        if remaining <= 0:
            raise OperationError(message)
        page.wait_for_timeout(min(250, max(1, int(remaining * 1000))))


def _chart_box(op: Any, ctx: OpContext) -> tuple[tuple[int, int, int, int], bool]:
    try:
        x, y, width, height = (int(op.x), int(op.y), int(op.w), int(op.h))
    except (TypeError, ValueError, AttributeError):
        raise OperationError("chart box must use integer pixel coordinates") from None
    if width <= 0 or height <= 0:
        raise OperationError("chart width and height must be positive")
    canvas_width, canvas_height = ctx.canvas_dimensions or (
        ctx.recipe.header.canvas.width, ctx.recipe.header.canvas.height
    )
    x = min(max(0, x), canvas_width - 1)
    y = min(max(0, y), canvas_height - 1)
    width = min(width, canvas_width - x)
    height = min(height, canvas_height - y)
    target = (x, y, width, height)
    clamped = target != (op.x, op.y, op.w, op.h)
    return target, clamped


def _field_names(group: Any, ctx: OpContext) -> list[str]:
    chips = group.locator(ctx.selectors["field_chips"])
    return chips.evaluate_all(
        "es => es.map(e => e.getAttribute('aria-label')).filter(Boolean).map(s => s.trim())"
    )


def _matches_field(label: str, field: str) -> bool:
    return label == field or label.startswith(f"{field} (")


def _source_fields(page: Any, ctx: OpContext) -> list[str]:
    available = _locator(page, ctx, "field_buttons")
    names = available.evaluate_all(
        "es => es.map(e => (e.getAttribute('aria-label') || e.innerText || '').trim())"
    )
    # A date control has no source and temporarily clears the Data panel.
    # The report's single immutable source is shared by every chart/control.
    if names:
        ctx.state["_source_fields"] = names
    return names or ctx.state.get("_source_fields", [])


def _require_source_field(page: Any, ctx: OpContext, field: str) -> None:
    if field not in _source_fields(page, ctx):
        raise OperationError(f"field {field} not in data source")


def _field_picker(page: Any, ctx: OpContext) -> Any:
    picker = _locator(page, ctx, "field_picker")
    _wait_visible(picker, ctx, "chart field picker did not open")
    return picker


def _choose_picker_field(page: Any, ctx: OpContext, field: str) -> None:
    picker = _field_picker(page, ctx)
    choices = picker.get_by_role("button", name=field, exact=True)
    empty = picker.locator(ctx.selectors["field_picker_empty"])
    search = picker.locator(ctx.selectors["field_picker_search"])
    if not _visible(choices) and not _visible(empty) and _visible(search):
        # The picker renders only the rows near its scroll position (16 field
        # buttons, live 2026-10-22): a later field exists only once searched.
        search.fill(field, timeout=ctx.timeout_ms())
        _poll(page, ctx, lambda: _visible(choices) or _visible(empty),
              f"field {field} not in data source")
    if not _visible(choices):
        raise OperationError(f"field {field} not in data source")
    choices.last.click(timeout=ctx.timeout_ms())
    _poll(page, ctx, lambda: not _visible(picker), "chart field selection did not close")


def _remove_extra_fields(page: Any, ctx: OpContext, group: Any, keep: int) -> None:
    chips = group.locator(ctx.selectors["field_chips"])
    while chips.count() > keep:
        before = chips.count()
        chip = group.locator(ctx.selectors["field_containers"]).nth(chips.count() - 1)
        chip.hover(timeout=ctx.timeout_ms())
        remove = chip.locator(ctx.selectors["field_remove_button"])
        if remove.count() == 0:
            raise OperationError("Data Studio does not expose a field removal control")
        remove.click(timeout=ctx.timeout_ms())
        _poll(page, ctx, lambda: chips.count() < before, "chart field was not removed")


def _set_fields(page: Any, ctx: OpContext, group: Any, fields: list[str], *,
                add_label: str | None = None) -> None:
    for field in fields:
        _require_source_field(page, ctx, field)

    _remove_extra_fields(page, ctx, group, len(fields))
    current = _field_names(group, ctx)
    for index, field in enumerate(fields):
        if index < len(current) and _matches_field(current[index], field):
            continue
        if index < len(current):
            group.locator(ctx.selectors["field_containers"]).nth(index).locator(
                ctx.selectors["field_replace_button"]
            ).click(
                timeout=ctx.timeout_ms()
            )
        elif add_label:
            add = group.locator(ctx.selectors[
                "add_dimension" if add_label == "Add dimension" else "add_metric"
            ])
            if add_label == "Add dimension" and not _visible(add):
                drill = _locator(page, ctx, "drill_down_switch")
                if _visible(drill):
                    _set_switch(page, ctx, "drill_down_switch", True, "drill down")
            _wait_visible(add, ctx, f"Data Studio {add_label.lower()} control is unavailable")
            add.click(timeout=ctx.timeout_ms())
        else:
            raise OperationError("Data Studio field group cannot accept another field")
        _choose_picker_field(page, ctx, field)
        _poll(page, ctx,
              lambda: index < len(_field_names(group, ctx))
              and _matches_field(_field_names(group, ctx)[index], field),
              f"chart field {field} did not appear in its Setup group")
        current = _field_names(group, ctx)


def _aggregation(page: Any, ctx: OpContext, group: Any, index: int,
                 agg: str, *, change: bool) -> None:
    label = _AGGREGATIONS.get(agg)
    if label is None:
        raise OperationError(f"unsupported metric aggregation {agg}")
    metric = group.locator(ctx.selectors["metric_chips"]).nth(index)
    metric.locator(ctx.selectors["metric_aggregation_button"]).click(timeout=ctx.timeout_ms())
    pane = _locator(page, ctx, "metric_editor")
    _wait_visible(pane, ctx, "metric editor did not open")
    control = pane.locator(ctx.selectors["aggregation_control"])
    if change and control.inner_text().splitlines()[0].strip() != label:
        control.click(timeout=ctx.timeout_ms())
        choices = _locator(page, ctx, "last_overlay").get_by_text(label, exact=True)
        if not _visible(choices):
            page.keyboard.press("Escape")
            page.keyboard.press("Escape")
            raise OperationError(f"Data Studio aggregation {label} is unavailable")
        choices.click(timeout=ctx.timeout_ms())
    actual = control.inner_text().splitlines()[0].strip()
    page.keyboard.press("Escape")
    if actual != label:
        raise OperationError(f"metric aggregation {label} did not verify (found {actual})")


def _inherent_sort(op: Any, dimensions: list[str]) -> bool:
    # Time series Setup has no Sort section (live 2026-10-21): the editor
    # always orders by the date dimension ascending. Only that sort is possible.
    sort = getattr(op, "sort", None)
    if op.chart_type != "time_series" or not sort:
        return False
    field = str(_value(sort, "field", ""))
    order = str(_value(sort, "order", "desc")).lower()
    if not dimensions or field != dimensions[0] or order != "asc":
        raise OperationError("time_series sorts only by its date dimension, ascending")
    return True


def _set_sort(page: Any, ctx: OpContext, sort: Any) -> None:
    if not sort:
        return
    group = _locator(page, ctx, "sort_group")
    _wait_visible(group, ctx, "chart sort controls are unavailable")
    field = str(_value(sort, "field", ""))
    _set_fields(page, ctx, group, [field])
    order = str(_value(sort, "order", "desc")).lower()
    key = "sort_ascending" if order == "asc" else "sort_descending"
    control = _locator(page, ctx, "sort_order_group").locator(ctx.selectors[key])
    _wait_visible(control, ctx, "chart sort order control is unavailable")
    control.check(timeout=ctx.timeout_ms())


def _set_switch(page: Any, ctx: OpContext, key: str, enabled: bool, option: str) -> None:
    switch = _locator(page, ctx, key)
    _wait_visible(switch, ctx, f"Data Studio option {option} is unavailable")
    current = switch.get_attribute("aria-checked") == "true"
    if current != enabled:
        switch.click(timeout=ctx.timeout_ms())
    if (switch.get_attribute("aria-checked") == "true") != enabled:
        raise OperationError(f"Data Studio option {option} did not apply")


def _nearest_option(requested: str, offered: list[str]) -> str | None:
    """The offered number closest to the requested one; the smaller on a tie."""
    values = [int(text) for text in offered if text.isdigit()]
    if not requested.isdigit() or not values:
        return None
    target = int(requested)
    return str(min(values, key=lambda value: (abs(value - target), value)))


def _set_dropdown(page: Any, ctx: OpContext, control_key: str, value: str,
                  option: str, *, nearest: bool = False) -> str:
    """Choose value in a menu control and return the value chosen.

    nearest: when the menu doesn't offer value, choose its nearest number instead.
    """
    control = _locator(page, ctx, control_key)
    _wait_visible(control, ctx, f"Data Studio option {option} is unavailable")
    control.click(timeout=ctx.timeout_ms())
    # Another pane can already be visible (one reading "Autogenerate" on the
    # release table, 2026-10-21), so wait until the last pane is the option list.
    pane = _locator(page, ctx, "last_overlay")
    _poll(page, ctx, lambda: _visible(pane.locator(ctx.selectors["dropdown_option"]).first),
          f"Data Studio option {option} menu did not open")
    if nearest:
        value = _nearest_option(value, pane.locator(ctx.selectors["dropdown_option"]).evaluate_all(
            "es => es.map(e => e.innerText.trim())")) or value
    choices = pane.get_by_text(value, exact=True)
    if not _visible(choices):
        page.keyboard.press("Escape")
        raise OperationError(f"Data Studio option {value} is unavailable")
    choices.last.click(timeout=ctx.timeout_ms())
    return value


def _set_title_and_options(page: Any, ctx: OpContext, op: Any) -> str | None:
    """Apply the title and chart options; return the table rows per page applied."""
    title_text = getattr(op, "title", None)
    if title_text:
        _locator(page, ctx, "style_tab").click(timeout=ctx.timeout_ms())
        show_title = _locator(page, ctx, "show_title_switch")
        if _visible(show_title) and show_title.get_attribute("aria-checked") != "true":
            show_title.click(timeout=ctx.timeout_ms())
        title = _locator(page, ctx, "chart_title_input")
        _wait_visible(title, ctx, "chart title input is unavailable")
        title.fill(str(title_text), timeout=ctx.timeout_ms())
        title.press("Tab", timeout=ctx.timeout_ms())

    options = getattr(op, "options", None) or {}
    if not options:
        return None
    if op.chart_type == "scorecard" and "compact_numbers" in options:
        _locator(page, ctx, "style_tab").click(timeout=ctx.timeout_ms())
        _set_switch(page, ctx, "compact_numbers_switch",
                    bool(options["compact_numbers"]), "compact numbers")
    elif op.chart_type == "bar":
        _locator(page, ctx, "style_tab").click(timeout=ctx.timeout_ms())
        if "orientation" in options:
            key = "orientation_vertical" if options["orientation"] == "vertical" else "orientation_horizontal"
            control = _locator(page, ctx, key)
            _wait_visible(control, ctx, "bar chart orientation control is unavailable")
            control.check(timeout=ctx.timeout_ms())
        if "stacked" in options:
            stacked = _locator(page, ctx, "stacked_switch")
            if _visible(stacked):
                _set_switch(page, ctx, "stacked_switch", bool(options["stacked"]), "stacked bars")
    elif op.chart_type == "table" and "rows_per_page" in options:
        _locator(page, ctx, "setup_tab").click(timeout=ctx.timeout_ms())
        # Rows per page is a fixed menu (1, 5, 10, 20, 25, 50, 100, 250, ...).
        rows = str(options["rows_per_page"])
        applied = _set_dropdown(page, ctx, "rows_per_page_control", rows, "rows per page",
                                nearest=True)
        if applied != rows:
            ctx.warn(f"{op.id}: rows_per_page {rows} is not offered; applied {applied}")
        return applied
    return None


def _drag(page: Any, start: tuple[float, float], end: tuple[float, float]) -> None:
    page.mouse.move(*start)
    page.mouse.down()
    # Cross the editor's CDK drag threshold before moving to the target.
    page.mouse.move(start[0] + 10, start[1] + 10, steps=2)
    page.mouse.move(*end, steps=12)
    page.mouse.up()


def _geometry(component: Any) -> tuple[int, int, int, int]:
    return tuple(component.evaluate("e => [e.offsetLeft, e.offsetTop, e.offsetWidth, e.offsetHeight]"))


# Canvases can be taller than the editor's scroll window (per_section pages). Mouse
# input outside the window misses its target, so every point is revealed first.
_EDGE = 40  # px kept clear of the scroll window's edges
_THRESHOLD = 10  # px of the initial move in _drag

_REVEAL = """(canvas, [left, top, right, bottom, edge]) => {
    let scroller = canvas.parentElement;
    for (; scroller && scroller !== document.scrollingElement; scroller = scroller.parentElement) {
        const style = getComputedStyle(scroller);
        if (/(auto|scroll)/.test(style.overflowY + style.overflowX)
                && (scroller.scrollHeight > scroller.clientHeight
                    || scroller.scrollWidth > scroller.clientWidth)) break;
    }
    scroller = scroller || document.scrollingElement;
    const area = () => {
        if (scroller === document.scrollingElement)
            return {left: 0, top: 0, right: innerWidth, bottom: innerHeight};
        const r = scroller.getBoundingClientRect();
        const x = r.left + scroller.clientLeft, y = r.top + scroller.clientTop;
        return {left: Math.max(0, x), top: Math.max(0, y),
                right: Math.min(innerWidth, x + scroller.clientWidth),
                bottom: Math.min(innerHeight, y + scroller.clientHeight)};
    };
    const shift = (low, high, start, end) =>
        high - low > end - start - 2 * edge || low < start + edge ? low - start - edge
            : high > end - edge ? high - end + edge : 0;
    let box = canvas.getBoundingClientRect(), view = area();
    scroller.scrollBy({left: shift(box.left + left, box.left + right, view.left, view.right),
                       top: shift(box.top + top, box.top + bottom, view.top, view.bottom),
                       behavior: 'instant'});
    box = canvas.getBoundingClientRect();
    return {x: box.left, y: box.top, view: area()};
}"""


def _reveal(canvas: Any, ctx: OpContext, left: float, top: float,
            right: float | None = None, bottom: float | None = None) -> dict:
    """Scroll this canvas box into the editor's view; return the canvas origin and the view."""
    box = [left, top, left if right is None else right, top if bottom is None else bottom, _EDGE]
    return canvas.evaluate(_REVEAL, box, timeout=ctx.timeout_ms())


def _click_canvas(page: Any, ctx: OpContext, canvas: Any, x: float, y: float) -> None:
    origin = _reveal(canvas, ctx, x, y)
    page.mouse.click(origin["x"] + x, origin["y"] + y)


def _click_workspace(page: Any, ctx: OpContext, canvas: Any) -> None:
    """Deselect by clicking the empty workspace left of the canvas top."""
    origin = _reveal(canvas, ctx, 0, 40)
    page.mouse.click(max(1, origin["x"] - 12), origin["y"] + 40)


def _close_calendar(page: Any, ctx: OpContext) -> None:
    """Escape the calendar a date control opens on click, a drag's mouse-up included.

    It opens flush with the control's bottom edge, over the resize corner.
    """
    calendar = _locator(page, ctx, "date_calendar")
    if _visible(calendar):
        page.keyboard.press("Escape")
        _poll(page, ctx, lambda: not _visible(calendar), "date control calendar did not close")


def _drag_to(page: Any, ctx: OpContext, canvas: Any, component: Any,
             target: tuple[int, int, int, int], *, handle: str,
             dismiss_popup: bool = False) -> None:
    """Drag a component until its box reaches target, in steps whose ends are in view.

    handle: "move" (10 px inside the top-left), "center", or "resize" (bottom-right).
    dismiss_popup: close a date control's calendar before each step.
    """
    def where() -> tuple[tuple[float, float], tuple[int, int]]:
        x, y, width, height = _geometry(component)
        if handle == "resize":
            return (x + width, y + height), (target[2] - width, target[3] - height)
        offset = (width / 2, height / 2) if handle == "center" else (10, 10)
        return (x + offset[0], y + offset[1]), (target[0] - x, target[1] - y)

    point, delta = where()
    if not (delta[0] or delta[1]):
        return
    view = _reveal(canvas, ctx, *point)["view"]
    reach = (view["right"] - view["left"] - 2 * _EDGE - _THRESHOLD,
             view["bottom"] - view["top"] - 2 * _EDGE - _THRESHOLD)
    if min(reach) < _THRESHOLD:
        raise OperationError("editor view is too small to place components")
    for _ in range(math.ceil(max(abs(delta[0]) / reach[0], abs(delta[1]) / reach[1]))):
        (x, y), (dx, dy) = where()
        if not (dx or dy):
            return
        dx, dy = (max(-reach[0], min(reach[0], dx)), max(-reach[1], min(reach[1], dy)))
        if dismiss_popup:
            _close_calendar(page, ctx)
        origin = _reveal(canvas, ctx, min(x, x + dx), min(y, y + dy),
                         max(x, x + dx) + _THRESHOLD, max(y, y + dy) + _THRESHOLD)
        start = (origin["x"] + x, origin["y"] + y)
        _drag(page, start, (start[0] + dx, start[1] + dy))


def _place_chart(page: Any, ctx: OpContext, component: Any, canvas: Any,
                 target: tuple[int, int, int, int], *, dismiss_popup: bool = False) -> None:
    if component.bounding_box() is None or canvas.bounding_box() is None:
        raise OperationError("chart or canvas is not visible")
    x, y, _, _ = _geometry(component)
    _click_canvas(page, ctx, canvas, x + 10, y + 10)
    if dismiss_popup:
        page.keyboard.press("Escape")
    _drag_to(page, ctx, canvas, component, target, handle="move", dismiss_popup=dismiss_popup)
    _drag_to(page, ctx, canvas, component, target, handle="resize", dismiss_popup=dismiss_popup)


def _run_add_chart(page: Any, op: Any, ctx: OpContext) -> OpResult:
    if op.chart_type not in _CHART_BUTTONS:
        raise OperationError(f"chart type {op.chart_type} is not implemented")
    dimensions, columns = _dimensions(op)
    if op.chart_type == "pivot_table" and not dimensions:
        raise OperationError("pivot_table requires at least one row dimension")
    if not op.metrics:
        raise OperationError(f"{op.chart_type} requires at least one metric")
    if op.chart_type == "scorecard":
        if dimensions or len(op.metrics) != 1:
            raise OperationError("scorecard requires one metric and no dimensions")
    elif not dimensions and not columns:
        raise OperationError(f"{op.chart_type} requires at least one dimension")
    if op.chart_type == "pie" and len(op.metrics) != 1:
        raise OperationError("pie requires exactly one metric")
    if op.chart_type == "scatter" and len(op.metrics) not in {2, 3}:
        raise OperationError("scatter requires X and Y metrics, with an optional bubble size metric")
    if op.chart_type == "geo_map" and (len(dimensions) != 1 or len(op.metrics) != 1):
        raise OperationError("geo_map requires one geo dimension and one metric")
    if op.chart_type == "geo_map":
        geo_type = (getattr(op, "options", {}) or {}).get("geo_type")
        if geo_type is not None and (not isinstance(geo_type, str) or geo_type not in _GEO_TYPES):
            raise OperationError("geo_type must be country, region or city")
    inherent_sort = _inherent_sort(op, dimensions)
    target, clamped = _chart_box(op, ctx)
    if clamped:
        ctx.warn(f"{op.id}: chart box was clamped to the canvas")

    fields = dimensions + columns
    fields += [str(_value(metric, "field", "")) for metric in op.metrics]
    fields += [value for value in (getattr(op, "date_dimension", None),
                                  getattr(op, "breakdown", None),
                                  _value(getattr(op, "sort", None), "field")) if value]
    for field in fields:
        _require_source_field(page, ctx, field)

    charts = _locator(page, ctx, "chart_components")
    previous = ctx.state.get(op.id, {})
    before = previous.get("chart_index", charts.count())
    canvas = _locator(page, ctx, "canvas")
    if canvas.bounding_box() is None:
        raise OperationError("report canvas is not visible")
    if not previous:
        ctx.state[op.id] = {"chart_index": before}
    if charts.count() == before:
        key = _CHART_BUTTONS[op.chart_type]
        options = getattr(op, "options", {}) or {}
        if op.chart_type == "bar":
            vertical = options.get("orientation") == "vertical"
            key = ("stacked_vertical_bar_chart" if vertical else "stacked_bar_chart") if options.get("stacked") else ("vertical_bar_chart" if vertical else "bar_chart")
        elif op.chart_type == "pie" and options.get("donut"):
            key = "donut_chart"
        _locator(page, ctx, "add_chart").click(timeout=ctx.timeout_ms())
        gallery = _locator(page, ctx, "chart_gallery")
        _wait_visible(gallery, ctx, "chart type gallery did not open")
        gallery.locator(ctx.selectors[key]).click(timeout=ctx.timeout_ms())
        _locator(page, ctx, "drawing").wait_for(state="visible", timeout=ctx.timeout_ms())
        _click_canvas(page, ctx, canvas, 24, 24)
        _poll(page, ctx, lambda: charts.count() == before + 1,
              "chart insertion did not add exactly one chart")
    component = charts.nth(before)

    consent = _locator(page, ctx, "consent_dialog")
    if _visible(consent):
        _locator(page, ctx, "consent_allow").click(timeout=ctx.timeout_ms())
    _place_chart(page, ctx, component, canvas, target)
    _locator(page, ctx, "setup_tab").click(timeout=ctx.timeout_ms())

    if dimensions or op.chart_type == "pivot_table":
        dimension_group = _locator(page, ctx, "pivot_rows_group" if op.chart_type == "pivot_table" else "dimension_group_any")
        _wait_visible(dimension_group, ctx, "chart dimension Setup group is unavailable")
        try:
            _set_fields(page, ctx, dimension_group, dimensions, add_label="Add dimension")
        except OperationError as error:
            if op.chart_type == "geo_map":
                page.keyboard.press("Escape")
                if str(error) == f"field {dimensions[0]} not in data source":
                    raise OperationError(f"geo dimension {dimensions[0]} cannot map to a geo type in this data source") from error
            raise
    if op.chart_type == "pivot_table":
        _set_fields(page, ctx, _locator(page, ctx, "pivot_columns_group"), columns, add_label="Add dimension")
    if op.chart_type == "geo_map":
        _geo_type(page, ctx, op, change=True)

    breakdown = getattr(op, "breakdown", None)
    if breakdown:
        group = _locator(page, ctx, "breakdown_group")
        _wait_visible(group, ctx, "chart breakdown Setup group is unavailable")
        _set_fields(page, ctx, group, [breakdown], add_label="Add dimension")
    elif _visible(_locator(page, ctx, "breakdown_group")):
        _set_fields(page, ctx, _locator(page, ctx, "breakdown_group"), [])

    metrics = list(getattr(op, "metrics", []) or [])
    if metrics:
        for metric_group, group_metrics in _metric_groups(page, ctx, op, metrics):
            _wait_visible(metric_group, ctx, "chart metric Setup group is unavailable")
            _set_fields(page, ctx, metric_group,
                        [str(_value(metric, "field", "")) for metric in group_metrics],
                        add_label="Add metric")
            for index, metric in enumerate(group_metrics):
                _aggregation(page, ctx, metric_group, index,
                             str(_value(metric, "agg", "none")), change=True)

    date_dimension = getattr(op, "date_dimension", None)
    if date_dimension and op.chart_type != "time_series":
        date_group = _locator(page, ctx, "date_range_dimension_group")
        _wait_visible(date_group, ctx, "chart date dimension Setup group is unavailable")
        _set_fields(page, ctx, date_group, [date_dimension])

    sort = None if inherent_sort else getattr(op, "sort", None)
    _set_sort(page, ctx, sort)
    rows_per_page = _set_title_and_options(page, ctx, op)
    ctx.state[op.id] = {
        "target": target,
        "chart_index": before,
        "dimensions": dimensions,
        "columns": columns,
        "metrics": [(str(_value(metric, "field", "")), str(_value(metric, "agg", "none")))
                    for metric in metrics],
        "date_dimension": date_dimension if op.chart_type != "time_series" else None,
        # The verified first dimension already proves an inherent date sort.
        "sort": (_value(sort, "field"), _value(sort, "order")) if sort else None,
        "title": getattr(op, "title", None),
        "breakdown": breakdown,
        "rows_per_page": rows_per_page,
    }
    return OpResult()


def _verify_add_chart(page: Any, op: Any, ctx: OpContext) -> None:
    state = ctx.state.get(op.id)
    if not state:
        raise OperationError("chart setup was not recorded")
    charts = _locator(page, ctx, "chart_components")
    if charts.count() != state["chart_index"] + 1:
        raise OperationError("chart component count did not increase by one")
    component = charts.nth(state["chart_index"])
    if component.locator(ctx.selectors[_CHART_COMPONENTS[op.chart_type]]).count() != 1:
        raise OperationError("inserted chart type did not match the recipe")
    actual = _geometry(component)
    target = state["target"]
    if not all(abs(found - expected) <= 4 for found, expected in zip(actual, target)):
        raise OperationError("chart box did not match the requested position and size")

    _locator(page, ctx, "setup_tab").click(timeout=ctx.timeout_ms())
    if state["dimensions"] or op.chart_type == "pivot_table":
        dimension_group = _locator(page, ctx, "pivot_rows_group" if op.chart_type == "pivot_table" else "dimension_group_any")
        actual_fields = _field_names(dimension_group, ctx)
        expected_fields = state["dimensions"]
        if len(actual_fields) != len(expected_fields) or not all(
            _matches_field(actual, expected)
            for actual, expected in zip(actual_fields, expected_fields)
        ):
            raise OperationError("chart dimension Setup fields did not match the recipe")

    if op.chart_type == "pivot_table":
        actual = _field_names(_locator(page, ctx, "pivot_columns_group"), ctx)
        if len(actual) != len(state["columns"]) or not all(
            _matches_field(a, e) for a, e in zip(actual, state["columns"])
        ):
            raise OperationError("pivot column Setup fields did not match the recipe")
    if op.chart_type == "geo_map":
        _geo_type(page, ctx, op, change=False)

    for metric_group, group_metrics in _metric_groups(page, ctx, op, state["metrics"]):
        actual_fields = _field_names(metric_group, ctx)
        expected_fields = [field for field, _ in group_metrics]
        if len(actual_fields) != len(expected_fields) or not all(
            _matches_field(actual, expected)
            for actual, expected in zip(actual_fields, expected_fields)
        ):
            raise OperationError("chart metric Setup fields did not match the recipe")
        for index, (_, agg) in enumerate(group_metrics):
            _aggregation(page, ctx, metric_group, index, agg, change=False)

    if state["breakdown"]:
        if not any(_matches_field(value, state["breakdown"]) for value in
                   _field_names(_locator(page, ctx, "breakdown_group"), ctx)):
            raise OperationError("chart breakdown field did not match the recipe")
    elif _field_names(_locator(page, ctx, "breakdown_group"), ctx):
        raise OperationError("chart retained an unrequested breakdown field")

    if state["date_dimension"]:
        date_group = _locator(page, ctx, "date_range_dimension_group")
        if not any(_matches_field(value, state["date_dimension"])
                   for value in _field_names(date_group, ctx)):
            raise OperationError("chart date dimension did not match the recipe")

    if state["sort"]:
        if not any(_matches_field(value, state["sort"][0]) for value in
                   _field_names(_locator(page, ctx, "sort_group"), ctx)):
            raise OperationError("chart sort field did not match the recipe")
        order_key = "sort_ascending" if str(state["sort"][1]).lower() == "asc" else "sort_descending"
        if not _locator(page, ctx, "sort_order_group").locator(ctx.selectors[order_key]).is_checked():
            raise OperationError("chart sort order did not match the recipe")

    options = getattr(op, "options", {}) or {}
    if state.get("rows_per_page"):
        # The applied value: the recipe's, or the nearest the menu offers.
        if _locator(page, ctx, "rows_per_page_control").inner_text().strip() != state["rows_per_page"]:
            raise OperationError("table rows per page did not match the recipe")
    if state["title"] or (options and op.chart_type != "table"):
        _locator(page, ctx, "style_tab").click(timeout=ctx.timeout_ms())
    if state["title"]:
        title = _locator(page, ctx, "chart_title_input")
        if title.input_value() != state["title"]:
            raise OperationError("chart title did not match the recipe")
        if _locator(page, ctx, "show_title_switch").get_attribute("aria-checked") != "true":
            raise OperationError("chart title is hidden")
    if op.chart_type == "scorecard" and "compact_numbers" in options:
        actual = _locator(page, ctx, "compact_numbers_switch").get_attribute("aria-checked") == "true"
        if actual != bool(options["compact_numbers"]):
            raise OperationError("scorecard compact numbers did not match the recipe")
    elif op.chart_type == "bar":
        if "orientation" in options:
            key = "orientation_vertical" if options["orientation"] == "vertical" else "orientation_horizontal"
            if not _locator(page, ctx, key).is_checked():
                raise OperationError("bar orientation did not match the recipe")
        if "stacked" in options:
            control = _locator(page, ctx, "stacked_switch")
            visible = _visible(control)
            actual = visible and control.get_attribute("aria-checked") == "true"
            # With one series, stacking has no visual effect and the editor
            # hides its switch. Type, orientation and the sole series have
            # already been verified independently.
            single_series = len(state["metrics"]) == 1 and not state["breakdown"]
            if not (single_series and not visible) and actual != bool(options["stacked"]):
                raise OperationError("bar stacking did not match the recipe")
    elif op.chart_type == "pie" and "donut" in options:
        actual = _locator(page, ctx, "pie_inner_radius").evaluate(
            "e => Number(e.value ?? e.getAttribute('aria-valuenow')) > 0"
        )
        if actual != bool(options["donut"]):
            raise OperationError("pie donut option did not match the recipe")


_RUNNERS = {"add_chart": _run_add_chart}
_VERIFIERS = {"add_chart": _verify_add_chart}


def run(page: Any, op: Any, ctx: OpContext) -> OpResult:
    return _RUNNERS[op.op](page, op, ctx)


def verify(page: Any, op: Any, ctx: OpContext) -> None:
    _VERIFIERS[op.op](page, op, ctx)
