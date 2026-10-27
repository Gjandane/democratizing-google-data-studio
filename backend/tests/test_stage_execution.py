"""Stage execution (change 2026-10-26): real ADK models, fake time, no provider or sleeps.

"""
import asyncio
from copy import deepcopy
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from google.genai.errors import APIError
import pytest

from dss.config import Config
from dss.harness import stages
from dss.harness.context import Context, Section, fit_request, request_estimate
from dss.harness.guardrails import RunError
from dss.harness.llm import ModelRouter, RetryingGemini, bind_model
from dss.harness.nodes import designer
from fakes import FakeLLM
from test_blueprint import blueprint_api  # noqa: F401
from test_context_node import context_api  # noqa: F401
from test_designer import DesignerLLM, Trace, designed_flow, quick_measure
from test_render import three_pages


ROUTING = {
    'interview': ('context', 'outline_propose', 'outline_suggest', 'outline_other'),
    'routine': ('hello', 'capability_check', 'revise', 'synthetic_schema', 'consolidate',
                'ux_audit', 'style_extract', 'research', 'judge'),
    'reference_interpretation': ('reference_extract',), 'native_planning': ('blueprint',),
    'html_brief': ('reference_brief',), 'reference_html': ('reference_html',),
    'html_no_reference': ('designer',),
}


def test_validation_diagnostic_projects_only_schema_paths_and_owned_categories():
    from dss.harness.tracing import validation_diagnostic
    from dss.harness.nodes.reference_extract import ReferenceOutput
    errors = [
        {'type': 'extra_forbidden', 'loc': ('items', 0, 'secret-key'), 'input': 'secret-value'},
        {'type': 'secret-category', 'loc': ('items', 1, 'aggregation', 'secret-union-label'),
         'msg': 'secret-message', 'ctx': {'secret': 'secret-context'}, 'url': 'https://secret'},
        {'type': 'int_type', 'loc': ('items', 1000000, 'box', 'x'), 'input': 'secret'},
        {'type': 'value_error', 'loc': ('items', True, 'secret'), 'ctx': {'error': ValueError('secret')}},
    ]
    result = validation_diagnostic(errors * 4, ReferenceOutput.model_json_schema(), local=True)
    assert result['boundary'] == 'local_validation' and result['category'] == 'local_pydantic_rejection'
    assert result['issue_count'] == 16 and result['issues_truncated'] is True and len(result['issues']) == 10
    assert result['issues'][:3] == [
        {'category': 'extra', 'path': ['items', 0, '?']},
        {'category': 'other', 'path': ['items', 1, 'aggregation', '?']},
        {'category': 'type', 'path': ['items', '?', 'box', 'x']},
    ]
    assert 'secret' not in json.dumps(result)


def test_diagnostic_projection_failure_is_unclassified_and_bounded():
    from dss.harness.tracing import validation_diagnostic, response_diagnostic, schema_path
    def broken_errors():
        raise RuntimeError('private diagnostic failure')
        yield
    result = validation_diagnostic(broken_errors(), {}, local=True)
    assert result == {'boundary': 'local_validation', 'category': 'unclassified'}
    assert response_diagnostic('private provider code') == {'boundary': 'provider_response', 'category': 'unclassified'}
    assert schema_path(['private'] * 100, {}) == ['?'] * 13


@pytest.mark.parametrize('outcome', ['ok', 'provider_error', 'output_cutoff', 'timeout',
                                     'input_over_limit', 'cancelled', 'invalid'])
def test_local_rejection_only_changes_an_existing_ok_call(outcome):
    from dss.harness.tracing import StageCall
    with stages.Execution(Config(), Trace()).activate() as run:
        session = run.session('reference_extract')
        stages.invalid_output('reference_extract')
        assert not run.calls  # no fabricated request
        call = StageCall(session, request(), stages.ARGON, 1)
        call.value['outcome'] = outcome
        stages.invalid_output('reference_extract')
        assert call.value['outcome'] == ('invalid' if outcome == 'ok' else outcome)
        assert len(run.calls) == 1


class FakeTime:
    def __init__(self):
        self.value, self.waits = 0, []

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds

    async def sleep(self, seconds):
        self.waits.append(seconds)
        self.advance(seconds)


@pytest.fixture
def fake_clock(monkeypatch):
    time, clocks = FakeTime(), []
    original = stages.StageClock
    def factory(node, seconds, **kwargs):
        clock = original(node, seconds, now=time.now, sleep=time.sleep)
        clocks.append(clock)
        return clock
    monkeypatch.setattr(stages, 'StageClock', factory)
    return time, clocks


def request(limit=777):
    return LlmRequest(model='fake', config=types.GenerateContentConfig(max_output_tokens=limit),
                      contents=[types.Content(role='user', parts=[types.Part(text='JSON only')])])


