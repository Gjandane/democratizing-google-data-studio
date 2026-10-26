# Stage settings and design briefs UI (change 2026-10-26)
For ../contracts/api.md 3.0, Stage settings and design briefs. Studio Light tokens and base
components only (architecture-essentials.md#UI design); no new dependency (react-markdown and
lucide-react are already approved).

## Settings
- The modal becomes wide (max 720 px, a Modal size variant built from tokens) with two tabs:
  "Models" (first) and "Google Cloud" (API key, project, dataset, location, bucket: today's
  fields and lock behavior). The planner/worker inputs are gone.
- Models tab, top: Fallback model (select) with hint "Used when a stage's model is unavailable or
  keeps failing. Not used for limits or invalid output."; "Review each page's design brief before
  its HTML is generated" checkbox (`review_briefs`).
- Then one collapsible row per stage, in pipeline order: Interview, Reference interpretation,
  Native chart planning, HTML brief, HTML with a reference, HTML without a reference, Other model
  work (routine). A collapsed row shows the stage name, model, thinking level and an "Edited" chip
  when any field differs from `SettingsCapabilities.defaults`. One sentence under each name says
  what the stage does (for example HTML brief: "Argon writes the full design brief Flash follows,
  for pages with and without a reference").
- Expanded fields: Model (select of `models`; an option shows "unavailable" when `available` is
  false and "availability unknown" when null; both stay selectable), Thinking (select of that
  model's `thinking_levels`). Interview and routine add only Request timeout (s). Generation stages
  add Input tokens, Output tokens (hint "Thinking counts toward this limit"), Total time (s) (hint
  per action or per page, from the stage), Transport retries, Validation repairs, and an
  "Advanced" disclosure with Input count margin (%). Validation repairs use the per-stage bounds in
  `limits.validation_repairs`; a stage bounded [0,0] (reference interpretation) shows "0 (this
  stage has no repair step)" read-only. HTML without a reference adds "Use the
  standard layout when the designed page still fails its checks" (`layout_fallback`).
- Numbers: integer inputs with min/max from `limits` and the selected model's
  `max_input_tokens`/`max_output_tokens`; invalid text stays only while focused (artifact-editor
  rule) and blocks Save with the field's message. Changing a model never changes another field: a
  thinking level or cap the new model doesn't support shows an issue on that field (no silent
  downgrade).
- "Reset to defaults" per stage copies that stage's defaults into the draft (saved on Save).
- `Settings.issues` (for example a migrated unknown model id) show on their fields when the tab
  opens, with the row expanded; they never block saving another field.
- Cost (user request 2026-10-26): each generation stage row shows "Up to $X per call (estimated)"
  = input tokens x input rate + output tokens x output rate from the model's `price` (long-context
  rates when input tokens exceed `long_context_over`), updated as the draft changes; "Cost unknown"
  when `price` is null. A footnote under the stage list: "Estimates from Google's list prices
  checked on <checked_on>. Actual billing may differ." Interview and routine show no estimate
  (their caps are per step). No prices are hardcoded in the frontend.
- Save sends only changed fields (deep per stage/field), once; `422 invalid_settings` maps each
  `detail.issues[].path` to its field (the stage row expands, focus moves to the first issue);
  an unknown path shows above the form. `notices` render as status lines at the top of the tab.
- Agent mode (`403 settings_locked`): the Google Cloud tab fields lock as today; the Models tab
  stays editable.
- States: loading, error with Retry (settings or capabilities fail -> the tab shows the error,
  never default values as if saved); saving disables Save only; "Settings saved." announced once.
- Opening Settings at a stage (from a stage-limit error) selects the Models tab, expands that
  stage and focuses its first relevant field (input tokens, output tokens, total time or model).

## Design briefs
- Prototype stage, per page tab: a "Design brief" button opens a side panel (440 px, popover
  shadow) with the brief's Markdown (react-markdown, no raw HTML), a meta line "Brief by <model> ·
  HTML by <model> · Generated|Edited · <first 8 of sha256>", and Download .md / Download .json
  (links to `/api/builds/{id}/files/brief_p<n>.md|json` with `download`). A page with no brief
  (made before 3.0) shows "No saved brief for this page".
