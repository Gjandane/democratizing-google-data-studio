---
type: Product Limits
tags:
- datastudio
- constraints
verified: '2026-10-20'
---

# Data Studio constraints

## Product facts
- Pie charts bind one dimension and one metric, display up to 10 slices, and can group remaining categories into Others.
  Source: [Pie chart reference](https://docs.cloud.google.com/data-studio/pie-chart-reference).
- Scatter charts compare X and Y metrics and display at most 1,000 bubbles.
  Source: [Scatter chart reference](https://docs.cloud.google.com/data-studio/scatter-chart-reference).
- Bar and column charts can be vertical or horizontal; stacking needs a breakdown dimension, and a breakdown dimension limits the chart to one metric.
  Source: [Bar chart and column chart reference](https://docs.cloud.google.com/data-studio/bar-chart-and-column-chart-reference).
- Time series charts plot a time dimension and show up to five metrics.
  Source: [Time series reference](https://docs.cloud.google.com/data-studio/time-series-reference).
- Geo charts need a geo dimension such as Country, Region or City; Google Maps bubble maps also accept latitude/longitude fields.
  Sources: [Geo chart reference](https://docs.cloud.google.com/data-studio/geo-chart-reference), [Google Maps reference](https://docs.cloud.google.com/data-studio/google-maps-reference).
- Custom canvas sizes range from 10x10 to 2000 wide by 10,000 high pixels; reports can have several pages.
  Source: [Report and page layout](https://docs.cloud.google.com/data-studio/report-and-page-layout).
- Data freshness for BigQuery is a cached refresh, from every minute to every 12 hours.
  Source: [Manage data freshness](https://docs.cloud.google.com/data-studio/manage-data-freshness).
- Cross-filtering, drill actions and community (custom JavaScript) visualizations exist in the product.
  Sources: [Chart cross-filtering](https://docs.cloud.google.com/data-studio/chart-cross-filtering), [Add drill actions to charts](https://docs.cloud.google.com/data-studio/add-drill-actions-to-charts), [Community visualizations](https://developers.google.com/data-studio/visualization).
- The documentation checked describes no animation, time-lapse playback or real-time streaming. Silence means unknown native support, not proof of absence.

## Capability registry
The curated registry `knowledge/datastudio/capabilities.json` (validated by `src/dss/spec/capabilities.py`) classifies every recipe 1.0 type, option and style key, plus negative cases (animation, streaming, community visualizations, interactions, multiple pages). Each record keeps native product evidence (official documentation above) separate from app evidence (`contracts/recipe.md`, its schema or a contract fixture). Native support without app evidence is unavailable in this app. DSS_ALLOWED_TYPES only narrows it. Refresh evidence deliberately in a build review; nothing searches the web at runtime.

## POC limits (application policy, not product maxima)
- One page; canvas width 1200; 12 grid columns, 20-pixel row height, 16-pixel gutter and 24-pixel margin by default.
- Only the 12 catalog types, further narrowed by DSS_ALLOWED_TYPES. Catalog frontmatter is the validator's authority for counts and minimum grid size.
- BigQuery is the data source. Compute derived fields and joins in the BigQuery view; no report calculated fields or blends.
- Date controls need a usable date field; parse date-like strings in the view. Dropdown controls bind a dimension through field.
- Background decorations are flattened by deterministic rendering; interactive components are placed by the recipe compiler.
- Dimensions group data; metrics aggregate it. Do not sum ratios or average averages without defining the intended weighted calculation in the view.
- Product capabilities may exceed these conservative bindings. Do not enlarge the catalog based on a product feature without updating and reviewing the POC implementation.

