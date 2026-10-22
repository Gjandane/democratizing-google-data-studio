# Change request 2026-10-22: AI-designed page backgrounds (user)

Written by the builder after task 19.3 so the architect can think it through. The user's request
comes first; the measured facts and conflicts follow. No design decision has been made.

## What the user asked
1. Can the background image be the same size in the first place, so nothing stretches it?
2. Use the background for headers and titles as much as possible. That means fewer recipe steps,
   and AI-generated HTML backgrounds look far better than manual boxes and text boxes. Put
   custom icons etc. in the background too.
3. The HTML/UI the app generates today is too simple and not aesthetic. `gemini-4-argon` should
   generate the HTML. Improve the prompt that creates the HTML dashboard, and add a proper
   design skill that the agent loads to generate it.
4. Target look: `docs/change-2026-10-22-reference.webp`. It has a light gray page and white cards
   with soft shadows and rounded corners. KPI cards have pastel icon tiles (people, document,
   clock, gear) and a chevron. Section cards have a title and a control slot top right, around a
   chart area or a table frame. The header has a bold title, a subtitle and filter controls.

This supersedes 19.3's idea of moving heading text out of the background into native Data Studio
text. The user rejected that idea: titles stay in the background.

## Facts measured in 19.3 (question 1)
- Data Studio doesn't stretch the background. In view mode the img box is the canvas size
  (1200 x 532 CSS px for b_a8ace098d03b page 1), with an identity transform, in both 1920 and
  1366 px windows. naturalWidth equals the file width (3600 at 3x; report e24616ea).
- The viewer turns CSS px into screen pixels: OS display scaling and browser zoom (1.25, 1.5,
  2 ...). A 1200 px file is 1:1 only at 100%; at 150% the browser stretches it 1.5x, which is
  the likely cause of the soft pre-19.1 1x look. A 3x file covers up to 300% by shrinking, and
  shrinking costs little quality.
- What stays soft at 100% is text: raster text shrunk 3:1 loses font hinting. Data Studio also
  places the canvas on a half pixel (x = 488.5 in a 1920 window), which resamples every edge.
  A bigger or smaller file fixes neither.
- "Same size" in screen pixels can't be known when the report is built, because it depends on
  each viewer's screen. The levers are the file scale (now 3x) and the canvas size (now 1200
  wide). A larger canvas (e.g. 1920) is designed at full-HD CSS size, but it changes the
  Layout grid, every component size and the fixtures. Check with the user what they mean by
  "same size" before choosing.

## What it conflicts with (needs the user's approval)
- docs/PRD.md Non-goals: "No LLM-generated HTML or recipe text (deterministic renderers only)."
- docs/architecture-essentials.md Never do: "Never let an LLM produce HTML, ...".
- docs/architecture.md#Prototype renderer: decorations come from code (`render/kits.py`,
  `Decoration.kind` band/panel/title/subtitle/text/logo/divider). It also sets the text-fit rule
  and the protected synthetic footer.
- PRD Goals assign `gemini-4-argon` to blueprint only.

## What any design must keep
- Data components stay native Data Studio objects placed on top of the background at the
  Layout boxes (charts, scorecards, controls). Cards may sit behind them; text and icons must
  not sit under them.
- One `background_p<n>.png` per page, at 3x and under 2 MB. The recipe box equals the canvas.
  The compiler stays deterministic (same spec gives the same bytes). The spec stays the source
  of truth.
- Text must fit its box: never bake a clipped heading, and keep the synthetic footer.
- Chromium would render the LLM's HTML. So: no scripts, no external fetches (inline assets
  only), a sanitizer, and a fallback to the code kit when validation fails.
- Budgets: render + background for a 12-component spec within 15 s, and the planner's 120 s
  deadline. A revise that only moves boxes re-queries nothing today. Decide whether it would
  regenerate the HTML, and what that costs.
- The ../contracts/api.md "Prototype HTML" contract: `data-cid`/`data-label`/`data-kind` on
  every component and decoration, and `section[data-page]`. The frontend preview should show
  the same designed background.
- No new dependency without a Verified row (for example an icon set; check its licence).

## Open questions for the architect
- Who writes what:
  - (A) The planner writes the decoration-layer HTML/CSS into fixed slots (the user's ask),
    with code validation and a kit fallback.
  - (B) The planner writes a richer design JSON (card style, an icon per section, a header
    variant) that an upgraded code kit renders.
  - (C) A hybrid of the two.
- Icons: SVG drawn by the LLM, or a vetted inline-SVG icon set.
- Where the design skill lives (`skills/<name>.md`, loaded by `harness/context.py`) and its
  prompt version (`prompts/v1/`). Which node and action generates the design: Design confirm,
  Blueprint or prototype.
- How to judge quality: the user approves against the reference image. `skills/ux-audit.md`
  already exists.
