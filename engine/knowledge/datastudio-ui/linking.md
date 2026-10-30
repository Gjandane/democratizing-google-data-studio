---
type: UI Selector Set
title: Linking API entry
description: Live spike observations for creating a report.
timestamp: 2026-10-29
selectors:
  document: body
  review_dialog: 'role=dialog[name="Review data access"s]'
  review_accept: 'role=checkbox[name="I understand and accept the risk."]'
  review_acknowledge: 'role=button[name="Acknowledge"s]'
  loading: 'role=progressbar'
  linking_error: 'role=dialog[name="Something went wrong when building your report"]'
---

The document selector is used for diagnostic accessibility snapshots only.

Live observation (2026-10-18): a blank create URL with `ds.ds0` reaches the
data-access review, then fails with "ds0 is not a valid data source alias for
this report." No template ID was configured. A template with a compatible
data source alias is required before the chart spike can proceed. Do not
interpret disappearance of the progress indicator as successful creation.

Resumed spike: with DSS_TEMPLATE_REPORT_ID configured, the same ds0 override
opens an editable report and loads the order_items fields. The template ID
stays in environment configuration. The initial risk acknowledgement appears
on each create; another acknowledgement is needed when first saving.

Review dialog (2026-10-21): Data Studio may show the create-time "Review data
access" dialog without the "I understand and accept the risk." checkbox. Detect
the dialog by its exact name (the save dialog's name starts with the same
words), tick the checkbox only when present, and click the dialog's own exact
Acknowledge button; never Close. `review_accept` and `review_acknowledge` are
looked up inside the dialog.

Controls can render after the dialog becomes visible. Poll the scoped checkbox
and button within the existing deadline; check a visible unchecked checkbox,
and click only once Acknowledge is enabled. A checkbox-free dialog may also
enable its button later. Never use a disabled-button click as the readiness wait.

GCS CSV source (2026-10-29, recipe 1.4, task 14.1): the create link with
`ds.ds0.connector=googleCloudStorage&ds.ds0.pathType=FILE&ds.ds0.path=<bucket>/<path>.csv`
and the template opens the editor with no `GCP_PROJECT_ID`. The account could
already read the bucket: only the usual create-time "Review data access" dialog
appeared, no "Authorize" prompt, so the prompt's name and selectors are still
unobserved (task 14.2 covers setup). Inferred types from a 10-column CSV:
`YYYY-MM-DD` -> Date (`type_datetime`), country names -> Geo (`type_geo`),
integers and `95.00` decimals -> Number (`type_numeric`), other strings -> Text.
Every CSV column is a dimension chip; only Record Count is a metric chip, and
`sum`/`avg` aggregation in charts works on the Number columns.

No template (2026-10-31, recipe 1.5, task 15.1): the un-aliased create link
(`ds.connector=googleCloudStorage&ds.pathType=FILE&ds.path=...`, no `c.reportId`)
opens Data Studio's default report on the GCS CSV. Page 1 already holds three
starter components (`components`): a text title naming the connector ("Google
Cloud Storage"), a table (first text column + Record Count) and a bar chart
(country + Record Count). They render with the canvas, before any recipe op.
`open_report` clicks the empty workspace, presses Ctrl/Cmd+A then Delete (no
confirmation), and waits until `components` is empty. No review dialog appeared
for this already-acknowledged account.
