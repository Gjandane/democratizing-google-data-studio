"""Incremental live checks for the staged workflow; each phase adds its own stage."""
import json
from pathlib import Path
import random
import shutil
import string
import time

from fastapi.testclient import TestClient
import pytest

from dss.data.bigquery import BigQuery
from dss.artifacts.models import Context
from dss.harness.context import Section, assemble, context_repair_context, fit_request
from dss.harness.guardrails import RunError
from dss.harness.nodes import blueprint as blueprint_node, context as context_node
from dss.harness.nodes.style_extract import provider_schema
from dss.harness.nodes.view import blueprint_sql
from dss.render.kits import accent_key
from google.adk.models.llm_request import LlmRequest
from google.genai import types
from .test_backend_flow import check_usage, evidence_dir, live_app, page_shots, trace, usage, validate_recipe
from .test_synthetic_flow import wait

DATA = Path(__file__).parents[1] / 'data'
AOV = 'average_order_value'
SAMPLE_NOTES = ('The sales director reviews net revenue weekly by region. Revenue is net of discounts; '
                'sum revenue and quantity; count distinct order_id for orders.')
# One "other" text: the ratio question itself when the proposal has none, else an ordinary one.
RATIO_OTHER = 'What is the average order value (net revenue / orders) by region?'
OTHER = 'Which product categories sell the most units?'
GPS_NOTES = ('A fleet manager reviews daily distance_km, driving_minutes, idle_minutes and trip_count per vehicle, '
             'and speeding events (speed_kph above speed_limit_kph, duration_seconds) per event_vehicle. Both files '
             'describe the same vans and trucks; stack them into one dataset rather than joining them.')
CHARTS = ('bar', 'time_series', 'pie', 'scatter')
COMPONENT_COLOR, DECORATION_COLOR = '#B91C1C', '#1E3A8A'


class Flow:
    """Drives one build through the API, recording each action's timing, run usage and response status."""

    def __init__(self, app, client, bid):
        self.app, self.client, self.url = app, client, f'/api/builds/{bid}'
        self.timings, self.runs, self.steps = {}, [], []

    def _send(self, stage, method, path, kwargs):
        start = time.monotonic()
        response = getattr(self.client, method)(self.url + path, **kwargs)
        self.steps.append({'stage': stage, 'path': path, 'status': response.status_code})
        return response, start

    def _time(self, stage, start):
        self.timings[stage] = round(self.timings.get(stage, 0) + time.monotonic() - start, 2)

    def call(self, stage, method, path, status=200, **kwargs):
        """A code-only action: no run, no model call."""
        response, start = self._send(stage, method, path, kwargs)
        self._time(stage, start)
        assert response.status_code == status, response.text
        return response.json()

    def act(self, stage, method, path, seconds=300, **kwargs):
        """One agent run: 202, wait until the build is idle, then its trace must be ok and within budget."""
        response, start = self._send(stage, method, path, kwargs)
        assert response.status_code == 202, response.text
        wait(self.app, seconds)
        self._time(stage, start)
        run = {'stage': stage, **usage(self.app, response.json()['run_id'])}
        self.runs.append(run)
        assert run['status'] == 'ok', {k: run[k] for k in ('stage', 'node', 'error')}
        check_usage(run)
        return run

    def get(self, path=''):
        response = self.client.get(self.url + path)
        assert response.status_code == 200, response.text
        return response.json()

    def report(self, label):
        lines = [f'{label}: per run billed input / enforced request bounds / budgets, output, latency']
        for run in self.runs:
            bounds = '+'.join(str(r['input_bound']) for r in run['requests']) or '-'
            budgets = '+'.join(str(r['budget']) for r in run['requests']) or '-'
            lines.append(f"  {run['stage']:<18} {run['node']:<16} in={run['input_tokens']} bound={bounds} "
                         f"budget={budgets} out={run['output_tokens']} {run['latency_ms']} ms {run['status']}")
        lines.append('  stage timings (s): ' + json.dumps(self.timings))
        print('\n'.join(lines))
        return lines


def keep(evidence, flow, folder, facts):
    """Save the run record and the build folder, whether the flow passed or failed."""
    if flow is not None:
        (evidence / 'report.txt').write_text('\n'.join(flow.report(evidence.parent.name)), encoding='utf-8')
        record = {'runs': flow.runs, 'timings': flow.timings, 'steps': flow.steps}
    else:
        record = {}
    (evidence / 'runs.json').write_text(json.dumps({**record, **facts}, indent=2, default=str), encoding='utf-8')
    if folder is not None and folder.exists():
        shutil.copytree(folder, evidence / 'build', dirs_exist_ok=True)


