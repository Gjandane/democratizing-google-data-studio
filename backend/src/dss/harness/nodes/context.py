"""Context drafting, deterministic semantic checks and code-owned publication."""
import asyncio
from collections import Counter
import json
import re

from google.adk import Event
from google.adk.agents import LlmAgent
from google.adk.events.event_actions import EventActions
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import ValidationError

from dss.artifacts import state as stages
from dss.artifacts.models import Context, ValidationIssue
from dss.artifacts.okf import read_artifact, write_artifact
from dss.data.bigquery import quoted, table_uri
from dss.data.profile import NUMBERS, DATES
from dss.harness.context import context_draft_context, context_repair_context, fit_request
from dss.harness.guardrails import RunError, check_reply
from dss.harness import stages as execution_stages
from dss.harness.nodes.style_extract import provider_schema
from dss.harness.nodes.view import expression

MAX_OUTPUT_TOKENS = 3000
# Hide literals and quoted identifiers before testing function names.
QUOTED = re.compile(r"(?i:\b(?:r|b|rb|br))?(?:'(?:\\.|''|[^'\\])*'|\"(?:\\.|\"\"|[^\"\\])*\")|`(?:\\.|[^`\\])*`")
AGGREGATE = re.compile(r'\b(?:SUM|AVG|COUNT|COUNTIF|MIN|MAX|ANY_VALUE|ARRAY_AGG|ARRAY_CONCAT_AGG|STRING_AGG|'
                       r'LOGICAL_AND|LOGICAL_OR|BIT_AND|BIT_OR|BIT_XOR|CORR|COVAR_POP|COVAR_SAMP|'
                       r'STDDEV(?:_POP|_SAMP)?|VARIANCE|VAR_POP|VAR_SAMP|GROUPING|MAX_BY|MIN_BY|'
                       r'ST_UNION_AGG|ST_CENTROID_AGG|ST_EXTENT|APPROX_\w+)\s*\(|\bOVER\s*\(|'
                       r'\b(?:HLL_COUNT\s*\.\s*(?:INIT|MERGE)|KLL_QUANTILES\s*\.\s*(?:INIT|MERGE)\w*)\s*\(', re.I)


def load(folder):
    path = folder / 'docs/context.md'
    return read_artifact(path, Context) if path.is_file() else None


def sources(db, build_id):
    with db.connect() as conn:
        return [{**dict(row), 'columns': json.loads(row['columns_json'])} for row in
                conn.execute('SELECT * FROM sources WHERE build_id=? ORDER BY rowid', (build_id,))]


def validate(draft, connected, service):
    """Replace model/user issues. One dry run checks all safe derived expressions together.

    BigQuery is the SQL parser and resolves expression field references; its errors
    never cross this boundary. No query executes and no data rows are retrieved.
    """
    issues = []
    def issue(path, message):
        issues.append(ValidationIssue(path=path, message=message))
    fields = {c['name']: c['type'] for source in reversed(connected) for c in source['columns']}
    base_fields = set(fields)
    source_ids = {s['id'] for s in connected}
    for i, dataset in enumerate(draft.datasets):
        if dataset.source_id not in source_ids:
            issue(f'/datasets/{i}/source_id', 'Unknown connected source')
    for name, limit in (('kpis', 15), ('derived_fields', 15), ('thresholds', 15), ('glossary', 30)):
        if len(getattr(draft, name)) > limit:
            issue('/' + name, f'At most {limit} entries are allowed')
    ids = Counter(item.id for item in [*draft.kpis, *draft.thresholds])
    for group in ('kpis', 'thresholds'):
        for i, item in enumerate(getattr(draft, group)):
            if not re.fullmatch(r'[a-z][a-z0-9_]*', item.id) or ids[item.id] != 1:
                issue(f'/{group}/{i}/id', 'IDs must be unique snake_case')
    names = Counter(d.name for d in draft.derived_fields)
    sql, paths = [], []
    for i, derived in enumerate(draft.derived_fields):
        path = f'/derived_fields/{i}'
        if derived.name.casefold() in {name.casefold() for name in base_fields} or names[derived.name] != 1:
            issue(path + '/name', 'Derived names must be unique and cannot collide with columns')
        else:
            fields[derived.name] = derived.type
        try:
            safe = expression(derived.expression, base_fields)
            if AGGREGATE.search(QUOTED.sub(' ', safe)):
                raise ValueError('Derived expressions cannot contain aggregate or window functions')
            sql.append(f'{safe} AS {quoted(derived.name)}')
            paths.append(path + '/expression')
        except ValueError:
            issue(path + '/expression', 'Use one scalar expression without aggregates, windows or subqueries')
    if sql:
        try:
            if not connected:
                raise ValueError('No base source')
            # Including unaggregated base columns also makes BigQuery reject any
            # aggregate spelling the fast lexical guard did not recognize.
            schema = service().dry_run('SELECT t0.*, ' + ', '.join(sql) + '\nFROM ' +
                                       quoted(table_uri(connected[0]['bq_table'])) + ' AS t0')
            actual = {field.name: ('string' if field.mode == 'REPEATED' else
                'number' if field.field_type in NUMBERS else 'date' if field.field_type == 'DATE' else
                'datetime' if field.field_type in DATES else 'boolean' if field.field_type in ('BOOL', 'BOOLEAN') else
                'geo' if field.field_type == 'GEOGRAPHY' else 'string') for field in schema or []}
            for i, derived in enumerate(draft.derived_fields):
                if f'/derived_fields/{i}/expression' in paths and actual.get(derived.name) != derived.type:
                    issue(f'/derived_fields/{i}/type', 'Declared type must match the BigQuery expression result')
        except Exception:
            for path in paths:
                issue(path, 'Expression must resolve against the base source and pass a BigQuery dry run')
    measures = {k.id for k in draft.kpis if k.measure is not None}
    for i, kpi in enumerate(draft.kpis):
        path = f'/kpis/{i}'
        if kpi.measure:
            field, agg = kpi.measure.field, kpi.measure.agg
            if field not in fields:
                issue(path + '/measure/field', 'Unknown field')
            elif ((agg in ('sum', 'avg') and fields[field] != 'number') or
                  (agg in ('min', 'max') and fields[field] not in ('number', 'date', 'datetime'))):
                issue(path + '/measure/agg', 'Aggregation is incompatible with the field type')
        if kpi.ratio:
            for part in ('numerator', 'denominator'):
                if getattr(kpi.ratio, part) not in measures:
                    issue(path + '/ratio/' + part, 'A ratio must name a measure KPI')
    for i, threshold in enumerate(draft.thresholds):
        if fields.get(threshold.field) != 'number':
            issue(f'/thresholds/{i}/field', 'Threshold field must exist and be numeric')
    return draft.model_copy(update={'issues': issues})


