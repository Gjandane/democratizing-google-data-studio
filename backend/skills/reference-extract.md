---
type: Procedural Skill
title: Analyze a dashboard reference image
---
# Reference extract
Return `style` (the style profile from the style-extract skill) and three short notes. In style
mode return nothing else. In recreate mode also return `element_count` and `items`.

- palette_notes, type_notes, spacing_notes: one plain sentence each (colors, typography,
  density and spacing); empty when nothing applies.
- element_count: how many distinct visible elements (charts, scorecards, tables, controls,
  legends, titles, text blocks, images) the image holds. Count honestly even above 24.
- items: one entry per visible element, 1 to 24. If there are more than 24, still set
  element_count to the true number; the app asks the user to crop.
- label: 1-120 characters naming what the item shows, e.g. "Yearly access bar chart".
- kind: chart (any data display: bars, lines, maps, tables), kpi (a headline number), control
  (date range, drop-down, list or slider that filters), text (titles, paragraphs), image
  (pictures, logos, illustrations), legend, or other.
- box: x, y, w, h as integers in thousandths of the image width (x, w) and height (y, h),
  0 to 1000; x + w and y + h at most 1000; w and h at least 1.
- disposition: native when one allowed type can draw or filter it as shown; static when it is
  art, text, a legend, or nothing allowed fits. Static items stay in the background picture.
- type: for native items, exactly one entry of the allowed types; null for static items.
  Control types (date_range, dropdown, fixed_size_list) only for kind control, and a native
  control needs a control type.
- shows: 0-300 characters of what the image displays: measures, dimensions and grain as read,
  e.g. "access % by year, 2000-2019". Display text only; never name a data field.
- reason: 0-300 characters on why native or static.
