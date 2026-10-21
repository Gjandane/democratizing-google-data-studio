"""Structured Blueprint requirements and deterministic, rechecked decision effects.

No extraction, SQL execution or model calls. Public issues retain their contract shape;
the ledger keeps the code-built effects and the evidence binding each explicit choice.
"""
from collections import Counter
from copy import deepcopy

from dss.artifacts.models import Blueprint, BlueprintRow, BlueprintComponent, Context, Outline, ViewSources
from dss.harness.nodes import view
from dss.spec import requirements as req
from dss.spec.capabilities import CONTROL_TYPES
from dss.spec.validate import catalog


def binding(snapshot, checker, target):
    context = snapshot['context']
    qids = target['qids']
    questions = [q for s in snapshot['outline']['sections'] for q in s['questions']
                 if q['selected'] and (not qids or q['id'] in qids)]
    definitions = {k['id']: k for k in context['kpis']}
    refs = {ref for q in questions for ref in q['kpi_refs']}
    pending = list(refs)
    while pending:
        kpi = definitions.get(pending.pop())
        if kpi and kpi['ratio']:
            for ref in kpi['ratio'].values():
                if ref not in refs:
                    refs.add(ref)
                    pending.append(ref)
    meaning = {'datasets': context['datasets'], 'derived_fields': context['derived_fields'],
               'kpis': [definitions[r] for r in sorted(refs) if r in definitions]}
    # Registry changes trigger deterministic component checks, not renewed consent
    # for an unchanged, still-supported choice. Display-only Context edits likewise.
    return req.digest([snapshot['sources'], meaning, questions])


def choices(snapshot, ledger, checker):
    return [d for d in ledger.blueprint_decisions if d['binding'] == binding(snapshot, checker, d['target'])]


def component_errors(component, fields, checker):
    c = component.model_dump()
    if component.type == 'dropdown' and len(component.dimensions) == 1:
        c['field'], c['dimensions'] = component.dimensions[0], []
    errors = [(v.status, v.reason, list(v.evidence)) for v in checker.component(c)]
    if errors:
        return errors  # Invalid option values must never reach slot arithmetic.
    rule = catalog().get(component.type)
    if rule is None:
        return errors + [('unsupported_app', 'Component type is absent from the catalog', [])]
    dimensions = component.dimensions
    if component.type == 'pivot_table' and any(k in component.options for k in ('row_dimensions', 'column_dimensions')):
        dimensions = component.options.get('row_dimensions', []) + component.options.get('column_dimensions', [])
    # Blueprint has no separate field slot: its single dropdown dimension maps
    # to add_control.field, and is excluded from catalog dimension counts.
    counted_dimensions = [] if component.type == 'dropdown' else dimensions
    for slot, values in (('dimensions', counted_dimensions), ('metrics', component.metrics)):
        if not rule['min_' + slot] <= len(values) <= rule['max_' + slot]:
            errors.append(('unsupported_app', f"Expected {rule['min_' + slot]}..{rule['max_' + slot]} {slot}", []))
    if rule['requires_date_dimension'] and not component.date_dimension:
        errors.append(('needs_data', 'A date dimension is required', []))
    slots = {'dimensions': [] if component.type == 'dropdown' else dimensions, 'metrics': component.metrics,
             'date_dimension': [component.date_dimension] if component.date_dimension else [],
             'breakdown': [component.breakdown] if component.breakdown else [],
             'field': dimensions if component.type == 'dropdown' else []}
    for slot, values in slots.items():
        for value in values:
            name = value.field if slot == 'metrics' else value
            field = fields.get(name)
            if field is None:
                errors.append(('needs_data', f'Field {name} is not in the view', []))
                continue
            counting = slot == 'metrics' and value.agg in ('count', 'count_distinct')
            if field['role'] not in rule['slot_roles'][slot] and not counting:
                errors.append(('needs_data', f'Field {name} has the wrong role for {slot}', []))
            if slot == 'date_dimension' and field['type'] not in ('DATE', 'DATETIME', 'TIMESTAMP'):
                errors.append(('needs_data', 'Date dimension must have a date or timestamp type', []))
            if slot == 'metrics' and value.agg in ('sum', 'avg') and field['role'] != 'metric':
                errors.append(('needs_data', 'sum/avg require a numeric field', []))
            if slot == 'dimensions' and component.type == 'geo_map' and field['type'] not in ('GEO', 'GEOGRAPHY'):
                errors.append(('needs_data', 'Geo map requires a geographic field', []))
    bound = set(dimensions) | {m.field for m in component.metrics} | set(slots['date_dimension']) | set(slots['breakdown'])
    if component.sort and component.sort.field not in bound:
        errors.append(('needs_data', 'Sort field must be among the row fields', []))
    if component.type == 'dropdown' and len(dimensions) != 1:
        errors.append(('needs_data', 'A dropdown needs one dimension field', []))
    return errors


