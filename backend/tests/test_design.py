"""Design oracle: seed accessibility, code-only prefill and contract-shaped API edits."""
from itertools import combinations
import json
import math

import pytest
import yaml

from dss.artifacts import design as node
from dss.artifacts.models import Outline, ThemePreset
from dss.artifacts.okf import frontmatter, read_artifact
from dss.harness.nodes.style_extract import StyleProfile, style_doc
from dss.render.kits import KITS, decorations, content_row
from dss.spec.models import Theme, DashboardSpec, Page
from dss.spec.layout import decoration_text_errors, box
from test_api_contract import FIXTURES, check, shape
from test_context_node import context_api, editable
from test_outline import outline_api


def outline(count, *, selected=True):
    return Outline(revision=1, sections=[{'id': f's{i}', 'title': f'Section {i}', 'purpose': 'Evidence',
        'questions': [{'id': f'q{i}', 'text': 'What drives revenue?', 'rationale': 'Decision',
        'recommended': True, 'selected': selected, 'kpi_refs': [], 'origin': 'proposed'}]} for i in range(count)])


# Machado, Oliveira, Fernandes (2009), severity 1.0; applied to LINEAR sRGB.
# https://www.inf.ufrgs.br/~oliveira/pubs_files/CVD_Simulation/CVD_Simulation.html
# https://colour.readthedocs.io/en/latest/generated/colour.matrix_cvd_Machado2009.html
MATRICES = (
    ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    ((.152286, 1.052583, -.204868), (.114503, .786281, .099216), (-.003882, -.048116, 1.051998)),
    ((.367322, .860646, -.227968), (.280085, .672501, .047413), (-.011820, .042940, .968881)),
)


def lab(color, matrix):
    linear = node.linear(color)
    rgb = [min(1, max(0, sum(v * c for v, c in zip(linear, row)))) for row in matrix]
    xyz = [sum(v * c for v, c in zip(rgb, row)) / white for row, white in zip(
        ((.4124564, .3575761, .1804375), (.2126729, .7151522, .0721750),
         (.0193339, .1191920, .9503041)), (.95047, 1, 1.08883))]
    f = [v ** (1 / 3) if v > (6 / 29) ** 3 else v / (3 * (6 / 29) ** 2) + 4 / 29 for v in xyz]
    return 116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])


def test_color_oracle_known_values():
    # Anchor both computations; tests must not merely restate the seed values.
    assert node.contrast('#000000', '#FFFFFF') == pytest.approx(21)
    assert lab('#FFFFFF', MATRICES[0]) == pytest.approx((100, 0, 0), abs=.001)
    assert lab('#000000', MATRICES[1]) == pytest.approx((0, 0, 0))
    assert math.dist(lab('#FF0000', MATRICES[0]), lab('#00FF00', MATRICES[0])) > 100


def test_every_preset_valid_accessible_and_color_distinguishable():
    presets = node.presets()
    assert len(presets) >= 6 and len({p.id for p in presets}) == len(presets)
    assert set(node.DEFAULTS) == {a for p in presets for a in p.archetypes}
    for p in presets:
        assert p.font_family in node.fonts()
        assert p.decoration_kit in KITS
        assert 3 <= len(p.palette) <= 8 and p.radius >= 0
        for foreground in (p.text, p.muted):
            for background in (p.background, p.surface):
                assert node.contrast(foreground, background) >= 4.5, (p.id, foreground, background)
        assert node.contrast(node.on_color(p.accent), p.accent) >= 4.5
        for matrix in MATRICES:
            for a, b in combinations(p.palette[:4], 2):
                assert math.dist(lab(a, matrix), lab(b, matrix)) >= 10, (p.id, a, b, matrix)
        design = node.prefill({'archetype': p.archetypes[0], 'title': 'Sales'}, None, outline(3))
        design = design.model_copy(update={k: getattr(p, k) for k in (
            'background', 'surface', 'text', 'accent', 'palette', 'font_family')})
        design.preset_id = p.id
        assert node.validate(design, outline(3)).issues == []
        metadata = frontmatter(node.KNOWLEDGE / f'themes/{p.id}.md')
        assert metadata['type'] == 'Theme Preset'
        assert ThemePreset.model_validate({k: v for k, v in metadata.items() if k != 'type'}) == p
    for filename in ('index.md', 'log.md'):
        assert frontmatter(node.KNOWLEDGE / 'themes' / filename)['type']


