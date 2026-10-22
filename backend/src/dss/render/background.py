"""Decoration-only Chromium capture, called from a worker thread on Windows."""
from playwright.sync_api import sync_playwright

# 3x pixels (3600 x 1596 for a 1200 x 532 page) keep Data Studio's scaled view sharp;
# the recipe box stays the canvas size.
SCALE = 3
# A designed page's PNG drops to scale 2 only when its 3x file would reach this size.
LIMIT = 2 * 1024 * 1024
DESIGNED_FALLBACK_SCALE = 2


def names(spec):
    return [f'background_p{page.index}.png' for page in spec.pages]


def write_pages(spec, folder):
    """background_p<n>.png at SCALE x canvas size per page; each file replaces atomically.
    Returns {name: device scale} (2 only for a designed page whose 3x file reached LIMIT)."""
    from dss.render.prototype import render
    scales = {}
    for page, name in zip(spec.pages, names(spec)):
        temporary = folder / name.replace('.png', '.tmp.png')
        html = render(spec, layer='decoration', folder=folder, page=page.index)
        capture(html, temporary, spec.canvas.width, page.height)
        scales[name] = SCALE
        if page.design is not None and temporary.stat().st_size >= LIMIT:
            capture(html, temporary, spec.canvas.width, page.height, scale=DESIGNED_FALLBACK_SCALE)
            scales[name] = DESIGNED_FALLBACK_SCALE
        temporary.replace(folder / name)
    return scales


def capture(html, path, width, height, scale=SCALE):
    # Recipe compilation is also called synchronously by async API handlers.
    import asyncio
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _capture(html, path, width, height, scale)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as worker:
        return worker.submit(_capture, html, path, width, height, scale).result()


def _capture(html, path, width, height, scale=SCALE):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': height}, device_scale_factor=scale)
            # Decoration HTML has inline assets and no chart/CDN scripts.
            page.set_content(html, wait_until='load', timeout=10000)
            page.evaluate('document.fonts.ready')
            page.locator('#dss-canvas').screenshot(path=str(path), animations='disabled', timeout=10000)
        finally:
            browser.close()
