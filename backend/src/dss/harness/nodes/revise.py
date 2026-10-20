"""Bounded revision branch: scoped patches, one repair, staged artifacts and decisions."""
import asyncio
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from typing import Any, Literal

from google.adk import Event
from google.adk.agents import LlmAgent
from google.adk.events.event_actions import EventActions
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from dss.db import now
from dss.harness.context import fit_request, revise_context
from dss.harness.guardrails import RunError, check_reply
from dss.harness.nodes.render import artifacts
from dss.spec.models import DashboardSpec
from dss.spec.patch import apply_scoped, items, PatchError
from dss.spec.validate import allowed_types, catalog, high_questions, validate_spec
from dss.spec import requirements as req
from dss.spec.capabilities import Checker, load_registry


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)


class Operation(Strict):
    op: Literal['add', 'remove', 'replace', 'move', 'copy', 'test']
    path: str = Field(max_length=500)
    value: Any = None
    from_path: str | None = Field(default=None, alias='from', max_length=500)


class Change(Strict):
    comment_index: int = Field(ge=0, le=19)
    patch: list[Operation] = Field(default_factory=list, max_length=40)
    unsupported_type: str | None = Field(default=None, max_length=100)


class Revision(Strict):
    changes: list[Change] = Field(min_length=1, max_length=20)


def response_schema():
    schema = Revision.model_json_schema(by_alias=True)
    # Gemini rejects an untyped Any property. RFC patch values may be any scalar,
    # object or array; spell those JSON types out at the provider boundary.
    values = [{'type':kind} for kind in ('string','number','boolean','null')]
    values.append({'type':'object', 'additionalProperties':True})
    schema['$defs']['Operation']['properties']['value'] = {'anyOf': values + [
        {'type':'array','items':{'anyOf':values}}]}
    # The worker rejects the nested 20-change / 40-operation maxItems bounds
    # with INVALID_ARGUMENT. Keep those limits in Pydantic at validation time.
    def provider_limits(value):
        if isinstance(value, dict):
            value.pop('maxItems', None)
            for child in value.values():
                provider_limits(child)
        elif isinstance(value, list):
            for child in value:
                provider_limits(child)
    provider_limits(schema)
    return schema


def revised(document, comments, batch, allowed):
    if [c.comment_index for c in batch.changes] != list(range(len(comments))):
        raise PatchError('Return exactly one change per comment, in order')
    candidate = deepcopy(document)
    records = []
    for comment, change in zip(comments, batch.changes):
        patch = [op.model_dump(by_alias=True, exclude_unset=True) for op in change.patch]
        if change.unsupported_type:
            raise PatchError('The complete batch must fulfill confirmed intent')
        updated = apply_scoped(candidate, patch, comment['component_id'])
        # A type patch itself can express the unsupported request. Never persist it.
        target = items(updated).get(comment['component_id'])
        requested = target.get('type') if target else None
        if requested and requested not in allowed:
            raise PatchError('The complete batch must use supported types')
        candidate = updated
        records.append({'comment': comment, 'change': patch or 'no change needed'})
    errors = validate_spec(candidate, allowed=allowed)
    if errors:
        raise PatchError(json.dumps(errors))
    return candidate, records


