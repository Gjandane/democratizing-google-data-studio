"""Persisted page review, exact reviewed inputs, idempotency and atomic publication."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dss.harness.nodes import reference_brief as rb
from dss.memory import episodic
from dss.spec import publication
from test_blueprint import blueprint_api  # noqa: F401
from test_context_node import context_api  # noqa: F401
from test_designer import DesignerLLM, ReferenceHTMLLLM, designed_flow
from test_reference_brief import BriefLLM, reference_set, section
from test_revise import setup, designed  # noqa: F401


def drain(client, app):
    async def wait():
        async with asyncio.timeout(60):
            while app.state.engine_tasks:
                await asyncio.sleep(.01)
    client.portal.call(wait)


def events(app, bid):
    with app.state.db.connect() as conn:
        return [(r['kind'], json.loads(r['payload_json'])) for r in conn.execute(
            'SELECT * FROM events WHERE build_id=? ORDER BY rowid', (bid,))]


def pending(client, bid):
    return client.get(f'/api/builds/{bid}/design-pages').json()['review']


def approve(client, bid, review):
    return client.post(f'/api/builds/{bid}/briefs/review/approve', json={
        'review_id': review['review_id'], 'revision': review['revision'], 'sha256': review['brief']['sha256']})


def edit(client, bid, review, value):
    return client.put(f'/api/builds/{bid}/briefs/review', json={
        'review_id': review['review_id'], 'revision': review['revision'], 'brief': value})


@pytest.fixture
def brief_api(blueprint_api, monkeypatch, request):
    client, app, bid, _, folder, service, _, _ = blueprint_api
    app.state.settings.update({'review_briefs': True})
    if getattr(request, 'param', False):
        from dss.spec import references
        reference_set(folder, count=1)
        ref = references.load(folder)
        ref['instructions'] = ''
        (folder / references.SET_FILE).write_text(json.dumps(ref), encoding='utf-8')
    brief, html = BriefLLM(), ReferenceHTMLLLM()
    client, app, bid, folder, run_id = designed_flow(blueprint_api, monkeypatch, html,
        reference_models={'reference_brief': brief, 'reference_html': html})
    review = pending(client, bid)
    assert review is not None, events(app, bid)
    return client, app, bid, folder, run_id, brief, html, service


@pytest.mark.parametrize('brief_api', [False, True], indirect=True)
def test_accept_pauses_finishes_ok_releases_lock_and_reviews_pages_in_order(brief_api):
    client, app, bid, folder, run_id, brief, html, service = brief_api
    first = pending(client, bid)
    assert first['page'] == 1 and first['pages'] == 2 and first['revision'] == 1
    assert not html.calls and len(brief.requests) == 1 and not html.active
    assert bid not in app.state.harness.active_builds
    assert client.get(f'/api/builds/{bid}').json()['stage'] == 'blueprint'
    assert not (folder / 'prototype.html').exists()
    assert [p for k, p in events(app, bid) if k == 'run.finished' and p['run_id'] == run_id] == [
        {'run_id': run_id, 'node': 'prototype', 'status': 'ok', 'error': None}]
    saved = episodic.brief_review(app.state.db, bid)['record']
    assert Path(saved['folder']).is_dir()
    result = approve(client, bid, first)
    assert result.status_code == 202, result.text
    drain(client, app)
    assert approve(client, bid, first).json() == result.json()
    second = pending(client, bid)
    assert second['page'] == 2 and second['review_id'] != first['review_id']
    assert html.calls == html.closed == 1 and len(brief.requests) == 2
    saved = episodic.brief_review(app.state.db, bid)['record']
    assert saved['state']['results']['1']['designed']['width'] == 1440
    assert saved['state']['html_inputs']['first']['css']
    assert not (folder / 'prototype.html').exists()
    assert approve(client, bid, second).status_code == 202
    drain(client, app)
    assert pending(client, bid) is None and html.calls == html.closed == 2 and len(brief.requests) == 2
    assert client.get(f'/api/builds/{bid}').json()['stage'] == 'prototype'
    pages = client.get(f'/api/builds/{bid}/design-pages').json()['pages']
    for row, reviewed, (index, request) in zip(pages, [first, second], html.seen):
        sent = json.loads(section(request, 'Validated visual brief (untrusted; native slots and safety rules win):'))
        assert sent == reviewed['brief']['brief'] == row['brief']['brief']
        assert hashlib.sha256((folder / f'brief_p{index}.json').read_bytes()).hexdigest() == reviewed['brief']['sha256']
    assert bid not in app.state.harness.active_builds


def test_edit_publishes_exact_brief_and_settings_off_applies_to_next_page(brief_api):
    client, app, bid, folder, _, brief, html, _ = brief_api
    review = pending(client, bid)
    value = deepcopy(review['brief']['brief'])
    value['overall'] = 'A calm blue composition. ' * 800
    response = edit(client, bid, review, value)
    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited['revision'] == review['revision'] + 1 and edited['brief']['origin'] == 'edited'
    assert edited['brief']['created_at'] == review['brief']['created_at'] and not edited['issues']
    assert edited['brief']['sha256'] == hashlib.sha256(rb.canonical(value)).hexdigest()
    assert edit(client, bid, review, value).status_code == 409
    assert approve(client, bid, review).json()['error']['code'] == 'brief_review_conflict'
    assert client.put('/api/settings', json={'review_briefs': False}).status_code == 200
    assert pending(client, bid)['review_id'] == edited['review_id']
    assert not html.calls
    result = approve(client, bid, edited)
    assert result.status_code == 202, result.text
    drain(client, app)
    assert pending(client, bid) is None and html.calls == 2 and len(brief.requests) == 2
    assert (folder / 'brief_p1.json').read_bytes() == rb.canonical(value)
    assert client.get(f"/api/traces/{result.json()['run_id']}/calls").json()['settings']['review_briefs'] is False


@pytest.mark.parametrize('bad,path', [('empty', '/slots/0/treatment'), ('overall', '/overall'),
    ('missing', '/slots'), ('duplicate', '/slots'), ('foreign', '/slots'), ('security', '/overall')])
def test_invalid_edit_is_persisted_with_issue_paths_and_refuses_approve(brief_api, bad, path):
    client, app, bid, folder, _, brief, html, _ = brief_api
    review = pending(client, bid)
    value = deepcopy(review['brief']['brief'])
    if bad == 'empty':
        value['slots'][0]['treatment'] = ' '
    elif bad == 'overall':
        value['overall'] = ''
    elif bad == 'missing':
        value['slots'].pop()
    elif bad == 'duplicate':
        value['slots'].append(value['slots'][0])
    elif bad == 'foreign':
        value['slots'][0]['id'] = 'p5_foreign'
    else:
        value['overall'] = '<script>alert(1)</script> https://outside.example/a.png'
    response = edit(client, bid, review, value)
    assert response.status_code == 200, response.text
    review = response.json()
    assert review['brief']['origin'] == 'edited' and review['revision'] == 2
    assert any(issue['path'].startswith(path) for issue in review['issues'])
    assert approve(client, bid, review).json()['error']['code'] == 'artifact_invalid'
    assert not html.calls and not (folder / 'prototype.html').exists()


def test_edit_checks_complete_html_request_against_current_profile(brief_api):
    client, app, bid, _, _, brief, html, _ = brief_api
    review = pending(client, bid)
    html.fixed = 200_000
    response = edit(client, bid, review, review['brief']['brief'])
    assert response.status_code == 200, response.text
    assert response.json()['issues'][0]['path'] == ''
    assert 'input tokens' in response.json()['issues'][0]['message']
    assert html.counted and not html.calls
    assert approve(client, bid, response.json()).json()['error']['code'] == 'artifact_invalid'


@pytest.mark.parametrize('change', ['live', 'candidate', 'assessment'])
def test_approve_checks_freshness_before_any_model_call_and_marks_stale(brief_api, change):
    client, app, bid, folder, _, brief, html, _ = brief_api
    review = pending(client, bid)
    saved = episodic.brief_review(app.state.db, bid)['record']
    if change == 'candidate':
        (Path(saved['folder']) / 'spec.json').write_text('{}', encoding='utf-8')
    elif change == 'assessment':
        from dss.spec import requirements as req
        ledger = req.load(folder)
        ledger.assessment.id = 'a_another'
        (folder / 'requirements.json').write_text(ledger.model_dump_json(), encoding='utf-8')
    else:
        (folder / 'docs/decisions.md').write_text('Changed externally', encoding='utf-8')
    before = len(brief.requests), len(html.counted), html.calls
    result = approve(client, bid, review)
    assert result.status_code == 409 and result.json()['error']['code'] == 'brief_review_stale'
    assert pending(client, bid)['stale'] is True
    assert (len(brief.requests), len(html.counted), html.calls) == before


def test_cancel_is_idempotent_preserves_publication_and_drops_only_owned_candidate(brief_api):
    client, app, bid, folder, _, brief, html, service = brief_api
    saved = episodic.brief_review(app.state.db, bid)['record']
    before = publication.folder_digest(folder)
    body = {'review_id': saved['review']['review_id']}
    route = f'/api/builds/{bid}/briefs/review/cancel'
    first = client.post(route, json=body)
    assert first.status_code == 200, first.text
    assert client.post(route, json=body).json() == first.json()
    assert pending(client, bid) is None and not Path(saved['folder']).exists()
    assert publication.folder_digest(folder) == before and not html.calls


def test_restart_retains_review_and_candidate_and_can_approve(brief_api, monkeypatch):
    from dss.main import create_app
    from fakes import fake_models
    client, app, bid, folder, _, brief, html, service = brief_api
    review = pending(client, bid)
    saved = episodic.brief_review(app.state.db, bid)['record']
    restored = create_app(app.state.settings.get(), model_lister=fake_models)
    restored.state.bigquery_factory = lambda config: service
    with TestClient(restored) as other:
        monkeypatch.setattr(restored.state.models, 'llm_for',
                            lambda node: brief if node == 'reference_brief' else html)
        assert pending(other, bid) == review
        assert Path(saved['folder']).is_dir()
        assert approve(other, bid, review).status_code == 202
        drain(other, restored)
        assert pending(other, bid)['page'] == 2 and html.calls == 1


def test_review_body_limit_and_missing_review(brief_api):
    client, app, bid, *_ = brief_api
    response = client.put(f'/api/builds/{bid}/briefs/review', content=b' ' * (256 * 1024 + 1))
    assert response.status_code == 413
    response = client.put(f'/api/builds/{bid}/briefs/review', json={
        'review_id': 'br_missing', 'revision': 1, 'brief': {}})
    assert response.status_code == 404 and response.json()['error']['code'] == 'review_not_found'


@pytest.mark.parametrize('cancel', [False, True])
def test_revision_reviews_two_pages_without_replaying_extraction_or_patches(setup, designed, client, monkeypatch, cancel):
    from test_revise import DesignFlow, response, post_designed, finished
    from dss.spec import requirements as req
    app, bid, folder, *_ = setup
    assert client.put('/api/settings', json={'review_briefs': True}).status_code == 200
    text = 'Title: Sales overview'
    fake = DesignFlow(needs_by_text={text: [{'capability': 'layout.background_image'}]},
                      properties_by_text={text: [{'path': 'text', 'value': 'Sales overview'}]},
                      response=response([], []))
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: fake)
    watched = ['spec.json', 'prototype.html', 'background_p1.png', 'background_p2.png', 'docs/decisions.md']
    before = {n: (folder / n).read_bytes() for n in watched}
    comments = [{'component_id': f'p{n}_design', 'text': text} for n in (1, 2)]
    assessment, run_id = post_designed(client, app, bid, comments)
    review = pending(client, bid)
    assert review and review['action'] == 'revise' and review['page'] == 1, finished(app, bid, run_id)
    assert finished(app, bid, run_id)['status'] == 'ok' and bid not in app.state.harness.active_builds
    assert client.get(f'/api/builds/{bid}').json()['stage'] == 'prototype'
    assert req.load(folder).pending_comments is not None and not fake.designs
    assert {n: (folder / n).read_bytes() for n in watched} == before
    extracts, revisions = fake.extractions, fake.revisions
    if cancel:
        saved = episodic.brief_review(app.state.db, bid)['record']
        result = client.post(f'/api/builds/{bid}/briefs/review/cancel', json={'review_id': review['review_id']})
        assert result.status_code == 200
        assert req.load(folder).pending_comments is not None and not Path(saved['folder']).exists()
        assert {n: (folder / n).read_bytes() for n in watched} == before
        return
    assert approve(client, bid, review).status_code == 202
    drain(client, app)
    second = pending(client, bid)
    assert second and second['page'] == 2
    assert [n for n, _ in fake.designs] == [1]
    assert {n: (folder / n).read_bytes() for n in watched} == before
    result = approve(client, bid, second)
    assert result.status_code == 202
    drain(client, app)
    assert pending(client, bid) is None, events(app, bid)
    assert [n for n, _ in fake.designs] == [1, 2]
    assert (fake.extractions, fake.revisions) == (extracts, revisions)
    assert req.load(folder).pending_comments is None
    assert finished(app, bid, result.json()['run_id'])['status'] == 'ok'


def test_review_events_follow_the_contract_fixture(brief_api):
    client, app, bid, _, run_id, *_ = brief_api
    expected = Path('../contracts/fixtures/stage-settings/events.review.sse').read_text(encoding='utf-8')
    from test_api_contract import shape
    observed = [(k, p) for k, p in events(app, bid) if p.get('run_id') == run_id or k == 'brief.review']
    cursor = 0
    for block in expected.strip().split('\n\n')[1:]:  # ready belongs to the SSE connection
        name, data = block.split('\n')
        name = name.removeprefix('event: ')
        value = json.loads(data.removeprefix('data: '))
        index = next(i for i in range(cursor, len(observed)) if observed[i][0] == name)
        shape(observed[index][1], value)
        cursor = index + 1


def test_two_clients_approve_only_one_continuation(brief_api):
    from concurrent.futures import ThreadPoolExecutor
    client, app, bid, folder, _, brief, html, _ = brief_api
    review = pending(client, bid)
    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(lambda _: approve(client, bid, review), range(2)))
    assert [r.status_code for r in responses] == [202, 202]
    assert responses[0].json() == responses[1].json()
    drain(client, app)
    assert html.calls == 1 and len(brief.requests) == 2
    assert pending(client, bid)['page'] == 2


def test_malformed_edit_returns_issues_and_nonfinite_json_is_rejected(brief_api):
    client, app, bid, *_ = brief_api
    review = pending(client, bid)
    value = deepcopy(review['brief']['brief'])
    value['slots'][0]['id'] = ['invalid']
    response = edit(client, bid, review, value)
    assert response.status_code == 200 and response.json()['issues'][0]['path'] == '/slots/0/id'
    response = client.put(f'/api/builds/{bid}/briefs/review', content=json.dumps({
        'review_id': review['review_id'], 'revision': 2, 'brief': {'overall': float('nan')}}),
        headers={'Content-Type': 'application/json'})
    assert response.status_code == 422 and pending(client, bid)['revision'] == 2


@pytest.mark.parametrize('route,method', [('design', 'PUT'), ('context', 'PUT'), ('feasibility/check', 'POST')])
def test_request_entering_before_pause_is_rechecked_after_its_body(brief_api, route, method):
    client, app, bid, *_ = brief_api
    row = episodic.brief_review(app.state.db, bid)
    episodic.update_brief_review(app.state.db, row, row['record'], state='body_arriving')
    if route == 'feasibility/check':
        data = b''
    else:
        value = client.get(f'/api/builds/{bid}/{route}').json()
        for key in ('revision', 'issues'):
            value.pop(key, None)
        data = json.dumps(value).encode()
    def body():
        # This runs in receive(), after the middleware's first guard and before reservation.
        current = episodic.brief_review(app.state.db, bid, row['review_id'])
        episodic.update_brief_review(app.state.db, current, current['record'])
        yield data
    before = publication.folder_digest(app.state.settings.get().data_dir / 'builds' / bid / 'v1')
    response = client.request(method, f'/api/builds/{bid}/{route}', content=body(),
                              headers={'Content-Type': 'application/json'})
    assert response.status_code == 409 and response.json()['error']['code'] == 'brief_review_pending'
    assert publication.folder_digest(app.state.settings.get().data_dir / 'builds' / bid / 'v1') == before


def test_read_and_cancel_remain_available_during_edit_token_count(brief_api, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    client, app, bid, *_ = brief_api
    review = pending(client, bid)
    started, release = client.portal.call(lambda: (asyncio.Event(), asyncio.Event()))
    counter = ReferenceHTMLLLM.count_request_tokens
    async def blocked(self, request):
        started.set()
        await release.wait()
        return await counter(self, request)
    monkeypatch.setattr(ReferenceHTMLLLM, 'count_request_tokens', blocked)
    async def ready():
        async with asyncio.timeout(5):
            await started.wait()
    with ThreadPoolExecutor(max_workers=3) as workers:
        editing = workers.submit(edit, client, bid, review, review['brief']['brief'])
        try:
            client.portal.call(ready)
            reading = workers.submit(pending, client, bid)
            assert reading.result(timeout=5)['review_id'] == review['review_id']
            cancelling = workers.submit(client.post, f'/api/builds/{bid}/briefs/review/cancel',
                                         json={'review_id': review['review_id']})
            assert cancelling.result(timeout=5).status_code == 200
        finally:
            client.portal.call(release.set)
        assert editing.result(timeout=5).status_code == 404
    assert pending(client, bid) is None


def test_cancelled_initial_revision_cleans_candidate_and_retains_comments(setup, designed, client, monkeypatch):
    from test_revise import DesignFlow, response
    from dss.spec import requirements as req
    app, bid, folder, *_ = setup
    app.state.settings.update({'review_briefs': True})
    started = client.portal.call(asyncio.Event)
    closed = []
    class BlockingBrief(BriefLLM):
        async def generate_content_async(self, request, stream=False):
            started.set()
            try:
                await asyncio.Event().wait()
                yield  # unreachable: keep the provider's async-generator protocol
            finally:
                closed.append(True)
    text = 'Title: Sales overview'
    fake = DesignFlow(needs_by_text={text: [{'capability': 'layout.background_image'}]},
                      response=response([]))
    brief = BlockingBrief()
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: brief if node == 'reference_brief' else fake)
    before = (folder / 'spec.json').read_bytes()
    result = client.post(f'/api/builds/{bid}/comments', json={'comments': [{'component_id': 'p1_design', 'text': text}]})
    assert result.status_code == 202
    async def stop():
        async with asyncio.timeout(5):
            await started.wait()
        assert list((app.state.settings.get().data_dir / '.brief-reviews').glob('r_*'))
        tasks = list(app.state.engine_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    client.portal.call(stop)
    assert closed and not list((app.state.settings.get().data_dir / '.brief-reviews').glob('r_*'))
    assert pending(client, bid) is None and bid not in app.state.harness.active_builds
    assert req.load(folder).pending_comments is not None and (folder / 'spec.json').read_bytes() == before


@pytest.mark.parametrize('terminal', ['published', 'cancelled'])
def test_terminal_journal_overrides_pending_review_in_older_sqlite_backup(brief_api, tmp_path, monkeypatch, terminal):
    import sqlite3
    from contextlib import closing
    client, app, bid, folder, _, brief, html, service = brief_api
    review = pending(client, bid)
    snapshot = tmp_path / 'before-approval.sqlite'
    with app.state.db.connect() as source, closing(sqlite3.connect(snapshot)) as destination:
        source.backup(destination)
    deleted = []
    monkeypatch.setattr(service, 'delete_view', lambda table: deleted.append(table) or True)
    if terminal == 'published':
        app.state.settings.update({'review_briefs': False})
        assert approve(client, bid, review).status_code == 202
        drain(client, app)
        assert client.get(f'/api/builds/{bid}').json()['stage'] == 'prototype'
    else:
        result = client.post(f'/api/builds/{bid}/briefs/review/cancel', json={'review_id': review['review_id']})
        assert result.status_code == 200
    terminal_files = publication.folder_digest(folder)
    deleted_before = list(deleted)
    # Restore with SQLite's backup API, never a byte copy of a live database.
    with closing(sqlite3.connect(snapshot)) as source, app.state.db.connect() as destination:
        source.backup(destination)
    assert pending(client, bid) is not None
    client.portal.call(publication.recover, app.state.db, app.state.settings.get(), lambda config: service)
    assert pending(client, bid) is None
    assert publication.folder_digest(folder) == terminal_files and deleted == deleted_before
    assert client.get(f'/api/builds/{bid}').json()['stage'] == ('prototype' if terminal == 'published' else 'blueprint')
    client.portal.call(publication.recover, app.state.db, app.state.settings.get(), lambda config: service)
    assert pending(client, bid) is None  # idempotent on every later restart
