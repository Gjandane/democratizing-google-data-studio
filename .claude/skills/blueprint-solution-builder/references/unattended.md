# Unattended mode: several small tasks, one fresh worker per task

Use this only when the user explicitly asks, for example `/blueprint-solution-builder unattended
2.1-2.4` or "do the next three tasks on your own." Supervised mode is the default. Each task still
gets a clean context, because each gets a new worker subagent. You orchestrate and verify, and you
never implement yourself.

## Before starting

- Scope: the tasks the user named, or the next N, up to **5 per run**. If more were asked, do 5
  and say why.
- `status` must show all of these: `Audit: done`, no lint errors, no `STOP` warning, and no task
  in `[~]` (finish or record it first).
- Walk the candidate tasks in order. End the run list just before the first task that:
  - has `Size: L` (it gets its own fresh, supervised session),
  - has a `STOP:` field (it needs the user),
  - depends on a task that isn't done, or
  - waits on another part's task that isn't done (`Needs:`; `status --task ID` warns).
- Tell the user the run list in one line, then start. There is no plan check here, even with
  `confirm`. Workers' permission prompts still come to the user unless the session runs in
  auto mode or the commands are pre-approved; say so in the same line if the session is in Manual
  mode.

## For each task

1. Run `start ID`.
2. Spawn a **new** `blueprint-worker` subagent for this task (if that agent isn't installed, use
   the built-in general-purpose agent). Give it `assets/worker-brief.md`, filled with the output
   of `status --task ID`, and leave its build notes empty: the docs carry the task. Pass the
   `model` and `effort` `references/models.md` gives a worker for this task's tier (deep: opus at
   high; routine: sonnet at medium). It runs in the background: wait for its completion
   notification, and don't start anything else meanwhile.
3. When it reports, verify for yourself: rerun the Done-when command and Test (all). Its report is
   a claim, not evidence.
4. Spawn the reviewer as in the supervised loop, with `assets/review-brief.md`, and wait for it.
5. Allow one fix round. Send the P0 and P1 findings, or the failing checks, back to the same worker
   once with SendMessage (it resumes with its history), then verify again.
6. **If it passes:** write the progress entry yourself (`Plan check: unattended`), from the
   worker's report and your own results. Review findings you didn't send back go under Left
   open, and the worker's Gotchas update AGENTS.md as SKILL.md's Record step says. Run `done ID`,
   then commit as in the supervised loop (git mode).
7. **If it still fails, the worker reports blocked, or a new dependency is needed:** run `restore
   ID`, write a `partial` or `blocked` entry (`references/failure.md`), run `block ID` if it's
   blocked, and **end the run**. Later tasks usually build on this one.

## Rules during the run

- Never edit the PRD, architecture or essentials, and never approve a dependency. Those need the
  user.
- Workers don't write docs, run the script or commit. You're the only writer of plan.md,
  progress.md, AGENTS.md's Known gotchas and commits.
- Keep only short summaries in your own context. If it grows heavy, end the run after the current
  task.

## End of the run

Post a table (task, result, commit or checkpoint, checks), the task that stopped the run and why,
and then: "Type `/clear` (or start a new session) before the next run or task, switch to <model>
at <effort> effort (task <ID> is <tier> work), then `/blueprint-solution-builder`." Take the model
and effort from the next task's row in `references/models.md`.
