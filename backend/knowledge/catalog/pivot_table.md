---
type: Chart Type
component_type: pivot_table
tags:
- catalog
- pivot_table
min_dimensions: 2
max_dimensions: 5
min_metrics: 1
max_metrics: 5
requires_date_dimension: false
min_w: 6
min_h: 10
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

# pivot_table

Compare a cross-tabulation. POC: first dimension is rows, second is columns; extra dimensions are nested rows.

Counts are conservative POC binding limits, not a complete product capability claim. Minimum sizes use grid columns and rows, not pixels. Date_dimension, breakdown, and field are separate slots, excluded from dimension counts. Metrics use explicit aggregations; count may count nonnumeric fields, while sum/avg require numeric fields.

See [product limits](../datastudio/product-limits.md).
