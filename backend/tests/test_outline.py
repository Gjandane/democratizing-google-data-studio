"""Outline oracle: stable IDs, explicit intent, bounded single-shot calls and API gates."""
from copy import deepcopy
import json

import pytest

from dss.artifacts.models import Context, Outline
from dss.harness.context import outline_context
from dss.harness.nodes import outline as node
from dss.spec import requirements as req
from test_api_contract import FIXTURES, check
from test_context_node import context_api, ContextLLM, editable, example, wait


def question(text, refs=None, recommended=True):
    return {'text': text, 'rationale': 'Answers the business goal.', 'recommended': recommended,
            'kpi_refs': ['net_revenue'] if refs is None else refs}


def proposal(count=3):
    return {'sections': [{'title': f'Section {s}', 'purpose': 'Business questions', 'questions': [
        question(f'Question {s}-{q}') for q in range(3)]} for s in range(count)]}


@pytest.fixture
def outline_api(context_api, monkeypatch):
    client, app, bid, sid, folder, bq = context_api
    context_llm = ContextLLM(replies=[json.dumps(example(sid))])
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: context_llm)
    assert client.post(f'/api/builds/{bid}/context').status_code == 202
    wait(app)
    assert client.get(f'/api/builds/{bid}/context').json()['issues'] == []
    llm = ContextLLM(replies=[json.dumps(proposal())])
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: llm)
    response = client.post(f'/api/builds/{bid}/context/confirm')
    assert response.status_code == 202, response.text
    wait(app)
    assert client.get(f'/api/builds/{bid}/outline').json() is not None
    return client, app, bid, sid, folder, llm


def response_next(llm, value):
    llm.replies.append(json.dumps(value))


def questions(outline):
    return [q for s in outline['sections'] for q in s['questions']]


def test_proposal_normalization_stable_ids_and_reconfirm(outline_api, monkeypatch):
    client, app, bid, sid, folder, llm = outline_api
    url = f'/api/builds/{bid}'
    first = client.get(url + '/outline').json()
    assert 3 <= len(first['sections']) <= 5
    assert all(3 <= len(s['questions']) <= 6 for s in first['sections'])
    assert all(q['selected'] == q['recommended'] for q in questions(first))
    fixture = json.loads((FIXTURES / 'outline.json').read_text(encoding='utf-8'))
    assert first.keys() == fixture.keys()
    assert first['sections'][0].keys() == fixture['sections'][0].keys()
    assert questions(first)[0].keys() == questions(fixture)[0].keys()
    assert Outline.model_validate(first).model_dump(mode='json') == first
    selected = questions(first)[0]
    chosen = client.put(url + '/outline/selection', json={'questions': [{'id': selected['id'], 'selected': False}]})
    assert chosen.status_code == 200 and llm.calls == 1
    assert client.put(url + '/context', json=editable(example(sid))).status_code == 200
    def no_model(_):
        raise AssertionError('Code revalidation must not construct a model')
    monkeypatch.setattr(app.state.models, 'llm_for', no_model)
    accepted = client.post(url + '/context/confirm')
    wait(app)
    current = client.get(url + '/outline').json()
    assert questions(current) == questions(chosen.json()) and llm.calls == 1
    with app.state.db.connect() as conn:
        traces = conn.execute('SELECT * FROM traces WHERE run_id=?', (accepted.json()['run_id'],)).fetchall()
    assert len(traces) == 1 and traces[0]['status'] == 'ok'
    assert traces[0]['input_tokens'] == 0 and traces[0]['output_tokens'] == 0
    assert (folder / 'docs/outline.md').is_file()


