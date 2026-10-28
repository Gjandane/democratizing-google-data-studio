// The recreate analysis review (docs/reference-ui.md, Reference analysis review): the summary as
// the question, one row per item with its Native/Static choice and type, the note, and Approve.
// The server owns state, issues and revision; unsaved edits live here until Approve sends them.
import { useEffect, useId, useLayoutEffect, useRef, useState, type Ref } from 'react';
import { api } from '../../../api/client';
import {
  ApiError,
  type ReferenceAnalysis,
  type ReferenceDisposition,
  type ReferenceItem,
  type ReferenceItemKind,
  type ReferenceSet,
  type ValidationIssue,
} from '../../../api/types';
import { Button } from '../../../components/Button';
import { TextArea } from '../../../components/Input';
import { typeLabel } from '../blueprint/BlueprintTable';
import { SelectField } from '../context/fields';

export const MAX_NOTE = 1000;
export const CONFLICT_NOTE = 'This analysis changed in another window; review it and approve again.';
export const STALE_WARNING = 'Changing the split marks the Blueprint and prototype as out of date';

const KINDS: Record<ReferenceItemKind, string> = {
  chart: 'Chart',
  control: 'Control',
  kpi: 'KPI',
  text: 'Text',
  image: 'Image',
  legend: 'Legend',
  other: 'Other',
};

type Choice = { disposition: ReferenceDisposition; type: string | null };
type Analyzed = ReferenceSet & { analysis: ReferenceAnalysis };

const same = (a: Choice, b: Choice) => a.disposition === b.disposition && (a.disposition === 'static' || a.type === b.type);
/** The row index an issue path points into (`/items/<i>/...`), else null. */
const rowOf = (issue: ValidationIssue) => {
  const match = /^\/items\/(\d+)(\/|$)/.exec(issue.path);
  return match ? Number(match[1]) : null;
};

