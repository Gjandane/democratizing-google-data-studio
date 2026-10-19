"""UX audit branch: one structured LLM call, findings formatted by code into one message."""
from typing import Literal

from google.adk.agents import LlmAgent
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dss.harness.context import fit_request, ux_audit_context
from dss.harness.guardrails import RunError, check_reply
from dss.spec.models import DashboardSpec

ORDER = {'high': 0, 'medium': 1, 'low': 2}


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Finding(Strict):
    component_id: str = Field(max_length=100)
    severity: Literal['high', 'medium', 'low']
    issue: str = Field(min_length=1, max_length=500)
    suggestion: str = Field(min_length=1, max_length=500)


class Audit(Strict):
    findings: list[Finding] = Field(max_length=20)


def response_schema():
    schema = Audit.model_json_schema()

    def provider_limits(value):
        # The worker rejects nested maxItems; Pydantic keeps the limit at validation time.
        if isinstance(value, dict):
            value.pop('maxItems', None)
            for child in value.values():
                provider_limits(child)
        elif isinstance(value, list):
            for child in value:
                provider_limits(child)
    provider_limits(schema)
    return schema


def format_findings(audit, ids):
    valid = sorted((f for f in audit.findings if f.component_id in ids), key=lambda f: ORDER[f.severity])
    if not valid:
        return 'UX audit: no issues found.'
    return 'UX audit findings:\n' + '\n'.join(
        f'- {f.component_id} ({f.severity}): {f.issue} Suggestion: {f.suggestion}' for f in valid)


def make_branch(harness, build_id, run_id, payload, model, trace, model_error):
    config = payload['config']
    secret = config.google_api_key.get_secret_value()
    with harness.db.connect() as conn:
        build = conn.execute('SELECT current_version, archetype FROM builds WHERE id=?', (build_id,)).fetchone()
    folder = config.data_dir / 'builds' / build_id / f'v{build[0]}'
    document = DashboardSpec.model_validate_json((folder / 'spec.json').read_text(encoding='utf-8')).model_dump()
    ids = {item['id'] for page in document['pages'] for item in page['components'] + page['decorations']}
    context = check_reply(ux_audit_context(config, document, build[1]), (secret,))
    state = {'raw': '', 'failure': None}

    async def instruction_provider(context_object):
        return context

    async def before_model(callback_context, llm_request):
        trace.span('ux_audit')
        llm_request.config.response_mime_type = 'application/json'
        llm_request.config.response_json_schema = response_schema()
        llm_request.contents = [types.Content(role='user', parts=[types.Part(text='Return the audit findings.')])]
        await fit_request(context, llm_request, model, trace.spans[-1])

    async def after_model(callback_context, llm_response):
        if llm_response.error_code:
            return LlmResponse(error_code='llm_unavailable', error_message='UX audit model failed')
        raw = ''.join(p.text for p in (llm_response.content.parts or []) if p.text and not p.thought) if llm_response.content else ''
        try:
            state['raw'] = check_reply(raw, (secret,))
        except RunError:
            return LlmResponse(error_code='llm_unavailable', error_message='UX audit model returned unsafe output')
        return LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Findings received for validation.')]))

    async def finish(node_input):
        trace.span('format_findings')
        try:
            return format_findings(Audit.model_validate_json(state['raw']), ids)
        except (ValidationError, ValueError):
            state['failure'] = RunError('llm_unavailable', 'UX audit returned invalid findings', 503)
            return 'UX audit did not finish.'

    agent = LlmAgent(name='ux_audit', model=model, mode='single_turn', instruction=instruction_provider,
        before_model_callback=before_model, after_model_callback=after_model, on_model_error_callback=model_error)
    return agent, finish, state
