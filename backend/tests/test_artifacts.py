import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from dss.artifacts import models, okf

FIXTURES = Path(__file__).parents[2] / 'contracts/fixtures/api'


@pytest.mark.parametrize('name,model', [('context', models.Context), ('outline', models.Outline),
    ('design', models.Design), ('blueprint', models.Blueprint), ('blueprint.blocked', models.Blueprint)])
async def test_contract_roundtrip(tmp_path, name, model):
    fixture = json.loads((FIXTURES / f'{name}.json').read_text(encoding='utf-8'))
    value = model.model_validate(fixture)
    assert value.model_dump(mode='json') == fixture
    events = []
    async def emit(kind, payload):
        events.append((kind, payload))
    artifact_name = name.split('.')[0]
    path = tmp_path / f'{artifact_name}.md'
    await okf.write_artifact(path, value, emit=emit)
    meta = okf.frontmatter(path)
    assert meta['type'] == okf.KINDS[model][1]
    assert meta['revision'] == fixture['revision'] and meta['data'] == fixture
    assert okf.read_artifact(path) == value
    assert okf.frontmatter(tmp_path / 'index.md')['type'] == 'Index'
    assert okf.frontmatter(tmp_path / 'log.md')['type'] == 'Log'
    assert f']({path.name})' in (tmp_path / 'index.md').read_text(encoding='utf-8')
    assert events == [('artifact.updated', {'artifact': artifact_name, 'revision': value.revision}),
                      ('docs.updated', {'docs': [{'path': path.name, 'title': meta['title'], 'type': meta['type']}]})]
    # Body deliberately isn't YAML or authoritative JSON.
    path.write_text(path.read_text(encoding='utf-8').split('\n---\n', 1)[0] + '\n---\n[invalid: yaml\n', encoding='utf-8')
    assert okf.read_artifact(path, model) == value
    with pytest.raises(ValueError, match='type'):
        okf.read_artifact(path, models.Design if model is not models.Design else models.Context)


def fixture_model(name, model):
    return model.model_validate_json((FIXTURES / f'{name}.json').read_text(encoding='utf-8'))


async def test_atomic_failure_keeps_existing_artifact_and_emits_nothing(tmp_path, monkeypatch):
    path = tmp_path / 'context.md'
    events = []
    async def emit(kind, payload):
        events.append(kind)
    artifact = fixture_model('context', models.Context)
    await okf.write_artifact(path, artifact, emit=emit)
    before = path.read_bytes()
    events.clear()
    monkeypatch.setattr(Path, 'replace', Mock(side_effect=OSError('rename failed')))
    with pytest.raises(OSError):
        await okf.write_artifact(path, artifact.model_copy(update={'revision': 9}), emit=emit)
    assert path.read_bytes() == before and events == []
    assert {p.name for p in tmp_path.iterdir()} == {'context.md', 'index.md', 'log.md'}


async def test_mutations_revalidated_and_unicode_readable_render(tmp_path):
    artifact = fixture_model('context', models.Context)
    artifact.title = 'Café — 売上'
    artifact.kpis[0].name = 'Revenue | net\nUSD'
    events = []
    async def emit(kind, payload):
        events.append(kind)
    path = tmp_path / 'context.md'
    await okf.write_artifact(path, artifact, emit=emit)
    assert okf.read_artifact(path) == artifact
    body = path.read_text(encoding='utf-8').split('\n---\n', 1)[1]
    assert 'Café — 売上' in body and 'Revenue \\| net USD' in body
    artifact.kpis[0].ratio = models.Ratio(numerator='a', denominator='b')
    events.clear()
    before = path.read_bytes()
    with pytest.raises(ValidationError):
        await okf.write_artifact(path, artifact, emit=emit)
    assert path.read_bytes() == before and not events


def test_structural_constraints_and_presets():
    for preset in json.loads((FIXTURES / 'design_presets.json').read_text(encoding='utf-8')):
        assert models.ThemePreset.model_validate(preset).model_dump(mode='json') == preset
    design = fixture_model('design', models.Design).model_dump()
    for patch in ({'palette': ['#123456']}, {'accent': 'blue'}, {'density': 'tiny'}, {'revision': 0}, {'unknown': 1}):
        with pytest.raises(ValidationError):
            models.Design.model_validate({**design, **patch})
    context = fixture_model('context', models.Context).model_dump()
    context['kpis'][0]['measure'] = None
    with pytest.raises(ValidationError, match='Exactly one'):
        models.Context.model_validate(context)
    with pytest.raises(ValidationError, match='both'):
        models.ViewSources(base='a', joins=[{'source_id': 'b', 'on': [{'left': 'id', 'right': 'id'}]}], union=['c'])


@pytest.mark.parametrize('text', ['', '---\ntype: Context\n', '---\n[]\n---\n', '---\ntype: ""\n---\n'])
def test_invalid_frontmatter(tmp_path, text):
    path = tmp_path / 'context.md'
    path.write_text(text, encoding='utf-8')
    with pytest.raises(ValueError):
        okf.read_artifact(path)
