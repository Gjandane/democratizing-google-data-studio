"""Task 24.11: real two-stage reference fidelity with retained synthetic inputs.

Run explicitly with -m live. Every run retains evidence, including failures; no
fallback or unresolved feasibility decision is accepted as a successful check.
The separate user visual STOP is never inferred from pytest success.
"""
import hashlib
import base64
import json
import itertools
import os
import re
import time
from contextlib import aclosing
from contextvars import ContextVar
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dss.data.bigquery import BigQuery
from dss.harness.guardrails import RunError, check_reply
from dss.harness.nodes import designer, reference_brief, synthetic_generate
from dss.spec import requirements
from dss.spec.capabilities import Checker, load_registry
from dss.spec.models import CHART_TYPES, CONTROL_TYPES, SYNTHETIC_LABEL, TYPES
from .test_backend_flow import check_usage, evidence_dir, live_app, page_shots, trace, usage, validate_recipe
from .test_staged_flow import Flow, keep
from .test_synthetic_flow import wait

DATA = Path(__file__).parents[1] / 'data/reference_design'
HASHES = {
    'electricity-access.jpg': '1c30b41832d16d21fcb74827d5b13aa6bd2861a978c647761ee07200f05e32a9',
    'sample.csv': 'eb6e57703776bd8f4514922733a9ef1c21525ce1f6f00cdbc57c702331820c82',
    'generation.json': '413051729b9ced475b43102abdb42de59c9f529993024db0b933b59ab52816ab',
}
NOTES = (
    'A global development analyst tracks access to electricity: the average access_pct, urban_pct and '
    'rural_pct, and the total people_without_access, by region and country for every year from 2000 to 2019. '
    'They pick regions from a list, compare urban and rural access over time, and follow the people without '
    'access year by year. Every row is invented synthetic sample data, not actual electricity statistics.'
)
RECREATE_NOTES = (
    ' Required report grouping: the FIRST section/page recreates the reference composition: '
    'headline left, region list left, access percentage scorecard, real-geography globe centre, '
    'people_without_access yearly bar at the bottom, and ONE combined urban_pct/rural_pct area chart '
    'in the right panel. Keep all those reference observations together on page 1. '
    'A SECOND section/page contains additional country and regional comparison analysis. '
    'The Philippines, Morocco, Fiji and Belize panels are approved aliases for the SAME combined '
    'urban/rural chart; do not split them into country charts or derive country-filtered metrics.'
    # Substitution/composition prose lives here, not in INSTRUCTIONS (24.11 ruling, change 2026-10-26):
    # a prose instruction sentence becomes its own requirement row (run 20261026-052835).
    ' Approved substitution: replace ALL FOUR observed country panels (Philippines, Morocco, Fiji, '
    'Belize) with exactly ONE native urban/rural area chart using AVG(urban_pct) and AVG(rural_pct) '
    'for all countries together over year. The four country definitions in the reference instructions '
    'are aliases for that SAME shared chart, not requests for separate country charts, country filters '
    'or derived fields. Retain the reference composition on page 1: headline and region list left, '
    'globe centre, yearly people-without-access chart at the bottom, shared urban/rural area chart in '
    'the right panel.'
)
# architecture.md#Recreate observation completion surface, one definition per clause. The region
# list is a native fixed-size list; the per-country small multiples (no per-chart filter) become
# one urban/rural area chart, the user's explicit substitution.
INSTRUCTIONS = (
    'Region Selector = region, chart fixed_size_list. Region = region. Country = country. '
    'Access to electricity = AVG(access_pct), unit %, date grain year using year. '
    'have access to electricity = AVG(access_pct), unit %, date grain year using year. '
    'People without access to electricity = SUM(people_without_access), date grain year using year. '
    'Philippines = AVG(urban_pct) and AVG(rural_pct), unit %, chart area, date grain year using year. '
    'Morocco = AVG(urban_pct) and AVG(rural_pct), unit %, chart area, date grain year using year. '
    'Fiji = AVG(urban_pct) and AVG(rural_pct), unit %, chart area, date grain year using year. '
    'Belize = AVG(urban_pct) and AVG(rural_pct), unit %, chart area, date grain year using year. '
    'Urban = AVG(urban_pct), unit %, date grain year using year. '
    'Rural = AVG(rural_pct), unit %, date grain year using year.'
)


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + '\n', encoding='utf-8')


INTAKE_REASONS = {
    'accessDenied', 'backendError', 'billingNotEnabled', 'blocked', 'duplicate',
    'internalError', 'invalid', 'invalidQuery', 'jobBackendError', 'jobInternalError',
    'jobRateLimitExceeded', 'notFound', 'quotaExceeded', 'rateLimitExceeded',
    'resourcesExceeded', 'responseTooLarge', 'stopped', 'tableUnavailable', 'timeout',
}


def intake_exception(exc):
    """An explicit projection: never serialize exception text, args or provider messages."""
    result = {'exception_class': type(exc).__name__}
    code = getattr(exc, 'code', None)
    if isinstance(code, int) and not isinstance(code, bool) and 100 <= code <= 599:
        result['http_status'] = int(code)
    entries = getattr(exc, 'errors', None)
    if isinstance(entries, (list, tuple)):
        result['provider_reasons'] = sorted({entry['reason'] for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get('reason'), str)
            and entry['reason'] in INTAKE_REASONS})
    return result


