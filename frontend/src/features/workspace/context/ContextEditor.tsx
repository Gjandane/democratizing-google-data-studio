// The Context stage's editor (docs/staged-ui.md): every part of the drafted Context is edited in
// place and saved with PUT. Selects, mode switches and add/remove save at once; text saves when the
// field loses focus. Saving never disables a control, so focus stays where the user is.
import { Plus, Trash2 } from 'lucide-react';
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { api } from '../../../api/client';
import { ApiError, COLUMN_TYPES, type Build, type Context, type ContextUpdate, type DerivedField, type Kpi, type Threshold, type ValidationIssue } from '../../../api/types';
import { Button } from '../../../components/Button';
import { ErrorState } from '../../../components/ErrorState';
import { Input, TextArea } from '../../../components/Input';
import { focusRing } from '../../../components/focus';
import { IssueList, issueText, NumberField, SelectField } from './fields';
import { AGG_LABELS, aggAfterFieldChange, aggsFor, fieldOptions, formula, newId, placeIssues, toUpdate, type FieldOption } from './model';

const OPERATORS: Threshold['operator'][] = ['>', '>=', '<', '<=', '='];
const sectionTitle = 'text-title font-semibold text-text';
const mono = 'font-mono text-label text-text-muted';
const cell = 'px-2 py-1.5 align-top';

/** Every path the editor shows: issues land on the deepest one that contains them. */
function renderedPaths(draft: ContextUpdate): Set<string> {
  const paths = new Set(['/title', '/goal', '/audience', '/datasets', '/kpis', '/derived_fields', '/thresholds', '/glossary']);
  const add = (list: string, i: number, keys: string[]) => {
    paths.add(`/${list}/${i}`);
    for (const key of keys) paths.add(`/${list}/${i}/${key}`);
  };
  draft.datasets.forEach((_, i) => add('datasets', i, []));
  draft.kpis.forEach((kpi, i) => add('kpis', i, ['name', 'description', 'unit', ...(kpi.ratio ? ['ratio/numerator', 'ratio/denominator'] : ['measure/field', 'measure/agg'])]));
  draft.derived_fields.forEach((_, i) => add('derived_fields', i, ['name', 'expression', 'type', 'description']));
  draft.thresholds.forEach((_, i) => add('thresholds', i, ['name', 'field', 'operator', 'value', 'unit', 'description']));
  draft.glossary.forEach((_, i) => add('glossary', i, ['term', 'definition']));
  return paths;
}

const errorText = (error: unknown) => (error instanceof ApiError ? error.message : "Couldn't save your change. Try again.");

type Focus = { list: 'kpis' | 'derived_fields' | 'thresholds' | 'glossary'; index: number } | { add: 'kpis' | 'derived_fields' | 'thresholds' | 'glossary' };

