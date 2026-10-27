"""Designed pages: allowlist sanitizer, vendored icons and Chromium slot measurement (task 20.1);
vendored static art (task 24.4)."""
from html.parser import HTMLParser
import importlib.util
import json
import math
from pathlib import Path
import re
import struct
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


STRETCH = ('<style>.dss-design-p1{display:flex;padding:12px}{extra}</style>'
           '<div class="dashboard"{wrap}><div class="card" style="height:300px">'
           '<div data-slot="p1_kpi" style="width:240px;height:96px"></div></div>{tail}</div>')


@pytest.mark.parametrize('extra,wrap,tail,errors', [
    # The fixed final page height stretches a flex child into the footer band; nothing visible reaches it.
    ('', '', '', []),
    ('.dss-design-p1 .dashboard{display:flex;flex-direction:column}', '', '', []),
    # Visible paint, a slot or text that the stretch carries into the band still fails.
    ('.dss-design-p1 .dashboard{background:#FFF}', '', '', ['div.dashboard']),
    ('.dss-design-p1 .dashboard{border:1px solid #CBD5E1}', '', '', ['div.dashboard']),
    ('.dss-design-p1 .dashboard{box-shadow:0 1px 2px #000}', '', '', ['div.dashboard']),
    ('.dss-design-p1 .dashboard{display:flex;flex-direction:column;justify-content:space-between}', '',
     '<p class="note">Source: synthetic</p>', ['div.dashboard > p.note']),
    ('.dss-design-p1 .dashboard{display:flex;flex-direction:column}.dss-design-p1 .card{flex:1;background:#FFF}',
     '', '', ['div.dashboard > div.card']),
    ('.dss-design-p1 .dashboard{background-image:linear-gradient(#FFF,#EEE)}', '', '', ['div.dashboard']),
    ('.dss-design-p1 .dashboard{background:rgba(0,0,0,0)}', '', '', []),
    # A marker or a shape drawn outside its svg's box paints without a box of its own.
    ('.dss-design-p1 .dashboard{display:flex;flex-direction:column;justify-content:space-between}', '',
     '<ul class="marks"><li></li></ul>', ['div.dashboard > ul.marks > li']),
    ('.dss-design-p1 svg{overflow:visible}', '',
     '<svg width="20" height="20" viewBox="0 0 20 20"><rect y="30" width="20" height="40"/></svg>',
     ['div.dashboard > svg > rect']),
])
def test_footer_counts_only_what_a_stretch_makes_visible(extra, wrap, tail, errors):
    html = STRETCH.replace('{extra}', extra).replace('{wrap}', wrap).replace('{tail}', tail)
    measured = design_page.measure(html, {'p1_kpi': 'scorecard'}, 1200, footer=64)
    assert [e['path'] for e in measured.errors] == errors, measured.errors
    assert all('reaches into the synthetic data footer' in e['message'] for e in measured.errors)
    assert measured.boxes['p1_kpi']['h'] == 96


def test_a_stretched_slot_reaching_the_footer_fails():
    html = ('<style>.dss-design-p1{display:flex;padding:12px}</style>'
            '<div data-slot="p1_kpi" style="width:240px;min-height:96px"></div>')
    measured = design_page.measure(html, {'p1_kpi': 'scorecard'}, 1200, footer=64)
    assert [e['path'] for e in measured.errors] == ['div[data-slot="p1_kpi"]'], measured.errors


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


# Static art (task 24.4): scripts/make_art.py output, vendored like the icons.
ART_NAMES = ['globe-americas', 'globe-asia-pacific', 'globe-europe-africa', 'world']
CONTINENTS = {'africa', 'antarctica', 'asia', 'europe', 'north-america', 'oceania', 'seven-seas', 'south-america'}
LAND = re.compile(r'<path class="land ([a-z-]+) c-([A-Z]{3})" d="([^"]+)"></path>')
GLOBE_PAGE = Path(__file__).parent / 'data/designed_globe.html'


def path_points(d):
    """Absolute points of make_art path data: M, relative l, A (rim arcs) and z."""
    tokens, points, here, command, i = re.findall(r'[MAlz]|-?(?:\d+(?:\.\d*)?|\.\d+)', d), [], (0.0, 0.0), None, 0
    while i < len(tokens):
        if tokens[i] in ('M', 'A', 'l', 'z'):
            command, i = tokens[i], i + 1
        elif command == 'A':
            here, i = (float(tokens[i + 5]), float(tokens[i + 6])), i + 7
            points.append(here)
        else:
            x, y = float(tokens[i]), float(tokens[i + 1])
            here, i = ((x, y) if command == 'M' else (here[0] + x, here[1] + y)), i + 2
            points.append(here)
    return points