@pytest.mark.parametrize('archetype,preset', list(node.DEFAULTS.items()))
def test_prefill_for_archetype(archetype, preset):
    build = {'archetype': archetype, 'title': 'Sales'}
    result = node.prefill(build, None, outline(3))
    assert result.preset_id == preset and result.source == 'preset' and result.issues == []
    assert result.density == ('compact' if archetype in ('analytical', 'operational') else 'comfortable')
    assert result.page_structure == 'per_section'
    assert node.prefill(build, None, outline(6)).page_structure == 'single'
    assert node.prefill(build, None, outline(4, selected=False)).page_structure == 'single'
    for count in (1, 5):
        assert node.prefill(build, None, outline(count)).page_structure == 'per_section'


def reference():
    return StyleProfile(background='#253B52', surface='#FFFFFF', text='#111111', accent='#9D3275',
        palette=['#316589', '#BC7821'], font_family='Unknown Font', radius=20)


def test_reference_overrides_are_snapped_valid_and_do_not_import_font_or_radius():
    build = {'archetype': 'executive', 'title': 'Sales'}
    style = reference()
    plain = node.prefill(build, None, outline(2))
    result = node.prefill(build, None, outline(2), style)
    assert result.source == 'reference' and result.issues == []
    assert result.accent == style.accent and result.palette[:2] == style.palette and len(result.palette) == 3
    assert node.contrast(result.background, result.text) >= 4.5
    assert result.font_family == plain.font_family and result.surface == plain.surface and result.text == plain.text
    assert style.background == '#253B52'  # never mutate reference evidence
    style.background = '#FEF9E9'
    assert node.prefill(build, None, outline(2), style).background == '#FEF9E9'


@pytest.mark.parametrize('change,path', [
    ({'text': '#FFFFFF'}, '/surface'), ({'background': '#152B42'}, '/background'),
    ({'title': 'x' * 81}, '/title'), ({'font_family': 'Inter'}, '/font_family'),
    ({'preset_id': 'missing'}, '/preset_id')])
def test_editable_invalid_values_give_issues(change, path):
    design = node.prefill({'archetype': 'executive', 'title': 'Sales'}, None, outline(2))
    result = node.validate(design.model_copy(update=change), outline(2))
    assert path in {i.path for i in result.issues}
    assert design.issues == []
    result = node.validate(result.model_copy(update=design.model_dump(exclude={'issues'})), outline(2))
    assert result.issues == []


def test_six_selected_sections_with_per_section_is_an_issue():
    result = node.prefill({'archetype': 'executive', 'title': 'Sales'}, None, outline(5))
    assert node.validate(result, outline(6)).issues[0].path == '/page_structure'
    assert node.validate(result, outline(6, selected=False)).issues[0].path == '/page_structure'
    six_with_one_empty = outline(6)
    six_with_one_empty.sections[-1].questions[0].selected = False
    assert node.validate(result, six_with_one_empty).issues == []


def test_blank_decoration_rules_keep_declared_browser_height():
    from playwright.sync_api import sync_playwright
    from dss.render.prototype import render
    preset = node.presets()[0]
    theme = Theme(**{k: getattr(preset, k) for k in Theme.model_fields})
    spec = DashboardSpec(spec_version=1, build_id='b_000000000000', title='Sales', archetype='executive',
        theme=theme, datasource={'table': 'p.d.t'}, pages=[Page(index=1, name='Sample', height=900,
            decorations=decorations('panel_grid', theme, 'Sales'))])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(render(spec, layer='decoration'))
            rule = page.locator('[data-cid="p1_header_rule"]').bounding_box()
            title = page.locator('[data-cid="p1_report_title"]').bounding_box()
            assert rule['height'] == box(spec.canvas, spec.grid, spec.pages[0].decorations[0].grid)['h'] == 4
            assert rule['y'] + rule['height'] <= title['y']
        finally:
            browser.close()


@pytest.mark.parametrize('kit', KITS)
def test_kit_deterministic_page_ids_bounds_and_text_fit(kit):
    preset = node.presets()[0]
    theme = Theme(**{k: getattr(preset, k) for k in Theme.model_fields})
    title, subtitle = 'Sales performance', 'Illustrative data for theme review'
    first = decorations(kit, theme, title, subtitle, page=2)
    assert first == decorations(kit, theme, title, subtitle, page=2)
    assert len({d.id for d in first}) == len(first) and all(d.id.startswith('p2_') for d in first)
    spec = DashboardSpec(spec_version=1, build_id='b_000000000000', title=title, archetype='executive',
        theme=theme, datasource={'table': 'p.d.t'}, pages=[Page(index=2, name='Sample', height=900, decorations=first)])
    assert decoration_text_errors(spec) == []
    for d in first:
        b = box(spec.canvas, spec.grid, d.grid)
        assert b['x'] >= 0 and b['y'] >= 0 and b['x'] + b['w'] <= 1200 and b['y'] + b['h'] <= 900
        assert d.grid.row + d.grid.h <= content_row(kit, title, subtitle)
    long = decorations(kit, theme, 'W' * 80, 'A longer subtitle ' * 8)
    spec.pages[0].decorations = long
    assert decoration_text_errors(spec) == []


