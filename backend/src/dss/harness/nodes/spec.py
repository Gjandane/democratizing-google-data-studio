"""Planner spec node; code owns bindings, validation, persistence and repairs."""
import json
from google.adk.agents import LlmAgent
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from dss.db import now
from dss.harness.context import spec_context
from dss.harness.guardrails import RunError, check_reply
from dss.memory.semantic import parse_concept
from dss.spec.models import DashboardSpec
from dss.spec.validate import allowed_types, catalog, high_questions
from dss.harness.nodes.validate import make_validator


def datasource_fields(sources, derived):
    """Match the deterministic view's first-occurrence projection and derived fields."""
    from dss.data.bigquery import snake_names
    fields = {}
    for source in sources:
        for column, name in zip(source['columns'], snake_names([c['name'] for c in source['columns']])):
            kind = 'DATE' if column.get('date_like') and column.get('bq_type', 'STRING') == 'STRING' else column.get('bq_type', column['type']).upper()
            kind = {'NUMBER': 'FLOAT', 'STRING': 'STRING', 'DATETIME': 'DATETIME', 'BOOLEAN': 'BOOLEAN'}.get(kind, kind)
            metric = kind in ('INT64', 'INTEGER', 'FLOAT', 'FLOAT64', 'NUMERIC', 'BIGNUMERIC')
            fields.setdefault(name, dict(name=name, type=kind, label=name.replace('_', ' ').title(),
                role='metric' if metric else 'dimension', default_agg='sum' if metric else 'none'))
    for field in derived:
        kind = field['type']
        metric = kind in ('INTEGER', 'FLOAT', 'NUMERIC')
        fields[field['name']] = dict(name=field['name'], type=kind, label=field['name'].replace('_', ' ').title(),
            role='metric' if metric else 'dimension', default_agg='sum' if metric else 'none')
    return list(fields.values())


def make_branch(harness, build_id, run_id, payload, model, trace, model_error):
    config = payload['config']
    state = {'raw': '', 'errors': [], 'repairs': 0, 'failure': None}
    prepared = {}
    secret = config.google_api_key.get_secret_value()

    def prepare():
        if prepared:
            return
        with harness.db.connect() as conn:
            build = dict(conn.execute('SELECT * FROM builds WHERE id=?', (build_id,)).fetchone())
            sources = [{'columns': json.loads(r[0]), 'bq_table': r[1]} for r in conn.execute('SELECT columns_json,bq_table FROM sources WHERE build_id=? ORDER BY rowid', (build_id,))]
            row = conn.execute('SELECT spec_version FROM versions WHERE build_id=? AND n=?', (build_id, build['current_version'])).fetchone()
        folder = config.data_dir / 'builds' / build_id / f"v{build['current_version']}"
        derived = parse_concept('derived-fields.md', (folder / 'docs/derived-fields.md').read_text(encoding='utf-8')).metadata
        selected = ([sources[0]] if sources else []) + [s for j in derived.get('joins', []) for s in sources if s['bq_table'] == j['table']]
        fields = datasource_fields(selected, derived.get('fields', []))
        build.update(table=derived['view'], spec_version=((row[0] if row else 0) or 0) + 1)
        expected = {k: build[k] for k in ('id', 'archetype', 'spec_version')}
        expected['build_id'] = expected.pop('id')
        expected['datasource'] = {'table': build['table'], 'fields': fields}
        allowed = allowed_types() & catalog().keys()
        if not allowed:
            raise RunError('invalid_request', 'DSS_ALLOWED_TYPES contains no catalog types', 422)
        prepared.update(context=spec_context(config, folder, build, fields, allowed), expected=expected,
            allowed=allowed, questions=high_questions((folder / 'docs/questions.md').read_text(encoding='utf-8')),
            folder=folder, version=build['current_version'])

    async def instruction_provider(context_object):
        prepare()
        context = prepared['context']
        if state['errors']:
            context += '\nPrevious output (untrusted):\n' + state['raw'] + '\nValidation errors:\n' + json.dumps(state['errors']) + '\nReturn the complete repaired JSON object.'
        if len(context) > 64000:
            raise RunError('llm_unavailable', 'Spec repair exceeds its input budget', 503)
        return context

    async def before_model(callback_context, llm_request):
        prepare()
        trace.span('spec_repair' if state['repairs'] else 'spec')
        schema = DashboardSpec.model_json_schema()
        schema['$defs']['Component']['properties']['type']['enum'] = sorted(prepared['allowed'])
        llm_request.config.response_mime_type = 'application/json'
        llm_request.config.response_json_schema = schema

    async def after_model(callback_context, llm_response):
        if llm_response.error_code:
            return LlmResponse(error_code='llm_unavailable', error_message='The spec model failed')
        raw = ''.join(p.text for p in (llm_response.content.parts or []) if p.text and not p.thought) if llm_response.content else ''
        state['raw'] = check_reply(raw, (secret,))
        # Validate in our code node rather than ADK output_schema, which logs invalid inputs.
        return LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Spec received for validation.')]))

    async def save(value):
        spec = DashboardSpec.model_validate(value)
        folder = prepared['folder']
        temporary = folder / 'spec.json.tmp'
        temporary.write_text(spec.model_dump_json(indent=2), encoding='utf-8')
        temporary.replace(folder / 'spec.json')
        with harness.db.connect() as conn:
            conn.execute("UPDATE versions SET spec_version=?,status='draft' WHERE build_id=? AND n=?", (spec.spec_version, build_id, prepared['version']))
            conn.execute('UPDATE builds SET updated_at=? WHERE id=?', (now(), build_id))

    async def validate(node_input):
        prepare()
        return await make_validator(state, allowed=prepared['allowed'], high_priority=prepared['questions'],
            expected=prepared['expected'], trace=trace, save=save)(node_input)

    def agent(name):
        return LlmAgent(name=name, model=model, mode='single_turn', instruction=instruction_provider,
            before_model_callback=before_model, after_model_callback=after_model, on_model_error_callback=model_error)
    return agent('spec'), agent('spec_repair'), validate, state