def memory(node, text='Mandatory facts'):
    # Internal legacy nodes such as style_extract have no standalone context recipe.
    return Context(node, [Section('input', 'facts', body=text)], {'past': 0, 'history': 0, 'semantic': 0}, budget=10000)


async def generate(model, req):
    return [response async for response in model.generate_content_async(req)]


@pytest.mark.parametrize('stage,node', [(s, n) for s, ns in ROUTING.items() for n in ns])
async def test_every_node_routes_and_explicitly_requests_its_profile(stage, node):
    config = Config()
    # Non-default thinking catches nodes which silently retain a hardcoded LOW or HIGH.
    config.stages[stage]['thinking'] = 'medium'
    config.stages[stage]['model'] = stages.ARGON
    router = ModelRouter(SimpleNamespace(get=lambda: config))
    trace = Trace()
    with stages.Execution(config, trace).activate():
        assert stages.stage_for(node) == stage
        assert router.model_for(node) == stages.ARGON
        assert router.timeout_ms(node) == config.stages[stage]['timeout_s'] * 1000
        req = request()
        if node != 'hello':
            await fit_request(memory(node), req, FakeLLM(), {})
        await generate(bind_model(node, FakeLLM()), req)
        assert req.config.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM
        assert req.config.max_output_tokens == (config.stages[stage]['output_tokens']
                                                if stage in stages.GENERATIONS else 777)
    assert trace.spans[0]['node'] == 'stage_settings' and trace.spans[0]['settings'] == stages.snapshot(config)
    assert len(trace.spans[0]['calls']) == 1


@pytest.mark.parametrize('node', ['blueprint', 'reference_extract'])
async def test_analysis_defaults_share_one_action_clock_through_count_and_repair(node, fake_clock):
    time, clocks = fake_clock
    scale = 2 if node == 'blueprint' else 1  # native_planning's clock is 1,200 s (api.md 3.1)
    class Counted(FakeLLM):
        async def count_request_tokens(self, req):
            time.advance(150 * scale)
            return 1000
        async def generate_content_async(self, req, stream=False):
            time.advance(200 * scale)
            async for item in super().generate_content_async(req, stream):
                yield item
    fake, trace = Counted(), Trace()
    with stages.Execution(Config(), trace).activate() as run:
        session = run.session(node)
        with pytest.raises(RunError) as caught:
            async with session.scope():
                first = request()
                await fit_request(memory(node), first, fake, {})
                await generate(bind_model(node, fake), first)
                assert first.config.max_output_tokens == 32768 * scale
                assert first.config.thinking_config.thinking_level == types.ThinkingLevel.HIGH
                time.advance(100 * scale)  # code validation/measurement also spends the action clock
                await fit_request(memory(node), request(), fake, {})
        assert caught.value.code == 'stage_timeout'
        assert caught.value.message.startswith(stages.stage_for(node) + ':')
        assert session.clock.end == 600 * scale and fake.calls == 1 and len(clocks) == 1
        assert session.profile['input_tokens'] == 131072


@pytest.mark.parametrize('failure', [TimeoutError, RuntimeError])
async def test_expired_count_failure_is_a_stage_timeout(failure, fake_clock):
    time, _ = fake_clock
    class Counter(FakeLLM):
        async def count_request_tokens(self, req):
            time.advance(1201)
            raise failure('private counter error')
    with stages.Execution(Config(), Trace()).activate():
        with pytest.raises(RunError) as caught:
            await fit_request(memory('blueprint'), request(), Counter(), {})
    assert caught.value.code == 'stage_timeout' and caught.value.message.startswith('native_planning:')
    assert 'private' not in caught.value.message


@pytest.mark.parametrize('code,retried', [(429, True), (500, True), (503, True), (504, False), (400, False)])
async def test_retry_policy_and_remaining_client_deadline(monkeypatch, fake_clock, code, retried):
    time, clocks = fake_clock
    calls = []
    async def provider(self, req, stream=False):
        calls.append(self.api_client._api_client._http_options.timeout)
        time.advance(1)
        if len(calls) <= 3:
            raise APIError(code, {'error': {'code': code, 'message': 'private provider text'}})
        yield LlmResponse(content=types.Content(parts=[types.Part(text='{}')]))
    monkeypatch.setattr(Gemini, 'generate_content_async', provider)
    config = Config(google_api_key='fake-key')
    config.stages['native_planning'].update(timeout_s=30, transport_retries=3)
    with stages.Execution(config, Trace()).activate() as run:
        model = ModelRouter(SimpleNamespace(get=lambda: config)).llm_for('blueprint')
        async with run.session('blueprint').scope():
            if retried:
                await generate(bind_model('blueprint', model), request())
                assert time.waits == [1, 2, 4]
                assert calls == [30000, 28000, 25000, 20000]
            else:
                with pytest.raises(APIError):
                    await generate(bind_model('blueprint', model), request())
                assert not time.waits and len(calls) == 1
    assert len(clocks) == 1


