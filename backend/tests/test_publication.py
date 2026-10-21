"""Publication's oracle is the complete old/new bundle and the live view catalog."""
import asyncio
import json
from pathlib import Path
import threading

import pytest
import yaml

from dss.db import Database, new_id, now
from dss.harness.guardrails import RunError
from dss.harness.nodes.intake import write_doc
from dss.spec.models import DashboardSpec
from dss.spec.publication import Candidate, build_lock, finish, recover, worker


def seed(app, build_id):
    app.state.settings.update({'gcp_project_id': 'project'})
    source = {'bq_table': 'project.data.sales', 'columns': [
        {'name': 'date', 'type': 'date', 'bq_type': 'DATE', 'sample': []},
        {'name': 'region', 'type': 'string', 'bq_type': 'STRING', 'sample': []},
        {'name': 'revenue', 'type': 'number', 'bq_type': 'FLOAT', 'sample': []}]}
    with app.state.db.connect() as conn:
        conn.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?)',
                     (new_id('s'), build_id, 'bigquery', 'sales', source['bq_table'], 2, json.dumps(source['columns'])))
    docs = app.state.settings.get().data_dir / 'builds' / build_id / 'v1/docs'
    docs.mkdir(parents=True)
    write_doc(docs / 'data-profile.md', {'type': 'BigQuery Table', 'sources': [source]}, '# Profile')
    return docs


class Views:
    def __init__(self, db):
        self.db = db
        self.live = {'project.data.legacy_view': 'SELECT old_report_data'}
        self.deleted = []
        self.fail = None

    def dry_run(self, sql):
        pass

    def create_view(self, table, sql):
        with self.db.connect() as conn:
            owned = conn.execute('SELECT * FROM plan_publications WHERE table_name=?', (table,)).fetchone()
        assert owned and owned['creating'] and not owned['committed']
        assert table not in self.live  # CREATE, never replace a published report view.
        if self.fail == 'before_create':
            raise RuntimeError('before create')
        self.live[table] = sql
        if self.fail == 'after_create':
            raise RuntimeError('ambiguous create result')

    def delete_view(self, table):
        self.deleted.append(table)
        if self.fail == 'delete':
            raise RuntimeError('temporary delete failure')
        self.live.pop(table, None)

    def aggregate(self, sql):
        assert any(f'`{table}`' in sql for table in self.live)
        return [{'m0': 321}]


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob('*') if p.is_file()}


def baseline(app, build_id):
    folder = seed(app, build_id).parent
    spec = json.loads(Path('tests/data/thin_spec.json').read_text())
    spec.update(build_id=build_id, spec_version=4)
    spec['datasource']['table'] = 'project.data.legacy_view'
    (folder / 'spec.json').write_text(json.dumps(spec), encoding='utf-8')
    (folder / 'prototype.html').write_text('old prototype', encoding='utf-8')
    (folder / 'background_p1.png').write_bytes(b'old PNG')
    (folder / 'aggregate-cache.json').write_text('{}')
    write_doc(folder / 'docs/derived-fields.md', {'type': 'Derived Fields', 'view': spec['datasource']['table']}, 'Old fields')
    write_doc(folder / 'docs/questions.md', {'type': 'Business Questions'}, '- q1: Old question (priority: high)')
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='prototype' WHERE id=?", (build_id,))
        conn.execute("INSERT INTO versions(build_id,n,status,spec_version,report_url,created_at) VALUES(?,1,'done',4,?,?)",
                     (build_id, 'https://datastudio.google.com/reporting/old', now()))
    return folder, Views(app.state.db)


def metadata(db, build_id):
    with db.connect() as conn:
        return (dict(conn.execute('SELECT * FROM builds WHERE id=?', (build_id,)).fetchone()),
                dict(conn.execute('SELECT * FROM versions WHERE build_id=? AND n=1', (build_id,)).fetchone()))


@pytest.fixture(autouse=True)
def offline_capture(monkeypatch):
    monkeypatch.setattr('dss.render.background.capture', lambda html, path, w, h: path.write_bytes(b'new PNG'))


