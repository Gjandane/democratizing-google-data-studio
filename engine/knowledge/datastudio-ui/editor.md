---
type: UI Selector Set
title: Report editor
description: Live editor controls observed during tasks 1.3, 2.1, 2.2 and 4.1.
timestamp: 2026-10-18
selectors:
  chart_frame: 'ng2-canvas-component.simple-barchart iframe'
  chart_component: '.lego-component-repeat:has(ng2-canvas-component.simple-barchart)'
  chart_components: '.lego-component-repeat:has(ng2-canvas-component)'
  component_scorecard: 'ng2-canvas-component.kpi-metric'
  component_time_series: 'ng2-canvas-component.simple-linechart'
  component_bar: 'ng2-canvas-component.simple-barchart'
  component_pie: 'ng2-canvas-component.simple-piechart'
  component_table: 'ng2-canvas-component.simple-table'
  chart_iframe: 'iframe'
  chart_frame_body: 'body'
  image_component: '.lego-component-repeat:has(ng2-canvas-component.image-component)'
  image_content: '.image-component img'
  page_menu: 'role=button[name="Page"]'
  current_page_settings: 'role=menuitem[name="Current page settings"]'
  page_style_tab: 'role=tab[name=/style/i]'
  canvas_size: 'text=/^(Auto|Custom)$/i'
  canvas_size_auto: 'text="Auto"'
  canvas_size_custom: 'text="Custom"'
  canvas_width: 'role=spinbutton[name="Width (px)"]'
  canvas_height: 'role=spinbutton[name="Height (px)"]'
  drawing: 'region-drawing-handler'
  setup_tab: 'role=tab[name="Setup"]'
  dimension_group: 'role=group[name="Dimension - Y axis"]'
  metric_group: 'role=group[name="Metric - X axis"]'
  dimension_group_any: '[data-webdriver-cell-key="actionConceptList"]'
  metric_group_any: 'role=group[name=/^(Metric( - [XY] axis)?|Primary field)$/]'
  date_range_dimension_group: '[data-webdriver-cell-key="dateRangeDimension"]'
  sort_group: '[data-webdriver-cell-key="sortConcept"], [data-webdriver-cell-key="sortConcept1"], [data-webdriver-cell-key="rowSortColumn0"]'
  sort_order_group: '[data-webdriver-cell-key="sortDir"], [data-webdriver-cell-key="sortDir1"], [data-webdriver-cell-key="rowSortDir0"]'
  sort_ascending: 'role=radio[name=/Ascending/]'
  sort_descending: 'role=radio[name=/Descending/]'
  field_buttons: '.all-chips-panel [role="button"]'
  field_chips: '[role="button"][aria-label]'
  field_picker: '.cdk-overlay-pane:has(ng2-selector-dialog), .cdk-overlay-pane:has-text("No results")'
  field_picker_search: 'role=searchbox[name="Text box to search Data Studio"]'
  field_picker_empty: 'text="No results"'
  date_calendar: '.cdk-overlay-pane:has(button.date-range-options)'
  chart_gallery: '.cdk-overlay-pane:has-text("Scorecard"):has-text("Table")'
  overlay_pane: '.cdk-overlay-pane'
  open_menu: 'role=menu'
  dropdown_option: 'role=option'
  metric_chips: '.common-chip.metric'
  metric_aggregation_button: '.left-half'
  field_remove_button: 'button.remove-chip-button'
  field_containers: '.common-chip'
  field_replace_button: '.right-half'
  metric_editor: '.cdk-overlay-pane:has-text("Comparison calculation")'
  aggregation_control: 'role=button[name=/^Aggregation /]'
  last_overlay: '.cdk-overlay-pane >> nth=-1'
  breakdown_group: '[data-webdriver-cell-key="breakdownDimension"]'
  drill_down_switch: 'role=switch[name="Drill down"]'
  vertical_bar_chart: 'role=button[name=/^Vertical bar chart$/]'
  stacked_bar_chart: 'role=button[name=/^Stacked bar chart$/]'
  stacked_vertical_bar_chart: 'role=button[name=/^Stacked vertical bar chart$/]'
  donut_chart: 'role=button[name=/^Donut chart$/]'
  add_dimension: 'role=button[name="Add dimension"]'
  add_metric: 'role=button[name="Add metric"]'
  status_field: 'role=button[name="status"]'
  count_field: 'role=button[name="Record Count"]'
  first_field: '.all-chips-panel [role="button"]'
  consent_dialog: 'role=dialog[name="Grant consent"]'
  review_save_dialog: 'role=dialog[name="Review data access before saving"s]'
  view: 'role=button[name="View"] >> nth=0'
  acknowledge_save: 'role=button[name="Acknowledge and save"]'
  send_back: 'role=menuitem[name=/^Send to back/]'
  order: 'role=menuitem[name="Order"]'
  upload_image: 'role=menuitem[name="Upload from computer"]'
  zoom_100: 'role=menuitem[name="100%"]'
  zoom_menu: '.split-container:has(button[aria-label="Zoom"]) button.mat-mdc-menu-trigger'
  zoom: 'role=button[name="Zoom"]'
  components: '.lego-component-repeat'
  style_tab: 'role=tab[name="Style"]'
  consent_allow: 'role=button[name="Allow"]'
  canvas: '.ng2-canvas-container'
  bar_chart: 'role=button[name="Bar chart"]'
  scorecard_chart: 'role=button[name=/^Scorecard$/]'
  time_series_chart: 'role=button[name=/^Time series chart$/]'
  pie_chart: 'role=button[name=/^Pie chart$/]'
  table_chart: 'role=button[name=/^Table$/]'
  pivot_table_chart: 'role=button[name=/^Pivot\ table$/]'
  scatter_chart: 'role=button[name=/^Scatter\ chart$/]'
  geo_map_chart: 'role=button[name=/^Geo\ chart$/]'
  component_pivot_table: 'ng2-canvas-component.pivot-table'
  component_scatter: 'ng2-canvas-component.simple-scatterchart'
  component_geo_map: 'ng2-canvas-component.simple-geomap'
  pivot_rows_group: '[data-webdriver-cell-key="pivotTableRowDimensions"]'
  pivot_columns_group: '[data-webdriver-cell-key="pivotTableColDimensions"]'
  scatter_x_group: '[data-webdriver-cell-key="scatterMetricx"]'
  scatter_y_group: '[data-webdriver-cell-key="scatterMetricy"]'
  scatter_size_group: '[data-webdriver-cell-key="scatterMetricSize"]'
  dimension_type_button: '.left-half'
  data_type_control: 'role=button[name=/^Data type /]'
  geo_type_menu: 'role=menuitem[name=/^Geo$/]'
  add_control: 'role=button[name=/^Add\ a\ control$/]'
  date_range_control: 'role=menuitem[name=/^Date\ range\ control$/]'
  dropdown_control: 'role=menuitem[name=/^Drop\-down\ list$/]'
  component_date_range_control: 'ng2-canvas-component.simple-daterangepicker'
  component_dropdown_control: 'ng2-canvas-component.dimension-filter'
  control_field_group: '[data-webdriver-cell-key="controlField"]'
  date_control_default: '[data-webdriver-cell-key="dateRange"]'
  date_range_options: '.cdk-overlay-pane button.date-range-options'
  last_7_days: 'role=menuitem[name=/^Last 7 days$/]'
  date_apply: '.cdk-overlay-pane >> role=button[name=/^Apply$/]'
  add_chart: 'role=button[name="Add a chart"]'
  insert: 'role=button[name="Insert"]'
  image: 'role=button[name="Image"]'
  arrange: 'role=button[name="Arrange"]'
  save_share: 'role=button[name="Save and share"]'
  show_title_switch: 'role=switch[name=/Show title/]'
  chart_title_input: 'role=group[name="Chart title"] >> role=textbox'
  compact_numbers_switch: 'role=switch[name=/Compact numbers/]'
  orientation_horizontal: 'role=radio[name=/Horizontal/]'
  orientation_vertical: 'role=radio[name=/Vertical/]'
  stacked_switch: 'role=switch[name="Stacked bars"]'
  pie_inner_radius: 'role=slider[name="Inner radius"]'
  rows_per_page_control: 'role=combobox[name=/Rows per page/]'