def test_suggest_other_repropose_preserves_choices_and_ids(outline_api):
    client, app, bid, sid, folder, llm = outline_api
    url = f'/api/builds/{bid}/outline'
    first = client.get(url).json()
    s1 = first['sections'][0]['id']
    response_next(llm, {'questions': [question('Extra insight'), question('  QUESTION 0-0  ')]})
    assert client.post(url + '/suggest', json={'section_id': s1}).status_code == 202
    wait(app)
    second = client.get(url).json()
    extra = next(q for q in questions(second) if q['text'] == 'Extra insight')
    assert not extra['selected'] and extra['origin'] == 'suggested'
    assert len(questions(second)) == 10
    # Source IDs are server-owned; the fake reads this action's new source, never history.
    original = llm.generate_content_async
    async def extract(request, stream=False):
        if 'outline_other' in str(request.config.system_instruction):
            with app.state.db.connect() as conn:
                mid = conn.execute("SELECT id FROM messages WHERE node='outline_other' AND role='user' ORDER BY rowid DESC").fetchone()[0]
            llm.replies[llm.calls] = json.dumps({'questions': [question('Animate the GPS points', [])],
                'requirements': [{'source_id': mid, 'text': 'Animate the GPS points',
                                  'needs': [{'capability': 'animation.temporal_playback'}]}]})
        async for r in original(request, stream):
            yield r
    # Pydantic model methods are patched on the class.
    from unittest.mock import patch
    response_next(llm, {})
    with patch.object(ContextLLM, 'generate_content_async', lambda self, request, stream=False: extract(request, stream)):
        accepted = client.post(url + '/other', json={'section_id': s1, 'text': 'Animate the GPS points'})
        assert accepted.status_code == 202
        wait(app)
    third = client.get(url).json()
    other = next(q for q in questions(third) if q['origin'] == 'other')
    assert other['selected']
    ledger = req.load(folder)
    assert ledger.assessment.state == 'blocked'
    assert any(n.capability == 'animation.temporal_playback' for r in ledger.requirements for n in r.needs)
    messages = client.get(f'/api/builds/{bid}/messages').json()
    assert 'Feasibility needs attention' in messages[-1]['text']
    assert messages[-2]['role'] == 'user' and messages[-2]['text'] == 'Animate the GPS points'
    # Both explicit deselections must survive Context re-confirm and re-propose.
    generated = questions(third)[1]
    selected = client.put(url + '/selection', json={'questions': [
        {'id': other['id'], 'selected': False}, {'id': generated['id'], 'selected': False}]}).json()
    other = next(q for q in questions(selected) if q['id'] == other['id'])
    assert client.put(f'/api/builds/{bid}/context', json=editable(example(sid))).status_code == 200
    assert client.post(f'/api/builds/{bid}/context/confirm').status_code == 202
    wait(app)
    assert questions(client.get(url).json()) == questions(selected)
    changed = proposal()
    changed['sections'][0]['questions'][0]['text'] = 'Replacement question'
    response_next(llm, changed)
    assert client.post(url + '/propose').status_code == 202
    wait(app)
    fourth = client.get(url).json()
    kept = next(q for q in questions(fourth) if q['id'] == other['id'])
    assert kept == other
    assert next(q for q in questions(fourth) if q['id'] == generated['id'])['selected'] is False
    ids_before = {q['text']: q['id'] for q in questions(third)}
    assert all(q['id'] == ids_before[q['text']] for q in questions(fourth) if q['text'] in ids_before)
    replacement = next(q for q in questions(fourth) if q['text'] == 'Replacement question')
    assert int(replacement['id'][1:]) > max(int(q['id'][1:]) for q in questions(third))
    assert llm.calls == 4
    for request in llm.seen:
        assert len(request.contents) == 1
        assert request.config.max_output_tokens in (2000, 3000)
    with app.state.db.connect() as conn:
        traces = conn.execute("SELECT * FROM traces WHERE node LIKE 'outline_%'").fetchall()
    assert len(traces) == 5 and all(t['status'] == 'ok' for t in traces)


