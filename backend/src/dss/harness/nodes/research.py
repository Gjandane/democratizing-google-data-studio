"""Search -> bounded scraper -> metadata-only selection -> existing intake, in one run."""
import asyncio
import json

from google.adk import Event
from google.adk.agents import LlmAgent
from google.adk.events.event_actions import EventActions
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import google_search
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from dss.data.research import Collector, public_url
from dss.db import now
from dss.harness.context import fit_request, research_context
from dss.harness.guardrails import RunError, check_reply
from dss.harness.nodes.intake import perform, write_doc


class Discovery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    urls: list[str] = Field(min_length=1, max_length=20)


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    table_id: int | None


def json_text(raw):
    raw = raw.strip()
    if raw.startswith('```') and raw.endswith('```'):
        raw = raw.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    return raw


def write_sources(folder, run_id, citations, collector, selected=None):
    docs = folder / 'docs'
    docs.mkdir(parents=True, exist_ok=True)
    path = docs / 'sources.md'
    old = path.read_text(encoding='utf-8').split('---', 2)[-1].strip() if path.exists() else '# Research sources'
    marker = f'\n\n## Run {run_id}\n'
    recorded = marker in old
    old = old.split(marker, 1)[0]  # Update this run's outcome without duplicating its requests.
    body = old + f'\n\n## Run {run_id}\n\nRetrieved: {now()}\n\n'
    body += 'Budget: one Google Search model call; at most 20 scraper HTTP requests. Google-internal fetches are outside this cap.\n'
    body += '\nDiscovery citations:\n' + ''.join(f'- {url}\n' for url in citations)
    body += '\nScraper requests (including redirects and failures):\n'
    body += ''.join(f'- {item["status"]}: {item["url"]}\n' for item in collector.attempts)
    body += f'\nRequests: {len(collector.attempts)}. Stop: {collector.stop_reason or "candidates_exhausted"}.\n'
    if selected is not None:
        body += f'\nSelected for intake: {selected.url}\n\nCSV: research-{run_id}.csv ({len(selected.rows)} rows).\n'
    else:
        body += '\nNo table selected for intake.\n'
    write_doc(path, {'type': 'Research Sources', 'title': 'Research sources'}, body)
    if not (docs / 'index.md').exists():
        write_doc(docs / 'index.md', {'type': 'Index', 'title': 'Build documents'}, '# Build documents\n')
    index = (docs / 'index.md').read_text(encoding='utf-8')
    if 'sources.md' not in index:
        index = index.rstrip() + '\n\n- [Research sources](sources.md)\n'
    if (docs / 'data-profile.md').exists() and 'data-profile.md' not in index:
        index = index.rstrip() + '\n- [Data profile](data-profile.md)\n'
    (docs / 'index.md').write_text(index, encoding='utf-8')
    if not (docs / 'log.md').exists():
        write_doc(docs / 'log.md', {'type': 'Log', 'title': 'Build log'}, '# Build log\n')
    if not recorded:
        with (docs / 'log.md').open('a', encoding='utf-8') as log:
            log.write(f'\n- {now()}: research {run_id}, {len(collector.attempts)} scraper requests.\n')


