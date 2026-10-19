import re
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


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    prompt: str = Field(min_length=1, max_length=4000)


@router.post('/{build_id}/research', status_code=202)
async def research(build_id: str, body: ResearchRequest, request: Request):
    import asyncio
    from dss.api.prototype import current
    from dss.harness.guardrails import check_reply
    state = request.app.state
    build, _ = current(state, build_id)
    if (build['mode'] != 'research' or build['stage'] not in ('connect', 'interview') or
            build_id in state.harness.active_builds):
        raise RunError('wrong_stage', 'Research requires an idle research build in connect or interview', 409,
                       {'stage': build['stage']})
    if not body.prompt.strip():
        raise bq.invalid('A research prompt is required')
    config = state.settings.get()
    if not config.gcp_project_id.strip():
        raise RunError('gcp_not_configured', 'Set the GCP project in Settings before researching data', 503)
    if not config.google_api_key.get_secret_value():
        raise RunError('llm_unavailable', 'Set the Google API key in Settings', 503)
    check_reply(body.prompt, tuple(getattr(config, name).get_secret_value()
                                  for name in ('google_api_key', 'access_code', 'agent_token')))
    run_id = new_id('r')
    state.harness.active_builds.add(build_id)

    async def background():
        try:
            await state.harness.run('research', build_id, {'config': config, 'prompt': body.prompt,
                'factory': state.bigquery_factory}, run_id=run_id, reserved=True)
        except RunError:
            pass
    task = asyncio.create_task(background())
    state.engine_tasks.add(task)
    task.add_done_callback(state.engine_tasks.discard)
    return {'run_id': run_id}


# Reference images (contracts/dashboard-intent.md, Reference set). Multipart framing and the two
# text fields fit well inside this allowance on top of the 15 MiB of image bytes.
FORM_OVERHEAD = 64 * 1024
FIELD_BYTES = 4 * 2000 + 64
REFERENCE_STAGES = ("connect", "interview", "prototype")


def reference_stage(state, build_id):
    from dss.api.prototype import current
    build, folder = current(state, build_id)
    if build["stage"] not in REFERENCE_STAGES or build_id in state.harness.active_builds:
        raise RunError("wrong_stage", "References change only in connect, interview or prototype with no running action",
                       409, {"stage": build["stage"]})
    return build, folder


async def reference_form(request, fields_allowed):
    """Stream the multipart body, enforcing byte limits while reading (never buffering more)."""
    from dss.spec import references
    from python_multipart.multipart import MultipartParser, parse_options_header
    from python_multipart.exceptions import MultipartParseError
    kind, options = parse_options_header(request.headers.get("content-type"))
    if kind != b"multipart/form-data" or not options.get(b"boundary"):
        raise references.invalid("Send multipart/form-data with the field files")
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > references.MAX_TOTAL_BYTES + FORM_OVERHEAD:
        raise references.invalid("Upload exceeds 15 MB in total", 413)
    files, fields, part, header = [], {}, {}, {"field": b"", "value": b""}
    totals = {"files": 0}

    def on_part_begin():
        part.clear()
        part.update(headers={}, data=bytearray())

    def on_header_field(data, start, end):
        header["field"] += data[start:end]

    def on_header_value(data, start, end):
        header["value"] += data[start:end]

    def on_header_end():
        part["headers"][header["field"].lower()] = header["value"]
        header.update(field=b"", value=b"")

    def on_headers_finished():
        _, disposition = parse_options_header(part["headers"].get(b"content-disposition"))
        part["name"] = disposition.get(b"name", b"").decode("utf-8", "replace")
        filename = disposition.get(b"filename")
        part["filename"] = None if filename is None else filename.decode("utf-8", "replace")
        if part["filename"] is not None:
            if part["name"] != "files":
                raise references.invalid("Images go in the field files")
            if len(files) >= max(high for _, high in references.IMAGE_COUNTS.values()):
                raise references.invalid("Upload one to three images")
        elif part["name"] not in fields_allowed:
            raise references.invalid(f"Unexpected form field {part['name'][:40]!r}")

    def on_part_data(data, start, end):
        size = len(part["data"]) + end - start
        if part["filename"] is not None:
            if size > references.MAX_FILE_BYTES:
                raise references.invalid("Image exceeds 5 MB", 413)
            totals["files"] += end - start
            if totals["files"] > references.MAX_TOTAL_BYTES:
                raise references.invalid("Upload exceeds 15 MB in total", 413)
        elif size > FIELD_BYTES:
            raise references.invalid("Form field is too long")
        part["data"] += data[start:end]

    def on_part_end():
        if part["filename"] is None:
            try:
                fields[part["name"]] = part["data"].decode("utf-8")
            except UnicodeDecodeError:
                raise references.invalid("Form fields must be UTF-8 text") from None
        else:
            files.append({"filename": part["filename"], "content_type": part["headers"].get(b"content-type", b"").decode("latin-1"),
                          "content": bytes(part["data"])})

    parser = MultipartParser(options[b"boundary"], {
        "on_part_begin": on_part_begin, "on_header_field": on_header_field, "on_header_value": on_header_value,
        "on_header_end": on_header_end, "on_headers_finished": on_headers_finished, "on_part_data": on_part_data,
        "on_part_end": on_part_end})
    received = 0
    try:
        async for chunk in request.stream():
            received += len(chunk)
            if received > references.MAX_TOTAL_BYTES + FORM_OVERHEAD:
                raise references.invalid("Upload exceeds 15 MB in total", 413)
            parser.write(chunk)
        parser.finalize()
    except MultipartParseError:
        raise references.invalid("Malformed multipart upload") from None
    return files, fields


