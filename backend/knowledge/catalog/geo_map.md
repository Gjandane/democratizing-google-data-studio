---
type: Chart Type
component_type: geo_map
tags:
- catalog
- geo_map
min_dimensions: 1
max_dimensions: 1
min_metrics: 1
max_metrics: 1
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

# geo_map

Show geography with a geographic dimension. Ensure source field geographic semantics are configured; ordinary category strings are insufficient.

Counts are conservative POC binding limits, not a complete product capability claim. Minimum sizes use grid columns and rows, not pixels. Date_dimension, breakdown, and field are separate slots, excluded from dimension counts. Metrics use explicit aggregations; count may count nonnumeric fields, while sum/avg require numeric fields.

See [product limits](../datastudio/product-limits.md).