async def run_publication(app, build_id, service):
    """Exercise publication ownership and rendering without a model planner."""
    from dss.harness.nodes.render import perform
    from dss.harness.tracing import Trace

    harness = app.state.harness
    payload = {'config': app.state.settings.get(), 'factory': lambda c: service}

    async def publish(run_id):
        try:
            with harness.db.connect() as conn:
                version = conn.execute('SELECT current_version FROM builds WHERE id=?', (build_id,)).fetchone()[0]
            candidate = Candidate.begin(harness.db, payload['config'], build_id, version, run_id, payload)
            sql = 'SELECT date, region, revenue FROM `project.data.sales`'
            await worker(service.dry_run, sql)
            await worker(service.create_view, candidate.creating(), sql)
            document = json.loads((candidate.folder / 'spec.json').read_text(encoding='utf-8'))
            document['build_id'] = build_id
            document['spec_version'] += 1
            document['datasource']['table'] = candidate.record()['table_name']
            spec = DashboardSpec.model_validate(document)
            write_doc(candidate.folder / 'docs/derived-fields.md',
                      {'type': 'Derived Fields', 'view': spec.datasource.table}, 'New fields')
            (candidate.folder / 'spec.json').write_text(spec.model_dump_json(), encoding='utf-8')
            return await perform(harness, build_id, run_id, payload, Trace(harness.db, run_id, build_id, 'load_spec'))
        except RunError:
            raise
        except Exception:
            raise RunError('invalid_source', 'Publication failed', 422) from None
        finally:
            if candidate := payload.get('_publication'):
                await finish(candidate, payload['factory'])

    return await harness.run('load_spec', build_id, publish)


@pytest.mark.parametrize('point', ['before_create', 'after_create', 'docs', 'render',
                                  'after_render', 'during_publication', 'before_commit', 'after_commit'])
async def test_failed_attempt_preserves_complete_bundle(client, app, build_id, monkeypatch, point):
    folder, service = baseline(app, build_id)
    before, rows = snapshot(folder), metadata(app.state.db, build_id)
    service.fail = point
    if point == 'docs':
        monkeypatch.setattr(__name__ + '.write_doc', lambda *a: (_ for _ in ()).throw(OSError('docs')))
    if point == 'render':
        monkeypatch.setattr('dss.render.background.capture', lambda *a: (_ for _ in ()).throw(RuntimeError('render')))
    if point == 'after_render':
        monkeypatch.setattr(Candidate, 'publish', lambda *a: (_ for _ in ()).throw(OSError('after render')))
    if point == 'during_publication':
        original = Path.replace
        def replace(path, target):
            if path.name == 'spec.json.publish-tmp':
                raise OSError('partial publication')
            return original(path, target)
        monkeypatch.setattr(Path, 'replace', replace)
    if point in ('before_commit', 'after_commit'):
        original = Candidate.commit
        def commit(candidate, spec):
            if point == 'after_commit':
                original(candidate, spec)
            raise OSError(point)
        monkeypatch.setattr(Candidate, 'commit', commit)
    with pytest.raises(RunError):
        await run_publication(app, build_id, service)
    if point == 'after_commit':
        assert_published(app, build_id, folder, service)
        assert not service.deleted
    else:
        assert snapshot(folder) == before
        assert metadata(app.state.db, build_id) == rows
        assert service.live == {'project.data.legacy_view': 'SELECT old_report_data'}
        assert all(name != 'project.data.legacy_view' for name in service.deleted)
    assert build_id not in app.state.harness.active_builds


def assert_published(app, build_id, folder, service):
    spec = DashboardSpec.model_validate_json((folder / 'spec.json').read_text())
    docs = yaml.safe_load((folder / 'docs/derived-fields.md').read_text().split('---', 2)[1])
    assert spec.datasource.table == docs['view']
    assert spec.datasource.table in service.live
    assert spec.datasource.table != 'project.data.legacy_view'
    assert spec.spec_version == 5
    assert (folder / 'background_p1.png').read_bytes() == b'new PNG'
    assert '321' in (folder / 'prototype.html').read_text(encoding='utf-8')
    from dss.render.prototype import aggregate_sql
    from hashlib import sha256
    cache = json.loads((folder / 'aggregate-cache.json').read_text())
    for component in spec.pages[0].components:
        sql = aggregate_sql(spec, component)
        if sql:
            assert spec.datasource.table in sql
            assert sha256(sql.encode()).hexdigest() in cache
    build, version = metadata(app.state.db, build_id)
    assert build['stage'] == 'prototype' and version['spec_version'] == 5
    assert service.live['project.data.legacy_view'] == 'SELECT old_report_data'
    return spec


