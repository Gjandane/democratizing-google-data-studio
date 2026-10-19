<!-- essentials-of: none (no architecture.md; this page is the architecture) -->
# Architecture essentials: frontend
One page, read at the start of every build session. POC: this page is the whole architecture.

## Stack
- Vite 8 + React 19 + TypeScript (strict) + Tailwind CSS v4 (`@tailwindcss/vite`); react-router;
  react-markdown; lucide-react icons; Vitest + Testing Library + jsdom. Node 20+.

## Folder map
```text
src/api/         client.ts (fetch wrappers, relative /api), types.ts (from ../contracts/api.md), events.ts (EventSource hook)
src/mocks/       mock API + fake event stream; data comes from ../contracts/fixtures/api/ (never copied)
src/styles/      tokens.css (all colors, type, spacing, radius as CSS variables)
src/components/  base components (Button, Input, Panel, Stepper, Pin, Popover, Toast, Spinner, EmptyState, ErrorState, Modal, Table)
src/features/    history/, workspace/ (shell, chat/, connect/, plan/, prototype/, build/), settings/, trace/
tests/           vitest specs; contract.test.ts checks ../contracts/fixtures/api/ against types.ts guards
screenshots/     UI check screenshots, named <task>-<view>-<viewport>.png
```

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
- Run `node` values are the api.md 1.2 names; StretchRoute `'audit'` is a route, not a node.
- Activity clock lives in ActivityStrip/RunCard, not useBuildStream (no per-second re-render).
- Focus after an async load: `useLayoutEffect`. Set state that disables a control in the event's
  batch, not via a child's passive effect. Truncate the focusable element, never its wrapper.

## Never do
- Never call anything but the backend's `/api` (one exception, kept by the user at 1.2: the
  Google Fonts stylesheet for Inter and Fira Code in src/index.css); never store the API key in
  localStorage.
- No raw hex/px in components: tokens only.
- Never edit ../contracts/; a needed change is a blocked task.

## UI design
- Direction: Studio Light — calm Data Studio-adjacent workspace, dense (8/10), blue data + amber for comments.
- Tokens: src/styles/tokens.css; components use tokens only.
- Palette: bg #F8FAFC, surface #FFFFFF, surface-muted #F1F5F9, text #0F172A, text-muted #475569, border #E2E8F0, primary #1E40AF (hover #1E3A8A, on #FFFFFF), accent #D97706 (comment pins, "Apply" CTA; on #000000), success #15803D, danger #DC2626, focus ring #1E40AF.
- Type and spacing: Inter (UI), Fira Code (recipe lines, ids); 12/13/14/16/20/24 px, body 14; spacing 4/8/12/16/24/32; radius 6 controls, 10 panels; shadow only on popovers/modals.
- Layout: top bar 48 px (logo, build title, stepper, Trace, Settings); left chat column 380 px fixed; stage area fills the rest; History is a single centered list (max 960 px). Stage areas: Connect (archetype, sources); Interview (sources summary, archetype card, questions answered so far, "Generate plan"); Plan (progress lines, docs); Prototype (scaled iframe, pins, pending list); Build (recipe ops, live status); Done (link card, versions, "New version"); above the chat input, the activity strip (task 6.1).
- Activity: strip above the chat input (phrase · m:ss · tokens), 400 ms after `run.started`, in
  a reserved slot; preset checklist card in the log, last step ticks only on `run.finished` ok.
- Copy: sentence case, active voice; buttons are verbs ("Apply 3 comments"); errors say what to do next.
- States: every data view has loading, empty and error; every control has hover, focus-visible and disabled.
- Accessibility: 4.5:1 text contrast, keyboard path to every action (Esc closes popovers), visible focus ring, respects prefers-reduced-motion.
- Viewports: 1280x800 and 1440x900; screenshots in screenshots/.
- Avoid: emoji as icons, gray-on-gray text, popovers covering the element being commented, layout shift when pins appear.

## Contracts
| Contract | Version | Role | Conformance check |
|---|---|---|---|
| ../contracts/api.md | 1.2 | consumes | `npm test -- contract` |
| ../contracts/conventions.md | 1.1 | consumes | manual: port 5173, `/api` proxy to 8000 |

## Dependencies
| Package | Registry | Version | Why | Verified |
| --- | --- | --- | --- | --- |
| react | npm | ^19.3.1 | UI | 2026-10-18 (19.3.1) |
| react-dom | npm | ^19.3.1 | UI | 2026-10-18 (19.3.1) |
| react-router-dom | npm | ^7.18.0 | two routes | 2026-10-18 (7.18.4) |
| react-markdown | npm | ^10.1.0 | chat and docs markdown | 2026-10-18 (10.1.0) |
| lucide-react | npm | ^1.59.0 | icons | 2026-10-18 (1.59.0) |
| vite | npm | ^8.3.0 | dev server + proxy | 2026-10-18 (8.3.4) |
| @vitejs/plugin-react | npm | ^6.1.0 | React in Vite | 2026-10-18 (6.1.2) |
| typescript | npm | >=5.5 <6 | types | 2026-10-18 (7.0.2) |
| tailwindcss | npm | ^4.3.0 | styling | 2026-10-18 (4.3.3) |
| @tailwindcss/vite | npm | ^4.3.0 | Tailwind v4 plugin | 2026-10-18 (4.3.3) |
| vitest | npm | ^5.0.0 | tests | 2026-10-18 (5.0.5) |
| @testing-library/react | npm | ^16.3.0 | component tests | 2026-10-18 (16.3.3) |
| jsdom | npm | ^30.1.0 | test DOM | 2026-10-18 (30.1.3) |
| @testing-library/dom | npm | ^10.4.0 | peer of @testing-library/react | 2026-10-18 (10.4.2) |
| @types/react | npm | ^19.0.0 | strict typecheck | 2026-10-18 (19.3.0) |
| @types/react-dom | npm | ^19.0.0 | strict typecheck | 2026-10-18 (19.3.0) |
