"""Designed pages: allowlist sanitizer, vendored icons and Chromium slot measurement (task 20.1)."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time

import pytest

from dss.render import design_page

FIXTURE = Path(__file__).parent / 'data/designed_page.html'
RAW = FIXTURE.read_text(encoding='utf-8')
EXPECTED = json.loads(re.search(r'\{"width".*?\}\}\}', RAW, re.S).group(0))
SLOTS = {cid: slot['type'] for cid, slot in EXPECTED['slots'].items()}
HOST = 'http://127.0.0.1:9'

# name -> (page HTML, substrings that must not survive). Every fixture also keeps the text "kept".
HOSTILE = {
    'script': (f'<div class="ok">kept</div><script>fetch("{HOST}/s")</script><script src="{HOST}/a.js"></script>',
               ['<script', 'fetch', HOST]),
    'event_attribute': ('<div class="ok" onclick="alert(1)" onmouseover="x()">kept</div>'
                        '<svg onload="alert(2)"><circle r="2" onclick="y()"></circle></svg>',
                        ['onclick', 'onmouseover', 'onload', 'alert']),
    'iframe': (f'<iframe src="{HOST}/frame"><p>inside</p></iframe><p>kept</p>', ['iframe', 'inside', HOST]),
    'form': (f'<form action="{HOST}/post"><input name="q" value="x"><button formaction="{HOST}/b">Go</button>'
             '</form><p>kept</p>', ['form', 'input', 'button', 'Go', HOST]),
    'use': (f'<svg><use href="#a"></use><use xlink:href="{HOST}/s.svg#i"/><circle r="4"></circle></svg><p>kept</p>',
            ['<use', 'href', HOST]),
    'foreign_object': (f'<svg><foreignObject><div>leak</div><img src="{HOST}/f.png"></foreignObject></svg><p>kept</p>',
                       ['foreignobject', 'leak', HOST]),
    'href_src': (f'<a href="{HOST}/l">kept</a><img src="{HOST}/i.png" srcset="{HOST}/2.png 2x">'
                 f'<video poster="{HOST}/p.png" src="{HOST}/v.mp4"></video><link rel="stylesheet" href="{HOST}/l.css">'
                 f'<base href="{HOST}/">', ['href', 'src', '<img', '<link', '<base', HOST]),
    'css_url': (f'<style>.ok{{color:#123456;background:url({HOST}/a.png)}} .b{{background-image:URL("{HOST}/b.png")}}'
                f' .c{{list-style:url({HOST}/c.png)}}</style>'
                f'<div class="ok" style="background-image:url(\'{HOST}/d.png\');color:#123456">kept</div>',
                ['url', HOST]),
    'import': (f'<style>@import url({HOST}/a.css);@import "{HOST}/b.css";.ok{{color:#123456}}</style>'
               '<div class="ok">kept</div>', ['@import', HOST]),
    'font_face': (f'<style>@font-face{{font-family:Evil;src:url({HOST}/f.woff2)}}.ok{{font-family:Evil, Arial;'
                  'color:#123456}</style><div class="ok">kept</div>', ['@font-face', 'Evil', HOST]),
    'javascript_url': ('<a href="javascript:alert(1)">kept</a><div style="background:javascript:alert(2)">x</div>'
                       '<svg><a href="javascript:alert(3)"><circle r="2"></circle></a></svg>'
                       '<div style="background-image:url(&#106;avascript:alert(4))">y</div>',
                       ['javascript', 'alert']),
    'position_fixed': ('<style>.ok{position:fixed;top:0;color:#123456}</style>'
                       '<div class="ok" style="position: FIXED;left:0">kept</div>', ['fixed']),
    'css_escape': (f'<style>.ok{{background:u\\72l({HOST}/e.png);color:#123456}}</style><div class="ok">kept</div>',
                   ['\\', HOST]),
    'svg_style_markup': (f'<svg><style><img src="{HOST}/x.png" onerror="alert(1)"></style><circle r="2"></circle></svg>'
                         '<p>kept</p>', ['<img', 'onerror', HOST]),
    'svg_animation': ('<svg><a><animate attributeName="href" values="javascript:alert(1)"></animate>'
                      '<set attributeName="onmouseover" to="alert(2)"></set><text>leak</text></a>'
                      '<circle r="2"></circle></svg><p>kept</p>', ['animate', '<set', 'javascript', 'alert', 'leak']),
    'sibling_selector': ('<style>body ~ div{color:#FF0000} + .x{color:#FF0000} .dss-design + section{color:#FF0000}'
                         ' body.dark+.x{color:#FF0000} .ok{color:#123456}</style><div class="ok">kept</div>',
                         ['~', '+', '#FF0000']),
    'embedded_documents': (f'<template><img src="{HOST}/t.png"></template><noscript><img src="{HOST}/n.png"></noscript>'
                           f'<object data="{HOST}/o"></object><embed src="{HOST}/e">'
                           f'<meta http-equiv="refresh" content="0;url={HOST}/m"><p>kept</p>',
                           ['template', 'noscript', 'object', 'embed', 'meta', HOST]),
    'code_attributes': ('<div id="dss-canvas" class="dss-design ok" data-cid="p1_x" data-kind="chart" '
                        'style="color:#123456 !important;height:50vh">kept</div>',
                        ['id=', 'dss-canvas', 'data-cid', 'data-kind', 'important', 'vh']),
}


class Tags(HTMLParser):
    """(tag, classes, slot, icon) per start tag outside <svg>, and the text."""

    def __init__(self):
        super().__init__()
        self.tags, self.text, self.svg = [], [], 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'svg' or self.svg:
            self.svg += tag == 'svg'
            return
        if tag != 'style':
            self.tags.append((tag, attrs.get('class'), attrs.get('data-slot'), attrs.get('data-icon')))

    def handle_endtag(self, tag):
        self.svg -= tag == 'svg' and self.svg > 0

    def handle_data(self, data):
        if self.lasttag != 'style' and data.strip():
            self.text.append(' '.join(data.split()))


def parsed(html):
    parser = Tags()
    parser.feed(html)
    return parser


def css_declarations(html):
    css = ''.join(re.findall(r'<style>(.*?)</style>', html, re.S))
    return {' '.join(f'{name.strip()}:{value.strip()}'.split()) for name, value in
            re.findall(r'([\w-]+)\s*:\s*([^;{}]+)', re.sub(r'[^{}]*\{', '{', css))}


@pytest.mark.parametrize('name', list(HOSTILE))
def test_sanitize_strips_hostile_markup(name):
    html, forbidden = HOSTILE[name]
    clean = design_page.sanitize(html)
    assert 'kept' in clean
    for needle in forbidden:
        assert needle.lower() not in clean.lower(), (name, needle, clean)
    assert design_page.sanitize(clean) == clean
    # The measured page never fetches anything: nothing hostile survives to make a request.
    assert design_page.measure(html, {}, 1440).requests == []


def test_sanitize_keeps_allowed_css_and_scopes_it_to_the_page_root():
    clean = design_page.sanitize(
        '<style>:root{--accent:#4F46E5} body{padding:24px} html body .card{color:var(--accent)}'
        ' body > .grid{display:grid} body.dark .x{color:#123456} .a + .b{margin:0}</style>'
        '<div class="card" style="font-family:&quot;Open Sans&quot;, Inter, sans-serif">kept</div>', page=2)
    css = re.search(r'<style>(.*?)</style>', clean).group(1)
    assert css == ('.dss-design-p2{--accent:#4F46E5}.dss-design-p2{padding:24px}'
                   '.dss-design-p2 .card{color:var(--accent)}.dss-design-p2 > .grid{display:grid}'
                   '.dss-design-p2.dark .x{color:#123456}.dss-design-p2 .a + .b{margin:0}')
    assert 'style="font-family:&quot;Open Sans&quot;, sans-serif"' in clean  # Inter is not a Data Studio font
    assert 'font-family:Inter' not in design_page.sanitize('<p style="font-family:Inter">x</p>')
    assert 'font-family:Inter' in design_page.sanitize('<p style="font-family:Inter">x</p>', fonts=('Inter',))
    assert design_page.sanitize(clean, page=2) == clean


def test_sanitize_keeps_the_reference_fixture_structure():
    clean = design_page.sanitize(RAW)
    raw, kept = parsed(RAW), parsed(clean)
    assert kept.tags == raw.tags
    assert kept.text == raw.text
    assert css_declarations(RAW) <= css_declarations(clean)
    assert set(re.findall(r'data-slot="([^"]+)"', clean)) == set(SLOTS)
    assert clean.count('<svg') == 4
    assert design_page.sanitize(clean) == clean


def test_slots_are_emptied():
    clean = design_page.sanitize('<div data-slot="p1_bar"><p>Revenue</p><svg><rect></rect></svg></div><p>kept</p>')
    assert clean == '<div data-slot="p1_bar"></div><p>kept</p>'


def test_icons_are_vendored_with_their_isc_licence():
    names = design_page.icons()
    assert 35 <= len(names) <= 45
    assert {'users', 'file-text', 'clock', 'settings', 'chevron-right', 'chevron-down', 'trending-up',
            'trending-down', 'dollar-sign', 'shopping-cart', 'truck', 'package', 'calendar', 'map-pin',
            'triangle-alert', 'circle-check', 'chart-bar', 'chart-pie', 'activity'} <= set(names)
    licence = (design_page.ICONS / 'LICENSE').read_text(encoding='utf-8')
    assert licence.startswith('ISC License') and 'Lucide Icons and Contributors' in licence
    for path in design_page.ICONS.glob('*.svg'):
        assert path.read_text(encoding='utf-8').startswith('<!-- @license lucide-static v1.61.0 - ISC -->')
        svg = names[path.stem]
        assert svg.startswith('<svg ') and svg.endswith('</svg>') and 'viewBox="0 0 24 24"' in svg
        assert design_page.sanitize(svg) == svg


def test_icon_placeholder_becomes_inline_lucide_svg():
    users = design_page.icons()['users']
    assert 'd="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"' in users
    assert design_page.sanitize('<i class="ic" data-icon="users">x</i>') == f'<i class="ic" data-icon="users">{users}</i>'
    # An unknown name keeps the model's own sanitized SVG; with none, measure reports it.
    own = '<i data-icon="rocket-ship"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle></svg></i>'
    assert design_page.sanitize(own) == own
    assert design_page.sanitize('<i data-icon="rocket-ship"></i>') == '<i data-icon="rocket-ship"></i>'


def test_measures_the_reference_fixture():
    started = time.perf_counter()
    result = design_page.measure(RAW, SLOTS, EXPECTED['width'])
    elapsed = time.perf_counter() - started
    assert result.errors == []
    assert result.requests == []
    assert result.height == EXPECTED['height']
    assert set(result.boxes) == set(SLOTS)
    for cid, slot in EXPECTED['slots'].items():
        got = result.boxes[cid]
        assert all(isinstance(v, int) for v in got.values())
        assert all(abs(got[k] - v) <= 1 for k, v in zip('xywh', slot['box'])), (cid, got, slot['box'])
    assert elapsed <= 5, elapsed


def test_page_height_comes_from_the_content_not_the_viewport():
    result = design_page.measure('<style>html, body { height: 100%; }</style>' + RAW, SLOTS, 1440)
    assert result.errors == [] and result.height == EXPECTED['height']


async def test_measure_inside_an_event_loop_uses_a_worker_thread():
    result = design_page.measure(RAW, SLOTS, 1440)
    assert result.errors == [] and result.height == EXPECTED['height']


def test_chromium_runs_without_javascript_and_aborts_every_request():
    raw = (f'<img src="{HOST}/pixel.png" style="position:absolute;width:1px;height:1px">'
           '<div class="x" style="height:40px">x</div>'
           '<script>document.querySelector(".dss-design").style.height = "999px"</script>')
    natural, height, geometry, requests = design_page._chromium(raw, 1440, None)
    assert natural == height == 40  # the script never ran; the image never loaded
    assert set(requests) == {f'{HOST}/pixel.png'}  # tried in each of the two passes, aborted


def broken_page():
    html = RAW
    for old, new in [
        # missing slot
        ('<div data-slot="p1_table_late_shipments"></div>',
         # duplicate and unknown slots
         '<div data-slot="p1_kpi_customers"></div><div data-slot="p1_ghost" style="height:60px"></div>'),
        # text over a slot, an icon over a slot
        ('<h2>Sales by region</h2>', '<h2>Sales by region</h2>'
         '<span class="badge" style="position:absolute;left:300px;top:300px">Peak</span>'),
        ('<h2>Category mix</h2>', '<h2>Category mix</h2>'
         '<i class="mark" data-icon="star" style="position:absolute;left:760px;top:480px"></i>'),
        # overflowing text, too-small text
        ('<h2>Top products</h2>', '<h2>Top products</h2>'
         '<div class="note" style="width:60px;white-space:nowrap;font-size:12px;line-height:15px">Updated hourly</div>'
         '<p class="fine" style="margin:0;font-size:10px;line-height:14px">tiny print</p>'),
        # a slot outside the page, a slot overlapping another
        ('</section>\n<section class="charts">', '</section>\n'
         '<div data-slot="p1_extra" style="position:absolute;left:24px;top:2000px;width:300px;height:100px"></div>'
         '<div data-slot="p1_overlap" style="position:absolute;left:1000px;top:400px;width:300px;height:100px"></div>'
         '<section class="charts">'),
        # an unknown icon with no SVG; another drawn as its own inline SVG is fine
        ('<i data-icon="truck"></i>', '<i data-icon="rocket-ship"></i>'),
        ('<i data-icon="users"></i>', '<i data-icon="handshake-x"><svg viewBox="0 0 24 24">'
         '<circle cx="12" cy="12" r="9"></circle></svg></i>'),
    ]:
        assert old in html
        html = html.replace(old, new, 1)
    return html


def test_measure_errors_name_the_slot_or_element():
    slots = {**SLOTS, 'p1_kpi_orders': 'bar', 'p1_extra': 'scorecard', 'p1_overlap': 'scorecard'}
    result = design_page.measure(broken_page(), slots, 1440)
    errors = {(e['path'], e['message']) for e in result.errors}
    assert len(errors) == len(result.errors) == 11, result.errors
    expected = {
        'slots.p1_table_late_shipments': 'has no slot',
        'slots.p1_kpi_customers': 'appears 2 times',
        'slots.p1_ghost': 'is not a component on this page',
        'slots.p1_kpi_orders': 'a bar needs at least 453x144 px at width 1440',
        'slots.p1_extra': 'is outside the 1440x',
        'slots.p1_overlap': 'overlaps slot p1_pie_category_mix',
        'section.charts > div.card:nth-of-type(1) > span.badge': 'text "Peak" overlaps slot p1_bar_sales_by_region',
        'section.charts > div.card:nth-of-type(2) > i[data-icon="star"]': 'icon or graphic overlaps slot p1_pie_category_mix',
        'section.tables > div.card:nth-of-type(1) > div.note': 'text "Updated hourly" does not fit',
        'section.tables > div.card:nth-of-type(1) > p.fine': 'text "tiny print" is 10px',
        'section.kpis > div.kpi:nth-of-type(4) > div.tile.rose > i[data-icon="rocket-ship"]':
            'icon "rocket-ship" is not vendored',
    }
    assert {path for path, _ in errors} == set(expected)
    for path, message in errors:
        assert expected[path] in message, (path, message)
    assert 'p1_kpi_customers' not in result.boxes and 'p1_ghost' not in result.boxes
    assert result.requests == []


def test_synthetic_footer_is_reserved_below_the_design():
    result = design_page.measure(RAW, SLOTS, 1440, footer=64)
    assert result.errors == [] and result.height == EXPECTED['footer_height']
    assert design_page.footer_top(EXPECTED['height']) == 1224
    stamp = RAW.replace('</section>\n<section class="tables">', '</section>\n<div class="stamp" style="position:absolute;'
                        'left:24px;top:1240px;width:200px;height:40px;background:#E2E8F0"></div><section class="tables">')
    result = design_page.measure(stamp, SLOTS, 1440, footer=64)
    assert [e['path'] for e in result.errors] == ['div.stamp']
    assert 'reaches into the synthetic data footer' in result.errors[0]['message']


@pytest.mark.parametrize('width', [1199, 1921, 1440.0, True])
def test_canvas_width_outside_the_range_is_an_error(width):
    result = design_page.measure(RAW, SLOTS, width)
    assert result.boxes == {} and result.requests == []
    assert [e['path'] for e in result.errors] == ['canvas_width']


def test_output_that_is_not_html_has_no_slots():
    result = design_page.measure('<<< not html at all', {'p1_bar': 'bar'}, 1200)
    assert [(e['path'], 'has no slot' in e['message']) for e in result.errors] == [('slots.p1_bar', True)]


def test_minimum_slot_sizes_follow_layout_at_the_canvas_width():
    assert design_page.minimum('scorecard', 1200) == (179, 44)
    assert design_page.minimum('table', 1440) == (688, 144)
    with pytest.raises(ValueError):
        design_page.minimum('gauge', 1200)
