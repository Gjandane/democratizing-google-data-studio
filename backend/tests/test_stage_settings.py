"""Stage Settings 3.0: contract, validation, atomic merge and one-time migration."""
import json
from copy import deepcopy
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from dss.config import Config, SettingsStore
from dss.db import Database
from dss.harness import stages
from dss.main import create_app
from fakes import fake_models

FIXTURES = Path(__file__).resolve().parents[2] / 'contracts/fixtures/stage-settings'


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


def test_stage_defaults_and_capabilities(client):
    settings = client.get('/api/settings').json()
    expected = fixture('settings.json')
    assert settings['stages'] == expected['stages']
    assert settings.keys() == expected.keys()
    capabilities = client.get('/api/settings/capabilities')
    assert capabilities.status_code == 200
    assert capabilities.json()['defaults'] == fixture('capabilities.json')['defaults']
    assert capabilities.json()['limits'] == fixture('capabilities.json')['limits']


def same_shape(actual, expected):
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            same_shape(actual[key], expected[key])
    elif isinstance(expected, list):
        assert isinstance(actual, list)
        if expected:
            for value in actual:
                same_shape(value, expected[0])
    else:
        assert type(actual) is type(expected)


def rows(db):
    with db.connect() as conn:
        return dict(conn.execute('SELECT key,value FROM settings').fetchall())


def store(tmp_path, **config):
    db = Database(tmp_path / 'settings.sqlite')
    db.initialize()
    return SettingsStore(Config(data_dir=tmp_path, **config), db)


def test_contract_shapes_and_verified_prices(client):
    same_shape(client.get('/api/settings').json(), fixture('settings.json'))
    same_shape(client.put('/api/settings', json={'review_briefs': True}).json(), fixture('settings.json'))
    response = client.get('/api/settings/capabilities').json()
    example = fixture('capabilities.json')
    assert response.keys() == example.keys()
    same_shape(response['defaults'], example['defaults'])
    same_shape(response['limits'], example['limits'])
    for model in response['models']:
        assert model.keys() == example['models'][0].keys()
        assert model['available'] is None or type(model['available']) is bool
        assert type(model['max_input_tokens']) is int
        assert type(model['max_output_tokens']) is int
        assert type(model['images']) is bool
        assert model['thinking_levels'] == ['low', 'medium', 'high']
        if model['price'] is not None:
            same_shape(model['price'], example['models'][0]['price'])
            assert model['price']['checked_on'] == '2026-10-26'
            assert model['price']['input_usd_per_mtok'] > 0
            assert model['price']['output_usd_per_mtok'] > 0
    # Independently checked Standard rates, not the shape-only sample fixture's prices.
    prices = {m['id']: m['price'] for m in response['models']}
    assert prices[stages.FLASH]['input_usd_per_mtok'] == 0.75
    assert prices[stages.FLASH]['output_usd_per_mtok'] == 3.75
    assert prices[stages.ARGON]['input_usd_per_mtok'] == 2.0
    assert prices[stages.ARGON]['output_usd_per_mtok'] == 10.0


REJECTS = [
    ({'fallback_model': 'unknown-secret'}, '/fallback_model'),
    ({'fallback_model': []}, '/fallback_model'),
    ({'review_briefs': 'true'}, '/review_briefs'),
    ({'stages': None}, '/stages'),
    ({'stages': {'bad/stage': {}}}, '/stages/bad~1stage'),
    ({'planner_model': 'unknown-secret'}, '/planner_model'),
    ({'google_api_key': None}, '/google_api_key'),
    ({'gcp_project_id': 1}, '/gcp_project_id'),
]
for stage, profile in stages.defaults()['stages'].items():
    invalid = [('model', 'unknown-secret'), ('model', []), ('thinking', 'minimal'),
               ('timeout_s', 29 if stage in stages.GENERATIONS else 9),
               ('timeout_s', 3601 if stage in stages.GENERATIONS else 601),
               ('timeout_s', True), ('unexpected', 1)]
    if stage in stages.GENERATIONS:
        for field, bad_values in {
            'input_tokens': [1023, 1048577, 1024.5, True],
            'output_tokens': [255, 65537, '256'],
            'transport_retries': [-1, 6], 'input_margin_pct': [-1, 101],
            'validation_repairs': [-1, stages.LIMITS['validation_repairs'][stage][1] + 1],
        }.items():
            invalid.extend((field, value) for value in bad_values)
    else:
        invalid.append(('input_tokens', 1024))
    if stage == 'html_no_reference':
        invalid.append(('layout_fallback', 1))
    else:
        invalid.append(('layout_fallback', True))
    REJECTS += [({'stages': {stage: {field: value}}}, f'/stages/{stage}/{field}') for field, value in invalid]
    REJECTS.append(({'stages': {stage: None}}, '/stages/' + stage))


@pytest.mark.parametrize('update,path', REJECTS)
def test_rejected_update_is_atomic_with_field_path(client, app, update, path):
    before = rows(app.state.db)
    response = client.put('/api/settings', json={**update, 'bq_location': 'EU'})
    assert response.status_code == 422, response.text
    error = response.json()
    same_shape(error, fixture('error.invalid_settings.json'))
    assert path in [i['path'] for i in error['error']['detail']['issues']]
    assert 'unknown-secret' not in response.text
    assert rows(app.state.db) == before


