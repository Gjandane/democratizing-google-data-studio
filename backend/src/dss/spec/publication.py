"""Run-owned plan candidates, rollback journal and serialized publication reads.

An atomic record on the data volume is the publication point. SQLite can be restored
from an older cloud backup; these records reconcile it before serving requests.
Backups remain until commit so interrupted file replacements can be undone.
"""
import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
import re
import shutil
import threading

from dss.db import now
from dss.harness.nodes.view import view_table

logger = logging.getLogger(__name__)
_locks_guard = threading.Lock()


def initialize(db):
    with db.connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS plan_publications (
            run_id TEXT PRIMARY KEY, build_id TEXT NOT NULL, version INTEGER NOT NULL,
            table_name TEXT NOT NULL UNIQUE, previous_json TEXT NOT NULL,
            creating INTEGER NOT NULL DEFAULT 0, files_json TEXT, restored INTEGER NOT NULL DEFAULT 0,
            committed INTEGER NOT NULL DEFAULT 0, published_spec_version INTEGER)""")


@asynccontextmanager
async def build_lock(db, build_id):
    # HTTP readers may run on a different event loop (TestClient). A thread lock
    # with nonblocking acquisition works across loops without blocking either one.
    with _locks_guard:
        if not hasattr(db, '_publication_locks'):
            db._publication_locks = {}
        lock = db._publication_locks.setdefault(build_id, threading.Lock())
    while not lock.acquire(blocking=False):
        await asyncio.sleep(.005)
    try:
        yield
    finally:
        lock.release()


async def worker(function, *args):
    """Do not release run ownership while a blocking view operation is unfinished."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(task)
        except Exception:
            pass
        raise