def observe_revisions(monkeypatch, facts):
    """Keep each revise candidate's patch outcome, spec errors and coverage errors as evidence."""
    from dss.harness.nodes import revise as revise_node
    from dss.spec import requirements as req
    log = facts.setdefault('revise_diagnostics', [])
    original_revised, original_validate, original_coverage = revise_node.revised, revise_node.validate_spec, req.coverage_errors

    def revised(document, comments, batch, allowed):
        entry = {'batch': batch.model_dump(mode='json')}
        log.append(entry)
        try:
            return original_revised(document, comments, batch, allowed)
        except Exception as exc:
            entry['patch_error'] = str(exc)[:2000]
            raise

    def validate_spec(*args, **kwargs):
        errors = original_validate(*args, **kwargs)
        if log:
            log[-1].setdefault('spec_errors', []).append(errors)
        return errors

    def coverage_errors(*args, **kwargs):
        errors = original_coverage(*args, **kwargs)
        if log:
            log[-1].setdefault('coverage_errors', []).append(errors)
        return errors

    monkeypatch.setattr(revise_node, 'revised', revised)
    monkeypatch.setattr(revise_node, 'validate_spec', validate_spec)
    monkeypatch.setattr(req, 'coverage_errors', coverage_errors)


def with_ratio(context):
    """The drafted Context plus the ratio KPI average order value = net revenue / orders, unless
    the draft already defines that ratio."""
    body = {k: v for k, v in context.items() if k not in ('revision', 'issues')}
    kpis = list(body['kpis'])

    def measure(field, agg, kpi_id, name):
        for kpi in kpis:
            if kpi['measure'] == {'field': field, 'agg': agg}:
                return kpi['id']
        kpis.append({'id': kpi_id, 'name': name, 'description': f'{agg.upper()}({field})', 'unit': None,
                     'measure': {'field': field, 'agg': agg}, 'ratio': None})
        return kpi_id

    ratio = {'numerator': measure('revenue', 'sum', 'net_revenue', 'Net revenue'),
             'denominator': measure('order_id', 'count_distinct', 'orders', 'Orders')}
    if not any(k['ratio'] == ratio for k in kpis):
        kpis.append({'id': AOV, 'name': 'Average order value', 'description': 'Net revenue / orders',
                     'unit': None, 'measure': None, 'ratio': ratio})
    return {**body, 'kpis': kpis}


def items(spec):
    return {item['id']: item for page in spec['pages'] for item in page['components'] + page['decorations']}


def decide(flow, assessment, issue, alternative):
    return flow.call('blueprint', 'post', '/feasibility/decisions', json={'assessment_id': assessment['id'],
        'decisions': [{'issue_id': issue['id'], 'action': 'accept_alternative', 'alternative_id': alternative}]})


