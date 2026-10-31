import { Link, Route, Routes, useParams } from 'react-router-dom';
import { buttonClass } from './components/Button';
import { EmptyState } from './components/EmptyState';
import { AccessGate } from './features/access/AccessGate';
import { HomeRoute, WelcomeRoute } from './features/onboarding/LandingPage';
import { OnboardingSeenProvider } from './features/onboarding/seen';
import { AppServicesProvider, useAppServices } from './features/settings/AppServices';
import { HostingProvider } from './features/workspace/build/hosting';
import { WorkspaceShell } from './features/workspace/WorkspaceShell';

function NotFound() {
  return (
    <main className="mx-auto w-full max-w-(--layout-page) px-6 py-8">
      <EmptyState
        framed
        headingLevel={1}
        title="Page not found"
        description="This address doesn't match a page in the app."
        action={
          <Link to="/" className={buttonClass('primary')}>
            Go to your dashboards
          </Link>
        }
      />
    </main>
  );
}

function WorkspaceRoute() {
  const { id } = useParams();
  const { openSettings, openTrace } = useAppServices();
  return <WorkspaceShell onOpenTrace={(runId) => openTrace(id, runId)} onOpenSettings={openSettings} />;
}

export function App() {
  return (
    <AccessGate>
      <AppServicesProvider>
        <HostingProvider>
          <OnboardingSeenProvider>
            <Routes>
              <Route path="/" element={<HomeRoute />} />
              <Route path="/welcome" element={<WelcomeRoute />} />
              <Route path="/builds/:id" element={<WorkspaceRoute />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </OnboardingSeenProvider>
        </HostingProvider>
      </AppServicesProvider>
    </AccessGate>
  );
}
