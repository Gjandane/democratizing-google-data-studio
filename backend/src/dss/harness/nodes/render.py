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
    background.write_pages(spec, folder)
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
    from dss.api.prototype import read_spec
    spec = read_spec(folder, db=harness.db, build_id=build_id)
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
                from dss.spec import requirements as req
                from dss.spec.capabilities import Checker, load_registry
                snapshot, checker = req.inputs(harness.db, build_id, folder), Checker(load_registry())
                ledger = req.load(folder)
                if req.new_sources(snapshot, ledger):
                    raise RunError('feasibility_stale', 'Intent changed during planning; check feasibility again', 409)
                assessment = req.evaluate(snapshot, ledger, checker)
                if assessment.state == 'blocked':
                    raise req.blocked(assessment)
                bindings = {}
                errors = req.coverage_errors(snapshot, ledger, checker, bindings=bindings)
                if errors:
                    raise RunError('invalid_request', 'Candidate no longer fulfills the active requirements', 422, {'errors': errors})
                ledger = req.revalidate_decisions(snapshot, ledger, checker)
                ledger.verification = req.verification(snapshot, ledger, checker)
                for rid, ids in bindings.items():
                    ledger.verification[rid].append({'fulfilled_by': ids})
                req.save(folder, ledger, req.evaluate(snapshot, ledger, checker))
                if payload.get('transition'):
                    # Blueprint acceptance commits with its prototype: a failed publish
                    # restores the previous stage and artifact states (Candidate.restore).
                    from dss.artifacts import state as stages
                    stages.save(harness.db, build_id, {**payload['transition'], 'stage': 'prototype'})
                candidate.publish(spec)
        except RunError:
            raise
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


def _view_doc(folder, table, connected, sources, derived):
    """derived-fields.md names the published view, its derivations and participating tables."""
    from dss.harness.nodes.intake import write_doc
    from dss.harness.nodes.view import API_TYPES
    tables = {s['id']: s['bq_table'] for s in connected}
    write_doc(folder / 'docs/derived-fields.md', {'type': 'Derived Fields', 'title': 'Derived fields',
        'view': table, 'fields': [{'name': f.name, 'sql': f.expression, 'type': API_TYPES[f.type],
                                   'description': f.description} for f in derived],
        'joins': [{'table': tables[j.source_id]} for j in sources.joins],
        'union': [{'table': tables[sid]} for sid in sources.union]},
        '# Derived fields\n\n' + ''.join(f'- `{f.name}`: {f.description}\n' for f in derived))


async def accept(harness, build_id, run_id, payload, trace):
    """blueprint/accept: candidate view -> code layout -> every page rendered -> one publication."""
    from dss.artifacts import design as design_node
    from dss.artifacts.okf import write_artifact
    from dss.harness.nodes import context as context_node, outline as outline_node, view
    from dss.spec.auto_layout import LayoutError, layout
    from dss.spec.publication import Candidate, finish, worker
    from dss.spec.validate import allowed_types, catalog, synthetic_participation
    config, build, draft = payload['config'], payload['build'], payload['blueprint']
    with harness.db.connect() as conn:
        version = conn.execute('SELECT current_version FROM builds WHERE id=?', (build_id,)).fetchone()[0]
        recorded = conn.execute('SELECT spec_version FROM versions WHERE build_id=? AND n=?', (build_id, version)).fetchone()
    try:
        candidate = Candidate.begin(harness.db, config, build_id, version, run_id, payload)
        folder = candidate.folder
        trace.span('view')
        connected = context_node.sources(harness.db, build_id)
        context = context_node.load(folder)
        try:
            sql = view.blueprint_sql(connected, draft.view_sources, draft.derived_fields,
                                     context_fields=[f.name for f in context.derived_fields])
            fields = view.blueprint_fields(connected, draft.view_sources, draft.derived_fields)
            service = payload['factory'](config)
            await worker(service.dry_run, sql)
            table = candidate.creating()
            await worker(service.create_view, table, sql)
        except Exception:
            raise RunError('invalid_source', 'View could not be created; check BigQuery access', 422) from None
        trace.span('layout')
        _view_doc(folder, table, connected, draft.view_sources, draft.derived_fields)
        accepted = draft.model_copy(update={'view_table': table})
        await write_artifact(folder / 'docs/blueprint.md', accepted, emit=lambda *_: asyncio.sleep(0))
        existing = folder / 'spec.json'
        previous = DashboardSpec.model_validate_json(existing.read_text(encoding='utf-8')).spec_version if existing.is_file() else 0
        try:
            spec = layout(accepted, design_node.load(folder), outline_node.load(folder), fields,
                          build_id=build_id, archetype=build['archetype'],
                          spec_version=max(previous, (recorded['spec_version'] or 0) if recorded else 0) + 1,
                          synthetic=synthetic_participation(harness.db, build_id, folder),
                          allowed=allowed_types() & catalog().keys())
        except LayoutError as exc:
            raise RunError('invalid_request', 'The Blueprint could not be laid out', 422, {'errors': exc.errors[:20]}) from None
        existing.write_text(spec.model_dump_json(indent=2), encoding='utf-8')
        reply = await perform(harness, build_id, run_id, payload, trace)
    except RunError:
        raise
    except Exception:
        raise RunError('invalid_source', 'Prototype could not be prepared; previous prototype retained', 422) from None
    finally:
        if candidate := payload.get('_publication'):
            await finish(candidate, payload['factory'])
    from dss.api.builds import build_response
    await harness.emit(build_id, run_id, 'build.updated', {'build': build_response(harness.db, config, build_id)})
    return reply
