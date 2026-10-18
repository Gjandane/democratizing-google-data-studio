import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { useState } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import { ApiError, STAGES } from '../src/api/types';
import { Button } from '../src/components/Button';
import { EmptyState } from '../src/components/EmptyState';
import { ErrorState } from '../src/components/ErrorState';
import { Input } from '../src/components/Input';
import { Modal } from '../src/components/Modal';
import { Pin } from '../src/components/Pin';
import { Popover } from '../src/components/Popover';
import { LoadingState } from '../src/components/Spinner';
import { Table } from '../src/components/Table';
import { Toast, ToastRegion } from '../src/components/Toast';
import { Stepper } from '../src/features/workspace/Stepper';
import { WorkspaceShell } from '../src/features/workspace/WorkspaceShell';
import { resetMockState } from '../src/mocks/api';
import { fixtures } from '../src/mocks/fixtures';

beforeEach(() => resetMockState());

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const FOCUS_RING = ['focus-visible:outline-2', 'focus-visible:outline-offset-2', 'focus-visible:outline-focus'];

describe('Button', () => {
  it('is a type="button" with the focus-visible ring classes', () => {
    render(<Button variant="primary">Generate plan</Button>);
    const button = screen.getByRole('button', { name: 'Generate plan' });
    expect(button.getAttribute('type')).toBe('button');
    for (const name of FOCUS_RING) expect(button.classList.contains(name)).toBe(true);
  });

  it('does nothing when disabled', () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Build in Data Studio
      </Button>,
    );
    const button = screen.getByRole('button', { name: 'Build in Data Studio' }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.className).toContain('disabled:opacity-50');
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('is busy and disabled while loading', () => {
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        Apply 2 comments
      </Button>,
    );
    const button = screen.getByRole('button', { name: 'Apply 2 comments' }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('aria-busy')).toBe('true');
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('keeps the ring on every variant', () => {
    const variants = ['primary', 'secondary', 'ghost', 'accent', 'danger', 'inverse'] as const;
    render(
      <>
        {variants.map((variant) => (
          <Button key={variant} variant={variant}>
            {variant}
          </Button>
        ))}
      </>,
    );
    for (const button of screen.getAllByRole('button')) {
      for (const name of FOCUS_RING) expect(button.classList.contains(name)).toBe(true);
    }
  });
});

describe('Stepper', () => {
  const step = (name: string) => screen.getByText(name).closest('li') as HTMLLIElement;

  it('marks the stages before the current one done and the current one with aria-current', () => {
    render(<Stepper current="plan" />);
    const nav = screen.getByRole('navigation', { name: 'Build stages' });
    expect(within(nav).getAllByRole('listitem')).toHaveLength(STAGES.length);

    for (const name of ['Connect', 'Interview']) {
      expect(step(name).dataset.state).toBe('done');
      expect(step(name).textContent).toContain('(done)');
      expect(step(name).getAttribute('aria-current')).toBeNull();
    }
    expect(step('Plan').dataset.state).toBe('current');
    expect(step('Plan').getAttribute('aria-current')).toBe('step');
    for (const name of ['Prototype', 'Build', 'Done']) {
      expect(step(name).dataset.state).toBe('upcoming');
      expect(step(name).getAttribute('aria-current')).toBeNull();
    }
  });

  it('starts on Connect with nothing done', () => {
    render(<Stepper current="connect" />);
    expect(step('Connect').getAttribute('aria-current')).toBe('step');
    expect(screen.queryByText('(done)')).toBeNull();
  });

  it('ends on Done with every earlier stage done', () => {
    render(<Stepper current="done" />);
    expect(screen.getAllByText('(done)')).toHaveLength(STAGES.length - 1);
    expect(step('Done').getAttribute('aria-current')).toBe('step');
  });
});

describe('EmptyState', () => {
  it('shows a heading, what will show up and the action', () => {
    render(
      <EmptyState
        title="No sources yet"
        description="CSV files you add show up here."
        action={<Button variant="primary">Upload CSV</Button>}
      />,
    );
    expect(screen.getByRole('heading', { level: 2, name: 'No sources yet' })).toBeTruthy();
    expect(screen.getByText('CSV files you add show up here.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Upload CSV' })).toBeTruthy();
  });

  it('takes a heading level', () => {
    render(<EmptyState title="Recipe" headingLevel={3} />);
    expect(screen.getByRole('heading', { level: 3, name: 'Recipe' })).toBeTruthy();
  });
});

