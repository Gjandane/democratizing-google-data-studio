"""Synthetic provenance survives models, style, legacy specs and version/recipe boundaries."""
import copy
import json
from pathlib import Path

import pytest

from dss.db import now
from dss.harness.nodes.intake import write_doc
from dss.recipe.compiler import compile_recipe
from dss.render.prototype import render
from dss.spec.layout import box, synthetic_decoration, with_synthetic_label
from dss.spec.models import DashboardSpec, SYNTHETIC_LABEL, SYNTHETIC_LABEL_ID
from dss.spec.patch import apply_scoped, PatchError
from dss.spec.validate import validate_spec, synthetic_participation


@pytest.fixture
def sample():
    return DashboardSpec.model_validate_json(Path('tests/data/thin_spec.json').read_text())


def seed_source(app, bid, kind='synthetic', suffix='one'):
    with app.state.db.connect() as conn:
        conn.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?)',
                     ('s_' + suffix, bid, kind, SYNTHETIC_LABEL if kind == 'synthetic' else 'Real',
                      'project.data.' + suffix, 1000, '[]'))
        conn.execute('UPDATE sources SET columns_json=? WHERE id=?',
                     (json.dumps([{'name': 'region', 'type': 'string', 'bq_type': 'STRING', 'sample': []},
                                  {'name': 'revenue', 'type': 'number', 'bq_type': 'FLOAT', 'sample': []}]), 's_' + suffix))


def test_label_spec_html_recipe_and_reserved_box(sample):
    spec = with_synthetic_label(sample, True)
    assert not sample.datasource.synthetic and sample.canvas.height == 900
    assert not validate_spec(spec)
    assert with_synthetic_label(spec, True) == spec
    label = spec.pages[0].decorations[-1]
    bounds = box(spec.canvas, spec.grid, label.grid)
    assert bounds['y'] >= sample.canvas.height
    assert bounds['y'] + bounds['h'] + 24 == spec.canvas.height
    for layer in ('all', 'decoration'):
        html = render(spec, layer=layer)
        assert SYNTHETIC_LABEL in html and f'data-cid="{SYNTHETIC_LABEL_ID}"' in html
        assert 'color:#0F172A' in html and 'background:#FFFFFF' in html
    recipe = recipe_lines(spec)
    assert_background_only_label(recipe, spec)
    assert recipe[0]['canvas']['height'] == spec.canvas.height
    assert recipe[4]['op'] == 'set_background_image'  # 19.2: rename_page is s002


def recipe_lines(spec):
    return [json.loads(line) for line in compile_recipe(spec, 1).split('\n')[:-1]]


def assert_background_only_label(recipe, spec):
    """Change 2026-10-23 (release 2.5 b_91869163c217 s010): background_p1.png is the report's one
    copy of the label, so no recipe op draws it again over the background."""
    ops = recipe[1:]
    assert not [op for op in ops if op.get('component_id') == SYNTHETIC_LABEL_ID]
    assert not [op for op in ops if SYNTHETIC_LABEL in json.dumps(op)]
    first = ops[:next((i for i, op in enumerate(ops) if op['op'] == 'add_page'), len(ops))]
    assert [(op['path'], op['x'], op['y'], op['w'], op['h']) for op in first if op['op'] == 'set_background_image'] == [
        ('background_p1.png', 0, 0, spec.canvas.width, spec.pages[0].height)]