def observe_intake(monkeypatch, app, bid, evidence, secrets):
    """Scope observation to this synthetic action; keep calls, exceptions and cleanup unchanged.

    The returned finalizer reads the reserved job after runtime cleanup has settled. A missing
    remote record is only unavailable metadata, never evidence that submission did not occur.
    """
    path = evidence / 'intake.json'
    record = {'phases': [], 'job_metadata': {'availability': 'unavailable'},
              'raw_provider_text_retained': False}
    services = []
    factory = app.state.bigquery_factory
    register = synthetic_generate.register_source
    load = synthetic_generate.load
    phase_started = 0.0

    def save():
        try:
            check_reply(json.dumps(record), secrets)
            dump(path, record)
        except Exception:
            # Diagnostic I/O/guard errors must not replace the original operation's exception.
            pass

    def timed(phase, operation, *args, **kwargs):
        nonlocal phase_started
        entry = {'phase': phase, 'status': 'running'}
        record['phases'].append(entry)
        started = phase_started = time.monotonic()
        try:
            result = operation(*args, **kwargs)
            entry['status'] = 'ok'
            return result
        except BaseException as exc:
            entry.update(status='failed', **intake_exception(exc))
            raise  # Observed here, before synthetic_generate sanitizes the exception.
        finally:
            entry['seconds'] = round(time.monotonic() - started, 3)
            save()

    def observed_factory(config):
        service = timed('client_creation', factory, config)
        services.append(service)
        for name, phase in (('load_typed_csv', 'typed_load'), ('profile', 'profile')):
            original = getattr(service, name)

            def observed(*args, _phase=phase, _original=original, **kwargs):
                return timed(_phase, _original, *args, **kwargs)
            monkeypatch.setattr(service, name, observed)
        return service

    def observed_register(db, config, build_id, *args):
        if build_id == bid:
            return timed('registration', register, db, config, build_id, *args)
        return register(db, config, build_id, *args)

    def observed_load(*args):
        try:
            return load(*args)
        except synthetic_generate.Failure as exc:
            # Row-count guards run after the service call returns. Attribute their failure
            # to that same phase; service exceptions already have their original record.
            entry = record['phases'][-1] if record['phases'] else None
            if entry and entry['status'] == 'ok' and entry['phase'] in ('typed_load', 'profile'):
                entry.update(status='failed', failure_boundary='row_count_guard',
                             seconds=round(time.monotonic() - phase_started, 3), **intake_exception(exc))
                save()
            raise

    monkeypatch.setattr(app.state, 'bigquery_factory', observed_factory)
    monkeypatch.setattr(synthetic_generate, 'register_source', observed_register)
    monkeypatch.setattr(synthetic_generate, 'load', observed_load)
    save()

    def finish():
        try:
            with app.state.db.connect() as connection:
                row = connection.execute(
                    'SELECT bq_table,bq_location,state,retry_ready FROM synthetic_generations '
                    'WHERE build_id=? AND generation_key=?', (bid, 'electricity_fixture')).fetchone()
            if row is not None:
                record.update(load_job_id=BigQuery.load_job_id(row['bq_table']), location=row['bq_location'],
                              generation_state=row['state'], cleanup_ready=bool(row['retry_ready']))
                if services:
                    try:
                        # A bounded read only, after the action; no submission, cancellation or retry.
                        job = services[0].client.get_job(record['load_job_id'],
                            location=row['bq_location'], timeout=10, retry=None)
                        metadata = {'availability': 'available',
                                    'state': job.state if job.state in ('PENDING', 'RUNNING', 'DONE') else 'unknown',
                                    'failed': bool(job.error_result)}
                        metadata['timestamps'] = {name: value.isoformat() for name in ('created', 'started', 'ended')
                                                  if (value := getattr(job, name, None)) is not None}
                        metadata['provider_reasons'] = sorted({entry['reason']
                            for entry in [job.error_result or {}, *(job.errors or [])]
                            if isinstance(entry, dict) and isinstance(entry.get('reason'), str)
                            and entry['reason'] in INTAKE_REASONS})
                        record['job_metadata'] = metadata
                    except Exception as exc:
                        record['job_metadata'].update(intake_exception(exc))
        except Exception as exc:
            record['diagnostic_error'] = intake_exception(exc)
        finally:
            save()
    return finish


class RecordedFlow(Flow):
    def act(self, stage, method, path, seconds=300, **kwargs):
        """Flow.act, except that a request refused over its budget before any provider call (its span's
        reason `over_budget`, as the reference HTML repair does) is not counted as a sent request."""
        print(f'  starting {stage}', flush=True)
        try:
            response, start = self._send(stage, method, path, kwargs)
            assert response.status_code == 202, response.text
            wait(self.app, seconds)
            self._time(stage, start)
            run = {'stage': stage, **usage(self.app, response.json()['run_id'])}
            self.runs.append(run)
            assert run['status'] == 'ok', {k: run[k] for k in ('stage', 'node', 'error')}
            spans = [s for s in json.loads(trace(self.app, run['run_id'])['spans_json'] or '[]') if 'sections' in s]
            for request, span in zip(run['requests'], spans):
                if span['node'] == 'reference_html' and span.get('attempt') == 2:
                    assert span['input_budget'] == 24000, span
                    request['budget'] = 24000
            sent = [r for r, s in zip(run['requests'], spans) if s.get('reason') != 'over_budget' or s.get('input_tokens')]
            check_usage({**run, 'requests': sent})
            return run
        finally:
            print(f'  finished {stage}: {self.timings.get(stage)} seconds', flush=True)