async def test_success_legacy_identity_and_new_version_reuse(client, app, build_id):
    folder, service = baseline(app, build_id)
    # The old identity is accepted without migration before any replan.
    assert client.get(f'/api/builds/{build_id}/spec').json()['datasource']['table'] == 'project.data.legacy_view'
    await run_publication(app, build_id, service)
    spec = assert_published(app, build_id, folder, service)
    assert not service.deleted
    result = client.post(f'/api/builds/{build_id}/versions')
    assert result.status_code == 201
    assert client.get(f'/api/builds/{build_id}/spec').json()['datasource']['table'] == spec.datasource.table
    assert not list((folder.parent / 'v2').glob('.publications*'))
    await run_publication(app, build_id, service)
    assert len(service.live) == 3  # legacy, v1 and v2 all keep their own SQL.
    assert client.get(f'/api/builds/{build_id}/spec').json()['datasource']['table'] != spec.datasource.table
    assert not service.deleted


async def test_failed_replan_keeps_previously_published_run_view(client, app, build_id):
    folder, service = baseline(app, build_id)
    await run_publication(app, build_id, service)
    before, catalog = snapshot(folder), dict(service.live)
    service.fail = 'after_create'
    with pytest.raises(RunError):
        await run_publication(app, build_id, service)
    assert snapshot(folder) == before and service.live == catalog
    assert all(table not in catalog for table in service.deleted)


class Crash(BaseException):
    """Simulate process death: skip normal exception rollback and harness finally."""


def staged(app, build_id, service):
    config = app.state.settings.get()
    candidate = Candidate.begin(app.state.db, config, build_id, 1, new_id('r'))
    service.create_view(candidate.creating(), 'SELECT candidate_data')
    document = json.loads((candidate.folder / 'spec.json').read_text())
    document['spec_version'] += 1
    document['datasource']['table'] = candidate.record()['table_name']
    spec = DashboardSpec.model_validate(document)
    (candidate.folder / 'spec.json').write_text(spec.model_dump_json())
    write_doc(candidate.folder / 'docs/derived-fields.md', {'type': 'Derived Fields', 'view': spec.datasource.table}, 'New fields')
    (candidate.folder / 'prototype.html').write_text('new prototype')
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='blueprint' WHERE id=?", (build_id,))
    return candidate, spec


@pytest.mark.parametrize('point', ['before_create', 'after_create', 'partial_files', 'before_commit', 'after_commit'])
async def test_restart_recovers_idempotently(client, app, build_id, monkeypatch, point):
    folder, service = baseline(app, build_id)
    before, rows = snapshot(folder), metadata(app.state.db, build_id)
    if point == 'before_create':
        candidate = Candidate.begin(app.state.db, app.state.settings.get(), build_id, 1, new_id('r'))
    else:
        candidate, document = staged(app, build_id, service)
    with monkeypatch.context() as patch:
        if point == 'partial_files':
            original = Path.replace
            def replace(path, target):
                if path.name == 'spec.json.publish-tmp':
                    raise Crash()
                return original(path, target)
            patch.setattr(Path, 'replace', replace)
        if point in ('before_commit', 'after_commit'):
            original = Candidate.commit
            def commit(owner, spec):
                if point == 'after_commit':
                    original(owner, spec)
                raise Crash()
            patch.setattr(Candidate, 'commit', commit)
        if point in ('partial_files', 'before_commit', 'after_commit'):
            with pytest.raises(Crash):
                candidate.publish(document)
    # New database instance: no in-memory candidate/lock state survives restart.
    restarted = Database(app.state.db.path)
    restarted.initialize()
    await recover(restarted, app.state.settings.get(), lambda c: service)
    once, metadata_once, live_once = snapshot(folder), metadata(restarted, build_id), dict(service.live)
    await recover(restarted, app.state.settings.get(), lambda c: service)
    assert snapshot(folder) == once and metadata(restarted, build_id) == metadata_once and service.live == live_once
    if point == 'after_commit':
        assert (folder / 'spec.json').read_text() == document.model_dump_json()
        assert document.datasource.table in service.live and not service.deleted
    else:
        assert once == before and metadata_once == rows
        assert service.live == {'project.data.legacy_view': 'SELECT old_report_data'}
    assert not candidate.root.exists()


