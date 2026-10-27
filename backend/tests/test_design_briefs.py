"""Full brief intent, validation repairs and version-local published design records."""
import json
import hashlib
from pathlib import Path

import pytest

from dss.harness import stages
from dss.harness.nodes import designer, reference_brief as rb
from dss.harness.nodes.style_extract import provider_schema
from test_designer import DesignerLLM, Trace
from test_reference_brief import BriefLLM, attached, reference_set, run, section, unit_reports
from test_render import three_pages
from test_blueprint import blueprint_api  # noqa: F401
from test_context_node import context_api  # noqa: F401
from test_revise import setup, designed  # noqa: F401


def brief_value(page):
    return {'page': page.index, 'overall': 'Wide calm panels. ' * 2500,
            'slots': [{'id': c.id, 'treatment': 'A spacious white card. ' * 100} for c in page.components]}


async def test_brief_without_reference_uses_dashboard_skill_and_no_image():
    spec = three_pages()
    model, trace = BriefLLM(), Trace()
    result = await rb.brief(model, None, unit_reports(spec)[1], spec, spec.pages[0], trace)
    assert isinstance(result, rb.PageBrief)
    task, images = attached(model.requests[0])
    assert images == [] and 'No reference image' in task
    instruction = str(model.requests[0].config.system_instruction)
    assert 'Reference set:' not in instruction and 'Approved native components' in instruction
    assert Path('skills/dashboard-design.md').read_text(encoding='utf-8').strip() in instruction


async def test_no_reference_page_brief_then_html():
    spec, brief, html, trace, records = three_pages(), BriefLLM(), DesignerLLM(gate=2), Trace(), {}
    plan = designer.ReferenceDesign(None, unit_reports(spec), lambda: brief, lambda: html)
    result, notes = await designer.design(spec, lambda: pytest.fail('legacy designer'), trace,
                                          reference=plan, briefs=records)
    assert not notes and all(page.design for page in result.pages)
    assert len(brief.requests) == len(html.seen) == len(spec.pages)
    assert all(attached(request)[1] == [] for request in brief.requests)
    assert html.seen[0][0] == 1 and html.peak == 2
    assert list(records) == [1, 2, 3]
    assert all('Validated visual brief' in request for _, request in html.seen)
    assert all('implement the validated visual brief' in request for _, request in html.seen)


@pytest.mark.parametrize('page', [1, 2])
@pytest.mark.parametrize('enabled', [True, False])
async def test_required_decoration_cannot_bypass_design_or_fallback(page, enabled):
    from types import SimpleNamespace
    from dss.harness.guardrails import RunError
    spec, brief, html, trace = three_pages(), BriefLLM(), DesignerLLM(), Trace()
    config = stages.defaults()
    config['stages']['html_no_reference']['layout_fallback'] = enabled
    plan = designer.ReferenceDesign(None, unit_reports(spec), lambda: brief, lambda: html)
    with stages.Execution(SimpleNamespace(**config), trace).activate():
        with pytest.raises(RunError) as caught:
            await designer.design(spec, lambda: None, trace, keep={page}, reference=plan)
    assert caught.value.detail['reason'] == 'requirements'
    assert not brief.requests and not html.seen


async def test_damaged_reference_refuses_even_with_required_decoration():
    from dss.harness.guardrails import RunError
    trace = Trace()
    plan = designer.ReferenceDesign(None, {}, None, None, designer.Fallback('reference'))
    with pytest.raises(RunError) as caught:
        await designer.design(three_pages(), lambda: None, trace, keep={1}, reference=plan)
    assert caught.value.detail['reason'] == 'reference'
    assert not any(span['node'] == 'designer_fallback' for span in trace.spans)


async def test_revision_page_one_completes_before_parallel_later_pages():
    spec, _ = await designer.design(three_pages(), lambda: DesignerLLM(), Trace())
    brief, html, trace = BriefLLM(), DesignerLLM(gate=2), Trace()
    plan = designer.ReferenceDesign(None, unit_reports(spec), lambda: brief, lambda: html)
    comments = {page.index: [{'component_id': f'p{page.index}_design', 'text': 'Darker header'}]
                for page in spec.pages}
    revised, failed = await designer.regenerate(spec, comments, lambda: None, trace, reference=plan, briefs={})
    assert not failed and all(page.design for page in revised.pages)
    page1_validation = next(i for i, span in enumerate(trace.spans)
                            if span['node'] == 'validate' and span.get('page') == 1)
    assert all(i > page1_validation for i, span in enumerate(trace.spans)
               if span['node'] == 'reference_brief' and span.get('page') in (2, 3))
    assert html.peak == 2 and html.seen[0][0] == 1
    assert all('Page 1 measured width and stylesheet' in request for _, request in html.seen[1:])


