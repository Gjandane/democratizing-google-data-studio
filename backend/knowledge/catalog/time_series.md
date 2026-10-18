---
type: Chart Type
component_type: time_series
tags:
- catalog
- time_series
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

# time_series

Show change over time. Bind the time axis through date_dimension; dimensions is empty. Use breakdown for one optional category.

Counts are conservative POC binding limits, not a complete product capability claim. Minimum sizes use grid columns and rows, not pixels. Date_dimension, breakdown, and field are separate slots, excluded from dimension counts. Metrics use explicit aggregations; count may count nonnumeric fields, while sum/avg require numeric fields.

See [product limits](../datastudio/product-limits.md).
