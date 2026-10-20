"""Durable generation boundaries and recovery from real SQLite backup snapshots."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import threading
import time
from unittest.mock import Mock

from fastapi.testclient import TestClient
import httpx
import pytest
from google.api_core.exceptions import Conflict, NotFound, ServiceUnavailable

import dss.db as db_module
from dss.config import Config
from dss.data.bigquery import BigQuery
from dss.db import Database
from dss.harness.nodes import synthetic_generate as node
from dss.main import create_app
from fakes import fake_models
from test_synthetic_api import FakeTypedBigQuery as ApiFakeTypedBigQuery
from test_synthetic_api import create, events, generate, post, wait


class FakeTypedBigQuery(ApiFakeTypedBigQuery):
    def delete_loaded_table(self, table, *, fence_missing=False):
        return super().delete_loaded_table(table)


def application(config, fake):
    return create_app(config, model_lister=fake_models, bigquery_factory=lambda _: fake)


def config_for(tmp_path):
    return Config(data_dir=tmp_path / 'volume', db_path=tmp_path / 'local' / 'live.sqlite',
                  gcp_project_id='test-project')


def rows(db, table='synthetic_generations'):
    with db.connect() as conn:
        return [dict(row) for row in conn.execute(f'SELECT * FROM {table}')]


def replace(config, **fields):
    return config.model_copy(update=fields)


def snapshot_state(path):
    with closing(sqlite3.connect(path)) as conn:
        row = conn.execute('SELECT state FROM synthetic_generations LIMIT 1').fetchone()
    return row[0] if row else None


def test_ack_and_completion_wait_for_backups_including_replay(tmp_path, monkeypatch):
    config, fake = config_for(tmp_path), FakeTypedBigQuery()
    app = application(config, fake)
    entered = {state: threading.Event() for state in ('queued', 'succeeded')}
    release = {state: threading.Event() for state in entered}
    original = db_module.shutil.copyfile
    replay_backing_up = threading.Event()

    def gated_copy(source, destination, *args, **kwargs):
        if Path(source).name == 'dss.bak':
            state = snapshot_state(source)
            if state in entered and not release[state].is_set():
                entered[state].set()
                assert release[state].wait(10)
        return original(source, destination, *args, **kwargs)

    with TestClient(app) as client, ThreadPoolExecutor(2) as pool:
        bid = create(client)
        original_async = app.state.db.async_backup
        calls = 0
        async def backup(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                replay_backing_up.set()
            await original_async(**kwargs)
        monkeypatch.setattr(app.state.db, 'async_backup', backup)
        monkeypatch.setattr(db_module.shutil, 'copyfile', gated_copy)
        accepted = pool.submit(post, client, bid)
        try:
            assert entered['queued'].wait(5)
            replay = pool.submit(post, client, bid)
            assert replay_backing_up.wait(5)
            assert not accepted.done() and not replay.done()
            assert not fake.loads and not app.state.engine_tasks
            # The action lock is already held throughout the reservation backup.
            assert post(client, bid, key='different').status_code == 409
            release['queued'].set()
            response = accepted.result(timeout=5)
            assert response.status_code == 202
            assert replay.result(timeout=5).json() == response.json()
            assert entered['succeeded'].wait(5)
            run_id = response.json()['run_id']
            assert rows(app.state.db)[0]['state'] == 'succeeded'
            assert len(rows(app.state.db, 'sources')) == 1
            assert 'run.finished' not in [kind for kind, _ in events(app, run_id)]
            release['succeeded'].set()
            wait(app)
            kind, payload = events(app, run_id)[-1]
            assert kind == 'run.finished' and payload['run_id'] == run_id and payload['status'] == 'ok'
            assert snapshot_state(app.state.db.backup_path) == 'succeeded'
        finally:
            for gate in release.values():
                gate.set()


def completed_snapshots(tmp_path, monkeypatch, *, before_commit=False):
    """Finish a job, retaining the actual backup images from each crash boundary."""
    config, fake = config_for(tmp_path), FakeTypedBigQuery()
    app, snapshots = application(config, fake), {}
    original_backup = Database.backup
    original_register = node.register_source

    def backup(db, **kwargs):
        original_backup(db, **kwargs)
        if db.backup_path and db.backup_path.exists():
            state = snapshot_state(db.backup_path)
            if state:
                snapshots.setdefault(state, db.backup_path.read_bytes())

    def register(db, *args):
        db.backup(force=True)
        assert snapshot_state(db.backup_path) == 'loading'
        original_register(db, *args)

    with monkeypatch.context() as patch:
        patch.setattr(Database, 'backup', backup)
        if before_commit:
            patch.setattr(node, 'register_source', register)
        with TestClient(app) as client:
            bid = create(client)
            run_id, status = generate(client, app, bid)
            assert status['state'] == 'succeeded'
            job, = rows(app.state.db)
    return config, fake, bid, run_id, job, snapshots


@pytest.mark.parametrize('checkpoint', ['queued', 'loading'])
def test_old_backup_recovers_only_owned_artifacts_and_retry_has_one_source(tmp_path, monkeypatch, checkpoint):
    config, fake, bid, run_id, job, snapshots = completed_snapshots(
        tmp_path, monkeypatch, before_commit=checkpoint == 'loading')
    # These files/table belong to other jobs and builds, and must survive recovery.
    others = [node.prefix(config.data_dir, bid, 'other'),
              node.prefix(config.data_dir, 'b_0123456789ab', 'sample_001')]
    for folder in others:
        folder.mkdir(parents=True)
        (folder / 'keep.txt').write_text('keep', encoding='utf-8')
    fake.tables['other.table'] = ([], [])
    (config.data_dir / 'dss.sqlite').write_bytes(snapshots[checkpoint])
    restarted = application(replace(config, db_path=tmp_path / 'replacement.sqlite'), fake)
    with TestClient(restarted) as client:
        # Startup has completed recovery before the first request.
        status = client.get(f'/api/builds/{bid}/synthetic-data/jobs/sample_001').json()
        assert status['state'] == 'failed' and status['error']['code'] == 'generation_interrupted'
        assert status['retry_ready'] is True and status['source_id'] is None
        assert status['run_id'] == run_id
        assert rows(restarted.state.db, 'sources') == []
        assert not node.prefix(config.data_dir, bid, 'sample_001').exists()
        assert fake.deleted == [job['bq_table']]
        assert list(fake.tables) == ['other.table']
        assert all((folder / 'keep.txt').read_text() == 'keep' for folder in others)
        assert post(client, bid).json() == {'run_id': run_id}
        assert len(fake.loads) == 1  # Replay never starts another worker.
        assert snapshot_state(restarted.state.db.backup_path) == 'failed'
        # Use a fresh key for an explicit retry, after cleanup is persisted.
        retry_run, retry = generate(client, restarted, bid, key='retry_001')
        assert retry_run != run_id and retry['state'] == 'succeeded'
        assert len(rows(restarted.state.db, 'sources')) == 1
        assert len(fake.loads) == 2
    again = application(replace(config, db_path=tmp_path / 'again.sqlite'), fake)
    with TestClient(again) as client:
        assert len(client.get(f'/api/builds/{bid}').json()['sources']) == 1
        assert fake.deleted == [job['bq_table']]


def test_registration_backup_keeps_succeeded_job_and_single_source(tmp_path, monkeypatch):
    config, fake, bid, run_id, job, snapshots = completed_snapshots(tmp_path, monkeypatch)
    (config.data_dir / 'dss.sqlite').write_bytes(snapshots['succeeded'])
    restarted = application(replace(config, db_path=tmp_path / 'replacement.sqlite'), fake)
    with TestClient(restarted) as client:
        status = client.get(f'/api/builds/{bid}/synthetic-data/jobs/sample_001').json()
        assert status['state'] == 'succeeded' and status['source_id'] == job['source_id']
        assert status['error'] is None and not status['retry_ready']
        assert len(rows(restarted.state.db, 'sources')) == 1
        assert post(client, bid).json() == {'run_id': run_id}
        assert len(fake.loads) == 1 and not fake.deleted
        assert client.get(f"/api/builds/{bid}/synthetic-data/{job['source_id']}/csv").status_code == 200


@pytest.mark.parametrize('failure', ['delete', 'unobserved', 'factory', 'files'])
def test_cleanup_failure_is_durable_and_retried_at_next_start(tmp_path, monkeypatch, failure):
    config, fake, bid, _, job, snapshots = completed_snapshots(tmp_path, monkeypatch)
    (config.data_dir / 'dss.sqlite').write_bytes(snapshots['queued'])
    restarted_config = replace(config, db_path=tmp_path / 'replacement.sqlite')
    restarted = application(restarted_config, fake)
    with monkeypatch.context() as patch:
        if failure == 'delete':
            patch.setattr(fake, 'fail_delete', True)
        elif failure == 'unobserved':
            patch.setattr(fake, 'delete_loaded_table', lambda table, **kwargs: False)
        elif failure == 'factory':
            def no_client(_):
                raise RuntimeError('private credentials')
            restarted = create_app(restarted_config, model_lister=fake_models, bigquery_factory=no_client)
        else:
            original_remove = node.shutil.rmtree
            def fail_remove(path, *args, **kwargs):
                if Path(path) == node.prefix(config.data_dir, bid, 'sample_001'):
                    raise OSError('volume unavailable')
                return original_remove(path, *args, **kwargs)
            patch.setattr(node.shutil, 'rmtree', fail_remove)
        with TestClient(restarted) as client:
            status = client.get(f'/api/builds/{bid}/synthetic-data/jobs/sample_001').json()
            assert status['state'] == 'failed' and not status['retry_ready']
            assert status['error']['code'] == 'generation_interrupted'
            assert rows(restarted.state.db, 'sources') == []
            with closing(sqlite3.connect(config.data_dir / 'dss.sqlite')) as conn:
                assert conn.execute('SELECT state,retry_ready FROM synthetic_generations').fetchone() == ('failed', 0)
    again = application(replace(config, db_path=tmp_path / 'again.sqlite'), fake)
    with TestClient(again) as client:
        assert client.get(f'/api/builds/{bid}/synthetic-data/jobs/sample_001').json()['retry_ready']
        assert job['bq_table'] not in fake.tables


def test_failing_immediate_backup_warns_but_accepts_and_stays_dirty(tmp_path, monkeypatch, caplog):
    config, fake = config_for(tmp_path), FakeTypedBigQuery()
    app = application(config, fake)
    with TestClient(app) as client:
        bid = create(client)
        original = db_module.shutil.copyfile
        with monkeypatch.context() as patch:
            def fail_snapshot(source, destination, *args, **kwargs):
                if Path(source).name == 'dss.bak':
                    raise OSError('private deployment path')
                return original(source, destination, *args, **kwargs)
            patch.setattr(db_module.shutil, 'copyfile', fail_snapshot)
            response = post(client, bid)
            assert response.status_code == 202
            wait(app)
            assert rows(app.state.db)[0]['state'] == 'succeeded'
            assert app.state.db.dirty
            assert events(app, response.json()['run_id'])[-1][1]['status'] == 'ok'
        assert 'Database backup failed; will retry' in caplog.text
        assert 'private deployment path' not in caplog.text
        app.state.db.backup()
        assert not app.state.db.dirty


async def test_periodic_and_immediate_share_snapshot_lock(tmp_path, monkeypatch):
    db = Database(tmp_path / 'local.sqlite', tmp_path / 'volume')
    db.initialize()
    entered, release, periodic_called = threading.Event(), threading.Event(), threading.Event()
    original_copy, original_async = db_module.shutil.copyfile, db.async_backup
    active = maximum = 0
    calls = 0
    lock = threading.Lock()

    def copy(*args, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        entered.set()
        try:
            assert release.wait(5)
            return original_copy(*args, **kwargs)
        finally:
            with lock:
                active -= 1

    async def backup(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            periodic_called.set()
        await original_async(**kwargs)

    monkeypatch.setattr(db_module.shutil, 'copyfile', copy)
    monkeypatch.setattr(db_module, 'BACKUP_INTERVAL_S', .01)
    monkeypatch.setattr(db, 'async_backup', backup)
    stop = asyncio.Event()
    immediate = asyncio.create_task(db.async_backup())
    periodic = asyncio.create_task(db.periodic_backup(stop))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        assert await asyncio.to_thread(periodic_called.wait, 3)
        assert not immediate.done()
    finally:
        stop.set()
        release.set()
        await asyncio.gather(immediate, periodic)
    assert maximum == 1 and calls >= 2 and not db.dirty


def test_colocated_database_backup_is_noop(tmp_path, monkeypatch):
    app = application(Config(data_dir=tmp_path, db_path=tmp_path / 'dss.sqlite',
                             gcp_project_id='test-project'), FakeTypedBigQuery())
    with TestClient(app) as client:
        def unexpected(**kwargs):
            raise AssertionError('No snapshot worker is needed for a colocated DB')
        monkeypatch.setattr(app.state.db, 'backup', unexpected)
        assert app.state.db.backup_path is None
        bid = create(client)
        _, status = generate(client, app, bid)
        assert status['state'] == 'succeeded'
        assert len(rows(app.state.db, 'sources')) == 1


@pytest.mark.parametrize('race', ['absent', 'load_wins', 'not_visible', 'fence_fails'])
def test_recovery_fences_missing_load_using_real_bigquery_helper(tmp_path, monkeypatch, race):
    config, _, bid, _, job, snapshots = completed_snapshots(tmp_path, monkeypatch)
    (config.data_dir / 'dss.sqlite').write_bytes(snapshots['queued'])
    remote, terminal = Mock(), Mock()
    terminal.done.return_value = True
    remote.get_job.side_effect = [NotFound('absent'),
                                  NotFound('not visible') if race == 'not_visible' else terminal]
    if race in ('load_wins', 'not_visible'):
        remote.query.side_effect = Conflict('load already accepted')
    elif race == 'fence_fails':
        remote.query.side_effect = ServiceUnavailable('private error')
    else:
        remote.query.return_value = terminal
    configs = []
    def factory(restored_config):
        configs.append(restored_config)
        return BigQuery(restored_config, client=remote)
    # Recovery must use reserved project/location even after deployment settings change.
    changed = replace(config, db_path=tmp_path / 'replacement.sqlite',
                      gcp_project_id='new-project', bq_location='EU')
    restarted = create_app(changed, model_lister=fake_models, bigquery_factory=factory)
    with TestClient(restarted) as client:
        status = client.get(f'/api/builds/{bid}/synthetic-data/jobs/sample_001').json()
        assert status['state'] == 'failed'
        assert status['retry_ready'] is (race in ('absent', 'load_wins'))
        assert configs[0].gcp_project_id == 'test-project' and configs[0].bq_location == config.bq_location
        job_id = BigQuery.load_job_id(job['bq_table'])
        remote.query.assert_called_once_with('SELECT 1', job_id=job_id, location=config.bq_location,
                                             timeout=30, job_retry=None)
        assert remote.get_job.call_args_list[0].args == (job_id,)
        if status['retry_ready']:
            terminal.done.assert_called_once_with(timeout=30)
            remote.delete_table.assert_called_once_with(job['bq_table'], not_found_ok=True, timeout=30)
        else:
            remote.delete_table.assert_not_called()


def test_cancel_during_reservation_backup_leaves_terminal_durable_job(tmp_path, monkeypatch):
    config, fake = config_for(tmp_path), FakeTypedBigQuery()
    app = application(config, fake)
    entered, release = threading.Event(), threading.Event()
    original = db_module.shutil.copyfile
    def copy(source, destination, *args, **kwargs):
        if Path(source).name == 'dss.bak' and not release.is_set():
            entered.set()
            assert release.wait(5)
        return original(source, destination, *args, **kwargs)
    with TestClient(app) as client:
        bid = create(client)
        with monkeypatch.context() as patch:
            patch.setattr(db_module.shutil, 'copyfile', copy)
            async def cancel():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as http:
                    from test_synthetic_api import SPEC
                    request = asyncio.create_task(http.post(f'/api/builds/{bid}/synthetic-data',
                        json={'generation_key': 'sample_001', 'proposal_id': None, 'spec': SPEC}))
                    try:
                        assert await asyncio.to_thread(entered.wait, 3)
                        request.cancel()
                    finally:
                        release.set()
                    with pytest.raises(asyncio.CancelledError):
                        await request
            client.portal.call(cancel)
        job, = rows(app.state.db)
        assert job['state'] == 'failed' and job['retry_ready'] == 1
        assert not fake.loads and not app.state.engine_tasks and not app.state.harness.active_builds
        assert snapshot_state(app.state.db.backup_path) == 'failed'
        assert post(client, bid).json() == {'run_id': job['run_id']}
        _, status = generate(client, app, bid, key='retry_001')
        assert status['state'] == 'succeeded'


@pytest.mark.parametrize('corruption', ['csv', 'missing_csv', 'missing_metadata'])
def test_succeeded_recovery_validates_checksum_before_serving(tmp_path, monkeypatch, corruption):
    config, fake, bid, _, _, snapshots = completed_snapshots(tmp_path, monkeypatch)
    (config.data_dir / 'dss.sqlite').write_bytes(snapshots['succeeded'])
    folder = node.prefix(config.data_dir, bid, 'sample_001')
    if corruption == 'csv':
        (folder / node.CSV).write_bytes(b'altered')
    else:
        (folder / (node.CSV if corruption == 'missing_csv' else node.METADATA)).unlink()
    restarted = application(replace(config, db_path=tmp_path / 'replacement.sqlite'), fake)
    with pytest.raises(RuntimeError, match='Stored synthetic sample data failed recovery validation'):
        with TestClient(restarted):
            pytest.fail('Startup served a corrupt synthetic source')
    assert not fake.deleted


def test_cancelled_registration_waits_for_backup_before_completion(tmp_path, monkeypatch):
    config, fake = config_for(tmp_path), FakeTypedBigQuery()
    app = application(config, fake)
    entered, release = threading.Event(), threading.Event()
    original = db_module.shutil.copyfile
    def copy(source, destination, *args, **kwargs):
        if Path(source).name == 'dss.bak' and snapshot_state(source) == 'succeeded':
            entered.set()
            assert release.wait(5)
        return original(source, destination, *args, **kwargs)
    with TestClient(app) as client:
        bid = create(client)
        with monkeypatch.context() as patch:
            patch.setattr(db_module.shutil, 'copyfile', copy)
            accepted = post(client, bid)
            assert accepted.status_code == 202
            run_id = accepted.json()['run_id']
            try:
                assert entered.wait(5)
                async def cancel():
                    task, = app.state.engine_tasks
                    task.cancel()
                    await asyncio.sleep(0)
                    assert 'run.finished' not in [kind for kind, _ in events(app, run_id)]
                    task.cancel()  # A second cancellation must not cancel the inner snapshot.
                    await asyncio.sleep(0)
                    assert 'run.finished' not in [kind for kind, _ in events(app, run_id)]
                    release.set()
                    await asyncio.gather(task, return_exceptions=True)
                client.portal.call(cancel)
                assert snapshot_state(app.state.db.backup_path) == 'succeeded'
                assert events(app, run_id)[-1][0] == 'run.finished'
                assert len(rows(app.state.db, 'sources')) == 1 and not fake.deleted
            finally:
                release.set()


def test_stalled_registration_backup_is_bounded_during_agent_shutdown(tmp_path, monkeypatch, caplog):
    import dss.main as main_module
    config, fake = replace(config_for(tmp_path), engine_mode='agent'), FakeTypedBigQuery()
    app = application(config, fake)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = db_module.shutil.copyfile
    def copy(source, destination, *args, **kwargs):
        if Path(source).name == 'dss.bak' and snapshot_state(source) == 'succeeded':
            entered.set()
            try:
                assert release.wait(5)
            finally:
                finished.set()
        return original(source, destination, *args, **kwargs)
    monkeypatch.setattr(db_module, 'IMMEDIATE_BACKUP_TIMEOUT_S', .1)
    monkeypatch.setattr(main_module, 'SHUTDOWN_BACKUP_TIMEOUT_S', .1)
    try:
        with TestClient(app) as client:
            bid = create(client)
            monkeypatch.setattr(db_module.shutil, 'copyfile', copy)
            accepted = post(client, bid)
            assert accepted.status_code == 202
            assert entered.wait(3)
            assert app.state.db.dirty
            started = time.monotonic()
        assert time.monotonic() - started < 1
        assert not finished.is_set() and app.state.db.dirty
        assert 'Database backup exceeded the immediate budget; will retry' in caplog.text
    finally:
        release.set()
        if entered.is_set():
            assert finished.wait(3)
