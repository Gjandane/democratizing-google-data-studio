# Engine report-building coverage audit

Date: 2026-10-18. Requested before continuing the remaining build tasks.
Scope confirmed by user: report-building features; exclude platform sharing permissions,
scheduled delivery, connector administration, and Pro administration.

## Verdict

The existing plan implements a deliberately limited POC, not Looker Studio report-editor
parity. Finishing tasks 3.1, 4.1, 4.2, and 4.3 will still leave major report-building gaps.
Native calculated fields and blends are expressly excluded; persistent filter rules are
absent. A PNG can carry decorative content, but does not provide editable text, controls,
or native report components.

This is an audit and proposed scope expansion, not a replacement executable blueprint.
The repository uses docs/plan.md and .blueprint/ checkpoints, not the invoked skill's
_blueprint/STATE.md workflow. Preserve the existing build workflow and task history.
Task statuses and the active contract have not changed. No product code was edited.

## Evidence and limits

- Read engine PRD, architecture, essentials, plan, progress, operation dispatch, report and
  chart implementations, recipe validation, and live-test definitions. Read the shared
  recipe contract/schema and the applicable program guide; did not inspect other parts.
- Current dispatch has five report operations and add_chart for five chart types. Six
  remaining contract operation names have no handler: add_control, add_text, add_image,
  set_style, add_page, and go_to_page. Three chart types remain unimplemented.
- Existing progress records successful live checks for report ops and the first five
  charts. These are historical evidence, not fresh live verification in this audit.
- Ran `uv run pytest` from engine via Git Bash: **77 passed, 4 deselected in 4.73s**.
  The four deselected tests are live tests. No live report was created during this audit.
- Google documentation was checked on 2026-10-18. The linked Looker Studio documentation
  now redirects to Google's Data Studio documentation. Feature availability may depend
  on report mode, connector, and account. This matrix covers feature families, not a
  certification of every setting or every third-party visualization.

## Coverage matrix

Implemented means source plus recorded live evidence for the bounded behavior below.
Planned means an unchecked current task. Missing means no defined recipe behavior/task;
permissive JSON extension fields do not constitute support.

| Report-building capability | Current coverage | Gap to expanded scope |
|---|---|---|
| Create, save, return report link | Implemented, 2.1 | Creates a new report using one BigQuery table and the configured template; reopening old reports is an explicit non-goal. |
| Fixed canvas and component boxes | Implemented for current report/chart ops | General move, resize, rotate, align, distribute, grouping, and arbitrary ordering operations are absent. |
| Upload PNG as page background | Implemented, 2.1 | Local file upload, placement, send-to-back. Test multiple images/pages, retry behavior, and conditional locking before broader claims. |
| Editable text | Planned, 4.2 | Contract covers text, size, color, bold, alignment. Rich spans, font family, links, padding, overflow, and rotation are not defined. [S1] |
| Standalone image/logo | Planned, 4.2 | Local upload only. URL images, replacement, alt text, links, aspect-ratio policy, and full image styling are not specified. [S1] |
| Shapes, lines, arrows, connectors | Missing | No recipe operations. A raster background is not native editable component support. [S1] |
| Scorecard, time series, bar/column, pie/donut, table | Implemented, 2.2 | Bounded contract options, not every setting for these chart families. Donut is a pie option, not a separate chart_type. |
| Pivot table, geo map, scatter | Planned, 4.1 | Geo acceptance currently permits a failed op; that is not proven geo support. |
| Other native chart families | Missing | Combo/line, Google Maps, area, bullet, gauge, treemap, Sankey, waterfall, boxplot, candlestick, timeline, funnel. Google Maps is distinct from geo_map. [S2] |
| Chart variants and detailed setup | Partial | Current contract covers basic fields, aggregation, date dimension, breakdown, one sort, title, and a few options. Optional metrics, explicit drill actions/default level, comparison periods, running/comparison calculations, reference/trend lines, detailed axes/legends and number formats need an inventory. Some current multi-dimension paths enable drill down; this is not full drill-action support. [S2, S8, S9] |
| Date-range and dropdown controls | Planned, 4.1 | Creation and one manual date interaction. Defaults, selection modes, dropdown interaction, reset, and scope are insufficiently specified/tested. |
| Other controls | Missing | Fixed-size list, input box, advanced filter, slider, checkbox, preset filters/buttons, dimension control, and data control. Data-control availability is connector-dependent. [S3] |
| Persistent filter properties | Missing | Include/exclude predicates, typed values, AND/OR combinations, report/page/group/chart scope, reuse, and inheritance. These are distinct from controls. [S4] |
| Chart cross-filtering and viewer interactions | Missing as a defined capability | Need explicit enablement, scope and reset behavior; chart placement alone does not prove interactions. [S3, S8] |
| Native calculated fields | Explicitly excluded, PRD line 25 | Both data-source and chart-specific fields; formulas, types, aggregation, naming and dependency rules. Existing BigQuery column selection does not create either kind. [S5] |
| Custom groups and bins | Missing | Native modeled-field behavior is not covered by selecting ordinary columns. [S5] |
| Parameters | Missing | Typed definitions, allowed/default values, bindings to controls/formulas, and overrides. [S6] |
| Multiple report data sources and native blends | Single source; blends explicitly excluded | Source identifiers, per-chart source selection, field metadata and join semantics are absent. Adding an already-authorized source to a report is report building; connector/account administration stays excluded. [S7] |
| Component styles | Planned, 4.2 | Only colors, show_title, font_size, background, border_color are named. Unknown keys may succeed with a warning; that is not styling support. |
| Themes and conditional formatting | Themes excluded; conditional rules missing | Separate report/page defaults from component overrides and ordered conditional rules. [S9, S10] |
| Multiple pages | Planned, 4.2 | Add/navigate only. Rename, duplicate, reorder, delete, hide, navigation structure and report-level components need decisions/specs. [S10] |
| Responsive layouts | Missing | Current recipe uses absolute pixel boxes. Responsive sections require a different layout model; arbitrary overlap/send-to-back is not available in that mode. [S11] |
| Embedded external content | Missing | URL embed component and availability/error behavior, without changing the embedded resource's permissions. [S12] |
| Community visualizations | Missing | An open-ended third-party ecosystem requires an explicit supported allowlist and per-visualization specifications; cannot promise universal parity. [S2] |
| Update/delete/duplicate existing components | Missing | Must distinguish components created in this run from reopening old reports, which current PRD forbids. |

