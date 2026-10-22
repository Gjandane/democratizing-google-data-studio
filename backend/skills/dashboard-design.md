---
type: Procedural Skill
title: Design a dashboard page around native components
---
# Dashboard design

## The look (reference)
A calm, light analytics page, data first:
- Page: theme `background` (a light gray), padding 24 px, 16 px gaps between cards.
- Header (no card): the dashboard title bold, 26-30 px, theme `text`; under it a one-line
  subtitle 14-15 px in theme `muted` saying what the page answers. Page 1 uses the dashboard
  title; later pages use their page name as the title.
- Cards: theme `surface` (white), border-radius 12-16 px, a 1 px border a little darker than the
  page (for example `#E2E8F0`) and one soft shadow such as `0 1px 3px rgba(15,23,42,.06)`.
  Padding 16-20 px. Same radius and shadow on every card.
- KPI cards (one per scorecard), in one row at the top: a 44-48 px rounded square icon tile in a
  pastel tint (the accent or a palette color mixed about 12% into white, for example
  `color-mix(in srgb, #4F46E5 12%, white)`), the icon in that full color, then the scorecard slot
  filling the rest of the card. Give each KPI card a different palette tint.
- Section cards (one per chart, table or map): a title row (the component label, 16 px, weight
  600, theme `text`), 12 px gap, then the slot filling the card's width.
- Filters (date range, dropdown): a slim card or a bare slot in the header row, right-aligned.
- Text and image components: a plain card around the slot, no title.
- Layout by importance: KPIs first, then the main trend or comparison wide, then supporting
  charts in two columns, tables full width at the bottom. Align card edges to one column grid
  (CSS grid with `grid-template-columns` works well) and keep the page's sections balanced.

Use sentence case, plain words and the component labels as titles. No all-caps eyebrows, no
decorative gradients, no emoji, no numbering unless the content is a sequence. Contrast: text on
white at least 4.5:1 (theme `text` and `muted` pass).

## Slots
- One empty `<div data-slot="<component id>"></div>` per component on the page, nothing inside.
  Code makes slots transparent and Data Studio draws the component exactly over the slot's box.
- A slot needs a definite size: set `height` (at least `min_h`) and a width of at least `min_w`
  (or let it stretch in a grid/flex cell that is at least that wide).
- Slots never overlap each other, stay inside the page, and nothing else (text, icon, svg,
  border line) may enter a slot's box. A card behind a slot is fine.
- A scorecard slot is the card's value area: at least its minimum, typically 56-80 px tall.

## Allowed markup and CSS
- Tags: div span section header footer main article aside nav h1-h6 p strong b em i small sup
  sub br hr ul ol li figure figcaption, and inline `<svg>` with g path circle ellipse line
  polyline polygon rect. Attributes: `class`, `style`, `data-slot` on div, `data-icon` on i.
  Everything else is removed (scripts, links, images, buttons, inputs, tables, `<use>`).
- One `<style>` block first. Class selectors and the page root as `body` (`body{...}` styles
  the page root). Properties: layout (display, grid, flex, gap, position static/relative/absolute,
  sizes, margin, padding, overflow), background colors and gradients, borders, radius,
  box-shadow, color, font-size/weight/style, line-height, letter-spacing, text-align,
  white-space, SVG fill and stroke. Functions: rgb/hsl/color-mix/gradients/calc/min/max/clamp/
  var/repeat/minmax. Removed: `url()`, any `@` rule, `!important`, viewport units, `position:
  fixed`, fonts other than the theme font.

## Icons
`<i data-icon="name"></i>` with a name from the icon list becomes that Lucide icon (24 px,
stroke `currentColor`: set `color` on the tile). Pick the icon by meaning (users for customers,
dollar-sign or wallet for revenue, shopping-cart for orders, truck for delivery, clock for time,
percent for rates, trending-up for growth). An unknown name is an error; if nothing fits, draw a
small inline `<svg>` of plain shapes inside the `<i>` instead.

## Text fit
Every text must fit its box with no overflow or clipping, at 12 px or larger. Give titles room
(`white-space: nowrap` only when the box is wide enough), let long subtitles wrap, and never set
fixed heights on text boxes that could be too small. Keep text out of slots.

## Page height and footer
The page is as tall as its content: do not set a page height. When `synthetic_footer` is true,
code draws a 64 px "Synthetic sample data" strip below your page: keep everything inside your
content (no negative margins or absolute elements below it).