export function ContextEditor({
  build,
  context,
  disabled,
  onSaved,
  onSavingChange,
}: {
  build: Build;
  /** The latest Context from the server: its issues show inline. */
  context: Context;
  /** A run holds the build's lock, or the build is past editing. */
  disabled: boolean;
  onSaved: (context: Context) => void;
  /** True while a save runs or after one failed: the server's copy isn't what the user sees. */
  onSavingChange: (saving: boolean) => void;
}) {
  const uid = useId();
  const [draft, setDraft] = useState<ContextUpdate>(() => toUpdate(context));
  const [saveError, setSaveError] = useState<string | null>(null);
  const latest = useRef(draft);
  latest.current = draft;
  // Edit counters: `edited` grows on every change, `sent` is the edit the last PUT carried,
  // `acked` the last one the server stored. The server's value replaces the draft only when
  // nothing newer is waiting.
  const edited = useRef(0);
  const sent = useRef(0);
  const acked = useRef(0);
  const inFlight = useRef(false);
  const queued = useRef(false);
  const mounted = useRef(true);
  const remembered = useRef(new Map<string, Pick<Kpi, 'measure' | 'ratio'>>());
  const focusNext = useRef<Focus | null>(null);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // A redraft or another tab's save arrives through artifact.updated: adopt it unless edits wait.
  useEffect(() => {
    if (!inFlight.current && edited.current === acked.current) setDraft(toUpdate(context));
  }, [context]);

  // After add or remove, keyboard focus goes to the new row's first field or back to the Add button.
  useLayoutEffect(() => {
    const target = focusNext.current;
    if (!target || !root.current) return;
    focusNext.current = null;
    const selector = 'add' in target ? `[data-add="${target.add}"]` : `[data-row="${target.list}-${target.index}"] input, [data-row="${target.list}-${target.index}"] textarea`;
    root.current.querySelector<HTMLElement>(selector)?.focus();
  });

  const save = async (): Promise<void> => {
    if (inFlight.current) {
      if (edited.current !== sent.current) queued.current = true;
      return;
    }
    inFlight.current = true;
    onSavingChange(true);
    const seq = edited.current;
    sent.current = seq;
    let failed = false;
    try {
      const saved = await api.updateContext(build.id, latest.current);
      if (!mounted.current) return;
      acked.current = seq;
      setSaveError(null);
      if (edited.current === seq) setDraft(toUpdate(saved));
      onSaved(saved);
    } catch (error) {
      failed = true;
      if (mounted.current) setSaveError(errorText(error));
    } finally {
      inFlight.current = false;
      if (mounted.current) {
        if (queued.current) {
          queued.current = false;
          void save();
        } else onSavingChange(failed);
      }
    }
  };

  /** Applies a change; `commit` saves it now (selects, switches, add/remove), else on blur. */
  const change = (update: (d: ContextUpdate) => ContextUpdate, commit = false) => {
    const next = update(latest.current);
    latest.current = next;
    edited.current += 1;
    setDraft(next);
    if (commit) void save();
  };
  const commitText = () => {
    if (edited.current !== acked.current) void save();
  };

  const setKpi = (i: number, patch: Partial<Kpi>, commit = false) =>
    change((d) => ({ ...d, kpis: d.kpis.map((k, j) => (j === i ? { ...k, ...patch } : k)) }), commit);
  const setDerived = (i: number, patch: Partial<DerivedField>, commit = false) =>
    change((d) => ({ ...d, derived_fields: d.derived_fields.map((f, j) => (j === i ? { ...f, ...patch } : f)) }), commit);
  const setThreshold = (i: number, patch: Partial<Threshold>, commit = false) =>
    change((d) => ({ ...d, thresholds: d.thresholds.map((t, j) => (j === i ? { ...t, ...patch } : t)) }), commit);
  const setTerm = (i: number, patch: Partial<ContextUpdate['glossary'][number]>, commit = false) =>
    change((d) => ({ ...d, glossary: d.glossary.map((t, j) => (j === i ? { ...t, ...patch } : t)) }), commit);
  const remove = (list: 'kpis' | 'derived_fields' | 'thresholds' | 'glossary', i: number) => {
    focusNext.current = { add: list };
    change((d) => ({ ...d, [list]: (d[list] as unknown[]).filter((_, j) => j !== i) }), true);
  };

  const fields = fieldOptions(build.sources, draft);
  const typeOf = (name: string) => fields.find((f) => f.name === name)?.type;
  const placed = placeIssues(context.issues, renderedPaths(draft));
  const at = (path: string) => placed.get(path);
  const err = (path: string) => issueText(at(path));
  const countIn = (prefix: string) => context.issues.filter((issue) => issue.path === prefix || issue.path.startsWith(`${prefix}/`)).length;

  const switchMode = (i: number, mode: 'measure' | 'ratio') => {
    const kpi = latest.current.kpis[i];
    if (!kpi || (mode === 'ratio') === (kpi.ratio !== null)) return;
    // Switching back restores what the card had in that mode.
    remembered.current.set(`${kpi.id}:${mode === 'ratio' ? 'measure' : 'ratio'}`, { measure: kpi.measure, ratio: kpi.ratio });
    const memory = remembered.current.get(`${kpi.id}:${mode}`);
    if (mode === 'ratio') {
      const others = latest.current.kpis.filter((k) => k.id !== kpi.id).map((k) => k.id);
      setKpi(i, { measure: null, ratio: memory?.ratio ?? { numerator: others[0] ?? '', denominator: others[1] ?? others[0] ?? '' } }, true);
    } else {
      const first = fields.find((f) => f.type === 'number') ?? fields[0];
      setKpi(i, { ratio: null, measure: memory?.measure ?? { field: first?.name ?? '', agg: aggAfterFieldChange('sum', first?.type) } }, true);
    }
  };

  const addKpi = () => {
    focusNext.current = { list: 'kpis', index: latest.current.kpis.length };
    const first = fields.find((f) => f.type === 'number') ?? fields[0];
    const kpi: Kpi = { id: newId('kpi', latest.current.kpis), name: '', description: '', unit: null, measure: { field: first?.name ?? '', agg: aggAfterFieldChange('sum', first?.type) }, ratio: null };
    change((d) => ({ ...d, kpis: [...d.kpis, kpi] }), true);
  };
  const addDerived = () => {
    focusNext.current = { list: 'derived_fields', index: latest.current.derived_fields.length };
    change((d) => ({ ...d, derived_fields: [...d.derived_fields, { name: '', expression: '', type: 'string', description: '' }] }), true);
  };
  const addThreshold = () => {
    focusNext.current = { list: 'thresholds', index: latest.current.thresholds.length };
    const first = fields.find((f) => f.type === 'number') ?? fields[0];
    change((d) => ({ ...d, thresholds: [...d.thresholds, { id: newId('threshold', d.thresholds), name: '', field: first?.name ?? '', operator: '>=', value: 0, unit: null, description: '' }] }), true);
  };
  const addTerm = () => {
    focusNext.current = { list: 'glossary', index: latest.current.glossary.length };
    change((d) => ({ ...d, glossary: [...d.glossary, { term: '', definition: '' }] }), true);
  };

  const sourceName = (id: string) => build.sources.find((s) => s.id === id)?.name ?? id;
  const kpiLabel = (kpi: Kpi) => kpi.name.trim() || kpi.id;

  return (
    <div ref={root} className="mt-4">
      {saveError && (
        <ErrorState className="mb-4" title="Couldn't save your change" message={`${saveError} Your edits are kept here.`} onRetry={disabled ? undefined : () => void save()} retryLabel="Save again" />
      )}
      <IssueList issues={at('')} className="mb-3" />
      <fieldset disabled={disabled} className="min-w-0">
        <legend className="sr-only">Context</legend>
        <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)] gap-3">
          <Input label="Title" value={draft.title} error={err('/title')} onChange={(e) => change((d) => ({ ...d, title: e.target.value }))} onBlur={commitText} />
          <Input label="Audience" placeholder="Who reads it" value={draft.audience ?? ''} error={err('/audience')} onChange={(e) => change((d) => ({ ...d, audience: e.target.value === '' ? null : e.target.value }))} onBlur={commitText} />
          <TextArea label="Goal" rows={2} className="col-span-2" value={draft.goal} error={err('/goal')} onChange={(e) => change((d) => ({ ...d, goal: e.target.value }))} onBlur={commitText} />
        </div>

        <h3 className={`${sectionTitle} mt-6 mb-2`}>Datasets</h3>
        <IssueList issues={at('/datasets')} className="mb-2" />
        <ul className="divide-y divide-border rounded-panel border border-border bg-surface">
          {draft.datasets.map((d, i) => (
            <li key={d.source_id} className="px-3 py-2 text-body">
              <span className="font-medium text-text">{sourceName(d.source_id)}</span> <code className={mono}>{d.source_id}</code>
              <p className="text-text-muted">{d.summary}</p>
              <IssueList issues={at(`/datasets/${i}`)} className="mt-1" />
            </li>
          ))}
        </ul>

        <div className="mt-6 mb-2 flex items-center justify-between gap-3">
          <h3 className={sectionTitle}>
            KPIs <span className="text-label font-normal text-text-muted tabular-nums">{draft.kpis.length}</span>
          </h3>
          <Button size="sm" variant="secondary" icon={<Plus aria-hidden="true" />} data-add="kpis" onClick={addKpi}>
            Add KPI
          </Button>
        </div>
        <IssueList issues={at('/kpis')} className="mb-2" />
        {draft.kpis.length === 0 ? (
          <p className="rounded-panel border border-dashed border-border-strong px-3 py-4 text-body text-text-muted">No KPIs yet. Add one to say what the dashboard measures.</p>
        ) : (
          <div className="grid grid-cols-1 gap-3 min-[1440px]:grid-cols-2">
            {draft.kpis.map((kpi, i) => (
              <KpiCard
                key={i}
                index={i}
                uid={uid}
                kpi={kpi}
                kpis={draft.kpis}
                fields={fields}
                typeOf={typeOf}
                issueCount={countIn(`/kpis/${i}`)}
                cardIssues={at(`/kpis/${i}`)}
                err={err}
                label={kpiLabel(kpi)}
                setKpi={setKpi}
                switchMode={switchMode}
                commitText={commitText}
                onRemove={() => remove('kpis', i)}
              />
            ))}
          </div>
        )}

        <Collapsible title="Derived fields" count={draft.derived_fields.length} issues={countIn('/derived_fields')} onAdd={addDerived} addLabel="Add derived field" list="derived_fields" listIssues={at('/derived_fields')}>
          {draft.derived_fields.length === 0 ? (
            <Empty>No derived fields. Add one to compute a column from the others.</Empty>
          ) : (
            <table className="w-full table-fixed border-collapse text-body">
              <colgroup>
                <col className="w-[22%]" />
                <col />
                <col className="w-28" />
                <col className="w-[24%]" />
                <col className="w-10" />
              </colgroup>
              <TableHead labels={['Name', 'Expression (BigQuery SQL)', 'Type', 'Description', '']} />
              <tbody>
                {draft.derived_fields.map((f, i) => (
                  <tr key={i} data-row={`derived_fields-${i}`} className="border-t border-border">
                    <td className={cell}>
                      <Input label={`Name of derived field ${i + 1}`} hideLabel className="[&_input]:font-mono" spellCheck={false} value={f.name} error={err(`/derived_fields/${i}/name`)} onChange={(e) => setDerived(i, { name: e.target.value })} onBlur={commitText} />
                    </td>
                    <td className={cell}>
                      <TextArea label={`Expression of ${f.name || `derived field ${i + 1}`}`} hideLabel rows={2} className="[&_textarea]:font-mono [&_textarea]:text-label" spellCheck={false} value={f.expression} error={err(`/derived_fields/${i}/expression`)} onChange={(e) => setDerived(i, { expression: e.target.value })} onBlur={commitText} />
                    </td>
                    <td className={cell}>
                      <SelectField label={`Type of ${f.name || `derived field ${i + 1}`}`} hideLabel value={f.type} error={err(`/derived_fields/${i}/type`)} onChange={(e) => setDerived(i, { type: e.target.value as DerivedField['type'] }, true)}>
                        {COLUMN_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                      </SelectField>
                    </td>
                    <td className={cell}>
                      <Input label={`Description of ${f.name || `derived field ${i + 1}`}`} hideLabel value={f.description} error={err(`/derived_fields/${i}/description`)} onChange={(e) => setDerived(i, { description: e.target.value })} onBlur={commitText} />
                    </td>
                    <td className={cell}>
                      <RemoveButton label={`Remove derived field ${f.name || i + 1}`} onClick={() => remove('derived_fields', i)} />
                      <IssueList issues={at(`/derived_fields/${i}`)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Collapsible>

        <Collapsible title="Thresholds" count={draft.thresholds.length} issues={countIn('/thresholds')} onAdd={addThreshold} addLabel="Add threshold" list="thresholds" listIssues={at('/thresholds')}>
          {draft.thresholds.length === 0 ? (
            <Empty>No thresholds. Add one to mark values above or below a limit.</Empty>
          ) : (
            <table className="w-full table-fixed border-collapse text-body">
              <colgroup>
                <col className="w-[22%]" />
                <col className="w-[18%]" />
                <col className="w-20" />
                <col className="w-20" />
                <col className="w-20" />
                <col />
                <col className="w-10" />
              </colgroup>
              <TableHead labels={['Name', 'Field', 'Rule', 'Value', 'Unit', 'Description', '']} />
              <tbody>
                {draft.thresholds.map((t, i) => {
                  const name = t.name || `threshold ${i + 1}`;
                  return (
                    <tr key={i} data-row={`thresholds-${i}`} className="border-t border-border">
                      <td className={cell}>
                        <Input label={`Name of threshold ${i + 1}`} hideLabel value={t.name} error={err(`/thresholds/${i}/name`)} onChange={(e) => setThreshold(i, { name: e.target.value })} onBlur={commitText} />
                      </td>
                      <td className={cell}>
                        <SelectField label={`Field of ${name}`} hideLabel value={t.field} error={err(`/thresholds/${i}/field`)} onChange={(e) => setThreshold(i, { field: e.target.value }, true)}>
                          <FieldChoices fields={fields} current={t.field} />
                        </SelectField>
                      </td>
                      <td className={cell}>
                        <SelectField label={`Rule of ${name}`} hideLabel className="[&_select]:font-mono" value={t.operator} error={err(`/thresholds/${i}/operator`)} onChange={(e) => setThreshold(i, { operator: e.target.value as Threshold['operator'] }, true)}>
                          {OPERATORS.map((op) => <option key={op} value={op}>{op}</option>)}
                        </SelectField>
                      </td>
                      <td className={cell}>
                        <NumberField label={`Value of ${name}`} className="[&_input]:tabular-nums" value={t.value} error={err(`/thresholds/${i}/value`)} onValue={(value) => setThreshold(i, { value })} onBlur={commitText} />
                      </td>
                      <td className={cell}>
                        <Input label={`Unit of ${name}`} hideLabel value={t.unit ?? ''} error={err(`/thresholds/${i}/unit`)} onChange={(e) => setThreshold(i, { unit: e.target.value === '' ? null : e.target.value })} onBlur={commitText} />
                      </td>
                      <td className={cell}>
                        <Input label={`Description of ${name}`} hideLabel value={t.description} error={err(`/thresholds/${i}/description`)} onChange={(e) => setThreshold(i, { description: e.target.value })} onBlur={commitText} />
                      </td>
                      <td className={cell}>
                        <RemoveButton label={`Remove threshold ${t.name || i + 1}`} onClick={() => remove('thresholds', i)} />
                        <IssueList issues={at(`/thresholds/${i}`)} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Collapsible>

        <Collapsible title="Glossary" count={draft.glossary.length} issues={countIn('/glossary')} onAdd={addTerm} addLabel="Add term" list="glossary" listIssues={at('/glossary')}>
          {draft.glossary.length === 0 ? (
            <Empty>No terms. Add one to define a word the dashboard uses.</Empty>
          ) : (
            <table className="w-full table-fixed border-collapse text-body">
              <colgroup>
                <col className="w-[28%]" />
                <col />
                <col className="w-10" />
              </colgroup>
              <TableHead labels={['Term', 'Definition', '']} />
              <tbody>
                {draft.glossary.map((t, i) => (
                  <tr key={i} data-row={`glossary-${i}`} className="border-t border-border">
                    <td className={cell}>
                      <Input label={`Term ${i + 1}`} hideLabel value={t.term} error={err(`/glossary/${i}/term`)} onChange={(e) => setTerm(i, { term: e.target.value })} onBlur={commitText} />
                    </td>
                    <td className={cell}>
                      <Input label={`Definition of ${t.term || `term ${i + 1}`}`} hideLabel value={t.definition} error={err(`/glossary/${i}/definition`)} onChange={(e) => setTerm(i, { definition: e.target.value })} onBlur={commitText} />
                    </td>
                    <td className={cell}>
                      <RemoveButton label={`Remove term ${t.term || i + 1}`} onClick={() => remove('glossary', i)} />
                      <IssueList issues={at(`/glossary/${i}`)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Collapsible>
      </fieldset>
    </div>
  );
}

function KpiCard({
  index: i,
  uid,
  kpi,
  kpis,
  fields,
  typeOf,
  issueCount,
  cardIssues,
  err,
  label,
  setKpi,
  switchMode,
  commitText,
  onRemove,
}: {
  index: number;
  uid: string;
  kpi: Kpi;
  kpis: Kpi[];
  fields: FieldOption[];
  typeOf: (name: string) => FieldOption['type'] | undefined;
  issueCount: number;
  cardIssues: ValidationIssue[] | undefined;
  err: (path: string) => ReactNode;
  label: string;
  setKpi: (i: number, patch: Partial<Kpi>, commit?: boolean) => void;
  switchMode: (i: number, mode: 'measure' | 'ratio') => void;
  commitText: () => void;
  onRemove: () => void;
}) {
  const mode = kpi.ratio ? 'ratio' : 'measure';
  const others = kpis.filter((k) => k.id !== kpi.id);
  const fieldType = kpi.measure ? typeOf(kpi.measure.field) : undefined;
  const aggs = aggsFor(fieldType);
  const path = `/kpis/${i}`;
  return (
    <section aria-label={`KPI ${label}`} data-row={`kpis-${i}`} className={`flex min-w-0 flex-col gap-2 rounded-panel border bg-surface p-3 ${issueCount > 0 ? 'border-danger' : 'border-border'}`}>
      <div className="flex items-start gap-2">
        <Input label="Name" className="min-w-0 flex-1" value={kpi.name} error={err(`${path}/name`)} onChange={(e) => setKpi(i, { name: e.target.value })} onBlur={commitText} />
        <Input label="Unit" className="w-24" placeholder="None" value={kpi.unit ?? ''} error={err(`${path}/unit`)} onChange={(e) => setKpi(i, { unit: e.target.value === '' ? null : e.target.value })} onBlur={commitText} />
        <RemoveButton label={`Remove KPI ${label}`} className="mt-5" onClick={onRemove} />
      </div>
      <Input label="Description" value={kpi.description} error={err(`${path}/description`)} onChange={(e) => setKpi(i, { description: e.target.value })} onBlur={commitText} />
      <fieldset className="min-w-0">
        <legend className="sr-only">Definition</legend>
        <div className="flex items-center gap-3">
          <span aria-hidden="true" className="text-label font-medium text-text">Definition</span>
          <div className="inline-flex rounded-control border border-border-strong p-0.5">
            {(['measure', 'ratio'] as const).map((value) => (
              <label key={value} className="relative">
                <input type="radio" name={`${uid}-kpi-${i}-mode`} value={value} checked={mode === value} onChange={() => switchMode(i, value)} className="peer sr-only" />
                <span className="flex h-7 cursor-pointer items-center rounded-control px-3 text-label font-medium text-text-muted transition-colors hover:text-text peer-checked:bg-primary peer-checked:text-on-primary peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-focus peer-disabled:cursor-not-allowed peer-disabled:opacity-50">
                  {value === 'measure' ? 'Measure' : 'Ratio of KPIs'}
                </span>
              </label>
            ))}
          </div>
        </div>
        {kpi.measure && (
          <div className="mt-2 grid grid-cols-2 gap-2">
            <SelectField
              label="Field"
              value={kpi.measure.field}
              error={err(`${path}/measure/field`)}
              onChange={(e) => {
                const field = e.target.value;
                setKpi(i, { measure: { field, agg: aggAfterFieldChange(kpi.measure!.agg, typeOf(field)) } }, true);
              }}
            >
              <FieldChoices fields={fields} current={kpi.measure.field} />
            </SelectField>
            <SelectField label="Aggregation" value={kpi.measure.agg} error={err(`${path}/measure/agg`)} onChange={(e) => setKpi(i, { measure: { ...kpi.measure!, agg: e.target.value as NonNullable<Kpi['measure']>['agg'] } }, true)}>
              {(aggs.includes(kpi.measure.agg) ? aggs : [kpi.measure.agg, ...aggs]).map((agg) => (
                <option key={agg} value={agg}>{AGG_LABELS[agg]}</option>
              ))}
            </SelectField>
          </div>
        )}
        {kpi.ratio && (
          <div className="mt-2 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-start gap-2">
            <SelectField label="Numerator" value={kpi.ratio.numerator} error={err(`${path}/ratio/numerator`)} onChange={(e) => setKpi(i, { ratio: { ...kpi.ratio!, numerator: e.target.value } }, true)}>
              <KpiChoices kpis={others} current={kpi.ratio.numerator} />
            </SelectField>
            <span aria-hidden="true" className="mt-7 text-body text-text-muted">÷</span>
            <SelectField label="Denominator" value={kpi.ratio.denominator} error={err(`${path}/ratio/denominator`)} onChange={(e) => setKpi(i, { ratio: { ...kpi.ratio!, denominator: e.target.value } }, true)}>
              <KpiChoices kpis={others} current={kpi.ratio.denominator} />
            </SelectField>
          </div>
        )}
      </fieldset>
      <p className="mt-auto flex items-baseline justify-between gap-2 border-t border-border pt-2">
        <code className="min-w-0 truncate font-mono text-label text-text" title={formula(kpi)}>{formula(kpi)}</code>
        <code className={`${mono} shrink-0`}>{kpi.id}</code>
      </p>
      <IssueList issues={cardIssues} />
    </section>
  );
}

/** Columns and derived fields, each with its type; a value no longer listed stays visible as unknown. */
function FieldChoices({ fields, current }: { fields: FieldOption[]; current: string }) {
  const base = fields.filter((f) => !f.derived);
  const derived = fields.filter((f) => f.derived);
  return (
    <>
      {!fields.some((f) => f.name === current) && <option value={current}>{current ? `${current} (unknown)` : 'Pick a field'}</option>}
      <optgroup label="Columns">
        {base.map((f) => <option key={f.name} value={f.name}>{f.name} · {f.type}</option>)}
      </optgroup>
      {derived.length > 0 && (
        <optgroup label="Derived fields">
          {derived.map((f) => <option key={f.name} value={f.name}>{f.name} · {f.type}</option>)}
        </optgroup>
      )}
    </>
  );
}

function KpiChoices({ kpis, current }: { kpis: Kpi[]; current: string }) {
  return (
    <>
      {!kpis.some((k) => k.id === current) && <option value={current}>{current ? `${current} (unknown)` : 'Pick a KPI'}</option>}
      {kpis.map((k) => <option key={k.id} value={k.id}>{k.name || k.id}</option>)}
    </>
  );
}

function RemoveButton({ label, onClick, className = '' }: { label: string; onClick: () => void; className?: string }) {
  return <Button size="sm" variant="ghost" icon={<Trash2 aria-hidden="true" />} aria-label={label} title={label} className={`shrink-0 ${className}`} onClick={onClick} />;
}

function TableHead({ labels }: { labels: string[] }) {
  return (
    <thead>
      <tr>
        {labels.map((l, i) => (
          <th key={i} scope="col" className="px-2 pb-1 text-left text-caption font-medium text-text-muted">
            {l || <span className="sr-only">Actions</span>}
          </th>
        ))}
      </tr>
    </thead>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="px-1 py-2 text-body text-text-muted">{children}</p>;
}

function Collapsible({
  title,
  count,
  issues,
  addLabel,
  onAdd,
  list,
  listIssues,
  children,
}: {
  title: string;
  count: number;
  issues: number;
  addLabel: string;
  onAdd: () => void;
  list: string;
  listIssues: ValidationIssue[] | undefined;
  children: ReactNode;
}) {
  return (
    <details open className="group mt-4 rounded-panel border border-border bg-surface">
      <summary className={`flex cursor-pointer items-center gap-2 rounded-panel px-3 py-2 ${focusRing}`}>
        <span className="text-title font-semibold text-text">{title}</span>
        <span className="text-label text-text-muted tabular-nums">{count}</span>
        {issues > 0 && <span className="text-label font-medium text-danger">{issues === 1 ? '1 issue' : `${issues} issues`}</span>}
      </summary>
      <div className="border-t border-border px-2 pt-1 pb-2">
        <IssueList issues={listIssues} className="px-1 py-1" />
        {children}
        <Button size="sm" variant="ghost" icon={<Plus aria-hidden="true" />} data-add={list} className="mt-1" onClick={onAdd}>
          {addLabel}
        </Button>
      </div>
    </details>
  );
}
