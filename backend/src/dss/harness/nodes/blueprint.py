"""Bounded Blueprint drafting/redrafting and code-built view dry runs.

The row checker is deliberately an extension point for task 15.7's feasibility rules
and code-built alternatives. Coverage is already enforced here, including one repair.
"""
import asyncio
from collections import Counter
import json

from google.adk import Event
from google.adk.agents import LlmAgent
from google.adk.events.event_actions import EventActions
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field, ValidationError

from dss.artifacts import design as design_node, state as stages
from dss.artifacts.models import Blueprint, BlueprintRow, DerivedField, Model, ViewSources
from dss.artifacts.okf import atomic_write, read_artifact, write_artifact
from dss.harness.context import blueprint_context, fit_request, tokens
from dss.harness.guardrails import RunError, check_reply
from dss.harness.nodes import context as context_node, outline as outline_node, view
from dss.harness.nodes.style_extract import provider_schema
from dss.spec import requirements as req
from dss.spec.capabilities import Checker, load_registry
from dss.spec.validate import allowed_types, catalog

MAX_OUTPUT_TOKENS = 6000


class ViewDraft(Model):
    view_sources: ViewSources
    derived_fields: list[DerivedField] = Field(max_length=15)


class Draft(ViewDraft):
    rows: list[BlueprintRow] = Field(max_length=82)


class RowRepair(Model):
    rows: list[BlueprintRow] = Field(max_length=82)


def load(folder):
    path = folder / 'docs/blueprint.md'
    return read_artifact(path, Blueprint) if path.is_file() else None


def page_plan(outline, design):
    sections = [s for s in outline.sections if any(q.selected for q in s.questions)]
    if design.page_structure == 'per_section' and not 1 <= len(sections) <= 5:
        raise RunError('artifact_invalid', 'Per-section pages need 1-5 selected sections', 409)
    return {s.id: index if design.page_structure == 'per_section' else 1 for index, s in enumerate(sections, 1)}


def questions(outline, context):
    kpis = {k.id: k.model_dump() for k in context.kpis}
    return {q.id: {'id': q.id, 'text': q.text, 'kpi_refs': q.kpi_refs, 'section_id': s.id,
                   'definitions': [kpis.get(ref) for ref in q.kpi_refs]}
            for s in outline.sections for q in s.questions if q.selected}


def catalog_summary():
    checker = Checker(load_registry())
    result = []
    for kind, rule in catalog().items():
        if kind not in allowed_types() or checker.component({'type': kind}):
            continue
        options = []
        for cap in checker.registry.capabilities:
            if any(loc.startswith(f'add_chart.options.{kind}.') for loc in cap.recipe) and checker.capability(cap.id).ok:
                options.append({'key': cap.recipe[0].rsplit('.', 1)[-1], 'values': cap.values, 'value_type': cap.value_type})
        result.append({**{k: v for k, v in rule.items() if k.startswith(('min_', 'max_')) or
                        k in ('requires_date_dimension', 'slot_roles')}, 'type': kind, 'options': options})
    return result


def source_metadata(connected):
    return [{'source_id': s['id'], 'fields': view.blueprint_fields([s], ViewSources(base=s['id'], joins=[], union=[]), [])}
            for s in connected]


def join_facts(metadata):
    result = []
    for i, left in enumerate(metadata):
        for right in metadata[i + 1:]:
            for field in left['fields']:
                if any(f['name'] == field['name'] and f['type'] == field['type'] for f in right['fields']):
                    result.append({'left_source': left['source_id'], 'right_source': right['source_id'],
                                   'field': field['name'], 'type': field['type']})
    return result


def derived_fields(context, extra, retained=()):
    fields = {f.name: f for f in context.derived_fields}
    for field in retained:
        fields.setdefault(field.name, field)
    for field in extra:
        if field.name in fields and fields[field.name] != field:
            raise ValueError('A retained or Context derived field cannot be redefined')
        fields[field.name] = field
    return list(fields.values())


