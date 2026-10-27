<!-- essentials-of: none (no architecture.md; this page is the architecture) -->
# Architecture essentials: frontend
Read first. POC: this page is the whole architecture.

## Stack
- Vite 8 + React 19 + TypeScript (strict) + Tailwind CSS v4 (`@tailwindcss/vite`); react-router;
  react-markdown; lucide-react icons; Vitest + Testing Library + jsdom. Node 20+.

## Folder map
```text
src/api/         client.ts (fetch wrappers, relative /api), types.ts (from ../contracts/api.md), events.ts (EventSource hook)
src/mocks/       mock API + fake event stream; data comes from ../contracts/fixtures/api/ (never copied)
src/styles/      tokens.css (all colors, type, spacing, radius as CSS variables)
src/components/  base components (Button, Input, Panel, Stepper, Pin, Popover, Toast, Spinner, EmptyState, ErrorState, Modal, Table)
src/features/    history/, activity/ (strip, run cards, node presets), access/, workspace/ (shell, connect/,
                 context/, outline/, design/, blueprint/, prototype/, briefs/, build/), settings/, trace/
tests/           vitest specs; contract.test.ts checks ../contracts/fixtures/api/ against types.ts guards
screenshots/     UI check screenshots, named <task>-<view>-<viewport>.png
```

## Conventions
- Read docs/implementation-notes.md for API/auth, mocks, iframe geometry, activity, stage
  settings, brief review lock and test rules.
- Relative /api; Vite proxy locally, backend static hosting on Cloud Run. Gate access with the
  cookie; never retain the code. Agent mode uses the agent panel instead of local sign-in.
- Exact runtime contract guards; mocks import shared fixtures. One EventSource per build;
  reconnect refetches state. Build/SSE guards stay exact in API 2.0 (stages, artifacts, notes, artifact.updated).
- Backend prototype iframe and pin overlay share one scaled 1200px canvas; no injected scripts.
  jsdom geometry is stubbed; verify real geometry at both UI viewports.
- Use contract node names; run-card anchor is message count at start. Clock stays in strip/card.
  Use layout effects for async focus; action guards update synchronously. Truncate focusable text.
- Artifact editors save per control, serialized; a pending or failed save blocks Confirm.

## Never do
- Never call anything but the backend's `/api` (one exception, kept by the user at 1.2: the
  Google Fonts stylesheet for Inter and Fira Code in src/index.css); never store the API key in
  localStorage.
- No raw hex/px in components: tokens only.
- Never edit ../contracts/; a needed change is a blocked task.

## UI design
- Direction: Studio Light: calm Data Studio-adjacent workspace, dense (8/10), blue data + amber for comments.
- Tokens: src/styles/tokens.css; components use tokens only.
- Palette: bg #F8FAFC, surface #FFFFFF, surface-muted #F1F5F9, text #0F172A, text-muted #475569, border #E2E8F0, primary #1E40AF (hover #1E3A8A, on #FFFFFF), accent #D97706 (comment pins, "Apply" CTA; on #000000), success #15803D, danger #DC2626, focus ring #1E40AF.
- Type and spacing: Inter (UI), Fira Code (recipe lines, ids); 12/13/14/16/20/24 px, body 14; spacing 4/8/12/16/24/32; radius 6 controls, 10 panels; shadow only on popovers/modals.
- Layout: top bar 48 px (logo, build title, stepper, Trace, Settings); left activity column 380 px fixed (messages, run cards, activity strip at its foot; no input); stage area fills the rest; History is a single centered list (max 960 px). Stage areas: docs/staged-ui.md (change 2026-10-21).
- Activity: strip at the foot of the activity column (phrase · m:ss · tokens), 400 ms after `run.started`, in
  a reserved slot; preset checklist card in the log, last step ticks only on `run.finished` ok.
- Copy: sentence case, active voice; buttons are verbs ("Apply 3 comments"); errors say what to do next.
- States: every data view has loading, empty and error; every control has hover, focus-visible and disabled.
- Accessibility: 4.5:1 text contrast, keyboard path to every action (Esc closes popovers), visible focus ring, respects prefers-reduced-motion.
- Viewports: 1280x800 and 1440x900; screenshots in screenshots/.
- Avoid: emoji as icons, gray-on-gray text, popovers covering the element being commented, layout shift when pins appear.

## Stage settings and design briefs UI
- Settings Models tab (per-stage profiles, fallback, brief review), brief panel and Standard
  layout chip in Prototype, brief review panel, stage calls in Trace, stage-limit errors (api.md
  3.0). Full rules and visual oracle: docs/stage-settings-ui.md.

## References and feasibility UI
- Style/recreate and synthetic-data controls, explicit decisions, stale/blocked gates; Studio
  Light. Full rules and visual oracle: docs/reference-ui.md (both sections).

## Contracts
| Contract | Version | Role | Conformance check |
|---|---|---|---|
| ../contracts/api.md | 3.0 | consumes | `npm test -- contract` (fixtures/api/ and, from 16.1, fixtures/stage-settings/) |
| ../contracts/conventions.md | 1.4 | consumes | manual: port 5173, `/api` proxy to 8000 |
| ../contracts/dashboard-intent.md | 1.2 | consumes | `npm test -- contract` |
| ../contracts/synthetic-data.md | 1.2 | consumes | `npm test -- synthetic` |

## Dependencies
| Package | Registry | Version | Why | Verified |
| --- | --- | --- | --- | --- |
| react | npm | ^19.3.1 | UI | 2026-10-20 (19.3.1) |
| react-dom | npm | ^19.3.1 | UI | 2026-10-20 (19.3.1) |
| react-router-dom | npm | ^7.18.0 | two routes | 2026-10-20 (7.18.4) |
| react-markdown | npm | ^10.1.0 | chat and docs markdown | 2026-10-20 (10.1.0) |
| lucide-react | npm | ^1.59.0 | icons | 2026-10-20 (1.60.0) |
| vite | npm | ^8.3.0 | dev server + proxy | 2026-10-20 (8.3.4) |
| @vitejs/plugin-react | npm | ^6.1.0 | React in Vite | 2026-10-20 (6.1.2) |
| typescript | npm | >=5.5 <6 | types | 2026-10-20 (5.9.3) |
| tailwindcss | npm | ^4.3.0 | styling | 2026-10-20 (4.3.3) |
| @tailwindcss/vite | npm | ^4.3.0 | Tailwind v4 plugin | 2026-10-20 (4.3.3) |
| vitest | npm | ^5.0.0 | tests | 2026-10-20 (5.0.5) |
| @testing-library/react | npm | ^16.3.0 | component tests | 2026-10-20 (16.3.3) |
| jsdom | npm | ^30.1.0 | test DOM | 2026-10-20 (30.1.3) |
| @testing-library/dom | npm | ^10.4.0 | peer of @testing-library/react | 2026-10-20 (10.4.2) |
| @types/react | npm | ^19.0.0 | strict typecheck | 2026-10-20 (19.3.0) |
| @types/react-dom | npm | ^19.0.0 | strict typecheck | 2026-10-20 (19.3.0) |
