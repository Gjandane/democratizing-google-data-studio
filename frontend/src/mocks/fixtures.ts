import feasibilityStaleJson from '../../../contracts/fixtures/dashboard-intent/feasibility.stale.json';
import feasibilityPendingJson from '../../../contracts/fixtures/dashboard-intent/feasibility.pending.json';
import feasibilityAlternativesJson from '../../../contracts/fixtures/dashboard-intent/feasibility.alternatives.json';
import feasibilityJson from '../../../contracts/fixtures/dashboard-intent/feasibility.json';
import syntheticDatasetJson from '../../../contracts/fixtures/synthetic-data/dataset.json';
import syntheticJobFailedJson from '../../../contracts/fixtures/synthetic-data/job.failed.json';
import syntheticJobSucceededJson from '../../../contracts/fixtures/synthetic-data/job.succeeded.json';
import syntheticProposalJson from '../../../contracts/fixtures/synthetic-data/proposal.json';
import syntheticRequestJson from '../../../contracts/fixtures/synthetic-data/request.json';
import syntheticSourceJson from '../../../contracts/fixtures/synthetic-data/source.json';
// The shared API fixtures, imported in place from ../contracts/fixtures/api/ (never copied)
// and checked against the contract guards once, so the mock can only serve conforming data.
import referenceSetJson from '../../../contracts/fixtures/dashboard-intent/reference_set.json';
import blueprintBlockedJson from '../../../contracts/fixtures/api/blueprint.blocked.json';
import blueprintJson from '../../../contracts/fixtures/api/blueprint.json';
import buildDoneJson from '../../../contracts/fixtures/api/build.done.json';
import buildJson from '../../../contracts/fixtures/api/build.json';
import buildsJson from '../../../contracts/fixtures/api/builds.json';
import contextJson from '../../../contracts/fixtures/api/context.json';
import designJson from '../../../contracts/fixtures/api/design.json';
import designPresetsJson from '../../../contracts/fixtures/api/design_presets.json';
import engineStatusJson from '../../../contracts/fixtures/api/engine_status.json';
import engineStatusLocalJson from '../../../contracts/fixtures/api/engine_status.local.json';
import errorJson from '../../../contracts/fixtures/api/error.json';
import eventsSse from '../../../contracts/fixtures/api/events.sse?raw';
import eventsUsageSse from '../../../contracts/fixtures/api/events.usage.sse?raw';
import messagesJson from '../../../contracts/fixtures/api/messages.json';
import outlineJson from '../../../contracts/fixtures/api/outline.json';
import prototypeMultipageHtml from '../../../contracts/fixtures/api/prototype.multipage.html?raw';
import prototypeHtml from '../../../contracts/fixtures/api/prototype.sample.html?raw';
import recipeJson from '../../../contracts/fixtures/api/recipe.json';
import runAcceptedJson from '../../../contracts/fixtures/api/run_accepted.json';
import sessionJson from '../../../contracts/fixtures/api/session.json';
import settingsJson from '../../../contracts/fixtures/api/settings.json';
import tracesJson from '../../../contracts/fixtures/api/traces.json';
import {
  arrayOf,
  isAssessment,
  isApiErrorBody,
  isBlueprint,
  isBuild,
  isBuildSummary,
  isContext,
  isDesign,
  isEngineStatus,
  isGenerationRequest,
  isGenerationStatus,
  isMessage,
  isOutline,
  isProposal,
  isRecipe,
  isReferenceSet,
  isRunAccepted,
  isSession,
  isSettings,
  isSource,
  isSyntheticDataset,
  isThemePreset,
  isTrace,
  problemsOf,
  toBuildEvent,
  type BuildEvent,
  type Guard,
} from '../api/types';
import { parseSse } from './sse';

function checked<T>(guard: Guard<T>, value: unknown, file: string): T {
  const problems = problemsOf(guard, value, file);
  if (problems.length > 0) throw new Error(`Fixture ${file} doesn't match the API contract:\n${problems.join('\n')}`);
  return value as T;
}