## Prioritized findings

### F1 — P1: The target and written scope disagree

Evidence: docs/PRD.md:25 excludes calculated fields and blends; :40 excludes themes.
docs/plan.md:62 and :70 only finish a narrow set of controls, charts and miscellaneous ops.
Completing that plan cannot satisfy the user's confirmed report-building target.

Correction: retain the POC milestone, then define a separate report-building expansion
with explicit supported/unsupported capabilities. Amend the PRD/design before activating
tasks that conflict with non-goals. Do not claim the hackathon deadline covers parity.

### F2 — P1: The recipe contract cannot express the most important missing features

Evidence: ../contracts/recipe.md:23-46 and recipe.schema.json define 12 op names, eight
chart types, two controls, a single BigQuery source, and field references as column names.
There is no native field, parameter, filter, blend, or source-management model.
The metric aggregation enum also has no Auto, relevant to native aggregate formulas. [S5]

Correction: prepare a versioned contract revision at program root before engine work.
Cover stable source/field/component/page references, native field scopes and aggregation,
filter predicates and targets, parameters, expanded chart/control schemas, and unsupported
capability behavior. Extra fields accepted by v1 do not authorize inventing semantics.
Per the program guide, shared contracts are read-only from this engine session.

### F3 — P1: Proposed filters need semantics and result checks, not just UI insertion

Evidence: docs/plan.md:62-69 only plans dropdown/date controls and one manual time-series
check. There is no persistent-filter task. Google distinguishes filter properties from
viewer controls, with scope and inheritance affecting results. [S3, S4]

Correction: separate persistent filters from controls. Test a scoped filter on two charts
and a second page, include/exclude behavior, combined conditions, reset, and saved-report
persistence. Verify actual displayed rows/values against known expectations.

### F4 — P1: Component identity is an unresolved dependency for style/page expansion

Evidence: docs/architecture.md:42 specifies a component_id registry with page and box;
src/dsengine/ops/charts.py:393 stores chart state by op.id and chart index. Current dispatch
in src/dsengine/ops/__init__.py:60-69 imports only report/charts. Tasks 4.1/4.2 omit this
dispatch file from their Files lists.

Correction: explicitly include dispatch and registry work in the task scopes. Store stable
component identity and owning page for all component families; test style changes after
page navigation and overlapping positions. Define missing/duplicate ID behavior. Do not
assume the current chart index is sufficient after page changes or component reordering.

### F5 — P2: Task 4.1 has contradictory geo acceptance

Evidence: docs/plan.md:68 requires every op ok; :69 permits geo_map failed without blocking.

Correction: use a verified geo-capable test fixture for positive support, while retaining a
separate negative fixture for unsupported data. If no such fixture is available, record geo
as unverified/deferred and revise the acceptance wording; never count a failed map as
implemented coverage. Any new data fixture must respect the shared test-data conventions.

### F6 — P2: Task 4.2's acceptance is materially narrower than its advertised operations

Evidence: docs/plan.md:76 checks font size/color, one image, chart colors, and a second page.
It does not explicitly exercise go_to_page, bold/alignment, the other named style keys,
target identity, multiple images, invalid page indices or saved persistence.

Correction: add a two-page recipe which returns to page 1, styles the intended component,
uses two images, tests every supported text/style argument and checks saved output.
Cover retry after insertion without duplicate components. The existing background code
uses broad image locators (report.py:212-218 and :239-240), so multiple-image behavior
requires explicit testing and likely scoped selectors; current single-image success is
not evidence for that case. Locking is not implemented; inspect whether the UI offers it
and satisfy or explicitly document the contract's conditional lock requirement.

