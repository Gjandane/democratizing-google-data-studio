---
type: Chart Type
component_type: fixed_size_list
tags:
- catalog
- fixed_size_list
min_dimensions: 0
max_dimensions: 0
min_metrics: 0
max_metrics: 0
requires_date_dimension: false
min_w: 3
min_h: 4
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

# fixed_size_list

Filter by one categorical field bound through field, not dimensions, with every value listed as a checkbox inside the box (Data Studio's fixed-size list). Prefer it to a dropdown when the field has a few values the reader should see at once. No metrics.

Minimum size: dropdown's width and four rows' height (the docs give none). Counts are conservative POC binding limits, not a complete product capability claim. Minimum sizes use grid columns and rows, not pixels. Date_dimension, breakdown, and field are separate slots, excluded from dimension counts.

See [product limits](../datastudio/product-limits.md).