def test_ratio_unknown_refs_duplicate_and_selection_survive(tmp_path):
    ctx = Context.model_validate(example())
    draft = proposal()
    draft['sections'][0]['questions'][0] = question('Ratio only', ['avg_order_value'])
    draft['sections'][0]['questions'][1] = question('Missing KPI', ['not_real', 'net_revenue'])
    draft['sections'][1]['questions'][0] = question('  ratio    ONLY ')
    result = node.compose(tmp_path / 'v1', None, ctx, node.Proposal.model_validate(draft), 'outline_propose')
    qs = questions(result.model_dump())
    assert len(qs) == 8
    assert qs[0]['recommended'] is False and qs[0]['selected'] is False and 'Ratio KPI' in qs[0]['rationale']
    assert qs[1]['kpi_refs'] == ['net_revenue'] and 'not_real' in qs[1]['rationale']
    result.sections[0].questions[0].selected = True
    ctx.kpis = []
    rechecked = node.revalidate(result, ctx)
    assert rechecked.sections[0].questions[0].selected
    assert not rechecked.sections[0].questions[0].kpi_refs
    assert node.revalidate(rechecked, ctx) == rechecked


def test_confirmation_limits_and_later_edit(outline_api):
    client, app, bid, sid, folder, llm = outline_api
    url = f'/api/builds/{bid}/outline'
    first = client.get(url).json()
    assert client.put(url + '/selection', json={'questions': [{'id': q['id'], 'selected': False} for q in questions(first)]}).status_code == 200
    rejected = client.post(url + '/confirm')
    assert rejected.status_code == 409 and rejected.json()['error']['code'] == 'artifact_invalid'
    qid = questions(first)[0]['id']
    assert client.put(url + '/selection', json={'questions': [{'id': qid, 'selected': True}]}).status_code == 200
    confirmed = client.post(url + '/confirm')
    assert confirmed.status_code == 200 and confirmed.json()['stage'] == 'design'
    assert confirmed.json()['artifacts']['outline'] == 'confirmed'
    # A later edit returns to Outline and invalidates downstream states.
    edited = client.put(url + '/selection', json={'questions': [{'id': qid, 'selected': False}]})
    assert edited.status_code == 200
    assert client.get(f'/api/builds/{bid}').json()['stage'] == 'outline'
    assert llm.calls == 1
    # 25 selected questions can be generated but cannot be confirmed.
    large = proposal(5)
    for i, s in enumerate(large['sections']):
        s['questions'] += [question(f'Extra {i}-{j}') for j in range(2)]
    response_next(llm, large)
    assert client.post(url + '/propose').status_code == 202
    wait(app)
    latest = client.get(url).json()
    client.put(url + '/selection', json={'questions': [{'id': q['id'], 'selected': True} for q in questions(latest)]})
    rejected = client.post(url + '/confirm')
    assert rejected.status_code == 409 and rejected.json()['error']['code'] == 'artifact_invalid'


def test_invalid_inputs_locks_and_no_repair(outline_api):
    client, app, bid, sid, folder, llm = outline_api
    url = f'/api/builds/{bid}/outline'
    for body in ({'questions': []}, {'questions': [{'id': 'missing', 'selected': True}]},
                 {'questions': [{'id': 'q1', 'selected': 'true'}]},
                 {'questions': [{'id': 'q1', 'selected': True}] * 2}):
        assert client.put(url + '/selection', json=body).status_code == 422
    for body in ({'section_id': 'missing'}, {'section_id': None}):
        assert client.post(url + '/suggest', json=body).status_code == 422
    for text in ('', ' ', 'x' * 1001):
        assert client.post(url + '/other', json={'section_id': None, 'text': text}).status_code == 422
    app.state.harness.active_builds.add(bid)
    assert client.post(url + '/propose').status_code == 409
    app.state.harness.active_builds.discard(bid)
    before = (folder / 'docs/outline.md').read_bytes()
    response_next(llm, {'sections': []})
    accepted = client.post(url + '/propose')
    wait(app)
    assert llm.calls == 2 and (folder / 'docs/outline.md').read_bytes() == before
    with app.state.db.connect() as conn:
        trace = conn.execute('SELECT * FROM traces WHERE run_id=?', (accepted.json()['run_id'],)).fetchone()
    assert trace['status'] == 'error'
    for stage in ('build', 'done', 'context'):
        with app.state.db.connect() as conn:
            conn.execute('UPDATE builds SET stage=? WHERE id=?', (stage, bid))
        assert client.post(url + '/propose').status_code == 409
        assert client.post(url + '/other', json={'section_id': None, 'text': 'Revenue'}).status_code == 409
        assert client.put(url + '/selection', json={'questions': [{'id': 'q1', 'selected': True}]}).status_code == 409


