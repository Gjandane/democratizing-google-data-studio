import asyncio
import json
import struct
import zlib
from pathlib import Path

import pytest
import yaml
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from dss.db import now
from dss.harness.context import BUDGETS, ORDER, assemble, spec_context, ux_audit_context, Section
from dss.harness.guardrails import RunError
from dss.harness.nodes.intake import write_doc
from dss.memory.episodic import messages
from dss.spec.models import DashboardSpec
from fakes import FakeLLM
from test_context import spec_inputs


def png():
    def chunk(kind, data):
        body = kind + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body))
    header = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00')) + chunk(b'IEND', b''))


STYLE = {'palette': ['#1e40af', '#0d9488', '#F59E0B'], 'background': '#f1f5f9', 'surface': '#FFFFFF',
         'text': '#0F172A', 'accent': '#1E40AF', 'font_family': 'Roboto', 'radius': 12, 'notes': 'Clean and blue.'}


class Capture(FakeLLM):
    requests: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request)
        async for item in super().generate_content_async(llm_request, stream):
            yield item


@pytest.fixture
def setup(client, app, build_id):
    config = app.state.settings.get()
    folder = config.data_dir / 'builds' / build_id / 'v1'
    (folder / 'docs').mkdir(parents=True)
    spec = DashboardSpec.model_validate_json(Path('tests/data/thin_spec.json').read_text())
    (folder / 'spec.json').write_text(spec.model_dump_json(), encoding='utf-8')
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='prototype' WHERE id=?", (build_id,))
        conn.execute("INSERT INTO versions(build_id,n,status,spec_version,created_at) VALUES(?,1,'draft',1,?)", (build_id, now()))
    return app, build_id, folder


def findings(*items):
    return json.dumps({'findings': [{'component_id': c, 'severity': s, 'issue': f'{c} issue.', 'suggestion': f'Fix {c}.'}
                                    for c, s in items]})


async def audit(setup, raw, fake=None):
    app, build_id, _ = setup
    fake = fake or Capture(response=raw, requests=[])
    return await app.state.harness.run('ux_audit', build_id, {'config': app.state.settings.get()}, llm=fake), fake


async def test_audit_one_assistant_message_sorted_and_filtered(setup):
    app, bid, _ = setup
    raw = findings(('p1_regions', 'low'), ('p1_revenue', 'high'), ('p1_ghost', 'high'), ('p1_title', 'medium'))
    result, fake = await audit(setup, raw)
    saved = messages(app.state.db, bid)
    assert len(saved) == 1 and saved[0]['role'] == 'assistant' and saved[0]['node'] == 'ux_audit'
    text = saved[0]['text']
    assert text == result['reply'] and 'p1_ghost' not in text
    assert text.index('p1_revenue (high)') < text.index('p1_title (medium)') < text.index('p1_regions (low)')
    assert text.startswith('UX audit findings:\n- p1_revenue (high): p1_revenue issue. Suggestion: Fix p1_revenue.')
    assert fake.calls == 1
    with app.state.db.connect() as conn:
        rows = conn.execute('SELECT * FROM traces').fetchall()
    assert len(rows) == 1 and rows[0]['status'] == 'ok'
    spans = [s['node'] for s in json.loads(rows[0]['spans_json'])]
    assert 'ux_audit' in spans and 'format_findings' in spans
    system = str(fake.requests[0].config.system_instruction)
    assert 'p1_revenue' in system and 'Executive' in system.title() and 'test-key' not in system


async def test_audit_no_valid_findings(setup):
    app, bid, _ = setup
    await audit(setup, findings(('p1_ghost', 'low')))
    assert messages(app.state.db, bid)[0]['text'] == 'UX audit: no issues found.'


@pytest.mark.parametrize('raw', ['not json', json.dumps({'findings': [{'component_id': 'p1_title', 'severity': 'urgent',
                                                                         'issue': 'x', 'suggestion': 'y'}]})])
async def test_audit_invalid_output_fails(setup, raw):
    app, bid, _ = setup
    with pytest.raises(RunError) as error:
        await audit(setup, raw)
    assert error.value.code == 'llm_unavailable' and error.value.status_code == 503
    assert messages(app.state.db, bid) == []
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT status FROM traces').fetchone()[0] == 'error'