async def test_retry_never_starts_with_less_than_one_second_left(monkeypatch, fake_clock):
    time, _ = fake_clock
    calls = []
    async def provider(self, req, stream=False):
        calls.append(True)
        time.advance(1198.5)
        raise APIError(503, {'error': {'code': 503, 'message': 'private'}})
        yield  # async generator
    monkeypatch.setattr(Gemini, 'generate_content_async', provider)
    config = Config(google_api_key='fake-key')
    with stages.Execution(config, Trace()).activate() as run:
        model = ModelRouter(SimpleNamespace(get=lambda: config)).llm_for('blueprint')
        with pytest.raises(RunError, match='native_planning:') as caught:
            async with run.session('blueprint').scope():
                await generate(bind_model('blueprint', model), request())
    assert caught.value.code == 'stage_timeout' and time.waits == [1] and len(calls) == 1


async def test_routine_retry_keeps_a_fresh_per_request_timeout(monkeypatch):
    from dss.harness import llm
    time, bounds, calls = FakeTime(), [], []
    @asynccontextmanager
    async def timeout(seconds):
        end = time.now() + seconds
        bounds.append(end)
        yield
        if time.now() >= end:
            raise TimeoutError
    async def provider(self, req, stream=False):
        calls.append(self.api_client._api_client._http_options.timeout)
        time.advance(29)
        if len(calls) == 1:
            raise APIError(503, {'error': {'code': 503, 'message': 'private'}})
        yield LlmResponse(content=types.Content(parts=[types.Part(text='Hello')]))
    monkeypatch.setattr(llm, '_request_timeout', timeout)
    monkeypatch.setattr(llm.asyncio, 'sleep', time.sleep)
    monkeypatch.setattr(Gemini, 'generate_content_async', provider)
    config = Config(google_api_key='fake-key')
    with stages.Execution(config, Trace()).activate():
        model = ModelRouter(SimpleNamespace(get=lambda: config)).llm_for('hello')
        result = await generate(bind_model('hello', model), request())
    assert result and bounds == [30, 60] and time.value == 59
    assert calls == [30000, 30000] and time.waits == [1]


def test_a_listing_refresh_cannot_change_a_running_actions_model():
    config = Config()
    router = ModelRouter(SimpleNamespace(get=lambda: config))
    router.available = {stages.FLASH}
    with stages.Execution(config, Trace(), available=router.available).activate():
        assert router.model_for('blueprint') == stages.FLASH
        router.available = None  # a Settings PUT starts a fresh listing which fails
        assert router.model_for('blueprint') == stages.FLASH
    assert router.model_for('blueprint') == stages.ARGON


@pytest.fixture
def stage_provider(monkeypatch, fake_clock):
    from dss.harness import llm
    time, clocks = fake_clock
    calls, outcomes = [], []
    @asynccontextmanager
    async def bounded(model, actual=None):
        yield model.model_copy(update={'model': actual or model.model})
    async def counter(self, req):
        time.advance(1)
        return 100
    async def provider(self, req, stream=False):
        calls.append((self.model, req.model, deepcopy(req.config), time.now()))
        time.advance(1)
        item = outcomes.pop(0) if outcomes else 'ok'
        if isinstance(item, int):
            raise APIError(item, {'error': {'code': item, 'message': 'PRIVATE provider prompt/key'}})
        if item == 'cut':
            yield LlmResponse(error_code='MAX_TOKENS', finish_reason=types.FinishReason.MAX_TOKENS)
        else:
            yield LlmResponse(content=types.Content(parts=[types.Part(text='{}' if item == 'ok' else 'invalid JSON')]),
                usage_metadata=types.GenerateContentResponseUsageMetadata(
                    prompt_token_count=125, candidates_token_count=7, thoughts_token_count=9))
    monkeypatch.setattr(llm, 'provider_model', bounded)
    monkeypatch.setattr(RetryingGemini, 'count_request_tokens', counter, raising=False)
    monkeypatch.setattr(Gemini, 'generate_content_async', provider)
    config = Config(google_api_key='fake-key')
    config.stages['native_planning'].update(timeout_s=30, transport_retries=1)
    return config, time, clocks, calls, outcomes


