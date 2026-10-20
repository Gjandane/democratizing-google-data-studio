---
type: Procedural Skill
title: Suggest an invented sample-data schema
---
# Synthetic schema
Use observed labels, units, chart candidates and date grains to suggest the smallest useful
dataset. Choose plausible invented values; disclose every unseen definition and distribution.
Default row_count 1000, seed 42, schema_version 1. Return at most 20 assumptions of at most
240 characters each. Explain that all sample rows will be invented, never recovered.

Columns: 1-40 unique snake_case names (max 64 characters), type integer/number/string/boolean/date,
nullable_fraction 0..1, generator. At most 100,000 rows and 1,000,000 total cells.
Prefer independent generators unless a simple relationship is clear:
- sequence: start, step (integers), prefix (empty for integer columns; string otherwise).
- integer: min/max inclusive, integer column.
- decimal: min/max inclusive, decimals 0..6, number column.
- choice: 1-100 distinct non-null typed scalar values, matching column type.
- boolean: true_probability 0..1, boolean column.
- date: start/end ISO dates, 1900-01-01..2100-12-31, date column.
- product: fields (two distinct earlier numeric column names), decimals 0..6, number column.
- lookup: field (earlier string choice/lookup), mapping (exactly every possible category to
  a typed scalar value). Dependent product/lookup nullable_fraction must be zero.
Numeric values/results must stay within +/-10^12. Strings max 120 characters, non-empty,
and must not start with whitespace followed by =,+,-,@, tab or CR. No forward references.
Choice values and lookup mappings are generator parameters, never lists of dataset records.
