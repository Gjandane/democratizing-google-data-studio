from pathlib import Path
import pytest
from dss.config import BACKEND_DIR
from dss.memory.procedural import SkillLoader
from dss.memory.semantic import SemanticNavigator, parse_concept
from dss.spec.models import TYPES


def put(root, path, text):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding='utf-8')


def test_seed_bundle(tmp_path):
    root = BACKEND_DIR / 'knowledge'
    nav = SemanticNavigator(root, tmp_path)
    for file in root.rglob('*.md'):
        assert nav.read(file.relative_to(root).as_posix()).metadata['type']
    for folder in [root, *(p for p in root.rglob('*') if p.is_dir())]:
        assert (folder / 'index.md').is_file()
        assert (folder / 'log.md').is_file()
    catalog = nav.search(type='Chart Type')
    assert {c.metadata['component_type'] for c in catalog} == set(TYPES)
    assert {p.stem for p in (root/'catalog').glob('*.md')} == set(TYPES) | {'index', 'log'}
    for c in catalog:
        m = c.metadata
        for key in ('min_dimensions', 'max_dimensions', 'min_metrics', 'max_metrics', 'min_w', 'min_h'):
            assert type(m[key]) is int and m[key] >= 0
        assert type(m['requires_date_dimension']) is bool
        assert m['min_dimensions'] <= m['max_dimensions']
        assert m['min_metrics'] <= m['max_metrics']
        assert m['min_w'] > 0 and m['min_h'] > 0
    assert len(nav.list_folder()) == 3
    assert len(nav.list_folder('catalog')) == len(TYPES) == 14  # 24.1: area, fixed_size_list
    assert {c.metadata['archetype'] for c in nav.search(type='Dashboard Archetype')} == {'executive','storytelling','operational','analytical'}
    assert nav.search(text='headline')
    assert len(nav.search(type='Chart Type', tags=['catalog','pie'], text='PROPORTIONS')) == 1
    assert not nav.search(tags=['missing'])
    assert not nav.search(text='absent_search_term')


def test_runtime_and_index(tmp_path):
    seed, runtime = tmp_path/'seed', tmp_path/'runtime'
    put(seed, 'user/index.md', '---\ntype: Index\n---\n[Fact](fact.md)\n[Fact](fact.md)\n[External](https://example.com)')
    put(seed, 'user/fact.md', '---\ntype: Preference\ntags: [color]\n---\nBlue')
    nav = SemanticNavigator(seed, runtime)
    assert nav.list_folder('user')[0].text.endswith('Blue')
    put(runtime, 'user/fact.md', '---\ntype: Preference\ntags: [color]\n---\nGreen')
    assert len(nav.list_folder('user')) == 1
    assert nav.read('user/fact.md').text.endswith('Green')
    assert not nav.search(text='Blue')
    assert len(nav.search(type='Preference', tags=['color'])) == 1
    with pytest.raises(FileNotFoundError):
        nav.read('missing.md')
    with pytest.raises(ValueError):
        nav.read('../escape.md')
    with pytest.raises(ValueError):
        nav.read('C:/escape.md')
    put(runtime, 'user/index.md', '---\ntype: Index\n---\n[bad](../../escape.md)')
    with pytest.raises(ValueError):
        nav.list_folder('user')


@pytest.mark.parametrize('text', ['', 'hello', '---\ntype: x', '---\n- list\n---', '---\ntype: " "\n---', '---\ntype: 3\n---', '---\ntype: X\ntags: color\n---', '---\ntype: [\n---'])
def test_invalid_frontmatter(text):
    with pytest.raises(ValueError):
        parse_concept('bad.md', text)


def test_skill_loader(tmp_path):
    put(tmp_path, 'interview.md', '# Interview\nAsk about goals.\n')
    assert SkillLoader(tmp_path).load('interview') == '# Interview\nAsk about goals.\n'
    with pytest.raises(FileNotFoundError):
        SkillLoader(tmp_path).load('unknown')
    for name in ('../secret', '/secret', 'x.md', 'x\\y', ''):
        with pytest.raises(ValueError):
            SkillLoader(tmp_path).load(name)
