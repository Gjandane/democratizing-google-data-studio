"""One integer geometry implementation shared by HTML and recipes."""
def box(canvas, grid, cell, *, height=None):
    col_w = (canvas.width - 2 * grid.margin - (grid.columns - 1) * grid.gutter) / grid.columns
    left = grid.margin + (cell.col - 1) * (col_w + grid.gutter)
    right = left + cell.w * col_w + (cell.w - 1) * grid.gutter
    x, end = round(left), round(right)
    y = grid.margin + (cell.row - 1) * grid.row_height
    h = cell.h * grid.row_height - grid.gutter
    if (col_w <= 0 or cell.col + cell.w - 1 > grid.columns or
            x < 0 or y < 0 or end > canvas.width or y + h > (height or canvas.height) or end <= x or h <= 0):
        raise ValueError("Grid box is outside the canvas or has no area")
    return dict(x=x, y=y, w=end-x, h=h)