def inside_the_globe(d):
    return all(math.hypot(x - 250, y - 250) <= 249.1 for x, y in path_points(d))  # rim radius 249, 0.1 rounding


def test_art_is_vendored_natural_earth_with_its_notice():
    art = design_page.art()
    assert sorted(art) == ART_NAMES
    notice = (design_page.ART / 'NOTICE').read_text(encoding='utf-8')
    assert 'ne_110m_admin_0_countries' in notice and 'v5.1.2' in notice and 'public domain' in notice
    countries = {}
    for name in ART_NAMES:
        assert (design_page.ART / f'{name}.svg').stat().st_size <= 80 * 1024
        svg = art[name]
        assert svg.startswith('<svg viewBox=') and design_page.sanitize(svg) == svg
        lands = LAND.findall(svg)
        assert len(lands) == svg.count('<path') > 0  # every country path carries its classes
        assert {continent for continent, _, _ in lands} <= CONTINENTS
        countries[name] = {code: d for _, code, d in lands}
        assert len(countries[name]) == len(lands)
    assert len(countries['world']) == 176 and 'ATA' not in countries['world']  # 177 countries but Antarctica
    # Natural Earth gives France and Norway ISO_A3 -99; their ISO_A3_EH codes still name them.
    assert {'FRA', 'NOR', 'ZAF', 'RUS', 'ATA'} <= set(countries['globe-europe-africa'])
    assert 'AUS' not in countries['globe-europe-africa'] and 'JPN' not in countries['globe-americas']
    assert 'BRA' not in countries['globe-asia-pacific']
    for name in ART_NAMES[:3]:
        assert '<circle class="ocean" cx="250" cy="250" r="249"' in art[name] and '<circle class="outline"' in art[name]
        for code, d in countries[name].items():
            assert inside_the_globe(d), (name, code)  # only the visible hemisphere
    # A country across the horizon follows the rim; one in full view does not.
    assert 'A249 249' in countries['globe-europe-africa']['RUS'] and 'A' not in countries['globe-europe-africa']['FRA']


def feature(iso, eh, adm0, continent, ring):
    return {'type': 'Feature', 'properties': {'ISO_A3': iso, 'ISO_A3_EH': eh, 'ADM0_A3': adm0, 'CONTINENT': continent},
            'geometry': {'type': 'Polygon', 'coordinates': [[*ring, ring[0]]]}}


def ring(west, south, east, north, step=5):
    return ([[lon, south] for lon in range(west, east, step)] + [[east, lat] for lat in range(south, north, step)]
            + [[lon, north] for lon in range(east, west, -step)] + [[west, lat] for lat in range(north, south, -step)])


BOX = (30, -30, 175, 80)  # west, south, east, north: crosses the horizon of 15E 20N on two edges