async def test_fallback_has_its_own_retries_same_request_caps_and_one_clock(stage_provider):
    config, time, clocks, calls, outcomes = stage_provider
    outcomes[:] = [503, 503, 429, 'ok', 'ok']
    trace = SimpleNamespace(spans=[], run_id='r_test')
    with stages.Execution(config, trace).activate() as run:
        model = ModelRouter(SimpleNamespace(get=lambda: config)).llm_for('blueprint')
        req, span = request(), {}
        await fit_request(memory('blueprint'), req, model, span)
        await generate(bind_model('blueprint', model), req)
        # A content repair stays on the fallback; it cannot alternate back to primary.
        req2 = request()
        await fit_request(memory('blueprint'), req2, model, {})
        await generate(bind_model('blueprint', model), req2)
    assert [c[0] for c in calls] == [stages.ARGON, stages.ARGON, stages.FLASH, stages.FLASH, stages.FLASH]
    assert all(c[0] == c[1] for c in calls)
    assert all(c[2].thinking_config.thinking_level == types.ThinkingLevel.HIGH and
               c[2].max_output_tokens == 65536 for c in calls)
    assert len(clocks) == 1 and clocks[0].end == 30 and time.waits == [1, 1] and time.value == 9
    recorded = trace.spans[0]['calls']
    assert [c['transport_attempt'] for c in recorded] == [1, 2, 1, 2, 1]
    assert [c['attempt'] for c in recorded] == [1, 1, 1, 1, 2]
    assert [c['fallback'] for c in recorded] == [False, False, True, True, True]
    assert all(c['requested_model'] == stages.ARGON and c['input_measured'] == 100 and
               c['input_enforced'] == 632 for c in recorded)
    assert [c['cost_usd_estimate'] for c in recorded] == [0, 0, 0, 0.00015375, 0.00015375]
    assert 'PRIVATE' not in json.dumps(trace.spans)


@pytest.mark.parametrize('same,available,count', [(False, None, 4), (True, None, 2),
                                                   (False, set(), 0), (False, {stages.FLASH}, 2)])
async def test_exhausted_or_listed_absent_models_stop_without_recursive_fallback(stage_provider, same, available, count):
    config, time, _, calls, outcomes = stage_provider
    if same:
        config.fallback_model = stages.ARGON
    outcomes[:] = [503] * 8
    with stages.Execution(config, SimpleNamespace(spans=[]), available=available).activate():
        router = ModelRouter(SimpleNamespace(get=lambda: config))
        with pytest.raises(RunError) as caught:
            await generate(bind_model('blueprint', router.llm_for('blueprint')), request())
    assert caught.value.code == 'stage_model_unavailable' and len(calls) == count
    assert caught.value.message.startswith('native_planning:') and 'PRIVATE' not in caught.value.message
    assert config.stages['native_planning']['model'] in caught.value.message
    if available == {stages.FLASH}:
        assert all(c[0] == stages.FLASH for c in calls)


@pytest.mark.parametrize('outcome,exception', [('cut', RunError), ('invalid', None), (400, APIError), (504, APIError)])
async def test_ineligible_failures_never_fallback(stage_provider, outcome, exception):
    config, _, _, calls, outcomes = stage_provider
    outcomes[:] = [outcome]
    trace = SimpleNamespace(spans=[])
    with stages.Execution(config, trace).activate():
        model = bind_model('blueprint', ModelRouter(SimpleNamespace(get=lambda: config)).llm_for('blueprint'))
        req = request()
        req.config.response_json_schema = {'type': 'object'}
        if exception:
            with pytest.raises(exception):
                await generate(model, req)
        else:
            await generate(model, req)
    assert len(calls) == 1 and calls[0][0] == stages.ARGON
    assert trace.spans[0]['calls'][0]['outcome'] == ('output_cutoff' if outcome == 'cut' else
                                                   'invalid' if outcome == 'invalid' else 'provider_error')


async def test_failed_listing_keeps_selected_and_listing_fallback_is_visible(stage_provider):
    config, _, _, calls, _ = stage_provider
    async def failed(key):
        raise RuntimeError('PRIVATE listing')
    router = ModelRouter(SimpleNamespace(get=lambda: config), failed)
    await router.refresh()
    assert router.available is None
    for available, actual in [(None, stages.ARGON), ({stages.FLASH}, stages.FLASH)]:
        trace = SimpleNamespace(spans=[])
        with stages.Execution(config, trace, available=available).activate():
            await generate(bind_model('blueprint', router.llm_for('blueprint')), request())
        record = trace.spans[0]['calls'][0]
        assert record['model'] == actual and record['requested_model'] == stages.ARGON
        assert record['fallback'] is (actual == stages.FLASH)


async def test_count_failure_and_overflow_make_no_provider_call_or_fallback(stage_provider, monkeypatch):
    config, _, _, calls, _ = stage_provider
    for result in ('failure', 200000):
        async def counter(self, req):
            if result == 'failure':
                raise ValueError('PRIVATE count')
            return result
        monkeypatch.setattr(RetryingGemini, 'count_request_tokens', counter)
        trace = SimpleNamespace(spans=[])
        with stages.Execution(config, trace).activate():
            model = ModelRouter(SimpleNamespace(get=lambda: config)).llm_for('blueprint')
            with pytest.raises(RunError):
                await fit_request(memory('blueprint'), request(), model, {})
        assert not trace.spans[0].get('calls') and not calls


