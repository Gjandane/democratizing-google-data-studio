"""Persist the engine outcome and publish the stable API events."""
from dss.db import now


async def publish(state, build_id, run_id, version, result):
    stage = "done" if result["status"] in ("ok", "partial") else "prototype"
    with state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage=?,updated_at=? WHERE id=?", (stage, now(), build_id))
        conn.execute("UPDATE versions SET status=?,report_url=? WHERE build_id=? AND n=?",
                     ("published" if stage == "done" else "failed", result["report_url"], build_id, version))
    await state.harness.emit(build_id, run_id, "stage.changed", {"stage": stage})
    from dss.api.builds import build_response
    await state.harness.emit(build_id, run_id, "build.updated", {
        "build": build_response(state.db, state.settings.get(), build_id)})
    await state.harness.emit(build_id, run_id, "build.finished", {**result, "version": version})
