import json
from typing import Literal

import yaml
from fastapi import APIRouter, Request, UploadFile, File
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from dss.db import new_id, now
from dss.data import bigquery as bq
from dss.harness.guardrails import RunError

router = APIRouter(prefix="/api/builds")


def version_file(state, build_id, name, subfolder=""):
    import re
    from dss.api.prototype import current
    _, folder = current(state, build_id)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name) or name in (".", ".."):
        raise RunError("invalid_name", "Invalid file name", 400)
    base = (folder / subfolder).resolve()
    path = (base / name).resolve()
    if not path.is_relative_to(base):
        raise RunError("invalid_name", "Invalid file name", 400)
    if not path.is_file():
        raise RunError("not_found", "File not found", 404)
    return path


@router.get("/{build_id}/docs/{path}")
def document(build_id: str, path: str, request: Request):
    from fastapi.responses import FileResponse
    return FileResponse(version_file(request.app.state, build_id, path, "docs"), media_type="text/markdown")


@router.get("/{build_id}/files/{name}")
def version_asset(build_id: str, name: str, request: Request):
    from fastapi.responses import FileResponse
    return FileResponse(version_file(request.app.state, build_id, name))


@router.get("/{build_id}/files/screens/{name}")
def screenshot(build_id: str, name: str, request: Request):
    from fastapi.responses import FileResponse
    return FileResponse(version_file(request.app.state, build_id, name, "screens"))


class BuildCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="Untitled dashboard", min_length=1, max_length=300)
    archetype: Literal["executive", "storytelling", "operational", "analytical"]
    mode: Literal["data", "research"]


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["gcs", "bigquery"]
    uri: str


def require_build(db, build_id):
    if not db.build_exists(build_id):
        raise RunError("build_not_found", "Build not found", 404)


def build_response(db, config, build_id):
    require_build(db, build_id)
    with db.connect() as connection:
        build = dict(connection.execute("SELECT * FROM builds WHERE id=?", (build_id,)).fetchone())
        sources = [{**dict(row), "columns": json.loads(row["columns_json"])}
                   for row in connection.execute("SELECT * FROM sources WHERE build_id=? ORDER BY rowid", (build_id,))]
        versions = [dict(row) for row in connection.execute(
            "SELECT n,status,report_url,created_at FROM versions WHERE build_id=? ORDER BY n", (build_id,))]
        version = connection.execute("SELECT spec_version,report_url FROM versions WHERE build_id=? AND n=?",
                                     (build_id, build["current_version"])).fetchone()
    docs_dir = config.data_dir / "builds" / build_id / f'v{build["current_version"]}' / "docs"
    docs = []
    if docs_dir.is_dir():
        for path in sorted(docs_dir.glob("*.md")):
            if path.name in ("index.md", "log.md"):
                continue
            text = path.read_text(encoding="utf-8")
            frontmatter = yaml.safe_load(text.split("---", 2)[1]) if text.startswith("---") else {}
            docs.append({"path": path.name, "title": frontmatter.get("title", path.stem), "type": frontmatter["type"]})
    return {**build, "ready_for_plan": bool(build["ready_for_plan"]),
            "sources": [bq.public_source({k: source[k] for k in ("id", "kind", "name", "bq_table", "row_count", "columns")}) for source in sources],
            "docs": docs, "versions": versions, "spec_version": version["spec_version"] if version else None,
            "report_url": version["report_url"] if version else None}