def diagnostics(snapshot, ledger, checker):
    """Return full, internal row diagnostics, including repair eligibility and effects."""
    if not snapshot.get('blueprint'):
        return []
    bp = Blueprint.model_validate(snapshot['blueprint'])
    for row in bp.rows:
        row.status, row.issue_ids = 'ok', []
    context, outline = Context.model_validate(snapshot['context']), Outline.model_validate(snapshot['outline'])
    selected = {q.id: q for s in outline.sections for q in s.questions if q.selected}
    sections = {q.id: s.id for s in outline.sections for q in s.questions}
    approved = choices(snapshot, ledger, checker)
    dropped = {q for d in approved if d['action'] == 'drop' or d.get('effect', {}).get('drop_questions')
               for q in d.get('effect', {}).get('drop_questions', d['target']['qids'])}
    ratios = {q for d in approved if d.get('effect', {}).get('ratio_measures') for q in d['target']['qids']}
    result = []
    connected = [{**s, 'bq_table': s.get('bq_table', s.get('table'))} for s in snapshot['sources']]

    def add(code, indices, qids, message, status='needs_clarification', repairable=True, offers=(), evidence=()):
        result.append(dict(code=code, indices=indices, qids=qids, message=message, status=status,
                           repairable=repairable, offers=list(offers), evidence=list(evidence)))

    fields, source_invalid = {}, False
    try:
        fields = {f['name']: f for f in view.blueprint_fields(connected, bp.view_sources, bp.derived_fields)}
        # Validate join keys too, without executing SQL.
        view.blueprint_sql(connected, bp.view_sources, bp.derived_fields,
                           context_fields=[f.name for f in context.derived_fields])
    except ValueError:
        source_invalid = True
    involved = {bp.view_sources.base, *[j.source_id for j in bp.view_sources.joins], *bp.view_sources.union}
    expected = {d.source_id for d in context.datasets}
    source_approved = any(d.get('effect', {}).get('view_sources') == bp.view_sources.model_dump() for d in approved)
    source_dropped = any(d['action'] == 'drop' and d['target']['code'] == 'sources' for d in approved)
    if (source_invalid and not (source_dropped and not bp.rows)) or (
            len(expected) > 1 and not expected <= involved and not source_approved and not source_dropped):
        offers = []
        for source in snapshot['sources']:
            offers.append({'id': 'source_' + source['id'], 'label': 'Use only source ' + source['id'],
                           'view_sources': {'base': source['id'], 'joins': [], 'union': []}})
        union = {'base': bp.view_sources.base, 'joins': [],
                 'union': [s['id'] for s in snapshot['sources'] if s['id'] != bp.view_sources.base]}
        try:
            view.blueprint_sql(connected, ViewSources.model_validate(union), bp.derived_fields,
                               context_fields=[f.name for f in context.derived_fields])
            offers.append({'id': 'union', 'label': 'Union the sources with dataset_name', 'view_sources': union})
        except ValueError:
            pass
        add('sources', list(range(len(bp.rows))), [], 'Multiple sources need valid joins or a union; choose how to combine them' if not source_invalid else
            'View sources or join keys are invalid; choose a source or union',
            'needs_data', False, offers)
    kpis = {k.id: k for k in context.kpis}
    for qid, question in selected.items():
        if qid in dropped:
            continue
        indices = [i for i, r in enumerate(bp.rows) if r.question_id == qid]
        if not 1 <= len(indices) <= 3:
            add('coverage', indices, [qid], 'Each selected question needs 1-3 rows')
        definitions = [kpis.get(ref) for ref in question.kpi_refs]
        if any(k is None for k in definitions):
            add('kpi', indices, [qid], 'Question names an unknown KPI')
        ratio = [k for k in definitions if k and k.ratio]
        if ratio and qid not in ratios:
            offers = []
            measures = []
            for kpi in ratio:
                for ref in (kpi.ratio.numerator, kpi.ratio.denominator):
                    inner = kpis.get(ref)
                    if inner and inner.measure:
                        measures.append(inner)
            if len(measures) == 2 * len(ratio) and len(measures) <= 3 and indices:
                rows = []
                for kpi in measures:
                    row = bp.rows[indices[0]].model_copy(deep=True)
                    row.component = BlueprintComponent.model_validate({**row.component.model_dump(), 'type': 'scorecard', 'label': kpi.name,
                        'dimensions': [], 'metrics': [kpi.measure.model_dump()], 'date_dimension': None,
                        'breakdown': None, 'sort': None, 'options': {}})
                    rows.append(row.model_dump())
                if all(not component_errors(type(bp.rows[0]).model_validate(r).component, fields, checker) for r in rows):
                    offers.append({'id': 'numerator_denominator', 'label': 'Show numerator and denominator as separate metrics',
                                   'rows': rows, 'ratio_measures': [k.measure.model_dump() for k in measures]})
            add('ratio', indices, [qid], 'A ratio KPI cannot be a chart metric; calculated fields are outside this app',
                'unsupported_app', False, offers)
        required = [k.measure.model_dump() for k in definitions if k and k.measure]
        for d in approved:
            if qid in d['target']['qids']:
                required += d.get('effect', {}).get('ratio_measures', [])
        metrics = [m.model_dump() for i in indices for m in bp.rows[i].component.metrics]
        if any(m not in metrics for m in required) or any(
            m['field'] in {needed['field'] for needed in required} and m not in required for m in metrics):
            add('kpi', indices, [qid], 'Use each named KPI with exactly its confirmed field and aggregation')
    for i, row in enumerate(bp.rows):
        if row.question_id is not None and row.question_id not in selected:
            add('coverage', [i], [row.question_id], 'Row must answer a selected question')
        if row.question_id in selected and row.section_id != sections[row.question_id]:
            add('page', [i], [row.question_id], 'Row must belong to its question section')
        for status, message, evidence in component_errors(row.component, fields, checker):
            offers = []
            date = fields.get(row.component.date_dimension)
            if row.component.type == 'time_series' and (not date or date['type'] not in ('DATE', 'DATETIME', 'TIMESTAMP')):
                for kind in ('scorecard', 'table', 'scatter'):
                    dimensions = []
                    if kind == 'table':
                        available = [f for f in fields if fields[f]['role'] == 'dimension' and
                                     fields[f]['type'] not in ('DATE', 'DATETIME', 'TIMESTAMP')]
                        dimensions = ([row.component.breakdown] if row.component.breakdown in available else available[:1])
                    replacement = row.model_copy(deep=True)
                    replacement.component = replacement.component.model_copy(update={'type': kind, 'dimensions': dimensions,
                        'date_dimension': None, 'breakdown': None, 'options': {}, 'sort': None})
                    if not component_errors(replacement.component, fields, checker):
                        offers.append({'id': 'without_date', 'label': f'Use a {kind} without a date axis',
                                       'replace_indices': [i], 'rows': [replacement.model_dump()]})
                        break
            add('row', [i], [row.question_id] if row.question_id else [], message, status, True, offers, evidence)
    for page, count in Counter(r.page for r in bp.rows).items():
        indices = [i for i, r in enumerate(bp.rows) if r.page == page]
        if not 1 <= page <= 5:
            add('page', indices, [], 'Blueprint needs 1-5 pages')
        controls = [i for i in indices if bp.rows[i].question_id is None]
        if len(controls) > 2 or any(bp.rows[i].component.type not in CONTROL_TYPES for i in controls):
            add('controls', controls, [], 'At most two supporting controls are allowed per page')
        if count > 12:
            nonrecommended = list(dict.fromkeys(bp.rows[i].question_id for i in reversed(indices)
                if bp.rows[i].question_id in selected and not selected[bp.rows[i].question_id].recommended))
            remove, remaining = [], count
            for qid in nonrecommended:
                if remaining <= 12:
                    break
                remove.append(qid)
                remaining -= sum(r.question_id == qid for r in bp.rows if r.page == page)
            offers = ([{'id': 'trim', 'label': 'Drop the last non-recommended questions', 'drop_questions': remove}]
                      if remaining <= 12 else [])
            section_counts = Counter(r.section_id for r in bp.rows)
            if 1 <= len(section_counts) <= 5 and max(section_counts.values()) <= 12:
                offers.append({'id': 'per_section', 'label': 'Use one page per section', 'page_structure': 'per_section'})
            add('capacity', indices, [], 'Too many components: a page holds at most 12 rows', offers=offers)
    for error in snapshot.get('blueprint_errors', []):
        if error.get('question_id') is None:
            add('sql', list(range(len(bp.rows))), [], error['message'], 'needs_data', False)
    return result


