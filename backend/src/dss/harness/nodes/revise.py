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
from dss.harness.nodes import designer
from dss.harness.nodes.render import artifacts
from dss.render import background, design_page
from dss.spec.models import DashboardSpec
from dss.spec.patch import apply_scoped, items, pages, PatchError
from dss.spec.validate import allowed_types, catalog, high_questions, validate_spec
from dss.spec import requirements as req
from dss.spec.capabilities import Checker, load_registry


# Why a page redesign failed when its answer left no check errors (designer.Fallback.reason).
FAILURES = {'model': 'the design model is unavailable; check Settings',
            'over_budget': 'the page is too large for the design model',
            'reference': 'the reference images are missing or damaged; upload them again',
            'feasibility': 'the candidate needs a current ready feasibility assessment',
            'timeout': 'the page design exceeded its time budget',
            'error': 'the design call failed'}


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


def design_ids(document):
    """The `p<n>_design` decoration ids of the designed pages: the reviser never sees comments on
    them (the designer revises the page)."""
    return {d['id'] for page in document['pages'] if page.get('design') for d in page['decorations'] if d['kind'] == 'design'}


def expand(batch, seen, total):
    """The reviser's changes for the comments it saw (batch positions `seen`) at their batch
    positions; a comment on a page design gets an empty patch."""
    if [c.comment_index for c in batch.changes] != list(range(len(seen))):
        raise PatchError('Return exactly one change per comment, in order')
    changes = [Change(comment_index=i) for i in range(total)]
    for change in batch.changes:
        changes[seen[change.comment_index]] = change.model_copy(update={'comment_index': seen[change.comment_index]})
    return Revision(changes=changes)


def _route(document, target, patch):
    """(kept operations, redesign) for a comment on a designed page (architecture.md#Designed pages):
    a comment on the page design, geometry (grid or box: dropped, the designer re-lays the page),
    a removal and a heading (label) change redesign the page; data operations are kept as is."""
    redesign = target in design_ids(document)
    kept = []
    for op in patch:
        suffixes = [op[key].split('/')[5:] for key in ('path', 'from') if isinstance(op.get(key), str)]
        if any(s[:1] in (['grid'], ['box']) for s in suffixes):
            redesign = True
            continue
        if not suffixes[0] or any(s[:1] == ['label'] for s in suffixes):  # removal, whole-item replace, heading
            redesign = True
        kept.append(op)
    return kept, redesign


def _too_small(document, item):
    """A component whose (new) type's minimum no longer fits its measured slot."""
    if not item.get('box') or item.get('type') not in catalog():
        return False
    w, h = design_page.minimum(item['type'], document['canvas']['width'])
    return item['box']['w'] < w or item['box']['h'] < h


def redesigns(records):
    """{page index: [comment, ...]} the designer regenerates, from revised()'s records."""
    pages = {}
    for record in records:
        if 'redesigned_page' in record:
            pages.setdefault(record['redesigned_page'], []).append(record['comment'])
    return pages


def revised(document, comments, batch, allowed):
    """Apply the batch to a copy. On a designed page, a record's `redesigned_page` marks a comment
    whose page the designer regenerates (redesigns); box errors on those pages wait for the new
    measurement."""
    if [c.comment_index for c in batch.changes] != list(range(len(comments))):
        raise PatchError('Return exactly one change per comment, in order')
    candidate = deepcopy(document)
    records = []
    redesign = set()
    for comment, change in zip(comments, batch.changes):
        patch = [op.model_dump(by_alias=True, exclude_unset=True) for op in change.patch]
        if change.unsupported_type:
            raise PatchError('The complete batch must fulfill confirmed intent')
        page = pages(candidate).get(comment['component_id'])
        design = page is not None and bool(candidate['pages'][page].get('design'))
        again = False
        if design:
            patch, again = _route(candidate, comment['component_id'], patch)
        updated = apply_scoped(candidate, patch, comment['component_id'])
        # A type patch itself can express the unsupported request. Never persist it.
        target = items(updated).get(comment['component_id'])
        requested = target.get('type') if target else None
        if requested and requested not in allowed:
            raise PatchError('The complete batch must use supported types')
        if design and target is not None and _too_small(updated, target):
            again = True
        record = {'comment': comment, 'change': patch or ('page redesign' if again else 'no change needed')}
        if target is None:
            record['removed'] = comment['component_id']
        if again:
            redesign.add(page + 1)
            record['redesigned_page'] = page + 1
        candidate = updated
        records.append(record)
    errors = [e for e in validate_spec(candidate, allowed=allowed) if not any(
        e['path'].startswith(f'pages.{n - 1}.components.') and '.box' in e['path'] for n in redesign)]
    if errors:
        raise PatchError(json.dumps(errors))
    return candidate, records


