"""Synthetic sample data: explicit generation, durable job status and CSV download
(contracts/synthetic-data.md 1.1, HTTP workflow and provenance; api.md 1.4)."""
import asyncio
import hashlib
import json

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dss.api.builds import require_build
from dss.data import synthetic
from dss.db import new_id, now
from dss.harness.guardrails import RunError
from dss.harness.nodes import synthetic_generate as node
from dss.harness.nodes import synthetic_schema
from dss.spec import references

router = APIRouter(prefix="/api/builds")
STAGES = ("connect", "interview")
JOB_LIMIT = 20
# A request without a proposal is a manual schema; the assumption keeps every row labeled invented.
MANUAL_ASSUMPTIONS = ["Manual schema entered by the user; every row is invented sample data."]


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    generation_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    proposal_id: str | None
    spec: dict


class ProposalRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    reference_set_id: str = Field(min_length=1, max_length=100)


def write_stage(state, build_id):
    """Check and reserve without yielding after the bounded request body was read."""
    with state.db.connect() as connection:
        build = connection.execute('SELECT stage FROM builds WHERE id=?', (build_id,)).fetchone()
        has_sources = connection.execute('SELECT 1 FROM sources WHERE build_id=?', (build_id,)).fetchone()
    if build['stage'] not in STAGES or build_id in state.harness.active_builds:
        raise RunError('wrong_stage', 'Sample data actions require connect or interview with no running action',
                       409, {'stage': build['stage']})
    if has_sources:
        raise RunError('synthetic_requires_empty_build', 'Sample data is only for a build without data sources; '
                       'start a new dashboard instead', 409)


def version_folder(state, build_id):
    from dss.api.prototype import current
    return current(state, build_id)[1]


@router.get('/{build_id}/synthetic-data/proposal')
def get_proposal(build_id: str, request: Request):
    proposal = synthetic_schema.load(version_folder(request.app.state, build_id))
    return proposal.model_dump(mode='json') if proposal else None


@router.post('/{build_id}/synthetic-data/proposal', status_code=202)
async def propose(build_id: str, request: Request):
    state = request.app.state
    require_build(state.db, build_id)
    try:
        body = ProposalRequest.model_validate(await read_json(request))
    except ValidationError:
        raise invalid_request() from None
    write_stage(state, build_id)
    folder = version_folder(state, build_id)
    reference = references.load(folder)
    if not reference or reference['mode'] != 'recreate':
        raise RunError('synthetic_schema_unavailable', 'Choose Recreate mode with a reference image, '
                       'or enter a manual sample-data schema', 422)
    if reference['id'] != body.reference_set_id:
        raise synthetic_schema.stale()
    run_id = new_id('r')
    config = state.settings.get()
    state.harness.active_builds.add(build_id)

    async def background():
        try:
            await state.harness.run('synthetic_schema', build_id,
                {'config': config, 'folder': folder, 'reference': reference}, run_id=run_id, reserved=True)
        except RunError:
            pass
        finally:
            state.harness.active_builds.discard(build_id)
    task = asyncio.create_task(background())
    state.engine_tasks.add(task)
    task.add_done_callback(state.engine_tasks.discard)
    return {'run_id': run_id}


def invalid_request():
    return RunError("invalid_request", "Invalid request", 422, {})


async def read_json(request):
    """The whole body is bounded at 64 KiB while streaming, never buffered beyond it."""
    too_large = RunError("request_too_large", "Request exceeds 64 KiB", 413, {})
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > synthetic.MAX_REQUEST_BYTES:
        raise too_large
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > synthetic.MAX_REQUEST_BYTES:
            raise too_large

    def unique(pairs):
        if len({key for key, _ in pairs}) != len(pairs):
            raise invalid_request()
        return dict(pairs)

    def constant(_):  # NaN and Infinity are not JSON
        raise invalid_request()
    try:
        return json.loads(bytes(body).decode("utf-8"), object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, RecursionError):
        raise invalid_request() from None


def request_hash(proposal_id, spec):
    canonical = json.dumps({"proposal_id": proposal_id}, sort_keys=True) + "\n" + synthetic.canonical_json(spec)
    return hashlib.sha256(canonical.encode("utf-8", "surrogatepass")).hexdigest()


def job(connection, build_id, key):
    return connection.execute("SELECT * FROM synthetic_generations WHERE build_id=? AND generation_key=?",
                              (build_id, key)).fetchone()


def status(row):
    succeeded = row["state"] == "succeeded"
    return {"generation_key": row["generation_key"], "run_id": row["run_id"], "state": row["state"],
            "source_id": row["source_id"] if succeeded else None,
            "retry_ready": row["state"] == "failed" and bool(row["retry_ready"]),
            "error": json.loads(row["error_json"]) if row["state"] == "failed" and row["error_json"] else None}


