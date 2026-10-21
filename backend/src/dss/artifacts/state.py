"""Code-owned stage transitions. Call mutations inside ``action``'s build reservation.

Transitions never touch published files: an edit invalidates downstream artifacts,
while the previous spec, view and prototype remain usable for display.
"""
from contextlib import contextmanager
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

from dss.db import now
from dss.harness.guardrails import RunError

Stage = Literal['connect', 'context', 'outline', 'design', 'blueprint', 'prototype', 'build', 'done']
ArtifactState = Literal['missing', 'draft', 'confirmed', 'stale']
ARTIFACTS = ('context', 'outline', 'design', 'blueprint')
STAGES = ('connect', *ARTIFACTS, 'prototype', 'build', 'done')


class ArtifactStates(BaseModel):
    model_config = ConfigDict(extra='forbid')
    context: ArtifactState = 'missing'
    outline: ArtifactState = 'missing'
    design: ArtifactState = 'missing'
    blueprint: ArtifactState = 'missing'


def stage(build):
    return 'context' if build['stage'] in ('interview', 'plan') else build['stage']


def states(build):
    return ArtifactStates.model_validate_json(build.get('artifacts_json') or '{}').model_dump()


def wrong_stage(build):
    return RunError('wrong_stage', 'This action is unavailable in the current stage', 409, {'stage': stage(build)})


@contextmanager
def action(state, build_id, allowed=STAGES):
    """Reserve before any await or artifact write; release on every exit path."""
    with state.db.connect() as conn:
        row = conn.execute('SELECT * FROM builds WHERE id=?', (build_id,)).fetchone()
    if row is None:
        raise RunError('build_not_found', 'Build not found', 404)
    build = dict(row)
    if stage(build) not in allowed or build_id in state.harness.active_builds:
        raise wrong_stage(build)
    state.harness.active_builds.add(build_id)
    try:
        yield build
    finally:
        state.harness.active_builds.discard(build_id)


def require_edit(build, artifact):
    if artifact not in ARTIFACTS:
        raise ValueError('Unknown artifact')
    if stage(build) not in STAGES[STAGES.index(artifact):STAGES.index('build')]:
        raise wrong_stage(build)


def edited(build, artifact):
    require_edit(build, artifact)
    values = states(build)
    values[artifact] = 'draft'
    for downstream in ARTIFACTS[ARTIFACTS.index(artifact) + 1:]:
        values[downstream] = 'stale'
    return {'stage': artifact, 'artifacts_json': json.dumps(values)}


def confirmed(build, artifact, issues=()):
    if artifact not in ARTIFACTS:
        raise ValueError('Unknown artifact')
    if stage(build) != artifact:
        raise wrong_stage(build)
    values = states(build)
    problems = list(issues)
    if values[artifact] == 'missing':
        problems.append({'path': '', 'message': 'Draft this artifact before confirming it'})
    if any(values[name] != 'confirmed' for name in ARTIFACTS[:ARTIFACTS.index(artifact)]):
        raise wrong_stage(build)
    if problems:
        raise RunError('artifact_invalid', 'Resolve artifact issues before confirming', 409, {'issues': problems})
    values[artifact] = 'confirmed'
    # Blueprint acceptance renders first; only successful publication reaches prototype.
    next_stage = STAGES[STAGES.index(artifact) + 1] if artifact != 'blueprint' else 'blueprint'
    return {'stage': next_stage, 'artifacts_json': json.dumps(values)}


def save(db, build_id, transition):
    """Persist a computed transition under the caller's per-build reservation."""
    with db.connect() as conn:
        conn.execute('UPDATE builds SET stage=?,artifacts_json=?,updated_at=? WHERE id=?',
                     (transition['stage'], transition['artifacts_json'], now(), build_id))


def require_confirmed(build, folder):
    values = states(build)
    legacy = all(value == 'missing' for value in values.values()) and (folder / 'spec.json').is_file()
    if not legacy and any(value != 'confirmed' for value in values.values()):
        raise wrong_stage(build)
