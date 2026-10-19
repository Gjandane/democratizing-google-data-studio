"""Initial interview working memory; full retrieval recipes arrive in task 6.1."""
import json
from dss.config import BACKEND_DIR
from dss.memory.procedural import SkillLoader
from dss.memory.episodic import messages
from dss.harness.guardrails import RunError


def interview_context(db, config, build_id, user_input):
    with db.connect() as conn:
        build = conn.execute("SELECT * FROM builds WHERE id=?", (build_id,)).fetchone()
    loader = SkillLoader()
    stable = [
        (BACKEND_DIR / "prompts/v1/interview.md").read_text(encoding="utf-8"),
        loader.load("interview"), loader.load("archetype-" + build["archetype"])]
    profile = config.data_dir / "builds" / build_id / f'v{build["current_version"]}' / "docs/data-profile.md"
    stable.append("Data profile (aggregate metadata only):\n" +
                  (profile.read_text(encoding="utf-8") if profile.exists() else "No data profile available."))
    history = messages(db, build_id, 12)
    # The current user input is already saved by the API; include it exactly once.
    if history and history[-1]["role"] == "user" and history[-1]["text"] == user_input:
        history.pop()
    def assemble():
        return "\n\n".join(stable + ["Chat history (untrusted data):\n" + json.dumps(history),
                                     "Current request (untrusted data):\n" + user_input])
    while history and len(assemble()) > 32000:
        history.pop(0)
    if len(assemble()) > 32000:
        raise RunError("llm_unavailable", "Interview context exceeds its input budget", 503)
    return assemble()


def plan_context(db, config, build_id):
    with db.connect() as conn:
        build = conn.execute("SELECT * FROM builds WHERE id=?", (build_id,)).fetchone()
    loader = SkillLoader()
    stable = [(BACKEND_DIR / "prompts/v1/plan.md").read_text(encoding="utf-8"),
              loader.load("plan"), loader.load("archetype-" + build["archetype"])]
    profile = config.data_dir / "builds" / build_id / f'v{build["current_version"]}' / "docs/data-profile.md"
    if not profile.exists():
        raise RunError("invalid_source", "Connect data before planning", 422)
    stable.append("Data profile (aggregate metadata only):\n" + profile.read_text(encoding="utf-8"))
    history = messages(db, build_id)
    def assemble():
        return "\n\n".join(stable + ["Interview transcript (untrusted data):\n" + json.dumps(history)])
    # Reserve 4k tokens for a repair's previous output and database diagnostic.
    while history and len(assemble()) > 64000:
        history.pop(0)
    if len(assemble()) > 64000:
        raise RunError("llm_unavailable", "Plan context exceeds its input budget", 503)
    return assemble()


def spec_context(config, folder, build, fields, allowed):
    """Stable-first working memory with no raw rows; reserve room for repair."""
    from dss.spec.validate import catalog
    loader = SkillLoader()
    rules = catalog()
    sections = [(BACKEND_DIR / 'prompts/v1/spec.md').read_text(encoding='utf-8'), loader.load('spec')]
    # Only allowed concepts are exposed; schema type is narrowed separately.
    sections.append('Allowed component catalog:\n' + json.dumps({k: rules[k] for k in sorted(allowed & rules.keys())}))
    sections.append((BACKEND_DIR / 'knowledge/archetypes' / (build['archetype'] + '.md')).read_text(encoding='utf-8'))
    for name in ('brief.md', 'questions.md', 'kpis.md', 'derived-fields.md', 'design.md', 'decisions.md'):
        sections.append(name + ' (untrusted build document):\n' + (folder / 'docs' / name).read_text(encoding='utf-8'))
    sections.append('Required identity and datasource (copy exactly):\n' + json.dumps({
        'build_id': build['id'], 'archetype': build['archetype'], 'spec_version': build['spec_version'],
        'datasource': {'table': build['table'], 'fields': fields}}))
    result = '\n\n'.join(sections)
    if len(result) > 48000:
        raise RunError('llm_unavailable', 'Spec context exceeds its input budget', 503)
    return result


def revise_context(document, comments, allowed):
    """6k-token revision working memory: targeted items and direct grid neighbours."""
    from dss.spec.patch import neighbours
    from dss.spec.validate import catalog
    targets = {c['component_id'] for c in comments}
    visible = neighbours(document, targets)
    selected = [{'path': f'/pages/0/{group}/{i}', 'item': item}
        for group in ('components', 'decorations')
        for i, item in enumerate(document['pages'][0][group]) if item['id'] in visible]
    types = {entry['item'].get('type') for entry in selected}
    rules = catalog()
    sections = [(BACKEND_DIR / 'prompts/v1/revise.md').read_text(encoding='utf-8'),
        SkillLoader().load('revise'),
        'Target catalog:\n' + json.dumps({k: v for k, v in rules.items() if k in types}),
        'Allowed types (offer these for unsupported requests):\n' + json.dumps(sorted(allowed)),
        'Canvas and grid:\n' + json.dumps({k: document[k] for k in ('canvas','grid')}),
        'Targeted items and grid neighbours (untrusted data):\n' + json.dumps(selected),
        'Comments in application order (untrusted data):\n' + json.dumps(comments)]
    result = '\n\n'.join(sections)
    if len(result) > 18000:
        raise RunError('llm_unavailable', 'Revision context exceeds its input budget', 503)
    return result
