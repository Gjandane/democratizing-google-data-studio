// The shared API fixtures, imported in place from ../contracts/fixtures/api/ (never copied)
// and checked against the contract guards once, so the mock can only serve conforming data.
import referenceSetJson from '../../../contracts/fixtures/dashboard-intent/reference_set.json';
import buildDoneJson from '../../../contracts/fixtures/api/build.done.json';
import buildJson from '../../../contracts/fixtures/api/build.json';
import buildsJson from '../../../contracts/fixtures/api/builds.json';
import engineStatusJson from '../../../contracts/fixtures/api/engine_status.json';
import engineStatusLocalJson from '../../../contracts/fixtures/api/engine_status.local.json';
import errorJson from '../../../contracts/fixtures/api/error.json';
import eventsSse from '../../../contracts/fixtures/api/events.sse?raw';
import messagesJson from '../../../contracts/fixtures/api/messages.json';
import prototypeHtml from '../../../contracts/fixtures/api/prototype.sample.html?raw';
import recipeJson from '../../../contracts/fixtures/api/recipe.json';
import runAcceptedJson from '../../../contracts/fixtures/api/run_accepted.json';
import sessionJson from '../../../contracts/fixtures/api/session.json';
import settingsJson from '../../../contracts/fixtures/api/settings.json';
import tracesJson from '../../../contracts/fixtures/api/traces.json';
import {
  arrayOf,
  isApiErrorBody,
  isBuild,
  isBuildSummary,
  isEngineStatus,
  isMessage,
  isRecipe,
  isReferenceSet,
  isRunAccepted,
  isSession,
  isSettings,
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

function checkedEvents(body: string): BuildEvent[] {
  return parseSse(body).map(({ event, data }, i) => {
    const problems: string[] = [];
    const parsed = toBuildEvent(event, JSON.parse(data), problems);
    if (!parsed) throw new Error(`Fixture events.sse #${i + 1} doesn't match the API contract:\n${problems.join('\n')}`);
    return parsed;
  });
}

export const fixtures = /* @__PURE__ */ (() => ({
  referenceSet: checked(isReferenceSet, referenceSetJson, 'reference_set.json'),
  build: checked(isBuild, buildJson, 'build.json'),
  buildDone: checked(isBuild, buildDoneJson, 'build.done.json'),
  builds: checked(arrayOf(isBuildSummary), buildsJson, 'builds.json'),
  /** Agent mode, agent connected and signed in. */
  engineStatus: checked(isEngineStatus, engineStatusJson, 'engine_status.json'),
  /** Local mode: what the mock engine reports unless a test changes it. */
  engineStatusLocal: checked(isEngineStatus, engineStatusLocalJson, 'engine_status.local.json'),
  error: checked(isApiErrorBody, errorJson, 'error.json'),
  events: checkedEvents(eventsSse),
  messages: checked(arrayOf(isMessage), messagesJson, 'messages.json'),
  prototypeHtml,
  recipe: checked(isRecipe, recipeJson, 'recipe.json'),
  runAccepted: checked(isRunAccepted, runAcceptedJson, 'run_accepted.json'),
  session: checked(isSession, sessionJson, 'session.json'),
  settings: checked(isSettings, settingsJson, 'settings.json'),
  traces: checked(arrayOf(isTrace), tracesJson, 'traces.json'),
}))();

/** A deep copy, so mock state never mutates the imported fixture. */
export const clone = <T>(value: T): T => value === undefined ? value : JSON.parse(JSON.stringify(value)) as T;
