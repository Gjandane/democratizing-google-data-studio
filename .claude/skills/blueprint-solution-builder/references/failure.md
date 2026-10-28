# When a task doesn't go to plan

Contents: What counts as an attempt · Two failed attempts at the same failure ·
A task too big for one session · Stale context ·
What isn't yours to settle (with a new dependency and a small doc change) · Blocking a task ·
Scope changes

## What counts as an attempt

An attempt is a real change plus a real rerun of the check. Printing values, reading files and
adding a debug line don't count. Between attempts, look before you guess: print the actual value
the check asserts on and compare it with what the task expects. When a check disagrees with a code
snippet in the plan, the check is the contract. Adjust the code; that's an attempt, not a
conflict. When a check disagrees with the task's Spec, neither wins: that's case (b) below.

## Two failed attempts at the same failure

A third attempt in the same context usually copies the wrong versions already in it. So:

1. Run `restore ID`. In git mode it stashes the attempt (recover it with `git stash list`, then
   `git stash apply`). In folder mode it moves the attempt to `.blueprint/attempts/`. Both keep
   docs/plan.md and docs/progress.md.
2. Append an entry with `Status: partial`. Under "Tried and failed", give each attempt and the
   evidence of why it failed. Under Next, give the approach you'd try next and why. A gotcha that
   qualifies under SKILL.md's Record step goes into AGENTS.md now, after the restore.
3. In git mode, commit only the entry (and AGENTS.md, if you just added a gotcha):
   `task ID: record failed attempt`.
4. Hand off: "Task ID: two attempts failed and were set aside; the log says why. Type `/clear` (or
   start a new session), switch to <model> at <effort> effort, then
   `/blueprint-solution-builder`." Take them from this task's row in `references/models.md`; if
   this session ran on Sonnet, recommend opus at high instead. The marker stays `[~]`, so the next
   session, in either tool, resumes this task and sees what failed.

A task gets two sessions. If `status` showed an earlier `partial` entry for this task (from either
tool) and this session also fails twice, block the task instead (below).

## A task too big for one session

This is for when progress is good but the context is filling up. Don't restore anything:
1. Stop at a point where the project still builds.
2. Append an entry with `Status: partial` and the exact next step under Next.
3. In git mode, commit `task ID (wip): <what is done>`.
4. Hand off. The marker stays `[~]`, and the next session resumes the task.

If the architect sized the task S or M, mention the real size under Gotchas.

## Stale context

Write a handoff entry (`assets/handoff-prompt.md`) and ask for a new session when either of these
happens:
- You're about to retry an approach listed under "Tried and failed".
- You, or the user, notice two of these signs: a fixed bug comes back; a rule from AGENTS.md is
  ignored; you re-read files or re-ask answered questions; you contradict a decision in the
  essentials.

## What isn't yours to settle

Everything is latitude (choose, record it under Decisions, continue), including how to design an
algorithm a Spec describes unless its Approach names one, except these cases:

- **(a)** Every way forward breaks a rule: AGENTS.md, the essentials' never-do rules, a non-goal,
  or a decision in architecture.md.
- **(b)** The fix needs a change to the PRD, architecture, essentials or plan, to a contract the
  part reads (a program's `contracts/`), or a dependency that isn't verified. A Spec you can't
  meet (a budget no approach reaches, rules that contradict each other) is this case too.
- **(c)** Something the task names doesn't exist: a file, command, service or credential, or a
  tool one of its checks needs (a browser that can open the app, for example).
- **(d)** Two sessions failed, or two attempts failed and you can't name the cause.

In supervised mode, ask the user about (a)-(c) on a card before blocking; many are one-click
answers.

- **A new dependency:** give the name, registry and reason. If the user agrees, add a row to the
  essentials Dependencies table and run `blueprint.py deps --write`. Install the package only if its
  row gets a date.
- **A small doc change** the user approves as an exact edit, confined to this task: edit the
  section in architecture.md, add a decision-log row (source: `task ID, approved by user`), update
  the essentials to match, then run `blueprint.py stamp`. For a POC, edit only the essentials. In
  unattended mode, never do this.
- **Anything bigger,** or the user wants to re-plan: block the task.

## Blocking a task

1. Run `restore ID` if the tree holds work the ruling could invalidate. It's recoverable.
2. Append an entry with `Status: blocked`, `Blocked because:` (a)-(d), `Question:` (one answerable
   sentence), and `Options:` A and B with your recommendation. If the block is a failure, add up
   to 20 lines of real output.
3. Run `block ID`. In git mode, commit only the docs (and AGENTS.md, if you added a Known
   gotchas line after the restore): `task ID: blocked`.
4. Hand off: "Task ID is blocked: <question>. Type `/clear` (or start a new session), switch to
   `best` at high effort, then `/blueprint-solution-architect` to resolve it." Codex's `$blueprint-solution-architect` can
   resolve it too. A block over a contract is resolved at the program root instead: "open a
   session in <program root>, then `/blueprint-solution-architect`."

## Scope changes

If the user asks for something outside this task, or something a non-goal excludes, don't build
it here:
- If it changes the current task, block the task (case b).
- Otherwise, finish the task, add `- Change request: <what the user asked>` to your entry, and
  add to the handoff: "A change request is waiting. Run `/blueprint-solution-architect` to plan
  it in before the next task." `status` warns about it in every session until the architect's
  Change entry settles it.