def designed():
    return DashboardSpec.model_validate_json(Path('tests/data/designed_spec.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('layout', ['code', 'designed'])
def test_background_png_is_the_one_label(sample, tmp_path, layout):
    """The decoration layer and background_p1.png draw the label in its reserved page-1 footer; the
    recipe places nothing for it."""
    import base64
    from playwright.sync_api import sync_playwright
    from dss.render import background
    from dss.spec.layout import layout_box
    spec = with_synthetic_label(sample, True) if layout == 'code' else designed()
    page = spec.pages[0]
    assert spec.datasource.synthetic and (page.design is not None) == (layout == 'designed')
    assert_background_only_label(recipe_lines(spec), spec)
    label = next(d for d in page.decorations if d.id == SYNTHETIC_LABEL_ID)
    bounds = layout_box(spec, page, label)
    # The footer is the page's last strip, below every other item.
    assert bounds['y'] + bounds['h'] + spec.grid.margin == page.height
    assert all(layout_box(spec, page, c)['y'] + layout_box(spec, page, c)['h'] <= bounds['y'] for c in page.components)
    html = render(spec, layer='decoration', page=1)
    assert html.count(f'data-cid="{SYNTHETIC_LABEL_ID}"') == 1
    scales = background.write_pages(spec, tmp_path)
    scale = scales['background_p1.png']
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            view = browser.new_page(viewport={'width': spec.canvas.width, 'height': page.height}, device_scale_factor=scale)
            view.set_content(html, wait_until='load')
            view.evaluate('document.fonts.ready')
            element = view.locator(f'[data-cid="{SYNTHETIC_LABEL_ID}"]')
            assert element.inner_text() == SYNTHETIC_LABEL
            drawn = element.bounding_box()
            assert drawn == dict(x=bounds['x'], y=bounds['y'], width=bounds['w'], height=bounds['h'])
            expected = element.screenshot()
            encoded = base64.b64encode((tmp_path / 'background_p1.png').read_bytes()).decode()
            view.set_content(f'<body style="margin:0"><img style="display:block;width:{spec.canvas.width}px" '
                             f'src="data:image/png;base64,{encoded}"></body>')
            view.locator('img').wait_for()
            # The PNG's footer pixels are the label as the decoration layer draws it.
            assert view.screenshot(clip=drawn) == expected
        finally:
            browser.close()


@pytest.mark.parametrize('change', ['remove', 'move', 'text', 'opacity', 'color', 'size', 'logo', 'component_overlap', 'decoration_overlap'])
def test_invalid_label_or_cover_rejected_at_every_boundary(sample, change):
    spec = with_synthetic_label(sample, True)
    label = spec.pages[0].decorations[-1]
    if change == 'remove':
        spec.pages[0].decorations.pop()
    elif change == 'move':
        label.grid.row -= 1
    elif change == 'text':
        label.text = 'Original data'
    elif change == 'opacity':
        label.style['opacity'] = 0
    elif change == 'color':
        label.style['color'] = '#FFFFFF'
    elif change == 'size':
        label.style['font_size'] = 0
    elif change == 'logo':
        label.kind = 'logo'
        label.style['image_path'] = 'style.png'
    elif change == 'component_overlap':
        spec.pages[0].components[0].grid = label.grid.model_copy()
    else:
        spec.pages[0].decorations[0].grid = label.grid.model_copy()
    assert any('Synthetic' in e['message'] for e in validate_spec(spec))
    with pytest.raises(ValueError, match='Synthetic'):
        render(spec)
    with pytest.raises(ValueError, match='Synthetic'):
        compile_recipe(spec, 1)


@pytest.mark.parametrize('operation', [
    {'op': 'remove', 'path': '/pages/0/decorations/1'},
    {'op': 'replace', 'path': '/pages/0/decorations/1/text', 'value': 'Original data'},
    {'op': 'replace', 'path': '/pages/0/decorations/1/grid/row', 'value': 1},
    {'op': 'replace', 'path': '/pages/0/decorations/1/style/opacity', 'value': 0},
    {'op': 'copy', 'from': '/pages/0/decorations/1/text', 'path': '/pages/0/components/0/label'},
])
def test_patch_cannot_change_or_copy_label(sample, operation):
    document = with_synthetic_label(sample, True).model_dump()
    before = copy.deepcopy(document)
    target = 'p1_revenue' if operation['op'] == 'copy' else SYNTHETIC_LABEL_ID
    with pytest.raises(PatchError, match='read-only'):
        apply_scoped(document, [operation], target)
    assert document == before


def test_image_theme_cannot_hide_label(sample):
    spec = with_synthetic_label(sample, True)
    spec.theme.background = spec.theme.surface = spec.theme.text = '#FFFFFF'
    spec.theme.font_family = 'fantasy'
    spec.theme.radius = 1000
    html = render(spec)
    assert not validate_spec(spec)
    label_html = html.split(f'data-cid="{SYNTHETIC_LABEL_ID}"', 1)[1].split('</div>', 1)[0]
    assert 'color:#0F172A' in label_html and 'font-family:Arial' in label_html
    assert 'border-radius:0px' in label_html and 'opacity:1' in label_html


def test_real_data_has_no_label(sample, tmp_path, monkeypatch):
    assert not validate_spec(sample)
    assert SYNTHETIC_LABEL not in render(sample)
    assert SYNTHETIC_LABEL not in compile_recipe(sample, 1)
    # A real-data build's recipe and background input are unchanged by the label change.
    data = Path('tests/data')
    golden = DashboardSpec.model_validate_json((data / 'golden_spec.json').read_text(encoding='utf-8'))
    assert not golden.datasource.synthetic
    assert compile_recipe(golden, 3) == (data / 'golden_recipe.jsonl').read_text(encoding='utf-8')
    captured = []
    monkeypatch.setattr('dss.render.background.capture', lambda html, path, *a, **k: (captured.append(html), path.write_bytes(b'PNG')))
    from dss.render import background
    background.write_pages(sample, tmp_path)
    assert captured == [render(sample, layer='decoration', folder=tmp_path, page=p.index) for p in sample.pages]
    assert SYNTHETIC_LABEL not in ''.join(captured)


def test_source_participation_tracks_base_and_joins(client, app, build_id, tmp_path):
    seed_source(app, build_id, 'bigquery', 'base')
    seed_source(app, build_id, 'synthetic', 'joined')
    folder = tmp_path / 'v1'
    (folder / 'docs').mkdir(parents=True)
    path = folder / 'docs/derived-fields.md'
    write_doc(path, {'type': 'Derived Fields', 'joins': []}, '')
    assert not synthetic_participation(app.state.db, build_id, folder)
    write_doc(path, {'type': 'Derived Fields', 'joins': [{'table': 'project.data.joined', 'on': 'TRUE'}]}, '')
    assert synthetic_participation(app.state.db, build_id, folder)


def test_old_spec_api_compile_and_versions_restore_label(client, app, build_id, sample, monkeypatch):
    from fakes import ready_fixture
    seed_source(app, build_id)
    folder = app.state.settings.get().data_dir / 'builds' / build_id / 'v1'
    folder.mkdir(parents=True)
    # A copied legacy spec has no provenance bit or label.
    legacy = sample.model_dump()
    legacy['datasource'].pop('synthetic')
    (folder / 'spec.json').write_text(json.dumps(legacy), encoding='utf-8')
    (folder / 'background_p1.png').write_bytes(b'old unlabelled image')
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='prototype' WHERE id=?", (build_id,))
        conn.execute("INSERT INTO versions(build_id,n,status,spec_version,created_at) VALUES(?,1,'draft',1,?)", (build_id, now()))
    ready_fixture(app, build_id, folder)
    captures = []
    def capture(html, path, w, h):
        captures.append(html)
        assert SYNTHETIC_LABEL in html
        path.write_bytes(b'labelled image')
    monkeypatch.setattr('dss.render.background.capture', capture)
    response = client.get(f'/api/builds/{build_id}/spec')
    assert response.json()['datasource']['synthetic'] is True
    assert SYNTHETIC_LABEL in client.get(f'/api/builds/{build_id}/prototype').text
    compiled = client.post(f'/api/builds/{build_id}/recipe')
    assert compiled.status_code == 200, compiled.text
    # The rebuilt background carries the label; the recipe draws no second copy over it.
    assert SYNTHETIC_LABEL not in (folder / 'recipe.jsonl').read_text(encoding='utf-8')
    assert (folder / 'background_p1.png').read_bytes() == b'labelled image'
    # Compilation must not invalidate the saved feasibility proof for the next run.
    assert client.post(f'/api/builds/{build_id}/recipe').status_code == 200
    response = client.post(f'/api/builds/{build_id}/versions')
    assert response.status_code == 201, response.text
    copied = folder.parent / 'v2'
    assert SYNTHETIC_LABEL in (copied / 'spec.json').read_text()
    assert SYNTHETIC_LABEL in (copied / 'prototype.html').read_text()
    assert (copied / 'background_p1.png').read_bytes() == b'labelled image'
    assert response.json()['sources'][0]['kind'] == 'synthetic'
    assert len(captures) == 3




async def test_legacy_revision_publishes_label_in_all_artifacts(client, app, build_id, monkeypatch):
    from test_revise import seed_revision, run, response, op
    setup = seed_revision(app, build_id, monkeypatch)
    seed_source(app, build_id)
    _, _, folder, _, _, captured = setup
    _, _, updated = await run(setup, response([op('/pages/0/decorations/0/style/font_size', 40, 'add')]),
        [{'component_id': 'p1_title', 'text': 'make the title bigger'}])
    assert updated.datasource.synthetic and not validate_spec(updated)
    assert updated.spec_version == 2
    assert SYNTHETIC_LABEL in (folder / 'spec.json').read_text()
    assert SYNTHETIC_LABEL in (folder / 'prototype.html').read_text()
    assert captured and SYNTHETIC_LABEL in captured[-1]


async def test_noop_legacy_revision_still_restores_label(client, app, build_id, monkeypatch):
    from test_revise import seed_revision, run, response
    setup = seed_revision(app, build_id, monkeypatch)
    seed_source(app, build_id)
    _, _, folder, _, _, captured = setup
    _, _, updated = await run(setup, response([]), [{'component_id': 'p1_revenue', 'text': 'keep this as it is'}])
    assert updated.datasource.synthetic and updated.spec_version == 2
    assert SYNTHETIC_LABEL in (folder / 'spec.json').read_text()
    assert captured and SYNTHETIC_LABEL in captured[-1]




def test_heading_cannot_expand_into_synthetic_footer(sample):
    spec = with_synthetic_label(sample, True)
    title = spec.pages[0].decorations[0]
    title.text = 'Multiline\nheading'
    title.grid.row = spec.pages[0].decorations[-1].grid.row - 3
    title.grid.h = 6
    assert any('reserved Synthetic' in e['message'] for e in validate_spec(spec))
    with pytest.raises(ValueError, match='reserved Synthetic'):
        render(spec)
