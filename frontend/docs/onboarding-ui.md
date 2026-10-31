# First-visit onboarding UI (change 2026-10-31, landing page revised 2026-10-31)
On the hosted link a first-time visitor lands on a separate page that shows the process and the
build in screenshots, explains how building works (the local build agent, Chrome, the one-time
code), and offers two actions and Proceed. The Build stage says why the agent is needed.
Studio Light (architecture-essentials.md#UI design); tokens and existing components only.

## When it shows
- Agent mode only: `useHosting()` gives `mode: "agent"` (api.md 3.4 `Hosting`). Local mode, or
  a failed Hosting load, shows nothing new: `/` is History as before, and `/welcome` redirects
  to `/` (replace).
- Route `/welcome` (react-router, inside AccessGate and HostingProvider like the other routes;
  `GET /api/hosting` is gated, so the landing comes after the gate).
- First visit: `/` in agent mode with `dss.onboardingSeen` unset redirects to `/welcome`
  (replace, so Back doesn't bounce). While `GET /api/hosting` is pending, `/` and `/welcome`
  show only History's loading panel ("Loading dashboards…"), never History's header or list,
  so neither page flashes before the redirect decision. History still starts its builds request
  at once (in parallel with hosting); only its header and list wait, so local mode gains no
  extra round trip. This needs a pending/failed distinction
  `useHosting()` doesn't give today (null = loading or failed): extend
  src/features/workspace/build/hosting.tsx with it, keeping `useHosting()` as is for its
  current callers.
- Seen: "Proceed to your dashboards" and "Start a new dashboard" write `dss.onboardingSeen` =
  `1` to localStorage (a boolean only; nothing else goes to storage), every access in
  try/catch. "Set up this computer" (20.2) writes nothing. When storage throws, the landing
  shows on every load, and an in-memory flag set by the same two buttons stops `/` redirecting
  again until the next load.
- Reopen: in agent mode History's header shows a secondary "How it works" button (lucide
  CircleHelp) left of "New build", always (not only after the first visit); it navigates to
  `/welcome`. Visiting `/welcome` never clears the key.
- Document title on `/welcome`: "How it works - Data Studio builder" (restored on leave, as
  WorkspaceShell does).

## Landing layout
One centered column, max 960 px (`--layout-page`, as History), page padding as History, sections
24-32 px apart. Top to bottom:
1. **Hero.** Eyebrow "Democratizing Google Data Studio" (13 px semibold, primary). h1 "Turn your
   data into a Google Data Studio dashboard" (24 px semibold). Subtitle "Design it here step by
   step. Then a small agent on your computer builds it in your own Data Studio account." (16 px,
   text-muted). A row of two buttons: primary "Start a new dashboard" (lucide Plus) opens the
   existing NewBuildDialog (creating a build navigates to it as on History); secondary "Set up
   this computer" (lucide Laptop; from 20.2) opens the setup modal (Setup modal below). After a
   passed check, "Set up this computer" is replaced by the ready line "Agent ready on this
   computer" (CircleCheck, success color) with a link button "Check again".
   At 1280x800 the hero and its buttons are fully above the fold.
2. **Screenshots.** h2 "See it in action" (20 px semibold). A 2x2 grid of figures (gap 16),
   each: the image (Panel border, radius 10, `width`/`height` attributes set so nothing shifts
   on load, `loading="lazy"`, `decoding="async"`, scaled to the cell width, never cropped), then
   a figcaption with a 24 px primary number badge (on-primary text), the title (14 px semibold)
   and the caption (13 px text-muted). Images, titles, captions and alt text are verbatim in
   Copy.
3. **How it works.** The panel of the 20.1 attempt (`.blueprint/attempts/20.1/OnboardingPanel.tsx`),
   without Hide: Panel surface, border, radius 10, padding 24; h2 "How it works" with the
   subtitle; three step cards in one row at both viewports, equal height, gap 16 (surface-muted,
   radius 10, padding 16; 24 px primary number badge, 20 px primary lucide icon, 16 px semibold
   title, 14 px body, never truncated); then "Before you start", items in a 2x2 grid (16 px icon +
   13 px text-muted, the bold part in text color).
