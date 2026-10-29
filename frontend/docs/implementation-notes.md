# Frontend implementation conventions

## Conventions
- Only relative `/api/...` URLs; `vite.config.ts` proxies `/api` to `http://localhost:8000`; on
  Cloud Run the backend serves `dist/` (same origin).
- Gate when `GET /api/session` is `required && !ok` or on `401 access_required`; it posts
  `POST /api/session`; the cookie does the rest. Never store the code.
- Google sign-in (api.md 3.3, task 18.1): when `Session.google_client_id` is set, the gate loads
  https://accounts.google.com/gsi/client (only on the gate), calls
  `google.accounts.id.initialize({client_id, callback})` and `renderButton`, and posts the
  callback's `credential` as `{google_id_token}`; no code field then. Type the small GIS surface
  you use in a local .d.ts; tests stub `window.google`. Never store the token.
- Setup step (api.md 3.4 Checks, frontend 19.3): in agent mode Build first shows "Set up this
  computer": `POST /api/agent-checks`, the conventions 1.7 setup-step commands with `-Check
  <code>` (same two tabs and Chrome line as the job panel), then poll `GET /api/agent-checks/{id}`
  every 3 s while `waiting`; `passed` shows "Agent ready on this computer" (check items ticked);
  `failed` lists each failed item with its fix and offers Check again (a new code); `expired`
  offers a new code. A passed check is remembered for the tab in sessionStorage as a boolean
  only (never the code), so the step folds into a one-line "Agent ready" after a reload. Build
  stays enabled throughout ("Already set up? Build in Data Studio").
- Agent mode (api.md 3.4, change 2026-10-29): Build in Data Studio is enabled (no agent to wait
  for); after `POST /run`, `GET /api/builds/{id}/job` gives the ticket; poll it every 3 s while
  `waiting` (stop on `running`, `finished`, `expired` or unmount) and follow the run on the event
  stream as in local mode. The job panel shows "Needs Google Chrome", two tabs (Windows
  PowerShell, macOS/Linux bash "untested") with the conventions 1.7 setup command built from
  `window.location.origin` and the code, one Copy button per tab, the code's countdown, and
  with `Hosting.share_data` the note "Your data is saved as a CSV that anyone with its private
  link can read, so your Data Studio account can open it." `expired` offers Build again; on mount in stage
  `build` the panel restores the ticket from `GET .../job` (a 404 offers Build again); a failed
  hosted run shows its error and Build again. The code is never logged or stored beyond the React
  state. `GET /api/hosting` once per app load;
  `locked_sources` disables the GCS/BigQuery form in Connect with "GCS and BigQuery sources need
  the local app (see README)"; `403 source_locked` shows the same text.
- `VITE_MOCK=1` swaps `client.ts` for `src/mocks/` (same function signatures). Mocks import
  ../contracts/fixtures/api/* directly (`server.fs.allow` includes `..`); never copy fixtures.
- One EventSource per open build (`/api/builds/{id}/events`); on reconnect re-fetch build + messages.
- Types in `src/api/types.ts` mirror ../contracts/api.md names exactly; runtime guards for the contract test.
- Prototype: `<iframe src="/api/builds/{id}/prototype?v=<spec_version>">`; the overlay reads
  `[data-cid]` elements from `iframe.contentDocument` and positions pins from their boxes (scaled
  to the iframe's zoom). Never inject scripts into the iframe.
- The 1200 px canvas is fitted to the stage width by one `transform: scale(s)` wrapper around both
  the iframe and the pin layer (s = stage width / canvas width, max 1), so pins and elements
  share one coordinate system.
- jsdom has no layout: tests stub `getBoundingClientRect` for `[data-cid]` elements; real pin
  placement is checked in the manual screenshots.
- Tests use the mock (`resetMockState()` per test; knobs `setMockEngine`, `setMockBuildOutcome`,
  `setMockSession`); no jest-dom: assert `el.disabled`, drive with `fireEvent`. Guards are exact.
- Test traps: under fake timers wrap mock calls (`await vi.runAllTimersAsync(); return promise`,
  tests/activity.test.tsx `call`), since mock `respond` uses `setTimeout(0)`; vitest has
  `URL.createObjectURL`, so spy `prototypeUrl` with `mockImplementation(httpApi.prototypeUrl)` to
  assert `?v=`; build-stage tests use `fixtures.build.id` (mock `compileRecipe` needs
  `spec_version`); call `button.focus()` before `fireEvent.click` to assert Modal focus return.
- Resource-panel tests (references, feasibility): a GET spy call only means a refetch started, and
  a background refetch keeps the old content, controls and gates: await what the new result
  renders (resolved requirements are hidden, a ready assessment is one line), or hold the GET on a
  pending promise to assert the in-between state. "Loading feasibility…" shows only before the
  first load. A status message renders before the refetch lands, so await post-action focus with
  `waitFor`.
- Workspace panels (references, feasibility, synthetic) share the build's one EventSource through
  stretch.ts `subscribeWorkspace`/`publishWorkspace`; WorkspaceShell owns the feasibility gates
  (planReady/buildReady); a panel drops a response older than its latest request or assessment id.
- Run `node` values are the api.md 2.0 names; StretchRoute `'audit'` is a route, not a node.
- Artifact editors (context/, outline/, design/; hosted by ArtifactStage): selects, radios,
  ticks, add/remove PUT at once, text and hex on blur; PUTs serialized by edit counters, and a
  response never overwrites newer typing; saving never disables inputs. `onSavingChange` (a PUT
  in flight or failed) blocks Confirm and the redraft actions. ArtifactStage drops a load with a
  lower revision. Issues land on the deepest rendered JSON-pointer path. Invalid hex/number text
  stays only while focused and is never sent.
- After a `202` for an artifact run (Suggest more, Other), controls stay off until that `run_id`
  shows in the stream's activity (fallback 30 s): a fast run can start and finish before React
  renders the lock.
- Blueprint feasibility issues render under their row through blueprint/issueSlots (one
  FeasibilityPanel, portals); after a saved decision the blueprint refetches, since the backend
  rewrites rows without `artifact.updated`. Prototype page tabs show one `data-page-name` section
  and keep the page by position across versions.
- jsdom: controls in a disabled `<fieldset>` keep `.disabled === false`, still receive clicks, and
  `activeElement` can stay on one; assert `el.matches(':disabled')`.
- New actions (reference, feasibility, synthetic) match their run by the `run_id` from the `202`,
  never by node, and refetch their resource on that run's `run.finished`. The stretch 404-hide
  (stretch.ts) never applies to the required reference, feasibility or synthetic routes.
- Activity clock lives in ActivityStrip/RunCard, not useBuildStream (no per-second re-render).
  A run card sits after the message count known at its `run.started` (never timestamps). A
  `ready` event drops running runs: tests fire `ready` before a pre-load `run.started`.
- Focus after an async load: `useLayoutEffect`. Set state that disables a control in the event's
  batch, not via a child's passive effect. Truncate the focusable element, never its wrapper.
- Settings (api.md 3.0): settings/stageSettings.ts is the one validator (STAGE_ORDER, STAGE_META,
  validateSettings, callCost, formatUsd), shared by the mock. Only issues the saved settings
  didn't already have block Save; Save sends only the diff; on success `rebaseDraft` keeps edits
  made while the PUT was in flight. Prices come only from capabilities (a Vitest guard rejects
  price constants in src/). `openSettings(target?)` opens a tab or a stage field.
- Brief review: Workspace owns one lock (briefs/reviewLock.ts `ReviewLockContext`, from
  design-pages + `stream.briefReview` + a pending approve run); controls read `useReviewLock()`.
  client.ts `withReviewNotice` catches 409 brief_review_pending from any call and refetches
  design-pages. Review PUTs are serialized with the response's revision, like artifact editors.
- Stage-limit run errors: trace/stageErrors.tsx `parseStageError` + `RunErrorActionsContext`
  (Adjust in Settings, View model calls), provided by WorkspaceShell.
- `npm run dev` runs under `<StrictMode>`, tests don't: set a "refetch quietly" ref when the data
  lands, never when the request starts (StrictMode's second run swallows the error); test that
  path inside `<StrictMode>`.
- Test traps (Phase 16): builds from `api.createBuild` have no spec_version, so call
  `setMockDesignPages(id, fixtures.designPages)` before reading design-pages; in WorkspaceShell
  tests find a stage control before reading `main` (the loading view has its own main), and give
  the file's first findBy a longer timeout than the default 1 s.

