# Frontend implementation conventions

## Conventions
- Only relative `/api/...` URLs; `vite.config.ts` proxies `/api` to `http://localhost:8000`; on
  Cloud Run the backend serves `dist/` (same origin).
- Gate when `GET /api/session` is `required && !ok` or on `401 access_required`; it posts
  `POST /api/session`; the cookie does the rest. Never store the code.
- Agent mode: Build shows an agent panel instead of sign-in (`agent_connected`, copyable
  `dss-agent` command with `--server <origin>`); Build off while offline.
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
- Run `node` values are the api.md 1.4 names; StretchRoute `'audit'` is a route, not a node.
- New actions (reference, feasibility, synthetic) match their run by the `run_id` from the `202`,
  never by node, and refetch their resource on that run's `run.finished`. The stretch 404-hide
  (stretch.ts) never applies to the required reference, feasibility or synthetic routes.
- Activity clock lives in ActivityStrip/RunCard, not useBuildStream (no per-second re-render).
  A run card sits after the message count known at its `run.started` (never timestamps). A
  `ready` event drops running runs: tests fire `ready` before a pre-load `run.started`.
- Focus after an async load: `useLayoutEffect`. Set state that disables a control in the event's
  batch, not via a child's passive effect. Truncate the focusable element, never its wrapper.

