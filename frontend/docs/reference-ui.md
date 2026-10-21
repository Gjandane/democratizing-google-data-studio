# Reference and feasibility UI specification

## Controls and states
- Reuse Studio Light tokens/components; no new page. References panel in Connect and Design
  (change 2026-10-21); also reachable in Prototype, where it starts collapsed (Attach reference
  expands it) so the canvas top shows above the fold at 1280x800. No chat attach (no chat input).
- Visible radio choices: Use style / Recreate dashboard; labeled instructions textarea; native
  file chooser (drag/drop optional). Explain file limits before selection and check them before
  upload: style 1-3, recreate exactly 1 PNG/JPEG, 5 MiB each, 15 MiB total; 413/422 get
  reference-specific text, never the CSV 32 MB message. Show safe thumbnail,
  filename, saved mode/summary and Replace/Remove controls; preserve selection on upload error.
- Busy/validation errors inline, status announced once; keyboard controls, descriptive alt text,
  fixed thumbnail area to avoid layout shifts. Done: read-only with New version action.
- Feasibility panel in Blueprint (and above Build) shows each blocked requirement, plain-language reason
  (product/app/data/uncertain), source links and checked alternatives. Buttons Use this alternative
  and Drop this requirement send explicit decisions; no preselected acceptance. Clarifications
  link to the Context or Outline stage. Copy: "This app cannot animate GPS points"; never an unsupported universal claim.
  Evidence: link only http(s) entries (new tab, screen-reader text); show repo paths as mono text.
- Fetch assessment/reference set on load, reconnect, docs.updated/run.finished and successful
  mutations. A background refetch keeps the last assessment or set and its controls in place (no
  unmount, layout shift or focus loss), and the gates keep their last loaded state until it lands
  (a pending refetch may close a gate, never reopen it); loading text only before the first load.
  After an action, focus moves to the panel heading once its refetch lands. A ready assessment with no open issue is one line.
  Unchecked/unknown assessment shows Check feasibility; unresolved issues disable
  Accept blueprint/Build. Resolved stale intent enables Regenerate blueprint (or Reapply saved comments), while Build
  stays disabled until the prototype is current. Show saved batch targets/text after reload and
  an explicit Discard pending comments action. Keep old preview visibly stale; server remains authority.
  A failed GET of the assessment or reference set fails closed: ErrorState with Retry, Accept
  blueprint, Generate recipe and Build stay disabled. The mock's default assessment for fixtures.build is ready.
- APIs/fixtures: ../contracts/dashboard-intent.md 1.2 and api.md 2.0. Build/SSE guards stay exact;
  the one 1.4 change is `Source.kind` adding `synthetic` (10.1). Add node labels for
  reference_extract/reference_delete/capability_check (and synthetic_schema/synthetic_generate) to the presets.
- Verify at 1280x800 and 1440x900: empty, saved, processing, failed, blocked and stale states;
  keyboard upload/decision/removal path, focus return, long names, no horizontal overflow.

## Synthetic data controls
- In Connect with no source, show Upload/connect data and Generate sample data as explicit choices;
  reference attachment and recreate-mode schema proposal work before any CSV or interview start.
- Sample-data panel shows proposed field names/types/generators and assumptions, a JSON schema
  textarea (no typed editor; backend owns bounds), `422 invalid_generation_spec`
  field errors inline, row count (default 1,000) and seed (42).
  Label all values as invented sample data; Generate sample data is the only generation action.
  Manual schema entry works without an image; style-only references explain why a schema is needed.
- Busy feedback distinguishes Proposing schema, Generating CSV,
  Loading sample data. Keep edits after errors; no duplicate action. A generation_key binds one
  exact request: same key only for its transport retry; an edit, `409 synthetic_request_conflict`
  or retry after a failed run mints a new key; 413 says the request is over 64 KiB.
- Source row has Synthetic badge plus Download CSV. Keep sample-data banner on prototype and
  report-link view; do not imply exact screenshot values. Existing-source builds offer New dashboard
  instead of merging/replacing real data. Successful generation refreshes build/sources/docs/assessment;
  it never auto-accepts substitutions or launches a build.
- Reload/reconnect and ambiguous POST result fetch persisted jobs/status; poll active job every
  2 s, stop on terminal/unmount. Failed jobs show Retry only once cleanup is ready. Restore
  successful dataset metadata and provenance; use source.kind for labels.
  Announce status once; visible labels, keyboard path, fixed progress area.
  Visual checks at both existing viewports: no-data, proposal, editing, busy, invalid, success,
  failed with Retry (retry_ready), reload.