4. **Proceed.** A row right-aligned under the panel: secondary button "Proceed to your
   dashboards" with a trailing lucide ArrowRight; it marks seen (When it shows) and navigates
   to `/`.

## Copy
Verbatim.
- Screenshots (files in `public/onboarding/`, served at `/onboarding/<file>`):
  1. `context.webp`. Title "Review the context". Caption "Confirm the KPIs and questions drafted
     from your data." Alt "The Context stage with KPI cards to confirm".
  2. `prototype.webp`. Title "Comment on the prototype". Caption "Click any chart to leave a
     comment, then apply them all at once." Alt "The Prototype stage with numbered comment pins".
  3. `build.webp`. Title "Watch the build". Caption "Each step ticks off live while the agent
     builds the report." Alt "The Build stage with recipe steps ticking off".
  4. `done.webp`. Title "Open your report". Caption "The finished dashboard opens in your own Data
     Studio." Alt "The Done stage with the link to the report in Data Studio".
- How it works subtitle: "Design a dashboard here, then build it in your own Google Data Studio."
- Steps:
  1. Icon LayoutDashboard. Title "Design it here". Body: "Upload a CSV or a screenshot, then
     confirm each stage. Nothing is built until you say so." Under it, the stage names as small
     chips (12 px, border, radius 6), in order: Connect, Context, Outline, Design, Blueprint,
     Prototype, Build (`STAGE_LABELS`, Done left out).
  2. Icon Laptop. Title "Set up this computer once". Body: "Building runs in Google Chrome on
     your computer, so the report is saved in your own Data Studio account. One copied command
     installs the build agent (a small helper and this app) and asks you to sign in to Google
     once in its own Chrome window. The first run takes a few minutes."
  3. Icon Rocket. Title "Build with a one-time code". Body: "At Build you get a code that works
     for 30 minutes and one command to paste into a terminal. The finished report opens in Data
     Studio."
- Before you start:
  - Globe: "**Google Chrome** must be installed."
  - Monitor: "**Windows** is tested. macOS and Linux are untested."
  - Lock: "Your build's data is saved as a CSV that anyone with its private link can read." (only
    when `Hosting.share_data` is true; otherwise three items)
  - Users: "Everyone with this link shares one build history."

## Screenshot assets
Task 20.1 captures them; they are product assets, not task screenshots.
- From mock mode (`VITE_MOCK=1 VITE_MOCK_HOSTED=1`, the fixture builds), headless Chrome over
  CDP (AGENTS.md Known gotchas) at a 1280x800 viewport, `Page.captureScreenshot` with
  `format: "webp"`, quality about 80; each file at most 200 KB (lower the quality, never the
  size, to fit). The view each shows: Context with its KPI cards; Prototype with at least two
  numbered pins; Build in agent mode with the job running and some recipe lines ticked; Done
  with the report link card.
