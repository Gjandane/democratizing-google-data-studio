---
type: Skill
title: Blueprint
---

# Blueprint

Map each selected question to one to three buildable components. Follow the code page plan.
Use the compact catalog summary for binding counts and optional values. Prefer direct chart
bindings to the user's defined KPI measures; never silently substitute an aggregation.
Use a date dimension for time series and a sort field already used by the component.
Keep a page within twelve rows including supporting controls. Controls have question_id null.
Join only on proven compatible keys; union stacks sources with typed NULLs and dataset_name.
The application builds and dry-runs SQL from ViewSources and scalar derived expressions.
SQL repair returns corrected ViewSources/extra derived fields, not SELECT or CREATE text.
