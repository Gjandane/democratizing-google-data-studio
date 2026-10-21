---
type: Skill
title: Context drafting
---

# Context drafting

At most 15 KPIs, 15 derived fields, 15 thresholds and 30 glossary terms.
Use unique lowercase snake_case KPI and threshold IDs and derived names; derived
names must not collide with source columns. A derived expression is a scalar
BigQuery expression over the first source, never an aggregate, window, subquery or
statement. Prefer existing columns. SUM/AVG require numbers; MIN/MAX require a
number or date/datetime; COUNT and COUNT_DISTINCT accept any field. Thresholds
require numeric fields. Use an explicit measure field, including for counts.
Keep source grain and metric assumptions visible in descriptions. Reference image
labels suggest vocabulary only; they do not establish fields or data values.