async def test_failed_html_records_actual_fallback_model(monkeypatch):
    spec, trace, records = three_pages(), Trace(), {}
    brief, html = BriefLLM(), DesignerLLM()
    plan = designer.ReferenceDesign(None, unit_reports(spec), lambda: brief, lambda: html)
    async def failed_page(model, spec, page, trace, **kwargs):
        trace.spans.append({'node': 'designer', 'page': page.index, 'model': 'actual-fallback-model'})
        return designer.Fallback('invalid')
    monkeypatch.setattr(designer, '_page', failed_page)
    result = await designer._reference_page(html, spec, spec.pages[0], trace, reference=plan, briefs=records)
    assert result.reason == 'invalid'
    assert records[1]['html_model'] == 'actual-fallback-model'


def test_unattempted_fallback_label_survives_later_revision(tmp_path):
    from dss.spec.publication import DESIGN_PAGES, design_artifacts
    spec = three_pages()
    records = {page.index: {'brief': None, 'html_model': None, 'layout_fallback': True} for page in spec.pages}
    initial = design_artifacts(spec, tmp_path, records, reset=True)
    (tmp_path / DESIGN_PAGES).write_bytes(initial[DESIGN_PAGES])
    spec.spec_version += 1
    updated = design_artifacts(spec, tmp_path, {})
    pages = json.loads(updated[DESIGN_PAGES])['pages']
    assert all(page['standard_reason'] == 'layout_fallback' and page['html_model'] is None for page in pages)


@pytest.mark.parametrize('page', [1, 3])
@pytest.mark.parametrize('enabled', [True, False])
async def test_no_reference_invalid_html_falls_back_only_when_enabled(page, enabled):
    from types import SimpleNamespace
    from dss.harness.guardrails import RunError
    spec, brief, html, trace, records = three_pages(), BriefLLM(), DesignerLLM(plan={page: ['bad']}), Trace(), {}
    config = stages.defaults()
    config['stages']['html_no_reference']['layout_fallback'] = enabled
    plan = designer.ReferenceDesign(None, unit_reports(spec), lambda: brief, lambda: html)
    with stages.Execution(SimpleNamespace(**config), trace).activate():
        if not enabled:
            with pytest.raises(RunError):
                await designer.design(spec, lambda: None, trace, reference=plan, briefs=records)
            return
        result, notes = await designer.design(spec, lambda: None, trace, reference=plan, briefs=records)
    assert notes and len([n for n, _ in html.seen if n == page]) == 3
    assert all(p.design is None for p in result.pages) if page == 1 else result.pages[2].design is None
    assert records[page]['html_model'] == html.model
    if page == 1:
        assert all(records[n]['layout_fallback'] and records[n]['html_model'] is None for n in (2, 3))


@pytest.mark.parametrize('enabled', [True, False])
@pytest.mark.parametrize('failure', ['brief', 'cutoff'])
async def test_no_reference_hard_stop_never_falls_back(enabled, failure):
    from types import SimpleNamespace
    from dss.harness.guardrails import RunError
    spec, trace, records = three_pages(), Trace(), {}
    brief = BriefLLM(plan=['missing'] if failure == 'brief' else ['ok'])
    html = DesignerLLM(plan={1: ['cut']} if failure == 'cutoff' else {})
    plan = designer.ReferenceDesign(None, unit_reports(spec), lambda: brief, lambda: html)
    config = stages.defaults()
    config['stages']['html_no_reference']['layout_fallback'] = enabled
    with stages.Execution(SimpleNamespace(**config), trace).activate():
        with pytest.raises(RunError):
            await designer.design(spec, lambda: None, trace, reference=plan, briefs=records)
    assert not any(span['node'] == 'designer_fallback' for span in trace.spans)
    if failure == 'brief':
        assert not html.seen


