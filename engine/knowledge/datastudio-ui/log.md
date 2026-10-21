---
type: UI Selector Set
title: Selector change log
description: Newest observations first.
timestamp: 2026-10-18
selectors: {}
---

- 2026-10-21 task 8.1: `canvas_size_auto`/`canvas_size_custom` are exact
  (`text="Custom"`): the substring form also matched the page-name tooltip
  "Customer Segment Analysis" (strict-mode violation on page 4 of the release
  recipe).
- 2026-10-21 task 8.1: `field_picker` now keys on the picker's
  `ng2-selector-dialog` component. "Chart fields" is only a group listing fields
  that charts on the page already use; the first charts of a fresh compiled
  recipe get a picker headed "Default group" alone (release source
  dash_b_31ee6bedd325_v1, at 100% zoom), so the old text selector timed out.
  Also documented: persisted Chrome page zoom (50%: 3840 x 2400 CSS px) and
  time series Setup lacking `sort_group`, under editor.md Geometry and
  Readiness and fields.
- 2026-10-21 task 7.1: dialog visibility precedes risk-checkbox rendering on
  create and save (spike observed first visibility after 1 and 3 readiness polls).
  Keep exact scoped selectors; poll checkbox readiness and button enabling inside
  the deadline, then acknowledge once. Checkbox-free variants remain supported.
- 2026-10-21 task 6.1: review-data-access dialogs may omit the risk checkbox.
  Added exact `review_dialog`; made `review_acknowledge` and `review_save_dialog`
  exact (the create name is a prefix of the save name); checkbox and buttons are
  scoped inside their dialog.
- 2026-10-19: title-size readback briefly includes the closing dropdown's options;
  documented exact-value polling in misc.md after live 8px/24px verification.
- 2026-10-19: repeated golden acceptance observed an empty Data panel while an
  uploaded image is selected; documented source-field retention before image
  selection in editor.md. No selector changes.
- 2026-10-18 task 4.2: text formatting, custom colors, image Setup/aspect ratio and page manager selectors in misc.md; Selection Mode exits text editing before geometry/readback.

- 2026-10-18: task 4.1 observed pivot row/column lists, scatter X/Y/size slots, Geo chart and geo-type menu, date/dropdown controls and date presets; added selectors. Geo picker with no compatible fields shows No results without Chart fields.
- 2026-10-18: task 2.2 live inspection: exact chart gallery names; scorecard metrics use
  Primary field; pie uses a singular Metric group. Match metric group names exactly. Field names (right half) open the picker; icons
  (left half) open the metric editor and its separate Aggregation menu. Use cell keys
  for field lists to exclude nested groups and breakdown fields. Chart title textbox
  is named textinput; donut is Inner radius, and stacking controls exist on stacked
  variants. Table rows per page is a Setup combobox. Scope its menu to the last
  overlay because the editor retains an empty overlay pane. Inner radius is a native
  range input whose current value is a DOM property. Added component type classes
  for independent postconditions. Scoped primary sort radios after observing Secondary
  sort on stacked bars; wait for Add dimension after drill-down; observed the unlabelled
  remove-chip-button and remove automatic stacked-preset breakdown fields. Single-series
  bars hide stacking controls; verify their equivalent one-series geometry/type/fields.

- 2026-10-18: inspected chart Setup for task 2.2. Chart field chips expose their field labels as
  accessible buttons; Add dimension opens the `Chart fields` picker in a CDK overlay. Added
  generic chart component, field picker, field group, type-menu and sort selectors.
- 2026-10-18: scoped chart type buttons to the Chart gallery overlay after the global Scorecard
  selector matched three visible controls and timed out during insertion.
- 2026-10-18: added editor.md selectors after live DOM/accessibility observation:
  component/canvas roots, data fields and Setup groups, drawing overlay,
  first-query consent, zoom and 100% menu, chart insertion, image upload,
  Arrange/Order/Send to back, first-save acknowledgement and View.
  View is disambiguated from the top menu. Send to back uses an ASCII regex
  prefix so platform shortcut glyphs do not affect lookup. Updated linking.md
  with observed template success. Geometry reads back at 0 px error.
- 2026-10-18: added chart_frame after inspecting the live sandboxed chart iframe;
  require rendered metric text before screenshots and after saved-view reload.
- 2026-10-18: added linking.md document, data-access acknowledgement,
  progress indicator and creation-error dialog selectors after live observation.
  Blank create with ds0 fails; template fallback remains untested.
- 2026-10-18: observed Page -> Current page settings -> STYLE, Canvas size,
  Auto/Custom options and Width (px)/Height (px) fields while validating the
  page canvas operation. Added the corresponding editor selectors.