def test_make_art_is_deterministic_and_clips_each_globe_to_its_visible_hemisphere(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('make_art', Path(__file__).parents[1] / 'scripts/make_art.py')
    make_art = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_art)
    monkeypatch.setattr(make_art, 'OUT', tmp_path / 'art')
    source = tmp_path / 'countries.geojson'
    source.write_text(json.dumps({'type': 'FeatureCollection', 'features': [
        feature('-99', 'FRA', 'FRA', 'Europe', ring(-5, 42, 8, 51)),
        feature('RUS', 'RUS', 'RUS', 'Europe', ring(*BOX)),
        feature('KIR', 'KIR', 'KIR', 'Oceania', ring(-160, -5, -150, 5)),  # on the far side
        feature('-99', '-99', 'KOS', 'Seven seas (open ocean)', ring(20, 42, 22, 44, 1)),
    ]}), encoding='utf-8')
    make_art.main([str(source)])
    first = {path.name: path.read_bytes() for path in (tmp_path / 'art').iterdir()}
    make_art.main([str(source)])
    assert {path.name: path.read_bytes() for path in (tmp_path / 'art').iterdir()} == first
    assert sorted(first) == ['NOTICE', *[f'{name}.svg' for name in ART_NAMES]]
    svg = design_page.sanitize(first['globe-europe-africa.svg'].decode('utf-8'))
    globe = {code: (continent, d) for continent, code, d in LAND.findall(svg)}
    assert {code: continent for code, (continent, _) in globe.items()} == {'FRA': 'europe', 'KOS': 'seven-seas',
                                                                         'RUS': 'europe'}
    assert globe['RUS'][1].count('A249 249') >= 2 and 'A' not in globe['FRA'][1]  # a rim run over 90 degrees
    assert all(inside_the_globe(d) for _, d in globe.values())
    assert first['world.svg'].count(b'<path class="land ') == 4
    # The filled region is the box's visible part: Chromium's own fill test at visible probes, near the
    # rim too (a reversed arc or rim step would bulge in or wrap the wrong way around). Probes within 2
    # units of a box edge as drawn are skipped (edges are sampled every 1/4 degree; near the limb a
    # degree foreshortens below the rounding).
    projection, probes = make_art.Globe(15, 20), []
    edges = [projection.xy(v) for v in (make_art.vector(lon / 4, lat / 4) for lon, lat in ring(*(4 * b for b in BOX), 1))
             if make_art.dot(projection.centre, v) > 0]
    for lon in range(BOX[0] - 5, 180, 3):
        for lat in range(BOX[1] - 5, 87, 3):
            point = make_art.vector(lon, lat)
            x, y = projection.xy(point)
            if make_art.dot(projection.centre, point) > .05 and min((x - a) ** 2 + (y - b) ** 2 for a, b in edges) >= 4:
                probes.append([x, y, BOX[0] < lon < BOX[2] and BOX[1] < lat < BOX[3]])
    assert sum(inside for *_, inside in probes) > 200 and sum(not inside for *_, inside in probes) > 200
    assert sum(math.hypot(x - 250, y - 250) > 230 for x, y, inside in probes if inside) > 10  # along the rim run
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(svg)
            filled = page.evaluate('''probes => probes.map(([x, y]) =>
                document.querySelector('.c-RUS').isPointInFill(new DOMPoint(x, y)))''', probes)
        finally:
            browser.close()
    wrong = [(round(x), round(y), inside) for (x, y, inside), fill in zip(probes, filled) if fill != inside]
    assert wrong == []


def test_art_tag_is_sanitized_empty_and_wrap_draws_the_vendored_svg():
    raw = ('<i class="globe" data-art="globe-europe-africa" data-icon="users" onclick="x()" data-x="1" '
           'style="width:300px"><svg onload="y()"><circle r="3"></circle></svg>hello<b>bold</b></i>')
    clean = design_page.sanitize(raw)
    assert clean == '<i class="globe" data-art="globe-europe-africa" style="width:300px"></i>'
    assert design_page.sanitize(clean) == clean
    wrapped = design_page.wrap(clean, 1200)
    globe = design_page.art()['globe-europe-africa']
    assert f'<i class="globe" data-art="globe-europe-africa" style="width:300px">{globe}</i>' in wrapped
    assert wrapped.count('<svg') == 1 and design_page.ART_CSS in wrapped
    markup = wrapped.split('</style>', 1)[1]  # after code's own stylesheet
    for needle in ('onload', 'onclick', 'data-x', 'data-icon', 'hello', 'bold'):
        assert needle not in markup
    # Any name survives bounded for measure to report; an unknown one stays empty.
    odd = design_page.sanitize('<i data-art="mars &quot;x"><svg viewBox="0 0 2 2"></svg></i>')
    assert odd == '<i data-art="mars--x"></i>' and '<i data-art="mars--x"></i>' in design_page.wrap(odd, 1200)
    # Pages without art keep their bytes.
    assert design_page.wrap('<p>x</p>', 1200) == design_page.wrap('<p>x</p>', 1200).replace(design_page.ART_CSS, '')


def chromium_art(html, width=1200):
    """Sizes and computed fills of sanitized, wrapped art, with JavaScript off and every request aborted."""
    from playwright.sync_api import sync_playwright
    requests = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(java_script_enabled=False, viewport={'width': width, 'height': 900})
            context.route('**/*', lambda route: route.abort())
            page = context.new_page()
            page.on('request', lambda request: requests.append(request.url))
            page.set_content(design_page._document(design_page.sanitize(html), width), wait_until='load')
            drawn = page.evaluate('''() => {
              const size = s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.width, r.height]; };
              const fill = s => getComputedStyle(document.querySelector(s)).fill;
              return {globe: size('.globe'), globe_svg: size('.globe > svg'), map: size('.map'), map_svg: size('.map > svg'),
                      fra: fill('.globe .c-FRA'), zaf: fill('.globe .c-ZAF'), deu: fill('.globe .c-DEU'),
                      map_fra: fill('.map .c-FRA'), ocean: fill('.globe .ocean')};
            }''')
        finally:
            browser.close()
    return drawn, requests


