# Staged workflow UI (change 2026-10-21)
Stage areas for ../contracts/api.md 2.0, in Studio Light (architecture-essentials.md#UI design).

## Stage areas
- Connect (archetype, sources, "About this data" notes, "Draft context")
- Context (dataset summaries, KPI cards editable in place with field/agg selects or ratio pickers, derived fields in mono, thresholds, glossary, inline issues, "Confirm context")
- Outline (sections with question checkboxes, Recommended badge, rationale, KPI chips, Suggest more, Other text per section, "n of 24 selected", "Confirm outline")
- Design (preset cards with swatches, palette chips with hex input, font select, single/per-section, density, title/subtitle, mini preview, "Confirm design")
- Blueprint (table question -> chart icon -> fields -> page -> status, Feasibility panel for blocked rows, "Regenerate", "Accept blueprint")
- Prototype (page tabs, scaled iframe, pins, pending list)
- Build (recipe ops, live status)
- Done (link card, versions, "New version")

## Layout per stage (stage area about 900 px wide at 1280, beside the 380 px activity column)
- Every stage: a header row (stage title, artifact state badge, revision), a scrolling body, and a
  sticky footer with the primary action (Confirm ... / Accept blueprint) on the right and the
  secondary actions (Redraft, Re-propose, Reset to preset, Regenerate) on the left.
- Context: dataset summaries as a compact list; KPI cards in a 2-column grid at 1440, 1 column
  at 1280; derived fields, thresholds and glossary as collapsible tables below; each issue sits on
  its card next to the field it names, and the footer counts open issues.
- Outline: one collapsible group per section (title, purpose, "k of n selected"); questions as
  full-width checkbox rows with the Recommended badge, KPI chips and the rationale as muted text;
  Suggest more and the Other textarea at the end of each group; with 6 sections x 6 questions the
  body scrolls, the sticky footer keeps "n of 24 selected" and Confirm in view.
- Design: preset cards in a 3-column grid; the editable fields beside a mini preview (header band,
  one scorecard, one bar) that updates on every change.
- Blueprint: a table (question, chart type icon + label, fields, page, status) grouped by page;
  blocked rows expand into the Feasibility panel inline.
- Run in progress (the build's lock is held): every mutating control is disabled with the
  activity strip's phrase as its reason; read-only content stays visible.
- Accept fails: the stage stays Blueprint, an ErrorState above the table shows the run error and
  Retry; the old prototype, if any, stays reachable from the stepper marked stale.
- Moving back (editing an earlier step): later steps show a stale badge with "Changed: <step>";
  a stale prototype stays visible, with a banner and Build disabled until a new accept.

## Stepper and states
- Stepper: each artifact step shows draft/confirmed/stale; a confirmed earlier step reopens for editing (api.md 2.0 Stage rules move the stage back); stale steps show why.
- Every stage area has loading, empty and error states; actions that start a run show it in the
  activity column (run card + strip); `artifact.updated` refetches only that artifact.
- User-chosen colors appear only as data swatches and in the design mini preview (inline style);
  each swatch carries its hex as text.
