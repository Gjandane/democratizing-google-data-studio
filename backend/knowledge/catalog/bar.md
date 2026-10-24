---
type: Chart Type
component_type: bar
tags:
- catalog
- bar
min_dimensions: 1
max_dimensions: 1
min_metrics: 1
max_metrics: 5
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
  breakdown:
  - dimension
  field: []
---

# bar

Compare categories. Use one optional breakdown for grouped or stacked bars; prefer sorted bars for rankings. Options: orientation, stacked, stacked_percent (each bar's parts sum to 100 %, Data Studio's "100% stacked"; shows a split such as rural vs urban share).

Counts are conservative POC binding limits, not a complete product capability claim. Minimum sizes use grid columns and rows, not pixels. Date_dimension, breakdown, and field are separate slots, excluded from dimension counts. Metrics use explicit aggregations; count may count nonnumeric fields, while sum/avg require numeric fields.

See [product limits](../datastudio/product-limits.md).
