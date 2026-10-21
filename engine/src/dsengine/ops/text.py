"""Text boxes and ordinary uploaded images."""

from typing import Any

from dsengine.ops import OpContext, OpResult, OperationError
from dsengine.ops.charts import (
    _EDGE, _chart_box, _click_workspace, _geometry, _locator, _place_chart, _poll, _reveal,
    _source_fields,
)
from dsengine.ops.report import _place_component, _prepare_image

HANDLED_OPS = {"add_text", "add_image"}


def _select_text(page: Any, component: Any, ctx: OpContext) -> Any:
    component.dblclick(position={"x": 12, "y": 12}, timeout=ctx.timeout_ms())
    editor = component.locator(ctx.selectors["text_editor"])
    editor.click(timeout=ctx.timeout_ms())
    editor.press("Control+a", timeout=ctx.timeout_ms())
    return editor


def text_styles(component: Any, ctx: OpContext) -> list[dict]:
    return component.locator(ctx.selectors["text_viewer"]).evaluate("""e => {
        const walker = document.createTreeWalker(e, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
        const result = []; let node;
        while (node = walker.nextNode()) {
            if (node.nodeType === Node.ELEMENT_NODE && node.tagName !== 'BR') continue;
            if (node.nodeType === Node.TEXT_NODE && !node.textContent.length) continue;
            const s = getComputedStyle(node.parentElement);
            result.push({size: parseFloat(s.fontSize), color: s.color,
                         bold: Number(s.fontWeight) >= 600, align: s.textAlign});
        }
        return result;
    }""")


def text_content(component: Any, ctx: OpContext) -> str:
    """Read logical lines, treating a lone BR in a blank paragraph as its placeholder."""
    return component.locator(ctx.selectors["text_viewer"]).evaluate(r"""root => {
        const block = e => e.nodeType === Node.ELEMENT_NODE && ['DIV', 'P'].includes(e.tagName);
        function read(e) {
            if (e.nodeType === Node.TEXT_NODE) return e.textContent;
            if (e.tagName === 'BR') return '\n';
            const children = Array.from(e.childNodes);
            if (children.length === 1 && children[0].nodeName === 'BR') return '';
            let value = '';
            children.forEach((child, i) => {
                if (block(child) && i > 0 && !block(children[i - 1])) value += '\n';
                value += read(child);
                if (block(child) && i < children.length - 1) value += '\n';
            });
            return value;
        }
        return read(root);
    }""")


def _format(page: Any, component: Any, op: Any, ctx: OpContext) -> None:
    from dsengine.ops.style import set_color

    for key in ("font_size", "color", "bold", "align"):
        value = getattr(op, key, None)
        if value is None:
            continue
        _select_text(page, component, ctx)
        if key == "font_size":
            control = _locator(page, ctx, "text_font_size")
            control.fill(str(value), timeout=ctx.timeout_ms())
            control.press("Enter", timeout=ctx.timeout_ms())
            page.keyboard.press("Escape")
        elif key == "color":
            set_color(page, _locator(page, ctx, "text_color"), value, ctx)
        elif key == "bold":
            button = _locator(page, ctx, "text_bold")
            if (button.get_attribute("aria-pressed") == "true") != value:
                button.click(timeout=ctx.timeout_ms())
        else:
            _locator(page, ctx, "text_align").click(timeout=ctx.timeout_ms())
            _locator(page, ctx, f"text_align_{value}").click(timeout=ctx.timeout_ms())
    page.keyboard.press("Escape")
    _locator(page, ctx, "selection_mode").click(timeout=ctx.timeout_ms())
    _click_workspace(page, ctx, _locator(page, ctx, "canvas"))


def run(page: Any, op: Any, ctx: OpContext) -> OpResult:
    _source_fields(page, ctx)
    path = ctx.recipe.asset_path(op.path) if op.op == "add_image" else None
    if path is not None and not path.is_file():
        raise OperationError("image asset was not found")
    target, clamped = _chart_box(op, ctx)
    if clamped:
        ctx.warn(f"{op.id}: {op.op} box was clamped to the canvas")
    components = _locator(page, ctx, "components")
    state = ctx.state.setdefault(op.id, {"component_index": components.count()})
    before = state["component_index"]
    canvas = _locator(page, ctx, "canvas")
    if components.count() == before:
        if path is not None:
            _locator(page, ctx, "image").click(timeout=ctx.timeout_ms())
            with page.expect_file_chooser(timeout=ctx.timeout_ms()) as chooser:
                _locator(page, ctx, "upload_image").click(timeout=ctx.timeout_ms())
            chooser.value.set_files(str(path), timeout=ctx.timeout_ms())
        else:
            _locator(page, ctx, "text_button").click(timeout=ctx.timeout_ms())
            _locator(page, ctx, "drawing").wait_for(state="visible", timeout=ctx.timeout_ms())
            if canvas.bounding_box() is None:
                raise OperationError("report canvas is not visible")
            # Draw the part of the box that fits in view; placement below resizes the rest.
            origin = _reveal(canvas, ctx, target[0], target[1],
                             target[0] + target[2], target[1] + target[3])
            start = (origin["x"] + target[0], origin["y"] + target[1])
            page.mouse.move(*start)
            page.mouse.down()
            page.mouse.move(min(start[0] + target[2], origin["view"]["right"] - _EDGE),
                            min(start[1] + target[3], origin["view"]["bottom"] - _EDGE), steps=10)
            page.mouse.up()
        _poll(page, ctx, lambda: components.count() == before + 1,
              "insertion did not add exactly one component")
    component = components.nth(before)
    if path is not None:
        image = component.locator(ctx.selectors["image_content"])
        image.wait_for(state="visible", timeout=ctx.timeout_ms())
        _poll(page, ctx, lambda: image.evaluate("e => e.naturalWidth") > 0,
              "image did not finish loading")
        _prepare_image(page, component, ctx)
        _place_component(page, ctx, component, canvas, target)
    else:
        editor = _select_text(page, component, ctx)
        editor.fill(op.text, timeout=ctx.timeout_ms())
        _format(page, component, op, ctx)
        _place_chart(page, ctx, component, canvas, target)
        _locator(page, ctx, "selection_mode").click(timeout=ctx.timeout_ms())
        _click_workspace(page, ctx, canvas)
    state["target"] = target
    return OpResult()


def verify(page: Any, op: Any, ctx: OpContext) -> None:
    from dsengine.ops.style import rgb

    state = ctx.state[op.id]
    components = _locator(page, ctx, "components")
    if components.count() != state["component_index"] + 1:
        raise OperationError("component count did not increase by one")
    component = components.nth(state["component_index"])
    _poll(page, ctx, lambda: all(abs(a - e) <= 4 for a, e in zip(
        _geometry(component), state["target"])), "component box did not match the recipe")
    if op.op == "add_image":
        if component.locator(ctx.selectors["image_content"]).evaluate("e => e.naturalWidth") <= 0:
            raise OperationError("image did not load")
        return
    viewer = component.locator(ctx.selectors["text_viewer"])
    viewer.wait_for(state="visible", timeout=ctx.timeout_ms())
    if text_content(component, ctx) != op.text:
        raise OperationError("text content did not match the recipe")
    expected = {"size": getattr(op, "font_size", None),
                "color": rgb(op.color) if getattr(op, "color", None) else None,
                "bold": getattr(op, "bold", None), "align": getattr(op, "align", None)}
    def matches():
        styles = text_styles(component, ctx)
        return styles and all(value is None or all(s[key] == value for s in styles)
                              for key, value in expected.items())
    _poll(page, ctx, matches, "rendered text formatting did not match the recipe")