@pytest.mark.parametrize('old_stage', ['interview', 'plan'])
@pytest.mark.parametrize('committed', [False, True])
async def test_old_publication_journals_remain_compatible_after_migration(client, app, build_id, old_stage, committed):
    folder, service = baseline(app, build_id)
    candidate, document = staged(app, build_id, service)
    previous = json.loads(candidate.record()['previous_json'])
    previous['stage'] = previous['build']['stage'] = old_stage
    previous['build']['ready_for_plan'] = 1  # Column absent in a freshly created 2.0 DB.
    candidate.persist(previous_json=json.dumps(previous))
    if committed:
        candidate.publish(document)
        with app.state.db.connect() as conn:
            conn.execute('UPDATE versions SET spec_version=4 WHERE build_id=?', (build_id,))
        candidate.reconcile()
    else:
        candidate.restore()
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT stage FROM builds WHERE id=?', (build_id,)).fetchone()[0] == (
            'prototype' if committed else 'context')
    await candidate.cleanup(lambda c: service)


async def test_delete_retry_cannot_rollback_later_publication(client, app, build_id):
    folder, service = baseline(app, build_id)
    abandoned, _ = staged(app, build_id, service)
    service.fail = 'delete'
    with pytest.raises(RuntimeError):
        await abandoned.cleanup(lambda c: service)
    assert abandoned.record()['restored']
    service.fail = None
    await run_publication(app, build_id, service)
    before = snapshot(folder), metadata(app.state.db, build_id), dict(service.live)
    await recover(app.state.db, app.state.settings.get(), lambda c: service)
    assert snapshot(folder) == before[0] and metadata(app.state.db, build_id) == before[1]
    assert len(service.live) == len(before[2]) - 1
    assert 'project.data.legacy_view' in service.live


@pytest.mark.parametrize('artifact', ['context', 'outline', 'design', 'blueprint'])
async def test_delete_retry_cannot_rollback_later_artifact_edit(client, app, build_id, artifact):
    from dss.artifacts import state
    folder, service = baseline(app, build_id)
    abandoned, _ = staged(app, build_id, service)
    service.fail = 'delete'
    with pytest.raises(RuntimeError):
        await abandoned.cleanup(lambda c: service)
    assert abandoned.record()['restored']
    with app.state.db.connect() as conn:
        conn.execute('UPDATE builds SET artifacts_json=? WHERE id=?',
                     (json.dumps(dict.fromkeys(state.ARTIFACTS, 'confirmed')), build_id))
    with state.action(app.state, build_id) as current:
        state.save(app.state.db, build_id, state.edited(current, artifact))
    before = metadata(app.state.db, build_id), snapshot(folder)
    service.fail = None
    await recover(app.state.db, app.state.settings.get(), lambda c: service)
    assert metadata(app.state.db, build_id) == before[0] and snapshot(folder) == before[1]
    assert metadata(app.state.db, build_id)[0]['stage'] == artifact


async def test_restored_journal_cleanup_survives_backup_predating_build(client, app, build_id, tmp_path):
    folder, service = baseline(app, build_id)
    abandoned, _ = staged(app, build_id, service)
    service.fail = 'delete'
    with pytest.raises(RuntimeError):
        await abandoned.cleanup(lambda c: service)
    assert abandoned.record()['restored']
    before = snapshot(folder)
    restarted = Database(tmp_path / 'pre-build.sqlite')
    restarted.initialize()
    service.fail = None
    await recover(restarted, app.state.settings.get(), lambda c: service)
    assert snapshot(folder) == before and not abandoned.root.exists()
    assert service.live == {'project.data.legacy_view': 'SELECT old_report_data'}


@pytest.mark.parametrize('failure', [False, True])
async def test_http_readers_and_actions_wait_for_complete_publication(client, app, build_id, monkeypatch, failure):
    folder, service = baseline(app, build_id)
    candidate, spec = staged(app, build_id, service)
    entered, release = threading.Event(), threading.Event()
    original = Candidate.commit
    def commit(owner, document):
        entered.set()  # Files are new, DB still old. No reader may observe this.
        assert release.wait(5)
        if failure:
            raise OSError('commit failed')
        original(owner, document)
    monkeypatch.setattr(Candidate, 'commit', commit)
    app.state.harness.active_builds.add(build_id)
    async def publish():
        async with build_lock(app.state.db, build_id):
            candidate.publish(spec)
    errors = []
    def publication_thread():
        try:
            asyncio.run(publish())
        except OSError as exc:
            errors.append(exc)
    thread = threading.Thread(target=publication_thread)
    thread.start()
    assert await asyncio.to_thread(entered.wait, 5)
    readers = [asyncio.create_task(asyncio.to_thread(client.get, f'/api/builds/{build_id}/{path}'))
               for path in ('spec', 'prototype', 'docs/derived-fields.md', 'files/prototype.html')]
    await asyncio.sleep(.03)
    assert all(not task.done() for task in readers)
    assert client.post(f'/api/builds/{build_id}/plan').status_code == 404
    assert client.post(f'/api/builds/{build_id}/versions').status_code == 409
    release.set()
    await asyncio.to_thread(thread.join, 5)
    responses = await asyncio.gather(*readers)
    assert all(r.status_code == 200 for r in responses)
    table = 'project.data.legacy_view' if failure else spec.datasource.table
    assert responses[0].json()['datasource']['table'] == table
    assert table in responses[2].text and responses[3].text == ('old prototype' if failure else 'new prototype')
    assert len(errors) == int(failure)
    app.state.harness.active_builds.discard(build_id)