async def upload_references(build_id, request, legacy):
    """Validate everything before any model work, then extract in the background (202)."""
    import asyncio
    from dss.spec import references
    state = request.app.state
    reference_stage(state, build_id)
    files, fields = await reference_form(request, () if legacy else ("mode", "instructions"))
    mode = "style" if legacy else fields.get("mode", "")
    instructions = fields.get("instructions", "")
    if mode not in references.IMAGE_COUNTS:
        raise references.invalid("mode must be style or recreate")
    low, high = references.IMAGE_COUNTS[mode]
    if not low <= len(files) <= high:
        raise references.invalid("Style needs one to three images; recreate needs exactly one")
    if len(instructions) > references.MAX_INSTRUCTIONS:
        raise references.invalid("Instructions exceed 2000 characters")
    config = state.settings.get()
    if any(secret and secret in instructions for secret in (
            getattr(config, name).get_secret_value() for name in ("google_api_key", "access_code", "agent_token"))):
        raise references.invalid("Instructions must not contain credentials")
    images = []
    for file in files:
        name = file["filename"].replace("\\", "/").rsplit("/", 1)[-1]
        checked = references.inspect_image(name, file["content_type"], file["content"])
        image_id = new_id("img")
        # Display names only (never paths): plain characters, no YAML quoting or '---' in style.md.
        display = re.sub(r"-{2,}", "-", re.sub(r"[^A-Za-z0-9._-]+", "_", name)).strip("-")[:120] or "image"
        images.append({"id": image_id, "name": display, "file": f"reference_{image_id}.{checked['ext']}",
                       "content": file["content"], **{k: checked[k] for k in ("mime_type", "width", "height")}})
    try:
        await asyncio.to_thread(references.decode, images)
    except RunError:
        raise
    except Exception:
        # A Chromium launch or crash is a server fault, reported in the error shape without a traceback.
        raise RunError("invalid_source", "Images could not be checked; try again", 503,
                       {"reason": "Image decoder failed"}) from None
    # Re-check after the decode await; checking and reserving happen without a yield in between.
    reference_stage(state, build_id)
    run_id = new_id("r")
    state.harness.active_builds.add(build_id)

    async def background():
        try:
            await state.harness.run("reference_extract", build_id, {"config": config, "mode": mode,
                "instructions": instructions, "images": images, "reference_id": new_id("ref")}, run_id=run_id, reserved=True)
        except RunError:
            pass
    task = asyncio.create_task(background())
    state.engine_tasks.add(task)
    task.add_done_callback(state.engine_tasks.discard)
    return {"run_id": run_id}


@router.get("/{build_id}/reference-images")
def get_references(build_id: str, request: Request):
    from dss.api.prototype import current
    from dss.spec import references
    _, folder = current(request.app.state, build_id)
    record = references.load(folder)
    return None if record is None else references.public(record)


@router.post("/{build_id}/reference-images", status_code=202)
async def post_references(build_id: str, request: Request):
    return await upload_references(build_id, request, legacy=False)


@router.post("/{build_id}/style-images", status_code=202)
async def style_images(build_id: str, request: Request):
    """Legacy alias: a style-mode reference replacement with the same validation and lifecycle."""
    return await upload_references(build_id, request, legacy=True)


@router.delete("/{build_id}/reference-images", status_code=204)
async def delete_references(build_id: str, request: Request):
    import asyncio
    from fastapi import Response
    from dss.spec import references
    state = request.app.state
    _, folder = reference_stage(state, build_id)

    async def perform(run_id):
        if not await asyncio.to_thread(references.remove, folder):
            return "No reference set to remove."
        await state.harness.emit(build_id, run_id, "docs.updated",
                                 {"docs": build_response(state.db, state.settings.get(), build_id)["docs"]})
        return "Reference set removed."
    await state.harness.run("reference_delete", build_id, perform)
    return Response(status_code=204)


