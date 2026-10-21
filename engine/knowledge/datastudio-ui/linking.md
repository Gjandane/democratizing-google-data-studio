---
type: UI Selector Set
title: Linking API entry
description: Live spike observations for creating a report.
timestamp: 2026-10-21
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