describe('ErrorState', () => {
  it('is an alert with what failed and what to do, and retries', () => {
    const onRetry = vi.fn();
    render(<ErrorState title="Couldn't load your dashboards" message="Start the backend on port 8000, then try again." onRetry={onRetry} />);
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain("Couldn't load your dashboards");
    expect(alert.textContent).toContain('Start the backend on port 8000, then try again.');
    fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('has no button without onRetry', () => {
    render(<ErrorState title="Build failed" message="Check the engine log." />);
    expect(screen.queryByRole('button')).toBeNull();
  });
});

describe('other base components', () => {
  it('LoadingState is a status with visible text', () => {
    render(<LoadingState>Loading sources…</LoadingState>);
    expect(screen.getByRole('status').textContent).toBe('Loading sources…');
  });

  it('Input ties its label, hint and error to the control', () => {
    const { rerender } = render(<Input label="GCP project" hint="The project that holds the dataset." />);
    const input = screen.getByLabelText('GCP project');
    expect(document.getElementById(input.getAttribute('aria-describedby') ?? '')?.textContent).toBe('The project that holds the dataset.');
    expect(input.getAttribute('aria-invalid')).toBeNull();

    rerender(<Input label="GCP project" error="Enter a project id, like my-project-123." />);
    const invalid = screen.getByLabelText('GCP project');
    expect(invalid.getAttribute('aria-invalid')).toBe('true');
    expect(document.getElementById(invalid.getAttribute('aria-describedby') ?? '')?.textContent).toBe(
      'Enter a project id, like my-project-123.',
    );
  });

  it('Pin is named by its number, and is a button when clickable', () => {
    const onClick = vi.fn();
    render(
      <>
        <Pin n={1} />
        <Pin n={2} onClick={onClick} />
      </>,
    );
    expect(screen.getByRole('img', { name: 'Comment 1' }).textContent).toBe('1');
    fireEvent.click(screen.getByRole('button', { name: 'Comment 2' }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('Table renders headers, rows and footer totals', () => {
    const rows = [
      { id: 'r1', node: 'planner', tokens: 1200 },
      { id: 'r2', node: 'worker', tokens: 300 },
    ];
    render(
      <Table
        caption="Runs"
        rows={rows}
        rowKey={(row) => row.id}
        columns={[
          { id: 'node', header: 'Node', cell: (row) => row.node, mono: true },
          { id: 'tokens', header: 'Tokens', cell: (row) => row.tokens, align: 'right' },
        ]}
        footer={{ node: 'Total', tokens: 1500 }}
      />,
    );
    const table = screen.getByRole('table', { name: 'Runs' });
    expect(within(table).getAllByRole('columnheader').map((th) => th.textContent)).toEqual(['Node', 'Tokens']);
    expect(within(table).getAllByRole('row')).toHaveLength(4);
    expect(within(table).getByText('1500')).toBeTruthy();
  });

  it('ToastRegion is a polite live region that stays mounted when empty', () => {
    render(<ToastRegion />);
    expect(screen.getByRole('region', { name: 'Notifications' }).getAttribute('aria-live')).toBe('polite');
  });

  it('Toast announces errors as alerts and can be dismissed', () => {
    const onDismiss = vi.fn();
    render(
      <Toast tone="danger" onDismiss={onDismiss}>
        Build failed. Check the engine, then try again.
      </Toast>,
    );
    fireEvent.click(within(screen.getByRole('alert')).getByRole('button', { name: 'Dismiss' }));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it('Toast dismisses itself after its duration', () => {
    vi.useFakeTimers();
    const onDismiss = vi.fn();
    render(
      <Toast tone="success" onDismiss={onDismiss} duration={3000}>
        Settings saved.
      </Toast>,
    );
    vi.advanceTimersByTime(2999);
    expect(onDismiss).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(onDismiss).toHaveBeenCalledOnce();
  });
});

function ModalHarness({ onClose }: { onClose: () => void }) {
  const [open, setOpen] = useState(false);
  const close = () => {
    onClose();
    setOpen(false);
  };
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open settings
      </button>
      <Modal open={open} onClose={close} title="Settings" footer={<Button variant="primary">Save</Button>}>
        <Input label="Dataset" />
      </Modal>
    </>
  );
}

describe('Modal', () => {
  it('moves focus in, traps Tab, closes on Esc and returns focus', () => {
    const onClose = vi.fn();
    render(<ModalHarness onClose={onClose} />);
    const opener = screen.getByRole('button', { name: 'Open settings' });
    opener.focus();
    fireEvent.click(opener);

    const dialog = screen.getByRole('dialog', { name: 'Settings' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    const field = within(dialog).getByLabelText('Dataset');
    expect(document.activeElement).toBe(field);

    // Close (last in the DOM) wraps to the first field, and back.
    const close = within(dialog).getByRole('button', { name: 'Close' });
    close.focus();
    fireEvent.keyDown(document.activeElement as Element, { key: 'Tab' });
    expect(document.activeElement).toBe(field);
    fireEvent.keyDown(document.activeElement as Element, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(close);

    fireEvent.keyDown(document.activeElement as Element, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });
});

describe('Popover', () => {
  it('focuses its first control and closes on Esc or a press outside', () => {
    const onClose = vi.fn();
    render(
      <>
        <button type="button">Outside</button>
        <Popover open onClose={onClose} label="Comment on KPI card">
          <Button variant="inverse">Cancel</Button>
        </Popover>
      </>,
    );
    const dialog = screen.getByRole('dialog', { name: 'Comment on KPI card' });
    expect(document.activeElement).toBe(within(dialog).getByRole('button', { name: 'Cancel' }));

    fireEvent.keyDown(document.activeElement as Element, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.pointerDown(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Outside' }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});

describe('WorkspaceShell', () => {
  const renderShell = (id: string) =>
    render(
      <MemoryRouter initialEntries={[`/builds/${id}`]}>
        <Routes>
          <Route path="/builds/:id" element={<WorkspaceShell />} />
        </Routes>
      </MemoryRouter>,
    );

  it('shows the title, the stepper on Connect, the chat column and the stage area for a new build', async () => {
    const build = await api.createBuild({ title: 'Marketing funnel', archetype: 'analytical', mode: 'data' });
    renderShell(build.id);
    expect(screen.getByRole('status').textContent).toMatch(/loading/i);

    expect(await screen.findByRole('heading', { level: 1, name: 'Marketing funnel' })).toBeTruthy();
    const current = screen.getByRole('navigation', { name: 'Build stages' }).querySelector('[aria-current="step"]');
    expect(current?.textContent).toBe('1Connect');
    expect(screen.getByRole('complementary', { name: 'Chat' })).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: 'Connect' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'All dashboards' }).getAttribute('href')).toBe('/');
    // Nothing handles Trace and Settings yet.
    expect((screen.getByRole('button', { name: 'Settings' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('puts the stepper on the build stage', async () => {
    renderShell(fixtures.build.id);
    await screen.findByRole('heading', { level: 1, name: fixtures.build.title });
    const nav = screen.getByRole('navigation', { name: 'Build stages' });
    expect(nav.querySelector('[aria-current="step"]')?.textContent).toContain('Prototype');
  });

  it('shows the error with a retry and a way back for an unknown build', async () => {
    renderShell('b_missing');
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain("Couldn't open this build");
    expect(within(alert).getByRole('link', { name: 'Back to dashboards' }).getAttribute('href')).toBe('/');
    expect(within(alert).getByRole('button', { name: 'Try again' })).toBeTruthy();
  });

  it('"Try again" reloads the build and puts focus on the main area', async () => {
    vi.spyOn(api, 'getBuild').mockRejectedValueOnce(new ApiError(0, 'network_error', "Can't reach the backend. Start it on port 8000, then try again."));
    renderShell(fixtures.build.id);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain("Can't reach the backend");

    fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
    await screen.findByRole('heading', { level: 1, name: fixtures.build.title });
    expect(document.activeElement).toBe(screen.getByRole('main'));
  });
});