def test_partial_fields_merge_and_independent_profiles(client, app):
    before = client.get('/api/settings').json()
    response = client.put('/api/settings', json={'stages': {'html_brief': {'timeout_s': 333},
                                                          'routine': {'thinking': 'high'}},
                                                'review_briefs': True})
    assert response.status_code == 200, response.text
    expected = deepcopy(before)
    expected['stages']['html_brief']['timeout_s'] = 333
    expected['stages']['routine']['thinking'] = 'high'
    expected['review_briefs'] = True
    assert response.json() == expected
    assert client.put('/api/settings', json={'gcp_project_id': 'project'}).json()['stages'] == expected['stages']
    assert json.loads(rows(app.state.db)['stages']) == expected['stages']


@pytest.mark.parametrize('stage', stages.GENERATIONS)
def test_generation_boundaries(client, stage):
    lo, hi = stages.LIMITS['validation_repairs'][stage]
    for repairs, tokens, timeout, retries, margin in ((lo, 1024, 30, 0, 0), (hi, 1048576, 3600, 5, 100)):
        response = client.put('/api/settings', json={'stages': {stage: {
            'validation_repairs': repairs, 'input_tokens': tokens,
            'output_tokens': 256 if margin == 0 else 65536, 'timeout_s': timeout,
            'transport_retries': retries, 'input_margin_pct': margin}}})
        assert response.status_code == 200, response.text


@pytest.mark.parametrize('role,model', [('planner_model', stages.ARGON), ('worker_model', stages.FLASH),
                                      ('planner_model', stages.FLASH), ('worker_model', stages.ARGON),
                                      ('planner_model', 'unknown-secret'), ('worker_model', 'unknown-secret')])
def test_stored_explicit_migration_includes_default_equal_and_unknown(tmp_path, role, model, caplog):
    settings = store(tmp_path)
    with settings.db.connect() as conn:
        conn.execute('INSERT INTO settings VALUES(?,?)', (role, model))
    first = settings.get().public()
    assert len(first['notices']) == len(stages.LEGACY_ROLES[role])
    for stage, profile in first['stages'].items():
        assert profile['model'] == (model if stage in stages.LEGACY_ROLES[role] else stages.defaults()['stages'][stage]['model'])
    if model == 'unknown-secret':
        assert {i['path'] for i in first['issues']} == {'/stages/' + s + '/model' for s in stages.LEGACY_ROLES[role]}
        assert 'unknown-secret' not in str(first['notices']) + caplog.text
        assert settings.update({'bq_location': 'EU'}).public()['issues'] == first['issues']
        assert settings.update({'stages': {'routine': {'timeout_s': 25}}}).stages['routine']['timeout_s'] == 25
        first['stages']['routine']['timeout_s'] = 25
    before = rows(settings.db)
    assert settings.get().public()['stages'] == first['stages']
    restarted = SettingsStore(Config(data_dir=tmp_path, planner_model='different-after-restart'), settings.db)
    assert restarted.get().public()['stages'] == first['stages']
    assert rows(settings.db) == before


@pytest.mark.parametrize('role', stages.LEGACY_ROLES)
@pytest.mark.parametrize('different', [False, True])
def test_env_migration_only_seeds_nondefault_values(tmp_path, monkeypatch, role, different):
    # Exercise actual env resolution without opening or exposing root .env values.
    monkeypatch.setattr('dss.config.dotenv_values', lambda _: {})
    for name in ('DSS_PLANNER_MODEL', 'DSS_WORKER_MODEL', 'DSS_ENGINE_MODE', 'DSS_DATA_DIR', 'DSS_DB_PATH'):
        monkeypatch.delenv(name, raising=False)
    chosen = 'unknown-secret' if different else stages.LEGACY_DEFAULTS[role]
    monkeypatch.setenv('DSS_PLANNER_MODEL' if role == 'planner_model' else 'DSS_WORKER_MODEL', chosen)
    config = Config.from_env().model_copy(update={'data_dir': tmp_path})
    settings = store(tmp_path)
    settings.defaults = config
    result = settings.get().public()
    assert len(result['notices']) == (len(stages.LEGACY_ROLES[role]) if different else 0)
    if not different:
        assert result['stages'] == stages.defaults()['stages']


def test_migration_none_and_both_stored_values_override_env(tmp_path):
    settings = store(tmp_path, planner_model=stages.FLASH, worker_model=stages.ARGON)
    with settings.db.connect() as conn:
        conn.executemany('INSERT INTO settings VALUES(?,?)', stages.LEGACY_DEFAULTS.items())
    result = settings.get().public()
    for role, names in stages.LEGACY_ROLES.items():
        assert all(result['stages'][s]['model'] == stages.LEGACY_DEFAULTS[role] for s in names)
    assert len(result['notices']) == 7


