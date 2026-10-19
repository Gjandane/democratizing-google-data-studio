"""Decoration-only Chromium capture, called from a worker thread on Windows."""
from playwright.sync_api import sync_playwright


def capture(html, path, width, height):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': height}, device_scale_factor=1)
            # Decoration HTML has inline assets and no chart/CDN scripts.
            page.set_content(html, wait_until='load', timeout=10000)
            page.evaluate('document.fonts.ready')
            page.locator('#dss-canvas').screenshot(path=str(path), animations='disabled', timeout=10000)
        finally:
            browser.close()