def test_audit_api_launch_busy_and_stage(setup, client, monkeypatch):
    app, bid, _ = setup
    started, release = asyncio.Event(), asyncio.Event()
    fake = FakeLLM(response=findings(('p1_title', 'low')), started=started, release=release)
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: fake)
    result = client.post(f'/api/builds/{bid}/audit')
    assert result.status_code == 202 and set(result.json()) == {'run_id'}
    busy = client.post(f'/api/builds/{bid}/audit')
    assert busy.status_code == 409 and busy.json()['error']['code'] == 'wrong_stage'
    client.portal.call(release.set)
    client.portal.call(drain, app)
    assert len(messages(app.state.db, bid)) == 1


async def drain(app):
    for _ in range(500):
        if not app.state.engine_tasks:
            break
        await asyncio.sleep(.01)
    assert not app.state.engine_tasks


def test_audit_api_wrong_stage(setup, client):
    app, bid, _ = setup
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='connect' WHERE id=?", (bid,))
    response = client.post(f'/api/builds/{bid}/audit')
    assert response.status_code == 409 and response.json()['error']['detail'] == {'stage': 'connect'}


def post_style(client, bid, files):
    return client.post(f'/api/builds/{bid}/style-images', files=files)


def test_style_upload_writes_style_md(setup, client, monkeypatch):
    app, bid, folder = setup
    fake = Capture(response=json.dumps(STYLE), requests=[])
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: fake)
    data = png()
    response = post_style(client, bid, [('files', ('Look.PNG', data, 'image/png'))])
    assert response.status_code == 202 and set(response.json()) == {'run_id'}
    client.portal.call(drain, app)
    text = (folder / 'docs/style.md').read_text(encoding='utf-8')
    meta = yaml.safe_load(text.split('---', 2)[1])
    assert meta['type'] == 'Style Profile' and meta['palette'] == ['#1E40AF', '#0D9488', '#F59E0B']
    assert meta['background'] == '#F1F5F9' and meta['sources'] == ['Look.PNG']
    assert '#0D9488' in text
    assert 'style.md' in (folder / 'docs/index.md').read_text(encoding='utf-8')
    parts = fake.requests[0].contents[0].parts
    blobs = [p.inline_data for p in parts if p.inline_data]
    assert len(blobs) == 1 and blobs[0].mime_type == 'image/png' and blobs[0].data == data
    reply = messages(app.state.db, bid)[-1]
    assert reply['node'] == 'style_extract' and '#1E40AF' in reply['text']
    docs = client.get(f'/api/builds/{bid}').json()['docs']
    assert {'path': 'style.md', 'title': 'Style profile', 'type': 'Style Profile'} in docs


def test_style_upload_unsafe_name_keeps_build_readable(setup, client, monkeypatch):
    app, bid, folder = setup
    fake = Capture(response=json.dumps(STYLE), requests=[])
    monkeypatch.setattr(app.state.models, 'llm_for', lambda node: fake)
    assert post_style(client, bid, [('files', ('Q3: a --- b #1.png', png(), 'image/png'))]).status_code == 202
    client.portal.call(drain, app)
    meta = yaml.safe_load((folder / 'docs/style.md').read_text(encoding='utf-8').split('---', 2)[1])
    assert meta['sources'] == ['Q3_a_-_b_1.png']
    assert client.get(f'/api/builds/{bid}').status_code == 200


@pytest.mark.parametrize('files', [
    [('files', ('notes.txt', b'hello', 'text/plain'))],
    [('files', ('fake.png', b'not a png', 'image/png'))],
    [('files', ('swap.jpg', png(), 'image/jpeg'))],
    [('files', ('big.png', png() + b'0' * (5 * 1024 * 1024), 'image/png'))],
    [('files', (f'{i}.png', png(), 'image/png')) for i in range(4)],
])
def test_style_rejects_invalid_files(setup, client, files):
    app, bid, folder = setup
    response = post_style(client, bid, files)
    assert response.status_code == 422 and response.json()['error']['code'] == 'invalid_source'
    assert 'reason' in response.json()['error']['detail']
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM traces').fetchone()[0] == 0
    assert not (folder / 'docs/style.md').exists()


