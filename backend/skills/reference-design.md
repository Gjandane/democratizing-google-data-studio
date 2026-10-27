---
type: Procedural Skill
title: Brief a dashboard page from a reference image
---
# Reference design brief

The coder reads only your brief, the slot list and the images. Write what you see as concrete,
buildable instructions: pixels, fractions of the canvas width, hex colors, font sizes and weights.
Short sentences; no adjectives without a value.

## Read the reference
- Regions: the page's bands and columns from top to bottom (header, rows, side panels, footer)
  and each one's share of the canvas width and of the page height, for example "left column 28%,
  centre 44%, right column 28%; header 120 px".
- Hierarchy: what the eye meets first, what is big, what is small. The headline's size and
  weight, the subtitle, section titles, small print.
- Type scale: sizes in px, weights, letter spacing, case, line height; the theme font only.
- Palette: page background, panel/card fills, borders, text, accents, as hex from the image and
  the palette notes. Say where each color goes.
- Treatments: card radius, borders, shadows, gradients, dividers, glows, transparency, spacing
  between panels and their inner padding.

## Map the reference to the approved slots
- Each approved component takes the place of the reference element it was approved for: the
  bindings name the observation (its kind, type and title) or the requirement. Put its slot in
  that element's region with that element's proportions.
- A substitution (an accepted alternative) takes the replaced element's place in the native type
  the decision names. A dropped element and any element with no approved component get no slot:
  leave its area to the layout, or neutral decoration (a panel, a rule, a heading) with no data.
- Size every slot at least its `min_w` x `min_h` at the page's canvas width. A filter's slot is
  slim; a scorecard's slot is the value area of its card.
- Every component draws its own title, values, axes and legend. Never ask for a title row,
  caption, legend, axis or value text for a component in the background.
- When `synthetic_footer` is true, code draws a 64 px "Synthetic sample data" strip below the
  page: brief nothing below the content.

## Modes
- recreate: match the screenshot's structure, region by region, with the approved slots and the
  explicit substitutions. Say which substitutions change the look.
- style: borrow only the visual treatment (palette, type, panels, spacing, art) and arrange the
  approved components in a layout that suits them. A style reference imports no charts or controls.

## Nothing fake
Never brief a chart, slider, split bar, small multiples, legend, data marks, counters, sample
numbers or a data-bearing map in the background to imitate a component that has no slot. Static
art is decoration, never data: a globe or world map from the art list may sit where the reference
shows one (outside every slot), colored with CSS on `.land`, a continent, `.c-<ISO alpha-3>`,
`.ocean` and `.outline`. Icons only by their listed names.

## Later pages and revisions
- Page 2 and later: keep page 1's width and visual language (its stylesheet is listed) and adapt
  it to this page's own components. Never repeat page 1's charts or regions that have no slot here.
- Revise run: apply the comments to the previous page and brief the whole page again; keep every
  region, size and treatment the comments do not change.

## Output
- `overall`: the page in reading order: canvas width, regions with proportions, the header,
  palette with hex, type scale, card treatment, spacing, art and icons with their placement.
- `slots`: one entry per approved component id, in reading order: its region, position and size
  (px or a share of its region, at least its minimum), its card or panel, and how it lines up
  with its neighbours.
- Plain prose with the full design intent. No HTML or CSS code blocks, no URLs, no data.
