"""api.md 2.0 Stage rules, migrations and the saved-spec compatibility boundary."""
from contextlib import closing
import json
import sqlite3

import pytest

from dss.artifacts import state
from dss.db import Database
from dss.harness.guardrails import RunError
from test_thin_slice import thin, load_checked, wait_done


def build(stage, **values):
    return {'stage': stage, 'artifacts_json': json.dumps({name: values.get(name, 'confirmed') for name in state.ARTIFACTS})}


@pytest.mark.parametrize('stage', state.STAGES)
@pytest.mark.parametrize('artifact', state.ARTIFACTS)
def test_edit_in_every_stage(stage, artifact):
    before = build(stage)
    allowed = state.STAGES.index(artifact) <= state.STAGES.index(stage) < state.STAGES.index('build')
    if not allowed:
        with pytest.raises(RunError) as error:
            state.edited(before, artifact)
        assert error.value.status_code == 409 and error.value.code == 'wrong_stage'
        assert error.value.detail == {'stage': stage}
        return
    result = state.edited(before, artifact)
    assert result['stage'] == artifact
    after = state.states(result)
    index = state.ARTIFACTS.index(artifact)
    assert list(after.values()) == ['confirmed'] * index + ['draft'] + ['stale'] * (3 - index)
    assert set(state.states(before).values()) == {'confirmed'}  # no mutation of caller's snapshot


@pytest.mark.parametrize('stage', state.STAGES)
@pytest.mark.parametrize('artifact', state.ARTIFACTS)
def test_confirm_in_every_stage(stage, artifact):
    before = build(stage, **{artifact: 'draft'})
    if stage != artifact:
        with pytest.raises(RunError) as error:
            state.confirmed(before, artifact)
        assert error.value.code == 'wrong_stage' and error.value.status_code == 409
    else:
        result = state.confirmed(before, artifact)
        assert state.states(result)[artifact] == 'confirmed'
        assert result['stage'] == {'context': 'outline', 'outline': 'design', 'design': 'blueprint',
                                   'blueprint': 'blueprint'}[artifact]


@pytest.mark.parametrize('artifact', state.ARTIFACTS)
def test_confirm_rejects_issues_and_missing_artifact(artifact):
    issues = [{'path': '/title', 'message': 'A title is required'}]
    before = build(artifact, **{artifact: 'draft'})
    with pytest.raises(RunError) as error:
        state.confirmed(before, artifact, issues)
    assert error.value.status_code == 409 and error.value.code == 'artifact_invalid'
    assert error.value.detail == {'issues': issues}
    with pytest.raises(RunError) as error:
        state.confirmed(build(artifact, **{artifact: 'missing'}), artifact)
    assert error.value.code == 'artifact_invalid'


def test_edit_and_reconfirm_keep_downstream_work_and_invalidate_all_later_artifacts():
    result = state.edited(build('prototype'), 'context')
    result = state.confirmed(result, 'context')
    assert result['stage'] == 'outline'
    assert state.states(result) == {'context': 'confirmed', 'outline': 'stale', 'design': 'stale', 'blueprint': 'stale'}
    initial = build('context', **dict.fromkeys(state.ARTIFACTS, 'missing'))
    assert state.states(state.edited(initial, 'context')) == {
        'context': 'draft', 'outline': 'stale', 'design': 'stale', 'blueprint': 'stale'}
    with pytest.raises(RunError) as error:
        state.confirmed(build('design', context='draft'), 'design')
    assert error.value.code == 'wrong_stage'


def test_state_mutation_uses_existing_lock_and_keeps_published_files(thin):
    client, app, bid, folder = thin
    load_checked(client, bid)
    originals = {'spec.json': (folder / 'spec.json').read_bytes(),
                 'prototype.html': (folder / 'prototype.html').read_bytes(),
                 'background_p1.png': b'old background'}
    (folder / 'background_p1.png').write_bytes(originals['background_p1.png'])
    with app.state.db.connect() as conn:
        conn.execute('UPDATE builds SET artifacts_json=? WHERE id=?', (build('prototype')['artifacts_json'], bid))
    with state.action(app.state, bid) as current:
        assert bid in app.state.harness.active_builds
        with pytest.raises(RunError) as error:
            with state.action(app.state, bid):
                pytest.fail('Concurrent artifact edit entered')
        assert error.value.code == 'wrong_stage'
        state.save(app.state.db, bid, state.edited(current, 'context'))
        assert client.post(f'/api/builds/{bid}/versions').status_code == 409
    assert bid not in app.state.harness.active_builds
    response = client.get(f'/api/builds/{bid}').json()
    assert response['stage'] == 'context' and response['artifacts']['blueprint'] == 'stale'
    assert {name: (folder / name).read_bytes() for name in originals} == originals
    with pytest.raises(ValueError):
        with state.action(app.state, bid):
            raise ValueError('Failed write')
    assert bid not in app.state.harness.active_builds


