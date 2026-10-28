# A supervised batch: up to 3 small tasks in one session

Use this when the user names a range without "unattended", for example
`/blueprint-solution-builder 3.1-3.3`. Small, related tasks then share one session instead of a
fresh session each. You build every task yourself, the user approves the plans only with
`confirm`, and each task keeps its own records: `start`, checks, review, progress entry, `done` and
commit. Codex's builder has no batch mode; the files it reads are the same either way.

## What can go in a batch

Up to 3 tasks, all `Size: S`, in the same phase, none with a `STOP:` field or an unmet `Needs:`,
each depending only on done tasks or on earlier tasks in the batch. Take the named tasks in plan order, and end the batch
just before the first one that breaks a rule; say so in one line. `status` must show no lint
errors, no `STOP` warning and no task in `[~]` outside the batch.

## The plan check: only with `confirm`

Run `status --task ID` for each task and read all of it. Without `confirm`, tell the user the batch
in one line (IDs and names) and start. With `confirm`, ask with one AskUserQuestion call, one
question per task, each carrying that task's plan: "Task ID plan: <how, and the files, in 2-3 short
sentences>. Proceed?", with **Proceed (Recommended)**, **Proceed with my change** (typed in the
notes) and **Stop here**. Ask open points in a second call before you build. A task answered
**Stop here** ends the batch just before it. The other rules of the plan check in SKILL.md step 3
still apply: nothing is built before the answers, and the pause gets no progress entry.

## Each task, in order

Run the supervised loop's steps 1-8 for it, without step 3, which the batch settled once: `start`,
build, verify, review, the progress entry (`Plan check: off`, or with `confirm`: `confirmed` or
`corrected: ...`), `done` and the commit. Only then start the next task. If a task fails twice,
needs something the docs don't cover, or turns out bigger than S, follow SKILL.md's Stop early for
it and end the batch there. If your context grows heavy, end the batch after the current task.

## Hand off once

After the last task: one line per task (ID, result, commit or checkpoint), then the next task and:
"Type `/clear` (or start a new session), switch to <model> at <effort> effort (task <ID> is
<tier> work), then `/blueprint-solution-builder`. Codex works too: `/new`, `/model` <Codex model>
at <effort>, then `$blueprint-solution-builder`." Take the model and effort from the next task's
row in `references/models.md`, and the Codex ones from its "Codex in a handoff".
