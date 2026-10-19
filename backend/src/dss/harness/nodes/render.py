"""Deterministic render node: aggregates, prototype, background, then stage/events."""
import asyncio
from dss.db import now
from dss.harness.guardrails import RunError
from dss.render import background
from dss.render.prototype import aggregate_data, render
from dss.spec.models import DashboardSpec


def artifacts(spec, service, folder):
    data = aggregate_data(spec, service, folder)
    html = render(spec, data=data, folder=folder)
    decoration = render(spec, layer='decoration', folder=folder)
    temporary = folder / 'background_p1.tmp.png'
    background.capture(decoration, temporary, spec.canvas.width, spec.pages[0].height)
    temporary.replace(folder / 'background_p1.png')
    temporary_html = folder / 'prototype.html.tmp'
    temporary_html.write_text(html, encoding='utf-8')
    temporary_html.replace(folder / 'prototype.html')


async def perform(harness, build_id, run_id, payload, trace):
    trace.span('render')
    config = payload['config']
    with harness.db.connect() as conn:
        version = conn.execute('SELECT current_version FROM builds WHERE id=?', (build_id,)).fetchone()[0]
    folder = config.data_dir / 'builds' / build_id / f'v{version}'
    candidate = payload.get('_publication')
    if candidate:
        folder = candidate.folder
    spec = DashboardSpec.model_validate_json((folder / 'spec.json').read_text(encoding='utf-8'))
    try:
        worker = asyncio.create_task(asyncio.to_thread(artifacts, spec, payload['factory'](config), folder))
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            # Keep the build reserved until the worker has stopped writing artifacts.
            try:
                await asyncio.shield(worker)
            except Exception:
                pass
            raise
    except Exception:
        # Provider/Playwright diagnostics must not cross ADK's logging boundary.
        raise RunError('invalid_source', 'Prototype rendering failed; check data access and image assets', 422) from None
    if candidate:
        from dss.spec.publication import build_lock
        try:
            async with build_lock(harness.db, build_id):
                candidate.publish(spec)
        except Exception:
            raise RunError('invalid_source', 'Plan publication failed; try again', 422) from None
        from dss.api.builds import build_response
        await harness.emit(build_id, run_id, 'docs.updated', {'docs': build_response(harness.db, config, build_id)['docs']})
    else:
        with harness.db.connect() as conn:
            conn.execute("UPDATE builds SET stage='prototype',updated_at=? WHERE id=?", (now(), build_id))
    await harness.emit(build_id, run_id, 'prototype.updated', {'spec_version': spec.spec_version})
    await harness.emit(build_id, run_id, 'stage.changed', {'stage': 'prototype'})
    return 'Prototype is ready.'