def make_branch(harness, build_id, run_id, payload, model, trace, model_error):
    config = payload['config']
    secrets = tuple(getattr(config, name).get_secret_value() for name in ('google_api_key', 'access_code', 'agent_token'))
    with harness.db.connect() as connection:
        version = connection.execute('SELECT current_version FROM builds WHERE id=?', (build_id,)).fetchone()[0]
    folder = config.data_dir / 'builds' / build_id / f'v{version}'
    collector = Collector(payload.get('getter'))
    state = {'failure': None, 'discovery': '', 'selection': '', 'citations': [], 'search_calls': 0,
             'select_calls': 0, 'calls': 0}

    def context(phase):
        metadata = [table.metadata(i) for i, table in enumerate(collector.tables)] if phase == 'SELECT' else None
        return check_reply(research_context(payload['prompt'], phase, metadata), secrets)

    async def search_instruction(ctx):
        return context('DISCOVER')

    async def select_instruction(ctx):
        return context('SELECT')

    def before(phase):
        async def callback(callback_context, llm_request):
            key = 'search_calls' if phase == 'DISCOVER' else 'select_calls'
            if state[key]:
                return LlmResponse(error_code='llm_unavailable', error_message='Research model call budget exhausted')
            state[key] += 1
            if phase == 'DISCOVER':
                state['calls'] += 1
            assembled = context(phase)
            trace.span('research_discover' if phase == 'DISCOVER' else 'research_select')
            # Replace accumulated ADK history; no search response or table rows flow to selection.
            llm_request.contents = [types.Content(role='user', parts=[types.Part(text='Follow the phase in working memory.')])]
            # Counting uses no search and no scraper request; the search tool declaration is counted.
            await fit_request(assembled, llm_request, model, trace.spans[-1])
        return callback

    def after(key):
        async def callback(callback_context, llm_response):
            if llm_response.error_code:
                return LlmResponse(error_code='llm_unavailable', error_message='Research model failed')
            try:
                parts = llm_response.content.parts if llm_response.content else []
                raw = ''.join(p.text for p in parts or [] if p.text and not p.thought)
                state[key] = check_reply(raw, secrets)
                if key == 'discovery':
                    metadata = llm_response.grounding_metadata
                    if metadata:
                        for chunk in metadata.grounding_chunks or []:
                            if chunk.web and chunk.web.uri:
                                url = public_url(check_reply(chunk.web.uri, secrets))
                                if url not in state['citations']:
                                    state['citations'].append(url)
            except Exception:
                return LlmResponse(error_code='llm_unavailable', error_message='Unsafe research output')
            # Raw model output is validated by code, never ADK output_schema logging.
            return LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Research response received.')]))
        return callback

    async def fetch(node_input):
        trace.span('research_fetch')
        try:
            discovery = Discovery.model_validate_json(json_text(state['discovery']))
            urls = list(dict.fromkeys(public_url(url) for url in discovery.urls))
            await asyncio.to_thread(collector.collect, urls)
            state['calls'] += len(collector.attempts)
            trace.spans[-1].update(http_requests=len(collector.attempts), stop_reason=collector.stop_reason)
            if not collector.tables:
                raise ValueError('No tables')
        except Exception:
            state['failure'] = RunError('invalid_source', 'Research found no usable public CSV or HTML table', 422)
        # Persist before SELECT: a provider failure or oversized selection context
        # can abort the Workflow without executing finish.
        await asyncio.to_thread(write_sources, folder, run_id, state['citations'], collector)
        return Event(actions=EventActions(route='failed' if state['failure'] else 'select'))

    async def finish(node_input):
        trace.span('research_intake')
        selected = None
        try:
            if not state['failure']:
                selection = Selection.model_validate_json(json_text(state['selection']))
                if selection.table_id is None or not 0 <= selection.table_id < len(collector.tables):
                    raise ValueError('No matching table')
                selected = collector.tables[selection.table_id]
            await asyncio.to_thread(write_sources, folder, run_id, state['citations'], collector, selected)
            if state['failure']:
                return 'Research did not find a usable table.'
            content = selected.csv_bytes()
            name = f'research-{run_id}.csv'
            await asyncio.to_thread((folder / name).write_bytes, content)
            sources = await asyncio.to_thread(perform, harness.db, build_id, {
                'config': config, 'factory': payload['factory'],
                'sources': [{'kind': 'research', 'name': name, 'content': content}]})
            await asyncio.to_thread(write_sources, folder, run_id, state['citations'], collector, selected)
            from dss.api.builds import build_response
            build = build_response(harness.db, config, build_id)
            await harness.emit(build_id, run_id, 'docs.updated', {'docs': build['docs']})
            await harness.emit(build_id, run_id, 'build.updated', {'build': build})
            return f'Research loaded {sources[0]["row_count"]} rows. Sources and retrieval details are in sources.md.'
        except Exception:
            if selected is None and not state['failure']:
                await asyncio.to_thread(write_sources, folder, run_id, state['citations'], collector)
            state['failure'] = RunError('invalid_source', 'Research could not select or load a matching table; check sources and data access', 422)
            return 'Research did not finish.'

    discover = LlmAgent(name='research_discover', model=model, mode='single_turn',
        instruction=search_instruction, tools=[payload.get('search_tool', google_search)],
        before_model_callback=before('DISCOVER'), after_model_callback=after('discovery'), on_model_error_callback=model_error)
    select = LlmAgent(name='research_select', model=model, mode='single_turn',
        instruction=select_instruction, before_model_callback=before('SELECT'),
        after_model_callback=after('selection'), on_model_error_callback=model_error)
    return discover, fetch, select, finish, state