---

## Readiness and fields

The template fallback reaches an unsaved editor. Wait for `first_field` in the
Data panel: the editor and spinner can finish earlier. `status_field` is one
observed field in the `order_items` test table, not a general readiness check.
The default `order_items` horizontal bar chart uses `status` and `Record Count`;
verify both in their Setup groups. This spike deliberately uses that test-table
shape; it is not the future generic field-selection implementation.
The first query can open `consent_dialog`; `consent_allow` grants viewer audit
logging for the report's configured source. Never automate Google sign-in.

Field pickers are `ng2-selector-dialog` overlays. "Chart fields" is only a group
of fields that charts on the page already use, listed above "Default group";
the first charts on a fresh page show "Default group" alone. Never detect the
picker by that heading.

The picker renders only the rows near its scroll position: 16 field buttons at
most (2026-10-22). Later fields have no DOM node at all, so a lookup by name
fails although the Data panel lists the field. Observed: the release view's
17th button `user_id`, and on order_items a table's sixth metric, because the
chart's own metrics are listed again under "Chart fields". `field_picker_search`
filters the list (`user_id` -> exactly one button, within 250 ms); a query with
no match shows `field_picker_empty` ("No results"), as does a geo picker with no
compatible field before any search.

Rows per page (`rows_per_page_control`) is a fixed `mat-select` menu, not a
number input: 1, 5, 10, 20, 25, 50, 100, 250, 500, 1000, 2500, 5000, 7500,
10000, 25000, 50000 (2026-10-22). A failed choice leaves the listbox open, and
it blocks later ops until they time out (save included): Escape it.

