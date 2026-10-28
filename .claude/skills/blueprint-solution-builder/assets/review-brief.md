# Review brief (fill the <...> parts, then hand this to the reviewer subagent)

Review the change for task <id> as a skeptical senior engineer. You didn't write it. Don't modify
any file, install anything, or commit.

Read AGENTS.md and docs/architecture-essentials.md. Everything else you need from docs/ is in
this brief: don't open docs/plan.md, docs/progress.md or docs/PRD.md. Open another doc only at a
section the Spec or a finding needs (Grep for its heading, then Read just that range). The task,
from docs/plan.md:
```
<task block>
```

The diff (`blueprint.py diff`) and the check results the builder saw:
```
<diff>
<check output, last lines>
```

Report findings, most severe first. Write each as `[P0|P1|P2|P3] <title> - <path>:<line>` followed
by one short paragraph.
1. Does the change do what Goal and Done when require? Would the Done-when check still pass if the
   feature were broken (a weak or missing test)?
2. <Review focus from the task, if any: check exactly that.>
   <Tasks with a Spec only:> Read the sections its Spec names (<Spec line>). Each rule and edge
   case there is handled and tested; the Done when compares with the oracle, properties or golden
   data, not only hand-picked examples; the budget is measured, not assumed; nothing
   special-cases the test inputs.
3. Correctness on the changed paths: empty, missing or invalid input; failures and timeouts.
4. Rules: files outside the task's Files; anything under Non-goals; packages not verified in the
   essentials; secrets printed, logged or committed; tests weakened or skipped.
5. Fit with the essentials: stack, conventions, never-do rules.
6. <UI tasks only:> The UI against the essentials' UI design section: tokens only, the states it
   requires, its accessibility bar, nothing overlapping at its viewports. Look at these
   screenshots: <paths>. <For each review-step skill from AGENTS.md's Skills section: run
   `<skill>` on <the changed UI files>, and grade its findings into this list: a missing label,
   focus state or keyboard path on a changed control is P1.>

Flag only real issues this change introduced that you can point to in the code. If there are none,
say "No findings." Never invent a finding to fill the list.
