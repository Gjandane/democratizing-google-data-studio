---
type: Chart Type
component_type: scorecard
tags:
- catalog
- scorecard
min_dimensions: 0
max_dimensions: 0
min_metrics: 1
max_metrics: 1
requires_date_dimension: false
min_w: 2
min_h: 3
slot_roles:
  dimensions:
  - dimension
  metrics:
  - metric
  date_dimension:
  - dimension
  breakdown: []
  field: []
---

# scorecard

Show one headline KPI with a clear unit and aggregation.

Counts are conservative POC binding limits, not a complete product capability claim. Minimum sizes use grid columns and rows, not pixels. Date_dimension, breakdown, and field are separate slots, excluded from dimension counts. Metrics use explicit aggregations; count may count nonnumeric fields, while sum/avg require numeric fields.

See [product limits](../datastudio/product-limits.md).
