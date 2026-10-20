---
type: Procedural Skill
title: Revise a prototype from comments
---
# Revise
Return changes with exactly one entry per comment, comment_index 0..N-1 in original order.
Each entry contains patch (RFC 6902 operations) and unsupported_type (null normally).
Use the provided absolute JSON pointer paths. Apply each entry after all earlier entries;
array indices therefore reflect earlier removals. The last comment wins for a shared property.
Change only the commented item. If a resize/move creates a component overlap, move the
neighbour's grid col/row just enough to avoid it. Do not resize, restyle or change a neighbour's
content. Decorations may overlap components and do not require neighbour moves.
No global settings, datasource, canvas, ids or list insertions/reordering may be patched.
For unsupported chart requests set unsupported_type to the requested type and patch to [].
Never silently substitute a different type. The code will explain the available Data Studio types.
For no necessary change return an empty patch. Use add for a missing style key (e.g.
/pages/0/decorations/0/style/font_size); replace requires that the property already exists.
Bigger text normally means font size, not a larger grid.
For a chart accent or series color request, patch only the target component's colors list.
Use #172554 for a qualitative dark blue accent. Use add for colors (replace is also valid
when the property exists). Preserve the target's geometry, data bindings and other components.
Components with colors omitted or null inherit the theme palette. Colors are chart-only,
with 1 to 20 six-digit hexadecimal colors; never patch the global theme for a component comment.
Renderer defaults when decoration style omits font_size: title 28px, subtitle 18px, other
text 16px. A request for bigger text must increase its effective size above the current
explicit value or that default. Set numeric style.font_size in pixels; font_weight,
color, background_color and border_radius are also supported decoration style keys.
Expand a chart's grid when requested, respecting canvas bounds, catalog minimum sizes and
non-overlap. Grid has 12 columns,
20px row height, 16px gutter and 24px margin. Keep every high-priority question reference.
One repair turn is available. Return the complete corrected changes batch after diagnostics.
