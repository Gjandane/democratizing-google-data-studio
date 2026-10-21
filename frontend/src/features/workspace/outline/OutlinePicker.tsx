// The Outline stage's picker (docs/staged-ui.md): one collapsible group per section with its
// questions as checkbox rows. Ticking saves the selection at once with PUT outline/selection;
// Suggest more and Other start a run, and their questions arrive through artifact.updated.
import { ChevronRight, Plus, Sparkles } from 'lucide-react';
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { api } from '../../../api/client';
import { ApiError, type Build, type Outline, type OutlineQuestion, type OutlineSection, type QuestionSelection, type RunAccepted } from '../../../api/types';
import { Button } from '../../../components/Button';
import { ErrorState } from '../../../components/ErrorState';
import { TextArea } from '../../../components/Input';
import { focusRing } from '../../../components/focus';

/** Longest Other text the server takes (api.md 2.0, outline/other). */
export const MAX_OTHER = 1000;
/** The key of the new-section Other box. */
const NEW_SECTION = '';
/** How long controls wait for an accepted run's `run.started` before giving up (a missed event). */
export const AWAIT_RUN_MS = 30_000;

const chip = 'inline-flex h-5 items-center rounded-full px-2 text-caption';
const ORIGIN: Record<OutlineQuestion['origin'], string | null> = { proposed: null, suggested: 'Suggested', other: 'Added by you' };

const errorText = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);
const count = (n: number) => n.toLocaleString('en-US');

/** Selected questions, with the user's unsaved ticks over the server's. */
export function selectedCount(outline: Outline, overrides: ReadonlyMap<string, boolean> = new Map()): number {
  return outline.sections.reduce((n, s) => n + s.questions.filter((q) => overrides.get(q.id) ?? q.selected).length, 0);
}

/** The Other box's check: blank or over the limit can't be sent. */
function otherProblem(text: string): string | null {
  if (text.length > MAX_OTHER) return `${count(text.length)} / ${count(MAX_OTHER)} characters. Remove ${count(text.length - MAX_OTHER)} to add it.`;
  return null;
}

