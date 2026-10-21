"""One-shot Outline drafts; code owns IDs, selections, normalization and feasibility."""
import json
import re

from google.adk.agents import LlmAgent
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field, ValidationError

from dss.artifacts import state as stages
from dss.artifacts.models import Model, Outline, OutlineQuestion, OutlineSection
from dss.artifacts.okf import atomic_write, read_artifact, write_artifact
from dss.harness.context import outline_context, fit_request, tokens
from dss.harness.guardrails import RunError, check_reply
from dss.harness.nodes import context as context_node
from dss.harness.nodes.style_extract import provider_schema
from dss.spec import references, requirements as req
from dss.spec.capabilities import Checker, load_registry

SCOPE_MESSAGE = 'Reduce the request scope (at most 40 requirements, 6k input and 2k output tokens), then try Other again.'


class QuestionDraft(Model):
    text: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(max_length=200)
    recommended: bool
    kpi_refs: list[str] = Field(max_length=15)


class SectionDraft(Model):
    title: str = Field(min_length=1, max_length=200)
    purpose: str = Field(max_length=1000)
    questions: list[QuestionDraft] = Field(min_length=3, max_length=6)


class Proposal(Model):
    sections: list[SectionDraft] = Field(min_length=3, max_length=5)


class Suggestions(Model):
    questions: list[QuestionDraft] = Field(max_length=5)


class Other(Model):
    questions: list[QuestionDraft] = Field(min_length=1, max_length=3)
    requirements: list[req.Extracted] = Field(max_length=req.MAX_REQUIREMENTS)


def load(folder):
    path = folder / 'docs/outline.md'
    return read_artifact(path, Outline) if path.is_file() else None


def normal(text):
    return ' '.join(text.split()).casefold()


def revalidate(outline, context):
    """Keep IDs and every selection, even when a KPI disappears or becomes a ratio."""
    result = outline.model_copy(deep=True)
    kpis = {k.id: k for k in context.kpis}
    for section in result.sections:
        for question in section.questions:
            unknown = [ref for ref in question.kpi_refs if ref not in kpis]
            question.kpi_refs = list(dict.fromkeys(ref for ref in question.kpi_refs if ref in kpis))
            notes = []
            if unknown:
                notes.append('Unknown KPI references removed: ' + ', '.join(unknown))
            if question.kpi_refs and all(kpis[ref].ratio is not None for ref in question.kpi_refs):
                question.recommended = False
                notes.append('Ratio KPI: use numerator and denominator as separate metrics.')
            if notes:
                # Keep the code-owned explanation even if the model used all 200 chars.
                note = ' '.join(notes)[:200]
                if note not in question.rationale:
                    question.rationale = (question.rationale[:max(0, 199 - len(note))] + ' ' + note).strip()
    return result