Time series Setup has no Sort section (cell keys observed 2026-10-21:
datasource, actionConceptList, metrics, filters, dateRangeDimension,
dateRangeSetting, ...; no `sortConcept`). It always orders by its date
dimension ascending, so `sort_group` never appears for it.

Selecting an image can also empty the Data panel before the first chart exists.
An empty `field_buttons` result in that state does not establish that a source
field is missing. Retain source-field names while the panel is populated, before
selecting an image, just as for a date control.

## Geometry

Set a 1920 x 1200 viewport and choose `zoom_menu` -> `zoom_100`. Chrome's own
per-site page zoom (persisted in the profile; CDP cannot reset it) must also be
100%: viewport emulation absorbs the Windows display scale, not that zoom. At
50% the editor laid out at 3840 x 2400 CSS px (devicePixelRatio 0.5); at 80% (the profile's default
after Ctrl+0) 2400 x 1500. `open_report` reads `innerWidth`/`innerHeight` at
readiness and fails unless they are 1920 x 1200. The canvas
has logical dimensions 1200 x 900 and a matching CSS bounding box at this zoom.
Use the canvas top-left as the coordinate origin, not the viewport top-left.
`components` exposes offsetLeft/Top/Width/Height for independent readback.
The Arrange menu and chart Style panel did not expose numeric box fields. For
the page canvas, use Page -> Current page settings -> STYLE, choose Custom
under Canvas size, then set the Width (px) and Height (px) inputs.

After selecting the bar chart, drag from 10 px inside its top-left to move it;
drag the bottom-right corner to resize it. Cross CDK's drag threshold with an
initial 10 px movement before moving to the destination. Image movement starts
at its center. A direct large movement on an image sometimes selected browser
text instead. Both chart and image measured 0 px error in exploratory readback.
The chart target is [24,120,560,300]; image target [0,0,1200,900].

## Tall canvases (task 9.1)

The canvas scrolls inside its nearest scrollable ancestor (`.mainBlock` on
2026-10-21: viewport y 162-1200, x 0-1440 with the right panels open; canvas top
22 px below its scroll origin). A 1200 x 1492 canvas does not fit. Mouse input
outside that window misses: a press there hits nothing, so a drag that starts
there does nothing, while a press inside can still move outside. Selecting a
component also scrolls the window, so a fixed `canvas + (24, 24)` insertion
click can land on the filter bar and open a "Choose a field" chip. Scroll the
region into view first (code finds the scroller by computed overflow, no
selector), keep points 40 px inside the window, and split drags longer than the
window into steps. `offsetLeft/Top` stay canvas coordinates at any scroll.
An uploaded image appears mid-canvas at a reduced, ratio-kept size (e.g. 400,394
at 201 x 250 for a 1200 x 1492 PNG). Resizing it in place to the full canvas
puts the handle beyond the canvas, so move it to where the resized box fits
first. After Send to back the image stays selected and the closing menu absorbs
the first workspace click: repeat Escape (`open_menu`) or the workspace click
until neither `open_menu` nor `selected_component` is visible.
Smart guides snap insertion and drops: with a table ending at y 1188 and a
control at 1220-1264 (gap 32), a text box drawn at y 1300 landed at 1296 (equal
32 px gap), and a 4 px corrective drag snapped back. Expect up to that offset
near stacked components; readback stays within the ±4 px tolerance there.

## Image and order

