---
type: Procedural Skill
title: Audit a dashboard layout
---
# UX audit
Review the spec summary against the archetype guidance. Check: visual hierarchy (the key
scorecards sit top-left and are larger than supporting charts), alignment on the grid, spacing
and empty areas, crowding or tiny boxes, label clarity, and a title that frames the page.
Return at most 10 findings, each with component_id (an id from the summary), severity
(high, medium or low), issue (one sentence, what is wrong) and suggestion (one sentence, a
concrete change). Report only real problems; return an empty findings list when the layout is sound.
