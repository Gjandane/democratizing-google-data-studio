import { ArrowRight, Plus } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { Button } from '../../components/Button';
import { DashboardsLoading, HistoryPage } from '../history/HistoryPage';
import { NewBuildDialog } from '../history/NewBuildDialog';
import { useHostingLoad } from '../workspace/build/hosting';
import { HowItWorks } from './HowItWorks';
import { useOnboardingSeen } from './seen';

/** The captures in public/onboarding/ are 1280x800 viewports (docs/onboarding-ui.md#Screenshot assets). */
const SHOT_WIDTH = 1280;
const SHOT_HEIGHT = 800;

const SHOTS = [
  {
    file: 'context.webp',
    title: 'Review the context',
    caption: 'Confirm the KPIs and questions drafted from your data.',
    alt: 'The Context stage with KPI cards to confirm',
  },
  {
    file: 'prototype.webp',
    title: 'Comment on the prototype',
    caption: 'Click any chart to leave a comment, then apply them all at once.',
    alt: 'The Prototype stage with numbered comment pins',
  },
  {
    file: 'build.webp',
    title: 'Watch the build',
    caption: 'Each step ticks off live while the agent builds the report.',
    alt: 'The Build stage with recipe steps ticking off',
  },
  {
    file: 'done.webp',
    title: 'Open your report',
    caption: 'The finished dashboard opens in your own Data Studio.',
    alt: 'The Done stage with the link to the report in Data Studio',
  },
];

const badge = 'flex size-6 shrink-0 items-center justify-center rounded-full bg-primary text-caption font-semibold text-on-primary';

/** The first-visit landing page at `/welcome`, agent mode only (docs/onboarding-ui.md#Landing layout). */
export function LandingPage({ shareData }: { shareData: boolean }) {
  const navigate = useNavigate();
  const { markSeen } = useOnboardingSeen();
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const previous = document.title;
    document.title = 'How it works - Data Studio builder';
    return () => {
      document.title = previous;
    };
  }, []);

  const start = () => {
    markSeen();
    setCreating(true);
  };

  const proceed = () => {
    markSeen();
    navigate('/');
  };

  return (
    <main className="mx-auto flex w-full max-w-(--layout-page) flex-col gap-8 px-6 py-8">
      <header>
        <p className="text-label font-semibold text-primary">Democratizing Google Data Studio</p>
        <h1 className="mt-2 text-display font-semibold text-text">Turn your data into a Google Data Studio dashboard</h1>
        <p className="mt-2 text-title text-text-muted">
          Design it here step by step. Then a small agent on your computer builds it in your own Data Studio account.
        </p>
        <div className="mt-4 flex items-center gap-3">
          <Button variant="primary" icon={<Plus aria-hidden="true" />} onClick={start}>
            Start a new dashboard
          </Button>
        </div>
      </header>
      {/* Mounted only while open, so each new build starts from a blank form. */}
      {creating && <NewBuildDialog open onClose={() => setCreating(false)} />}

      <section aria-labelledby="landing-shots-heading">
        <h2 id="landing-shots-heading" className="text-heading font-semibold text-text">
          See it in action
        </h2>
        <ol className="mt-4 grid grid-cols-2 gap-4">
          {SHOTS.map((shot, index) => (
            <li key={shot.file}>
              <figure className="flex h-full flex-col gap-3">
                <img
                  src={`/onboarding/${shot.file}`}
                  alt={shot.alt}
                  width={SHOT_WIDTH}
                  height={SHOT_HEIGHT}
                  loading="lazy"
                  decoding="async"
                  className="block h-auto w-full rounded-panel border border-border bg-surface"
                />
                <figcaption className="flex items-start gap-3">
                  <span aria-hidden="true" className={badge}>
                    {index + 1}
                  </span>
                  <span className="flex min-w-0 flex-col">
                    <span className="text-body font-semibold text-text">{shot.title}</span>
                    <span className="text-label text-text-muted">{shot.caption}</span>
                  </span>
                </figcaption>
              </figure>
            </li>
          ))}
        </ol>
      </section>

      <HowItWorks shareData={shareData} />

      <div className="-mt-2 flex justify-end">
        <Button onClick={proceed}>
          Proceed to your dashboards
          <ArrowRight aria-hidden="true" />
        </Button>
      </div>
    </main>
  );
}

/** `/`: History, or the landing page on an agent-mode first visit. Nothing but loading shows until hosting is known. */
export function HomeRoute() {
  const load = useHostingLoad();
  const { seen } = useOnboardingSeen();
  if (load.status === 'ready' && load.hosting.mode === 'agent' && !seen) return <Navigate to="/welcome" replace />;
  return <HistoryPage hold={load.status === 'pending'} />;
}

/** `/welcome`: the landing page in agent mode; local mode and a failed hosting load go back to `/`. */
export function WelcomeRoute() {
  const load = useHostingLoad();
  if (load.status === 'pending') return <DashboardsLoading />;
  if (load.status === 'failed' || load.hosting.mode !== 'agent') return <Navigate to="/" replace />;
  return <LandingPage shareData={load.hosting.share_data} />;
}
