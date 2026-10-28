# Worker brief (unattended or delegated): fill the <...> parts, then hand this to a new worker

You are building exactly one task on your own. Nobody will answer questions; the docs are the
authority. Read AGENTS.md first (if its Subagent roles section defines a Worker role, take it on),
then this bundle (the task, its Spec, the essentials, the non-goals, and earlier decisions):

```
<output of: blueprint.py status --task <id>>
```

Build notes from the session that delegated this task (empty in unattended mode). Follow them;
where you deviate, say what and why under Decisions:

```
<build notes, or "none">
```

Do:
- Implement only this task, inside its Files, following the essentials and the AGENTS.md rules.
- If AGENTS.md has a Skills section, use its build-step skills; the essentials' UI design section
  wins over their generic advice. A listed skill that isn't installed: skip it and say so under
  Gotchas.
- Where the docs are silent, choose the smallest change that passes the Done-when check, and list
  the choice under Decisions. For UI, smallest never means unstyled: use the design foundation's
  tokens and components.
- Under a Spec, smallest never means naive: meet all of it (rules, edge cases, budget), not just
  the tests. How is yours to design, unless its Approach names one; report the approach, its
  parameters and the measured budget under Decisions.
- Run the Done-when command and Test (all). Report the real output. Never simulate or summarize a
  run you didn't do. For a UI task, with a browser tool, also check it at the essentials'
  viewports and save the screenshots the Done when names; without one, say so.
- At most two attempts at the same failure (a real change plus a rerun is one attempt). Then stop
  and report.
- The bundle is your context: don't open docs/plan.md, docs/progress.md, the PRD or the
  architecture whole. For anything more from docs/, run `python "<path to blueprint.py>" recall
  <task ID | docs/<file>.md | "docs/<file>.md#<Heading>" | "<regex>">`; it only reads.

Don't: edit anything in docs/, run blueprint.py other than `recall`, commit, push, start subagents, use skills other
than AGENTS.md's build-step ones, install a package or skill that isn't approved, or print
secrets. Packages are approved only when verified in the essentials' Dependencies table.

Stop and report instead of guessing in any of these cases:
- Every option breaks a rule in the docs.
- The fix needs a doc, plan or environment change.
- Something the task names doesn't exist.
- The task has a STOP field and there are no build notes.

Reply with:
- Result: done | failed | blocked
- What changed: files and behavior
- Checks: each command, PASS or FAIL with counts, and the last lines of its output
- Decisions:
- Tried and failed:
- Gotchas:
- If blocked or failed: which case, the question, options A and B, and your recommendation