def failed_draft_shot(path, html, width, height):
    """Best-effort local screenshot using the runtime's offline, script-disabled surface."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(timeout=10000)
        try:
            context = browser.new_context(java_script_enabled=False, service_workers='block',
                                          viewport={'width': width, 'height': min(max(height, 900), 20000)})
            context.route('**/*', lambda route: route.abort())
            page = context.new_page()
            page.set_content(html, wait_until='load', timeout=10000)
            page.screenshot(path=str(path), timeout=10000)
        finally:
            browser.close()


def save_failed_draft(evidence, name, html, width, fonts, measured, secrets):
    """Never persist provider replies: only guarded, sanitized measured HTML and errors."""
    try:
        check_reply(html, secrets)
        clean = designer.design_page.sanitize(html, fonts=fonts)
        document = designer.design_page._document(clean, width)
        errors = json.dumps(measured.errors, ensure_ascii=False)
        check_reply(document, secrets)
        check_reply(errors, secrets)
    except RunError:
        return
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / f'{name}.html').write_text(document, encoding='utf-8')
    dump(evidence / f'{name}.errors.json', measured.errors)
    try:
        failed_draft_shot(evidence / f'{name}.png', document, width, measured.height)
    except Exception:
        pass  # Missing browser/screenshot must not replace the measured design failure.


def observe_generation(monkeypatch, calls, *, evidence=None, secrets=()):
    """Observe real generation, including thinking/transport retries; never change requests or answers."""
    from google.adk.models.google_llm import Gemini
    from google.genai import types

    active = ContextVar('reference_comparison_call', default=None)
    registered = {}
    provider_generate = Gemini.generate_content_async

    async def provider(self, request, stream=False):
        call = active.get()
        attempt = None
        if call is not None:
            attempt = {'attempt': len(call['transport_attempts']) + 1, 'responses': []}
            call['transport_attempts'].append(attempt)
        started = time.monotonic()
        try:
            async with aclosing(provider_generate(self, request, stream=stream)) as responses:
                async for response in responses:
                    if attempt is not None:
                        version = response.model_version
                        attempt['responses'].append({
                            'finish_reason': response.finish_reason.value
                                if isinstance(response.finish_reason, types.FinishReason) else None,
                            'truncated': response.finish_reason == types.FinishReason.MAX_TOKENS
                                or response.error_code == 'MAX_TOKENS',
                            'error': bool(response.error_code),
                            'model_version': version if isinstance(version, str)
                                and re.fullmatch(r'[A-Za-z0-9._/-]{1,120}', version) else None,
                        })
                    yield response
        except BaseException as exc:
            if attempt is not None:
                attempt['exception_class'] = type(exc).__name__
                code = getattr(exc, 'code', None)
                if isinstance(code, int) and not isinstance(code, bool) and 100 <= code <= 599:
                    attempt['http_status'] = code
            raise
        finally:
            if attempt is not None:
                attempt['seconds'] = round(time.monotonic() - started, 3)

    monkeypatch.setattr(Gemini, 'generate_content_async', provider)
    if evidence is not None:
        original_measure = designer.design_page.measure
        sequence = itertools.count(1)

        def measured(html, slots, width, **kwargs):
            result = original_measure(html, slots, width, **kwargs)
            if result.errors:
                save_failed_draft(evidence, f'failed-draft-{next(sequence)}', html, width,
                                  kwargs.get('fonts', ()), result, secrets)
            return result

        monkeypatch.setattr(designer.design_page, 'measure', measured)
    for module in (reference_brief, designer):
        original = module._generate
        original_fit = module.fit_request

        def count_wrapper(original_fit):
            async def counted(memory, request, model, span):
                call = {'stage': span['node'], 'page': span['page'], 'attempt': span['attempt'],
                        'model': model.model, 'output_limit': request.config.max_output_tokens,
                        'requested_thinking': request.config.thinking_config.thinking_level.value,
                        'images': sum(p.inline_data is not None for c in request.contents for p in c.parts),
                        'request_sha256': hashlib.sha256(request.model_dump_json(exclude_none=True).encode()).hexdigest(),
                        'usage': [], 'transport_attempts': [], 'generation_started': False,
                        'truncated': None, 'status': 'counting'}
                calls.append(call)
                registered[id(request)] = call
                started = time.monotonic()
                try:
                    return await original_fit(memory, request, model, span)
                except BaseException as exc:
                    call.update(status='count_failed', exception_class=type(exc).__name__)
                    raise
                finally:
                    call['count_seconds'] = round(time.monotonic() - started, 3)
                    call['input_budget'] = memory.budget
                    call['enforced_input_bound'] = span.get('enforced_input_bound')
            return counted

        monkeypatch.setattr(module, 'fit_request', count_wrapper(original_fit))

        def wrapper(original):
            async def timed(model, request, usage, limit=16000):
                started = time.monotonic()
                call = registered.pop(id(request))
                call.update(generation_started=True, status='generating')
                token = active.set(call)

                async def record(metadata):
                    call['usage'].append({'input': metadata.prompt_token_count or 0,
                                          'output': metadata.candidates_token_count or 0,
                                          'thinking': metadata.thoughts_token_count,
                                          'output_including_thinking': None if metadata.thoughts_token_count is None
                                              else (metadata.candidates_token_count or 0) + metadata.thoughts_token_count})
                    await usage(metadata)
                try:
                    result = await original(model, request, record, limit)
                    call.update(status='returned', truncated=result[1])
                    return result
                except BaseException as exc:
                    call.update(status='generation_failed', exception_class=type(exc).__name__)
                    raise
                finally:
                    active.reset(token)
                    call['seconds'] = round(time.monotonic() - started, 3)
            return timed
        monkeypatch.setattr(module, '_generate', wrapper(original))


def stage_evidence(app, flow):
    return [{'stage': run['stage'], 'run_id': run['run_id'],
             'spans': json.loads(trace(app, run['run_id'])['spans_json'] or '[]')}
            for run in flow.runs]


def assert_design_stages(app, run, spec, mode, models, pages=None, facts=None):
    assert run['status'] == 'ok', {k: run.get(k) for k in ('stage', 'node', 'error')}
    spans = json.loads(trace(app, run['run_id'])['spans_json'] or '[]')
    failed = [s for s in spans if s['node'] in ('designer_fallback', 'redesign_failed', 'reference_html_timeout')]
    expected = pages or {p['index'] for p in spec['pages']}
    if mode == 'none':
        # Existing no-reference behavior (task 24.8 If): a later page may fall back to the kit; recorded, not
        # failed. Page 1 still requires its planner design.
        later = {i for i in expected if i > 1 and not spec['pages'][i - 1].get('design')}
        facts.setdefault('later_page_fallbacks', []).extend(
            {'page': i, 'spans': [s for s in failed if s.get('page') == i]} for i in sorted(later))
        failed = [s for s in failed if s.get('page') not in later]
        expected -= later
    assert not failed, spans
    assert all(spec['pages'][i - 1].get('design') for i in expected), 'kit fallback'
    if mode == 'none':
        assert not any(s['node'] in ('reference_brief', 'reference_html') for s in spans)
        assert expected <= {s['page'] for s in spans if s['node'] == 'designer'}
    else:
        assert not any(s['node'] == 'designer' for s in spans)
        for node, model, limit, seconds in (
            ('reference_brief', models.planner_model, 4000, 120),
            ('reference_html', models.worker_model, 16000, 600),
        ):
            stages = [s for s in spans if s['node'] == node]
            assert {s['page'] for s in stages} == expected, stages
            for span in stages:
                assert span['model'] == model and span['images'] == 1, span
                budget = 24000 if node == 'reference_html' and span['attempt'] == 2 else 12000
                assert span['input_budget'] == budget, span
                assert 0 < span['enforced_input_bound'] <= budget, span
                assert 0 < span['output_tokens'] <= limit, span
                assert span.get('stage_duration_ms', span['duration_ms']) <= seconds * 1000, span
                assert not span.get('reason') and not span.get('truncated'), span
        assert all(spec['pages'][i - 1]['design']['model'] == models.worker_model for i in expected)
    assert any(s['node'] == 'publish' and not s.get('coverage_errors') for s in spans), spans


def coverage(app, bid, folder):
    snapshot = requirements.inputs(app.state.db, bid, folder)
    ledger, checker, bindings = requirements.load(folder), Checker(load_registry()), {}
    errors = requirements.coverage_errors(snapshot, ledger, checker, bindings=bindings)
    return {'errors': errors, 'bindings': bindings,
            'approved': reference_brief.report(snapshot, ledger, checker),
            'image_requirements': [r.id for r in ledger.requirements if r.source.kind == 'image']}


def all_issues(app, bid, folder, monkeypatch):
    """The full issue list behind a scope refusal, for the decision STOP; never decides anything."""
    with monkeypatch.context() as m:
        m.setattr(requirements, 'MAX_ISSUES', 1000)
        snapshot = requirements.inputs(app.state.db, bid, folder)
        found = requirements.evaluate(snapshot, requirements.load(folder), Checker(load_registry()))
    return [i.model_dump(mode='json') for i in found.issues]


def capture(flow, folder, evidence, label):
    spec = flow.get('/spec')
    html = flow.client.get(flow.url + '/prototype').text
    (evidence / f'{label}.html').write_text(html, encoding='utf-8')
    dump(evidence / f'{label}.spec.json', spec)
    shots = page_shots(html, spec, evidence, label)
    reference = flow.get('/reference-images')
    if label == 'prototype' and reference is not None:
        comparison(evidence, shots[0], reference['mode'])
    flow.call('recipe', 'post', '/recipe')
    recipe_text = (folder / 'recipe.jsonl').read_text(encoding='utf-8')
    (evidence / f'{label}.recipe.jsonl').write_text(recipe_text, encoding='utf-8')
    recipe = validate_recipe(recipe_text)
    slots = [c for p in spec['pages'] for c in p['components']]
    dump(evidence / f'{label}.native-slots.json', [
        {'page': p['index'], **{key: c[key] for key in
         ('id', 'type', 'label', 'field', 'dimensions', 'metrics', 'date_dimension', 'breakdown',
          'sort', 'options', 'box') if key in c}}
        for p in spec['pages'] for c in p['components'] if c['type'] in (*CHART_TYPES, *CONTROL_TYPES)
    ])
    emitted = {op['component_id'] for op in recipe[1:] if op['op'] in ('add_chart', 'add_control')}
    assert emitted == {c['id'] for c in slots if c['type'] in (*CHART_TYPES, *CONTROL_TYPES)}, (emitted, slots)
    proof = coverage(flow.app, flow.url.rsplit('/', 1)[1], folder)
    dump(evidence / f'{label}.coverage.json', proof)
    assert proof['errors'] == [], proof['errors']
    assert spec['datasource']['synthetic'] is True
    assert SYNTHETIC_LABEL in html, 'protected synthetic footer absent'
    return spec, proof


def comparison(evidence, prototype, mode):
    """A standalone, labelled comparison; each original image remains unchanged."""
    from playwright.sync_api import sync_playwright
    reference = base64.b64encode((DATA / 'electricity-access.jpg').read_bytes()).decode('ascii')
    generated = base64.b64encode(prototype.read_bytes()).decode('ascii')
    html = ('<!doctype html><meta charset="utf-8"><style>'
            'body{margin:0;padding:20px;background:#e2e8f0;font:20px Arial}'
            'main{display:flex;gap:20px}section{width:1000px}img{width:100%}'
            'h2{font-size:22px}p{font-size:16px}</style>'
            '<main><section><h2>User-supplied reference</h2><p>Visual reference; values are not source data.</p>'
            f'<img src="data:image/jpeg;base64,{reference}"></section>'
            f'<section><h2>Generated {mode} prototype — approval pending</h2>'
            '<p>Invented synthetic sample data; native chart/control slots.</p>'
            f'<img src="data:image/png;base64,{generated}"></section></main>')
    (evidence / 'side-by-side.html').write_text(html, encoding='utf-8')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 2060, 'height': 1000})
            page.set_content(html, wait_until='load')
            page.screenshot(path=str(evidence / 'side-by-side.png'), full_page=True)
        finally:
            browser.close()


# The user-approved drop classes (change 2026-10-25), each selected by its observation's kind, candidate, label
# and status, never "first alternative": the geo map (the data has no GEO field), the misread
# Rural/Urban legend control, and a year slider if one is extracted. Any other issue is a block.
APPROVED_DROPS = (
    # Approval drops this observation as a whole, including a separate aggregation clarification
    # on its country binding; one observation can produce more than one issue.
    ('geo map without a GEO field', lambda item, status: item.get('chart_candidate') == 'geo_map'),
    # The legend reads "Location: Rural, Urban"; the extractor labels it with either part. Its status
    # follows the extractor's shape: no or a guessed field (needs_clarification) or no candidate (unknown).
    ('Rural/Urban legend control', lambda item, status: item.get('kind') == 'control'
     and re.search(r'rural|urban|location', item.get('label') or '', re.I) and status in ('needs_clarification', 'unknown')),
    ('year slider', lambda item, status: item.get('kind') == 'control'
     and re.search(r'year|slider', item.get('label') or '', re.I) and not re.search(r'region', item.get('label') or '', re.I)),
)


def approved_drops(flow, folder, assessment):
    """Drop exactly the approved observation issues; returns the recorded substitutions, or the issues left."""
    owners = {r.text: json.loads(r.source.text) for r in requirements.load(folder).requirements if r.source.kind == 'image'}
    decisions, left, recorded = [], [], []
    for issue in (i for i in assessment['issues'] if i['resolution'] == 'unresolved'):
        item = owners.get(issue['requirement'])
        name = next((n for n, accepts in APPROVED_DROPS if item and accepts(item, issue['status'])), None)
        if name is None:
            left.append(issue)
            continue
        decisions.append({'issue_id': issue['id'], 'action': 'drop', 'alternative_id': None})
        recorded.append({'drop': name, 'issue_id': issue['id'], 'item': item.get('id'), 'label': item.get('label'),
                         'status': issue['status'], 'reason': issue['reason']})
    if decisions and not left:
        flow.call('decisions', 'post', '/feasibility/decisions', json={'assessment_id': assessment['id'], 'decisions': decisions})
    return recorded if not left else [], left


# DSS_LIVE_STAGE=24.7 stops after the published, dry-run recreate build: the design-stage, fidelity and
# revision assertions below belong to task 24.11 (two-stage reference fidelity and its visual STOP).
STAGE = os.environ.get('DSS_LIVE_STAGE')
FIDELITY = STAGE not in ('24.7', '24.9')


def require_reference_regressions(spec, proof):
    """A page-placement/title regression must stop before spending on a revision."""
    first = {c['id']: c for c in spec['pages'][0]['components']}
    for requirement, bound in proof['bindings'].items():
        if requirement in proof['image_requirements']:
            assert set(bound) & first.keys(), f'24.10 regression: {requirement} fulfilled only on later pages: {bound}'
    access = [c for cid, c in first.items() if c['type'] == 'scorecard'
              and any(m['field'] == 'access_pct' for m in c.get('metrics', []))
              and any(cid in bound for bound in proof['bindings'].values())]
    assert access, '24.10 regression: no bound access scorecard on page 1'
    for component in access:
        title = component['label']
        assert '2011' not in title and title.endswith('worldwide (%)'), f'24.10 regression: access title {title!r}'


def require_fidelity(spec):
    """Minimum structural oracle; the screenshot and native slot semantics still need human review."""
    page = spec['pages'][0]
    assert 'data-art="globe-' in page['design']['html'], 'missing real-geography globe artwork'
    controls = [c for c in page['components'] if c['type'] == 'fixed_size_list' and c.get('field') == 'region']
    assert controls and controls[0]['box']['x'] < spec['canvas']['width'] * .4, 'native region list must be left'
    yearly = [c for c in page['components'] if c['type'] in ('bar', 'area', 'time_series')
              and any(m['field'] == 'people_without_access' for m in c.get('metrics', []))]
    assert yearly and any(c['box']['y'] > page['height'] * .5 for c in yearly), 'yearly chart must be at bottom'
    combined = [c for c in page['components'] if c['type'] == 'area'
                and {(m['field'], m['agg']) for m in c.get('metrics', [])}
                == {('urban_pct', 'avg'), ('rural_pct', 'avg')}]
    assert len(combined) == 1, 'page 1 requires one native combined urban/rural area chart'
    assert combined[0]['box']['x'] > spec['canvas']['width'] * .6, 'combined area must be in right panel'


def fidelity_inventory(spec, proof, evidence):
    """Read-only diagnostics before a known assertion can stop revision/engine checks."""
    from playwright.sync_api import sync_playwright
    first = spec['pages'][0]
    result = {'structural_errors': [], 'titles': [], 'area_slots': [],
              'later_only_observations': [], 'visual_approval': 'pending'}
    for oracle in (lambda: require_reference_regressions(spec, proof), lambda: require_fidelity(spec)):
        try:
            oracle()
        except AssertionError as exc:
            result['structural_errors'].append(str(exc))
    ids = {c['id'] for c in first['components']}
    result['later_only_observations'] = [rid for rid, bound in proof['bindings'].items()
        if rid in proof['image_requirements'] and not (set(bound) & ids)]
    result['titles'] = [{'id': c['id'], 'label': c['label']} for c in first['components'] if c['type'] == 'scorecard']
    result['area_slots'] = [{'id': c['id'], 'metrics': c.get('metrics'), 'box': c['box']}
        for c in first['components'] if c['type'] == 'area']
    # DOM reads only: widths of rendered values and date labels, no source rows or provider replies.
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': spec['canvas']['width'], 'height': 900})
                page.set_content((evidence / 'prototype.html').read_text(encoding='utf-8'), wait_until='networkidle')
                page.wait_for_timeout(1500)
                result['rendered'] = page.evaluate('''() => ({
                  scorecards: [...document.querySelectorAll('section[data-page="1"] .scorecard')].map(el => {
                    const value = el.querySelector('.value');
                    if (!value) return {id: el.dataset.cid, available: false};
                    const range = document.createRange(); range.selectNodeContents(value);
                    const text = range.getBoundingClientRect(), box = el.getBoundingClientRect();
                    return {id: el.dataset.cid, available: true, text_width: text.width, slot_width: box.width,
                      clipped: text.right > box.right + 1 || text.bottom > box.bottom + 1};
                  }),
                  charts: [...document.querySelectorAll('section[data-page="1"] .chart')].map(el => {
                    const texts = [...el.querySelectorAll('svg text')];
                    const dates = texts.filter(t => /^\\d{4}-\\d{2}-\\d{2}$/.test(t.textContent));
                    const overlap = (a,b) => {const x=a.getBoundingClientRect(), y=b.getBoundingClientRect();
                      return x.left < y.right && y.left < x.right && x.top < y.bottom && y.top < x.bottom;};
                    return {id: el.id, svg_present: !!el.querySelector('svg'), full_date_labels: dates.length,
                      overlapping_text_pairs: texts.reduce((n,t,i) => n + texts.slice(i+1).filter(u=>overlap(t,u)).length,0)};
                  })
                })''')
            finally:
                browser.close()
    except Exception as exc:
        result['render_diagnostic_unavailable'] = type(exc).__name__
    dump(evidence / 'fidelity-inventory.json', result)
    return result


@pytest.mark.live
@pytest.mark.parametrize('mode', ['recreate', 'style', 'none'])
def test_electricity_reference_design(tmp_path, monkeypatch, mode):
    monkeypatch.setenv('DSS_ENGINE_DRY_RUN', '1')
    # Old local .env may still restrict the catalog to recipe 1.2. This fixture targets 1.3.
    monkeypatch.setenv('DSS_ALLOWED_TYPES', ','.join(TYPES))
    fixtures = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in DATA.iterdir() if p.is_file()}
    assert all(fixtures[name] == digest for name, digest in HASHES.items())
    generation = json.loads((DATA / 'generation.json').read_text(encoding='utf-8-sig'))
    app, config, project = live_app(tmp_path)
    evidence = evidence_dir('24.9' if STAGE == '24.9' else '24.11' if FIDELITY else '24.7',
                            f'high-comparison/{mode}' if FIDELITY else mode)
    (evidence / 'test-source.py').write_bytes(Path(__file__).read_bytes())
    print(f'{evidence.parents[1].name} {mode} evidence: {evidence}', flush=True)
    calls, tables = [], set()
    inputs = {'instructions': INSTRUCTIONS if mode == 'recreate' else '',
              'notes': NOTES + (RECREATE_NOTES if mode == 'recreate' else ''),
              'recreate_notes': RECREATE_NOTES if mode == 'recreate' else ''}
    dump(evidence / 'workflow-inputs.json', inputs)
    facts = {'mode': mode, 'fixture_sha256': fixtures,
             'input_sha256': {name: hashlib.sha256(value.encode('utf-8')).hexdigest() for name, value in inputs.items()},
             'generation_calls': calls,
             'comparison': 'HIGH reference stages; historical LOW evidence in RESUMED.md',
             'runtime_sha256': {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                                for name, module in [('reference_brief', reference_brief), ('designer', designer)]},
             'visual_approval': 'pending', 'accepted_substitutions': [], 'dry_engine': True,
             'check_status': 'running', 'fixture_provenance': str(DATA / 'README.md'),
             'approved_fixture_substitutions': [
                 'geo_map omitted; globe remains static real-geography art',
                 'Rural/Urban legend misread as dropdown omitted',
                 'extracted year slider omitted',
                 'four per-country small multiples become native urban/rural area chart',
                 'region selector uses native fixed_size_list',
             ] if mode == 'recreate' else []}
    secrets = tuple(s.get_secret_value() for s in (config.google_api_key, config.access_code, config.agent_token))
    observe_generation(monkeypatch, calls, evidence=evidence / 'failed-drafts', secrets=secrets)
    started = time.monotonic()
    with TestClient(app) as client:
        assert client.put('/api/settings', json={'gcp_project_id': project}).status_code == 200
        service = BigQuery(app.state.settings.get())
        bid = client.post('/api/builds', json={'archetype': 'executive', 'mode': 'data',
                                               'title': 'Access to electricity — synthetic sample'}).json()['id']
        folder = config.data_dir / 'builds' / bid / 'v1'
        flow = RecordedFlow(app, client, bid)
        facts.update(build_id=bid, models={'planner': config.planner_model, 'worker': config.worker_model})
        try:
            with monkeypatch.context() as intake_patch:
                finish_intake = observe_intake(intake_patch, app, bid, evidence, secrets)
                try:
                    flow.act('synthetic', 'post', '/synthetic-data', json={
                        'generation_key': 'electricity_fixture', 'proposal_id': None, 'spec': generation})
                finally:
                    finish_intake()
            assert (evidence / 'intake.json').is_file(), 'intake diagnostics unavailable'
            [source] = flow.get()['sources']
            tables.add(source['bq_table'])
            assert source['kind'] == 'synthetic' and source['row_count'] == 2000
            downloaded = client.get(flow.url + f"/synthetic-data/{source['id']}/csv")
            assert downloaded.status_code == 200 and downloaded.content == (DATA / 'sample.csv').read_bytes()
            if mode != 'none':
                flow.act('reference', 'post', '/reference-images', seconds=180,
                         data={'mode': mode, 'instructions': inputs['instructions']},
                         files=[('files', ('electricity-access.jpg', (DATA / 'electricity-access.jpg').read_bytes(), 'image/jpeg'))])
            flow.act('context', 'post', '/context', seconds=150,
                     json={'notes': inputs['notes']})
            flow.act('outline', 'post', '/context/confirm', seconds=150)
            outline = flow.get('/outline')
            flow.call('outline', 'put', '/outline/selection', json={'questions': [
                {'id': q['id'], 'selected': q['recommended']} for s in outline['sections'] for q in s['questions']]})
            flow.call('design', 'post', '/outline/confirm')
            design = flow.get('/design')
            flow.call('design', 'put', '/design', json={
                **{k: v for k, v in design.items() if k not in ('revision', 'issues')}, 'page_structure': 'per_section'})
            if mode == 'recreate':
                # Reconcile the reference before drafting (as the offline 24.7 fixture does), so the planner and
                # code completion see the observations; only the approved classes are dropped.
                flow.act('reconcile', 'post', '/feasibility/check', seconds=150)
                early = flow.get('/feasibility')
                dump(evidence / 'assessment-before-blueprint.json', early)
                if early['state'] != 'ready':
                    drops, left = approved_drops(flow, folder, early)
                    facts['accepted_substitutions'] += drops
                    assert not left, f'Issues outside the approved drops (a block for the architect): {left}'
            flow.act('blueprint', 'post', '/design/confirm', seconds=400)
            assessment = flow.get('/feasibility')
            if any(i['id'].startswith('bp_intent_') for i in assessment['issues']):
                flow.act('feasibility', 'post', '/feasibility/check', seconds=150)
                assessment = flow.get('/feasibility')
            dump(evidence / 'assessment.json', assessment)
            if assessment['state'] != 'ready' and mode == 'recreate':
                # There is intentionally no "first alternative or drop" loop: only the approved classes.
                drops, left = approved_drops(flow, folder, assessment)
                facts['accepted_substitutions'] += drops
                assert not left, f'Issues outside the approved drops (a block for the architect): {left}'
                assessment = flow.get('/feasibility')
                dump(evidence / 'assessment-after-drops.json', assessment)
            if assessment['state'] != 'ready':
                dump(evidence / 'issues-uncapped.json', all_issues(app, bid, folder, monkeypatch))
            assert assessment['state'] == 'ready', (
                f'Explicit feasibility decisions required; inspect {evidence / "assessment.json"}')
            blueprint = flow.get('/blueprint')
            dump(evidence / 'blueprint.json', blueprint)
            facts['code_added_rows'] = [r['note'] for r in blueprint['rows'] if r['note'].startswith('observation ')]
            if STAGE == '24.9':
                facts['stage_limit'] = ('Stopped after real-model/BigQuery /design/confirm readiness; '
                                        'no reference HTML, prototype, engine run or visual approval claimed.')
                assert not calls, calls
                facts['check_status'] = 'passed_stage_only'
                return
            run = flow.act('prototype', 'post', '/blueprint/accept', seconds=1600)
            spec, proof = capture(flow, folder, evidence, 'prototype')
            if mode == 'recreate' and FIDELITY:
                facts['fidelity_inventory'] = fidelity_inventory(spec, proof, evidence)
            if FIDELITY:
                assert_design_stages(app, run, spec, mode, app.state.settings.get(), facts=facts)
                assert len(spec['pages']) >= 2, 'later-page route not exercised'
            if mode == 'recreate':
                assert proof['image_requirements'], 'recreate did not import observations'
                dropped = {d['item'] for d in facts['accepted_substitutions']}
                assert set(proof['bindings']) >= {r.id for r in requirements.load(folder).requirements
                                                  if r.source.kind == 'image' and r.source.item_id not in dropped
                                                  and json.loads(r.source.text).get('kind') in ('chart', 'control')}, proof
                if FIDELITY:
                    facts['active_check'] = '24.10_regressions'
                    require_reference_regressions(spec, proof)
                    facts.pop('active_check')
            if mode == 'recreate' and FIDELITY:
                target = next(c for c in spec['pages'][0]['components'] if c['type'] == 'fixed_size_list')
                old_html = spec['pages'][0]['design']['html']
                run = flow.act('revision', 'post', '/comments', seconds=850, json={'comments': [{
                    'component_id': target['id'],
                    'text': 'Move this region list card down by 24 pixels, keeping it on the left and preserving the other visual regions.'}]})
                revised, _ = capture(flow, folder, evidence, 'revised')
                assert_design_stages(app, run, revised, mode, app.state.settings.get(), pages={1}, facts=facts)
                assert revised['pages'][0]['design']['source'] == 'revise'
                assert revised['pages'][0]['design']['html'] != old_html
                assert [c['id'] for c in revised['pages'][0]['components']] == [c['id'] for c in spec['pages'][0]['components']]
                moved = next(c for c in revised['pages'][0]['components'] if c['id'] == target['id'])
                assert abs(moved['box']['y'] - target['box']['y'] - 24) <= 2, (target['box'], moved['box'])
                assert moved['box']['x'] < revised['canvas']['width'] * .4, moved['box']
                for before, after in zip(spec['pages'][1:], revised['pages'][1:]):
                    assert after['design'] == before['design']
            elif mode == 'style':
                assert proof['image_requirements'] == [], 'style mode imported chart/control observations'
            for call in calls:
                if not call['generation_started']:
                    continue  # Count-before-generation refusals have no provider usage.
                assert call['usage'], call
                assert all(u['output'] <= call['output_limit'] and (u['output_including_thinking'] is None
                           or u['output_including_thinking'] <= call['output_limit']) for u in call['usage']), call
                assert call['requested_thinking'] == ('LOW' if mode == 'none' else 'HIGH'), call
            flow.act('dry_engine', 'post', '/run', seconds=300)
            events = [json.loads(line) for line in (folder / 'events.jsonl').read_text(encoding='utf-8').splitlines() if line]
            finished = [event for event in events if event['event'] == 'run_finished']
            assert len(finished) == 1 and finished[0]['status'] == 'ok' and finished[0]['failed'] == 0, finished
            ops = [event for event in events if event['event'] == 'op_finished']
            recipe = validate_recipe((folder / 'recipe.jsonl').read_text(encoding='utf-8'))
            assert [op['op_id'] for op in ops] == [op['id'] for op in recipe[1:]]
            assert all(op['status'] == 'skipped' for op in ops), 'engine was not dry-run'
            facts['engine'] = finished
            if mode == 'recreate' and FIDELITY:
                # Retain revision/dry-engine evidence even when the original published layout
                # fails fidelity. The same structural acceptance oracle still must pass.
                facts['active_check'] = 'fidelity'
                require_fidelity(spec)
                facts.pop('active_check')
            facts['check_status'] = 'passed'
        except BaseException:
            facts['check_status'] = 'failed'
            facts['failure_stage'] = facts.pop('active_check', None) or (flow.steps[-1]['stage'] if flow.steps else 'setup')
            raise
        finally:
            published = client.get(flow.url + '/spec')
            facts['published_prototype'] = published.status_code == 200 and bool(published.json())
            facts['seconds'] = round(time.monotonic() - started, 2)
            facts['stages'] = stage_evidence(app, flow)
            try:
                keep(evidence, flow, folder, facts)
            finally:
                # Only this isolated build's exact source/view identities are removed.
                for suffix in ('/blueprint', '/spec'):
                    response = client.get(flow.url + suffix)
                    if response.status_code == 200 and response.json():
                        obj = response.json()
                        table = obj.get('view_table') if suffix == '/blueprint' else obj['datasource']['table']
                        if table:
                            tables.add(table)
                for table in tables:
                    service.client.delete_table(table, not_found_ok=True)
