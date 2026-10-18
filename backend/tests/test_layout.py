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
