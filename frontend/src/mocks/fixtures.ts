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
import referenceSetPendingJson from '../../../contracts/fixtures/dashboard-intent/reference_set.pending.json';
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
import sessionGoogleJson from '../../../contracts/fixtures/api/session.google.json';
import sessionJson from '../../../contracts/fixtures/api/session.json';
// api.md 3.0: the Settings come from stage-settings/ (api/settings.json is the 2.0 shape, kept by the contract until removal).
import buildCostJson from '../../../contracts/fixtures/stage-settings/build_cost.json';
import capabilitiesJson from '../../../contracts/fixtures/stage-settings/capabilities.json';
import designPagesJson from '../../../contracts/fixtures/stage-settings/design_pages.json';
import designPagesReviewIssueJson from '../../../contracts/fixtures/stage-settings/design_pages.review.issue.json';
import designPagesReviewJson from '../../../contracts/fixtures/stage-settings/design_pages.review.json';
import invalidSettingsJson from '../../../contracts/fixtures/stage-settings/error.invalid_settings.json';
import eventsReviewSse from '../../../contracts/fixtures/stage-settings/events.review.sse?raw';
import runCallsJson from '../../../contracts/fixtures/stage-settings/run_calls.json';
import settingsJson from '../../../contracts/fixtures/stage-settings/settings.json';
import tracesJson from '../../../contracts/fixtures/api/traces.json';
// contracts/fixtures/hosted-build/ (api.md 3.4).
import claimedJobJson from '../../../contracts/fixtures/hosted-build/claimed_job.json';
import hostingLocalJson from '../../../contracts/fixtures/hosted-build/hosting.local.json';
import hostingOpenJson from '../../../contracts/fixtures/hosted-build/hosting.open.json';
import jobTicketRunningJson from '../../../contracts/fixtures/hosted-build/job_ticket.running.json';
import jobTicketWaitingJson from '../../../contracts/fixtures/hosted-build/job_ticket.waiting.json';
import {
  arrayOf,
  isAssessment,
  isApiErrorBody,
  isBlueprint,
  isBuild,
  isBuildCost,
  isBuildSummary,
  isClaimedJob,
  isContext,
  isDesignPages,
  isDesign,
  isEngineStatus,
  isGenerationRequest,
  isGenerationStatus,
  isHosting,
  isJobTicket,
  isMessage,
  isOutline,
  isProposal,
  isRecipe,
  isReferenceSet,
  isRunAccepted,
  isRunCalls,
  isSession,
  isSettings,
  isSettingsCapabilities,
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
  /** A recreate set with its analysis approved (revision 2). */
  referenceSet: checked(isReferenceSet, referenceSetJson, 'reference_set.json'),
  /** The analysis as a recreate upload commits it: pending, revision 1. */
  referenceSetPending: checked(isReferenceSet, referenceSetPendingJson, 'reference_set.pending.json'),
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
  /** Google sign-in on, a user signed in. */
  sessionGoogle: checked(isSession, sessionGoogleJson, 'session.google.json'),
  settings: checked(isSettings, settingsJson, 'stage-settings/settings.json'),
  traces: checked(arrayOf(isTrace), tracesJson, 'traces.json'),
  // contracts/fixtures/stage-settings/ (api.md 3.0)
  capabilities: checked(isSettingsCapabilities, capabilitiesJson, 'stage-settings/capabilities.json'),
  /** A designed page and a standard page, no review. */
  designPages: checked(isDesignPages, designPagesJson, 'stage-settings/design_pages.json'),
  /** A pending brief review, revision 1, no issues. */
  designPagesReview: checked(isDesignPages, designPagesReviewJson, 'stage-settings/design_pages.review.json'),
  /** A pending review, revision 2, with issues. */
  designPagesReviewIssue: checked(isDesignPages, designPagesReviewIssueJson, 'stage-settings/design_pages.review.issue.json'),
  runCalls: checked(isRunCalls, runCallsJson, 'stage-settings/run_calls.json'),
  buildCost: checked(isBuildCost, buildCostJson, 'stage-settings/build_cost.json'),
  /** The 422 invalid_settings body. */
  invalidSettings: checked(isApiErrorBody, invalidSettingsJson, 'stage-settings/error.invalid_settings.json'),
  /** A prototype run that pauses for a brief review (brief.review, then run.finished ok). */
  eventsReview: checkedEvents(eventsReviewSse, 'stage-settings/events.review.sse'),
  // contracts/fixtures/hosted-build/ (api.md 3.4)
  /** Local mode: nothing locked, no shared data. */
  hostingLocal: checked(isHosting, hostingLocalJson, 'hosted-build/hosting.local.json'),
  /** The open link: agent mode, GCS and BigQuery locked, data shared. */
  hostingOpen: checked(isHosting, hostingOpenJson, 'hosted-build/hosting.open.json'),
  jobTicketWaiting: checked(isJobTicket, jobTicketWaitingJson, 'hosted-build/job_ticket.waiting.json'),
  jobTicketRunning: checked(isJobTicket, jobTicketRunningJson, 'hosted-build/job_ticket.running.json'),
  claimedJob: checked(isClaimedJob, claimedJobJson, 'hosted-build/claimed_job.json'),
}))();

/** A deep copy, so mock state never mutates the imported fixture. */
export const clone = <T>(value: T): T => value === undefined ? value : JSON.parse(JSON.stringify(value)) as T;