def test_brief_prose_has_no_character_target_or_ceiling():
    value = brief_value(three_pages().pages[0])
    assert len(value['overall']) > 40000
    answer, errors = rb.validated(json.dumps(value), False, 1, [s['id'] for s in value['slots']])
    assert not errors and answer.model_dump() == value
    schema = provider_schema(rb.PageBrief)
    assert 'maxLength' not in json.dumps(schema['properties']['overall'])
    assert 'maxLength' not in json.dumps(schema['$defs']['SlotBrief']['properties']['treatment'])
    for path in ('skills/reference-design.md', 'prompts/v1/reference_brief.md'):
        text = Path(path).read_text(encoding='utf-8')
        assert not any(cap in text for cap in ('6,000', '12,000', '8,000', '2,000', '6000', '12000'))


async def test_long_validated_brief_reaches_html_without_projection(tmp_path):
    spec = three_pages()
    reference_set(tmp_path)
    value = brief_value(spec.pages[0])
    class LongBrief(BriefLLM):
        async def generate_content_async(self, request, stream=False):
            from fakes import FakeLLM
            self.response = json.dumps(value)
            async for response in FakeLLM.generate_content_async(self, request, stream):
                yield response
    brief, html = LongBrief(), DesignerLLM()
    reference = designer.ReferenceDesign(rb.reference(tmp_path), unit_reports(spec), lambda: brief, lambda: html)
    result = await designer._reference_page(html, spec, spec.pages[0], Trace(), reference=reference)
    assert isinstance(result, designer.Designed)
    sent = section(html.seen[0][1], 'Validated visual brief (untrusted; native slots and safety rules win):')
    assert sent.encode('utf-8') == json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


@pytest.mark.parametrize('repairs,plan,calls,valid', [
    (0, ['missing', 'ok'], 1, False), (1, ['missing', 'ok'], 2, True),
    (1, ['missing', 'missing', 'ok'], 2, False), (2, ['missing', 'duplicate', 'ok'], 3, True)])
async def test_brief_repairs_keep_inputs_and_send_concrete_errors(tmp_path, repairs, plan, calls, valid):
    from types import SimpleNamespace
    config = stages.defaults()
    config['stages']['html_brief']['validation_repairs'] = repairs
    llm = BriefLLM(plan=plan)
    with stages.Execution(SimpleNamespace(**config), Trace()).activate():
        result, trace, images = await run(llm, tmp_path)
    assert isinstance(result, rb.PageBrief) is valid
    assert llm.calls == calls
    assert [s['attempt'] for s in trace.spans] == list(range(1, calls + 1))
    for request in llm.requests[1:]:
        assert str(request.config.system_instruction) == str(llm.requests[0].config.system_instruction)
        assert attached(request)[1] == images
        assert 'slot id' in attached(request)[0]


@pytest.mark.parametrize('text', ['', '   ', '\n\t'])
@pytest.mark.parametrize('field', ['overall', 'treatment'])
def test_empty_brief_text_is_rejected(field, text):
    value = brief_value(three_pages().pages[0])
    if field == 'overall':
        value[field] = text
    else:
        value['slots'][0][field] = text
    assert rb.validated(json.dumps(value), False, 1, [s['id'] for s in value['slots']])[0] is None


def test_brief_report_keeps_full_requirements_and_decisions(monkeypatch):
    from dss.spec import requirements as req, feasibility
    from dss.spec.capabilities import Checker, load_registry
    text = 'Preserve this requirement in full. ' * 80 + 'FINAL REQUIREMENT DETAIL'
    row = req.Requirement(id='r_long', source=req.Source(id='m1', kind='message', text=text), text=text)
    ledger = req.Ledger(requirements=[row], assessment=req.Assessment(id='a1', state='ready'),
                        decisions=[{'requirement_id': row.id, 'meaning': req.meaning(row), 'action': 'drop'}])
    def coverage(snapshot, ledger, checker, *, bindings):
        bindings[row.id] = [snapshot['spec']['pages'][0]['components'][0]['id']]
        return []
    monkeypatch.setattr(req, 'coverage_errors', coverage)
    monkeypatch.setattr(feasibility, 'choices', lambda *args: [
        {'target': {}, 'issue': {'requirement': text}, 'action': 'drop', 'effect': {}}])
    snapshot = {'spec': three_pages().model_dump(), 'blueprint': True}
    report = rb.report(snapshot, ledger, Checker(load_registry()))[1]
    assert report['components'][0]['bindings'][0]['text'] == text
    assert [d['text'] for d in report['decisions']] == [text, text]