async def test_fallback_uses_remaining_clock_and_records_timeout(stage_provider, monkeypatch):
    config, time, clocks, calls, outcomes = stage_provider
    outcomes[:] = [503, 503]
    async def slow(self, req, stream=False):
        calls.append(self.model)
        time.advance(10)
        raise APIError(503, {'error': {'code': 503, 'message': 'PRIVATE'}})
        yield
    monkeypatch.setattr(Gemini, 'generate_content_async', slow)
    trace = SimpleNamespace(spans=[])
    with stages.Execution(config, trace).activate():
        model = ModelRouter(SimpleNamespace(get=lambda: config)).llm_for('blueprint')
        with pytest.raises(RunError) as caught:
            await fit_request(memory('blueprint'), request(), model, {})
            await generate(bind_model('blueprint', model), request())
    assert caught.value.code == 'stage_timeout' and len(clocks) == 1
    assert calls == [stages.ARGON, stages.ARGON, stages.FLASH] and time.value == 32
    assert trace.spans[0]['calls'][-1]['outcome'] == 'timeout'


async def test_generation_stream_error_after_chunk_is_neither_retried_nor_fallen_back(stage_provider, monkeypatch):
    config, _, _, calls, _ = stage_provider
    async def streamed(self, req, stream=False):
        calls.append(self.model)
        yield LlmResponse(partial=True, content=types.Content(parts=[types.Part(text='partial')]))
        raise APIError(503, {'error': {'code': 503, 'message': 'PRIVATE'}})
    monkeypatch.setattr(Gemini, 'generate_content_async', streamed)
    trace = SimpleNamespace(spans=[])
    with stages.Execution(config, trace).activate():
        model = ModelRouter(SimpleNamespace(get=lambda: config)).llm_for('blueprint')
        with pytest.raises(APIError):
            await generate(bind_model('blueprint', model), request())
    assert calls == [stages.ARGON]
    record = trace.spans[0]['calls'][0]
    assert record['outcome'] == 'provider_error' and record['cost_usd_estimate'] is None


async def test_page_models_remain_page_local_through_fallback_and_revision(stage_provider, monkeypatch):
    config, _, _, _, _ = stage_provider
    config.stages['html_no_reference'].update(model=stages.ARGON, transport_retries=0)
    monkeypatch.setattr(designer.design_page, 'measure', quick_measure)
    scripted = DesignerLLM()
    async def pages(self, req, stream=False):
        session = stages.active_session.get()
        if session.page == 2 and self.model == stages.ARGON:
            raise APIError(503, {'error': {'code': 503, 'message': 'PRIVATE'}})
        async for response in scripted.generate_content_async(req, stream):
            yield response
    monkeypatch.setattr(Gemini, 'generate_content_async', pages)
    trace = Trace()
    with stages.Execution(config, trace).activate():
        router = ModelRouter(SimpleNamespace(get=lambda: config))
        result, notes = await designer.design(three_pages(), lambda: router.llm_for('designer'), trace)
        revised, failed = await designer.regenerate(result, {2: [{'text': 'Darker', 'component_id': 'p2_design'}]},
                                                    lambda: router.llm_for('designer'), trace)
    assert not notes and not failed
    assert [p.design.model for p in result.pages] == [stages.ARGON, stages.FLASH, stages.ARGON]
    assert [p.design.model for p in revised.pages] == [stages.ARGON, stages.FLASH, stages.ARGON]
    assert all(s['model'] == (stages.FLASH if s['page'] == 2 else stages.ARGON)
               for s in trace.spans if s['node'] == 'designer')


async def test_routine_runtime_errors_keep_existing_behavior_without_fallback(stage_provider):
    config, _, _, calls, outcomes = stage_provider
    config.stages['routine']['model'] = stages.ARGON
    outcomes[:] = [503, 503, 'ok']
    trace = SimpleNamespace(spans=[])
    with stages.Execution(config, trace).activate():
        model = ModelRouter(SimpleNamespace(get=lambda: config)).llm_for('hello')
        with pytest.raises(APIError):
            await generate(bind_model('hello', model), request())
    assert len(calls) == 2 and all(c[0] == stages.ARGON for c in calls)


async def test_cancelled_provider_call_is_persisted_and_releases_lock(client, app, build_id):
    started, release = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(app.state.harness.run('hello', build_id, {},
        llm=FakeLLM(started=started, release=release)))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with app.state.db.connect() as conn:
        row = conn.execute("SELECT * FROM traces WHERE build_id=?", (build_id,)).fetchone()
    response = client.get(f"/api/traces/{row['run_id']}/calls")
    assert response.status_code == 200
    assert response.json()['calls'][0]['outcome'] == 'cancelled'
    assert response.json()['calls'][0]['thinking_tokens'] is None
    assert not app.state.harness.active_builds and stages.execution.get() is None


async def test_routine_nodes_keep_their_own_call_identity_and_content_attempts():
    trace = SimpleNamespace(spans=[])
    with stages.Execution(Config(), trace).activate():
        for node in ('capability_check', 'revise', 'revise'):
            req = request()
            await fit_request(memory(node), req, FakeLLM(), {})
            await generate(bind_model(node, FakeLLM()), req)
    assert [(c['node'], c['attempt']) for c in trace.spans[0]['calls']] == [
        ('capability_check', 1), ('revise', 1), ('revise', 2)]