def issue_rows(snapshot, ledger, checker):
    rows = []
    for error in diagnostics(snapshot, ledger, checker):
        iid = 'bp_' + req.digest(error)[:24]
        issue = req.Issue(id=iid, requirement=', '.join(error['qids']) or 'Blueprint view',
            status=error['status'], reason=error['message'], evidence=error['evidence'],
            alternatives=[req.Alternative(id=o['id'], label=o['label']) for o in error['offers']])
        rows.append((issue, error))
    # Resolved issues remain visible, with the user's explicit choice.
    for decision in choices(snapshot, ledger, checker):
        issue = req.Issue.model_validate(decision['issue'])
        issue.resolution = 'dropped' if decision['action'] == 'drop' else 'accepted_alternative'
        if not any(i.id == issue.id for i, _ in rows):
            rows.append((issue, decision['target']))
    return rows


def mark(snapshot, ledger, checker, assessment):
    bp = Blueprint.model_validate(snapshot['blueprint'])
    for row in bp.rows:
        row.status, row.issue_ids = 'ok', []
    by_id = {i.id: e for i, e in issue_rows(snapshot, ledger, checker)}
    for issue in assessment.issues:
        if issue.resolution != 'unresolved':
            continue
        target = by_id.get(issue.id)
        indices = target['indices'] if target else range(len(bp.rows))
        for i in indices:
            if i < len(bp.rows):
                bp.rows[i].status = 'blocked'
                bp.rows[i].issue_ids.append(issue.id)
    bp.assessment_id = assessment.id
    return bp