async def persist(harness, build, folder, run_id, draft):
    old = load(folder)
    draft = draft.model_copy(update={'revision': old.revision + 1 if old else 1})
    await write_artifact(folder / 'docs/context.md', draft,
        emit=lambda kind, payload: harness.emit(build['id'], run_id, kind, payload))
    # Connect is the one initial transition; edited() handles downstream invalidation.
    stages.save(harness.db, build['id'], stages.edited({**build, 'stage': 'context'}, 'context'))
    await harness.emit(build['id'], run_id, 'stage.changed', {'stage': 'context'})
    from dss.api.builds import build_response
    await harness.emit(build['id'], run_id, 'build.updated', {
        'build': build_response(harness.db, harness.models.settings.get(), build['id'])})
    return draft


def make_branch(harness, build_id, run_id, payload, model, trace, model_error):
    config, folder, build = payload['config'], payload['folder'], payload['build']
    connected = sources(harness.db, build_id)
    secret = config.google_api_key.get_secret_value()
    initial = context_draft_context(config, connected, build.get('notes'), build['archetype'])
    check_reply(initial, (secret, config.access_code.get_secret_value(), config.agent_token.get_secret_value()))
    state = {'raw': '', 'draft': None, 'issues': [], 'repair': False, 'failure': None}

    async def instruction_provider(context_object):
        return str(initial)

    async def before_model(callback_context, llm_request):
        trace.span('context_repair' if state['repair'] else 'context')
        context = context_repair_context(state['raw'], state['issues']) if state['repair'] else initial
        llm_request.config.system_instruction = str(context)
        llm_request.config.response_mime_type = 'application/json'
        llm_request.config.response_json_schema = provider_schema(Context)
        llm_request.config.max_output_tokens = MAX_OUTPUT_TOKENS
        llm_request.config.thinking_config = types.ThinkingConfig(thinking_level='LOW')
        llm_request.contents = [types.Content(role='user', parts=[types.Part(text='Return the Context JSON draft only.')])]
        await fit_request(context, llm_request, model, trace.spans[-1])

    async def after_model(callback_context, llm_response):
        if llm_response.error_code or llm_response.finish_reason == types.FinishReason.MAX_TOKENS:
            return LlmResponse(error_code='llm_unavailable', error_message='Context generation failed')
        raw = ''.join(p.text for p in (llm_response.content.parts or []) if p.text and not p.thought) if llm_response.content else ''
        try:
            state['raw'] = check_reply(raw, (secret, config.access_code.get_secret_value(), config.agent_token.get_secret_value()))
        except RunError:
            execution_stages.invalid_output('context')
            return LlmResponse(error_code='llm_unavailable', error_message='Context returned unsafe output')
        return LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Context received for validation.')]),
                           usage_metadata=llm_response.usage_metadata)

    async def check(node_input):
        trace.span('validate_context')
        try:
            draft = Context.model_validate_json(state['raw'])
            state['draft'] = await asyncio.to_thread(validate, draft, connected, lambda: payload['factory'](config))
            state['issues'] = [i.model_dump() for i in state['draft'].issues]
        except ValidationError as exc:
            state['draft'] = None
            state['issues'] = [{'path': '/' + '/'.join(map(str, e['loc'])), 'message': 'Invalid Context structure: ' + e['type']}
                               for e in exc.errors(include_input=False, include_context=False)]
        if state['issues']:
            execution_stages.invalid_output('context')
        if state['issues'] and not state['repair']:
            state['repair'] = True
            return Event(actions=EventActions(route='repair'))
        return Event(actions=EventActions(route='complete'))

    async def complete(node_input):
        if state['draft'] is None:
            state['failure'] = RunError('llm_unavailable', 'The model returned an invalid Context structure; draft again',
                                       503, {'issues': state['issues']})
            return 'Context could not be drafted.'
        await persist(harness, build, folder, run_id, state['draft'])
        return ('Context drafted. Review its KPI assumptions and resolve the listed issues.' if state['issues'] else
                'Context drafted. Review its KPI assumptions, then confirm to continue.')

    def agent(name):
        return LlmAgent(name=name, model=model, mode='single_turn', instruction=instruction_provider,
            before_model_callback=before_model, after_model_callback=after_model, on_model_error_callback=model_error)
    return agent('context'), agent('context_repair'), check, complete, state