class Candidate:
    def __init__(self, db, config, run_id):
        if not re.fullmatch(r'r_[a-zA-Z0-9_]+', run_id):
            raise ValueError('Invalid publication run identity')
        self.db, self.config, self.run_id = db, config, run_id
        self.root = config.data_dir / '.publications' / run_id
        self.folder = self.root / 'candidate'
        self.backup = self.root / 'previous'
        self.journal = self.root.with_suffix('.json')
        self.safe = False

    def record(self):
        if self.journal.exists():
            return json.loads(self.journal.read_text(encoding='utf-8'))
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM plan_publications WHERE run_id=?', (self.run_id,)).fetchone()
        return dict(row) if row else None

    def persist(self, **changes):
        row = {**self.record(), **changes}
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.journal.with_suffix('.json.tmp')
        with temporary.open('w', encoding='utf-8', newline='\n') as stream:
            json.dump(row, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.journal)
        self.sync_record(row)

    def sync_record(self, row):
        keys = tuple(row)
        with self.db.connect() as conn:
            conn.execute(f"INSERT OR REPLACE INTO plan_publications ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
                         tuple(row.values()))

    @property
    def destination(self):
        row = self.record()
        return self.config.data_dir / 'builds' / row['build_id'] / f"v{row['version']}"

    @classmethod
    def begin(cls, db, config, build_id, version, run_id, payload=None):
        initialize(db)
        candidate = cls(db, config, run_id)
        table = view_table(config, build_id, version, run_id)
        with db.connect() as conn:
            build = conn.execute('SELECT * FROM builds WHERE id=?', (build_id,)).fetchone()
            row = conn.execute('SELECT * FROM versions WHERE build_id=? AND n=?',
                               (build_id, version)).fetchone()
            previous = dict(stage=build['stage'], updated_at=build['updated_at'],
                            status=row['status'] if row else 'draft', spec_version=row['spec_version'] if row else None,
                            build=dict(build), version=dict(row) if row else None)
            spec_path = config.data_dir / 'builds' / build_id / f'v{version}' / 'spec.json'
            spec = json.loads(spec_path.read_text(encoding='utf-8')) if spec_path.exists() else None
            previous['spec'] = {'table': spec['datasource']['table'], 'spec_version': spec['spec_version']} if spec else None
            # Ownership is durable BEFORE a create can reach BigQuery.
            conn.execute('INSERT INTO plan_publications(run_id,build_id,version,table_name,previous_json) VALUES(?,?,?,?,?)',
                         (run_id, build_id, version, table, json.dumps(previous)))
        if payload is not None:
            # Make staging failures visible to the harness's normal cleanup path.
            payload['_publication'] = candidate
        candidate.persist()
        destination = candidate.destination
        candidate.backup.mkdir(parents=True)
        if destination.exists():
            shutil.copytree(destination, candidate.backup, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('screens', 'events.jsonl', 'recipe.jsonl'))
        shutil.copytree(candidate.backup, candidate.folder)
        return candidate

    def creating(self):
        self.persist(creating=1)
        return self.record()['table_name']

    def publish(self, spec):
        """Caller holds build_lock and the harness reservation; no awaits in commit."""
        row = self.record()
        if row['committed']:
            return
        if spec.datasource.table != row['table_name']:
            raise ValueError('Spec must bind the owned candidate view')
        files = sorted(str(p.relative_to(self.folder).as_posix()) for p in (self.folder / 'docs').glob('*.md'))
        files += ['spec.json', 'aggregate-cache.json', 'background_p1.png', 'prototype.html']
        if (self.folder / 'requirements.json').is_file():
            files.append('requirements.json')
        for name in files:
            if not (self.folder / name).is_file():
                raise ValueError('Incomplete candidate publication')
        # This write-ahead list makes every partial replacement recoverable.
        self.persist(files_json=json.dumps(files))
        try:
            destination = self.destination
            for name in files:
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + '.publish-tmp')
                shutil.copyfile(self.folder / name, temporary)
                temporary.replace(target)
            self.commit(spec)
        except Exception:
            if not self.record()['committed']:
                # Roll back before the caller releases the read lock.
                self.restore()
            raise

    def commit(self, spec):
        # Durable commit BEFORE readers are released or rollback files are removed.
        self.persist(committed=1, published_spec_version=spec.spec_version)
        self.reconcile()

    def reconcile(self):
        """Repair stale SQLite metadata only for the spec actually on disk now."""
        row = self.record()
        path = self.destination / 'spec.json'
        if not row['committed'] or not path.exists():
            return
        spec = json.loads(path.read_text(encoding='utf-8'))
        if spec['datasource']['table'] != row['table_name']:
            return  # A newer plan/revision owns this version's metadata.
        previous = json.loads(row['previous_json'])
        with self.db.connect() as conn:
            build = previous['build']
            conn.execute(f"INSERT OR IGNORE INTO builds ({','.join(build)}) VALUES ({','.join('?' for _ in build)})", tuple(build.values()))
            conn.execute("INSERT OR IGNORE INTO versions(build_id,n,status,created_at) VALUES(?,?,'draft',?)",
                         (row['build_id'], row['version'], now()))
            version = conn.execute('SELECT spec_version FROM versions WHERE build_id=? AND n=?',
                                   (row['build_id'], row['version'])).fetchone()
            if (version['spec_version'] or 0) < spec['spec_version']:
                conn.execute("UPDATE versions SET spec_version=?,status='draft' WHERE build_id=? AND n=?",
                             (spec['spec_version'], row['build_id'], row['version']))
                conn.execute("UPDATE builds SET current_version=?,stage='prototype',updated_at=? WHERE id=? AND current_version<=?",
                             (row['version'], now(), row['build_id'], row['version']))

    def restore(self):
        row = self.record()
        if row['committed']:
            return
        destination = self.destination
        previous = json.loads(row['previous_json'])
        if row['restored']:
            spec_path = destination / 'spec.json'
            spec = json.loads(spec_path.read_text(encoding='utf-8')) if spec_path.exists() else None
            identity = {'table': spec['datasource']['table'], 'spec_version': spec['spec_version']} if spec else None
            if identity == previous['spec']:
                with self.db.connect() as conn:
                    conn.execute("UPDATE builds SET stage=?,updated_at=? WHERE id=? AND stage='plan' AND current_version=?",
                                 (previous['stage'], previous['updated_at'], row['build_id'], row['version']))
            return
        for name in json.loads(row['files_json'] or '[]'):
            target, previous_file = destination / name, self.backup / name
            if previous_file.exists():
                temporary = target.with_name(target.name + '.restore-tmp')
                shutil.copyfile(previous_file, temporary)
                temporary.replace(target)
            else:
                target.unlink(missing_ok=True)
            target.with_name(target.name + '.publish-tmp').unlink(missing_ok=True)
        with self.db.connect() as conn:
            build = previous['build']
            conn.execute(f"INSERT OR IGNORE INTO builds ({','.join(build)}) VALUES ({','.join('?' for _ in build)})", tuple(build.values()))
            conn.execute('UPDATE builds SET stage=?,updated_at=? WHERE id=?',
                         (previous['stage'], previous['updated_at'], row['build_id']))
            version = previous['version']
            if version:
                conn.execute(f"INSERT OR REPLACE INTO versions ({','.join(version)}) VALUES ({','.join('?' for _ in version)})", tuple(version.values()))
        # A delayed deletion must never roll back a newer publication, including
        # when startup restores a database backup predating the rollback.
        self.persist(restored=1)

    async def cleanup(self, factory):
        row = self.record()
        if row is None:
            return
        async with build_lock(self.db, row['build_id']):
            row = self.record()
            self.sync_record(row)
            if not row['committed']:
                self.restore()
                self.safe = True
                if row['creating']:
                    # Exact run-owned identity only; legacy or published views cannot match.
                    expected = row['table_name']
                    if expected.rsplit('.', 1)[-1] != f"dash_{row['build_id']}_v{row['version']}_{self.run_id}":
                        raise ValueError('Candidate ownership mismatch')
                    terminal = await worker(factory(self.config).delete_view, expected)
                    if terminal is False:
                        return  # A possibly late CREATE still needs reconciliation.
                    self.persist(creating=0)
            else:
                self.reconcile()
                self.safe = True
            # Committed ownership rows survive cleanup, including future replans.
            if self.root.exists():
                shutil.rmtree(self.root)


