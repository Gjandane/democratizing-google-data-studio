---
type: Chart Type
component_type: dropdown
tags:
- catalog
- dropdown
min_dimensions: 0
max_dimensions: 0
min_metrics: 0
max_metrics: 0
requires_date_dimension: false
min_w: 3
min_h: 2
slot_roles:
  dimensions:
  - dimension
  metrics:
  - metric
  date_dimension:
  - dimension
  breakdown: []
  field:
  - dimension
---

# dropdown

Filter by one categorical field bound through field, not dimensions. No metrics.

Counts are conservative POC binding limits, not a complete product capability claim. Minimum sizes use grid columns and rows, not pixels. Date_dimension, breakdown, and field are separate slots, excluded from dimension counts. Metrics use explicit aggregations; count may count nonnumeric fields, while sum/avg require numeric fields.

See [product limits](../datastudio/product-limits.md).