`image` -> `upload_image` opens a native file chooser; handle it with
Playwright's expect_file_chooser/set_files. The upload adds an image component
automatically. Wait for its image naturalWidth before manipulating it.
Disable Preserve Aspect Ratio in this image's Setup panel before resizing to an
arbitrary recipe rectangle. Resize before moving an uploaded image to a canvas
edge: moving its default-size box there first can hide the resize handle beyond
the canvas. Retain the newly appended component before waiting
for its image to load; scope image_content under that component, since ordinary
images and earlier backgrounds can already exist. Retain a pending upload too:
retry must not open another chooser after set_files may have inserted the image.
Choose Arrange -> Order -> Send to back. Verify this exact retained component
is first in DOM paint order, then refresh page-local component/control/chart
indices by element identity: moving a background changes the indices used by
later set_style operations. Leave other pages' indices alone. Inspect the saved screenshot. A blob preview
alone does not establish persistence: check the saved view too.

## Saving

The initial editor requires Save and share, then the data-access review dialog:
tick its risk checkbox when visible (it may render late or be absent), then click
the dialog's own Acknowledge and save. Wait for a concrete `/reporting/<id>/page/<id>/edit`
URL and the View button. Remove `/edit` for the view URL. The View selector
chooses the first matching button: the editor's View menu has the same name.
View stays in the same owned tab; check both component boxes after it loads.
Do not use the create URL as a saved-report link.
Poll the scoped checkbox and acknowledgement until the button is enabled, within
the existing operation deadline. Do not wait on a disabled click: it prevents
accepting a checkbox that appears later and exhausts the shared retry budget.

The chart renders in `chart_frame`, a sandboxed iframe. Its body must contain
the metric label before capturing the screenshot; component count/geometry
alone can pass while the chart still shows a loading placeholder. Reload the
saved view and verify both boxes, image naturalWidth and the rendered metric.
Sign-in held across repeated script processes on the persistent profile;
browser-process restart was not tested because other profile tabs were open.


## Chart setup (task 2.2)

Choose exact gallery names: the gallery contains several scorecards and tables.
Field chips have two targets: the right half opens the field picker, while the
left icon opens the field editor. Aggregation is a separate button in that editor;
read back its accessible name, not the chart Setup chip's text. Unavailable
aggregations fail the op rather than silently keeping the default.

The main dimension list is actionConceptList. For multiple dimensions, enabling
Drill down exposes Add dimension asynchronously; wait for it. Table permits
multiple dimensions without enabling drill down. Stacked bar presets may add an
unrequested breakdown automatically; remove it using remove-chip-button. Scope
sort order to sortDir/sortDir1 so Secondary sort's radios cannot match. With one
metric and no breakdown, stacking is visually equivalent and the editor hides its
switch; verify the sole series, bar type and orientation instead.

Title is the textbox within Chart title, after enabling Show title. Rows per page
is in Setup. Compact numbers and bar orientation/stacking are in Style. Donut is
a pie preset with a nonzero native Inner radius range input value. Time series,
bar and pie render in lazily created iframes; scorecard and table render directly.
Wait for rendered values/labels before saved-report screenshots.

## Remaining charts and controls (task 4.1)

Pivot tables use pivotTableRowDimensions and pivotTableColDimensions instead of
actionConceptList. The editor requires at least one row dimension; the column list
may be empty. Remove surplus preset fields before adding replacements. Primary row sort uses rowSortColumn0
and rowSortDir0. Scatter uses individual scatterMetricx/scatterMetricy slots and
an optional scatterMetricSize slot, in recipe metric order.

Geo chart accepts only geo-compatible fields. The public order_items source has
none: its picker shows No results without the usual Chart fields heading. Close
that picker on rejection so later operations and saving remain usable. A compatible
dimension's left icon exposes Data type -> Geo, with Country, Country subdivision
(1st level), and City corresponding to country, region, and city.

Add a control opens a menu containing Date range control and Drop-down list.
Wait for the chosen menu item to disappear before clicking the drawing canvas;
drawing mode can appear while the menu still intercepts clicks. Date controls have
no source and clear the Data panel field list; preserve source-field names before
selecting one. Dropdown controlField holds its single filter field. Date controls
filter charts with an Auto date range and a compatible date range dimension.
Selecting a date control opens its calendar: Escape before geometry and Setup.
A move drag's mouse-up is also a click and reopens it (`date_calendar`), flush
with the control's bottom edge (pane 0,500-460,854 for a control ending at
viewport y 500), so the resize corner hits the calendar header and nothing
resizes. Close it before each drag step. The default control is 300 x 50; it
resizes to 276 x 44 (no larger minimum observed). A background's center guide
snaps a move: on a 532 px canvas y 264 lands at 266, inside ±4.
Last 7 days first opens a preset-family submenu; select the exact Last 7 days
entry there before Apply. After filtering, require changed numeric chart content
together, then wait for progress bars to disappear before capturing evidence.