@pytest.mark.live
def test_staged_flow_sample_csv(tmp_path, monkeypatch):
    """Sample CSV: context -> ratio KPI -> outline -> per_section design -> blueprint (ratio blocked,
    numerator/denominator accepted) -> 2+ page prototype -> two comments -> recipe -> dry-run `done`."""
    monkeypatch.setenv('DSS_ENGINE_DRY_RUN', '1')
    app, config, project = live_app(tmp_path)
    evidence = evidence_dir('15.11', 'sample')
    tables, flow, folder, facts = [], None, None, {}
    observe_revisions(monkeypatch, facts)
    with TestClient(app) as client:
        assert client.put('/api/settings', json={'gcp_project_id': project}).status_code == 200
        service = BigQuery(app.state.settings.get())
        bid = client.post('/api/builds', json={'archetype': 'executive', 'mode': 'data', 'title': 'Sales staged flow'}).json()['id']
        flow, folder, facts['build_id'] = Flow(app, client, bid), config.data_dir / 'builds' / bid / 'v1', bid
        try:
            sources = flow.call('connect', 'post', '/sources/upload', status=201,
                                files=[('files', ('sales.csv', (DATA / 'interview_sales.csv').read_bytes(), 'text/csv'))])['sources']
            tables.extend(s['bq_table'] for s in sources)
            flow.act('context', 'post', '/context', seconds=150, json={'notes': SAMPLE_NOTES})
            edited = flow.call('context', 'put', '/context', json=with_ratio(flow.get('/context')))
            assert edited['issues'] == [], edited['issues']
            ratios = {k['id'] for k in edited['kpis'] if k['ratio']}
            assert ratios

            flow.act('outline', 'post', '/context/confirm', seconds=150)
            outline = flow.get('/outline')
            proposed = [q for s in outline['sections'] for q in s['questions'] if ratios & set(q['kpi_refs'])]
            facts['ratio_proposed'] = [q['id'] for q in proposed]
            other = OTHER if proposed else RATIO_OTHER
            flow.act('outline', 'post', '/outline/other', seconds=150,
                     json={'section_id': outline['sections'][-1]['id'], 'text': other})
            outline = flow.get('/outline')
            questions = [q for s in outline['sections'] for q in s['questions']]
            # Recommended picks, the other text (selected by code) and one proposed ratio question ticked.
            tick = proposed[0]['id'] if proposed else None
            selection = [{'id': q['id'], 'selected': q['recommended'] or q['origin'] == 'other' or q['id'] == tick}
                         for q in questions]
            outline = flow.call('outline', 'put', '/outline/selection', json={'questions': selection})
            selected = [q for s in outline['sections'] for q in s['questions'] if q['selected']]
            ratio_ids = [q['id'] for q in selected if ratios & set(q['kpi_refs'])]
            facts.update(other_text=other, ratio_questions=ratio_ids, selected=[q['id'] for q in selected])
            assert ratio_ids, 'no selected question references the ratio KPI'
            assert any(q['origin'] == 'other' for q in selected)

            flow.call('design', 'post', '/outline/confirm')
            design = flow.get('/design')
            if design['page_structure'] != 'per_section':
                design = flow.call('design', 'put', '/design', json={
                    **{k: v for k, v in design.items() if k not in ('revision', 'issues')}, 'page_structure': 'per_section'})
            assert design['page_structure'] == 'per_section' and design['issues'] == [], design

            flow.act('blueprint', 'post', '/design/confirm', seconds=400)
            blueprint, assessment = flow.get('/blueprint'), flow.get('/feasibility')
            facts['blocked_assessment'] = assessment
            rows = [r for r in blueprint['rows'] if r['question_id'] in ratio_ids]
            assert rows and all(r['status'] == 'blocked' for r in rows), rows
            issues = [i for i in assessment['issues'] if any(a['id'] == 'numerator_denominator' for a in i['alternatives'])]
            assert sorted(i['requirement'] for i in issues) == sorted(ratio_ids), issues
            assert all(i['status'] == 'unsupported_app' for i in issues), issues
            decided = assessment
            for issue in issues:  # one per selected ratio question; each choice returns the next assessment
                decided = decide(flow, decided, issue, 'numerator_denominator')
            facts['decided_assessment'] = decided
            assert decided['state'] == 'ready', decided
            rows = [r for r in flow.get('/blueprint')['rows'] if r['question_id'] in ratio_ids]
            assert rows and all(r['status'] == 'ok' for r in rows), rows

            flow.act('prototype', 'post', '/blueprint/accept', seconds=300)
            build = flow.get()
            assert build['stage'] == 'prototype' and set(build['artifacts'].values()) == {'confirmed'}, build
            spec = flow.get('/spec')
            facts['view'] = spec['datasource']['table']
            assert len(spec['pages']) >= 2, [p['name'] for p in spec['pages']]
            page_shots(client.get(flow.url + '/prototype').text, spec, evidence, 'prototype')
            for page in spec['pages']:
                background = client.get(flow.url + f"/files/background_p{page['index']}.png")
                assert background.status_code == 200
                (evidence / f"background_p{page['index']}.png").write_bytes(background.content)

            chart = next(c for p in spec['pages'] for c in p['components'] if c['type'] in CHARTS)
            kinds = {}
            for d in (d for p in spec['pages'] for d in p['decorations']):
                kinds.setdefault(d['kind'], d)  # the first page's
            decoration = next(kinds[k] for k in ('band', 'panel', 'title') if k in kinds)
            comments = [('comment_component', chart, f'Use {COMPONENT_COLOR} as the color of this chart.'),
                        ('comment_decoration', decoration, f'Use a dark blue accent ({DECORATION_COLOR}) for this component.')]
            for stage, target, text in comments:
                before = items(flow.get('/spec'))
                flow.act(stage, 'post', '/comments', json={'comments': [{'component_id': target['id'], 'text': text}]})
                after = items(flow.get('/spec'))
                assert after.keys() == before.keys()
                assert [i for i in after if after[i] != before[i]] == [target['id']], (stage, target['id'])
                if stage == 'comment_component':
                    assert COMPONENT_COLOR in [c.upper() for c in after[target['id']]['colors'] or []], after[target['id']]
                else:
                    value = after[target['id']]['style'].get(accent_key(target['kind'])) or ''
                    assert value.upper() == DECORATION_COLOR, after[target['id']]
            spec = flow.get('/spec')
            page_shots(client.get(flow.url + '/prototype').text, spec, evidence, 'revised')

            compiled = flow.call('recipe', 'post', '/recipe')
            recipe = validate_recipe((folder / 'recipe.jsonl').read_text(encoding='utf-8'))
            assert compiled['op_count'] == len(recipe) - 1
            assert sum(op['op'] == 'add_page' for op in recipe[1:]) == len(spec['pages']) - 1
            flow.act('build', 'post', '/run', seconds=900)
            build = flow.get()
            assert build['stage'] == 'done', build
            events = [json.loads(line) for line in (folder / 'events.jsonl').read_text(encoding='utf-8').splitlines() if line]
            finished = [e for e in events if e['event'] == 'run_finished']
            facts['engine'] = finished
            assert len(finished) == 1 and finished[0]['status'] == 'ok', finished
            ops = [e for e in events if e['event'] == 'op_finished']
            assert [o['op_id'] for o in ops] == [op['id'] for op in recipe[1:]]
            assert all(o['status'] == 'skipped' for o in ops), 'engine was not in dry-run mode'
        finally:
            try:
                keep(evidence, flow, folder, facts)
            finally:  # cleanup even when saving evidence fails (e.g. a Windows file lock)
                response = client.get(flow.url + '/blueprint')
                drafted = response.json() if response.status_code == 200 else None
                for table in tables + [facts.get('view'), (drafted or {}).get('view_table')]:
                    if table:
                        service.client.delete_table(table, not_found_ok=True)


