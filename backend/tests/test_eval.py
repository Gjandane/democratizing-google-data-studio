import json
from pathlib import Path

import pytest

from dss.harness.guardrails import RunError
from dss.ops.eval import evaluate
from fakes import FakeLLM


@pytest.fixture
def evaluation(app, build_id):
    config = app.state.settings.get()
    folder = config.data_dir / 'builds' / build_id / 'v1'
    (folder / 'docs').mkdir(parents=True)
    (folder / 'spec.json').write_text(Path('tests/data/thin_spec.json').read_text(), encoding='utf-8')
    (folder / 'docs/questions.md').write_text('---\ntype: Questions\n---\nHigh priority: total revenue?', encoding='utf-8')
    return app.state.db, config, build_id


@pytest.mark.parametrize('values,passed', [((3, 4, 5), True), ((5, 2, 3), False), ((1, 1, 1), False)])
async def test_scores_and_one_trace(evaluation, values, passed):
    scores = dict(zip(('question_coverage', 'catalog_fit', 'layout_balance'), values))
    fake = FakeLLM(response=json.dumps(scores))
    result = await evaluate(*evaluation, llm=fake)
    assert result == {**scores, 'pass': passed}
    assert fake.calls == 1
    with evaluation[0].connect() as conn:
        rows = conn.execute('SELECT * FROM traces').fetchall()
    assert len(rows) == 1 and rows[0]['status'] == 'ok' and rows[0]['model'] == 'fake-worker'
    span = json.loads(rows[0]['spans_json'])[0]
    assert span['scores'] == result and span['version'] == 1
    assert {s['name'] for s in span['sections']} >= {'questions.md', 'spec.json'}


@pytest.mark.parametrize('raw', ['bad json', '{}', '{"question_coverage":6,"catalog_fit":3,"layout_balance":3}',
    '{"question_coverage":true,"catalog_fit":3,"layout_balance":3}',
    '{"question_coverage":3,"catalog_fit":3,"layout_balance":3,"pass":true}', 'test-key'])
async def test_invalid_scores_one_failed_trace(evaluation, raw):
    with pytest.raises(RunError):
        await evaluate(*evaluation, llm=FakeLLM(response=raw))
    with evaluation[0].connect() as conn:
        rows = conn.execute('SELECT * FROM traces').fetchall()
    assert len(rows) == 1 and rows[0]['status'] == 'error'
    assert 'test-key' not in json.dumps(dict(rows[0]))


async def test_provider_failure_is_sanitized(evaluation, caplog):
    with pytest.raises(RunError):
        await evaluate(*evaluation, llm=FakeLLM(fail=True))
    assert 'provider error containing sensitive content' not in caplog.text


async def test_missing_build(evaluation):
    db, config, _ = evaluation
    with pytest.raises(RunError) as error:
        await evaluate(db, config, '../unknown', llm=FakeLLM())
    assert error.value.code == 'build_not_found'


async def test_current_version_and_worker_routing(evaluation, monkeypatch):
    from dss.harness.llm import ModelRouter
    db, config, bid = evaluation
    folder = config.data_dir / 'builds' / bid
    (folder / 'v2/docs').mkdir(parents=True)
    for name in ('spec.json', 'docs/questions.md'):
        (folder / 'v2' / name).write_bytes((folder / 'v1' / name).read_bytes())
    with db.connect() as conn:
        conn.execute('UPDATE builds SET current_version=2 WHERE id=?', (bid,))
    selected = []
    fake = FakeLLM(response='{"question_coverage":3,"catalog_fit":3,"layout_balance":3}')
    def model_for(self, node):
        selected.append(node)
        return fake
    monkeypatch.setattr(ModelRouter, 'llm_for', model_for)
    await evaluate(db, config, bid)
    assert selected == ['judge']
    with db.connect() as conn:
        span = json.loads(conn.execute('SELECT spans_json FROM traces').fetchone()[0])[0]
    assert span['version'] == 2


async def test_missing_questions_and_oversized_context_fail_before_model(evaluation):
    db, config, bid = evaluation
    path = config.data_dir / 'builds' / bid / 'v1/docs/questions.md'
    path.unlink()
    fake = FakeLLM()
    with pytest.raises(RunError):
        await evaluate(db, config, bid, llm=fake)
    path.write_text('x' * 64000, encoding='utf-8')
    with pytest.raises(RunError):
        await evaluate(db, config, bid, llm=fake)
    assert fake.calls == 0
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM traces WHERE status='error'").fetchone()[0] == 2
