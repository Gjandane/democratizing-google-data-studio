---
type: UI Selector Set
title: Linking API entry
description: Live spike observations for creating a report.
timestamp: 2026-10-18
selectors:
  document: body
  review_accept: 'role=checkbox[name="I understand and accept the risk."]'
  review_acknowledge: 'role=button[name="Acknowledge"]'
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