def persist(harness, build_id, version, folder, candidate, records, changed, service, questions, snapshot, ledger, checker):
    """Render into a sibling staging folder; retain the published version on failure."""
    from dss.harness.nodes.intake import write_doc
    spec = DashboardSpec.model_validate(candidate)
    errors = validate_spec(spec, allowed=allowed_types() & catalog().keys(), high_priority=questions)
    if errors:
        raise PatchError(json.dumps(errors))
    folder.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.revise-', dir=folder) as temporary:
        staging = Path(temporary)
        updates = {}
        if changed:
            # Reuse version-local aggregate cache and only the referenced local images.
            cache = folder / 'aggregate-cache.json'
            if cache.exists():
                shutil.copyfile(cache, staging / cache.name)
            assets = [c.image_path for p in spec.pages for c in p.components if c.image_path]
            assets += [d.style.get('image_path') for p in spec.pages for d in p.decorations if d.kind == 'logo' and d.style.get('image_path')]
            for name in assets:
                source = (folder / name).resolve()
                if not source.is_relative_to(folder.resolve()):
                    raise ValueError('Image must stay inside version folder')
                target = staging / source.relative_to(folder.resolve())
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            artifacts(spec, service(), staging)
            updates.update({folder / name: (staging / name).read_bytes() for name in ('prototype.html','background_p1.png','aggregate-cache.json')})
            updates[folder / 'spec.json'] = spec.model_dump_json(indent=2).encode('utf-8')
        decisions = folder / 'docs/decisions.md'
        text = decisions.read_text(encoding='utf-8') if decisions.exists() else '---\ntype: Design Decisions\ntitle: Design decisions\n---\n\n# Design decisions\n'
        for record in records:
            text += f'\n- {now()} (spec {spec.spec_version}): ' + json.dumps(record, ensure_ascii=False) + '\n'
        updates[decisions] = text.encode('utf-8')
        # Baseline plans have these already; fixed-spec samples may lack build docs.
        for name, kind, body in [('index.md','Index','- [Design decisions](decisions.md)'), ('log.md','Log','# Build log')]:
            destination = folder / 'docs' / name
            if not destination.exists():
                write_doc(staging / name, {'type':kind}, body)
                updates[destination] = (staging / name).read_bytes()
        # Publish proof and the changed artifacts in the same rollback transaction.
        for name in ('index.md', 'log.md'):
            source = folder / 'docs' / name
            (staging / 'docs').mkdir(exist_ok=True)
            if source.exists():
                shutil.copyfile(source, staging / 'docs' / name)
            elif folder / 'docs' / name in updates:
                (staging / 'docs' / name).write_bytes(updates[folder / 'docs' / name])
        proposed = deepcopy(snapshot)
        proposed['spec'] = candidate
        proposed['definitions']['decisions.md'] = text
        verified = req.revalidate_decisions(proposed, ledger, checker)
        bindings = {}
        errors = req.coverage_errors(proposed, verified, checker, bindings=bindings)
        if errors:
            raise PatchError('Candidate does not fulfill confirmed intent')
        verified.pending_comments = None
        verified.verification = req.verification(proposed, verified, checker)
        for rid, ids in bindings.items():
            verified.verification[rid].append({'fulfilled_by': ids})
        req.save(staging, verified, req.evaluate(proposed, verified, checker))
        for name in ('requirements.json', 'docs/feasibility.md', 'docs/index.md', 'docs/log.md'):
            updates[folder / name] = (staging / name).read_bytes()
        if (req.digest(req.inputs(harness.db, build_id, folder)) != req.digest(snapshot)
                or Checker(load_registry()).digest() != checker.digest()):
            raise RunError('feasibility_stale', 'Inputs changed during revision; check again', 409)
        backups = {path: path.read_bytes() if path.exists() else None for path in updates}
        written = []
        try:
            with harness.db.connect() as conn:
                for i, (path, content) in enumerate(updates.items()):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    staged = staging / f'publish-{i}'
                    staged.write_bytes(content)
                    staged.replace(path)
                    written.append(path)
                conn.execute("UPDATE versions SET spec_version=?,status='draft' WHERE build_id=? AND n=?", (spec.spec_version, build_id, version))
                conn.execute('UPDATE builds SET updated_at=? WHERE id=?', (now(), build_id))
        except Exception:
            for i, path in enumerate(written):
                if backups[path] is not None:
                    restored = staging / f'restore-{i}'
                    restored.write_bytes(backups[path])
                    restored.replace(path)
                else:
                    # Preserve files without exposing a partial publication.
                    path.replace(staging / f'unpublished-{i}')
            raise


