---
type: Chart Type
component_type: table
tags:
- catalog
- table
min_dimensions: 1
max_dimensions: 10
min_metrics: 1
max_metrics: 10
requires_date_dimension: false
min_w: 6
min_h: 8
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

# table

Show exact values and detail. Keep labels legible; pre-aggregate large datasets.

Counts are conservative POC binding limits, not a complete product capability claim. Minimum sizes use grid columns and rows, not pixels. Date_dimension, breakdown, and field are separate slots, excluded from dimension counts. Metrics use explicit aggregations; count may count nonnumeric fields, while sum/avg require numeric fields.

See [product limits](../datastudio/product-limits.md).
