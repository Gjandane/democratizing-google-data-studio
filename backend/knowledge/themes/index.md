---
type: Index
---

# Theme presets

Built with frontend-design and ui-ux-pro-max for Data Studio dashboards. The
dashboard product guidance favors clear hierarchy, comparisons and minimal
ornament. The generated landing-page pattern and unsupported font suggestions
were discarded; the verified [Data Studio font menu](../datastudio/fonts.md) governs typography.

- [Studio Light](studio_light.md): executive default, band_header
- [Night Ops](night_ops.md): operational default, panel_grid
- [Field Notes](field_notes.md): storytelling default, side_rail
- [Graphite](graphite.md): analytical default, ruled_header
- [Atlas](atlas.md): regional comparisons, title_block
- [Copper Report](copper_report.md): business narratives, band_header

## Shared foundation

1200px canvas, 12 columns, 24px margin, 16px gutter, 20px row pitch.
Titles use 28px bold, subtitles 18px, chart labels 14px. Decoration kits
reserve at least rows 1-9 and grow for long headings; chart content starts at
`content_row(kit, title, subtitle)` (row 10 for the samples). Theme text and muted text
pass 4.5:1 on both the background and surface. Accent-backed text chooses
black or white for contrast. Palette labels sit outside the color swatches
and bars, so categorical color is never the only way to read the samples.
The first four series pass the stdlib Machado/CIE76 oracle in test_design.py.

Generate the approval sheets with `uv run python scripts/render_presets.py`.
Generated HTML and PNGs live in backend/data/preset_sheets (git ignored).
