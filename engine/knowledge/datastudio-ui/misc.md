---
type: UI Selector Set
title: Text, styles and pages
description: Controls observed live for task 4.2.
timestamp: 2026-10-18
selectors:
  selection_mode: 'role=button[name="Selection Mode"]'
  text_button: 'role=button[name=/^Text$/]'
  text_component: '.lego-component-repeat:has(ng2-canvas-component.simple-description)'
  text_editor: '.ng2-textbox-editor'
  text_viewer: '.ng2-textbox-viewer'
  text_font_size: 'role=spinbutton[name="font size selector"]'
  text_color: '[data-webdriver-cell-key="foreColor"] button'
  text_bold: '[data-webdriver-cell-key="bold"] button'
  text_align: '[data-webdriver-cell-key="textAlignment"] button'
  text_align_left: '[role="menuitem"]:has([data-mat-icon-name="format_align_left"])'
  text_align_center: '[role="menuitem"]:has([data-mat-icon-name="format_align_center"])'
  text_align_right: '[role="menuitem"]:has([data-mat-icon-name="format_align_right"])'
  custom_color: 'role=button[name="Add custom color"]'
  color_hex: 'role=textbox[name="Hex"]'
  color_done: 'role=button[name=/^Done$/]'
  color_preview: '.color-preview-cell'
  style_colors: '[data-webdriver-cell-key="multiColor"] ng2-color-picker-button, [data-webdriver-cell-key="multiColor"] .swatch:not([style*="no-drop"])'
  series_swatch: '.swatch'
  style_background: '[data-webdriver-cell-key="background"] ng2-color-picker-button'
  style_border_color: '[data-webdriver-cell-key="borderColor"] ng2-color-picker-button'
  style_title_size: '[data-webdriver-cell-key="chartTitleFontSize"] [role="combobox"]'
  color_button: 'button'
  font_size_option: 'role=option'
  image_preserve_ratio: 'role=switch[name="Preserve Aspect Ratio"]'
  selected_component: '.lego-component.selected'
  add_page_button: 'role=button[name=/^Add page$/]'
  manage_pages: 'role=button[name="Manage pages"]'
  pages_panel: 'article:has(button[aria-label="Close Report Pages"])'
  page_rows: '.row-container'
  page_row_menu: 'button'
  page_add: 'role=button[name=/^Add a page$/]'
  page_rename: 'role=menuitem[name=/^Rename$/]'
  page_name: 'role=textbox[name="Enter new name"]'
  pages_close: 'role=button[name="Close Report Pages"]'
---

Text uses a hidden editor plus a viewer when deselected. Double-click the component
to edit, select all again before each property change, and verify computed styles
on the viewer's text nodes. Custom color opens a Hex dialog above the palette.
Chart series colors are individual multiColor pickers; skip unavailable styles with
a warning. Page manager rows expose nested menu buttons and Rename -> Enter new name.
The initial Add page creates page 2 and opens the manager; later adds use Add a page.


Exit text editing with Selection Mode before geometry, then deselect before reading the viewer.
For images, deselect on the canvas and click near the image top-left before waiting for Setup.
On saved-report reload, visible images may still be loading: wait for naturalWidth.
Use rendered innerText for multiline text; textContent joins block text without line breaks.

Add a page inserts after current; switch to the last existing page before appending.
Blank paragraphs use lone BR placeholders; logical text readback joins their block boundaries.

After choosing a chart title font size, the combobox can briefly include all of
the closing dropdown's option labels in innerText. Poll for the exact selected
size within the existing op deadline; do not treat a substring match as proof.
