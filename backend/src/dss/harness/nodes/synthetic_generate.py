"""Code node: generate a synthetic CSV, store it, load it to BigQuery with its declared types and
register it as the build's synthetic source (contracts/synthetic-data.md, HTTP workflow, Storage).

The generation table row is the only job record: queued -> generating -> loading -> succeeded,
or failed after this job's own prefix and BigQuery table were cleaned (then retry_ready).
"""
import asyncio
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from dss.data.synthetic import SyntheticError, generate_csv
from dss.harness.guardrails import RunError
from dss.harness.nodes.intake import register, write_doc

NAME = "Synthetic sample data"
CSV, METADATA, DOC = "sample.csv", "metadata.json", "synthetic-data.md"
FAILURES = {"synthetic_generation_failed": "Sample data could not be generated.",
            "synthetic_load_failed": "Sample data could not be loaded.",
            "generation_interrupted": "Sample data generation was interrupted by a restart."}


class Failure(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def prefix(data_dir, build_id, key):
    """Server-derived storage prefix of one generation; build and key are validated IDs."""
    return Path(data_dir) / "generated" / build_id / key


def set_state(db, build_id, key, state, **fields):
    columns = ", ".join(f"{name}=?" for name in ("state", *fields))
    with db.connect() as conn:
        conn.execute(f"UPDATE synthetic_generations SET {columns} WHERE build_id=? AND generation_key=?",
                     (state, *fields.values(), build_id, key))


def digest(path):
    hasher, size = hashlib.sha256(), 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
            size += len(chunk)
    return size, hasher.hexdigest()


def copy_file(source, destination):
    shutil.copyfile(source, destination)


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def store(config, build_id, key, spec, metadata):
    """Write sample.csv, then metadata.json last as the completion record."""
    folder = prefix(config.data_dir, build_id, key)
    # Only this generation's own prefix: left over when a lost reservation reused its key.
    if folder.exists():
        shutil.rmtree(folder)
    if config.cloud_service:
        # Hosted: DSS_DATA_DIR is the GCS volume. Generate and size-check on local disk, then
        # copy; a cross-file rename there is not atomic, so nothing relies on one.
        with tempfile.TemporaryDirectory(prefix="dss-synthetic-") as local:
            result = generate_csv(spec, Path(local) / CSV)
            folder.mkdir(parents=True, exist_ok=True)
            copy_file(Path(local) / CSV, folder / CSV)
        if digest(folder / CSV) != (result.bytes, result.sha256):
            raise Failure("The stored CSV does not match its checksum")
    else:
        result = generate_csv(spec, folder / CSV)
    write_json(folder / METADATA, {**metadata, **result.model_dump()})
    return result


def load(service, table, path, spec):
    """Typed load, then the exact requested row count from both BigQuery and the profile."""
    rows = service.load_typed_csv(table, path, [(column.name, column.type) for column in spec.columns])
    if rows != spec.row_count:
        raise Failure(f"BigQuery loaded {rows} of {spec.row_count} rows")
    profile = service.profile(table)
    if profile["row_count"] != spec.row_count:
        raise Failure(f"BigQuery reports {profile['row_count']} of {spec.row_count} rows")
    return profile


def document(spec, job, result):
    columns = [{"name": c.name, "type": c.type, "nullable_fraction": c.nullable_fraction,
                "generator": c.generator.model_dump(mode="json")} for c in spec.columns]
    metadata = {"type": "Synthetic Dataset", "title": NAME, "synthetic": True,
                "source_id": job["source_id"], "generation_key": job["generation_key"],
                "seed": spec.seed, "row_count": spec.row_count, "sha256": result.sha256, "bytes": result.bytes,
                "generator_version": result.generator_version, "schema": columns, "assumptions": job["assumptions"]}
    body = ["# " + NAME, "",
            "Every row was invented by the deterministic generator from the schema below. No value was "
            "recovered from a screenshot, reference or original dataset.", "",
            f"- Seed: {spec.seed}", f"- Rows: {spec.row_count}", f"- SHA-256: `{result.sha256}` ({result.bytes} bytes)",
            f"- Generator: {result.generator_version}", "", "## Schema", ""]
    body += [f"- `{c['name']}` ({c['type']}): {c['generator']['kind']}, nullable fraction {c['nullable_fraction']}"
             for c in columns]
    body += ["", "## Assumptions", ""] + [f"- {text}" for text in job["assumptions"]]
    return metadata, "\n".join(body) + "\n"


def register_source(db, config, build_id, job, spec, result, profile):
    """Source, profile, provenance docs and state=succeeded commit together; docs roll back on failure."""
    with db.connect() as conn:
        version = conn.execute("SELECT current_version FROM builds WHERE id=?", (build_id,)).fetchone()[0]
    docs = config.data_dir / "builds" / build_id / f"v{version}" / "docs"
    names = ("data-profile.md", "index.md", "log.md", DOC)
    before = {name: (docs / name).read_bytes() if (docs / name).is_file() else None for name in names}
    try:
        with db.connect() as conn:
            # Never mix with or replace a real dataset, even if one arrived since the request.
            if conn.execute("SELECT 1 FROM sources WHERE build_id=?", (build_id,)).fetchone():
                raise Failure("The build already has a data source")
            source = {"id": job["source_id"], "kind": "synthetic", "name": NAME, "bq_table": job["bq_table"], **profile}
            register(conn, config, build_id, version, [source])
            write_doc(docs / DOC, *document(spec, job, result))
            index = (docs / "index.md").read_text(encoding="utf-8")
            if f"]({DOC})" not in index:
                (docs / "index.md").write_text(index.rstrip("\n") + f"\n- [{NAME}]({DOC})\n", encoding="utf-8")
            conn.execute("UPDATE synthetic_generations SET state='succeeded',retry_ready=0,error_json=NULL,"
                         "generator_version=?,sha256=?,bytes=? WHERE build_id=? AND generation_key=?",
                         (result.generator_version, result.sha256, result.bytes, build_id, job["generation_key"]))
    except BaseException:
        for name, content in before.items():
            if content is None:
                (docs / name).unlink(missing_ok=True)
            else:
                (docs / name).write_bytes(content)
        raise


def cleanup(config, job, service, *, fence_missing=False):
    """Remove only this job's generated prefix and BigQuery table; True when both are gone.

    service is None when no BigQuery client was ever created, so no load can exist.
    Startup fences absent jobs against a delayed remote submission. During a run,
    an unobserved submission must retain ownership.
    """
    cleaned = True
    try:
        folder = prefix(config.data_dir, job["build_id"], job["generation_key"])
        if folder.exists():
            shutil.rmtree(folder)
    except OSError:
        cleaned = False
    if service is not None:
        try:
            complete = (service.delete_loaded_table(job["bq_table"], fence_missing=True) if fence_missing
                        else service.delete_loaded_table(job["bq_table"]))
            if complete is False:
                # An unobserved load can still create a table later. Retain ownership.
                cleaned = False
        except Exception:
            cleaned = False
    return cleaned


async def recover(db, config, factory):
    """Before serving: fail orphaned workers and retry unfinished, job-owned cleanup.

    The reserved row may predate a load or even its registration commit, so every
    interrupted job must reconcile its table regardless of the restored state.
    """
    with db.connect() as conn:
        succeeded = [dict(row) for row in conn.execute(
            "SELECT * FROM synthetic_generations WHERE state='succeeded'")]
        conn.execute("UPDATE synthetic_generations SET state='failed',retry_ready=0,error_json=? "
                     "WHERE state IN ('queued','generating','loading')",
                     (json.dumps({"code": "generation_interrupted",
                                  "message": FAILURES["generation_interrupted"] +
                                  " Retry becomes available after cleanup."}),))
        pending = [dict(row) for row in conn.execute(
            "SELECT * FROM synthetic_generations WHERE state='failed' AND retry_ready=0")]
    # Volume files can outlive a container. Never serve a restored successful
    # source whose completed CSV has disappeared or changed on that volume.
    for job in succeeded:
        folder = prefix(config.data_dir, job['build_id'], job['generation_key'])
        try:
            valid = ((folder / METADATA).is_file() and
                     await asyncio.to_thread(digest, folder / CSV) == (job['bytes'], job['sha256']))
        except OSError:
            valid = False
        if not valid:
            raise RuntimeError('Stored synthetic sample data failed recovery validation')
    if not pending:
        return
    await db.immediate_backup()
    for job in pending:
        try:
            # Settings may have changed since reservation; job identity must not.
            job_config = config.model_copy(update={'gcp_project_id': job['bq_table'].split('.')[0],
                                                   'bq_location': job['bq_location'] or config.bq_location})
            service = await asyncio.to_thread(factory, job_config)
        except Exception:
            # Still clean the owned files, but a missing client cannot prove BQ cleanup.
            await asyncio.to_thread(cleanup, config, job, None)
            continue
        cleaned = await asyncio.to_thread(cleanup, config, job, service, fence_missing=True)
        error = json.loads(job['error_json'])
        error['message'] = FAILURES[error['code']] + (
            " Retry is available." if cleaned else " Retry becomes available after cleanup.")
        set_state(db, job['build_id'], job['generation_key'], 'failed',
                  retry_ready=int(cleaned), error_json=json.dumps(error))
    await db.immediate_backup()


async def perform(harness, build_id, run_id, job):
    db, config, spec, key = harness.db, job["config"], job["spec"], job["generation_key"]
    code, service = "synthetic_generation_failed", None
    metadata = {"generation_key": key, "build_id": build_id, "source_id": job["source_id"],
                "bq_table": job["bq_table"], "synthetic": True, "spec": spec.model_dump(mode="json"),
                "assumptions": job["assumptions"], "created_at": job["created_at"]}
    try:
        set_state(db, build_id, key, "generating")
        result = await asyncio.to_thread(store, config, build_id, key, spec, metadata)
        code = "synthetic_load_failed"
        set_state(db, build_id, key, "loading")
        service = job["factory"](config)
        profile = await asyncio.to_thread(load, service, job["bq_table"], prefix(config.data_dir, build_id, key) / CSV, spec)
        await asyncio.to_thread(register_source, db, config, build_id, job, spec, result, profile)
    except Exception as exc:
        # Our own reasons only: provider exceptions may carry paths, URLs or credentials.
        reason = (exc.reason if isinstance(exc, Failure) else
                  exc.message if isinstance(exc, SyntheticError) and exc.field != "output" else None)
        cleaned = await asyncio.to_thread(cleanup, config, job, service)
        error = {"code": code, "message": FAILURES[code] + (" Retry is available." if cleaned else
                                                            " Retry becomes available after cleanup.")}
        set_state(db, build_id, key, "failed", retry_ready=int(cleaned), error_json=json.dumps(error))
        await db.immediate_backup()
        raise RunError(code, error["message"], 500, {"reason": reason} if reason else {}) from None
    # Registration is already committed: backup failure must never roll it back or clean it.
    # Defer cancellation until this boundary settles, or the harness can emit
    # run.finished while the registered Source is still absent from the backup.
    await db.immediate_backup()
    from dss.api.builds import build_response
    built = build_response(db, config, build_id)
    await harness.emit(build_id, run_id, "build.updated", {"build": built})
    await harness.emit(build_id, run_id, "docs.updated", {"docs": built["docs"]})
    return f"{NAME}: {spec.row_count} rows generated and loaded."
