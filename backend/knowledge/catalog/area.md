---
type: Chart Type
component_type: area
tags:
- catalog
- area
min_dimensions: 0
max_dimensions: 0
min_metrics: 1
max_metrics: 5
requires_date_dimension: true
min_w: 6
min_h: 8
slot_roles:
  dimensions:
  - dimension
  metrics:
  - metric
  date_dimension:
  - dimension
  breakdown:
  - dimension
  field: []
---

# area

Show how totals and their parts change over time: one filled area per metric, or per breakdown value with one metric. Bind the time axis through date_dimension; dimensions is empty. Options: stacked (areas on top of each other), stacked_percent (each date's parts sum to 100 %, Data Studio's "100% stacked"). Like a time series, a date bucket field draws one point per bucket.

Counts and minimum sizes mirror time_series (the area chart reference states no metric limit). Counts are conservative POC binding limits, not a complete product capability claim. Minimum sizes use grid columns and rows, not pixels. Date_dimension, breakdown, and field are separate slots, excluded from dimension counts. Metrics use explicit aggregations; count may count nonnumeric fields, while sum/avg require numeric fields.

See [product limits](../datastudio/product-limits.md).