def normalize_rows(rows, selected, pages):
    result = []
    for row in rows:
        section = selected[row.question_id]['section_id'] if row.question_id in selected else row.section_id
        if section not in pages or (row.question_id is not None and row.question_id not in selected):
            continue  # model cannot resurrect a deselected or invent a selected question
        result.append(row.model_copy(update={'section_id': section, 'page': pages[section],
                                            'status': 'ok', 'issue_ids': []}, deep=True))
    return result


def row_errors(rows, selected):
    """Coverage diagnostics; full catalog/KPI feasibility is added by task 15.7."""
    counts = Counter(r.question_id for r in rows if r.question_id is not None)
    return [{'question_id': qid, 'message': 'Each selected question needs 1-3 rows'}
            for qid in selected if not 1 <= counts[qid] <= 3]


def inputs_path(folder):
    return folder / 'blueprint-inputs.json'


def previous_inputs(folder):
    path = inputs_path(folder)
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


async def persist(harness, build, folder, run_id, draft, fingerprints, errors, context_fields):
    old = load(folder)
    draft.revision = old.revision + 1 if old else 1
    ledger = req.load(folder)
    checker = Checker(load_registry())
    snapshot = req.inputs(harness.db, build['id'], folder)
    # Keep pre-existing intent issues and decisions. Task 15.7 extends this assessment
    # with all row feasibility checks and alternatives; this task only establishes coverage.
    assessment = req.evaluate(snapshot, ledger, checker, check_components=False)
    for error in errors:
        qid = error.get('question_id')
        issue = req.Issue(id='bp_' + req.digest(error)[:16], requirement=qid or 'Blueprint view',
                          status='needs_data' if qid is None else 'unknown', reason=error['message'])
        assessment.issues.append(issue)
        for row in draft.rows:
            if qid is None or row.question_id == qid:
                row.status = 'blocked'
                row.issue_ids.append(issue.id)
    if errors:
        assessment.state = 'blocked'
    elif assessment.state == 'ready':
        # Coverage and a SQL dry run alone are not full Blueprint feasibility.
        assessment.state = 'unchecked'
    if len(assessment.issues) > req.MAX_ISSUES:
        # The public assessment is bounded, while full diagnostics remain durable.
        assessment.issues = [req.Issue(id='bp_scope_' + req.digest(errors)[:16],
            requirement='Blueprint coverage', status='needs_clarification',
            reason='More than 20 issues; reduce the request scope. Affected questions: ' +
                   ', '.join(e['question_id'] or 'view' for e in errors))]
        assessment.state = 'blocked'
        for row in draft.rows:
            row.status, row.issue_ids = 'blocked', [assessment.issues[0].id]
    draft.assessment_id = assessment.id
    targets = [folder / 'requirements.json', inputs_path(folder), *[folder / 'docs' / name for name in
               ('blueprint.md', 'feasibility.md', 'index.md', 'log.md')]]
    backup = {p: p.read_bytes() if p.is_file() else None for p in targets}
    try:
        req.save(folder, ledger, assessment)
        atomic_write(inputs_path(folder), json.dumps({'questions': fingerprints,
            'context_fields': context_fields, 'errors': errors}, ensure_ascii=False))
        await write_artifact(folder / 'docs/blueprint.md', draft,
            emit=lambda kind, payload: harness.emit(build['id'], run_id, kind, payload))
        stages.save(harness.db, build['id'], stages.edited({**build, 'stage': 'blueprint'}, 'blueprint'))
    except BaseException:
        for path, content in backup.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        raise
    await harness.emit(build['id'], run_id, 'stage.changed', {'stage': 'blueprint'})
    from dss.api.builds import build_response
    await harness.emit(build['id'], run_id, 'build.updated', {
        'build': build_response(harness.db, harness.models.settings.get(), build['id'])})


