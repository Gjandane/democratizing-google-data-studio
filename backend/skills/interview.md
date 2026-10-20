---
type: Procedural Skill
---
# Interview
Use the aggregate data profile to ground questions in actual columns. Ask one question at a time;
do not combine audience and decision questions in one turn. Start with the most useful missing
fact: audience, then decision, then KPIs and aggregation/time comparison, then filters and scope.
Use information already supplied rather than asking again. Offer concise choices when helpful.
Explain when a requested metric cannot be supported by the available fields; ask for an alternative.
Listed feasibility issues are the next questions: a missing or ambiguous metric definition gets a
concrete question naming the candidate columns (for example "SUM(revenue)" or
"COUNT(DISTINCT order_id)"); an unsupported or unknown behavior gets an explanation and the
offered alternatives. Keep earlier answers; ask only about what is still open.
Accept coordinated affirmative formulas as one answer. Reuse confirmed same-metric definitions
with their provenance for compatible later charts. Clean blue theme and dark blue chart accents
use supported series palettes; proceed alone never accepts alternatives or drops open issues.
Once audience, decision, KPIs and scope are sufficiently clear and no feasibility issue remains,
call mark_ready_for_plan and summarize the agreed direction. The user may still refine it before planning.
