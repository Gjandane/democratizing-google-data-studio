"""Shared live configuration and image helpers for synthetic intake tests."""
import os
from pydantic import SecretStr
from dss.config import Config
from dss.main import create_app

def trace(app, run_id):
    with app.state.db.connect() as conn:
        row = conn.execute("SELECT * FROM traces WHERE run_id=?", (run_id,)).fetchone()
    assert row is not None, run_id
    return dict(row)

def live_app(tmp_path):
    env = Config.from_env()
    assert env.google_api_key.get_secret_value(), 'GOOGLE_API_KEY must be configured'
    project = (os.environ.get('DSS_LIVE_GCP_PROJECT') or env.gcp_project_id).strip()
    assert project, 'GCP_PROJECT_ID must be configured'
    config = env.model_copy(update={'data_dir': tmp_path / 'data', 'db_path': None, 'static_dir': None,
        'access_code': SecretStr(''), 'engine_mode': 'local', 'cloud_service': ''})
    return create_app(config), config, project

def revenue_reference():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 1200, 'height': 700})
            page.set_content('''<body style="margin:0;background:#F1F5F9;font-family:Arial;color:#0F172A">
              <h1 style="margin:28px">Regional sales</h1>
              <section style="margin:28px;padding:24px;background:white;border-radius:12px">
              <h2>Revenue by region</h2><svg width="1000" height="450">
              <g fill="#1E40AF"><rect x="100" y="100" width="150" height="300"/>
              <rect x="400" y="200" width="150" height="200"/>
              <rect x="700" y="250" width="150" height="150"/></g>
              <text x="150" y="430">North</text><text x="450" y="430">South</text>
              <text x="750" y="430">West</text></svg></section></body>''')
            return page.screenshot(type='png')
        finally:
            browser.close()