- No dev overlays, focus rings, toasts or open popovers in the frame; no real data, codes or
  emails (the mock's own are fine).
- 20.2 recaptures `build.webp` the same way once the Build-stage agent note and the new JobPanel
  line are in, so the landing never shows an outdated Build view.

## Setup modal
Task 20.2.
- The landing's "Set up this computer" opens the existing Modal titled "Set up this computer",
  holding the SetupPanel flow of docs/implementation-notes.md (Setup step) unchanged in
  behavior: a new check code on open (`POST /api/agent-checks`), the two command tabs with
  `-Check`/`--check`, the 3 s poll, passed/failed/expired states, the sessionStorage boolean.
  Closing (Esc, X or Done) drops the code; reopening asks for a new one. A click on the backdrop
  never closes it (Modal gets a `closeOnBackdrop` prop, default true; this dialog passes false),
  so a visitor coming back from the terminal doesn't lose the check.
- SetupPanel props for this use (the Build stage keeps today's defaults): `startUnfolded` (open
  on the check-code flow and request a code even when `dss.agentReady` is set; the modal always
  passes it), `onState(state)` (reports `passed`, `failed`, `expired` to the landing, which shows
  or takes back the ready line; a failed recheck turns the ready line back into the button), and
  `hint` (the modal passes none, so "Already set up? Build in Data Studio." never shows on the
  landing). Inside the modal SetupPanel renders with no Panel and no title of its own (the
  Modal's title is the only "Set up this computer" heading): add the container/heading prop this
  needs. The Modal uses `size="wide"` (720 px) so the PowerShell command and the four steps fit.
- On load, the landing shows the ready line when `dss.agentReady` is set (same tab, 19.3).
- Focus on close: to whichever hero control shows after the dialog closes: "Check again" after a
  pass, "Set up this computer" when there is no pass or a recheck failed (the opener may be gone
  either way, so never rely on Modal's restore to the opener alone).
- How-to steps, added inside SetupPanel itself (so the Build stage's setup step shows them too),
  as a numbered list between the Chrome line and the tabs; it replaces SetupPanel's line "Run this
  once in a terminal on the computer you will build on. ...":
  1. "Pick your system and copy the command."
  2. "Paste it into PowerShell (Windows: Start menu, type PowerShell) or Terminal (macOS/Linux)
     and press Enter."
  3. "If a Chrome window opens, sign in to Google and accept Data Studio's terms if it asks."
  4. "Keep this page open. It shows Agent ready when the check passes."
- Passed in the modal: "Agent ready on this computer" with the four items ticked and a primary
  "Done" that closes it; the hero then shows the ready line.
- After Check again, Get a new code or Try again, focus moves to the new state's heading or
  first control, never to body (fixes 19.3's Left open P2).
- JobPanel (Build stage, agent mode): its line "Run this in a terminal on the computer signed in
  to Data Studio." becomes "Paste it into PowerShell (Windows) or Terminal (macOS/Linux) and press
  Enter. On a computer without the agent, the first run installs it and asks you to sign in to
  Google."

## Build-stage agent note
Task 20.2. In agent mode the Build stage shows, at the top of its stage area above the setup
step and the job panel, one note: lucide Info (16 px, primary) + 13 px text, surface-muted,
radius 6, padding 12, verbatim: "To continue, the build agent runs this build on your computer,
in your own Chrome. This step makes no AI calls, so it uses no AI tokens." It shows while the
stage is Build (before, during and after a failed or expired run) and not once the build is done;
never in local mode.
- Why the claim holds (checked 2026-10-31 against contracts api.md 3.4, conventions 1.7,
  recipe.md): the recipe is compiled in code (`POST /api/builds/{id}/recipe`), the agent replays
  it with `dsengine run`, and the agent's machine has no API key. The earlier stages do use model
  tokens (the app's own key), so the claim is scoped to "this step" and goes nowhere else.

## Visual oracle
- Mocks: `VITE_MOCK=1 VITE_MOCK_HOSTED=1` (agent mode, share data on); `VITE_MOCK=1` (local).
- 20.1: screenshots/20.1-landing-top-{1280,1440}.png (viewport), 20.1-landing-full-{1280,1440}.png
  (whole page), 20.1-landing-focus-1280.png (focus ring on "Start a new dashboard"),
  20.1-history-howitworks-1280.png (History header with "How it works").
- 20.2: screenshots/20.2-setup-modal-{waiting,passed,failed}-{1280,1440}.png,
  20.2-landing-ready-1280.png, 20.2-build-setup-steps-1280.png (with the agent note),
  20.2-job-steps-1280.png.
- Check each against UI design: tokens only (no raw hex or px), 4.5:1 text contrast, visible
  focus ring, hero and buttons above the fold at 1280x800, screenshot grid 2x2 with equal cells,
  three cards one row and equal height, no truncated text, no horizontal scroll, nothing
  overlapping, number badges and icons aligned on one baseline per card.