async def test_layout_rejection_records_invalid_before_successful_repair(monkeypatch):
    monkeypatch.setattr(designer.design_page, 'measure', quick_measure)
    trace = Trace()
    with stages.Execution(Config(), trace).activate():
        result, notes = await designer.design(three_pages(), lambda: DesignerLLM(plan={1: ['bad', 'ok']}), trace)
    assert not notes and all(p.design for p in result.pages)
    assert [c['outcome'] for c in trace.spans[0]['calls'] if c['page'] == 1] == ['invalid', 'ok']


@pytest.mark.parametrize('problem', ['page', 'missing'])
async def test_brief_semantic_rejection_records_invalid(tmp_path, problem):
    from test_reference_brief import BriefLLM, run
    trace = Trace()
    with stages.Execution(Config(), trace).activate():
        result, _, _ = await run(BriefLLM(), tmp_path, plan=[problem])
    assert isinstance(result, designer.Fallback)
    assert trace.spans[0]['calls'][0]['outcome'] == 'invalid'


def test_interview_semantic_repair_has_invalid_then_ok_calls(context_api, monkeypatch):
    from test_context_node import ContextLLM, example, wait
    client, app, bid, sid, *_ = context_api
    bad = example(sid)
    bad['kpis'][0]['measure']['field'] = 'missing'
    model = ContextLLM(replies=[json.dumps(bad), json.dumps(example(sid))])
    monkeypatch.setattr(app.state.models, 'llm_for', lambda _: model)
    response = client.post(f'/api/builds/{bid}/context', json={'notes': 'Improve revenue'})
    assert response.status_code == 202
    wait(app)
    calls = client.get(f"/api/traces/{response.json()['run_id']}/calls").json()['calls']
    assert [(c['node'], c['attempt'], c['outcome']) for c in calls] == [
        ('context', 1, 'invalid'), ('context', 2, 'ok')]


async def test_blueprint_drops_labels_then_observations_before_the_hard_stop():
    class Counted(FakeLLM):
        async def count_request_tokens(self, req):
            return request_estimate(req)
    config = Config()
    config.stages['native_planning']['input_tokens'] = 1024
    with stages.Execution(config, Trace()).activate():
        mandatory = Section('input', 'facts', body='NEVER DROP THIS')
        observations = Section('reference', 'observations', body='label' * 2000, compact='meaning' * 1000)
        mem = Context('blueprint', [observations, mandatory], {'past': 0, 'history': 0, 'semantic': 0})
        req, span = request(), {}
        fitted = await fit_request(mem, req, Counted(), span)
        assert span['dropped']['profile'] == 1 and span['dropped']['reference'] == 1
        assert 'NEVER DROP THIS' in req.config.system_instruction and fitted.sections == [mandatory]
        assert span['folded_request_tokens'] != span['enforced_input_bound']
        fake = Counted()
        with pytest.raises(RunError) as caught:
            await fit_request(memory('blueprint', 'mandatory' * 2000), request(), fake, {})
        assert caught.value.code == 'stage_input_over_limit' and fake.calls == 0
        assert caught.value.message.startswith('native_planning:')


@pytest.mark.parametrize('node', ['blueprint', 'reference_extract', 'reference_brief', 'reference_html', 'designer'])
async def test_cutoff_is_immediate_on_every_generation_stage(node):
    class Cut(FakeLLM):
        async def generate_content_async(self, req, stream=False):
            self.calls += 1
            yield LlmResponse(error_code='MAX_TOKENS', finish_reason=types.FinishReason.MAX_TOKENS)
    fake = Cut()
    with stages.Execution(Config(), Trace()).activate():
        with pytest.raises(RunError) as caught:
            await generate(bind_model(node, fake), request())
    assert caught.value.code == 'stage_output_cutoff' and fake.calls == 1
    assert caught.value.message.startswith(stages.stage_for(node) + ':')


async def test_partial_cutoff_signal_stops_and_closes_without_reading_another_chunk():
    closed = []
    class Partial(FakeLLM):
        async def generate_content_async(self, req, stream=False):
            try:
                yield LlmResponse(partial=True, finish_reason=types.FinishReason.MAX_TOKENS)
                raise AssertionError('A cutoff must never continue reading the stream')
            finally:
                closed.append(True)
    with stages.Execution(Config(), Trace()).activate():
        with pytest.raises(RunError) as caught:
            async for _ in bind_model('blueprint', Partial()).generate_content_async(request(), stream=True):
                pytest.fail('A cutoff chunk must not reach a consumer')
    assert caught.value.code == 'stage_output_cutoff' and closed == [True]