- A page with layout `standard` shows a "Standard layout" chip on its tab and a one-line note in
  the panel: `layout_fallback` -> "The designed page still failed its checks after its repairs, so
  this page uses the standard layout (switch in Settings, HTML without a reference)";
  `not_designed` -> "This page uses the standard layout." Text, not color alone.
- Data: `GET design-pages` on load, reconnect, `prototype.updated`, `brief.review` and the
  `run.finished` of a prototype/revise run; a background refetch keeps the last content.

## Brief review
- When `DesignPages.review` is non-null, WorkspaceShell shows the review panel at the top of the
  stage area, whatever the stage: heading "Review the design brief · Page n of m", text "HTML
  generation waits for you. Edit the design text; components and data stay fixed."
- Body: Overall (textarea) then one block per component: label, type and id (mono, read-only) and
  its Treatment (textarea). Textareas grow with content; no character limit.
- Save on blur, serialized like the artifact editors (a response never overwrites newer typing);
  `issues` land on their path (`/overall`, `/slots/<i>/treatment`; `""` above the form); the footer
  counts open issues.
- Footer: Approve and generate HTML (primary; disabled while a save is pending or failed, with
  issues, or when stale), Cancel run (secondary, a confirm modal "Discard this prototype run?
  Nothing is published; pending comments stay."), Download .md (a Blob of `brief.markdown`).
- Save sends the review's current `revision`; Approve sends `revision` and the `sha256` on screen.
  A `409 brief_review_conflict` refetches the review and shows "This brief changed in another
  window. Check it, then approve again." with the new text (typing in progress is kept in the
  field only if it was not yet saved, and flagged). A repeated approve after a lost response just
  shows the run it returns.
- Stale (`stale` or `409 brief_review_stale`): a warning line "The build changed after this brief
  was written. Cancel and run it again." with only Cancel enabled.
- While a review waits, every mutating control in the workspace is disabled with the reason
  "Waiting for your brief review" (the run-lock pattern); a `409 brief_review_pending` from any
  action refetches design-pages and shows the panel. Settings stays usable.
- Run card: a run that emitted `brief.review` ends with the step "Paused for brief review" (no
  final success tick); approving starts a new run card under the same node.
- Reload restores the panel from `GET design-pages`; cancel refetches the build.

## Stage calls and stage-limit errors
- Trace modal: each run row expands (lazy `GET /api/traces/{run_id}/calls`) to "Settings used"
  (one line per stage: model, thinking, caps, time, retries/repairs; "Not recorded" when null) and
  "Stage calls" (with an Est. cost column: "$0.0442", "<$0.0001", "unknown" when null).
  Stage, Page, Attempt ("2 · try 3"), Model (requested -> actual with a "Fallback" chip),
  Thinking, Input (measured / enforced / limit), Output (answer · thinking · limit; null shows
  "unknown", never 0), Outcome, Time. Loading, empty ("No model calls in this run") and error.
- Cost in Trace: the modal header shows "Estimated cost of this build: $X" from
  `GET /api/builds/{id}/cost` ("at least $X" plus "Some calls have no price or thinking count"
  when not complete; "unknown" when null), with "Prices checked <date>. Actual billing may
  differ."; each run row gets an Est. cost cell from that response (by run_id; runs before 3.0
  marked "from run totals"). Refetch on open and after each `run.finished`.
- A `run.finished` error whose code (text before the first ":") is `stage_input_over_limit`,
  `stage_output_cutoff`, `stage_timeout` or `stage_model_unavailable` shows the message after the
  code with "Adjust in Settings" (opens Settings at the StageId that starts the message) and
  "View model calls" (opens Trace at that run); `brief_invalid`/`html_invalid` show the message and
  "View model calls". Other errors keep today's text.

## Visual oracle
- Screenshots at 1280x800 and 1440x900 in screenshots/: 16.2-settings-{models,stage-open,issue},
  16.3-{brief-panel,standard-chip}, 16.4-{review,review-stale}, 16.5-{trace-calls,limit-error}; each
  checked against this page and the UI design section (density, contrast, focus ring, no layout
  shift, nothing clipped, text not color alone).