@pytest.fixture
def design_api(outline_api, monkeypatch):
    client, app, bid, sid, folder, llm = outline_api
    def no_model(_):
        raise AssertionError('The Design stage must not construct a model')
    monkeypatch.setattr(app.state.models, 'llm_for', no_model)
    return client, app, bid, sid, folder


def test_endpoint_contract_edits_revalidation_and_events(design_api):
    client, app, bid, sid, folder = design_api
    url = f'/api/builds/{bid}'
    assert client.get(url + '/design').json() is None
    check(client.get(url + '/design/presets'), 'design_presets.json')
    assert client.post(url + '/design/prefill').status_code == 409
    with app.state.db.connect() as conn:
        before = conn.execute('SELECT COUNT(*) FROM traces').fetchone()[0]
    confirmed = client.post(url + '/outline/confirm')
    check(confirmed, 'build.json')
    assert confirmed.json()['stage'] == 'design'
    assert confirmed.json()['artifacts']['outline'] == 'confirmed'
    first = client.get(url + '/design').json()
    fixture = json.loads((FIXTURES / 'design.json').read_text(encoding='utf-8'))
    fixture['subtitle'] = None  # contract: string|null
    shape(first, fixture)
    assert first['revision'] == 1 and first['issues'] == []
    draft = editable(first)
    draft.update(title='Custom title', subtitle='My subtitle', source='user', background='#FFFFFF', text='#FFFFFF')
    invalid = client.put(url + '/design', json=draft)
    assert invalid.status_code == 200 and invalid.json()['issues']
    draft['text'] = '#152B42'
    saved = client.put(url + '/design', json=draft)
    check(saved, 'design.json')
    assert saved.json()['revision'] == 3 and saved.json()['issues'] == []
    assert client.get(url + '/design').json() == saved.json()
    assert read_artifact(folder / 'docs/design.md').model_dump(mode='json') == saved.json()
    # Editing the outline then confirming keeps the Design and revalidates its pages.
    choice = client.get(url + '/outline').json()['sections'][0]['questions'][0]
    assert client.put(url + '/outline/selection', json={'questions': [{'id': choice['id'], 'selected': False}]}).status_code == 200
    assert client.post(url + '/outline/confirm').status_code == 200
    kept = client.get(url + '/design').json()
    assert editable(kept) == draft and kept['revision'] == 4
    reset = client.post(url + '/design/prefill')
    assert reset.status_code == 200 and reset.json()['revision'] == 5
    assert reset.json()['source'] == 'preset' and reset.json()['title'] != 'Custom title'
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM traces').fetchone()[0] == before
        events = [json.loads(r[0]) for r in conn.execute(
            "SELECT payload_json FROM events WHERE kind='artifact.updated' AND build_id=?", (bid,))]
    assert [e['revision'] for e in events if e['artifact'] == 'design'] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize('mode', ['style', 'recreate'])
def test_active_reference_used_on_first_prefill_and_explicit_reset(design_api, mode):
    client, app, bid, sid, folder = design_api
    record = {'id': 'ref_test', 'mode': mode}
    (folder / 'references.json').write_text(json.dumps(record), encoding='utf-8')
    meta, body = style_doc(reference(), [], record['id'])
    (folder / 'docs/style.md').write_text('---\n' + yaml.safe_dump(meta) + '---\n' + body, encoding='utf-8')
    assert client.post(f'/api/builds/{bid}/outline/confirm').status_code == 200
    url = f'/api/builds/{bid}/design'
    first = client.get(url).json()
    assert first['source'] == 'reference' and first['accent'] == reference().accent and first['issues'] == []
    meta['reference_set'] = 'obsolete'
    (folder / 'docs/style.md').write_text('---\n' + yaml.safe_dump(meta) + '---\n' + body, encoding='utf-8')
    reset = client.post(url + '/prefill').json()
    assert reset['source'] == 'preset'


@pytest.mark.parametrize('change', [{'background': '#123'}, {'palette': ['#000000'] * 2},
    {'palette': ['#000000'] * 9}, {'revision': 42}, {'issues': []}, {'unexpected': 'field'}])
