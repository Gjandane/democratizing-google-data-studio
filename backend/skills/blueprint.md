---
type: Skill
title: Blueprint
---

# Blueprint

Map each selected question to one to three buildable components. Follow the code page plan.
Use the compact catalog summary for binding counts and optional values. Prefer direct chart
bindings to the user's defined KPI measures; never silently substitute an aggregation.
Cover every named KPI across that question's one to three rows, including a named gap/difference
measure alongside its two inputs. Repair feedback names the missing field and aggregation;
preserve all of them within catalog and page limits. Never change the confirmed definitions.
Reuse a projected DATE field for yearly grouping when code supplies full-column year-start proof.
Do not introduce a redundant year alias or DATE arithmetic; sort on the same date binding.
Use a date dimension for time series and a sort field already used by the component.
Labels are human titles only: no `agg(field)` formula or `[unit]`. A trend label that names one
grain (Daily, Weekly, Monthly, Quarterly, Yearly) is drawn at that grain; name one only when the
question asks for it.
An area chart is a time series of filled parts (date dimension, metrics or one breakdown):
set stacked for parts of a total, stacked_percent for shares that sum to 100 %. A bar with
stacked_percent shows each category's split (e.g. rural vs urban share). A fixed_size_list
control lists every value of its one dimension as checkboxes; prefer it to a dropdown when
the reference shows a checkbox list or the field has a few values.
Keep a page within twelve rows including supporting controls. Controls have question_id null.
Join only on proven compatible keys; union stacks sources with typed NULLs and dataset_name.
The application builds and dry-runs SQL from ViewSources and scalar derived expressions.
SQL repair returns corrected ViewSources/extra derived fields, not SELECT or CREATE text.