def make_branch(harness, build_id, run_id, payload, model, trace, model_error):
    config, folder, build = payload['config'], payload['folder'], payload['build']
    context, outline, design = context_node.load(folder), outline_node.load(folder), design_node.load(folder)
    connected = context_node.sources(harness.db, build_id)
    old = load(folder)
    selected, pages = questions(outline, context), page_plan(outline, design)
    fingerprints = {qid: req.digest(q) for qid, q in selected.items()}
    recorded = previous_inputs(folder)
    previous = recorded.get('questions', {})
    kept_ids = {qid for qid in selected if old and not payload.get('regenerate') and previous.get(qid) == fingerprints[qid]}
    pending = {qid: q for qid, q in selected.items() if qid not in kept_ids}
    kept = [r for r in old.rows if r.question_id in kept_ids or (kept_ids and r.question_id is None)] if old else []
    metadata, summary = source_metadata(connected), catalog_summary()
    facts = join_facts(metadata)
    retained = [f for f in old.derived_fields if f.name not in recorded.get('context_fields', [])] if old and kept_ids else []
    initial_view = ViewDraft(view_sources=old.view_sources if old and kept_ids else
        ViewSources(base=connected[0]['id'], joins=[], union=[]), derived_fields=derived_fields(context, [], retained))
    state = {'raw': '', 'draft': None, 'view': initial_view, 'rows': normalize_rows(kept, selected, pages),
             'errors': [], 'row_repaired': False, 'sql_repaired': False, 'phase': 'generate', 'failure': None}
    secrets = (config.google_api_key.get_secret_value(), config.access_code.get_secret_value(), config.agent_token.get_secret_value())

    async def start(node_input):
        return Event(actions=EventActions(route='generate' if pending else 'check'))

    async def instruction_provider(context_object):
        return 'Return the requested Blueprint JSON only.'

    async def before_model(callback_context, llm_request):
        phase = state['phase']
        trace.span('blueprint' if phase == 'generate' else 'blueprint_' + phase)
        request_questions = pending
        repair = None
        schema = Draft
        if phase == 'row_repair':
            ids = {e['question_id'] for e in state['errors']}
            request_questions = {qid: selected[qid] for qid in ids}
            repair = {'kind': 'rows', 'errors': state['errors'],
                      'rows': [r.model_dump() for r in state['rows'] if r.question_id in ids]}
            schema = RowRepair
        elif phase == 'sql_repair':
            request_questions = {}
            repair = {'kind': 'view', 'error': state['sql_error'],
                      'view': state['view'].model_dump()}
            schema = ViewDraft
        memory = blueprint_context(context, metadata, list(request_questions.values()), pages, summary, facts,
            previous_view=state['view'].model_dump(), repair=repair)
        check_reply(memory, secrets)
        llm_request.config.system_instruction = str(memory)
        llm_request.config.response_mime_type = 'application/json'
        llm_request.config.response_json_schema = provider_schema(schema)
        llm_request.config.max_output_tokens = MAX_OUTPUT_TOKENS
        llm_request.config.thinking_config = types.ThinkingConfig(thinking_level='LOW')
        llm_request.contents = [types.Content(role='user', parts=[types.Part(text='Return the requested Blueprint draft JSON only.')])]
        await fit_request(memory, llm_request, model, trace.spans[-1])

    async def after_model(callback_context, llm_response):
        if llm_response.partial:
            return LlmResponse(partial=True)
        raw = ''.join(p.text for p in (llm_response.content.parts or []) if p.text and not p.thought) if llm_response.content else ''
        usage = llm_response.usage_metadata
        if (llm_response.error_code or llm_response.finish_reason == types.FinishReason.MAX_TOKENS or
                tokens(raw) > MAX_OUTPUT_TOKENS or (usage and (usage.candidates_token_count or 0) > MAX_OUTPUT_TOKENS)):
            state['failure'] = RunError('llm_unavailable', 'Blueprint generation failed or exceeded its output budget', 503)
        else:
            try:
                state['raw'] = check_reply(raw, secrets)
            except RunError:
                state['failure'] = RunError('llm_unavailable', 'Blueprint returned unsafe output', 503)
        return LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Blueprint received for validation.')]),
                           usage_metadata=usage)

    async def check_rows(node_input):
        trace.span('validate_blueprint_rows')
        if not state['failure']:
            try:
                if pending and state['phase'] == 'generate':
                    draft = Draft.model_validate_json(state['raw'])
                    state['view'] = ViewDraft(view_sources=draft.view_sources,
                        derived_fields=derived_fields(context, draft.derived_fields, retained))
                    state['rows'] += normalize_rows([r for r in draft.rows if r.question_id not in kept_ids], pending, pages)
                elif state['phase'] == 'row_repair':
                    repaired = RowRepair.model_validate_json(state['raw'])
                    ids = {e['question_id'] for e in state['errors']}
                    state['rows'] = [r for r in state['rows'] if r.question_id not in ids] + normalize_rows(
                        [r for r in repaired.rows if r.question_id in ids], selected, pages)
                state['errors'] = row_errors(state['rows'], selected)
            except (ValueError, ValidationError):
                state['failure'] = RunError('llm_unavailable', 'The model returned an invalid Blueprint structure; draft again', 503)
        if state['errors'] and not state['row_repaired'] and not state['failure']:
            state['row_repaired'], state['phase'] = True, 'row_repair'
            return Event(actions=EventActions(route='repair'))
        return Event(actions=EventActions(route='view'))

    async def check_view(node_input):
        trace.span('validate_blueprint_view')
        if state['failure']:
            return Event(actions=EventActions(route='complete'))
        try:
            if state['phase'] == 'sql_repair':
                repaired = ViewDraft.model_validate_json(state['raw'])
                state['view'] = ViewDraft(view_sources=repaired.view_sources,
                    derived_fields=derived_fields(context, repaired.derived_fields, retained))
            sql = view.blueprint_sql(connected, state['view'].view_sources, state['view'].derived_fields,
                                     context_fields=[f.name for f in context.derived_fields])
            service = payload['factory'](config)
            await asyncio.to_thread(service.dry_run, sql)
            state['view_table'] = view.view_table(config, build_id, build['current_version'], run_id)
        except Exception as exc:
            # Dry-run errors are metadata; bound and redact before the one SQL repair.
            error = str(exc)
            for secret in secrets:
                if secret:
                    error = error.replace(secret, '[redacted]')
            state['sql_error'] = error[:1000]
            if not state['sql_repaired']:
                state['sql_repaired'], state['phase'] = True, 'sql_repair'
                return Event(actions=EventActions(route='repair'))
            state['errors'].append({'question_id': None, 'message': 'The view did not pass SQL validation after one repair'})
        return Event(actions=EventActions(route='complete'))

    async def complete(node_input):
        if state['failure']:
            return 'Blueprint could not be drafted.'
        draft = Blueprint(revision=1, **state['view'].model_dump(), rows=state['rows'],
                          view_table=state.get('view_table'), assessment_id=None)
        await persist(harness, build, folder, run_id, draft, fingerprints, state['errors'],
                      [f.name for f in context.derived_fields])
        return ('Blueprint drafted. Resolve the listed issues before accepting.' if state['errors'] else
                'Blueprint drafted and its view dry run passed. Review the component rows.')

    def agent(name):
        return LlmAgent(name=name, model=model, mode='single_turn', instruction=instruction_provider,
            before_model_callback=before_model, after_model_callback=after_model, on_model_error_callback=model_error)
    generate, row_repair, sql_repair = agent('blueprint'), agent('blueprint_row_repair'), agent('blueprint_sql_repair')
    edges = [(start, {'generate': generate, 'check': check_rows}), (generate, check_rows),
        (check_rows, {'repair': row_repair, 'view': check_view}), (row_repair, check_rows),
        (check_view, {'repair': sql_repair, 'complete': complete}), (sql_repair, check_view)]
    return start, edges, complete, state