def compose(folder, old, context, draft, action, section_id=None):
    """Preserve other questions first, then deduplicate incoming normalized text."""
    counter_path = folder.parent / 'outline_ids.json'
    counters = json.loads(counter_path.read_text(encoding='utf-8')) if counter_path.is_file() else {}
    for prefix, ids in (('q', [q.id for s in old.sections for q in s.questions] if old else []),
                        ('s', [s.id for s in old.sections] if old else [])):
        counters[prefix] = max([counters.get(prefix, 0), *[int(i[1:]) for i in ids if re.fullmatch(prefix + r'\d+', i)]])
    def allocate(prefix):
        counters[prefix] += 1
        return prefix + str(counters[prefix])
    previous = {normal(q.text): q for s in old.sections for q in s.questions} if old else {}
    if action == 'outline_propose':
        sections = []
        for entry in draft.sections:
            match = next((s for s in old.sections if normal(s.title) == normal(entry.title)
                          and s.id not in {used.id for used in sections}), None) if old else None
            sections.append(OutlineSection(id=match.id if match else allocate('s'), title=entry.title,
                                           purpose=entry.purpose, questions=[]))
        # Keep other questions in their original section, even if the model replaces that section.
        for original in old.sections if old else []:
            others = [q.model_copy(deep=True) for q in original.questions if q.origin == 'other']
            if others:
                target = next((s for s in sections if s.id == original.id), None)
                if target is None:
                    target = original.model_copy(update={'questions': []}, deep=True)
                    sections.append(target)
                target.questions.extend(others)
        incoming = [(sections[i], entry.questions) for i, entry in enumerate(draft.sections)]
    else:
        sections = old.model_copy(deep=True).sections
        target = next((s for s in sections if s.id == section_id), None)
        if target is None:
            target = OutlineSection(id=allocate('s'), title='Your questions', purpose='Additional user questions.', questions=[])
            sections.append(target)
        incoming = [(target, draft.questions)]
    seen = {normal(q.text) for s in sections for q in s.questions}
    for target, questions in incoming:
        for entry in questions:
            key = normal(entry.text)
            if not key:
                continue
            if key in seen:
                if action == 'outline_other':
                    existing = next(q for s in sections for q in s.questions if normal(q.text) == key)
                    existing.origin, existing.selected = 'other', True
                continue
            seen.add(key)
            prior = previous.get(key)
            origin = {'outline_propose': 'proposed', 'outline_suggest': 'suggested', 'outline_other': 'other'}[action]
            question = OutlineQuestion(id=prior.id if prior else allocate('q'), **entry.model_dump(),
                selected=prior.selected if prior else origin == 'other', origin=origin)
            # Apply ratio/unknown checks before deriving first-proposal selection.
            question = revalidate(Outline(revision=1, sections=[OutlineSection(
                id=target.id, title=target.title, purpose=target.purpose, questions=[question])]), context).sections[0].questions[0]
            if not prior:
                question.selected = question.recommended if origin == 'proposed' else origin == 'other'
            target.questions.append(question)
    # Reserve IDs before publication: failures may leave gaps, never recycled IDs.
    atomic_write(counter_path, json.dumps(counters))
    if action != 'outline_propose':
        original_ids = {s.id for s in old.sections}
        sections = [s for s in sections if s.questions or s.id in original_ids]
    return revalidate(Outline(revision=1, sections=sections), context)


async def persist(harness, build, folder, run_id, outline, *, confirm_context=False):
    old = load(folder)
    outline = outline.model_copy(update={'revision': old.revision + 1 if old else 1})
    await write_artifact(folder / 'docs/outline.md', outline,
        emit=lambda kind, payload: harness.emit(build['id'], run_id, kind, payload))
    if confirm_context:
        build = {**build, **stages.confirmed(build, 'context')}
    stages.save(harness.db, build['id'], stages.edited({**build, 'stage': 'outline'}, 'outline'))
    from dss.api.builds import build_response
    await harness.emit(build['id'], run_id, 'stage.changed', {'stage': 'outline'})
    await harness.emit(build['id'], run_id, 'build.updated', {
        'build': build_response(harness.db, harness.models.settings.get(), build['id'])})
    return outline