async def finish(candidate, factory):
    """Cleanup is best effort; a retained journal is retried by startup recovery."""
    try:
        await candidate.cleanup(factory)
    except Exception:
        logger.warning('Plan candidate cleanup deferred until restart')
    return candidate.record() is None or candidate.safe


async def recover(db, config, factory):
    initialize(db)
    for path in (config.data_dir / '.publications').glob('r_*.json'):
        candidate = Candidate(db, config, path.stem)
        candidate.sync_record(candidate.record())
    with db.connect() as conn:
        # Restore unfinished writes first, then reconcile committed identities.
        runs = [r[0] for r in conn.execute('SELECT run_id FROM plan_publications ORDER BY committed')]
    for run_id in runs:
        if not await finish(Candidate(db, config, run_id), factory):
            raise RuntimeError('Interrupted plan publication could not be restored')


class PublicationReads:
    """Hold a build's read lock through FileResponse streaming as well as JSON reads."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        parts = scope.get('path', '').strip('/').split('/')
        if (scope['type'] == 'http' and scope['method'] == 'GET' and len(parts) >= 3
                and parts[:2] == ['api', 'builds'] and parts[3:] != ['events']):
            async with build_lock(scope['app'].state.db, parts[2]):
                with scope['app'].state.db.connect() as conn:
                    pending = conn.execute('SELECT 1 FROM plan_publications WHERE build_id=? AND files_json IS NOT NULL '
                                           'AND committed=0 AND restored=0', (parts[2],)).fetchone()
                if pending:
                    from starlette.responses import JSONResponse
                    response = JSONResponse({'error': {'code': 'invalid_source',
                        'message': 'Interrupted plan publication requires recovery', 'detail': {}}}, status_code=503)
                    await response(scope, receive, send)
                    return
                await self.app(scope, receive, send)
        else:
            await self.app(scope, receive, send)
