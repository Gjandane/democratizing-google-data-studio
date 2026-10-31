# First-visit onboarding UI (change 2026-10-31)
On the hosted link a first-time visitor learns, on the home page and before any build, that
building into their own Data Studio needs the local build agent, and can set it up there.
Studio Light (architecture-essentials.md#UI design); tokens and existing components only.

## When it shows
- Agent mode only: `useHosting()` gives `mode: "agent"` (api.md 3.4 `Hosting`). Local mode, a
  Hosting still loading, or a failed Hosting load shows nothing new: History stays as it is.
- Shown expanded until the visitor hides it. "Hide" writes `dss.onboardingHidden` = `1` to
  localStorage (a boolean only; nothing else goes to storage), every access in try/catch: when
  storage throws, the panel still shows on load and Hide hides it until the next load.
- Hidden: a secondary "How it works" button (lucide CircleHelp) sits left of "New build" in the
  History header; it reopens the panel and removes the key. The button shows only while hidden.
- Focus: Hide moves focus to "How it works"; reopening moves it to the panel's heading.

## Panel layout
On the History page, between the header and the builds list.
- Full list width (max 960 px), Panel surface, border, radius 10, padding 24; above the list,
  and above History's loading, error and empty states (those states and their CTAs stay).
- Header row: h2 "How it works" (20 px semibold) with the subtitle "Design a dashboard here, then
  build it in your own Google Data Studio." (14 px, text-muted); a ghost "Hide" button with an X
  icon on the right (accessible name "Hide how it works").
- Three step cards in one row at both viewports, equal height, gap 16: surface-muted background,
  radius 10, padding 16; each has a 24 px primary number badge (on-primary text), a lucide icon
  (20 px, primary), a title (16 px semibold) and the body text (14 px). Never truncated.
- Below the cards: a "Before you start" row, four items in a 2x2 grid (lucide icon 16 px +
  13 px text-muted, the bold part in text color).
- At 1280x800 with the panel open, the top edge of the first build row is above the fold.

## Copy
Verbatim.
1. Icon LayoutDashboard. Title "Design it here". Body: "Upload a CSV or a screenshot, then
   confirm each stage. Nothing is built until you say so." Under it, the stage names as small
   chips (12 px, border, radius 6), in order: Connect, Context, Outline, Design, Blueprint,
   Prototype, Build (`STAGE_LABELS`, Done left out).
2. Icon Laptop. Title "Set up this computer once". Body: "Building runs in Google Chrome on your
   computer, so the report is saved in your own Data Studio account. One copied command installs
   the build agent (a small helper and this app) and asks you to sign in to Google once in its own Chrome
   window. The first run takes a few minutes." Then (from 20.2) the primary button "Set up this
   computer", or, after a passed check, a success line "Agent ready on this computer" (CircleCheck,
   success color) with a link button "Check again" that opens the setup modal.
3. Icon Rocket. Title "Build with a one-time code". Body: "At Build you get a code that works for
   30 minutes and one command to paste into a terminal. The finished report opens in Data
   Studio."
- Before you start:
  - Globe: "**Google Chrome** must be installed."
  - Monitor: "**Windows** is tested. macOS and Linux are untested."
  - Lock: "Your build's data is saved as a CSV that anyone with its private link can read." (only
    when `Hosting.share_data` is true; otherwise the grid has three items)
  - Users: "Everyone with this link shares one build history."

## Setup modal
Task 20.2.
- "Set up this computer" opens the existing Modal titled "Set up this computer", holding the
  SetupPanel flow of docs/implementation-notes.md (Setup step) unchanged in behavior: a new check
  code on open (`POST /api/agent-checks`), the two command tabs with `-Check`/`--check`, the 3 s
  poll, passed/failed/expired states, the sessionStorage boolean. Closing (Esc, X or Done) drops
  the code; reopening asks for a new one. A click on the backdrop never closes it (Modal gets a
  `closeOnBackdrop` prop, default true; this dialog passes false), so a visitor coming back from
  the terminal doesn't lose the check.
- SetupPanel props for this use (the Build stage keeps today's defaults): `startUnfolded` (open
  on the check-code flow and request a code even when `dss.agentReady` is set; the modal always
  passes it), `onState(state)` (reports `passed`, `failed`, `expired` to the panel, which shows or
  takes back the ready line; a failed recheck turns step 2 back into the button), and `hint` (the
  modal passes none, so "Already set up? Build in Data Studio." never shows on History). Add a
  container or heading-level prop only if the Panel wrapper doesn't fit inside the Modal.
- Focus on close: back to the control that opened the dialog; after a pass that control is gone
  (the button became the ready line), so focus goes to step 2's "Check again".
- How-to steps, added inside SetupPanel itself (so the Build stage's setup step shows them too),
  as a numbered list between the Chrome line and the tabs; it replaces SetupPanel's line "Run this
  once in a terminal on the computer you will build on. ...":
  1. "Pick your system and copy the command."
  2. "Paste it into PowerShell (Windows: Start menu, type PowerShell) or Terminal (macOS/Linux)
     and press Enter."
  3. "If a Chrome window opens, sign in to Google and accept Data Studio's terms if it asks."
  4. "Keep this page open. It shows Agent ready when the check passes."
- Passed in the modal: "Agent ready on this computer" with the four items ticked and a primary
  "Done" that closes it; the panel's step 2 then shows the ready line.
- After Check again, Get a new code or Try again, focus moves to the new state's heading or
  first control, never to body (fixes 19.3's Left open P2).
- JobPanel (Build stage, agent mode): its line "Run this in a terminal on the computer signed in
  to Data Studio." becomes "Paste it into PowerShell (Windows) or Terminal (macOS/Linux) and press
  Enter. On a computer without the agent, the first run installs it and asks you to sign in to
  Google."

## Visual oracle
- Mocks: `VITE_MOCK=1 VITE_MOCK_HOSTED=1` (agent mode, share data on); `VITE_MOCK=1` (local).
- 20.1: screenshots/20.1-onboarding-{open,hidden,empty}-{1280,1440}.png and
  20.1-onboarding-focus-1280.png (focus ring on Hide).
- 20.2: screenshots/20.2-setup-modal-{waiting,passed,failed}-{1280,1440}.png,
  20.2-history-ready-1280.png, 20.2-build-setup-steps-1280.png, 20.2-job-steps-1280.png.
- Check each against UI design: tokens only (no raw hex or px), 4.5:1 text contrast, visible
  focus ring, three cards one row and equal height, no truncated text, no horizontal scroll,
  nothing overlapping, number badges and icons aligned on one baseline per card.