@router.post("", status_code=201)
async def create_build(body: BuildCreate, request: Request):
    state = request.app.state
    build_id, timestamp = new_id("b"), now()
    with state.db.connect() as connection:
        connection.execute("INSERT INTO builds(id,title,archetype,mode,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                           (build_id, body.title, body.archetype, body.mode, "connect", timestamp, timestamp))
        connection.execute("INSERT INTO versions(build_id,n,status,created_at) VALUES(?,?,?,?)", (build_id, 1, "draft", timestamp))
    await state.harness.run("create_build", build_id)
    return build_response(state.db, state.settings.get(), build_id)


@router.get("")
def list_builds(request: Request):
    with request.app.state.db.connect() as connection:
        return [dict(row) for row in connection.execute(
            "SELECT b.id,b.title,b.archetype,b.stage,b.updated_at,v.report_url FROM builds b "
            "LEFT JOIN versions v ON v.build_id=b.id AND v.n=b.current_version ORDER BY b.updated_at DESC,b.rowid DESC")]


@router.get("/{build_id}")
def get_build(build_id: str, request: Request):
    state = request.app.state
    return build_response(state.db, state.settings.get(), build_id)


@router.post("/{build_id}/versions", status_code=201)
async def new_version(build_id: str, request: Request):
    import shutil
    from dss.api.prototype import current, read_spec
    state = request.app.state
    build, folder = current(state, build_id)
    if build["stage"] not in ("done", "prototype") or build_id in state.harness.active_builds:
        raise RunError("wrong_stage", "A new version needs an idle prototype or completed build", 409,
                       {"stage": build["stage"]})
    document = read_spec(folder)
    async def perform(run_id):
        number = build["current_version"] + 1
        destination = folder.parent / f"v{number}"
        # Reuse deterministic render inputs and the existing view, never engine outputs.
        def copy_inputs():
            destination.mkdir()
            for path in folder.iterdir():
                if path.name in ("recipe.jsonl", "events.jsonl", "screens"):
                    continue
                if path.is_dir():
                    shutil.copytree(path, destination / path.name)
                else:
                    shutil.copy2(path, destination / path.name)
        import asyncio
        await asyncio.to_thread(copy_inputs)
        with state.db.connect() as conn:
            conn.execute("INSERT INTO versions(build_id,n,status,spec_version,created_at) VALUES(?,?,'draft',?,?)",
                         (build_id, number, document.spec_version, now()))
            conn.execute("UPDATE builds SET current_version=?,stage='prototype',updated_at=? WHERE id=?",
                         (number, now(), build_id))
        await state.harness.emit(build_id, run_id, "stage.changed", {"stage": "prototype"})
        result = build_response(state.db, state.settings.get(), build_id)
        await state.harness.emit(build_id, run_id, "build.updated", {"build": result})
        return json.dumps(result)
    result = await state.harness.run("versions", build_id, perform)
    return json.loads(result["reply"])


async def intake_sources(request, build_id, sources):
    state = request.app.state
    require_build(state.db, build_id)
    config = state.settings.get()
    if not config.gcp_project_id.strip():
        raise RunError("gcp_not_configured", "Set the GCP project in Settings before connecting data", 503)
    result = await state.harness.run("intake", build_id, {
        "sources": sources, "config": config, "factory": state.bigquery_factory})
    await state.harness.emit(build_id, result["run_id"], "build.updated", {"build": build_response(state.db, config, build_id)})
    return json.loads(result["reply"])


@router.post("/{build_id}/sources/upload", status_code=201)
async def upload_sources(build_id: str, request: Request, files: list[UploadFile] = File(...)):
    require_build(request.app.state.db, build_id)
    if not files:
        raise bq.invalid("At least one CSV file is required")
    sources = []
    try:
        for file in files:
            name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
            if not name.lower().endswith(".csv"):
                raise bq.invalid("Only .csv files are supported")
            if file.size is not None and file.size > bq.MAX_SOURCE_BYTES:
                raise bq.invalid("File exceeds 100 MB")
            content = await file.read(bq.MAX_SOURCE_BYTES + 1)
            if len(content) > bq.MAX_SOURCE_BYTES:
                raise bq.invalid("File exceeds 100 MB")
            sources.append({"kind": "upload", "name": name, "content": content})
        return {"sources": await intake_sources(request, build_id, sources)}
    finally:
        for file in files:
            await file.close()


@router.post("/{build_id}/sources", status_code=201)
async def connect_source(build_id: str, body: SourceCreate, request: Request):
    if body.kind == "gcs":
        _, path = bq.gcs_uri(body.uri)
        name = path.rsplit("/", 1)[-1]
    else:
        bq.table_uri(body.uri)
        name = body.uri
    return (await intake_sources(request, build_id, [{"kind": body.kind, "name": name, "uri": body.uri}]))[0]


@router.get("/{build_id}/events")
async def events(build_id: str, request: Request):
    if not request.app.state.db.build_exists(build_id):
        raise RunError("build_not_found", "Build not found", 404)
    return EventSourceResponse(request.app.state.bus.stream(build_id), ping=15)