def test_art_renders_scaled_to_its_css_box_and_colored_by_page_css():
    html = ('<style>body{padding:24px}.globe{width:320px;height:240px}.map{width:600px}'
            '.c-FRA{fill:#1e3a8a}.africa{fill:#93c5fd}</style>'
            '<i class="globe" data-art="globe-europe-africa"></i><i class="map" data-art="world"></i>')
    drawn, requests = chromium_art(html)
    assert drawn['globe'] == drawn['globe_svg'] == [320, 240]
    _, _, w, h = map(int, re.search(r'viewBox="([^"]+)"', design_page.art()['world']).group(1).split())
    assert drawn['map'] == drawn['map_svg'] and drawn['map'][0] == 600 and abs(drawn['map'][1] - 600 * h / w) < 1
    assert drawn['fra'] == drawn['map_fra'] == 'rgb(30, 58, 138)' and drawn['zaf'] == 'rgb(147, 197, 253)'
    assert drawn['deu'] == 'rgb(203, 213, 225)' and drawn['ocean'] == 'rgb(241, 245, 249)'  # the art's own defaults
    assert requests == []
    result = design_page.measure(html, {}, 1200)
    assert result.errors == [] and result.requests == []


def test_art_errors_unknown_name_inside_or_over_a_slot():
    html = ('<style>.g{width:200px;height:200px}.slot{width:600px;height:300px}</style>'
            '<i class="g" data-art="globe-americas"></i>'
            '<i class="m" data-art="mars" style="width:40px;height:40px"></i>'
            '<div class="slot" data-slot="p1_bar"><i data-art="world"></i></div>'
            '<i class="over" data-art="world" style="position:absolute;left:100px;top:300px;width:400px"></i>')
    result = design_page.measure(html, {'p1_bar': 'bar'}, 1200)
    errors = {(e['path'], e['message']) for e in result.errors}
    assert len(errors) == len(result.errors) == 3, result.errors
    expected = {
        'slots.p1_bar': 'art "world" is inside slot p1_bar',
        'i[data-art="mars"]': 'art "mars" is not vendored: use one of ' + ', '.join(ART_NAMES),
        'i[data-art="world"]': 'art "world" overlaps slot p1_bar',
    }
    assert {path for path, _ in errors} == set(expected)
    for path, message in errors:
        assert expected[path] in message, (path, message)
    assert result.boxes == {'p1_bar': {'x': 0, 'y': 240, 'w': 600, 'h': 300}} and result.requests == []


def test_globe_page_renders_to_a_3x_png_under_2mb(tmp_path):
    from dss.harness.nodes import designer
    from dss.render import background
    from dss.render.prototype import render
    from dss.spec.models import DashboardSpec
    from dss.spec.validate import validate_spec
    spec = DashboardSpec.model_validate_json((Path(__file__).parent / 'data/designed_spec.json').read_text(encoding='utf-8'))
    html = GLOBE_PAGE.read_text(encoding='utf-8')
    slots = {c.id: c.type for c in spec.pages[0].components}
    measured = design_page.measure(html, slots, 1440, footer=designer.FOOTER)  # page 1 of a synthetic build
    assert measured.errors == [] and measured.requests == []
    clean = design_page.sanitize(html)
    assert clean.count('data-art=') == 2 and '<svg' not in clean  # the design stores the tags, not the art
    designed = designer.assemble(spec, [designer.Designed(clean, measured.boxes, measured.height, 1440, '')], 'fixture')
    assert validate_spec(designed) == []
    assert design_page.art()['globe-americas'] in render(designed, layer='decoration')
    assert background.write_pages(designed, tmp_path) == {'background_p1.png': 3}
    png = (tmp_path / 'background_p1.png').read_bytes()
    assert struct.unpack('>II', png[16:24]) == (4320, 3 * measured.height)
    assert len(png) < background.LIMIT