@pytest.mark.parametrize('plan', [['missing', 'missing'], ['duplicate', 'unknown']])
async def test_unrepaired_brief_never_calls_html(tmp_path, plan):
    spec, html = three_pages(), DesignerLLM()
    reference_set(tmp_path)
    brief = BriefLLM(plan=plan)
    reference = designer.ReferenceDesign(rb.reference(tmp_path), unit_reports(spec), lambda: brief, lambda: html)
    result = await designer._reference_page(html, spec, spec.pages[0], Trace(), reference=reference)
    assert isinstance(result, designer.Fallback) and brief.calls == 2
    assert not html.seen


def test_markdown_matches_contract_and_hash_covers_canonical_file():
    from types import SimpleNamespace
    fixture = json.loads(Path('../contracts/fixtures/stage-settings/design_pages.json').read_text(encoding='utf-8'))
    for row in fixture['pages']:
        value = rb.PageBrief.model_validate(row['brief']['brief'])
        components = ([('c_kpi_total', 'scorecard', 'Total access'), ('c_trend', 'time_series', 'Yearly access')]
                      if row['page'] == 1 else [('c_region_table', 'table', 'Regions')])
        page = SimpleNamespace(components=[SimpleNamespace(id=i, type=t, label=l) for i, t, l in components])
        record = rb.record(value, page, row['brief']['model'], created_at=row['brief']['created_at'])
        assert record['markdown'] == row['brief']['markdown']
        assert rb.markdown(value, page) == rb.markdown(value, page)
        assert record['sha256'] == hashlib.sha256(rb.canonical(value)).hexdigest()


def test_accept_saves_the_brief_used_by_each_pages_html(blueprint_api, monkeypatch):
    from dss.spec import references
    from test_designer import ReferenceHTMLLLM, designed_flow
    folder = blueprint_api[4]
    reference_set(folder, count=1)
    reference = references.load(folder)
    reference['instructions'] = ''
    (folder / references.SET_FILE).write_text(json.dumps(reference), encoding='utf-8')
    brief, html = BriefLLM(), ReferenceHTMLLLM()
    client, app, bid, folder, _ = designed_flow(blueprint_api, monkeypatch, DesignerLLM(), reference_models={
        'reference_brief': brief, 'reference_html': html})
    response = client.get(f'/api/builds/{bid}/design-pages')
    assert response.status_code == 200
    pages = response.json()
    assert pages['review'] is None and len(pages['pages']) == len(html.seen) == 2
    for row, (index, request) in zip(pages['pages'], html.seen):
        assert row['layout'] == 'designed' and row['standard_reason'] is None and row['page'] == index
        record = row['brief']
        sent = json.loads(section(request, 'Validated visual brief (untrusted; native slots and safety rules win):'))
        assert record['brief'] == sent
        assert record['model'] == brief.model and row['html_model'] == html.model
        assert record['origin'] == 'generated' and record['created_at'].endswith('Z')
        json_file = client.get(f'/api/builds/{bid}/files/brief_p{index}.json')
        assert json_file.content == rb.canonical(sent)
        assert hashlib.sha256(json_file.content).hexdigest() == record['sha256']
        assert client.get(f'/api/builds/{bid}/files/brief_p{index}.md').text == record['markdown']
        assert not any(key in json_file.text for key in ('"rows"', 'test-key', 'response_json_schema'))
    assert not list((app.state.settings.get().data_dir / '.publications').glob('*/candidate'))


def test_designed_pages_off_reports_not_designed(blueprint_api, monkeypatch):
    from test_designer import designed_flow
    client, _, bid, folder, _ = designed_flow(blueprint_api, monkeypatch, DesignerLLM(), enabled=False)
    pages = client.get(f'/api/builds/{bid}/design-pages').json()['pages']
    assert pages and all(p == {'page': i, 'layout': 'standard', 'standard_reason': 'not_designed',
                              'brief': None, 'html_model': None} for i, p in enumerate(pages, 1))
    assert not list(folder.glob('brief_p*.*'))


