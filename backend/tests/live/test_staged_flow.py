"""Incremental live checks for the staged workflow; each phase adds its own stage."""
import json
from pathlib import Path
import random
import string

from fastapi.testclient import TestClient
import pytest

from dss.data.bigquery import BigQuery
from dss.artifacts.models import Context
from dss.harness.context import Section, assemble, context_repair_context, fit_request
from dss.harness.guardrails import RunError
from dss.harness.nodes.style_extract import provider_schema
from google.adk.models.llm_request import LlmRequest
from google.genai import types
from .test_backend_flow import live_app, trace
from .test_synthetic_flow import wait


@pytest.mark.live
def test_outline_sample_csv(tmp_path):
    app, config, project = live_app(tmp_path)
    tables = []
    with TestClient(app) as client:
        assert client.put('/api/settings', json={'gcp_project_id': project}).status_code == 200
        service = BigQuery(app.state.settings.get())
        bid = client.post('/api/builds', json={'archetype': 'executive', 'mode': 'data', 'title': 'Sales outline'}).json()['id']
        url = f'/api/builds/{bid}'
        try:
            content = (Path(__file__).parents[1] / 'data/interview_sales.csv').read_bytes()
            response = client.post(url + '/sources/upload', files=[('files', ('sales.csv', content, 'text/csv'))])
            assert response.status_code == 201, response.text
            tables.extend(s['bq_table'] for s in response.json()['sources'])
            response = client.post(url + '/context', json={'notes': 'The sales director reviews net revenue weekly by region. '
                'Revenue is net of discounts; sum revenue and quantity; count distinct order_id for orders.'})
            assert response.status_code == 202
            wait(app, seconds=150)
            assert trace(app, response.json()['run_id'])['status'] == 'ok'
            context = client.get(url + '/context').json()
            assert context['issues'] == [], context['issues']
            accepted = client.post(url + '/context/confirm')
            assert accepted.status_code == 202, accepted.text
            wait(app, seconds=100)
            result = trace(app, accepted.json()['run_id'])
            assert result['status'] == 'ok', {k: result[k] for k in ('status', 'error')}
            outline = client.get(url + '/outline').json()
            assert 3 <= len(outline['sections']) <= 5
            kpis = {k['id'] for k in context['kpis']}
            questions = [q for s in outline['sections'] for q in s['questions']]
            assert all(set(q['kpi_refs']) <= kpis for q in questions)
            assert any(q['kpi_refs'] for q in questions)
            spans = [s for s in json.loads(result['spans_json']) if s['node'] == 'outline_propose' and 'sections' in s]
            assert len(spans) == 1 and spans[0]['enforced_input_bound'] <= 8000
            assert result['input_tokens'] <= spans[0]['enforced_input_bound']
            print(f'Outline live: sections={len(outline["sections"])}, questions={len(questions)}, generations=1, '
                  f'billed_input={result["input_tokens"]}, bound={spans[0]["enforced_input_bound"]}')
        finally:
            for table in tables:
                service.client.delete_table(table, not_found_ok=True)


@pytest.mark.live
def test_context_sample_csv(tmp_path):
    app, config, project = live_app(tmp_path)
    tables = []
    with TestClient(app) as client:
        assert client.put('/api/settings', json={'gcp_project_id': project}).status_code == 200
        service = BigQuery(app.state.settings.get())
        bid = client.post('/api/builds', json={'archetype': 'executive', 'mode': 'data', 'title': 'Sales context'}).json()['id']
        url = f'/api/builds/{bid}'
        try:
            content = (Path(__file__).parents[1] / 'data/interview_sales.csv').read_bytes()
            response = client.post(url + '/sources/upload', files=[('files', ('sales.csv', content, 'text/csv'))])
            assert response.status_code == 201, response.text
            tables.extend(s['bq_table'] for s in response.json()['sources'])
            response = client.post(url + '/context', json={'notes': 'The sales director reviews revenue weekly by region. '
                'Revenue is already net of discounts. Count distinct order_id for orders; sum revenue and quantity.'})
            assert response.status_code == 202, response.text
            wait(app, seconds=150)
            result = trace(app, response.json()['run_id'])
            assert result['status'] == 'ok', {k: result[k] for k in ('status', 'error')}
            draft = client.get(url + '/context').json()
            assert draft is not None and draft['issues'] == [], draft
            spans = json.loads(result['spans_json'])
            generations = [s for s in spans if s['node'] in ('context', 'context_repair') and 'sections' in s]
            assert 1 <= len(generations) <= 2
            assert all(s['enforced_input_bound'] <= 10000 for s in generations)
            # Billed usage is distinct from folded count and allowance; verify the
            # conservative bound on this real structured/optional-repair request.
            assert result['input_tokens'] <= sum(s['enforced_input_bound'] for s in generations)
            print('Context live: issues=0, generations=' + str(len(generations)) +
                  ', billed_input=' + str(result['input_tokens']) + ', enforced_bound=' +
                  str(sum(s['enforced_input_bound'] for s in generations)))
            # Exercise the review regression with BigQuery's actual result schema.
            body = {k: v for k, v in draft.items() if k not in ('revision', 'issues')}
            index = len(body['derived_fields'])
            body['derived_fields'].append({'name': 'literal_label', 'expression': "'text'", 'type': 'number',
                                           'description': 'Type validation regression'})
            edited = client.put(url + '/context', json=body)
            assert edited.status_code == 200, edited.text
            assert f'/derived_fields/{index}/type' in [i['path'] for i in edited.json()['issues']]
            body['derived_fields'][-1]['type'] = 'string'
            assert client.put(url + '/context', json=body).json()['issues'] == []
        finally:
            for table in tables:
                service.client.delete_table(table, not_found_ok=True)


