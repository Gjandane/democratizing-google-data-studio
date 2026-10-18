import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { ApiError, ARCHETYPES, MODES, type Archetype, type Mode } from '../../api/types';
import { Button } from '../../components/Button';
import { focusRing } from '../../components/focus';
import { Input } from '../../components/Input';
import { Modal } from '../../components/Modal';

export const ARCHETYPE_INFO: Record<Archetype, { label: string; description: string }> = {
  executive: { label: 'Executive', description: 'Headline KPIs at a glance.' },
  storytelling: { label: 'Storytelling', description: 'A guided narrative, page by page.' },
  operational: { label: 'Operational', description: 'Live monitoring of day-to-day metrics.' },
  analytical: { label: 'Analytical', description: 'Filters and drill-down to explore.' },
};

const MODE_INFO: Record<Mode, { label: string; hint: string }> = {
  data: { label: 'Data', hint: 'Build from your own CSV files or tables.' },
  research: { label: 'Research', hint: 'Start from a topic the assistant researches.' },
};

const card =
  'flex h-full cursor-pointer flex-col gap-0.5 rounded-panel border border-border-strong bg-surface p-3 transition-[border-color,background-color] hover:border-text-muted peer-checked:border-primary peer-checked:bg-primary-soft peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-focus peer-disabled:cursor-not-allowed peer-disabled:opacity-50 peer-disabled:hover:border-border-strong';

export function NewBuildDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [title, setTitle] = useState('');
  const [archetype, setArchetype] = useState<Archetype | null>(null);
  const [mode, setMode] = useState<Mode>('data');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!archetype || busy) return;
    setBusy(true);
    setError(null);
    try {
      const trimmed = title.trim();
      const build = await api.createBuild({ ...(trimmed ? { title: trimmed } : {}), archetype, mode });
      onClose();
      navigate(`/builds/${encodeURIComponent(build.id)}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't create the build. Try again.");
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={() => {
        if (!busy) onClose();
      }}
      title="New build"
      description="Pick the kind of dashboard to build."
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} disabled={!archetype} onClick={() => void submit()}>
            Create build
          </Button>
        </>
      }
    >
      <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-4">
        <Input label="Title (optional)" placeholder="Untitled dashboard" value={title} onChange={(e) => setTitle(e.target.value)} disabled={busy} />

        <fieldset className="flex flex-col gap-2" disabled={busy}>
          <legend className="mb-1 text-label font-medium text-text">Dashboard type</legend>
          <div className="grid grid-cols-2 gap-2">
            {ARCHETYPES.map((value) => (
              <label key={value} className="relative block">
                <input
                  type="radio"
                  name="archetype"
                  value={value}
                  checked={archetype === value}
                  onChange={() => setArchetype(value)}
                  className="peer sr-only"
                />
                <span className={card}>
                  <span className="text-body font-medium text-text">{ARCHETYPE_INFO[value].label}</span>
                  <span className="text-caption text-text-muted">{ARCHETYPE_INFO[value].description}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset className="flex flex-col gap-2" disabled={busy}>
          <legend className="mb-1 text-label font-medium text-text">Mode</legend>
          <div className="flex flex-col gap-2">
            {MODES.map((value) => (
              <label key={value} className="flex cursor-pointer items-start gap-2 rounded-control p-1 transition-colors hover:bg-surface-muted has-disabled:cursor-not-allowed has-disabled:opacity-50 has-disabled:hover:bg-surface">
                <input
                  type="radio"
                  name="mode"
                  value={value}
                  checked={mode === value}
                  onChange={() => setMode(value)}
                  className={`mt-0.5 size-4 accent-primary ${focusRing}`}
                />
                <span>
                  <span className="block text-body font-medium text-text">{MODE_INFO[value].label}</span>
                  <span className="block text-caption text-text-muted">{MODE_INFO[value].hint}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        {error && (
          <p role="alert" className="rounded-control border border-danger bg-danger-soft px-3 py-2 text-body text-text">
            {error}
          </p>
        )}
      </form>
    </Modal>
  );
}