def make_branch(harness, build_id, run_id, payload, model, trace, model_error):
    action, config, folder, build = payload['action'], payload['config'], payload['folder'], payload['build']
    context, old = context_node.load(folder), load(folder)
    section = next((s for s in old.sections if s.id == payload.get('section_id')), None) if old else None
    schema = {'outline_propose': Proposal, 'outline_suggest': Suggestions, 'outline_other': Other}[action]
    limit = 3000 if action == 'outline_propose' else 2000
    checker, ledger = Checker(load_registry()), req.load(folder)
    secrets = tuple(getattr(config, k).get_secret_value() for k in ('google_api_key', 'access_code', 'agent_token'))
    state = {'raw': '', 'failure': None, 'scope': False}

    async def instructions(context_object):
        return 'Draft analytical questions. Return only JSON.'

    async def before_model(callback_context, llm_request):
        trace.span(action)
        llm_request.config.response_mime_type = 'application/json'
        llm_request.config.response_json_schema = provider_schema(schema)
        llm_request.config.max_output_tokens = limit
        llm_request.config.thinking_config = types.ThinkingConfig(thinking_level='LOW')
        llm_request.contents = [types.Content(role='user', parts=[types.Part(text='Return the Outline action JSON only.')])]
        try:
            memory = outline_context(config, context, context_node.sources(harness.db, build_id), build['archetype'],
                action, section=section, source=payload.get('source'), reference=references.load(folder), ledger=ledger, checker=checker)
            check_reply(memory, secrets)
            llm_request.config.system_instruction = str(memory)
            await fit_request(memory, llm_request, model, trace.spans[-1])
        except RunError as exc:
            if action == 'outline_other' and exc.detail.get('reason') == 'over_budget':
                state['scope'] = True
            else:
                state['failure'] = exc
            return LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Outline request could not proceed.')]))

    async def after_model(callback_context, llm_response):
        if state['failure'] or state['scope']:
            return llm_response
        if llm_response.partial:
            return LlmResponse(partial=True)
        raw = ''.join(p.text for p in (llm_response.content.parts or []) if p.text and not p.thought) if llm_response.content else ''
        if (llm_response.error_code or llm_response.finish_reason == types.FinishReason.MAX_TOKENS
                or (llm_response.usage_metadata and (llm_response.usage_metadata.candidates_token_count or 0) > limit)
                or tokens(raw) > limit):
            if action == 'outline_other' and (llm_response.finish_reason == types.FinishReason.MAX_TOKENS
                    or tokens(raw) > limit or (llm_response.usage_metadata and
                                             (llm_response.usage_metadata.candidates_token_count or 0) > limit)):
                state['scope'] = True
            else:
                state['failure'] = RunError('llm_unavailable', 'Outline generation failed or exceeded its output budget', 503)
        else:
            try:
                state['raw'] = check_reply(raw, secrets)
            except RunError:
                state['failure'] = RunError('llm_unavailable', 'Outline returned unsafe output', 503)
        return LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Outline received for validation.')]),
                           usage_metadata=llm_response.usage_metadata)

    async def scope_refusal():
        snapshot = req.inputs(harness.db, build_id, folder)
        candidate = ledger.model_copy(deep=True)
        candidate.scope_error = SCOPE_MESSAGE
        candidate.prototype_stale |= (folder / 'spec.json').is_file()
        assessment = req.evaluate(snapshot, candidate, checker, check_components=False)
        req.save(folder, candidate, assessment)
        from dss.api.builds import build_response
        await harness.emit(build_id, run_id, 'docs.updated', {
            'docs': build_response(harness.db, config, build_id)['docs']})
        return SCOPE_MESSAGE

    async def complete(node_input):
        trace.span('validate_outline')
        if state['failure']:
            return 'Outline action could not finish.'
        if state['scope']:
            return await scope_refusal()
        candidate, assessment = None, None
        try:
            draft = schema.model_validate_json(state['raw'])
            if action == 'outline_other':
                candidate, assessment = req.outline_other(harness.db, build_id, folder, payload['source'],
                                                         req.Extraction(requirements=draft.requirements), checker)
            outline = compose(folder, old, context, draft, action, payload.get('section_id'))
        except (ValueError, ValidationError) as exc:
            oversized = str(exc) == 'Requirement scope exceeded' or (isinstance(exc, ValidationError) and any(
                e['type'] == 'too_long' and e['loc'][0] == 'requirements'
                for e in exc.errors(include_input=False, include_context=False)))
            if action == 'outline_other' and oversized:
                return await scope_refusal()
            state['failure'] = RunError('llm_unavailable', 'Outline returned an invalid draft; try again', 503)
            return 'Outline action could not finish.'
        # Combined Other extraction and artifact publication is one commit. Keep the
        # prior bundle on failed writes; the high-water ID counter may retain gaps.
        targets = [folder / 'requirements.json', *[folder / 'docs' / name for name in
                   ('outline.md', 'feasibility.md', 'index.md', 'log.md')]] if candidate is not None else []
        backup = {path: path.read_bytes() if path.is_file() else None for path in targets}
        try:
            if candidate is not None:
                req.save(folder, candidate, assessment)
            await persist(harness, build, folder, run_id, outline, confirm_context=payload.get('confirm_context', False))
        except BaseException:
            for path, content in backup.items():
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(content)
            if backup:
                stages.save(harness.db, build_id, build)
            raise
        if assessment and assessment.state == 'blocked':
            return 'Your questions were saved. Feasibility needs attention: ' + ' '.join(i.reason for i in assessment.issues)
        return 'Outline updated. Select 1-24 questions, then confirm to continue.'

    agent = LlmAgent(name=action, model=model, mode='single_turn', instruction=instructions,
        before_model_callback=before_model, after_model_callback=after_model, on_model_error_callback=model_error)
    return agent, complete, state