@pytest.mark.parametrize('stage', list(stages.IMAGE_STAGES))
def test_image_capability_rules_and_fallback(client, monkeypatch, stage):
    # A future code-owned text-only model exercises the rule, independently of listing.
    text = {**deepcopy(stages.MODELS[stages.ARGON]), 'id': 'text-only', 'images': False}
    monkeypatch.setitem(stages.MODELS, 'text-only', text)
    response = client.put('/api/settings', json={'stages': {stage: {'model': 'text-only'}}})
    assert response.status_code == 422
    assert f'/stages/{stage}/model' in [i['path'] for i in response.json()['error']['detail']['issues']]
    response = client.put('/api/settings', json={'fallback_model': 'text-only'})
    assert response.status_code == 422
    assert '/fallback_model' in [i['path'] for i in response.json()['error']['detail']['issues']]


@pytest.mark.parametrize('capability,path', [('thinking_levels', 'thinking'),
                                         ('max_input_tokens', 'input_tokens'),
                                         ('max_output_tokens', 'output_tokens')])
def test_fallback_must_cover_each_profile(client, monkeypatch, capability, path):
    small = {**deepcopy(stages.MODELS[stages.FLASH]), 'id': 'small'}
    small[capability] = ['low'] if capability == 'thinking_levels' else 1024
    monkeypatch.setitem(stages.MODELS, 'small', small)
    response = client.put('/api/settings', json={'fallback_model': 'small'})
    assert response.status_code == 422
    assert f'/stages/html_brief/{path}' in [i['path'] for i in response.json()['error']['detail']['issues']]


def test_listing_failure_is_unknown_and_recovers(client, app):
    async def missing(key):
        return ['models/' + stages.FLASH]
    app.state.models.model_lister = missing
    assert client.put('/api/settings', json={}).status_code == 200
    models = client.get('/api/settings/capabilities').json()['models']
    assert {m['id']: m['available'] for m in models} == {stages.FLASH: True, stages.ARGON: False}
    # Availability does not decide validity.
    assert client.put('/api/settings', json={'stages': {'html_brief': {'model': stages.ARGON}}}).status_code == 200
    async def broken(key):
        raise RuntimeError('provider-secret')
    app.state.models.model_lister = broken
    assert client.put('/api/settings', json={}).status_code == 200
    assert all(m['available'] is None for m in client.get('/api/settings/capabilities').json()['models'])
    client.put('/api/settings', json={'google_api_key': ''})
    assert all(m['available'] is None for m in client.get('/api/settings/capabilities').json()['models'])


@pytest.mark.parametrize('field,value', [('timeout_s', 0), ('transport_retries', 6),
                                       ('validation_repairs', 6), ('input_margin_pct', 101),
                                       ('old_field', True)])
def test_model_change_keeps_unrelated_stored_issues(client, app, field, value):
    current = client.get('/api/settings').json()['stages']
    current['html_brief'][field] = value
    with app.state.db.connect() as conn:
        conn.execute("UPDATE settings SET value=? WHERE key='stages'", (json.dumps(current),))
    issue = {'path': '/stages/html_brief/' + field}
    before = client.get('/api/settings').json()['issues']
    assert any(i['path'] == issue['path'] for i in before)
    response = client.put('/api/settings', json={'stages': {'html_brief': {'model': stages.FLASH}}})
    assert response.status_code == 200, response.text
    assert response.json()['issues'] == before
    assert response.json()['stages']['html_brief'][field] == value
    # Explicitly touching the same bad field must still reject without writes.
    saved = rows(app.state.db)
    response = client.put('/api/settings', json={'stages': {'html_brief': {field: value}}})
    assert response.status_code == 422
    assert rows(app.state.db) == saved


def test_agent_stage_settings_and_locked_deployment_fields(tmp_path):
    app = create_app(Config(data_dir=tmp_path, engine_mode='agent', google_api_key='key'), model_lister=fake_models)
    with TestClient(app) as client:
        for key in ('google_api_key', 'gcp_project_id', 'bq_dataset', 'bq_location', 'gcs_bucket'):
            before = rows(app.state.db)
            response = client.put('/api/settings', json={key: 'changed', 'review_briefs': True})
            assert response.status_code == 403 and response.json()['error']['code'] == 'settings_locked'
            assert rows(app.state.db) == before
        response = client.put('/api/settings', json={'review_briefs': True, 'fallback_model': stages.ARGON,
                                                     'stages': {'interview': {'thinking': 'high'}}})
        assert response.status_code == 200, response.text
        assert response.json()['review_briefs'] is True
        assert response.json()['stages']['interview']['thinking'] == 'high'


def test_explicit_empty_unknown_stage_is_not_grandfathered(client, app):
    current = client.get('/api/settings').json()['stages']
    current['old-stage'] = {}
    with app.state.db.connect() as conn:
        conn.execute("UPDATE settings SET value=? WHERE key='stages'", (json.dumps(current),))
    assert client.put('/api/settings', json={'bq_location': 'EU'}).status_code == 200
    saved = rows(app.state.db)
    response = client.put('/api/settings', json={'stages': {'old-stage': {}}})
    assert response.status_code == 422
    assert '/stages/old-stage' in [i['path'] for i in response.json()['error']['detail']['issues']]
    assert rows(app.state.db) == saved