@router.post("/{build_id}/synthetic-data", status_code=202)
async def generate(build_id: str, request: Request):
    state = request.app.state
    require_build(state.db, build_id)
    try:
        body = GenerateRequest.model_validate(await read_json(request))
    except ValidationError:
        raise invalid_request() from None
    try:
        spec = synthetic.parse_spec(body.spec)
    except synthetic.SyntheticError as exc:
        raise RunError("invalid_generation_spec", "The generation spec is invalid", 422,
                       {"field": exc.field, "reason": exc.message}) from None
    digest = request_hash(body.proposal_id, spec)
    # Replay first: the same key and request always return the original run, even after success.
    # Everything from here to the reservation runs without an await, so it is atomic per build.
    with state.db.connect() as connection:
        existing = job(connection, build_id, body.generation_key)
    if existing is not None:
        if existing["request_hash"] == digest:
            return {"run_id": existing["run_id"]}
        raise RunError("synthetic_request_conflict", "This generation key was used for a different request", 409,
                       {"generation_key": body.generation_key})
    write_stage(state, build_id)
    assumptions = list(MANUAL_ASSUMPTIONS)
    if body.proposal_id is not None:
        proposal = synthetic_schema.load(version_folder(state, build_id))
        if proposal is None or proposal.id != body.proposal_id:
            raise synthetic_schema.stale()
        assumptions = list(proposal.assumptions)
        if synthetic.canonical_json(spec) != synthetic.canonical_json(proposal.spec):
            assumptions.append(synthetic_schema.EDITED_NOTE)
    config = state.settings.get()
    if not config.gcp_project_id.strip():
        raise RunError("gcp_not_configured", "Set the GCP project in Settings before generating data", 503)
    run_id, source_id, created = new_id("r"), new_id("s"), now()
    table = f"{config.gcp_project_id}.{config.bq_dataset}.src_{build_id}_synthetic_{source_id[2:]}"
    with state.db.connect() as connection:
        connection.execute(
            "INSERT INTO synthetic_generations(generation_key,build_id,request_hash,run_id,source_id,bq_table,state,"
            "retry_ready,created_at,spec_json,assumptions_json) VALUES(?,?,?,?,?,?,'queued',0,?,?,?)",
            # The accepted exact spec as sent (canonical form only identifies the request).
            (body.generation_key, build_id, digest, run_id, source_id, table, created,
             json.dumps(body.spec, ensure_ascii=False), json.dumps(assumptions)))
    state.harness.active_builds.add(build_id)
    payload = {"config": config, "factory": state.bigquery_factory, "spec": spec, "build_id": build_id,
               "generation_key": body.generation_key, "source_id": source_id, "bq_table": table,
               "assumptions": assumptions, "created_at": created}

    async def background():
        try:
            await state.harness.run("synthetic_generate", build_id,
                                    lambda rid: node.perform(state.harness, build_id, rid, payload),
                                    run_id=run_id, reserved=True)
        except Exception:
            pass
        finally:
            state.harness.active_builds.discard(build_id)
            # A run that never reached the node generated nothing: fail it as retryable.
            with state.db.connect() as connection:
                connection.execute(
                    "UPDATE synthetic_generations SET state='failed',retry_ready=1,error_json=? "
                    "WHERE build_id=? AND generation_key=? AND state='queued'",
                    (json.dumps({"code": "synthetic_generation_failed",
                                 "message": node.FAILURES["synthetic_generation_failed"] + " Retry is available."}),
                     build_id, body.generation_key))
    task = asyncio.create_task(background())
    state.engine_tasks.add(task)
    task.add_done_callback(state.engine_tasks.discard)
    return {"run_id": run_id}


@router.get("/{build_id}/synthetic-data")
def datasets(build_id: str, request: Request):
    db = request.app.state.db
    require_build(db, build_id)
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT g.* FROM synthetic_generations g JOIN sources s ON s.id=g.source_id AND s.build_id=g.build_id "
            "WHERE g.build_id=? AND g.state='succeeded' ORDER BY g.created_at, g.rowid", (build_id,)).fetchall()
    return [{"source_id": row["source_id"], "generation_key": row["generation_key"], "synthetic": True,
             "spec": json.loads(row["spec_json"]), "assumptions": json.loads(row["assumptions_json"]),
             "generator_version": row["generator_version"], "sha256": row["sha256"], "bytes": row["bytes"],
             "created_at": row["created_at"]} for row in rows]


@router.get("/{build_id}/synthetic-data/jobs")
def jobs(build_id: str, request: Request):
    db = request.app.state.db
    require_build(db, build_id)
    with db.connect() as connection:
        rows = connection.execute("SELECT * FROM synthetic_generations WHERE build_id=? "
                                  "ORDER BY created_at DESC, rowid DESC LIMIT ?", (build_id, JOB_LIMIT)).fetchall()
    return [status(row) for row in rows]


@router.get("/{build_id}/synthetic-data/jobs/{generation_key}")
def job_status(build_id: str, generation_key: str, request: Request):
    db = request.app.state.db
    require_build(db, build_id)
    with db.connect() as connection:
        row = job(connection, build_id, generation_key)
    if row is None:
        raise RunError("not_found", "Generation job not found", 404, {})
    return status(row)


@router.get("/{build_id}/synthetic-data/{source_id}/csv")
async def download(build_id: str, source_id: str, request: Request):
    """Only a registered, completed file of this build's own synthetic source, checksum-verified."""
    state = request.app.state
    require_build(state.db, build_id)
    with state.db.connect() as connection:
        row = connection.execute(
            "SELECT g.* FROM synthetic_generations g JOIN sources s ON s.id=g.source_id AND s.build_id=g.build_id "
            "WHERE g.build_id=? AND g.source_id=? AND g.state='succeeded' AND s.kind='synthetic'",
            (build_id, source_id)).fetchone()
    missing = RunError("not_found", "Sample data file not found", 404, {})
    if row is None:
        raise missing
    folder = node.prefix(state.settings.get().data_dir, build_id, row["generation_key"])
    path = folder / node.CSV
    try:
        if not (folder / node.METADATA).is_file() or await asyncio.to_thread(node.digest, path) != (row["bytes"], row["sha256"]):
            raise missing
    except OSError:
        raise missing from None
    return FileResponse(path, media_type="text/csv; charset=utf-8", filename="synthetic-sample.csv")
