"""Backend application entry point."""
from contextlib import asynccontextmanager
import asyncio
import logging
import os
import re
from pathlib import Path
import tempfile

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from dss.api import builds, settings, prototype, run, dev, chat, engine, session, agent, feasibility, synthetic_data, workflow
from dss.agent.jobs import AgentJobs
from dss.harness.nodes.execute import environment
from dss.bus import EventBus
from dss.config import Config, SettingsStore
from dss.db import Database
from dss.harness.guardrails import RunError
from dss.harness.llm import ModelRouter

SHUTDOWN_BACKUP_TIMEOUT_S = 3
logger = logging.getLogger(__name__)


class SPAFiles(StaticFiles):
    async def get_response(self, path, scope):
        # StaticFiles normalizes paths to backslashes on Windows.
        url_path = path.replace("\\", "/")
        if url_path == "api" or url_path.startswith("api/"):
            raise HTTPException(404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


def create_app(config=None, *, model_lister=None, bigquery_factory=None):
    config = config or Config.from_env()

    @asynccontextmanager
    async def lifespan(app):
        config.validate_start()
        if config.open_link:
            logger.warning("DSS_PUBLIC=1: the API is open to anyone with the link (no access gate)")
        db_path = config.db_path or (Path(tempfile.gettempdir()) / "dss.sqlite" if config.cloud_service
                                     else config.data_dir / "dss.sqlite")
        if config.cloud_service and db_path.resolve().is_relative_to(config.data_dir.resolve()):
            raise RuntimeError("Cloud Run requires DSS_DB_PATH outside DSS_DATA_DIR")
        app.state.db = Database(db_path, config.data_dir)
        app.state.db.initialize()
        app.state.settings = SettingsStore(config, app.state.db)
        app.state.models = ModelRouter(app.state.settings, model_lister)
        app.state.bus = EventBus()
        app.state.engine_busy = False
        app.state.engine_tasks = set()
        from dss.data.bigquery import BigQuery
        app.state.bigquery_factory = bigquery_factory or BigQuery
        from dss.spec.publication import recover
        await recover(app.state.db, app.state.settings.get(), app.state.bigquery_factory)
        await synthetic_data.node.recover(app.state.db, app.state.settings.get(), app.state.bigquery_factory)
        from dss.harness.graph import AgentHarness
        app.state.harness = AgentHarness(app.state.db, app.state.bus, app.state.models)
        app.state.agent_jobs = AgentJobs(app.state)
        sweep_task = None
        if config.engine_mode == "agent":
            # The startup sweep: running tickets fail, expired ones end, waiting ones resume.
            await app.state.agent_jobs.recover()
            sweep_task = asyncio.create_task(app.state.agent_jobs.sweep_forever())
        await app.state.models.refresh()
        stop_backup = asyncio.Event()
        backup_task = (asyncio.create_task(app.state.db.periodic_backup(stop_backup))
                       if app.state.db.backup_path else None)
        try:
            yield
        finally:
            shutdown_deadline = asyncio.get_running_loop().time() + SHUTDOWN_BACKUP_TIMEOUT_S
            try:
                if config.engine_mode == "agent":
                    await app.state.agent_jobs.close()
                    sweep_task.cancel()
                tasks = tuple(app.state.engine_tasks)
                for task in tasks:
                    task.cancel()
                if tasks:
                    # Workflow tasks include reference HTML calls with a ten-minute deadline.
                    # Cancel in every mode; their finally blocks close streams, clean candidates
                    # and release ownership. SSE disconnect does not enter this path.
                    done, pending = await asyncio.wait(tasks, timeout=max(
                        0, shutdown_deadline - asyncio.get_running_loop().time()))
                    for task in done:
                        if not task.cancelled():
                            task.exception()  # retrieve guarded background failures
                    if pending:
                        logger.warning('Active work exceeded the shutdown budget; cleanup deferred until restart')
            finally:
                stop_backup.set()
                if backup_task:
                    try:
                        async with asyncio.timeout_at(shutdown_deadline):
                            await backup_task
                            await app.state.db.async_backup(force=True)
                    except TimeoutError:
                        logger.warning("Database backup exceeded the shutdown budget")

    app = FastAPI(lifespan=lifespan)
    app.state.config = config
    app.add_middleware(session.AccessMiddleware, config=config)
    from dss.spec.publication import PublicationReads
    app.add_middleware(PublicationReads)
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
    app.include_router(session.router)
    app.include_router(settings.router)
    app.include_router(builds.router)
    app.include_router(workflow.router)
    app.include_router(feasibility.router)
    app.include_router(synthetic_data.router)
    app.include_router(chat.router)
    app.include_router(prototype.router)
    app.include_router(run.router)
    app.include_router(engine.router)
    app.include_router(engine.trace_router)
    app.include_router(agent.router)
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
        # Messages remain readable; the removed chat input must still answer 404,
        # rather than the router's 405 for a method mismatch on the history URL.
        if (error.status_code == 405 and request.method == 'POST' and
                re.fullmatch(r'/api/builds/[^/]+/messages', request.url.path)):
            error = HTTPException(404)
        return JSONResponse({"error": {"code": "not_found" if error.status_code == 404 else "http_error",
                                      "message": "Request could not be handled", "detail": {}}},
                            status_code=error.status_code)

    if config.static_dir:
        app.mount("/", SPAFiles(directory=config.static_dir))
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")),
                forwarded_allow_ips="*", timeout_graceful_shutdown=3)
