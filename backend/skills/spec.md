---
type: Procedural Skill
title: Dashboard Spec
---
# Dashboard specification
Write exactly one page, index 1. Use a 1200 px canvas; page height equals canvas height.
Grid: columns 12, row_height 20, gutter 16, margin 24. Integer grid positions start at 1.
All component and decoration IDs are unique lowercase snake_case prefixed p1_.
Calculate pixel bounds: column width=(1200-48-11*16)/12; x=24+(col-1)*(column width+16),
y=24+(row-1)*20; width=w*column width+(w-1)*16; height=h*20-16.
Keep all boxes inside the canvas, and components separated. Decorations may underlay charts.
Text decorations must fit after wrapping and padding; clipped text is a validation error.
Title/subtitle defaults: 28px bold / 18px normal, zero padding; other text: 16px, 16px padding.
Line height is 1.25 times the effective pixel font size. Newlines are preserved and long words wrap.
font_size/font-size accepts positive pixel numbers or px strings; font_weight/font-weight
accepts normal, bold or 100..900. A default one-line title needs h>=3 (44px), never h=2 (24px).
Allocate extra height for larger or multiline headings; keep other items and the synthetic footer clear.
Use only the supplied allowed catalog types and its exact slot roles, counts and minimum sizes.
Copy the supplied datasource and build identity exactly; do not invent fields.
Each high priority question qN must appear in a component question_ref. Bind dedicated
date_dimension and field slots as the supplied catalog requires. Field types and roles constrain binding.
Respect design.md, brief.md and KPI definitions. Never generate HTML, SQL or recipe lines.
Theme background, surface, text, muted, accent and every palette item use exactly #RRGGBB
(# plus six hexadecimal digits). Keep the # prefix; no short hex, names, alpha or CSS functions.
Return a complete JSON DashboardSpec. Repair diagnostics are a list of path/message objects;
correct them all while preserving the required datasource. At most two repair turns are available.