def test_structural_errors_never_write(design_api, change):
    client, app, bid, sid, folder = design_api
    client.post(f'/api/builds/{bid}/outline/confirm')
    url = f'/api/builds/{bid}/design'
    original = client.get(url).json()
    response = client.put(url, json={**editable(original), **change})
    assert response.status_code == 422 and response.json()['error']['code'] == 'invalid_request'
    assert client.get(url).json() == original


@pytest.mark.parametrize('stage', ['blueprint', 'prototype', 'build', 'done'])
def test_later_stage_edit_gates_and_invalidation(design_api, stage):
    client, app, bid, sid, folder = design_api
    client.post(f'/api/builds/{bid}/outline/confirm')
    url = f'/api/builds/{bid}/design'
    original = client.get(url).json()
    artifacts = dict.fromkeys(('context', 'outline', 'design', 'blueprint'), 'confirmed')
    with app.state.db.connect() as conn:
        conn.execute('UPDATE builds SET stage=?,artifacts_json=? WHERE id=?', (stage, json.dumps(artifacts), bid))
    (folder / 'prototype.html').write_text('Published prototype', encoding='utf-8')
    (folder / 'spec.json').write_text('{"sentinel":true}', encoding='utf-8')
    assert client.post(url + '/prefill').status_code == 409
    response = client.put(url, json={**editable(original), 'title': 'Updated'})
    assert response.status_code == (409 if stage in ('build', 'done') else 200)
    if response.status_code == 200:
        build = client.get(f'/api/builds/{bid}').json()
        assert build['stage'] == 'design' and build['artifacts'] == {
            'context': 'confirmed', 'outline': 'confirmed', 'design': 'draft', 'blueprint': 'stale'}
    assert (folder / 'prototype.html').read_text(encoding='utf-8') == 'Published prototype'
    assert (folder / 'spec.json').read_text(encoding='utf-8') == '{"sentinel":true}'


def test_missing_build_and_busy_reservation(design_api):
    client, app, bid, sid, folder = design_api
    for route in ('design', 'design/presets'):
        assert client.get('/api/builds/b_000000000000/' + route).status_code == 404
    client.post(f'/api/builds/{bid}/outline/confirm')
    url = f'/api/builds/{bid}/design'
    original = client.get(url).json()
    app.state.harness.active_builds.add(bid)
    try:
        assert client.post(url + '/prefill').status_code == 409
        assert client.put(url, json=editable(original)).status_code == 409
    finally:
        app.state.harness.active_builds.discard(bid)
    assert client.get(url).json() == original


@pytest.mark.parametrize('failure', ['log', 'event'])
def test_post_write_failure_rolls_back_or_saves_consistent_flags(design_api, monkeypatch, failure):
    from dss.artifacts import okf
    client, app, bid, sid, folder = design_api
    client.post(f'/api/builds/{bid}/outline/confirm')
    url = f'/api/builds/{bid}/design'
    original = client.get(url).json()
    before = {name: (folder / 'docs' / name).read_bytes() for name in ('design.md', 'index.md', 'log.md')}
    artifacts = dict.fromkeys(('context', 'outline', 'design', 'blueprint'), 'confirmed')
    with app.state.db.connect() as conn:
        conn.execute('UPDATE builds SET stage=?,artifacts_json=? WHERE id=?', ('prototype', json.dumps(artifacts), bid))
        event_count = conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
    if failure == 'log':
        real_write = okf.atomic_write
        def fail_log(path, text):
            if path.name == 'log.md':
                raise OSError('log file locked')
            return real_write(path, text)
        monkeypatch.setattr(okf, 'atomic_write', fail_log)
    else:
        async def fail_event(*args, **kwargs):
            raise OSError('event transport failed')
        monkeypatch.setattr(app.state.harness, 'emit', fail_event)
    with pytest.raises(OSError):
        client.put(url, json={**editable(original), 'title': 'Changed after publication'})
    build = client.get(f'/api/builds/{bid}').json()
    saved = client.get(url).json()
    if failure == 'log':
        assert saved == original and build['stage'] == 'prototype' and build['artifacts'] == artifacts
        assert all((folder / 'docs' / name).read_bytes() == content for name, content in before.items())
    else:
        assert saved['title'] == 'Changed after publication' and saved['revision'] == original['revision'] + 1
        assert build['stage'] == 'design' and build['artifacts'] == {**artifacts, 'design': 'draft', 'blueprint': 'stale'}
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM events').fetchone()[0] == event_count