async def test_settings_change_during_a_run_keeps_and_persists_the_effective_snapshot(client, app, build_id):
    saved = deepcopy(stages.snapshot(app.state.settings.get()))
    class ChangesSettings(FakeLLM):
        async def generate_content_async(self, req, stream=False):
            app.state.settings.update({'stages': {'routine': {'thinking': 'high', 'model': stages.ARGON}}})
            assert stages.profile('hello') == saved['stages']['routine']
            assert app.state.models.model_for('hello') == saved['stages']['routine']['model']
            assert req.config.thinking_config.thinking_level == types.ThinkingLevel.LOW
            async for response in super().generate_content_async(req, stream):
                yield response
    result = await app.state.harness.run('hello', build_id, {}, llm=ChangesSettings())
    with app.state.db.connect() as conn:
        row = conn.execute('SELECT spans_json FROM traces WHERE run_id=?', (result['run_id'],)).fetchone()
    assert [s['settings'] for s in json.loads(row[0]) if 'settings' in s] == [saved]
    assert 'google_api_key' not in row[0]
    assert stages.execution.get() is None and stages.active_session.get() is None
    assert app.state.models.model_for('hello') == stages.ARGON


async def test_page_thinking_and_clock_cover_first_later_repairs_and_revision(monkeypatch):
    monkeypatch.setattr(designer.design_page, 'measure', quick_measure)
    config = Config()
    config.stages['html_no_reference']['thinking'] = 'medium'
    class Observed(DesignerLLM):
        sessions: list = []
        async def count_request_tokens(self, req):
            self.sessions.append(stages.active_session.get())
            return 1000
    model = Observed(plan={1: ['bad', 'ok'], 2: ['bad', 'ok']})
    with stages.Execution(config, Trace()).activate():
        spec, notes = await designer.design(three_pages(), lambda: model, Trace())
        revision = Observed(plan={2: ['bad', 'ok']})
        revised, failed = await designer.regenerate(spec, {2: [{'text': 'Darker', 'component_id': 'p2_design'}]},
                                                   lambda: revision, Trace())
    assert not notes and revised is not None and not failed
    assert all(c.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM for c in model.configs + revision.configs)
    assert all(c.max_output_tokens == 65536 for c in model.configs + revision.configs)
    assert len({id(s.clock) for s in model.sessions}) == 3
    assert model.sessions[0] is model.sessions[1]  # repair reuses page 1 clock
    assert revision.sessions[0] is revision.sessions[1]
    assert revision.sessions[0] is not model.sessions[2]  # revision starts a new page clock


async def test_measurement_spends_the_html_clock_and_cannot_publish(monkeypatch, fake_clock):
    time, clocks = fake_clock
    def measure(*args, **kwargs):
        time.advance(1201)
        return quick_measure(*args, **kwargs)
    monkeypatch.setattr(designer.design_page, 'measure', measure)
    model, spec = DesignerLLM(), three_pages()
    with pytest.raises(RunError) as caught:
        await designer.design(spec, lambda: model, Trace())
    assert caught.value.code == 'stage_timeout' and caught.value.message.startswith('html_no_reference:')
    assert len(clocks) == 1 and model.calls == 1 and all(p.design is None for p in spec.pages)


async def test_custom_limits_margin_and_output_are_effective():
    class Counted(FakeLLM):
        measured: int = 300
        async def count_request_tokens(self, req):
            return self.measured
    config = Config()
    config.stages['native_planning'].update(input_tokens=1024, output_tokens=256, input_margin_pct=35)
    with stages.Execution(config, Trace()).activate():
        req, span, model = request(), {}, Counted()
        await fit_request(memory('blueprint'), req, model, span)
        await generate(bind_model('blueprint', model), req)
        assert span['folded_request_tokens'] == 300 and span['enforced_input_bound'] == 917
        assert req.config.max_output_tokens == 256 and model.calls == 1
        model.measured = 400
        with pytest.raises(RunError) as caught:
            await fit_request(memory('blueprint'), request(), model, {})
        assert caught.value.code == 'stage_input_over_limit' and model.calls == 1


async def test_reference_profiles_apply_on_first_later_repair_and_revision(tmp_path, monkeypatch):
    from test_designer import reference_plan, ReferenceHTMLLLM
    monkeypatch.setattr(designer.design_page, 'measure', quick_measure)
    config = Config()
    config.stages['html_brief']['thinking'] = 'low'
    config.stages['reference_html']['thinking'] = 'medium'
    spec = three_pages()
    ref, brief, html = reference_plan(tmp_path, spec, html=ReferenceHTMLLLM(plan={2: ['bad', 'ok']}))
    with stages.Execution(config, Trace()).activate():
        designed, notes = await designer.design(spec, lambda: None, Trace(), reference=ref)
        ref, revision_brief, revision_html = reference_plan(tmp_path, designed,
            html=ReferenceHTMLLLM(plan={2: ['bad', 'ok']}))
        result, failed = await designer.regenerate(designed, {2: [{'text': 'Darker', 'component_id': 'p2_design'}]},
            lambda: None, Trace(), reference=ref)
    assert not notes and result is not None and not failed
    assert len(brief.requests) == 3 and len(html.requests) == 4 and len(revision_html.requests) == 2
    assert all(r.config.thinking_config.thinking_level == types.ThinkingLevel.LOW
               for r in brief.requests + revision_brief.requests)
    assert all(r.config.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM
               for r in html.requests + revision_html.requests)