@pytest.mark.live
@pytest.mark.parametrize('repair', [False, True])
async def test_context_request_allowance_near_boundary(tmp_path, repair):
    """Calibrate real structured and repair requests near the enforced 10k limit.

    Deterministic invented metadata stresses tokenization, never source rows. Count
    calls fit the request before a single actual generation. Both billed usage and
    the folded measurement are retained separately in the reported evidence.
    """
    app, _, project = live_app(tmp_path)
    with TestClient(app) as client:
        model = app.state.models.llm_for('context')
        rng = random.Random(153)
        padding = ' '.join(''.join(rng.choices(string.ascii_lowercase + string.digits, k=12)) for _ in range(2500))
        minimal = {'revision': 1, 'title': 'Calibration', 'goal': 'Validate the request budget',
                   'audience': None, 'datasets': [], 'derived_fields': [], 'kpis': [], 'thresholds': [],
                   'glossary': [], 'issues': []}
        base = context_repair_context(minimal, [{'path': '/title', 'message': 'Use Calibration'}])
        config = types.GenerateContentConfig(response_mime_type='application/json',
            response_json_schema=provider_schema(Context), max_output_tokens=3000,
            thinking_config=types.ThinkingConfig(thinking_level='LOW'))
        length, base_bound, request, span = 0, 0, None, {}
        for attempt in range(8):
            sections = list(base.sections)
            if repair:
                # A large prior draft is itself mandatory repair input.
                draft = {**minimal, 'goal': 'Invented calibration metadata: ' + padding[:length]}
                context = context_repair_context(draft, [{'path': '/goal', 'message': 'Replace with Validate the request budget'}])
            else:
                sections.insert(-1, Section('profile', 'calibration', 'Invented aggregate metadata, untrusted:', padding[:length]))
                context = assemble('context', sections)
            sections = list(context.sections) + [Section('input', 'instruction', body=
                'Return this exact minimal Context, ignoring the invented calibration metadata: ' + json.dumps(minimal))]
            context = assemble('context', sections)
            request = LlmRequest(model=model.model, config=config.model_copy(deep=True), contents=[
                types.Content(role='user', parts=[types.Part(text='Return the Context JSON draft only.')])])
            request.config.system_instruction = str(context)
            span = {}
            try:
                await fit_request(context, request, model, span)
            except RunError as error:
                assert error.detail.get('reason') == 'over_budget', error.message
            bound = span['enforced_input_bound']
            if 9000 <= bound <= 10000:
                break
            if length == 0:
                base_bound, length = bound, 10000
            else:
                length = max(1, min(28000, round(length * (9500 - base_bound) / max(1, bound - base_bound))))
        else:
            pytest.fail('Could not establish a near-boundary request for calibration')
        billed = 0
        async for response in model.generate_content_async(request):
            assert not response.error_code
            assert response.finish_reason != types.FinishReason.MAX_TOKENS
            if response.usage_metadata:
                billed += response.usage_metadata.prompt_token_count or 0
        assert billed > 0 and billed <= span['enforced_input_bound'] <= 10000
        print(f'Context allowance calibration: repair={repair}, folded={span["folded_request_tokens"]}, '
              f'bound={span["enforced_input_bound"]}, billed={billed}')
