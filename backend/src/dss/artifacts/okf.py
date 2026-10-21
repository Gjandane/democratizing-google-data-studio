"""Code-owned OKF rendering and atomic persistence for staged artifacts."""
from collections.abc import Awaitable, Callable
import os
from pathlib import Path
import tempfile

import yaml

from dss.artifacts.models import Artifact, Blueprint, Context, Design, Outline

KINDS = {Context: ('context', 'Business and Data Context'),
         Outline: ('outline', 'Dashboard Outline'),
         Design: ('design', 'Design Preferences'),
         Blueprint: ('blueprint', 'Technical Blueprint')}


def frontmatter(path):
    """Parse only the frontmatter; the human-readable body is never authoritative."""
    with Path(path).open(encoding='utf-8') as handle:
        if handle.readline().rstrip('\r\n') != '---':
            raise ValueError('Missing OKF frontmatter')
        lines = []
        for line in handle:
            if line.rstrip('\r\n') == '---':
                metadata = yaml.safe_load(''.join(lines))
                if (not isinstance(metadata, dict) or not isinstance(metadata.get('type'), str)
                        or not metadata['type'].strip()):
                    raise ValueError('Non-empty OKF type required')
                return metadata
            lines.append(line)
    raise ValueError('Unterminated OKF frontmatter')


def read_artifact(path, model=None) -> Artifact:
    metadata = frontmatter(path)
    inferred = next((cls for cls, (_, kind) in KINDS.items() if kind == metadata['type']), None)
    if inferred is None or (model is not None and model is not inferred):
        raise ValueError('Unexpected artifact type')
    artifact = inferred.model_validate(metadata['data'])
    if metadata['revision'] != artifact.revision:
        raise ValueError('Artifact revision disagrees with frontmatter')
    return artifact


def cell(value):
    return str(value).replace('|', '\\|').replace('\r', ' ').replace('\n', ' ')


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join('---' for _ in headers) + ' |',
                      *('| ' + ' | '.join(cell(v) for v in row) + ' |' for row in rows)])


def render(artifact):
    _, kind = KINDS[type(artifact)]
    title = getattr(artifact, 'title', kind)
    body = [f'# {cell(title)}']
    if isinstance(artifact, Context):
        body += [artifact.goal, f'Audience: {artifact.audience or "Unspecified"}',
                 table(['Dataset', 'Summary'], ((d.source_id, d.summary) for d in artifact.datasets)),
                 '## KPIs', table(['KPI', 'Definition', 'Unit'],
                    ((k.name, f'{k.measure.agg}({k.measure.field})' if k.measure else
                      f'{k.ratio.numerator} / {k.ratio.denominator}', k.unit or '') for k in artifact.kpis)),
                 '## Thresholds', table(['Name', 'Rule', 'Description'],
                    ((t.name, f'{t.field} {t.operator} {t.value:g}', t.description) for t in artifact.thresholds)),
                 '## Glossary', table(['Term', 'Definition'], ((t.term, t.definition) for t in artifact.glossary))]
    elif isinstance(artifact, Outline):
        for section in artifact.sections:
            body += [f'## {cell(section.title)}', section.purpose,
                     *[f'- [{"x" if q.selected else " "}] {cell(q.id)}: {cell(q.text)} — {cell(q.rationale)}'
                       for q in section.questions]]
    elif isinstance(artifact, Design):
        body += [artifact.subtitle or '', f'Font: {artifact.font_family}',
                 f'Pages: {artifact.page_structure}; density: {artifact.density}',
                 '## Theme swatches', table(['Role', 'Color'],
                    [(key, getattr(artifact, key)) for key in ('background', 'surface', 'text', 'accent')]
                    + [(f'Series {i}', color) for i, color in enumerate(artifact.palette, 1)])]
    else:
        body += [table(['Question', 'Section / page', 'Chart', 'Fields', 'Status', 'Note'],
                    ((r.question_id or 'Supporting control', f'{r.section_id} / {r.page}', r.component.type,
                      ', '.join([*r.component.dimensions, *[f'{m.agg}({m.field})' for m in r.component.metrics],
                                 *[f for f in (r.component.date_dimension, r.component.breakdown) if f]]),
                      r.status, r.note) for r in artifact.rows))]
    if isinstance(artifact, (Context, Blueprint)):
        body += ['## Derived fields', table(['Field', 'Type', 'Expression'],
                    ((f.name, f.type, f.expression) for f in artifact.derived_fields))]
    if getattr(artifact, 'issues', None):
        body += ['## Issues', table(['Path', 'Message'], ((i.path, i.message) for i in artifact.issues))]
    metadata = {'type': kind, 'title': title, 'revision': artifact.revision, 'data': artifact.model_dump(mode='json')}
    return '---\n' + yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True) + '---\n\n' + '\n\n'.join(body) + '\n'


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique sibling file: same filesystem for replace, no shared .tmp collision.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=path.parent, prefix=f'.{path.name}.', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def write_artifact(path, artifact: Artifact, *, emit: Callable[[str, dict], Awaitable[None]]):
    """Persist under the caller's build lock, then emit the two contract events.

    ``emit`` is a build/run-bound harness.emit callback. No event is emitted on
    failed writes. Stage state/revisions are owned by the caller, not this IO layer.
    """
    path = Path(path)
    # Revalidate mutated models before touching the existing file.
    artifact = type(artifact).model_validate(artifact.model_dump(mode='json'))
    name, _ = KINDS[type(artifact)]
    if path.name != f'{name}.md':
        raise ValueError('Artifact filename must match its type')
    atomic_write(path, render(artifact))
    docs = []
    for file in sorted(path.parent.glob('*.md')):
        if file.name not in ('index.md', 'log.md'):
            meta = frontmatter(file)
            docs.append({'path': file.name, 'title': meta.get('title', file.stem), 'type': meta['type']})
    index = path.parent / 'index.md'
    if index.exists():
        text = index.read_text(encoding='utf-8')
        if f']({path.name})' not in text:
            atomic_write(index, text.rstrip() + f'\n- [{cell(getattr(artifact, "title", KINDS[type(artifact)][1]))}]({path.name})\n')
    else:
        atomic_write(index, '---\ntype: Index\ntitle: Build documents\n---\n\n# Build documents\n\n' +
                     ''.join(f'- [{cell(d["title"])}]({d["path"]})\n' for d in docs))
    log = path.parent / 'log.md'
    text = log.read_text(encoding='utf-8') if log.exists() else '---\ntype: Log\ntitle: Build log\n---\n\n# Build log\n'
    atomic_write(log, text.rstrip() + f'\n- {name}: revision {artifact.revision}\n')
    await emit('artifact.updated', {'artifact': name, 'revision': artifact.revision})
    await emit('docs.updated', {'docs': docs})
