"""Decoration-only Chromium capture, called from a worker thread on Windows."""
from playwright.sync_api import sync_playwright

# 2x pixels (2400 x 1064 for a 1200 x 532 page) keep Data Studio's scaled view sharp;
# the recipe box stays the canvas size.
SCALE = 2


def names(spec):
    return [f'background_p{page.index}.png' for page in spec.pages]


def write_pages(spec, folder):
    """background_p<n>.png at SCALE x canvas size per page; each file replaces atomically."""
    from dss.render.prototype import render
    for page, name in zip(spec.pages, names(spec)):
        temporary = folder / name.replace('.png', '.tmp.png')
        capture(render(spec, layer='decoration', folder=folder, page=page.index), temporary,
                spec.canvas.width, page.height)
        temporary.replace(folder / name)


def capture(html, path, width, height):
    # Recipe compilation is also called synchronously by async API handlers.
    import asyncio
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _capture(html, path, width, height)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as worker:
        return worker.submit(_capture, html, path, width, height).result()


def _capture(html, path, width, height):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': height}, device_scale_factor=SCALE)
            # Decoration HTML has inline assets and no chart/CDN scripts.
            page.set_content(html, wait_until='load', timeout=10000)
            page.evaluate('document.fonts.ready')
            page.locator('#dss-canvas').screenshot(path=str(path), animations='disabled', timeout=10000)
        finally:
            browser.close()