async def test_cancel_during_create_waits_then_cleans_only_candidate(client, app, build_id):
    folder, service = baseline(app, build_id)
    before = snapshot(folder)
    started, release = threading.Event(), threading.Event()
    original = service.create_view
    def create(table, sql):
        started.set()
        assert release.wait(5)
        original(table, sql)
    service.create_view = create
    task = asyncio.create_task(run_publication(app, build_id, service))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(.03)
    assert not task.done() and build_id in app.state.harness.active_builds
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert snapshot(folder) == before
    assert service.live == {'project.data.legacy_view': 'SELECT old_report_data'}
    assert len(service.deleted) == 1


def test_application_startup_recovers_before_serving(client, app, build_id, monkeypatch):
    from fastapi.testclient import TestClient
    from dss.main import create_app
    from fakes import fake_models
    folder, service = baseline(app, build_id)
    before = snapshot(folder)
    candidate, document = staged(app, build_id, service)
    with monkeypatch.context() as patch:
        patch.setattr(Candidate, 'commit', lambda *a: (_ for _ in ()).throw(Crash()))
        with pytest.raises(Crash):
            candidate.publish(document)
    restarted = create_app(app.state.settings.get(), model_lister=fake_models, bigquery_factory=lambda c: service)
    with TestClient(restarted) as api:
        assert api.get(f'/api/builds/{build_id}').json()['stage'] == 'prototype'
        assert api.get(f'/api/builds/{build_id}/spec').json()['datasource']['table'] == 'project.data.legacy_view'
        assert snapshot(folder) == before
        assert service.live == {'project.data.legacy_view': 'SELECT old_report_data'}


def test_create_view_ddl_is_non_destructive(tmp_path):
    from dss.config import Config
    from dss.data.bigquery import BigQuery
    from unittest.mock import Mock
    client = Mock()
    config = Config(data_dir=tmp_path, gcp_project_id='project')
    service = BigQuery(config, client=client)
    service.create_view('project.data.dash_b_v1_r_run', 'SELECT 1')
    assert client.query.call_args.args[0] == 'CREATE VIEW `project.data.dash_b_v1_r_run` AS\nSELECT 1'
    assert client.query.call_args.kwargs['job_id'] == service.view_job_id('project.data.dash_b_v1_r_run')
    service.delete_view('project.data.dash_b_v1_r_run')
    client.delete_table.assert_called_once_with('project.data.dash_b_v1_r_run', not_found_ok=True, timeout=30)


async def test_staging_copy_failure_preserves_previous_stage(client, app, build_id, monkeypatch):
    folder, service = baseline(app, build_id)
    before, rows = snapshot(folder), metadata(app.state.db, build_id)
    with monkeypatch.context() as patch:
        patch.setattr('dss.spec.publication.shutil.copytree', lambda *a, **kw: (_ for _ in ()).throw(OSError('copy failed')))
        with pytest.raises(RunError):
            await run_publication(app, build_id, service)
    assert snapshot(folder) == before and metadata(app.state.db, build_id) == rows
    with app.state.db.connect() as conn:
        records = [dict(r) for r in conn.execute('SELECT * FROM plan_publications')]
    assert len(records) == 1 and records[0]['restored'] and not records[0]['creating']
    assert not (app.state.settings.get().data_dir / '.publications' / records[0]['run_id']).exists()
    assert not service.deleted