def test_prompt_only_artifacts_fields_and_bounded_facts(tmp_path, monkeypatch):
    from dss.harness import context as working
    from dss.harness.context import Section
    monkeypatch.setattr(working, '_user_facts', lambda _: [Section('semantic', 'facts', body='f' * 5000)])
    source = {'id': 's1', 'columns': [{'name': 'revenue', 'type': 'number', 'sample': ['PRIVATE_SAMPLE']}],
              'rows': ['PRIVATE_ROWS']}
    memory = outline_context(None, Context.model_validate(example()), [source], 'executive', 'outline_propose')
    assert 'PRIVATE_' not in memory
    assert len(next(s.body for s in memory.sections if s.name == 'user-facts').encode('utf-8')) <= 500
    assert not any(s.kind in ('past', 'history') for s in memory.sections)


def test_over_budget_makes_no_generation_and_preserves_outline(outline_api, monkeypatch):
    client, app, bid, sid, folder, llm = outline_api
    before = (folder / 'docs/outline.md').read_bytes()
    async def count(self, request):
        return 9000
    monkeypatch.setattr(ContextLLM, 'count_request_tokens', count, raising=False)
    accepted = client.post(f'/api/builds/{bid}/outline/propose')
    assert accepted.status_code == 202
    wait(app)
    assert llm.calls == 1 and (folder / 'docs/outline.md').read_bytes() == before
    with app.state.db.connect() as conn:
        trace = conn.execute('SELECT * FROM traces WHERE run_id=?', (accepted.json()['run_id'],)).fetchone()
    spans = json.loads(trace['spans_json'])
    assert trace['status'] == 'error'
    span = next(s for s in spans if 'enforced_input_bound' in s)
    assert span['folded_request_tokens'] == 9000 and span['enforced_input_bound'] > 8000


def test_other_new_section_and_invalid_extraction_do_not_publish(outline_api):
    client, app, bid, sid, folder, llm = outline_api
    before = (folder / 'docs/outline.md').read_bytes()
    response_next(llm, {'questions': [question('New user question')], 'requirements': [
        {'source_id': 'spoofed', 'text': 'New user question', 'needs': []}]})
    assert client.post(f'/api/builds/{bid}/outline/other', json={'section_id': None, 'text': 'New user question'}).status_code == 202
    wait(app)
    assert llm.calls == 2 and (folder / 'docs/outline.md').read_bytes() == before
    assert not (folder / 'requirements.json').is_file()
    # A valid empty extraction still preserves the unclassified request as a blocked row.
    response_next(llm, {'questions': [question('New user question')], 'requirements': []})
    assert client.post(f'/api/builds/{bid}/outline/other', json={'section_id': None, 'text': 'New user question'}).status_code == 202
    wait(app)
    latest = client.get(f'/api/builds/{bid}/outline').json()
    assert len(latest['sections']) == 4
    assert latest['sections'][-1]['questions'][0]['origin'] == 'other'
    assert latest['sections'][-1]['questions'][0]['selected']
    assert req.load(folder).assessment.state == 'blocked'


def test_other_duplicate_promotes_existing_stable_question(outline_api):
    client, app, bid, sid, folder, llm = outline_api
    url = f'/api/builds/{bid}/outline'
    first = questions(client.get(url).json())[0]
    client.put(url + '/selection', json={'questions': [{'id': first['id'], 'selected': False}]})
    response_next(llm, {'questions': [question('  QUESTION   0-0  ')], 'requirements': []})
    client.post(url + '/other', json={'section_id': None, 'text': 'Question 0-0'})
    wait(app)
    latest = questions(client.get(url).json())
    assert len(latest) == 9
    assert len(client.get(url).json()['sections']) == 3
    promoted = next(q for q in latest if q['id'] == first['id'])
    assert promoted['selected'] and promoted['origin'] == 'other'
    changed = proposal()
    changed['sections'][0]['questions'][0]['text'] = 'Replacement question'
    response_next(llm, changed)
    client.post(url + '/propose')
    wait(app)
    assert promoted in questions(client.get(url).json())


