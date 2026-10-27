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
from dss.artifacts.state import stage
from dss.harness.nodes.view import view_table

logger = logging.getLogger(__name__)
_locks_guard = threading.Lock()
DESIGN_PAGES = 'design-pages.json'
BRIEF_FILE = re.compile(r'brief_p[1-5]\.(json|md)')


def design_pages(spec, folder):
    """Published page metadata, including a deterministic legacy projection without briefs."""
    path = folder / DESIGN_PAGES
    saved = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    records = {p['page']: p for p in saved.get('pages', [])} if saved.get('spec_version') == spec.spec_version else {}
    return [records.get(p.index, {'page': p.index, 'layout': 'designed' if p.design else 'standard',
            'standard_reason': None if p.design else 'not_designed', 'brief': None,
            'html_model': p.design.model if p.design else None}) for p in spec.pages]


def design_artifacts(spec, folder, briefs=None, *, reset=False):
    """An unpublished file update set. None values retire obsolete brief files atomically.

    `briefs` holds generated records and actual HTML models, outside DashboardSpec. An accept
    resets the version's previous records; a revise preserves records for untouched pages.
    """
    from dss.harness.nodes.reference_brief import canonical
    previous = {} if reset else {p['page']: p for p in design_pages(spec, folder)}
    # A revise increments spec_version; its previous metadata still belongs to unchanged pages.
    path = folder / DESIGN_PAGES
    if not reset and path.is_file():
        previous = {p['page']: p for p in json.loads(path.read_text(encoding='utf-8'))['pages']}
    updates, pages = {}, []
    for page in spec.pages:
        record = (briefs or {}).get(page.index, previous.get(page.index, {}))
        brief = record.get('brief')
        row = {'page': page.index, 'layout': 'designed' if page.design else 'standard',
               'standard_reason': None if page.design else 'layout_fallback' if (
                   record.get('layout_fallback') or record.get('standard_reason') == 'layout_fallback'
                   or record.get('html_model')) else 'not_designed',
               'brief': brief, 'html_model': page.design.model if page.design else record.get('html_model')}
        pages.append(row)
        if brief is not None:
            updates[f'brief_p{page.index}.json'] = canonical(brief['brief'])
            updates[f'brief_p{page.index}.md'] = brief['markdown'].encode('utf-8')
    updates[DESIGN_PAGES] = json.dumps({'spec_version': spec.spec_version, 'pages': pages},
                                     ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    for path in folder.glob('brief_p*.*'):
        if BRIEF_FILE.fullmatch(path.name) and path.name not in updates:
            updates[path.name] = None
    return updates


def initialize(db):
    from dss.memory.episodic import initialize_reviews
    initialize_reviews(db)
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
        from dss.render.background import names
        files += ['spec.json', 'aggregate-cache.json', *names(spec), 'prototype.html']
        if (self.folder / 'requirements.json').is_file():
            files.append('requirements.json')
        if (self.folder / DESIGN_PAGES).is_file():
            files += [DESIGN_PAGES, *sorted(p.name for p in self.folder.glob('brief_p*.*')
                                           if BRIEF_FILE.fullmatch(p.name))]
        for name in files:
            if not (self.folder / name).is_file():
                raise ValueError('Incomplete candidate publication')
        # Retire previous briefs too; recovery journals replacements and deletions together.
        obsolete = sorted(p.name for p in self.backup.glob('brief_p*.*')
                          if BRIEF_FILE.fullmatch(p.name) and not (self.folder / p.name).exists())
        files += obsolete
        # This write-ahead list makes every partial replacement recoverable.
        self.persist(files_json=json.dumps(files))
        try:
            destination = self.destination
            for name in files:
                target = destination / name
                if name in obsolete:
                    target.unlink(missing_ok=True)
                    continue
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
        # Journals outlive database migrations, including old cloud snapshots.
        previous['stage'] = stage(previous)
        with self.db.connect() as conn:
            build = previous['build']
            columns = {r['name'] for r in conn.execute('PRAGMA table_info(builds)')}
            build = {key: value for key, value in build.items() if key in columns}
            build['stage'] = stage(build)
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
        previous['stage'] = stage(previous)
        if row['restored']:
            spec_path = destination / 'spec.json'
            spec = json.loads(spec_path.read_text(encoding='utf-8')) if spec_path.exists() else None
            identity = {'table': spec['datasource']['table'], 'spec_version': spec['spec_version']} if spec else None
            if identity == previous['spec']:
                with self.db.connect() as conn:
                    current_row = conn.execute('SELECT * FROM builds WHERE id=?', (row['build_id'],)).fetchone()
                    current = dict(current_row) if current_row is not None else None
                    from dss.artifacts.state import states
                    legacy_pending = (current is not None and current['stage'] == 'context' and
                                      set(states(current).values()) == {'missing'} and
                                      current['notes'] == previous['build'].get('notes'))
                    # Only a stale pre-2.0 database backup needs stage repair here.
                    # A later artifact edit keeps the same spec identity on purpose.
                    if current is not None and (current['stage'] == 'plan' or legacy_pending):
                        conn.execute('UPDATE builds SET stage=?,updated_at=? WHERE id=? AND current_version=?',
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
            columns = {r['name'] for r in conn.execute('PRAGMA table_info(builds)')}
            build = {key: value for key, value in build.items() if key in columns}
            build['stage'] = stage(build)
            conn.execute(f"INSERT OR IGNORE INTO builds ({','.join(build)}) VALUES ({','.join('?' for _ in build)})", tuple(build.values()))
            conn.execute('UPDATE builds SET stage=?,updated_at=? WHERE id=?',
                         (previous['stage'], previous['updated_at'], row['build_id']))
            if 'artifacts_json' in build:
                # A blueprint confirmation saved before an uncommitted publish rolls back too.
                conn.execute('UPDATE builds SET artifacts_json=? WHERE id=?', (build['artifacts_json'], row['build_id']))
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
            from dss.memory.episodic import brief_review, update_brief_review
            review = brief_review(self.db, row['build_id'])
            if review and review['record']['owner'] == self.run_id:
                if not row['committed'] and not row['restored']:
                    self.safe = True  # intentionally retained; no clock or run owns the wait
                    return
                # The volume journal outlives an older SQLite backup. A terminal publication
                # must reconcile normally and must never resurrect a gate to its removed files.
                update_brief_review(self.db, review, review['record'], state='retired')
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
    # Revisions own no new view, but their copied candidate also needs crash cleanup.
    with db.connect() as conn:
        retained = {json.loads(r[0])['owner'] for r in conn.execute(
            "SELECT record_json FROM brief_reviews WHERE state='pending'")}
    root = config.data_dir / '.brief-reviews'
    for folder in root.glob('r_*'):
        if (folder.name not in retained and folder.is_dir()
                and folder.resolve().parent == root.resolve()):
            shutil.rmtree(folder)


class PublicationReads:
    """Shared pending-review mutation guard and publication locks for all build reads."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        parts = scope.get('path', '').strip('/').split('/')
        if (scope['type'] == 'http' and scope['method'] in ('POST', 'PUT', 'PATCH', 'DELETE')
                and len(parts) >= 3 and parts[:2] == ['api', 'builds']
                and (scope['method'], tuple(parts[3:])) not in {
                    ('PUT', ('briefs', 'review')),
                    ('POST', ('briefs', 'review', 'approve')),
                    ('POST', ('briefs', 'review', 'cancel'))}):
            from dss.memory.episodic import require_no_brief_review
            from dss.harness.guardrails import RunError
            try:
                require_no_brief_review(scope['app'].state.db, parts[2])
            except RunError as error:
                from starlette.responses import JSONResponse
                await JSONResponse({'error': {'code': error.code, 'message': error.message, 'detail': error.detail}},
                                   status_code=error.status_code)(scope, receive, send)
                return
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


class ReviewPause(Exception):
    """Caught inside the action node, before ADK; the run completes successfully."""


def review_fingerprint(db, config, build_id, folder):
    from dss.spec import requirements as req, references
    from dss.spec.capabilities import Checker, load_registry
    with db.connect() as conn:
        build = dict(conn.execute('SELECT * FROM builds WHERE id=?', (build_id,)).fetchone())
    live = config.data_dir / 'builds' / build_id / f"v{build['current_version']}"
    ledger = req.load(live)
    return req.digest({'inputs': req.inputs(db, build_id, live), 'artifacts': build['artifacts_json'],
                       'version': build['current_version'], 'stage': build['stage'],
                       'ledger': ledger.model_dump(mode='json'), 'reference': references.load(live),
                       'catalog': Checker(load_registry()).digest(), 'candidate': folder_digest(folder)})


def folder_digest(folder):
    from hashlib import sha256
    # Names and contents both matter; a removed/replaced image is stale too.
    return sha256(b''.join(str(p.relative_to(folder).as_posix()).encode() + b'\0' +
                          sha256(p.read_bytes()).digest() for p in sorted(folder.rglob('*')) if p.is_file())).hexdigest()


class BriefGate:
    """Serializable page continuation. It never keeps a provider stream or a clock open."""
    def __init__(self, harness, config, build_id, run_id, action, folder, state, *, owner=None):
        self.harness, self.config = harness, config
        self.build_id, self.run_id, self.action = build_id, run_id, action
        self.folder, self.state, self.owner = folder, state, owner or run_id
        self.results = state.setdefault('results', {})
        self.briefs = {int(k): v for k, v in state.setdefault('briefs', {}).items()}
        self.approved = state.pop('approved', None)

    @property
    def enabled(self):
        from dss.harness.stages import execution
        current = execution.get()
        return (current.config if current else self.config).review_briefs

    def result(self, page):
        from dss.harness.nodes.designer import Designed, Fallback
        saved = self.results.get(str(page))
        if saved:
            return Designed(**saved['designed']) if 'designed' in saved else Fallback(**saved['fallback'])

    def completed(self, page, result):
        from dss.harness.nodes.designer import Designed
        self.results[str(page)] = {'designed' if isinstance(result, Designed) else 'fallback': result._asdict()}

    def reviewed(self, page):
        if self.approved and self.approved['page'] == page:
            return self.approved

    async def pause(self, page, reference, first, revision):
        from dss.db import new_id
        from dss.memory.episodic import save_brief_review
        # The current run snapshots the setting; switching it off affects the next brief.
        if not self.enabled:
            return
        record = self.briefs[page.index]['brief']
        review = {'review_id': new_id('br'), 'revision': 1, 'action': self.action,
                  'page': page.index, 'pages': len(self.state['spec']['pages']),
                  'components': [{'id': c.id, 'type': c.type, 'label': c.label} for c in page.components],
                  'brief': record, 'issues': [], 'stale': False, 'created_at': now()}
        self.state['briefs'] = self.briefs
        self.state['html_inputs'] = {'first': first._asdict() if first else None,
                                     'revision': revision, 'approved': reference.approved[page.index]}
        saved = {'review': review, 'owner': self.owner, 'folder': str(self.folder), 'state': self.state,
                 'fingerprint': review_fingerprint(self.harness.db, self.config, self.build_id, self.folder)}
        from dss.spec.requirements import digest
        saved['state_digest'] = digest(self.state)
        save_brief_review(self.harness.db, self.build_id, saved)
        await self.harness.db.immediate_backup()
        await self.harness.emit(self.build_id, self.run_id, 'brief.review',
                                {k: review[k] for k in ('review_id', 'page', 'pages')})
        raise ReviewPause()

    def cleanup_revision(self):
        from dss.memory.episodic import brief_review
        if self.action == 'revise' and not brief_review(self.harness.db, self.build_id):
            expected = self.config.data_dir / '.brief-reviews' / self.owner
            if self.folder.resolve() != expected.resolve():
                raise ValueError('Review candidate ownership mismatch')
            if self.folder.exists():
                try:
                    shutil.rmtree(self.folder)
                except OSError:
                    logger.warning('Revision candidate cleanup deferred until restart')
