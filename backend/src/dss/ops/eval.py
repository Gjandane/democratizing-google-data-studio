"""Score the current build version: uv run python -m dss.ops.eval <build_id>."""
import argparse
import asyncio
import json

from google.adk import Workflow
from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from dss.config import Config, SettingsStore
from dss.db import Database, new_id
from dss.harness.context import fit_request, judge_context
from dss.harness.guardrails import RunError, check_reply
from dss.harness.llm import ModelRouter
from dss.harness.tracing import Trace
from dss.spec.models import DashboardSpec


class Scores(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    question_coverage: int = Field(ge=1, le=5)
    catalog_fit: int = Field(ge=1, le=5)
    layout_balance: int = Field(ge=1, le=5)


async def evaluate(db, config, build_id, *, llm=None):
    with db.connect() as conn:
        build = conn.execute('SELECT current_version FROM builds WHERE id=?', (build_id,)).fetchone()
    if build is None:
        raise RunError('build_not_found', 'Build not found', 404)
    version = build[0]
    trace = Trace(db, new_id('r'), build_id, 'judge')
    trace.span('judge')
    trace.spans[-1]['version'] = version
    status, error, runner = 'error', 'llm_unavailable', None
    state = {}
    try:
        folder = config.data_dir / 'builds' / build_id / f'v{version}'
        document = DashboardSpec.model_validate_json((folder / 'spec.json').read_text(encoding='utf-8')).model_dump()
        secrets = tuple(getattr(config, name).get_secret_value() for name in ('google_api_key', 'access_code', 'agent_token'))
        context = check_reply(judge_context(config, folder, document), secrets)
        context.record(trace.spans[-1])
        model = llm if llm is not None else ModelRouter(SettingsStore(config, db)).llm_for('judge')
        trace.model = model.model

        async def instructions(context_object):
            return context

        async def before_model(callback_context, llm_request):
            await fit_request(context, llm_request, model, trace.spans[-1])

        async def after_model(callback_context, llm_response):
            try:
                if llm_response.error_code:
                    raise ValueError('Model failure')
                raw = ''.join(p.text for p in (llm_response.content.parts or []) if p.text and not p.thought) if llm_response.content else ''
                scores = Scores.model_validate_json(check_reply(raw, secrets)).model_dump()
                state['result'] = {**scores, 'pass': all(v >= 3 for v in scores.values())}
            except (ValueError, RunError):
                return LlmResponse(error_code='llm_unavailable', error_message='Invalid judge output')
            return LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Scores validated.')]))

        async def model_error(callback_context, llm_request, error):
            return LlmResponse(error_code='llm_unavailable', error_message='Judge model failed')

        agent = LlmAgent(name='judge', model=model, mode='single_turn', instruction=instructions,
                         generate_content_config=types.GenerateContentConfig(response_mime_type='application/json',
                             response_json_schema=Scores.model_json_schema()),
                         before_model_callback=before_model, after_model_callback=after_model,
                         on_model_error_callback=model_error)
        sessions = InMemorySessionService()
        await sessions.create_session(app_name='dss', user_id='local', session_id=trace.run_id)
        runner = Runner(app_name='dss', node=Workflow(name='judge_run', edges=[('START', agent)]), session_service=sessions)
        async for event in runner.run_async(user_id='local', session_id=trace.run_id,
                new_message=types.Content(role='user', parts=[types.Part(text='Evaluate the spec.')]),
                run_config=RunConfig(max_llm_calls=1)):
            if event.error_code:
                raise RunError('llm_unavailable', 'Judge model failed or returned invalid scores', 503)
            if event.usage_metadata:
                trace.input_tokens += event.usage_metadata.prompt_token_count or 0
                trace.output_tokens += event.usage_metadata.candidates_token_count or 0
        result = state['result']
        trace.spans[-1]['scores'] = result
        status, error = 'ok', None
        return result
    except Exception:
        raise RunError('llm_unavailable', 'Evaluation failed; check the build documents and model settings', 503) from None
    finally:
        trace.save(status, error)
        if runner is not None:
            await runner.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build_id')
    args = parser.parse_args()
    defaults = Config.from_env()
    db = Database(defaults.db_path or defaults.data_dir / 'dss.sqlite', defaults.data_dir)
    db.initialize()
    try:
        result = asyncio.run(evaluate(db, SettingsStore(defaults, db).get(), args.build_id))
    except RunError as exc:
        parser.exit(1, f'{exc.code}: {exc.message}\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
