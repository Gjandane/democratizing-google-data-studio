import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api } from '../../api/client';
import type { Settings } from '../../api/types';
import { TraceModal } from '../trace/TraceModal';
import { ServiceBanner } from './ServiceBanner';
import { SettingsModal } from './SettingsModal';
import { onServiceError, type ServiceError } from './serviceNotice';

interface AppServices {
  openSettings: () => void;
  /** With a build id the table starts on that build's runs. */
  openTrace: (buildId?: string) => void;
}

const Services = createContext<AppServices | null>(null);

export function useAppServices(): AppServices {
  const services = useContext(Services);
  if (!services) throw new Error('useAppServices needs an <AppServices> above it.');
  return services;
}

interface Notice {
  title: string;
  message: string;
}

const SERVICE_TITLES: Record<ServiceError['code'], string> = {
  llm_unavailable: "The planner isn't available.",
  gcp_not_configured: "Google Cloud isn't set up.",
};

/** What is missing from the backend's settings, if anything. */
function missingNotice(settings: Settings | null): Notice | null {
  if (!settings) return null;
  const noKey = !settings.google_api_key_set;
  const noProject = settings.gcp_project_id.trim() === '';
  if (noKey && noProject) return { title: 'Finish setup.', message: 'Add your Google API key and GCP project in Settings to plan and build dashboards.' };
  if (noKey) return { title: 'Add your API key.', message: 'The planner needs a Google API key. Add it in Settings.' };
  if (noProject) return { title: 'Set your GCP project.', message: 'Data is loaded into BigQuery. Set the GCP project in Settings.' };
  return null;
}

/**
 * The Settings and Trace dialogs plus the banner that sends the user to Settings: when the key or
 * project is missing, or when any API call answers 503 `llm_unavailable` / `gcp_not_configured`.
 */
export function AppServicesProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [failure, setFailure] = useState<Notice | null>(null);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [trace, setTrace] = useState<{ buildId?: string } | null>(null);

  useEffect(() => {
    let active = true;
    // A failed read leaves the banner off: the next call that needs the settings reports the cause.
    api.getSettings().then(
      (loaded) => {
        if (active) setSettings(loaded);
      },
      () => {},
    );
    return () => {
      active = false;
    };
  }, []);

  useEffect(
    () =>
      onServiceError((error) => {
        setDismissed(null);
        setFailure({ title: SERVICE_TITLES[error.code], message: error.message });
      }),
    [],
  );

  const services = useMemo<AppServices>(
    () => ({ openSettings: () => setSettingsOpen(true), openTrace: (buildId) => setTrace({ buildId }) }),
    [],
  );

  const onSaved = useCallback((saved: Settings) => {
    setSettings(saved);
    setFailure(null);
    setDismissed(null);
  }, []);

  const notice = failure ?? missingNotice(settings);
  const shown = notice && notice.message !== dismissed ? notice : null;

  return (
    <Services.Provider value={services}>
      <div className="flex h-dvh flex-col">
        {shown && (
          <ServiceBanner
            title={shown.title}
            message={shown.message}
            onOpenSettings={services.openSettings}
            onDismiss={() => setDismissed(shown.message)}
          />
        )}
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
      {settingsOpen && <SettingsModal open onClose={() => setSettingsOpen(false)} onSaved={onSaved} />}
      {trace && <TraceModal open onClose={() => setTrace(null)} buildId={trace.buildId} />}
    </Services.Provider>
  );
}
