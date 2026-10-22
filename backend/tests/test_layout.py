import random
import pytest
from dss.spec.layout import box
from dss.spec.models import Canvas, Grid, Cell


def test_two_spans_fill_width():
    canvas, grid = Canvas(), Grid()
    a = box(canvas, grid, Cell(col=1,row=1,w=6,h=3))
    b = box(canvas, grid, Cell(col=7,row=1,w=6,h=3))
    assert a['x'] == 24
    assert b['x'] + b['w'] == 1176
    assert 15 <= b['x'] - a['x'] - a['w'] <= 17


def test_seeded_geometry():
    rng = random.Random(7)
    canvas, grid = Canvas(), Grid()
    for _ in range(50):
        split = rng.randint(1,11)
        a = box(canvas, grid, Cell(col=1,row=1,w=split,h=3))
        b = box(canvas, grid, Cell(col=split+1,row=1,w=12-split,h=3))
        assert 15 <= b['x'] - a['x'] - a['w'] <= 17
        assert a['x'] >= 0 and b['x'] + b['w'] <= canvas.width
    with pytest.raises(ValueError):
        box(canvas, grid, Cell(col=12,row=1,w=2,h=3))
    with pytest.raises(ValueError):
        box(canvas, grid, Cell(col=1,row=45,w=2,h=3))


def test_a_component_box_is_returned_unchanged():
    from pathlib import Path
    from dss.spec.layout import layout_box
    from dss.spec.models import DashboardSpec
    spec = DashboardSpec.model_validate_json(Path('tests/data/designed_spec.json').read_text(encoding='utf-8'))
    page = spec.pages[0]
    for c in page.components:
        assert layout_box(spec, page, c) == c.box.model_dump()
        assert layout_box(spec, page, c) != box(spec.canvas, spec.grid, c.grid, height=page.height)
    design, label = page.decorations
    assert layout_box(spec, page, design) == dict(x=0, y=0, w=1440, h=page.height)
    # Without a box (code layout, synthetic label): the grid cell's box at the canvas width.
    plain = page.components[0].model_copy(update={'box': None})
    assert layout_box(spec, page, plain) == box(spec.canvas, spec.grid, plain.grid, height=page.height)
    assert layout_box(spec, page, label) == box(spec.canvas, spec.grid, label.grid, height=page.height)
    assert layout_box(spec, page, label)['y'] == 1224


def test_design_decoration_covers_the_page_rows():
    from pathlib import Path
    from dss.spec.layout import design_decoration
    from dss.spec.models import DashboardSpec
    spec = DashboardSpec.model_validate_json(Path('tests/data/designed_spec.json').read_text(encoding='utf-8'))
    item = design_decoration(1, spec.pages[0].height)
    assert item == spec.pages[0].decorations[0]
    b = box(spec.canvas, spec.grid, item.grid, height=spec.pages[0].height)
    assert (b['x'], b['y']) == (24, 24) and spec.pages[0].height - 40 < b['y'] + b['h'] <= spec.pages[0].height - 24