export function AnalysisReview({
  buildId,
  set,
  disabled,
  readOnly,
  headingRef,
  onSaved,
  onReload,
  onHighlight,
  onBusyChange,
}: {
  buildId: string;
  set: Analyzed;
  /** Another action runs (upload, a run, the brief review lock): every control here waits. */
  disabled: boolean;
  /** Build and Done: the split shows without its controls. */
  readOnly: boolean;
  /** The review heading (or the approved line), where focus goes on request. */
  headingRef: Ref<HTMLElement>;
  onSaved: (set: ReferenceSet) => void;
  onReload: () => void;
  onHighlight: (item: ReferenceItem | null) => void;
  onBusyChange: (busy: boolean) => void;
}) {
  const id = useId();
  const analysis = set.analysis;
  const [overrides, setOverrides] = useState<Record<string, Choice>>({});
  const [noteDraft, setNoteDraft] = useState<string | null>(null);
  const [editing, setEditing] = useState<'closed' | 'warning' | 'open'>('closed');
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const list = useRef<HTMLOListElement>(null);
  const editButton = useRef<HTMLButtonElement>(null);
  const continueButton = useRef<HTMLButtonElement>(null);
  const approveButton = useRef<HTMLButtonElement>(null);
  const localHeading = useRef<HTMLElement | null>(null);
  // Focus to place once the next render lands: a heading, the Edit split button, the warning or a row.
  const [focusTarget, setFocusTarget] = useState<{ to: 'heading' | 'edit' | 'continue' | 'approve' | 'row'; row?: string } | null>(null);
  const busyChange = useRef(onBusyChange);
  busyChange.current = onBusyChange;
  const highlight = useRef(onHighlight);
  highlight.current = onHighlight;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      highlight.current(null);
      // Unmounted mid-approve (another window replaced the set): the panel's controls must not stay locked.
      if (inFlight.current) busyChange.current(false);
    };
  }, []);

  const items = analysis.items.map((item) => ({ item, choice: overrides[item.id] ?? { disposition: item.disposition, type: item.type } }));
  const note = noteDraft ?? analysis.note;
  const touched = (item: ReferenceItem) => {
    const choice = overrides[item.id];
    return choice !== undefined && !same(choice, item);
  };
  const edited = analysis.items.some(touched) || note !== analysis.note;
  // A server issue stays open until the user changes what it points at; Approve then sends the change.
  const openIssues = analysis.issues.filter((issue) => {
    const row = rowOf(issue);
    if (row !== null) return !(analysis.items[row] && touched(analysis.items[row]));
    if (issue.path === '/note') return note === analysis.note;
    return true;
  });
  const rowIssues = (index: number) => analysis.issues.filter((issue) => rowOf(issue) === index);
  const noteIssue = analysis.issues.find((issue) => issue.path === '/note');
  const otherIssues = analysis.issues.filter((issue) => rowOf(issue) === null && issue.path !== '/note');
  const approved = analysis.state === 'approved';
  const showRows = !readOnly && (!approved || editing === 'open');
  const locked = disabled || saving;
  // Rows that unmount (approved, collapsed) leave no box behind on the image.
  const active = showRows ? (focused ?? hovered) : null;
  const activeItem = analysis.items.find((item) => item.id === active) ?? null;
  useEffect(() => highlight.current(activeItem), [activeItem]);

  useLayoutEffect(() => {
    if (!focusTarget) return;
    setFocusTarget(null);
    if (focusTarget.to === 'heading') localHeading.current?.focus();
    else if (focusTarget.to === 'edit') editButton.current?.focus();
    else if (focusTarget.to === 'continue') continueButton.current?.focus();
    else if (focusTarget.to === 'approve') (approveButton.current?.disabled ? localHeading.current : approveButton.current)?.focus();
    else list.current?.querySelector<HTMLInputElement>(`[data-item="${focusTarget.row}"] input:checked`)?.focus();
  }, [focusTarget]);

  const setHeading = (el: HTMLElement | null) => {
    localHeading.current = el;
    if (typeof headingRef === 'function') headingRef(el);
    else if (headingRef) headingRef.current = el;
  };

  const choose = (item: ReferenceItem, next: Choice) => {
    setConflict(false);
    setOverrides((current) => ({ ...current, [item.id]: next }));
  };
  const reset = (item: ReferenceItem) => {
    choose(item, { ...item.proposed });
    setFocusTarget({ to: 'row', row: item.id });
  };

  const approve = async () => {
    if (inFlight.current || locked || openIssues.length > 0) return;
    inFlight.current = true;
    setSaving(true);
    busyChange.current(true);
    setConflict(false);
    setError(null);
    try {
      let current: ReferenceSet = set;
      if (edited) {
        current = await api.updateReferenceAnalysis(buildId, {
          revision: analysis.revision,
          items: items.map(({ item, choice }) => ({ id: item.id, disposition: choice.disposition, type: choice.disposition === 'native' ? choice.type : null })),
          note,
        });
        if (!mounted.current) return;
        setOverrides({});
        setNoteDraft(null);
        onSaved(current);
        // The server found issues in the saved split: they show on their rows, and approval waits.
        if (!current.analysis || current.analysis.issues.length > 0) {
          const row = current.analysis?.issues.map(rowOf).find((i): i is number => i !== null);
          const item = row === undefined ? undefined : current.analysis?.items[row];
          setFocusTarget(item ? { to: 'row', row: item.id } : { to: 'heading' });
          return;
        }
      }
      const result = await api.approveReferenceAnalysis(buildId, current.analysis!.revision);
      if (!mounted.current) return;
      onSaved(result);
      setEditing('closed');
      setFocused(null);
      setHovered(null);
      setFocusTarget({ to: 'heading' });
    } catch (reason) {
      if (!mounted.current) return;
      if (reason instanceof ApiError && reason.code === 'reference_analysis_conflict') setConflict(true);
      else setError(reason instanceof ApiError ? reason.message : "Couldn't approve the analysis. Try again.");
      // The button was disabled while saving, which dropped focus: put it back.
      setFocusTarget({ to: 'approve' });
      // The server holds the current revision and issues: read them; unsaved edits stay.
      onReload();
    } finally {
      inFlight.current = false;
      if (mounted.current) {
        setSaving(false);
        busyChange.current(false);
      }
    }
  };

  const discard = () => {
    setOverrides({});
    setNoteDraft(null);
    setConflict(false);
    setError(null);
    setEditing('closed');
    setFocusTarget({ to: 'edit' });
  };

  const native = analysis.items.filter((item) => item.disposition === 'native').length;
  if (approved && !showRows) {
    return (
      <div className="flex min-w-0 flex-col gap-2 rounded-control border border-border bg-surface-muted px-3 py-2">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
          <p ref={setHeading} tabIndex={-1} className="min-w-0 flex-1 rounded-control text-body font-medium text-text outline-none">
            Approved: {native} native, {analysis.items.length - native} static
          </p>
          {!readOnly && editing === 'closed' && (
            <Button ref={editButton} size="sm" variant="secondary" disabled={disabled} onClick={() => { setEditing('warning'); setFocusTarget({ to: 'continue' }); }}>
              Edit split
            </Button>
          )}
        </div>
        {editing === 'warning' && (
          <div role="group" aria-labelledby={`${id}-warning`} className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2 rounded-control border border-accent bg-surface px-3 py-2">
            <p id={`${id}-warning`} className="min-w-0 flex-1 text-body text-text">{STALE_WARNING}.</p>
            <Button ref={continueButton} size="sm" variant="primary" disabled={disabled} onClick={() => { setEditing('open'); setFocusTarget({ to: 'heading' }); }}>
              Continue
            </Button>
            <Button size="sm" variant="ghost" onClick={() => { setEditing('closed'); setFocusTarget({ to: 'edit' }); }}>
              Cancel
            </Button>
          </div>
        )}
      </div>
    );
  }

  return (
    <section aria-labelledby={`${id}-question`} className="flex min-w-0 flex-col gap-3 rounded-control border border-border bg-surface-muted p-3">
      <div>
        <h3 ref={setHeading} id={`${id}-question`} tabIndex={-1} className="rounded-control text-title font-semibold text-text outline-none [overflow-wrap:anywhere]">
          {analysis.summary}
        </h3>
        <p className="text-body text-text-muted">{readOnly ? 'This analysis waits for approval.' : 'Proceed?'}</p>
      </div>
      {showRows && (
        <>
          <ol ref={list} aria-label="Reference items" className="flex min-w-0 flex-col gap-2">
            {items.map(({ item, choice }, index) => {
              const changed = !same(choice, item.proposed);
              const issues = rowIssues(index);
              const issueId = issues.length > 0 ? `${id}-issue-${item.id}` : undefined;
              const typeOptions = choice.type !== null && !analysis.allowed_types.includes(choice.type) ? [choice.type, ...analysis.allowed_types] : analysis.allowed_types;
              return (
                <li
                  key={item.id}
                  data-item={item.id}
                  data-active={active === item.id || undefined}
                  onMouseEnter={() => setHovered(item.id)}
                  onMouseLeave={() => setHovered((current) => (current === item.id ? null : current))}
                  onFocus={() => setFocused(item.id)}
                  onBlur={(event) => {
                    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused((current) => (current === item.id ? null : current));
                  }}
                  className="group flex min-w-0 flex-wrap items-start justify-between gap-x-4 gap-y-2 rounded-control border border-border bg-surface px-3 py-2 data-active:border-primary"
                >
                  <div className="min-w-0 flex-1 basis-64">
                    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="min-w-0 text-body font-semibold text-text [overflow-wrap:anywhere]">{item.label}</span>
                      <span className="rounded-full bg-surface-muted px-2 text-caption text-text-muted">{KINDS[item.kind]}</span>
                      {changed && (
                        <>
                          <span className="rounded-full bg-accent px-2 text-caption font-medium text-on-accent">Changed</span>
                          <button type="button" disabled={locked} onClick={() => reset(item)} className="rounded-control text-caption font-medium text-primary underline underline-offset-2 enabled:hover:text-primary-hover disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus">
                            Reset<span className="sr-only"> {item.label} to the proposed choice</span>
                          </button>
                        </>
                      )}
                    </div>
                    {item.shows && <p title={item.shows} className="line-clamp-2 text-label text-text-muted group-focus-within:line-clamp-none [overflow-wrap:anywhere]">Shows: {item.shows}</p>}
                    <p title={item.reason} className="line-clamp-2 text-label text-text-muted group-focus-within:line-clamp-none [overflow-wrap:anywhere]">{item.reason}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <fieldset disabled={locked} aria-describedby={issueId} className="inline-flex rounded-control border border-border-strong bg-surface p-0.5">
                      <legend className="sr-only">{item.label}: native or static</legend>
                      {(['native', 'static'] as const).map((disposition) => (
                        <label
                          key={disposition}
                          className="inline-flex h-7 cursor-pointer items-center rounded-control px-2.5 text-label font-medium text-text hover:bg-surface-muted has-checked:bg-primary has-checked:text-on-primary has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-focus has-disabled:cursor-not-allowed has-disabled:opacity-50"
                        >
                          <input
                            type="radio"
                            name={`${id}-${item.id}`}
                            value={disposition}
                            checked={choice.disposition === disposition}
                            onChange={() =>
                              choose(item, {
                                disposition,
                                // Back to native keeps the type chosen before, else the saved or proposed one.
                                type: choice.type ?? item.type ?? (item.proposed.disposition === 'native' ? item.proposed.type : null),
                              })
                            }
                            className="sr-only"
                          />
                          {disposition === 'native' ? 'Native' : 'Static'}
                        </label>
                      ))}
                    </fieldset>
                    {/* Fixed width either way: switching Native/Static never moves the row. */}
                    <div className="w-48">
                      {choice.disposition === 'native' ? (
                        <SelectField
                          label={`${item.label}: component type`}
                          hideLabel
                          value={choice.type ?? ''}
                          disabled={locked}
                          aria-describedby={issueId}
                          aria-invalid={issues.length > 0 || undefined}
                          onChange={(event) => choose(item, { disposition: 'native', type: event.target.value || null })}
                          className="[&_select]:h-8"
                        >
                          {choice.type === null && (
                            <option value="" disabled>
                              Choose a type
                            </option>
                          )}
                          {typeOptions.map((type) => (
                            <option key={type} value={type}>
                              {typeLabel(type)}
                            </option>
                          ))}
                        </SelectField>
                      ) : (
                        <p className="text-label text-text-muted">Drawn as static art</p>
                      )}
                    </div>
                  </div>
                  {issues.length > 0 && (
                    <ul id={issueId} className="basis-full text-label text-danger">
                      {issues.map((issue, i) => (
                        <li key={i} className="[overflow-wrap:anywhere]">{issue.message}</li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ol>
          <TextArea
            label="Note for the planner"
            name="analysis-note"
            value={note}
            maxLength={MAX_NOTE}
            rows={2}
            disabled={locked}
            onChange={(event) => {
              setConflict(false);
              setNoteDraft(event.target.value);
            }}
            hint={`Optional. ${note.length}/${MAX_NOTE} characters.`}
            error={noteIssue?.message}
          />
          {otherIssues.length > 0 && (
            <ul aria-label="Open issues" className="text-label text-danger">
              {otherIssues.map((issue, i) => (
                <li key={i} className="[overflow-wrap:anywhere]">{issue.message}</li>
              ))}
            </ul>
          )}
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
            <Button ref={approveButton} variant="primary" loading={saving} disabled={locked || openIssues.length > 0} aria-describedby={`${id}-send`} onClick={() => void approve()}>
              Approve and continue
            </Button>
            {approved && (
              <Button variant="ghost" disabled={saving} onClick={discard}>
                Cancel
              </Button>
            )}
            <p id={`${id}-send`} className="min-w-0 text-caption text-text-muted">
              {openIssues.length > 0 ? 'Fix the issues above to approve. ' : ''}Your changes are sent when you approve.
            </p>
          </div>
          {conflict && <p role="alert" className="text-label text-danger">{CONFLICT_NOTE}</p>}
          {error && <p role="alert" className="text-label text-danger [overflow-wrap:anywhere]">{error}</p>}
        </>
      )}
    </section>
  );
}