export function OutlinePicker({
  build,
  outline,
  disabled,
  onSaved,
  onSavingChange,
  onCountChange,
  startedRuns,
}: {
  build: Build;
  /** The latest Outline from the server. */
  outline: Outline;
  /** A run holds the build's lock, or the build is past editing. */
  disabled: boolean;
  onSaved: (outline: Outline) => void;
  /** True while a save or an action request runs, or after a save failed. */
  onSavingChange: (saving: boolean) => void;
  /** The selected count the user sees, unsaved ticks included. */
  onCountChange: (count: number) => void;
  /** Run ids the activity has seen start: an accepted Suggest/Other waits for its own. */
  startedRuns: readonly string[];
}) {
  const uid = useId();
  // Ticks not yet stored: shown over the server's copy until a PUT stores them.
  const [overrides, setOverrides] = useState<ReadonlyMap<string, boolean>>(new Map());
  const [saveError, setSaveError] = useState<string | null>(null);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [action, setAction] = useState<string | null>(null);
  // The run of an accepted Suggest/Other, until it starts: the server already holds the lock.
  const [awaitRun, setAwaitRun] = useState<string | null>(null);
  // An Other text the server accepted: cleared once a newer outline lands, kept if the run fails.
  const [sent, setSent] = useState<{ box: string; text: string; revision: number } | null>(null);
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({});
  const [kpiNames, setKpiNames] = useState<ReadonlyMap<string, string>>(new Map());
  const unsent = useRef(new Map<string, boolean>());
  const inFlight = useRef(false);
  const failed = useRef(false);
  const acting = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // KPI chips show the confirmed context's names; without it they show the ids.
  useEffect(() => {
    let active = true;
    api.getContext(build.id).then(
      (context) => {
        if (active && context) setKpiNames(new Map(context.kpis.map((k) => [k.id, k.name.trim() || k.id])));
      },
      () => {},
    );
    return () => {
      active = false;
    };
  }, [build.id]);

  // Matched by run_id, never by node; a run.started missed while the stream was down times out.
  const awaiting = awaitRun !== null && !startedRuns.includes(awaitRun);
  useEffect(() => {
    if (awaitRun !== null && startedRuns.includes(awaitRun)) setAwaitRun(null);
  }, [awaitRun, startedRuns]);
  useEffect(() => {
    if (awaitRun === null) return;
    const timer = setTimeout(() => setAwaitRun(null), AWAIT_RUN_MS);
    return () => clearTimeout(timer);
  }, [awaitRun]);
  useEffect(() => {
    if (!sent || outline.revision <= sent.revision) return;
    setTexts((current) => (current[sent.box] === sent.text ? { ...current, [sent.box]: '' } : current));
    setSent(null);
  }, [outline.revision, sent]);

  // The footer's count and Confirm follow what the user sees, before paint.
  const shown = selectedCount(outline, overrides);
  useLayoutEffect(() => onCountChange(shown), [shown, onCountChange]);

  const report = () => onSavingChange(inFlight.current || failed.current || acting.current);

  const save = async (): Promise<void> => {
    if (inFlight.current || unsent.current.size === 0) return;
    const body: QuestionSelection[] = [...unsent.current].map(([id, selected]) => ({ id, selected }));
    unsent.current.clear();
    inFlight.current = true;
    report();
    try {
      const saved = await api.updateOutlineSelection(build.id, body);
      if (!mounted.current) return;
      failed.current = false;
      setSaveError(null);
      // A tick made again while this PUT ran stays shown until its own PUT lands.
      setOverrides((current) => {
        const next = new Map(current);
        for (const { id } of body) if (!unsent.current.has(id)) next.delete(id);
        return next;
      });
      onSaved(saved);
    } catch (error) {
      if (!mounted.current) return;
      failed.current = true;
      for (const { id, selected } of body) if (!unsent.current.has(id)) unsent.current.set(id, selected);
      setSaveError(errorText(error, "Couldn't save your selection. Try again."));
    } finally {
      inFlight.current = false;
      if (mounted.current) {
        report();
        if (!failed.current) void save();
      }
    }
  };

  const toggle = (question: OutlineQuestion, selected: boolean) => {
    unsent.current.set(question.id, selected);
    setOverrides((current) => new Map(current).set(question.id, selected));
    void save();
  };

  /** Starts a run; `other` names the Other box whose text the run turns into questions. */
  const run = async (key: string, start: () => Promise<RunAccepted>, fallback: string, other?: { box: string; text: string }) => {
    if (acting.current || inFlight.current || failed.current) return;
    acting.current = true;
    setAction(key);
    setActionErrors(({ [key]: _gone, ...rest }) => rest);
    report();
    try {
      const { run_id } = await start();
      if (mounted.current) {
        setAwaitRun(run_id);
        if (other) setSent({ ...other, revision: outline.revision });
      }
    } catch (error) {
      if (mounted.current) setActionErrors((current) => ({ ...current, [key]: errorText(error, fallback) }));
    } finally {
      acting.current = false;
      if (mounted.current) {
        setAction(null);
        report();
      }
    }
  };

  const suggest = (section: OutlineSection) =>
    void run(`suggest:${section.id}`, () => api.suggestOutlineQuestions(build.id, section.id), "Couldn't ask for more questions. Try again.");
  const addOther = (sectionId: string) => {
    const text = texts[sectionId] ?? '';
    if (text.trim() === '' || otherProblem(text)) return;
    void run(`other:${sectionId}`, () => api.addOutlineQuestions(build.id, sectionId === NEW_SECTION ? null : sectionId, text), "Couldn't add your question. Try again.", { box: sectionId, text });
  };

  const locked = disabled || action !== null || awaiting;
  const blocked = locked || saveError !== null;

  const otherBox = (sectionId: string, label: string, buttonLabel: string, placeholder: string, extra?: ReactNode) => {
    const text = texts[sectionId] ?? '';
    const problem = otherProblem(text);
    const key = `other:${sectionId}`;
    return (
      <div className="flex flex-col gap-2">
        <TextArea
          label={label}
          rows={2}
          value={text}
          error={problem}
          hint={`${count(text.length)} / ${count(MAX_OTHER)} characters`}
          placeholder={placeholder}
          onChange={(e) => {
            const value = e.target.value;
            setTexts((current) => ({ ...current, [sectionId]: value }));
          }}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" icon={<Plus aria-hidden="true" />} disabled={blocked || text.trim() === '' || problem !== null} loading={action === key} onClick={() => addOther(sectionId)}>
            {buttonLabel}
          </Button>
          {extra}
        </div>
        {actionErrors[key] && (
          <p role="alert" className="text-caption text-danger">
            {actionErrors[key]}
          </p>
        )}
      </div>
    );
  };

  return (
    <div className="mt-4">
      {saveError && (
        <ErrorState className="mb-4" title="Couldn't save your selection" message={`${saveError} Your ticks are kept here.`} onRetry={disabled ? undefined : () => { failed.current = false; void save(); }} retryLabel="Save again" />
      )}
      <fieldset disabled={locked} className="min-w-0 space-y-3">
        <legend className="sr-only">Questions</legend>
        {outline.sections.map((section) => {
          const picked = section.questions.filter((q) => overrides.get(q.id) ?? q.selected).length;
          const suggestKey = `suggest:${section.id}`;
          return (
            <details key={section.id} open className="group rounded-panel border border-border bg-surface">
              <summary className={`flex cursor-pointer items-center gap-2 rounded-panel px-3 py-2 ${focusRing}`}>
                <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-text-muted transition-transform group-open:rotate-90 motion-reduce:transition-none" />
                <span className="min-w-0 text-title font-semibold text-text [overflow-wrap:anywhere]">{section.title}</span>
                <span className="ml-auto shrink-0 text-label text-text-muted tabular-nums">
                  {picked} of {section.questions.length} selected
                </span>
              </summary>
              <fieldset className="min-w-0 border-t border-border" aria-describedby={`${uid}-${section.id}-purpose`}>
                <legend className="sr-only">{section.title}</legend>
                <p id={`${uid}-${section.id}-purpose`} className="px-3 pt-2 text-label text-text-muted">
                  {section.purpose}
                </p>
                {section.questions.length === 0 ? (
                  <p className="px-3 py-2 text-body text-text-muted">No questions here yet. Suggest some or add your own.</p>
                ) : (
                  <ul className="py-1">
                    {section.questions.map((q) => (
                      <QuestionRow key={q.id} id={`${uid}-${q.id}`} question={q} selected={overrides.get(q.id) ?? q.selected} kpiNames={kpiNames} onToggle={toggle} />
                    ))}
                  </ul>
                )}
                <div className="border-t border-border px-3 py-2.5">
                  {otherBox(
                    section.id,
                    `Your own question for ${section.title}`,
                    'Add question',
                    'Which customers order again within 30 days?',
                    <Button size="sm" variant="ghost" icon={<Sparkles aria-hidden="true" />} disabled={blocked} loading={action === suggestKey} onClick={() => suggest(section)}>
                      Suggest more
                    </Button>,
                  )}
                  {actionErrors[suggestKey] && (
                    <p role="alert" className="mt-2 text-caption text-danger">
                      {actionErrors[suggestKey]}
                    </p>
                  )}
                </div>
              </fieldset>
            </details>
          );
        })}
        <section aria-labelledby={`${uid}-new`} className="rounded-panel border border-dashed border-border-strong px-3 py-2.5">
          <h3 id={`${uid}-new`} className="mb-1 text-title font-semibold text-text">
            Add a section
          </h3>
          {otherBox(NEW_SECTION, 'Questions for a new section', 'Add section', 'Returns: which products come back most, and why?')}
        </section>
      </fieldset>
    </div>
  );
}

