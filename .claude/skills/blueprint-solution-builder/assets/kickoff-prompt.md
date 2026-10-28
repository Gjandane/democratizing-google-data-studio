# Kickoff prompt (template D.6): fallback when the builder skill isn't installed

With the skill installed, type `/clear`, then `/blueprint-solution-builder`. Without it, type
`/clear` and paste this at the start of the new session. To approve the plan before any code,
replace the sentence that starts "The plan is curated" with "Before editing, give me your plan in
3-5 bullets and wait for my OK."

```
New task. Read AGENTS.md, docs/architecture-essentials.md, the Non-goals in docs/PRD.md, and the
latest entry in docs/progress.md, plus the entries for the tasks this one depends on. If the
task has a Spec: field, read the doc sections it names; the code must meet all of them.
We're doing Task <id> from docs/plan.md. The plan is curated: build it as written, without asking
me to approve a plan first; ask me only what a STOP field in the task reserves for me.
Explore only what this task needs; use the Explore subagent if the search is wide.
Implement, run the task's "Done when" command and the full test suite, have a subagent review the
diff, add a docs/progress.md entry with a one-line `- Digest:` (at most 280 bytes: the names,
paths and shapes later tasks consume), then mark the task done with the blueprint script
(`python <path to blueprint.py> done <id>`), never by editing docs/plan.md.
```
