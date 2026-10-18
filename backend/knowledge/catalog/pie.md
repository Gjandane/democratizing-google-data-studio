---
type: Chart Type
component_type: pie
tags:
- catalog
- pie
min_dimensions: 1
max_dimensions: 1
min_metrics: 1
max_metrics: 1
requires_date_dimension: false
min_w: 4
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

# pie

Show part-to-whole proportions for a few categories. Avoid negative values and too many slices.

Counts are conservative POC binding limits, not a complete product capability claim. Minimum sizes use grid columns and rows, not pixels. Date_dimension, breakdown, and field are separate slots, excluded from dimension counts. Metrics use explicit aggregations; count may count nonnumeric fields, while sum/avg require numeric fields.

See [product limits](../datastudio/product-limits.md).
