"""Chart insertion and setup operations for Data Studio."""

from __future__ import annotations

import math
import re
from typing import Any, Callable

from dsengine.ops import OpContext, OpResult, OperationError

HANDLED_OPS = {"add_chart"}

_CHART_BUTTONS = {
    "scorecard": "scorecard_chart",
    "time_series": "time_series_chart",
    "area": "area_chart",
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

# Charts drawn over date_dimension as their first dimension (recipe 1.3 adds area).
_DATE_AXIS = {"time_series", "area"}

# Gallery buttons by (stacked, 100% stacked); Style switches read each variant back
# (live 2026-10-24: Show stack / Stacked bars, then 100% stacking once stacked).
_AREA_BUTTONS = {(False, False): "area_chart", (True, False): "stacked_area_chart",
                 (True, True): "percent_stacked_area_chart"}
_STACK_LABELS = {(False, False): "", (True, False): "stacked ", (True, True): "100% stacked "}

_GEO_TYPES = {"country": "Country", "region": "Country subdivision (1st level)", "city": "City"}

# Data type -> Date & Time labels (live 2026-10-23); the menu offers no "Year Week".
_DATE_GRANULARITIES = {"day": "Date", "week": "ISO Year Week", "month": "Year Month",
                       "quarter": "Year Quarter", "year": "Year"}


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
    if op.chart_type in _DATE_AXIS and getattr(op, "date_dimension", None):
        dimensions = [op.date_dimension] + [f for f in dimensions if f != op.date_dimension]
    return dimensions, columns


def _metric_groups(page: Any, ctx: OpContext, op: Any, metrics: list) -> list[tuple[Any, list]]:
    if op.chart_type == "scatter":
        keys = ["scatter_x_group", "scatter_y_group", "scatter_size_group"]
        return [(_locator(page, ctx, key), metrics[i:i + 1]) for i, key in enumerate(keys)]
    return [(_locator(page, ctx, "metric_group_any"), metrics)]


def _data_type(page: Any, ctx: OpContext, menu_key: str, label: str, *,
               change: bool, subject: str) -> str:
    """Set (change) or read the first dimension's Data type in the chart; return the type read.

    menu_key: the Data type menu entry whose submenu offers label (Geo, Date & Time).
    """
    group = _locator(page, ctx, "dimension_group_any")
    group.locator(ctx.selectors["dimension_type_button"]).first.click(timeout=ctx.timeout_ms())
    control = _locator(page, ctx, "data_type_control")
    try:
        _wait_visible(control, ctx, f"{subject} data type is unavailable")
        # The control reads "<type>\narrow_drop_down": the second line is its icon.
        actual = control.inner_text().splitlines()[0].strip()
        if change and actual != label:
            control.click(timeout=ctx.timeout_ms())
            _locator(page, ctx, menu_key).hover(timeout=ctx.timeout_ms())
            _locator(page, ctx, "last_overlay").get_by_role("menuitem", name=label, exact=True).click(timeout=ctx.timeout_ms())
            actual = control.inner_text().splitlines()[0].strip()
    finally:
        # One Escape closes the field editor with any type menus still open.
        page.keyboard.press("Escape")
    return actual


def _geo_type(page: Any, ctx: OpContext, op: Any, *, change: bool) -> None:
    value = (getattr(op, "options", {}) or {}).get("geo_type")
    if value is None:
        return
    if not isinstance(value, str) or value not in _GEO_TYPES:
        raise OperationError("geo_type must be country, region or city")
    if _data_type(page, ctx, "geo_type_menu", _GEO_TYPES[value],
                  change=change, subject="geo dimension") != _GEO_TYPES[value]:
        raise OperationError(f"geo dimension could not map to {value}")


def _granularity(op: Any) -> str | None:
    """A time series' or area's date_granularity, checked before any UI action (recipe 1.2)."""
    value = (getattr(op, "options", {}) or {}).get("date_granularity")
    if op.chart_type not in _DATE_AXIS or value is None:
        return None
    if not isinstance(value, str) or value not in _DATE_GRANULARITIES:
        raise OperationError("date_granularity must be day, week, month, quarter or year")
    return value


def _date_granularity(page: Any, ctx: OpContext, op: Any, *, change: bool) -> None:
    """Set or verify the date dimension's Date & Time type; without the option, leave it."""
    value = _granularity(op)
    if value is None:
        return
    label = _DATE_GRANULARITIES[value]
    subject = f"{op.chart_type.replace('_', ' ')} date dimension"
    actual = _data_type(page, ctx, "date_type_menu", label, change=change, subject=subject)
    if actual != label:
        raise OperationError(f"{subject} type is {actual}, not {label}")


def _stacking(op: Any) -> tuple[bool, bool] | None:
    """(stacked, 100% stacked) asked of a bar or area, checked before any UI action.

    stacked_percent implies stacked. An area always has a variant (plain by default);
    a bar without either option keeps what its gallery button gives (None).
    """
    if op.chart_type not in {"bar", "area"}:
        return None
    options = getattr(op, "options", {}) or {}
    if any(not isinstance(options.get(key, False), bool) for key in ("stacked", "stacked_percent")):
        raise OperationError("stacked and stacked_percent must be true or false")
    if op.chart_type == "bar" and not {"stacked", "stacked_percent"} & options.keys():
        return None
    percent = options.get("stacked_percent", False)
    return options.get("stacked", False) or percent, percent


def _variant(op: Any, stacking: tuple[bool, bool]) -> str:
    """The variant's name as the gallery spells it: "Area", "Stacked area", "100% stacked bar"."""
    return (_STACK_LABELS[stacking] + op.chart_type).capitalize()


def _gallery_key(op: Any, stacking: tuple[bool, bool] | None) -> str:
    """The selector key of the chart gallery button that inserts op's variant."""
    options = getattr(op, "options", {}) or {}
    if op.chart_type == "bar":
        key = "vertical_bar_chart" if options.get("orientation") == "vertical" else "bar_chart"
        return {(True, True): "percent_stacked_", (True, False): "stacked_"}.get(stacking, "") + key
    if op.chart_type == "area":
        return _AREA_BUTTONS[stacking]
    if op.chart_type == "pie" and options.get("donut"):
        return "donut_chart"
    return _CHART_BUTTONS[op.chart_type]


def _stack_keys(op: Any) -> tuple[str, str]:
    return ("stacked_switch" if op.chart_type == "bar" else "area_stack_switch",
            "percent_stack_switch")


def _set_stacking(page: Any, ctx: OpContext, op: Any, stacking: tuple[bool, bool]) -> None:
    """Match the Style tab's stacking switches to stacking (the gallery variant normally has).

    Each is set only while shown: one series hides stacking, and 100% stacking shows
    only once stacked. Verification reads the variant back either way.
    """
    for key, enabled, option in zip(_stack_keys(op), stacking, ("stacking", "100% stacking")):
        if _visible(_locator(page, ctx, key)):
            _set_switch(page, ctx, key, enabled, option)


def _read_stacking(page: Any, ctx: OpContext, op: Any) -> tuple[bool, bool] | None:
    """The (stacked, 100% stacked) the open Style tab shows.

    None when one series hides the stacking switch: then the inserted type is all there is.
    """
    stack_key, percent_key = _stack_keys(op)
    stack, percent = _locator(page, ctx, stack_key), _locator(page, ctx, percent_key)
    if not _visible(stack):
        single = len(getattr(op, "metrics", None) or []) == 1 and not getattr(op, "breakdown", None)
        return None if single else (False, False)
    stacked = stack.get_attribute("aria-checked") == "true"
    return stacked, stacked and _visible(percent) and percent.get_attribute("aria-checked") == "true"


def _verify_stacking(page: Any, ctx: OpContext, op: Any, stacking: tuple[bool, bool]) -> None:
    """Read the variant back from the open Style tab and log it.

    With one series, stacking has no visual effect and the editor hides its switch:
    type, orientation and the sole series are verified independently.
    """
    found = _read_stacking(page, ctx, op)
    if found is not None and found != stacking:
        raise OperationError(f"{op.chart_type} variant read back {_variant(op, found)}, "
                             f"not {_variant(op, stacking)}")
    ctx.events.emit("log", level="info", message=f"{op.id}: {_variant(op, stacking)}"
                    + ("" if found else " (one series: stacking not shown)"))


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
                  option: str, *, pick: Callable[[list[str]], str | None] | None = None,
                  pane_key: str = "last_overlay") -> str:
    """Choose value in a menu control and return the value chosen.

    pick: given the offered labels, the one to choose instead of value (None keeps value).
    pane_key: the overlay that holds the options.
    """
    control = _locator(page, ctx, control_key)
    _wait_visible(control, ctx, f"Data Studio option {option} is unavailable")
    control.click(timeout=ctx.timeout_ms())
    # Another pane can already be visible (one reading "Autogenerate" on the
    # release table, 2026-10-21), so wait until the last pane is the option list.
    pane = _locator(page, ctx, pane_key)
    _poll(page, ctx, lambda: _visible(pane.locator(ctx.selectors["dropdown_option"]).first),
          f"Data Studio option {option} menu did not open")
    if pick:
        value = pick(pane.locator(ctx.selectors["dropdown_option"]).evaluate_all(
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
    stacking = _stacking(op)
    if not options and not stacking:
        return None
    if op.chart_type == "scorecard" and "compact_numbers" in options:
        _locator(page, ctx, "style_tab").click(timeout=ctx.timeout_ms())
        _set_switch(page, ctx, "compact_numbers_switch",
                    bool(options["compact_numbers"]), "compact numbers")
    elif op.chart_type in {"bar", "area"}:
        _locator(page, ctx, "style_tab").click(timeout=ctx.timeout_ms())
        if op.chart_type == "bar" and "orientation" in options:
            key = "orientation_vertical" if options["orientation"] == "vertical" else "orientation_horizontal"
            control = _locator(page, ctx, key)
            _wait_visible(control, ctx, "bar chart orientation control is unavailable")
            control.check(timeout=ctx.timeout_ms())
        if stacking:
            _set_stacking(page, ctx, op, stacking)
    elif op.chart_type == "table" and "rows_per_page" in options:
        _locator(page, ctx, "setup_tab").click(timeout=ctx.timeout_ms())
        # Rows per page is a fixed menu (1, 5, 10, 20, 25, 50, 100, 250, ...).
        rows = str(options["rows_per_page"])
        applied = _set_dropdown(page, ctx, "rows_per_page_control", rows, "rows per page",
                                pick=lambda offered: _nearest_option(rows, offered))
        if applied != rows:
            ctx.warn(f"{op.id}: rows_per_page {rows} is not offered; applied {applied}")
        return applied
    return None


# Scorecards (recipe 1.1). Labels > Font size defaults to "auto", which scales the
# value into what the title leaves: 10 px under a 34 px title at h=84 (live
# 2026-10-22). Data Studio's title is its font size + 16 px of padding tall.
_SCORECARD_FIT = """(component, [valueKey, titleKey]) => {
    const value = component.querySelector(valueKey);
    if (!value || !value.innerText.trim()) return null;
    const box = component.getBoundingClientRect(), own = value.getBoundingClientRect();
    const range = document.createRange();
    range.selectNodeContents(value);
    const text = range.getBoundingClientRect(), title = component.querySelector(titleKey);
    const below = title ? title.getBoundingClientRect().bottom : box.top;
    return {size: getComputedStyle(value).fontSize,
            title: title && getComputedStyle(title).fontSize,
            box: [own.left, own.top, own.right, own.bottom],
            over: Math.ceil(Math.max(0, own.bottom - box.bottom, below - own.top)),
            wide: text.left < box.left || text.right > box.right};
}"""


def _largest_size(offered: list[str], limit: int) -> str | None:
    """The largest offered "<n>px" size not above limit."""
    sizes = [int(text[:-2]) for text in offered if text.endswith("px") and text[:-2].isdigit()]
    return f"{max(size for size in sizes if size <= limit)}px" if any(
        size <= limit for size in sizes) else None


def _scorecard_value_size(height: int, offered: list[str]) -> str | None:
    """The prototype's clamp(16, h - 28, 36) px, as the largest offered size not above it."""
    return _largest_size(offered, min(max(16, height - 28), 36))


def _scorecard_fit(component: Any, ctx: OpContext) -> dict | None:
    return component.evaluate(_SCORECARD_FIT, [ctx.selectors["scorecard_value"],
                                               ctx.selectors["scorecard_title"]],
                              timeout=ctx.timeout_ms())


_VERIFY_RESERVE_S = 5  # op budget kept for verification after waiting on a render
_EDIT_RESERVE_S = 12  # and, before the Style edits, for the edits as well


def _settled_fit(page: Any, ctx: OpContext, component: Any, ready: Callable[[dict], bool],
                 *, reserve: float = _VERIFY_RESERVE_S) -> dict | None:
    """The rendered value's fit once ready() holds and one poll later it is unchanged.

    None when it doesn't settle while the op budget has more than reserve seconds:
    a source error can leave the value unrendered, which mustn't fail the chart.
    """
    previous = None
    while True:
        fit = _scorecard_fit(component, ctx)
        if fit is not None and ready(fit) and fit == previous:
            return fit
        previous = fit
        remaining = ctx.remaining_s() - reserve
        if remaining <= 0:
            return None
        page.wait_for_timeout(min(250, max(1, int(remaining * 1000))))


def _px(text: str | None) -> int | None:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)px", (text or "").strip())
    return int(float(match.group(1))) if match else None


def _title_limit(height: int, size: str) -> int:
    """The largest title font size that leaves the value room below it.

    Measured live (2026-10-22): the title is its font size + 16 px tall; with no top
    padding the value starts 1 px lower, and its line is 1.15 x its size (Arial).
    """
    return height - 17 - round(1.15 * (_px(size) or 0))


def _shrink_title(page: Any, ctx: OpContext, limit: int) -> str:
    limit = max(8, limit)
    return _set_dropdown(page, ctx, "style_title_size", f"{limit}px", "title font size",
                         pane_key="option_overlay",
                         pick=lambda offered: _largest_size(offered, limit))


def _style_scorecard(page: Any, ctx: OpContext, op: Any, component: Any, height: int) -> dict:
    """Size the value to the box; with a title, hide the metric name and fit the value below it.

    Style comboboxes show a tooltip pane after the option list opens, so their
    menus are found by the pane holding options, not by the last pane.
    """
    # Edit a rendered value: in 2 of 7 live runs a value still loading when the
    # edits began never rendered (order_items, 2026-10-22).
    _settled_fit(page, ctx, component, lambda found: True, reserve=_EDIT_RESERVE_S)
    _locator(page, ctx, "style_tab").click(timeout=ctx.timeout_ms())
    size = _set_dropdown(page, ctx, "scorecard_value_size", f"{min(max(16, height - 28), 36)}px",
                         "scorecard value size", pane_key="option_overlay",
                         pick=lambda offered: _scorecard_value_size(height, offered))
    titled = bool(getattr(op, "title", None))
    title = None
    if titled:
        _set_switch(page, ctx, "scorecard_hide_name", True, "hide field name")
        # The default 8 px top padding leaves a 36 px value touching an 84 px box's border.
        _set_dropdown(page, ctx, "scorecard_padding_top", "0px", "scorecard top padding",
                      pane_key="option_overlay")
        # The title is the one thing above the value: shrink it when the value can't fit,
        # without waiting on the value's query.
        current = _px(_locator(page, ctx, "style_title_size").inner_text(timeout=ctx.timeout_ms()))
        if current is not None and current > max(8, _title_limit(height, size)):
            title = _shrink_title(page, ctx, _title_limit(height, size))
    fit = _settled_fit(page, ctx, component,
                       lambda found: found["size"] == size and title in {None, found["title"]})
    if titled and fit and fit["over"] > 0 and (_px(fit["title"]) or 8) > 8:
        title = _shrink_title(page, ctx, _px(fit["title"]) - fit["over"])
        fit = _settled_fit(page, ctx, component, lambda found: found["title"] == title)
    result = {"value_size": size, "hide_name": titled, "title_size": title,
              "fits": bool(fit) and fit["over"] <= 0 and not fit["wide"]}
    if not fit:
        ctx.warn(f"{op.id}: scorecard value did not render; its fit was not checked")
    elif not result["fits"]:
        ctx.warn(f"{op.id}: scorecard value {size} does not fit "
                 f"{'below the title ' if titled else ''}in its {height} px box")
    ctx.events.emit("log", level="info",
                    message=f"{op.id}: scorecard value {size}" + (f", title {title}" if title else ""))
    return result


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
    _granularity(op)
    stacking = _stacking(op)
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
        _locator(page, ctx, "add_chart").click(timeout=ctx.timeout_ms())
        gallery = _locator(page, ctx, "chart_gallery")
        _wait_visible(gallery, ctx, "chart type gallery did not open")
        gallery.locator(ctx.selectors[_gallery_key(op, stacking)]).click(timeout=ctx.timeout_ms())
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
    _date_granularity(page, ctx, op, change=True)

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
    if date_dimension and op.chart_type not in _DATE_AXIS:
        date_group = _locator(page, ctx, "date_range_dimension_group")
        _wait_visible(date_group, ctx, "chart date dimension Setup group is unavailable")
        _set_fields(page, ctx, date_group, [date_dimension])

    sort = None if inherent_sort else getattr(op, "sort", None)
    _set_sort(page, ctx, sort)
    rows_per_page = _set_title_and_options(page, ctx, op)
    scorecard = (_style_scorecard(page, ctx, op, component, target[3])
                 if op.chart_type == "scorecard" else None)
    ctx.state[op.id] = {
        "target": target,
        "chart_index": before,
        "dimensions": dimensions,
        "columns": columns,
        "metrics": [(str(_value(metric, "field", "")), str(_value(metric, "agg", "none")))
                    for metric in metrics],
        "date_dimension": date_dimension if op.chart_type not in _DATE_AXIS else None,
        # The verified first dimension already proves an inherent date sort.
        "sort": (_value(sort, "field"), _value(sort, "order")) if sort else None,
        "title": getattr(op, "title", None),
        "breakdown": breakdown,
        "rows_per_page": rows_per_page,
        "scorecard": scorecard,
    }
    return OpResult()


def _verify_scorecard(page: Any, ctx: OpContext, component: Any, applied: dict) -> None:
    """Read the applied value size (and title size) back from the open Style tab."""
    # A closing menu's option labels can briefly join the combobox text.
    for key, size in (("scorecard_value_size", applied["value_size"]),
                      ("style_title_size", applied["title_size"])):
        if size:
            _poll(page, ctx, lambda: _locator(page, ctx, key).inner_text(
                timeout=ctx.timeout_ms()).strip() == size, f"scorecard {key} did not read back {size}")
    if applied["hide_name"] and _locator(page, ctx, "scorecard_hide_name").get_attribute(
            "aria-checked") != "true":
        raise OperationError("scorecard field name is shown under its title")
    if applied["fits"]:
        def inside() -> bool:
            fit = _scorecard_fit(component, ctx)
            return bool(fit) and fit["size"] == applied["value_size"] and fit["over"] <= 0                 and not fit["wide"]
        _poll(page, ctx, inside, "scorecard value is not inside its box below the title")


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
    _date_granularity(page, ctx, op, change=False)

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
    stacking = _stacking(op)
    if state["title"] or (options and op.chart_type != "table") or state.get("scorecard") or stacking:
        _locator(page, ctx, "style_tab").click(timeout=ctx.timeout_ms())
    scorecard = state.get("scorecard")
    if scorecard:
        _verify_scorecard(page, ctx, component, scorecard)
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
    if stacking:
        _verify_stacking(page, ctx, op, stacking)
    if op.chart_type == "pie" and "donut" in options:
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
