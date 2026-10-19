---
type: Procedural Skill
title: Interpret a dashboard reference image
---
# Reference extract
Return `style` (the style profile from the style-extract skill), `element_count`, three short
notes and `items`.

- element_count: how many distinct visible elements (charts, scorecards, tables, controls,
  titles, panels, logos) the image holds. Count honestly even above 24.
- items: one entry per element, at most 24, top-left to bottom-right. If there are more than
  24, still set element_count to the true number; the app asks the user to crop.
- kind: chart (any data display, including scorecards and tables), control (date range,
  dropdown, filter), decoration (title, text, panel, band, logo, divider) or unknown.
- box: x, y, w, h as integers in thousandths of the image width (x, w) and height (y, h),
  0 to 1000; x + w and y + h at most 1000; w and h at least 1.
- label: the element's visible title, or null.
- chart_candidate: the closest of scorecard, time_series, bar, pie, table, pivot_table, geo_map,
  scatter, text, image, date_range, dropdown; for a visible widget none of these fits, a short
  name such as gauge or sankey; null when you cannot tell.
- metric_label, unit (for example USD, %, count), aggregation (sum, avg, count,
  count_distinct, min, max, none) and date_grain (day, week, month, quarter, year): only when
  the image shows them; otherwise null.
- confidence: high, medium or low for the item as a whole.
- palette_notes, type_notes, spacing_notes: one plain sentence each (colors, typography,
  density and spacing); empty when nothing applies.
