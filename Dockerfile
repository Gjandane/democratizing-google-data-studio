# One Cloud Run image: the backend (FastAPI on $PORT) serving the built frontend.
# No engine, no data/, no .env (contracts/conventions.md, Cloud deployment). Built by
# deploy/deploy.sh through Cloud Build (`gcloud run deploy --source .`).

# Stage 1: build the frontend (its mocks import contracts/fixtures, so contracts/ comes along).
FROM node:20-bookworm-slim AS frontend
WORKDIR /app
COPY contracts/ contracts/
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci --no-audit --no-fund
COPY frontend/ frontend/
RUN cd frontend && npm run build

# Stage 2: the backend with Playwright Chromium (background_p<n>.png renders).
FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 \
    UV_FROZEN=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install --no-cache-dir "uv>=0.13"

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY contracts/ /app/contracts/
COPY backend/ ./
RUN uv sync --frozen --no-dev
RUN uv run playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*
# Smoke test: a missing or broken browser fails the build here, not at the first render.
RUN uv run python -c "import os; from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(); pg = b.new_page(); pg.set_content('<h1>smoke</h1>'); pg.screenshot(path='/tmp/smoke.png'); b.close(); p.stop(); assert os.path.getsize('/tmp/smoke.png') > 0; os.remove('/tmp/smoke.png'); print('chromium smoke screenshot ok')"

COPY --from=frontend /app/frontend/dist /app/frontend/dist
ENV PORT=8080 \
    DSS_STATIC_DIR=/app/frontend/dist
EXPOSE 8080
CMD ["uv", "run", "python", "-m", "dss.main"]