def test_style_wrong_stage(setup, client):
    app, bid, _ = setup
    with app.state.db.connect() as conn:
        conn.execute("UPDATE builds SET stage='build' WHERE id=?", (bid,))
    response = post_style(client, bid, [('files', ('a.png', png(), 'image/png'))])
    assert response.status_code == 409 and response.json()['error']['detail'] == {'stage': 'build'}


async def test_style_invalid_hex_writes_nothing(setup):
    app, bid, folder = setup
    bad = {**STYLE, 'accent': 'blue'}
    fake = FakeLLM(response=json.dumps(bad))
    with pytest.raises(RunError) as error:
        await app.state.harness.run('style_extract', bid, {'config': app.state.settings.get(),
            'images': [{'name': 'a.png', 'mime_type': 'image/png', 'content': png()}]}, llm=fake)
    assert error.value.code == 'llm_unavailable'
    assert not (folder / 'docs/style.md').exists() and messages(app.state.db, bid) == []


def test_spec_context_includes_style_only_when_present(app, build_id):
    folder, build = spec_inputs(app, build_id, 'Revenue: SUM(revenue).')
    config = app.state.settings.get()
    args = (config, folder, build, [], {'bar', 'scorecard', 'time_series'})
    assert 'style.md' not in [s.name for s in spec_context(*args).sections]
    write_doc(folder / 'docs/style.md', {'type': 'Style Profile'}, 'Palette: #1E40AF, #0D9488')
    context = spec_context(*args)
    names = [s.name for s in context.sections]
    assert names[-1] == 'style.md'
    assert '#0D9488' in context and names.index('style.md') > names.index('decisions.md')


def test_ux_audit_context_order_and_budget(app, build_id):
    document = DashboardSpec.model_validate_json(Path('tests/data/thin_spec.json').read_text()).model_dump()
    context = ux_audit_context(app.state.settings.get(), document, 'executive')
    assert [s.kind for s in context.sections] == ['system', 'skills', 'semantic', 'docs', 'input']
    assert context.sections[2].name == 'archetypes/executive.md' and 'p1_revenue' in context.sections[3].text
    assert [ORDER.index(s.kind) for s in context.sections] == sorted(ORDER.index(s.kind) for s in context.sections)
    document['pages'][0]['components'][0]['label'] = 'x' * (BUDGETS['ux_audit'] * 4)
    with pytest.raises(RunError) as error:
        ux_audit_context(app.state.settings.get(), document, 'executive')
    assert error.value.status_code == 503


async def test_audit_and_style_count_the_whole_request(setup):
    from test_context import assert_counted, counting
    from dss.harness.context import IMAGE_TOKENS, request_estimate
    app, bid, _ = setup
    seen = []

    class Seen(Capture):
        async def count_request_tokens(self, llm_request):
            seen.append(llm_request.model_copy(deep=True))
            return request_estimate(llm_request) // 2

    _, audit_model = await audit(setup, '', counting(Capture)(response=findings(('p1_revenue', 'low')), requests=[]))
    style_model = Seen(response=json.dumps(STYLE), requests=[])
    await app.state.harness.run('style_extract', bid, {'config': app.state.settings.get(),
        'images': [{'name': 'a.png', 'mime_type': 'image/png', 'content': png()}]}, llm=style_model)
    with app.state.db.connect() as conn:
        rows = conn.execute("SELECT node, spans_json FROM traces WHERE node IN ('ux_audit','style_extract')").fetchall()
    spans = {node: next(s for s in json.loads(raw) if s['node'] == node) for node, raw in rows}
    assert_counted(spans['ux_audit'], audit_model)
    style = spans['style_extract']
    # The image is in the counted request; offline its estimate adds IMAGE_TOKENS.
    assert [p.inline_data.data for p in seen[0].contents[0].parts if p.inline_data] == [png()]
    assert style['input_tokens_estimate'] > IMAGE_TOKENS and style['request_tokens'] == style['input_tokens_estimate'] // 2
    assert audit_model.calls == 1 and style_model.calls == 1
