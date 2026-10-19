# Reference and feasibility UI specification

## Controls and states
- Reuse Studio Light tokens/components; no new page. References panel in Connect and Interview;
  also reachable in Prototype. Chat has an Attach reference button opening the same panel.
- Visible radio choices: Use style / Recreate dashboard; labeled instructions textarea; native
  file chooser (drag/drop optional). Explain file limits before selection. Show safe thumbnail,
  filename, saved mode/summary and Replace/Remove controls; preserve selection on upload error.
- Busy/validation errors inline, status announced once; keyboard controls, descriptive alt text,
  fixed thumbnail area to avoid layout shifts. Done: read-only with New version action.
- Feasibility panel above Generate/Build shows each blocked requirement, plain-language reason
  (product/app/data/uncertain), source links and checked alternatives. Buttons Use this alternative
  and Drop this requirement send explicit decisions; no preselected acceptance. Clarifications
  link/focus chat. Copy: "This app cannot animate GPS points"; never an unsupported universal claim.
- Fetch assessment/reference set on load, reconnect, docs.updated/run.finished and successful
  mutations. Unchecked/unknown assessment shows Check feasibility; unresolved issues disable
  Generate/Build. Resolved stale intent enables Replan (or Reapply saved comments), while Build
  stays disabled until the prototype is current. Show saved batch targets/text after reload and
  an explicit Discard pending comments action. Keep old preview visibly stale; server remains authority.
- APIs/fixtures: ../contracts/dashboard-intent.md and api.md 1.3. Legacy Build/SSE exact guards
  unchanged; add node labels for reference_extract/capability_check to existing activity presets.
- Verify at 1280x800 and 1440x900: empty, saved, processing, failed, blocked and stale states;
  keyboard upload/decision/removal path, focus return, long names, no horizontal overflow.

## Synthetic data controls
- In Connect with no source, show Upload/connect data and Generate sample data as explicit choices;
  reference attachment and recreate-mode schema proposal work before any CSV or interview start.
- Sample-data panel shows proposed field names/types/generators and assumptions, editable typed
  values or JSON advanced editor with inline field errors, row count (default 1,000) and seed (42).
  Label all values as invented sample data; Generate sample data is the only generation action.
  Manual schema entry works without an image; style-only references explain why a schema is needed.
- Reuse tokens/base inputs/panels. Busy feedback distinguishes Proposing schema, Generating CSV,
  Loading sample data. Keep edits after errors. Disable duplicate action and reuse generation_key
  for transport retry; explicit retry after failed run uses a new key.
- Source row has Synthetic badge plus Download CSV. Keep sample-data banner on prototype and
  report-link view; do not imply exact screenshot values. Existing-source builds offer New dashboard
  instead of merging/replacing real data. Successful generation refreshes build/sources/docs/assessment;
  it never auto-accepts substitutions or launches a build.
- Reload/reconnect and ambiguous POST result fetch persisted jobs/status; poll active job every
  2 s, stop on terminal/unmount. Failed jobs show Retry only once cleanup is ready. Restore
  successful dataset metadata and provenance; use source.kind for labels.
  Announce error/status once; visible labels, keyboard editing/generate/download, fixed progress area.
  Visual checks at both existing viewports: no-data, proposal, editing, busy, invalid, success, reload.