def make_branch(harness, build_id, run_id, payload, model, trace, model_error):
    config, comments = payload['config'], payload['comments']
    secret = config.google_api_key.get_secret_value()
    with harness.db.connect() as conn:
        version = conn.execute('SELECT current_version FROM builds WHERE id=?', (build_id,)).fetchone()[0]
    folder = config.data_dir / 'builds' / build_id / f'v{version}'
    from dss.api.prototype import read_spec
    original = read_spec(folder, db=harness.db, build_id=build_id).model_dump()
    migrating = original['datasource']['synthetic'] and original != json.loads((folder / 'spec.json').read_text(encoding='utf-8'))
    allowed = allowed_types() & catalog().keys()
    context = None
    questions_file = folder / 'docs/questions.md'
    questions = high_questions(questions_file.read_text(encoding='utf-8')) if questions_file.exists() else []
    state = {'raw':'', 'errors':'', 'repairs':0, 'failure':None, 'reply':'Revision did not finish.'}

    def repair():
        if not state['errors']:
            return ''
        return '\nPrevious output (untrusted):\n' + state['raw'] + '\nValidation diagnostics:\n' + state['errors'] + '\nReturn the complete repaired revision batch.'

    async def instruction_provider(context_object):
        # Extraction precedes this node; assemble mandatory intent only afterwards.
        return 'Revise the complete comment batch using the confirmed requirements.'

    async def before_model(callback_context, llm_request):
        nonlocal context
        context = check_reply(revise_context(original, comments, allowed, config, folder=folder), (secret,))
        if not state['repairs']:
            state['snapshot'], state['ledger'], state['checker'] = req.inputs(harness.db, build_id, folder), req.load(folder), Checker(load_registry())
        trace.span('revise_repair' if state['repairs'] else 'revise')
        llm_request.config.response_mime_type = 'application/json'
        llm_request.config.response_json_schema = response_schema()
        llm_request.contents = [types.Content(role='user', parts=[types.Part(text='Return the comment patches in order.')])]
        await fit_request(context, llm_request, model, trace.spans[-1], extra=repair())

    async def after_model(callback_context, llm_response):
        if llm_response.error_code:
            return LlmResponse(error_code='llm_unavailable', error_message='Revision model failed')
        raw = ''.join(p.text for p in (llm_response.content.parts or []) if p.text and not p.thought) if llm_response.content else ''
        try:
            state['raw'] = check_reply(raw, (secret,))
        except RunError:
            return LlmResponse(error_code='llm_unavailable', error_message='Revision model returned unsafe output')
        return LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Revision received for validation.')]),
            usage_metadata=llm_response.usage_metadata)

    async def validate(node_input):
        trace.span('validate_revision')
        try:
            candidate, records = revised(original, comments, Revision.model_validate_json(state['raw']), allowed)
            errors = validate_spec(candidate, allowed=allowed, high_priority=questions)
            if errors:
                raise PatchError(json.dumps(errors))
            candidate = DashboardSpec.model_validate(candidate).model_dump()
            changed = candidate != original or migrating
            candidate['spec_version'] = original['spec_version'] + int(changed)
            proposed = deepcopy(state['snapshot'])
            proposed['spec'] = candidate
            errors = req.coverage_errors(proposed, state['ledger'], state['checker'])
            if errors:
                raise PatchError(json.dumps(errors))
        except (ValueError, TypeError, KeyError, AttributeError):
            # Keep repair diagnostics free of pydantic inputs and provider text.
            state['errors'] = 'Patch rejected: fulfill every active requirement and confirmed decision; preserve scope/ids, move only collision neighbours, use valid field bindings, sizes and a non-overlapping layout.'
            if not state['repairs']:
                state['repairs'] = 1
                return Event(actions=EventActions(route='repair'))
            state['failure'] = RunError('invalid_request', 'Revision patch was rejected after one repair', 422)
            return Event(actions=EventActions(route='complete'))
        try:
            from dss.spec.publication import build_lock
            async with build_lock(harness.db, build_id):
                worker = asyncio.create_task(asyncio.to_thread(persist, harness, build_id, version, folder, candidate, records, changed, lambda:payload['factory'](config), questions, state['snapshot'], state['ledger'], state['checker']))
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    try:
                        await asyncio.shield(worker)
                    except Exception:
                        pass
                    raise
        except RunError as exc:
            state['failure'] = exc
            return Event(actions=EventActions(route='complete'))
        except Exception:
            state['failure'] = RunError('invalid_source', 'Revision could not be rendered and saved; previous prototype retained', 422)
            return Event(actions=EventActions(route='complete'))
        notes = ['Prototype updated.' if changed else 'No change needed.']
        if any(n > 1 for n in Counter(c['component_id'] for c in comments).values()):
            notes.append('Comments on the same item were applied in order; the last change to the same property wins.')
        state['reply'] = ' '.join(notes)
        if changed:
            await harness.emit(build_id, run_id, 'prototype.updated', {'spec_version':candidate['spec_version']})
        from dss.api.builds import build_response
        await harness.emit(build_id, run_id, 'docs.updated', {'docs':build_response(harness.db,config,build_id)['docs']})
        return Event(actions=EventActions(route='complete'))

    async def complete(node_input):
        return state['reply']

    def agent(name):
        return LlmAgent(name=name, model=model, mode='single_turn', instruction=instruction_provider,
            before_model_callback=before_model, after_model_callback=after_model, on_model_error_callback=model_error)
    return agent('revise'), agent('revise_repair'), validate, complete, state