### F7 — P2: Golden success is not feature-completeness evidence

Evidence: docs/plan.md:53-59 requires >=90% ok for the five-chart core flow, whereas the
PRD also promises every contract op and a 20-op budget. The described core flow has ten
ops, so one failed chart could still meet 90%, and it need not exercise twenty operations.

Correction: keep the existing reliability metric for integration; add an all-required-ops
feature gate after phase 4 and a genuine 20-op budget run. Include text, independent image,
controls, styling, page navigation, and all advertised chart types. Assert successful
save/link and independent saved-result verification, not just exit code 0 (partial also
exits 0). New native field/filter/control work needs value-based assertions.

## Proposed revision sequence

These are planning work packages, not executable tasks or new status markers. Compile
each into the existing plan with Files, Spec, Depends on and concrete Done when checks
after the shared interface is settled. No new implementation is authorized by this file.

| Order | Work package | Acceptance to put in the revised plan |
|---|---|---|
| A | Finish the current POC honestly | 3.1 golden run; correct F4-F6 before 4.1/4.2; all current contract ops exercised successfully; preserve separate negative cases. Screencast remains a stretch delivery feature, not report-editor coverage. |
| B | Capability inventory and contract revision | Every matrix family has an explicit scope and versioned schema representation or exclusion; old recipe compatibility tested; compiler/engine boundaries agreed at program root. |
| C | Component/page/source identity and typed preflight | Resolve references deterministically; reject invalid dependencies before UI mutation where feasible; no duplicate creations after retries; test two pages and overlapping boxes. |
| D | Native calculated fields | Separate data-source and chart-specific operations; explicit formula dialect, result type and aggregation; preserve references. Test row expression, aggregate ratio, text/date expression, invalid formula, missing field, duplicate name, dependent fields, and persistence. |
| E | Persistent filters | Typed include/exclude predicates, documented AND/OR rules, scope/reuse/inheritance. Compare visible results before/after on targeted and untargeted charts/pages. |
| F | Parameters and complete control families | Declare types/defaults/allowed values; bind controls to fields or parameters. Exercise control interaction, scope, reset and parameter-driven formula results; respect connector restrictions. |
| G | Report assets and layout | Finish editable text and image behavior, then shapes/lines/embeds, grouping/order and page operations. Verify two-page persistence, component identity and links/alt text where supported. |
| H | Native charts and chart settings | Inventory every native family/variant from S2; split into small family tasks. Each has valid field shapes, setup/style schema, representative live data, saved render checks and incompatible-data failures. |
| I | Themes, conditional styling and interactions | Test report/page defaults versus component overrides, ordered formatting rules, drill/cross-filter interactions and actual viewer behavior. |
| J | Multiple sources and native blends | Define source ownership, field IDs, join keys/types, aggregation order and filter behavior. Verify join output and aggregates against a controlled dataset; never edit a shared existing source implicitly. |
| K | Responsive reports and selected community visuals | Separate responsive section layout from fixed boxes. Specify platform-incompatible operations and selected visualization support; validate responsive behavior at multiple widths. |
| L | Report-building conformance suite | Each supported capability has schema validation, handler, independent live result verification and a saved-report check. Publish versioned coverage; refresh the inventory when Google adds features. |

D and E should be the first feature additions after the POC and interface foundation: they
address the explicit user examples the current plan misses. SQL preprocessing can remain
useful, but it is not a substitute for native editable fields, scoped filters or parameters.
For example, a precomputed row-level ratio can aggregate differently from a native
ratio of sums under interactive filtering; equivalence must be demonstrated, not assumed.

The next planning decision is how to stage this expansion against the existing deadline.
The user confirmed report-building scope, but did not replace the deadline or authorize
changes to shared contracts from this part. Full editor parity must not be silently
added to a small remaining POC task.

## Official references

- [S1: Text, images, lines and shapes](https://docs.cloud.google.com/data-studio/add-text-images-lines-and-shapes-to-your-reports)
- [S2: Types of charts](https://docs.cloud.google.com/data-studio/types-of-charts)
- [S3: About controls](https://docs.cloud.google.com/data-studio/about-controls)
- [S4: Filter properties](https://docs.cloud.google.com/data-studio/about-filter-properties)
- [S5: Calculated fields](https://docs.cloud.google.com/data-studio/about-calculated-fields)
- [S6: Parameters](https://docs.cloud.google.com/data-studio/parameters)
- [S7: Blending concepts](https://docs.cloud.google.com/data-studio/blending-tips-and-advanced-concepts)
- [S8: Drill actions](https://docs.cloud.google.com/data-studio/add-drill-actions-to-charts)
- [S9: Conditional formatting](https://docs.cloud.google.com/data-studio/use-conditional-formatting-rules)
- [S10: Report and page layout](https://docs.cloud.google.com/data-studio/report-and-page-layout)
- [S11: Responsive reports](https://docs.cloud.google.com/data-studio/create-a-responsive-report)
- [S12: Embedded external content](https://docs.cloud.google.com/data-studio/embed-external-content-in-reports)
