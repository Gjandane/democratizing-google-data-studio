"""Backend application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from fastapi.responses import JSONResponse

from dss.api import builds, settings, prototype, run, dev, chat, engine
from dss.harness.nodes.execute import environment
from dss.bus import EventBus
from dss.config import Config, SettingsStore
from dss.db import Database
from dss.harness.guardrails import RunError
from dss.harness.llm import ModelRouter


def create_app(config=None, *, model_lister=None, bigquery_factory=None):
    config = config or Config.from_env()

    @asynccontextmanager
    async def lifespan(app):
        app.state.db = Database(config.db_path or config.data_dir / "dss.sqlite")
        app.state.db.initialize()
        app.state.settings = SettingsStore(config, app.state.db)
        app.state.models = ModelRouter(app.state.settings, model_lister)
        app.state.bus = EventBus()
        app.state.engine_busy = False
        app.state.engine_tasks = set()
        from dss.data.bigquery import BigQuery
        app.state.bigquery_factory = bigquery_factory or BigQuery
        from dss.harness.graph import AgentHarness
        app.state.harness = AgentHarness(app.state.db, app.state.bus, app.state.models)
        await app.state.models.refresh()
        yield
        if app.state.engine_tasks:
            import asyncio
            await asyncio.gather(*app.state.engine_tasks, return_exceptions=True)

    app = FastAPI(lifespan=lifespan)
    app.include_router(settings.router)
    app.include_router(builds.router)
    app.include_router(chat.router)
    app.include_router(prototype.router)
    app.include_router(run.router)
    app.include_router(engine.router)
    app.include_router(engine.trace_router)
    if environment().get("DSS_DEV") == "1":
        app.include_router(dev.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.exception_handler(RunError)
    async def run_error(request, error):
        return JSONResponse({"error": {"code": error.code, "message": error.message,
                                      "detail": error.detail}}, status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Pydantic's default errors include input values, including write-only secrets.
        return JSONResponse({"error": {"code": "invalid_request", "message": "Invalid request",
                                      "detail": {}}}, status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse({"error": {"code": "not_found" if error.status_code == 404 else "http_error",
                                      "message": "Request could not be handled", "detail": {}}},
                            status_code=error.status_code)

    return app


app = create_app()
