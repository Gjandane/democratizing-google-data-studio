"""One retry per model call on 429/500/503, never on 504 (our own deadline) or other 4xx.

The provider is faked at the google-genai client the router builds, so ADK's real Gemini
request path runs offline and every provider call is counted."""
import json
from types import SimpleNamespace

import pytest
from google.adk.models.llm_request import LlmRequest
from google.genai import errors, types
from pydantic import SecretStr

from dss.harness import llm as llm_module
from dss.harness.guardrails import RunError
from dss.harness.llm import ModelRouter, RetryingGemini

SECRET = 'provider text echoing the prompt'


class Settings:
    def get(self):
        return SimpleNamespace(planner_model='planner-model', worker_model='worker-model',
                               google_api_key=SecretStr('test-key'))


def failure(code):
    cls = errors.ClientError if code < 500 else errors.ServerError
    return cls(code, {'error': {'code': code, 'message': SECRET, 'status': 'FAILED'}})


def reply(text='Hello!', prompt=5, output=2):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role='model', parts=[types.Part(text=text)]),
                                    finish_reason=types.FinishReason.STOP)],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt, candidates_token_count=output))


class Provider:
    """Scripted outcomes for successive provider calls: an int fails with that status."""

    def __init__(self, model, *outcomes, chunks_before_failure=0):
        self.outcomes, self.calls, self.chunks = list(outcomes), 0, chunks_before_failure
        model.api_client.aio.models.generate_content = self.generate
        model.api_client.aio.models.generate_content_stream = self.stream

    def next(self):
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else 'ok'
        return outcome

    async def generate(self, *, model, contents, config):
        outcome = self.next()
        if outcome != 'ok':
            raise failure(outcome)
        return reply()

    async def stream(self, *, model, contents, config):
        outcome = self.next()
        if outcome != 'ok' and not self.chunks:
            raise failure(outcome)

        async def chunks():
            try:
                for _ in range(self.chunks):
                    yield reply('partial ')
                if outcome != 'ok':
                    raise failure(outcome)
                yield reply()
            finally:
                self.closed = True
        self.closed = False
        return chunks()


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(llm_module, 'RETRY_DELAY_S', 0)


def worker():
    return ModelRouter(Settings()).llm_for('hello')


def request():
    return LlmRequest(model='worker-model', contents=[
        types.Content(role='user', parts=[types.Part(text='Say hello')])])


def trace(app):
    with app.state.db.connect() as connection:
        rows = connection.execute('SELECT * FROM traces').fetchall()
    assert len(rows) == 1
    return rows[0]


@pytest.mark.parametrize('code', [429, 500, 503])
async def test_transient_error_retries_once_in_one_trace(client, app, build_id, code, caplog):
    model = worker()
    provider = Provider(model, code)
    result = await app.state.harness.run('hello', build_id, {}, llm=model)
    assert result['reply'] == 'Hello!' and provider.calls == 2
    row = trace(app)
    assert row['status'] == 'ok'
    spans = json.loads(row['spans_json'])
    assert [s for s in spans if s['node'] == 'model_retry'] == [{'node': 'model_retry', 'status': code}]
    # Usage is the sum over both attempts; the failed attempt reported none.
    assert (row['input_tokens'], row['output_tokens']) == (5, 2)
    assert f'HTTP {code}' in caplog.text and SECRET not in caplog.text


@pytest.mark.parametrize('code', [429, 500, 503])
async def test_second_failure_is_llm_unavailable_after_two_calls(client, app, build_id, code, caplog):
    model = worker()
    provider = Provider(model, code, code, code)
    with pytest.raises(RunError) as raised:
        await app.state.harness.run('hello', build_id, {}, llm=model)
    assert raised.value.code == 'llm_unavailable' and provider.calls == 2
    assert SECRET not in raised.value.message and SECRET not in caplog.text
    row = trace(app)
    assert (row['status'], row['error']) == ('error', 'llm_unavailable')
    assert [s['node'] for s in json.loads(row['spans_json'])].count('model_retry') == 1
    with app.state.db.connect() as connection:
        assert SECRET not in str([tuple(r) for r in connection.execute('SELECT * FROM events')])
        assert SECRET not in str(tuple(row))
    assert not app.state.harness.active_builds


@pytest.mark.parametrize('code', [504, 400, 403])
async def test_no_retry_on_deadline_or_client_error(client, app, build_id, code, caplog):
    model = worker()
    provider = Provider(model, code)
    with pytest.raises(RunError) as raised:
        await app.state.harness.run('hello', build_id, {}, llm=model)
    assert raised.value.code == 'llm_unavailable' and provider.calls == 1
    assert 'model_retry' not in trace(app)['spans_json']
    assert SECRET not in caplog.text


async def test_streamed_call_retries_before_first_chunk():
    model = worker()
    provider = Provider(model, 503)
    responses = [r async for r in model.generate_content_async(request(), stream=True)]
    assert provider.calls == 2 and responses[-1].content.parts[0].text == 'Hello!'


async def test_streamed_call_never_retries_after_a_chunk():
    model = worker()
    provider = Provider(model, 503, chunks_before_failure=1)
    seen = []
    with pytest.raises(errors.ServerError):
        async for response in model.generate_content_async(request(), stream=True):
            seen.append(response)
    assert provider.calls == 1 and seen


async def test_early_close_closes_the_provider_stream_at_once():
    model = worker()
    provider = Provider(model, chunks_before_failure=2)
    responses = model.generate_content_async(request(), stream=True)
    await anext(responses)
    await responses.aclose()
    assert provider.calls == 1 and provider.closed


async def test_success_makes_one_call_without_retry_span(client, app, build_id):
    model = worker()
    provider = Provider(model)
    await app.state.harness.run('hello', build_id, {}, llm=model)
    assert provider.calls == 1 and 'model_retry' not in trace(app)['spans_json']


@pytest.mark.parametrize('node,timeout', [('blueprint', 120_000), ('hello', 30_000),
                                          ('context', 30_000), ('revise', 30_000)])
def test_timeouts_unchanged(node, timeout):
    model = ModelRouter(Settings()).llm_for(node)
    assert isinstance(model, RetryingGemini)
    assert model.api_client._api_client._http_options.timeout == timeout