def test_other_publication_failure_preserves_bundle(outline_api, monkeypatch):
    client, app, bid, sid, folder, llm = outline_api
    paths = [folder / 'requirements.json', *[folder / 'docs' / name for name in
             ('outline.md', 'feasibility.md', 'index.md', 'log.md')]]
    before = {p: p.read_bytes() if p.is_file() else None for p in paths}
    async def fail(*args, **kwargs):
        raise OSError('Simulated artifact write failure')
    monkeypatch.setattr(node, 'write_artifact', fail)
    response_next(llm, {'questions': [question('New user question')], 'requirements': []})
    client.post(f'/api/builds/{bid}/outline/other', json={'section_id': None, 'text': 'New user question'})
    wait(app)
    assert {p: p.read_bytes() if p.is_file() else None for p in paths} == before
    assert llm.calls == 2


@pytest.mark.parametrize('overflow', ['input', 'output', 'rows', 'cumulative'])
def test_other_scope_overflow_is_durably_blocked(outline_api, monkeypatch, overflow):
    client, app, bid, sid, folder, llm = outline_api
    before = (folder / 'docs/outline.md').read_bytes()
    if overflow == 'cumulative':
        req.save(folder, req.Ledger(requirements=[req.Requirement(id=f'req_{i}', text=f'Old request {i}',
            source=req.Source(id=f'old_{i}', kind='message', text=f'Old request {i}')) for i in range(40)]))
    value = {'questions': [question('New question')], 'requirements': []}
    response_next(llm, value)
    original = ContextLLM.generate_content_async
    async def generate(self, request, stream=False):
        if overflow == 'output':
            from google.adk.models.llm_response import LlmResponse
            from google.genai import types
            self.calls += 1
            yield LlmResponse(error_code='MAX_TOKENS', finish_reason=types.FinishReason.MAX_TOKENS)
            return
        if overflow in ('rows', 'cumulative'):
            with app.state.db.connect() as conn:
                mid = conn.execute("SELECT id FROM messages WHERE node='outline_other' AND role='user' ORDER BY rowid DESC").fetchone()[0]
            value['requirements'] = [{'source_id': mid, 'text': f'New request {i}', 'needs': []}
                                     for i in range(41 if overflow == 'rows' else 1)]
            llm.replies[llm.calls] = json.dumps(value)
        async for result in original(self, request, stream):
            yield result
    monkeypatch.setattr(ContextLLM, 'generate_content_async', generate)
    if overflow == 'input':
        async def count(self, request):
            return 9000
        monkeypatch.setattr(ContextLLM, 'count_request_tokens', count, raising=False)
    response = client.post(f'/api/builds/{bid}/outline/other', json={'section_id': None, 'text': 'New question'})
    assert response.status_code == 202
    wait(app)
    assert (folder / 'docs/outline.md').read_bytes() == before
    ledger = req.load(folder)
    assert ledger.scope_error == node.SCOPE_MESSAGE and ledger.assessment.state == 'blocked'
    assessment = client.get(f'/api/builds/{bid}/feasibility').json()
    assert assessment['state'] == 'blocked'
    assert node.SCOPE_MESSAGE in client.get(f'/api/builds/{bid}/messages').json()[-1]['text']
    assert llm.calls == (1 if overflow == 'input' else 2)
    if overflow == 'cumulative':
        assert len(ledger.requirements) == 40


def test_repropose_duplicate_section_titles_keep_unique_ids(tmp_path):
    folder = tmp_path / 'v1'
    context = Context.model_validate(example())
    first = node.compose(folder, None, context, node.Proposal.model_validate(proposal()), 'outline_propose')
    draft = proposal()
    draft['sections'][1]['title'] = draft['sections'][0]['title']
    second = node.compose(folder, first, context, node.Proposal.model_validate(draft), 'outline_propose')
    assert len({s.id for s in second.sections}) == len(second.sections)
