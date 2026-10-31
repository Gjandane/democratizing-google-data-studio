import { Globe, Laptop, LayoutDashboard, Lock, Monitor, Rocket, Users } from 'lucide-react';
import type { ReactNode } from 'react';
import { STAGES } from '../../api/types';
import { STAGE_LABELS } from '../workspace/Stepper';

const STAGE_CHIPS = STAGES.filter((stage) => stage !== 'done').map((stage) => STAGE_LABELS[stage]);

interface Step {
  icon: ReactNode;
  title: string;
  body: string;
  extra?: ReactNode;
}

const STEPS: Step[] = [
  {
    icon: <LayoutDashboard />,
    title: 'Design it here',
    body: 'Upload a CSV or a screenshot, then confirm each stage. Nothing is built until you say so.',
    extra: (
      <ul aria-label="Stages" className="mt-3 flex flex-wrap gap-1.5">
        {STAGE_CHIPS.map((label) => (
          <li key={label} className="rounded-control border border-border bg-surface px-1.5 py-0.5 text-caption text-text-muted">
            {label}
          </li>
        ))}
      </ul>
    ),
  },
  {
    icon: <Laptop />,
    title: 'Set up this computer once',
    body:
      'Building runs in Google Chrome on your computer, so the report is saved in your own Data Studio account. ' +
      'One copied command installs the build agent (a small helper and this app) and asks you to sign in to Google once in its own Chrome window. ' +
      'The first run takes a few minutes.',
  },
  {
    icon: <Rocket />,
    title: 'Build with a one-time code',
    body:
      'At Build you get a code that works for 30 minutes and one command to paste into a terminal. ' +
      'The finished report opens in Data Studio.',
  },
];

function BeforeItem({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <li className="flex items-start gap-2 text-label text-text-muted [&_strong]:font-semibold [&_strong]:text-text">
      <span aria-hidden="true" className="flex h-(--text-label--line-height) shrink-0 items-center text-text-muted [&_svg]:size-4">
        {icon}
      </span>
      <span>{children}</span>
    </li>
  );
}

/** The landing page's "How it works" panel, agent mode only (docs/onboarding-ui.md#Landing layout). */
export function HowItWorks({ shareData }: { shareData: boolean }) {
  return (
    <section aria-labelledby="how-it-works-heading" className="rounded-panel border border-border bg-surface p-6">
      <h2 id="how-it-works-heading" className="text-heading font-semibold text-text">
        How it works
      </h2>
      <p className="mt-1 text-body text-text-muted">Design a dashboard here, then build it in your own Google Data Studio.</p>

      <ol className="mt-4 grid grid-cols-3 gap-4">
        {STEPS.map((step, index) => (
          <li key={step.title} className="flex flex-col rounded-panel bg-surface-muted p-4">
            <div className="flex items-center justify-between">
              <span
                aria-hidden="true"
                className="flex size-6 items-center justify-center rounded-full bg-primary text-caption font-semibold text-on-primary"
              >
                {index + 1}
              </span>
              <span aria-hidden="true" className="text-primary [&_svg]:size-5">
                {step.icon}
              </span>
            </div>
            <h3 className="mt-3 text-title font-semibold text-text">{step.title}</h3>
            <p className="mt-1 text-body text-text">{step.body}</p>
            {step.extra}
          </li>
        ))}
      </ol>

      <div className="mt-4 border-t border-border pt-4">
        <h3 id="how-it-works-before" className="text-label font-semibold text-text">
          Before you start
        </h3>
        <ul aria-labelledby="how-it-works-before" className="mt-2 grid grid-cols-2 gap-x-6 gap-y-2">
          <BeforeItem icon={<Globe />}>
            <strong>Google Chrome</strong> must be installed.
          </BeforeItem>
          <BeforeItem icon={<Monitor />}>
            <strong>Windows</strong> is tested. macOS and Linux are untested.
          </BeforeItem>
          {shareData && (
            <BeforeItem icon={<Lock />}>Your build's data is saved as a CSV that anyone with its private link can read.</BeforeItem>
          )}
          <BeforeItem icon={<Users />}>Everyone with this link shares one build history.</BeforeItem>
        </ul>
      </div>
    </section>
  );
}
