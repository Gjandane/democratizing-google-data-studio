// Stage-limit run errors (api.md 3.0, Run errors): `"<code>: <stage> <message>"`. The UI shows the
// message after the code with "Adjust in Settings" and "View model calls" (docs/stage-settings-ui.md).
import { Activity, Settings } from 'lucide-react';
import { createContext, useContext } from 'react';
import { STAGE_IDS, type StageId } from '../../api/types';
import { Button } from '../../components/Button';
import type { SettingsTarget, StageFocusField } from '../settings/stageSettings';

/** The limit codes, with the stage field Settings focuses for each. */
const LIMIT_FIELDS: Readonly<Record<string, StageFocusField>> = {
  stage_input_over_limit: 'input_tokens',
  stage_output_cutoff: 'output_tokens',
  stage_timeout: 'timeout_s',
  stage_model_unavailable: 'model',
};
/** Validation repairs used up: nothing in Settings to adjust, only the calls to look at. */
const INVALID_CODES: ReadonlySet<string> = new Set(['brief_invalid', 'html_invalid']);

export interface StageRunError {
  /** The text after the code. */
  message: string;
  /** Where "Adjust in Settings" opens; null for brief_invalid / html_invalid. */
  settings: SettingsTarget | null;
}

/** A run error that names a stage limit or used-up repairs; null for any other error (shown as before). */
export function parseStageError(text: string | null | undefined): StageRunError | null {
  if (!text) return null;
  const colon = text.indexOf(':');
  if (colon < 0) return null;
  const code = text.slice(0, colon).trim();
  const message = text.slice(colon + 1).trim();
  if (message === '') return null;
  if (INVALID_CODES.has(code)) return { message, settings: null };
  const field = LIMIT_FIELDS[code];
  if (!field) return null;
  // The message starts with the StageId; one the UI doesn't know opens the Models tab.
  const stage = /^[a-z_]+/.exec(message)?.[0];
  const known = stage !== undefined && (STAGE_IDS as readonly string[]).includes(stage);
  return { message, settings: known ? { stage: stage as StageId, field } : { tab: 'models' } };
}

export interface RunErrorActions {
  openSettings?: (target: SettingsTarget) => void;
  /** Opens Trace on the open build, at the run when given. */
  openTrace?: (runId?: string) => void;
}

/** Provided by the workspace; without it the buttons don't show. */
export const RunErrorActionsContext = createContext<RunErrorActions>({});

/** "Adjust in Settings" (limit codes only) and "View model calls" for a parsed run error. */
export function StageErrorActions({ error, runId }: { error: StageRunError; runId: string | null | undefined }) {
  const { openSettings, openTrace } = useContext(RunErrorActionsContext);
  const target = error.settings;
  return (
    <>
      {target && openSettings && (
        <Button size="sm" icon={<Settings aria-hidden="true" />} onClick={() => openSettings(target)}>
          Adjust in Settings
        </Button>
      )}
      {openTrace && (
        <Button size="sm" icon={<Activity aria-hidden="true" />} onClick={() => openTrace(runId ?? undefined)}>
          View model calls
        </Button>
      )}
    </>
  );
}
