"""Render real kit decorations with illustrative data; no model, CDN or new dependency.

uv run python scripts/render_presets.py [--output-dir PATH]
"""
import argparse
import base64
from html import escape
from pathlib import Path

from playwright.sync_api import sync_playwright

from dss.artifacts.design import presets, contrast
from dss.render.kits import decorations, content_row
from dss.render.prototype import render
from dss.spec.layout import box
from dss.spec.models import DashboardSpec, Page, Theme, Cell


def sample_html(preset):
    title, subtitle = 'Sales performance', 'Illustrative data for theme review'
    theme = Theme(**{k: getattr(preset, k) for k in Theme.model_fields})
    start = content_row(preset.decoration_kit, title, subtitle)
    cells = [Cell(col=1, row=start, w=4, h=14), Cell(col=5, row=start, w=8, h=22)]
    spec = DashboardSpec(spec_version=1, build_id='b_000000000000', title=preset.name, archetype=preset.archetypes[0],
        theme=theme, datasource={'table': 'example.review.sample'}, pages=[Page(index=1, name='Theme sample', height=900,
            decorations=decorations(preset.decoration_kit, theme, title, subtitle, panels=cells))])
    html = render(spec, layer='decoration')
    def position(cell):
        b = box(spec.canvas, spec.grid, cell)
        return f'left:{b["x"]}px;top:{b["y"]}px;width:{b["w"]}px;height:{b["h"]}px'
    cards = [f'<section class="sample score" style="{position(cells[0])}"><h2>Net revenue</h2>'
             '<p class="number">$284,650</p><p>Across 1,842 orders</p><p>January–September 2026</p></section>',
             f'<section class="sample bars" style="{position(cells[1])}"><h2>Revenue by channel</h2>'
             '<p>USD, illustrative data</p><div class="bar-list">']
    for name, value, color in zip(('Direct', 'Wholesale', 'Partner', 'Marketplace'), (112000, 82000, 54000, 36650), preset.palette):
        cards.append(f'<div class="bar-row"><span>{name}</span><div class="track"><i style="width:{value / 1120}%;background:{color}"></i></div><span>${value:,}</span></div>')
    cards += ['</div></section>', '<footer><h2>' + escape(preset.name) + '</h2><p>' + escape(preset.description) + '</p>',
              '<p>' + escape(preset.font_family) + ' / ' + escape(preset.decoration_kit) +
              f' / text contrast {min(contrast(preset.text, preset.background), contrast(preset.text, preset.surface)):.1f}:1</p>',
              '<div class="swatches">']
    for i, color in enumerate(preset.palette, 1):
        cards.append(f'<div><i style="background:{color}"></i><span>Series {i}<br>{color}</span></div>')
    cards += ['</div></footer>']
    css = f'''<style>body{{background:{theme.background};color:{theme.text};font-family:{theme.font_family};font-size:14px}}
    .sample{{position:absolute;padding:24px;background:{theme.surface};border-radius:{theme.radius}px}}
    h2{{font-size:18px;margin:0 0 12px}}p{{margin:0 0 16px;line-height:1.5}}.number{{font-size:40px;font-weight:bold;margin:26px 0 12px}}
    .bar-list{{margin-top:24px;display:grid;gap:24px}}.bar-row{{display:grid;grid-template-columns:100px 1fr 85px;align-items:center;gap:16px}}.bar-row span:last-child{{text-align:right;font-variant-numeric:tabular-nums}}
    .track{{height:28px}}.track i{{display:block;height:100%}}footer{{position:absolute;left:24px;right:24px;top:690px}}
    .swatches{{display:flex;gap:32px}}.swatches>div{{display:flex;gap:12px;align-items:center}}.swatches i{{width:36px;height:36px;display:block}}.swatches span{{font-size:13px;line-height:1.5}}
    </style>'''
    return html.replace('</head>', css + '</head>').replace('</body>', ''.join(cards) + '</body>')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'data/preset_sheets')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    images = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 1200, 'height': 900}, device_scale_factor=1)
            for preset in presets():
                html = sample_html(preset)
                (args.output_dir / f'{preset.id}.html').write_text(html, encoding='utf-8')
                page.set_content(html, wait_until='load')
                page.evaluate('document.fonts.ready')
                path = args.output_dir / f'{preset.id}.png'
                page.screenshot(path=str(path), full_page=True, animations='disabled')
                images.append((preset.name, base64.b64encode(path.read_bytes()).decode('ascii')))
                print(path)
            gallery = '<!doctype html><html lang="en"><meta charset="utf-8"><title>Theme preset sheet</title><style>body{margin:0;display:grid;grid-template-columns:repeat(3,600px);background:#fff}img{display:block;width:600px;height:450px}</style>'
            gallery += ''.join(f'<img alt="{escape(name, quote=True)}" src="data:image/png;base64,{data}">' for name, data in images) + '</html>'
            (args.output_dir / 'index.html').write_text(gallery, encoding='utf-8')
            page.set_viewport_size({'width': 1800, 'height': 900})
            page.set_content(gallery, wait_until='load')
            path = args.output_dir / 'preset_sheet.png'
            page.screenshot(path=str(path), full_page=True)
            print(path)
        finally:
            browser.close()


if __name__ == '__main__':
    main()
