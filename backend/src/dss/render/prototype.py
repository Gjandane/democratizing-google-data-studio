"""Basic boxes and labels for the integration thin slice (task 1.3)."""
from html import escape
from dss.spec.layout import box


def render(spec, *, layer=None):
    theme = spec.theme
    parts = [f'<!doctype html><html><head><meta charset="utf-8"><title>{escape(spec.title)}</title>',
             '<style>body{margin:0}*{box-sizing:border-box}.item{position:absolute;overflow:hidden;padding:12px;border:1px solid #CBD5E1}.component{background:#FFFFFF}.label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}</style></head><body>']
    for page in spec.pages:
        canvas_id = 'id="dss-canvas"' if page.index == 1 else ""
        parts.append(f'<div {canvas_id} data-page="{page.index}" style="position:relative;width:{spec.canvas.width}px;height:{page.height}px;background:{escape(theme.background, quote=True)};color:{escape(theme.text, quote=True)};font-family:{escape(theme.font_family, quote=True)}">')
        for kind, items in (("decoration", page.decorations), ("component", page.components)):
            for item in items:
                b = box(spec.canvas, spec.grid, item.grid, height=page.height)
                label = item.label if kind == "component" else (item.text or item.kind)
                style = f'left:{b["x"]}px;top:{b["y"]}px;width:{b["w"]}px;height:{b["h"]}px;border-radius:{theme.radius}px'
                if layer == "decoration" and kind == "component":
                    style += ';display:none'
                parts.append(f'<div class="item {kind}" data-cid="{escape(item.id, quote=True)}" data-label="{escape(label, quote=True)}" data-kind="{kind}" style="{style}"><div class="label" title="{escape(label, quote=True)}">{escape(item.text or label)}</div></div>')
        parts.append('</div>')
    return ''.join(parts) + '</body></html>'