@pytest.mark.parametrize('old_stage', ['interview', 'plan'])
def test_additive_migration_preserves_existing_builds_and_messages(tmp_path, old_stage):
    path = tmp_path / 'old.sqlite'
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute('CREATE TABLE builds (id TEXT PRIMARY KEY,title TEXT,archetype TEXT,mode TEXT,stage TEXT,'
                     'current_version INTEGER,created_at TEXT,updated_at TEXT,ready_for_plan INTEGER)')
        conn.execute('INSERT INTO builds VALUES(?,?,?,?,?,?,?,?,?)',
                     ('b_old', 'Old build', 'executive', 'data', old_stage, 1, 'created', 'updated', 1))
    db = Database(path)
    db.initialize()
    with db.connect() as conn:
        conn.execute("INSERT INTO messages VALUES('m_old','b_old','assistant','Keep this explanation',NULL,'created')")
        row = dict(conn.execute("SELECT * FROM builds WHERE id='b_old'").fetchone())
    assert row['stage'] == 'context' and row['notes'] is None
    assert row['ready_for_plan'] == 1 and row['title'] == 'Old build' and row['updated_at'] == 'updated'
    assert set(state.states(row).values()) == {'missing'}
    with db.connect() as conn:
        conn.execute("UPDATE builds SET notes='About these orders' WHERE id='b_old'")
    db.initialize()
    with db.connect() as conn:
        assert conn.execute('SELECT notes FROM builds').fetchone()[0] == 'About these orders'
        assert conn.execute('SELECT text FROM messages').fetchone()[0] == 'Keep this explanation'


@pytest.mark.parametrize('artifact', state.ARTIFACTS)
@pytest.mark.parametrize('value', ['draft', 'stale', 'missing'])
def test_recipe_run_versions_require_all_confirmed(thin, artifact, value):
    client, app, bid, folder = thin
    load_checked(client, bid)
    values = build('prototype', **{artifact: value})
    with app.state.db.connect() as conn:
        conn.execute('UPDATE builds SET artifacts_json=? WHERE id=?', (values['artifacts_json'], bid))
    for endpoint in ('recipe', 'run', 'versions'):
        response = client.post(f'/api/builds/{bid}/{endpoint}')
        assert response.status_code == 409 and response.json()['error']['code'] == 'wrong_stage'
    assert not app.state.engine_tasks and not app.state.engine_busy
    assert not (folder / 'recipe.jsonl').exists()


@pytest.mark.parametrize('legacy', [False, True])
def test_confirmed_and_legacy_builds_compile_run_and_carry_new_versions(thin, legacy):
    client, app, bid, folder = thin
    load_checked(client, bid)
    if not legacy:
        with app.state.db.connect() as conn:
            conn.execute('UPDATE builds SET artifacts_json=? WHERE id=?', (build('prototype')['artifacts_json'], bid))
    assert client.get(f'/api/builds/{bid}').json()['stage'] == 'prototype'
    assert client.post(f'/api/builds/{bid}/recipe').status_code == 200
    assert client.post(f'/api/builds/{bid}/run').status_code == 202
    assert wait_done(client, bid)['stage'] == 'done'
    from test_execute import settle
    settle(client, app)
    response = client.post(f'/api/builds/{bid}/versions')
    assert response.status_code == 201 and response.json()['current_version'] == 2
    assert set(response.json()['artifacts'].values()) == ({'missing'} if legacy else {'confirmed'})
    # Versioning carries the exemption; feasibility still requires a fresh proof.
    from fakes import ready_fixture
    ready_fixture(app, bid, folder.parent / 'v2')
    assert client.post(f'/api/builds/{bid}/recipe').status_code == 200


@pytest.mark.parametrize('action', ['interview', 'plan', 'spec'])
async def test_removed_graph_nodes_are_unreachable(client, app, build_id, monkeypatch, action):
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: pytest.fail('Removed node constructed a model'))
    with pytest.raises(RunError) as error:
        await app.state.harness.run(action, build_id, {'config': app.state.settings.get()})
    assert error.value.code == 'wrong_stage'
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT stage FROM builds WHERE id=?', (build_id,)).fetchone()[0] == 'connect'