def context_document(document):
    """The document the reviser reads. A designed page keeps each component's code-layout cell as
    its fallback, which may reach below the measured page: give the neighbour lookup room for it.
    The design HTML itself never enters the reviser's context."""
    if not any(page.get('design') for page in document['pages']):
        return document
    document = deepcopy(document)
    grid = document['grid']
    for page in document['pages']:
        if page.pop('design', None):
            cells = [i['grid'] for group in ('components', 'decorations') for i in page[group]]
            bottom = max((grid['margin'] + (c['row'] - 1 + c['h']) * grid['row_height'] for c in cells), default=0)
            page['height'] = max(page['height'], bottom)
    return document


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
            updates.update({folder / name: (staging / name).read_bytes() for name in ('prototype.html', *background.names(spec), 'aggregate-cache.json')})
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
    # Comments on a page design go to the designer only; the reviser patches the others.
    seen = [i for i, c in enumerate(comments) if c['component_id'] not in design_ids(original)]
    state = {'raw':'', 'errors':'', 'repairs':0, 'failure':None, 'reply':'Revision did not finish.', 'skip':not seen}

    def repair():
        if not state['errors']:
            return ''
        return '\nPrevious output (untrusted):\n' + state['raw'] + '\nValidation diagnostics:\n' + state['errors'] + '\nReturn the complete repaired revision batch.'

    async def instruction_provider(context_object):
        # Extraction precedes this node; assemble mandatory intent only afterwards.
        return 'Revise the complete comment batch using the confirmed requirements.'

    async def before_model(callback_context, llm_request):
        nonlocal context
        if not state['repairs']:
            state['snapshot'], state['ledger'], state['checker'] = req.inputs(harness.db, build_id, folder), req.load(folder), Checker(load_registry())
        trace.span('revise_repair' if state['repairs'] else 'revise')
        if state['skip']:
            # Every comment is on a page design: no patch to ask for.
            trace.spans[-1]['skipped'] = 'design_comments'
            return LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Design comments only.')]))
        context = check_reply(revise_context(context_document(original), [comments[i] for i in seen], allowed, config,
                                             folder=folder), (secret,))
        llm_request.config.response_mime_type = 'application/json'
        llm_request.config.response_json_schema = response_schema()
        if model.model.startswith(('gemini-3', 'gemini-4')):
            # Live 20.5: default thinking on a move comment overran the 30 s worker deadline.
            llm_request.config.thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
        llm_request.contents = [types.Content(role='user', parts=[types.Part(text='Return the comment patches in order.')])]
        await fit_request(context, llm_request, model, trace.spans[-1], extra=repair())

    async def after_model(callback_context, llm_response):
        if state['skip']:
            return llm_response  # ADK also passes before_model's short-circuit response here
        if llm_response.error_code:
            return LlmResponse(error_code='llm_unavailable', error_message='Revision model failed')
        raw = ''.join(p.text for p in (llm_response.content.parts or []) if p.text and not p.thought) if llm_response.content else ''
        try:
            state['raw'] = check_reply(raw, (secret,))
        except RunError:
            return LlmResponse(error_code='llm_unavailable', error_message='Revision model returned unsafe output')
        return LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Revision received for validation.')]),
            usage_metadata=llm_response.usage_metadata)

    def patched():
        """The patch phase: the reviser's batch applied and validated. Requirements that only a
        redesigned page's design.html can prove wait for it; box errors there wait for the new
        measurement (revised)."""
        if seen:
            batch = expand(Revision.model_validate_json(state['raw']), seen, len(comments))
        else:
            batch = Revision(changes=[Change(comment_index=i) for i in range(len(comments))])
        candidate, records = revised(original, comments, batch, allowed)
        redesign = redesigns(records)
        errors = [e for e in validate_spec(candidate, allowed=allowed, high_priority=questions) if not any(
            e['path'].startswith(f'pages.{n - 1}.components.') and '.box' in e['path'] for n in redesign)]
        if errors:
            raise PatchError(json.dumps(errors))
        candidate = DashboardSpec.model_validate(candidate).model_dump()
        # Coverage sees the version this candidate publishes as (validate sets it again after a redesign).
        candidate['spec_version'] = original['spec_version'] + int(candidate != original or migrating)
        proposed = deepcopy(state['snapshot'])
        proposed['spec'] = candidate
        waiting = {f'p{n}_design' for n in redesign}
        rows = {'requirements.' + r.id for r in state['ledger'].requirements if r.component_ids and set(r.component_ids) <= waiting}
        errors = [e for e in req.coverage_errors(proposed, state['ledger'], state['checker']) if e['path'] not in rows]
        if errors:
            raise PatchError(json.dumps(errors))
        return candidate, records, redesign

    async def redesigned(candidate, redesign):
        """Each page in `redesign` designed again (one designer run per page), then the whole spec
        and every requirement checked; a RunError leaves the published version unchanged."""
        secrets = (secret, *(s.get_secret_value() for s in (config.access_code, config.agent_token)))
        reference = designer.reference_design(
            folder, {**state['snapshot'], 'spec': candidate}, state['ledger'], state['checker'], harness.models)
        spec, failed = await designer.regenerate(
            DashboardSpec.model_validate(candidate), redesign,
            payload.get('_designer') or (lambda: harness.models.llm_for('designer')), trace, secrets=secrets, reference=reference,
            report=lambda totals: harness.emit(build_id, run_id, 'run.usage', {'run_id': run_id, 'node': 'revise', **totals}))
        if failed:
            if reference is not None:
                index = min(failed)
                designer.reference_failed(index, failed[index], trace)
            reasons = []
            for n, result in sorted(failed.items()):
                found = [e['message'] for e in result.errors[:3]] or [FAILURES.get(result.reason, FAILURES['error'])]
                reasons.append(f'page {n}: ' + '; '.join(found))
            raise RunError('invalid_request', check_reply('The page design could not be revised, so nothing changed and the '
                           'comments stay pending (' + ' | '.join(reasons) + ')', (secret,)), 422,
                           {'errors': [dict(e, page=n) for n, result in sorted(failed.items())
                                       for e in result.errors[:designer.MAX_ERRORS]]})
        candidate = spec.model_dump()
        proposed = deepcopy(state['snapshot'])
        proposed['spec'] = candidate
        errors = validate_spec(spec, allowed=allowed, high_priority=questions) or req.coverage_errors(
            proposed, state['ledger'], state['checker'])
        if errors:
            raise RunError('invalid_request', 'The revised page design does not fulfill the requirements, so nothing '
                           'changed and the comments stay pending', 422, {'errors': errors[:20]})
        return candidate

    async def validate(node_input):
        trace.span('validate_revision')
        try:
            candidate, records, redesign = patched()
        except (ValueError, TypeError, KeyError, AttributeError):
            # Keep repair diagnostics free of pydantic inputs and provider text.
            state['errors'] = 'Patch rejected: fulfill every active requirement and confirmed decision; preserve scope/ids, move only collision neighbours, use valid field bindings, sizes and a non-overlapping layout.'
            if not state['repairs']:
                state['repairs'] = 1
                return Event(actions=EventActions(route='repair'))
            state['failure'] = RunError('invalid_request', 'Revision patch was rejected after one repair', 422)
            return Event(actions=EventActions(route='complete'))
        if redesign:
            # After the patch is final, so a reviser repair never designs a page twice.
            try:
                candidate = await redesigned(candidate, redesign)
            except RunError as exc:
                state['failure'] = exc
                return Event(actions=EventActions(route='complete'))
        changed = candidate != original or migrating
        candidate['spec_version'] = original['spec_version'] + int(changed)
        trace.span('render')
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