def decide(snapshot, ledger, checker, body):
    current = req.require_current(snapshot, ledger, checker, body.assessment_id)
    targets = {i.id: (i, e) for i, e in issue_rows(snapshot, ledger, checker) if i.resolution == 'unresolved'}
    validated = []
    for item in (d for d in body.decisions if d.issue_id.startswith('bp_')):
        if item.issue_id not in targets or not any(i.id == item.issue_id for i in current.issues):
            raise req.RunError('invalid_request', 'Choose an unresolved Blueprint issue', 422)
        issue, target = targets[item.issue_id]
        offer = next((o for o in target['offers'] if o['id'] == item.alternative_id), None)
        if item.action == 'accept_alternative' and offer is None:
            raise req.RunError('invalid_request', 'Choose an offered Blueprint alternative', 422)
        if any(set(target['indices']) & set(t['indices']) or set(target['qids']) & set(t['qids'])
               for _, _, t, _ in validated):
            raise req.RunError('invalid_request', 'Resolve overlapping Blueprint issues separately', 422)
        validated.append((item, issue, target, offer))
    regular = [d for d in body.decisions if not d.issue_id.startswith('bp_')]
    updated = (req.decide(snapshot, ledger, checker, req.Decisions(assessment_id=body.assessment_id,
               decisions=regular))[0] if regular else ledger.model_copy(deep=True))
    fresh = deepcopy(snapshot)
    bp = Blueprint.model_validate(fresh['blueprint'])
    remove_indices, additions = set(), []
    for item, issue, target, offer in validated:
        drop_questions = list(dict.fromkeys(target['qids'] + [
            bp.rows[i].question_id for i in target['indices'] if bp.rows[i].question_id is not None]))
        if target['code'] == 'row':
            drop_questions = [qid for qid in drop_questions if all(
                r.question_id != qid or i in target['indices'] for i, r in enumerate(bp.rows))]
        effect = offer or {'drop_questions': drop_questions}
        if item.action == 'drop':
            remove_indices.update(target['indices'])
            if target['code'] == 'sql':
                fresh['blueprint_errors'] = []
        if 'drop_questions' in effect:
            remove_indices.update(i for i, r in enumerate(bp.rows) if r.question_id in effect['drop_questions'])
        if 'rows' in effect:
            remove_indices.update(effect.get('replace_indices', target['indices']))
            additions.extend(effect['rows'])
        if 'view_sources' in effect:
            bp.view_sources = ViewSources.model_validate(effect['view_sources'])
            bp.view_table = None  # explicit choice needs the accept-time dry run
            fresh['blueprint_errors'] = []
        if effect.get('page_structure'):
            fresh['design']['page_structure'] = effect['page_structure']
            sections = [s for s in Outline.model_validate(fresh['outline']).sections if any(q.selected for q in s.questions)]
            pages = {s.id: i for i, s in enumerate(sections, 1)}
            for row in bp.rows:
                row.page = pages[row.section_id]
        updated.blueprint_decisions.append({'binding': binding(snapshot, checker, target), 'action': item.action,
            'issue': issue.model_dump(), 'target': target, 'effect': effect})
    bp.rows = [r for i, r in enumerate(bp.rows) if i not in remove_indices] + [
        BlueprintRow.model_validate(r) for r in additions]
    bp.revision += 1
    fresh['blueprint'] = bp.model_dump()
    assessment = req.evaluate(fresh, updated, checker, check_components=False)
    bp = mark(fresh, updated, checker, assessment)
    fresh['blueprint'] = bp.model_dump()
    assessment.input_digest = req.input_digest(fresh, updated, checker)
    return updated, assessment, bp, fresh