function QuestionRow({
  id,
  question,
  selected,
  kpiNames,
  onToggle,
}: {
  id: string;
  question: OutlineQuestion;
  selected: boolean;
  kpiNames: ReadonlyMap<string, string>;
  onToggle: (question: OutlineQuestion, selected: boolean) => void;
}) {
  const origin = ORIGIN[question.origin];
  return (
    <li data-question={question.id} className="flex items-start gap-2.5 px-3 py-1.5 hover:bg-surface-muted">
      <input
        id={id}
        type="checkbox"
        checked={selected}
        aria-describedby={`${id}-meta`}
        onChange={(e) => onToggle(question, e.target.checked)}
        className={`mt-0.5 size-4 shrink-0 cursor-pointer accent-primary disabled:cursor-not-allowed ${focusRing}`}
      />
      <div className="min-w-0 flex-1">
        <label htmlFor={id} className="block cursor-pointer text-body text-text [overflow-wrap:anywhere]">
          {question.text}
        </label>
        <div id={`${id}-meta`} className="mt-1 flex flex-wrap items-center gap-1.5">
          {question.recommended && <span className={`${chip} bg-primary-soft font-medium text-primary`}>Recommended</span>}
          {origin && <span className={`${chip} bg-surface-muted text-text`}>{origin}</span>}
          {question.kpi_refs.length > 0 && (
            <>
              <span className="sr-only">KPIs:</span>
              {question.kpi_refs.map((ref) => (
                <span key={ref} className={`${chip} border border-border text-text-muted`}>
                  {kpiNames.get(ref) ?? ref}
                </span>
              ))}
            </>
          )}
          <span className="text-caption text-text-muted [overflow-wrap:anywhere]">{question.rationale}</span>
        </div>
      </div>
    </li>
  );
}