@pytest.fixture
def cloud_state(tmp_path):
    from fastapi.testclient import TestClient
    from dss.config import Config
    from dss.main import create_app
    from fakes import fake_models
    config = Config(data_dir=tmp_path / 'volume', db_path=tmp_path / 'local/db.sqlite', google_api_key='test-key')
    app = create_app(config, model_lister=fake_models)
    with TestClient(app):
        bid = new_id('b')
        with app.state.db.connect() as conn:
            conn.execute('INSERT INTO builds(id,title,archetype,mode,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                         (bid, 'Cloud', 'executive', 'data', 'connect', now(), now()))
        folder, service = baseline(app, bid)
        yield app, bid, folder, service


@pytest.mark.parametrize('checkpoint', ['before_begin', 'creating', 'promoting', 'committed'])
async def test_cloud_old_db_backup_cannot_delete_published_view(cloud_state, tmp_path, monkeypatch, checkpoint):
    app, bid, folder, service = cloud_state
    db = app.state.db
    if checkpoint == 'before_begin':
        db.backup(force=True)
    candidate, spec = staged(app, bid, service)
    if checkpoint == 'creating':
        db.backup(force=True)
    with monkeypatch.context() as patch:
        if checkpoint == 'promoting':
            original = Candidate.commit
            def commit(owner, document):
                db.backup(force=True)
                original(owner, document)
            patch.setattr(Candidate, 'commit', commit)
        candidate.publish(spec)
    if checkpoint == 'committed':
        db.backup(force=True)
    await candidate.cleanup(lambda c: service)
    assert not candidate.root.exists() and candidate.journal.is_file()
    before = snapshot(folder), dict(service.live)
    restarted = Database(tmp_path / 'new-local/db.sqlite', folder.parents[2])
    restarted.initialize()  # Restores the deliberately stale volume SQLite backup.
    for _ in range(2):
        await recover(restarted, app.state.settings.get(), lambda c: service)
        assert snapshot(folder) == before[0] and service.live == before[1]
        assert spec.datasource.table in service.live and not service.deleted
        build, version = metadata(restarted, bid)
        assert build['stage'] == 'prototype' and version['spec_version'] == 5


@pytest.mark.parametrize('checkpoint', ['before_begin', 'creating'])
async def test_cloud_stale_db_recovers_partial_files(cloud_state, tmp_path, monkeypatch, checkpoint):
    app, bid, folder, service = cloud_state
    before, rows = snapshot(folder), metadata(app.state.db, bid)
    if checkpoint == 'before_begin':
        app.state.db.backup(force=True)
    candidate, spec = staged(app, bid, service)
    if checkpoint == 'creating':
        app.state.db.backup(force=True)
    original = Path.replace
    def replace(path, target):
        if path.name == 'spec.json.publish-tmp':
            raise Crash()
        return original(path, target)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'replace', replace)
        with pytest.raises(Crash):
            candidate.publish(spec)
    restarted = Database(tmp_path / 'new-local/db.sqlite', folder.parents[2])
    restarted.initialize()
    for _ in range(2):
        await recover(restarted, app.state.settings.get(), lambda c: service)
        assert snapshot(folder) == before and metadata(restarted, bid) == rows
        assert service.live == {'project.data.legacy_view': 'SELECT old_report_data'}


@pytest.mark.parametrize('visible', [False, True])
async def test_late_bigquery_create_keeps_ownership_until_job_terminal(client, app, build_id, visible):
    from dss.data.bigquery import BigQuery
    from unittest.mock import Mock
    folder, _ = baseline(app, build_id)
    candidate = Candidate.begin(app.state.db, app.state.settings.get(), build_id, 1, new_id('r'))
    client = Mock()
    job = client.query.return_value
    done = False
    job.done.side_effect = lambda **kw: done
    job.result.side_effect = TimeoutError('server still running')
    client.get_job.return_value = job
    class NotVisible(Exception):
        code = 404
    if not visible:
        client.get_job.side_effect = NotVisible()
    service = BigQuery(app.state.settings.get(), client=client)
    table = candidate.creating()
    with pytest.raises(TimeoutError):
        service.create_view(table, 'SELECT candidate_data')
    if visible:
        with pytest.raises(TimeoutError):
            await candidate.cleanup(lambda c: service)
        job.cancel.assert_called_once()
    else:
        await candidate.cleanup(lambda c: service)
    assert candidate.record()['creating'] and candidate.journal.exists()
    # The remote job succeeds AFTER the first cleanup returned.
    live = {table}
    done = True
    client.get_job.side_effect = None
    client.delete_table.side_effect = lambda table, **kw: live.discard(table)
    await recover(app.state.db, app.state.settings.get(), lambda c: service)
    assert not live and not candidate.record()['creating']
    assert not candidate.root.exists()
