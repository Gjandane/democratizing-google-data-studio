---
type: Product Limits
tags:
- datastudio
- constraints
verified: '2026-10-19'
---

# Data Studio constraints

## Product facts
- Pie charts bind one dimension and one metric, display up to 10 slices, and can group remaining categories into Others.
  Source: [Pie chart reference](https://docs.cloud.google.com/data-studio/pie-chart-reference).
- Scatter charts compare X and Y metrics and display at most 1,000 bubbles.
  Source: [Scatter chart reference](https://docs.cloud.google.com/data-studio/scatter-chart-reference).

## POC limits (application policy, not product maxima)
- One page; canvas width 1200; 12 grid columns, 20-pixel row height, 16-pixel gutter and 24-pixel margin by default.
- Only the 12 catalog types, further narrowed by DSS_ALLOWED_TYPES. Catalog frontmatter is the validator's authority for counts and minimum grid size.
- BigQuery is the data source. Compute derived fields and joins in the BigQuery view; no report calculated fields or blends.
- Date controls need a usable date field; parse date-like strings in the view. Dropdown controls bind a dimension through field.
- Background decorations are flattened by deterministic rendering; interactive components are placed by the recipe compiler.
- Dimensions group data; metrics aggregate it. Do not sum ratios or average averages without defining the intended weighted calculation in the view.
- Product capabilities may exceed these conservative bindings. Do not enlarge the catalog based on a product feature without updating and reviewing the POC implementation.

