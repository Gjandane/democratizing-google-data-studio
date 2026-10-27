"""One bounded schema suggestion from the recreate reference analysis items; never generates rows."""
from typing import Annotated

from google.adk.agents import LlmAgent
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dss.data import synthetic
from dss.db import new_id
from dss.harness.context import fit_request, synthetic_schema_context
from dss.harness.guardrails import RunError, check_reply
from dss.harness.nodes.style_extract import provider_schema
from dss.spec import references

FILE = 'synthetic-proposal.json'
MAX_OUTPUT_TOKENS = 6000
EDITED_NOTE = 'Schema edited by user; every row remains invented sample data.'


class Suggestion(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    spec: synthetic.GenerationSpec
    assumptions: list[Annotated[str, Field(min_length=1, max_length=240)]] = Field(max_length=20)


class Proposal(Suggestion):
    id: str
    reference_set_id: str


def load(folder):
    """Only the current reference's suggestion is available; old files are harmless."""
    path = folder / FILE
    reference = references.load(folder)
    if not path.is_file() or not reference or reference['mode'] != 'recreate':
        return None
    proposal = Proposal.model_validate_json(path.read_text(encoding='utf-8'))
    return proposal if proposal.reference_set_id == reference['id'] else None


def stale():
    return RunError('synthetic_proposal_stale', 'The schema proposal or reference is no longer current; '
                    'request a new proposal or enter a manual schema', 409)


def make_branch(harness, build_id, run_id, payload, model, trace, model_error):
    config, folder, reference = payload['config'], payload['folder'], payload['reference']
    secret = config.google_api_key.get_secret_value()
    context = check_reply(synthetic_schema_context(reference), (secret,))
    state = {'raw': '', 'failure': None}

    async def instruction_provider(context_object):
        return context

    async def before_model(callback_context, llm_request):
        trace.span('synthetic_schema')
        llm_request.config.response_mime_type = 'application/json'
        llm_request.config.response_json_schema = provider_schema(Suggestion)
        llm_request.config.max_output_tokens = MAX_OUTPUT_TOKENS
        llm_request.config.thinking_config = types.ThinkingConfig(thinking_level='LOW')
        llm_request.contents = [types.Content(role='user', parts=[types.Part(text='Return the schema suggestion only.')])]
        await fit_request(context, llm_request, model, trace.spans[-1])

    async def after_model(callback_context, llm_response):
        if llm_response.error_code or llm_response.finish_reason == types.FinishReason.MAX_TOKENS:
            return LlmResponse(error_code='llm_unavailable', error_message='Schema proposal model failed')
        raw = ''.join(p.text for p in (llm_response.content.parts or []) if p.text and not p.thought) if llm_response.content else ''
        try:
            state['raw'] = check_reply(raw, (secret,))
        except RunError:
            return LlmResponse(error_code='llm_unavailable', error_message='Schema proposal returned unsafe output')
        return LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Suggestion received for validation.')]),
                           usage_metadata=llm_response.usage_metadata)

    async def finish(node_input):
        trace.span('write_synthetic_proposal')
        try:
            # Size/JSON/compiler validation also enforces cross-column dependencies and types.
            if len(state['raw'].encode('utf-8')) > synthetic.MAX_REQUEST_BYTES:
                raise ValueError('oversized suggestion')
            suggestion = Suggestion.model_validate_json(state['raw'])
            synthetic.parse_spec(suggestion.spec)
        except (ValidationError, ValueError):
            state['failure'] = RunError('llm_unavailable', 'The model returned an invalid sample-data schema; '
                                        'request a new proposal or enter a manual schema', 503)
            return 'Sample-data schema proposal did not finish.'
        current = references.load(folder)
        if not current or current['id'] != reference['id'] or current['mode'] != 'recreate':
            state['failure'] = stale()
            return 'Sample-data schema proposal did not finish.'
        proposal = Proposal(id=new_id('proposal'), reference_set_id=reference['id'], **suggestion.model_dump())
        # Atomic publication on local disk; a single file is the proposal record on the volume.
        folder.mkdir(parents=True, exist_ok=True)
        temp = folder / (FILE + '.tmp')
        temp.write_text(proposal.model_dump_json(indent=2) + '\n', encoding='utf-8')
        temp.replace(folder / FILE)
        from dss.api.builds import build_response
        built = build_response(harness.db, config, build_id)
        await harness.emit(build_id, run_id, 'build.updated', {'build': built})
        await harness.emit(build_id, run_id, 'docs.updated', {'docs': built['docs']})
        return ('Sample-data schema suggested for invented rows, not recovered original data. '
                'Review its assumptions and edit it before choosing Generate.')
    agent = LlmAgent(name='synthetic_schema', model=model, mode='single_turn', instruction=instruction_provider,
        before_model_callback=before_model, after_model_callback=after_model, on_model_error_callback=model_error)
    return agent, finish, state