@pytest.mark.live
def test_staged_flow_gps_union(tmp_path):
    """Two GPS-style CSVs with distinct schemas reach a blueprint whose view stacks them (union)."""
    app, config, project = live_app(tmp_path)
    evidence = evidence_dir('15.11', 'gps')
    tables, flow, folder, facts = [], None, None, {}
    with TestClient(app) as client:
        assert client.put('/api/settings', json={'gcp_project_id': project}).status_code == 200
        service = BigQuery(app.state.settings.get())
        bid = client.post('/api/builds', json={'archetype': 'operational', 'mode': 'data', 'title': 'Fleet GPS'}).json()['id']
        flow, folder, facts['build_id'] = Flow(app, client, bid), config.data_dir / 'builds' / bid / 'v1', bid
        try:
            files = [('files', (f'gps_{n}.csv', (DATA / f'gps_{n}.csv').read_bytes(), 'text/csv'))
                     for n in ('activity_summary', 'route_speeding_events')]
            sources = flow.call('connect', 'post', '/sources/upload', status=201, files=files)['sources']
            tables.extend(s['bq_table'] for s in sources)
            assert len(sources) == 2
            flow.act('context', 'post', '/context', seconds=150, json={'notes': GPS_NOTES})
            context = flow.get('/context')
            assert context['issues'] == [], context['issues']
            flow.act('outline', 'post', '/context/confirm', seconds=150)
            flow.call('design', 'post', '/outline/confirm')
            assert flow.get('/design')['issues'] == []
            flow.act('blueprint', 'post', '/design/confirm', seconds=400)
            blueprint, assessment = flow.get('/blueprint'), flow.get('/feasibility')
            facts.update(drafted_view_sources=blueprint['view_sources'], assessment=assessment)
            if not blueprint['view_sources']['union']:
                issue = next(i for i in assessment['issues'] if any(a['id'] == 'union' for a in i['alternatives']))
                facts['decided_assessment'] = decide(flow, assessment, issue, 'union')
                blueprint = flow.get('/blueprint')
            facts['view_sources'] = blueprint['view_sources']
            assert blueprint['view_sources']['union'] and not blueprint['view_sources']['joins'], blueprint['view_sources']
            # The code-built union view resolves on BigQuery, with both schemas and the dataset_name column.
            draft, context = blueprint_node.load(folder), context_node.load(folder)
            sql = blueprint_sql(context_node.sources(app.state.db, bid), draft.view_sources, draft.derived_fields,
                                context_fields=[f.name for f in context.derived_fields])
            (evidence / 'union_view.sql').write_text(sql, encoding='utf-8')
            names = {f.name for f in service.dry_run(sql)}
            facts['union_columns'] = sorted(names)
            assert {'dataset_name', 'distance_km', 'speed_kph'} <= names, names
        finally:
            try:
                keep(evidence, flow, folder, facts)
            finally:
                for table in tables:
                    service.client.delete_table(table, not_found_ok=True)


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
