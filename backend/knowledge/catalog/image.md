---
type: Chart Type
component_type: image
tags:
- catalog
- image
min_dimensions: 0
max_dimensions: 0
min_metrics: 0
max_metrics: 0
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

# image

Use image_path for a supplied local asset. No datasource slots.

Counts are conservative POC binding limits, not a complete product capability claim. Minimum sizes use grid columns and rows, not pixels. Date_dimension, breakdown, and field are separate slots, excluded from dimension counts. Metrics use explicit aggregations; count may count nonnumeric fields, while sum/avg require numeric fields.

See [product limits](../datastudio/product-limits.md).