function checkedEvents(body: string, file: string): BuildEvent[] {
  return parseSse(body).map(({ event, data }, i) => {
    const problems: string[] = [];
    const parsed = toBuildEvent(event, JSON.parse(data), problems);
    if (!parsed) throw new Error(`Fixture ${file} #${i + 1} doesn't match the API contract:\n${problems.join('\n')}`);
    return parsed;
  });
}

export const fixtures = /* @__PURE__ */ (() => ({
  feasibility: checked(isAssessment, feasibilityJson, 'feasibility.json'),
  feasibilityAlternatives: checked(isAssessment, feasibilityAlternativesJson, 'feasibility.alternatives.json'),
  feasibilityPending: checked(isAssessment, feasibilityPendingJson, 'feasibility.pending.json'),
  feasibilityStale: checked(isAssessment, feasibilityStaleJson, 'feasibility.stale.json'),
  referenceSet: checked(isReferenceSet, referenceSetJson, 'reference_set.json'),
  // contracts/fixtures/synthetic-data/
  syntheticDataset: checked(isSyntheticDataset, syntheticDatasetJson, 'synthetic-data/dataset.json'),
  syntheticJobFailed: checked(isGenerationStatus, syntheticJobFailedJson, 'synthetic-data/job.failed.json'),
  syntheticJobSucceeded: checked(isGenerationStatus, syntheticJobSucceededJson, 'synthetic-data/job.succeeded.json'),
  syntheticProposal: checked(isProposal, syntheticProposalJson, 'synthetic-data/proposal.json'),
  syntheticRequest: checked(isGenerationRequest, syntheticRequestJson, 'synthetic-data/request.json'),
  syntheticSource: checked(isSource, syntheticSourceJson, 'synthetic-data/source.json'),
  build: checked(isBuild, buildJson, 'build.json'),
  buildDone: checked(isBuild, buildDoneJson, 'build.done.json'),
  builds: checked(arrayOf(isBuildSummary), buildsJson, 'builds.json'),
  /** Agent mode, agent connected and signed in. */
  engineStatus: checked(isEngineStatus, engineStatusJson, 'engine_status.json'),
  /** Local mode: what the mock engine reports unless a test changes it. */
  engineStatusLocal: checked(isEngineStatus, engineStatusLocalJson, 'engine_status.local.json'),
  error: checked(isApiErrorBody, errorJson, 'error.json'),
  events: checkedEvents(eventsSse, 'events.sse'),
  /** A blueprint run with live token counts. */
  eventsUsage: checkedEvents(eventsUsageSse, 'events.usage.sse'),
  messages: checked(arrayOf(isMessage), messagesJson, 'messages.json'),
  prototypeHtml,
  /** Two page sections (data-page, data-page-name). */
  prototypeMultipageHtml,
  // Staged workflow artifacts (api.md 2.0).
  context: checked(isContext, contextJson, 'context.json'),
  outline: checked(isOutline, outlineJson, 'outline.json'),
  design: checked(isDesign, designJson, 'design.json'),
  designPresets: checked(arrayOf(isThemePreset), designPresetsJson, 'design_presets.json'),
  /** Every row ok. */
  blueprint: checked(isBlueprint, blueprintJson, 'blueprint.json'),
  /** The ratio row (q2) blocked. */
  blueprintBlocked: checked(isBlueprint, blueprintBlockedJson, 'blueprint.blocked.json'),
  recipe: checked(isRecipe, recipeJson, 'recipe.json'),
  runAccepted: checked(isRunAccepted, runAcceptedJson, 'run_accepted.json'),
  session: checked(isSession, sessionJson, 'session.json'),
  settings: checked(isSettings, settingsJson, 'settings.json'),
  traces: checked(arrayOf(isTrace), tracesJson, 'traces.json'),
}))();

/** A deep copy, so mock state never mutates the imported fixture. */
export const clone = <T>(value: T): T => value === undefined ? value : JSON.parse(JSON.stringify(value)) as T;
