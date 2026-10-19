"""Style extract branch: vision call to a validated style profile, written by code as style.md."""
import asyncio
from typing import Annotated

from google.adk.agents import LlmAgent
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from dss.db import now
from dss.harness.context import fit_request, style_context
from dss.harness.guardrails import RunError, check_reply

Hex = Annotated[str, Field(pattern=r'^#[0-9A-Fa-f]{6}$')]


class StyleProfile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    palette: list[Hex] = Field(min_length=2, max_length=8)
    background: Hex
    surface: Hex
    text: Hex
    accent: Hex
    font_family: str = Field(min_length=1, max_length=60, pattern=r'^[A-Za-z0-9 -]+$')
    radius: int = Field(ge=0, le=32)
    notes: str = Field(default='', max_length=1000)

    @field_validator('palette', mode='after')
    @classmethod
    def upper_palette(cls, value):
        return [v.upper() for v in value]

    @field_validator('background', 'surface', 'text', 'accent', mode='after')
    @classmethod
    def upper(cls, value):
        return value.upper()


def response_schema():
    schema = StyleProfile.model_json_schema()

    def provider_limits(value):
        # Nested array maxima are rejected by the worker; Pydantic keeps them.
        if isinstance(value, dict):
            value.pop('maxItems', None)
            for child in value.values():
                provider_limits(child)
        elif isinstance(value, list):
            for child in value:
                provider_limits(child)
    provider_limits(schema)
    return schema


def write_style(folder, profile, sources):
    from dss.harness.nodes.intake import write_doc
    docs = folder / 'docs'
    docs.mkdir(parents=True, exist_ok=True)
    body = '# Style profile\n\nPalette: ' + ', '.join(profile.palette) + '\n\n' + '\n'.join(
        f'- {k}: {getattr(profile, k)}' for k in ('background', 'surface', 'text', 'accent', 'font_family', 'radius'))
    if profile.notes:
        body += '\n\nNotes (model text, untrusted):\n\n' + ' '.join(profile.notes.split())
    write_doc(docs / 'style.md', {'type': 'Style Profile', 'title': 'Style profile', **profile.model_dump(exclude={'notes'}),
                                  'sources': sources}, body + '\n')
    if not (docs / 'index.md').exists():
        write_doc(docs / 'index.md', {'type': 'Index', 'title': 'Build documents'}, '# Build documents\n\n- [Style profile](style.md)\n')
    else:
        index = (docs / 'index.md').read_text(encoding='utf-8')
        if 'style.md' not in index:
            (docs / 'index.md').write_text(index.rstrip('\n') + '\n- [style.md](style.md)\n', encoding='utf-8')
    if not (docs / 'log.md').exists():
        write_doc(docs / 'log.md', {'type': 'Log', 'title': 'Build log'}, '# Build log\n')
    with (docs / 'log.md').open('a', encoding='utf-8') as log:
        log.write(f'\n- {now()}: style.md written from {len(sources)} image(s)\n')


def make_branch(harness, build_id, run_id, payload, model, trace, model_error):
    config, images = payload['config'], payload['images']
    secret = config.google_api_key.get_secret_value()
    with harness.db.connect() as conn:
        version = conn.execute('SELECT current_version FROM builds WHERE id=?', (build_id,)).fetchone()[0]
    folder = config.data_dir / 'builds' / build_id / f'v{version}'
    context = check_reply(style_context(config), (secret,))
    state = {'raw': '', 'failure': None}

    async def instruction_provider(context_object):
        return context

    async def before_model(callback_context, llm_request):
        trace.span('style_extract')
        llm_request.config.response_mime_type = 'application/json'
        llm_request.config.response_json_schema = response_schema()
        text = 'Extract the style profile from these images.'
        llm_request.contents = [types.Content(role='user', parts=[types.Part(text=text), *[
            types.Part.from_bytes(data=image['content'], mime_type=image['mime_type']) for image in images]])]
        # The images are part of the counted request (IMAGE_TOKENS each when offline).
        await fit_request(context, llm_request, model, trace.spans[-1])

    async def after_model(callback_context, llm_response):
        if llm_response.error_code:
            return LlmResponse(error_code='llm_unavailable', error_message='Style model failed')
        raw = ''.join(p.text for p in (llm_response.content.parts or []) if p.text and not p.thought) if llm_response.content else ''
        try:
            state['raw'] = check_reply(raw, (secret,))
        except RunError:
            return LlmResponse(error_code='llm_unavailable', error_message='Style model returned unsafe output')
        return LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Profile received for validation.')]),
            usage_metadata=llm_response.usage_metadata)

    async def save(node_input):
        trace.span('write_style')
        try:
            profile = StyleProfile.model_validate_json(state['raw'])
        except (ValidationError, ValueError):
            state['failure'] = RunError('llm_unavailable', 'Style extraction returned an invalid profile', 503)
            return 'Style extraction did not finish.'
        await asyncio.to_thread(write_style, folder, profile, [i['name'] for i in images])
        from dss.api.builds import build_response
        await harness.emit(build_id, run_id, 'docs.updated', {'docs': build_response(harness.db, config, build_id)['docs']})
        return 'Style profile saved: palette ' + ', '.join(profile.palette)

    agent = LlmAgent(name='style_extract', model=model, mode='single_turn', instruction=instruction_provider,
        before_model_callback=before_model, after_model_callback=after_model, on_model_error_callback=model_error)
    return agent, save, state