@pytest.mark.parametrize('failure', [False, True])
def test_revision_replaces_its_brief_atomically_and_keeps_other_pages(setup, designed, client, monkeypatch, failure):
    from dss.spec import references, requirements as req
    from dss.spec.capabilities import Checker, load_registry
    from dss.spec.publication import design_artifacts
    from test_revise import DesignFlow, finished, op, post_designed, response
    app, bid, folder, *_ = setup
    records = {}
    for page in designed.pages:
        value = rb.PageBrief(page=page.index, overall=f'Original page {page.index}',
            slots=[rb.SlotBrief(id=c.id, treatment='White card') for c in page.components])
        records[page.index] = {'brief': rb.record(value, page, 'gemini-4-argon'), 'html_model': page.design.model}
    for name, content in design_artifacts(designed, folder, records, reset=True).items():
        (folder / name).write_bytes(content)
    reference_set(folder, count=1)
    reference = references.load(folder)
    reference['instructions'] = ''
    (folder / references.SET_FILE).write_text(json.dumps(reference), encoding='utf-8')
    snap, ledger = req.inputs(app.state.db, bid, folder), req.load(folder)
    req.save(folder, ledger, req.evaluate(snap, ledger, Checker(load_registry())))
    text = 'Make it a table'
    fake = DesignFlow(needs_by_text={text: [{'capability': 'chart.table'}]}, response=response([
        op('/pages/0/components/0/type', 'table'), op('/pages/0/components/0/dimensions', ['region'])]))
    brief = BriefLLM()
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: {'reference_brief': brief,
                        'reference_html': fake}.get(node) or fake)
    watched = ['spec.json', 'prototype.html', 'design-pages.json',
               *(f'brief_p{i}.{ext}' for i in range(1, 4) for ext in ('json', 'md'))]
    before = {name: (folder / name).read_bytes() for name in watched}
    if failure:
        replace = Path.replace
        def fail_at_manifest(path, target):
            if Path(target) == folder / 'design-pages.json' and path.name.startswith('publish-'):
                raise OSError('Injected manifest publication failure')
            return replace(path, target)
        monkeypatch.setattr(Path, 'replace', fail_at_manifest)
    assessment, run_id = post_designed(client, app, bid, [{'component_id': 'p1_scorecard_0', 'text': text}])
    if failure:
        assert finished(app, bid, run_id)['status'] == 'error'
        assert all((folder / name).read_bytes() == content for name, content in before.items())
        assert assessment['pending_comments'] is not None
        return
    assert finished(app, bid, run_id)['status'] == 'ok'
    rows = client.get(f'/api/builds/{bid}/design-pages').json()['pages']
    sent = json.loads(section(fake.designs[0][1], 'Validated visual brief (untrusted; native slots and safety rules win):'))
    assert rows[0]['brief']['brief'] == sent and (folder / 'brief_p1.json').read_bytes() == rb.canonical(sent)
    assert rows[0]['brief']['markdown'].count('(table:') >= 1
    assert rows[1]['brief'] == records[2]['brief'] and rows[2]['brief'] == records[3]['brief']
    assert all((folder / name).read_bytes() == before[name] for name in watched if name.startswith(('brief_p2', 'brief_p3')))
    # The same revision can render byte-identical HTML while using a different new brief.
    # Persist that brief too: the public record always describes the last HTML request.
    previous_spec = json.loads((folder / 'spec.json').read_text(encoding='utf-8'))
    brief.plan = ['ok', 'long']
    # An unchanged heading patch still explicitly routes this page through the designer.
    fake.response = response([op('/pages/0/components/0/label', previous_spec['pages'][0]['components'][0]['label'])])
    assessment, repeated = post_designed(client, app, bid, [{'component_id': 'p1_scorecard_0', 'text': text}])
    assert finished(app, bid, repeated)['status'] == 'ok'
    next_spec = json.loads((folder / 'spec.json').read_text(encoding='utf-8'))
    assert next_spec['pages'] == previous_spec['pages']
    new_record = client.get(f'/api/builds/{bid}/design-pages').json()['pages'][0]['brief']
    last_sent = json.loads(section(fake.designs[-1][1], 'Validated visual brief (untrusted; native slots and safety rules win):'))
    assert last_sent != sent and new_record['brief'] == last_sent
    assert (folder / 'brief_p1.json').read_bytes() == rb.canonical(last_sent)