async def test_five_pages_get_independent_page_clocks(monkeypatch):
    real_clock, clocks = stages.StageClock, []
    def clock(node, seconds, **kwargs):
        time = FakeTime()
        result = real_clock(node, seconds, now=time.now, sleep=time.sleep)
        result.fake_time = time
        clocks.append(result)
        return result
    monkeypatch.setattr(stages, 'StageClock', clock)
    def measure(*args, **kwargs):
        stages.active_session.get().clock.fake_time.advance(200)
        return quick_measure(*args, **kwargs)
    monkeypatch.setattr(designer.design_page, 'measure', measure)
    class Slow(DesignerLLM):
        async def generate_content_async(self, req, stream=False):
            stages.active_session.get().clock.fake_time.advance(601)
            async for response in super().generate_content_async(req, stream):
                yield response
    spec = three_pages()
    for index in (4, 5):
        page = spec.pages[2].model_copy(deep=True)
        page.index, page.name = index, f'Page {index}'
        for item in [*page.components, *page.decorations]:
            item.id = item.id.replace('p3_', f'p{index}_')
        spec.pages.append(page)
    result, notes = await designer.design(spec, lambda: Slow(), Trace())
    assert not notes and len(result.pages) == len(clocks) == 5
    assert all(p.design is not None for p in result.pages)
    assert all(c.fake_time.value == 801 and c.end == 1200 for c in clocks)
    assert sum(c.fake_time.value for c in clocks) > 1200


async def test_adk_cutoff_preserves_stage_code_and_reported_usage(client, app, build_id):
    from test_references import image, payload
    class Cut(FakeLLM):
        async def generate_content_async(self, req, stream=False):
            self.calls += 1
            yield LlmResponse(error_code='MAX_TOKENS', finish_reason=types.FinishReason.MAX_TOKENS,
                usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=17, candidates_token_count=3))
    with pytest.raises(RunError) as caught:
        await app.state.harness.run('reference_extract', build_id, payload(app, [image()]), llm=Cut())
    assert caught.value.code == 'stage_output_cutoff'
    assert caught.value.message.startswith('reference_interpretation:')
    with app.state.db.connect() as conn:
        row = conn.execute("SELECT * FROM traces WHERE node='reference_extract'").fetchone()
    assert row['error'] == 'stage_output_cutoff' and (row['input_tokens'], row['output_tokens']) == (17, 3)
    assert not app.state.harness.active_builds and stages.execution.get() is None


@pytest.mark.parametrize('failure', ['overflow', 'cutoff'])
def test_no_reference_hard_stop_preserves_publication_and_cleans_candidate(blueprint_api, monkeypatch, failure):
    from test_context_node import wait
    from dss.spec.publication import Candidate
    monkeypatch.setattr(designer.design_page, 'measure', quick_measure)
    client, app, bid, folder, _ = designed_flow(blueprint_api, monkeypatch, DesignerLLM())
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='blueprint' WHERE id=?", (bid,))
    before = {}
    begin = Candidate.begin
    def capture(*args, **kwargs):
        before.update({p.relative_to(folder): p.read_bytes() for p in folder.rglob('*') if p.is_file()})
        return begin(*args, **kwargs)
    monkeypatch.setattr(Candidate, 'begin', capture)
    class Overflow(DesignerLLM):
        async def count_request_tokens(self, req):
            return 131072
    model = Overflow() if failure == 'overflow' else DesignerLLM(plan={1: ['cut']})
    from test_reference_brief import BriefLLM
    brief = BriefLLM()
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: brief if node == 'reference_brief' else model)
    response = client.post(f'/api/builds/{bid}/blueprint/accept')
    assert response.status_code == 202
    wait(app)
    code = 'stage_input_over_limit' if failure == 'overflow' else 'stage_output_cutoff'
    with app.state.db.connect() as conn:
        row = conn.execute('SELECT * FROM traces WHERE run_id=?', (response.json()['run_id'],)).fetchone()
        event = conn.execute("SELECT payload_json FROM events WHERE run_id=? AND kind='run.finished'",
                             (response.json()['run_id'],)).fetchone()
    assert row['error'] == code and json.loads(event[0])['error'].startswith(code + ': html_no_reference:')
    assert {p.relative_to(folder): p.read_bytes() for p in folder.rglob('*') if p.is_file()} == before
    assert not app.state.harness.active_builds and not app.state.engine_tasks
    assert not list((app.state.settings.get().data_dir / '.publications').glob('r_*/'))
    assert model.calls == (0 if failure == 'overflow' else 1)
