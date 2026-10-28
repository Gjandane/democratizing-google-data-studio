---
name: blueprint-solution-builder
description: Build the next task in docs/plan.md, one task per fresh session - implementation straight from the curated plan, the task's Done-when check plus the full test suite (with screenshots for UI work), a subagent review, a commit or folder checkpoint, and a docs/progress.md entry. Continues builds started in Codex too. Add a task ID to pick one, a range like 2.1-2.3 to build up to 3 small tasks in one supervised session, 'unattended 2.1-2.4' to run up to 5 small tasks with fresh worker subagents, 'confirm' to approve the plan on a card before building, or 'headless ID' for a run nobody watches (scripts/overnight.py builds task after task that way, each in a fresh session).
argument-hint: "[task-id | 2.1-2.3 | unattended 2.1-2.4 | headless task-id] [confirm]"
disable-model-invocation: true
allowed-tools: Bash(python "${CLAUDE_SKILL_DIR}/scripts/blueprint.py" *)
---

# Blueprint Solution Builder

You build one task from docs/plan.md in this session, or a batch of up to 3 small ones that the
user names. The architect already wrote and audited the plan, and the user approved it, so you
build it as written: there is no plan check unless the user adds `confirm`. The docs are your
memory and this session is disposable: everything the next session needs goes into the files
before you stop. The next session may run in Codex, so all state lives in the repo (markers,
progress entries, commits), never in memory. The model and effort come from the session, and they
should match the task's tier: a task with heavy logic runs on Opus at high effort, a routine one
on Sonnet or on Opus that delegates the typing (`references/models.md`). `status`, `start` and
`done` print the effort in force.

What the user typed after the command: $ARGUMENTS

If that includes `headless`, read `references/headless.md` before anything else: nobody is
watching, and its fixed answers replace every question this skill asks.

## The script

Run it with the Bash tool, from the project root, exactly like this (keep the quotes; paths often
contain spaces):

    python "${CLAUDE_SKILL_DIR}/scripts/blueprint.py" status

The Bash tool is the one this skill pre-approves and the one that reports the effort; use
PowerShell only if there is no Bash tool. Commands: `status [--task ID]`, `start ID [--owner NAME]`,
`diff`, `restore ID`, `done ID`, `block ID`, `recall QUERY`, plus `deps --write` and `stamp`, which
you run only for changes the user approves (`references/failure.md`). Task markers change only
through the script, never by hand. It works in git repos and in plain folders. If `python` isn't
found, try `py -3`.

`recall` fetches one thing from the docs, so you never read plan.md, progress.md, the PRD or the
architecture whole: `recall 2.3` (a task's plan block and every entry), `recall
docs/architecture.md` (its outline, with sizes), `recall "docs/architecture.md#Data model"` (one
section), or `recall "<regex>"` (each matching line, labelled with its task or heading).

## Start

1. Run `status`, or `status --task ID` if the user named one task (several: step 5). It prints
   the task, the Spec sections it names, the architecture essentials, the PRD non-goals, earlier
   sessions of this task (from either tool), what the tasks it builds on left (direct ones: What
   changed, Decisions and Gotchas; earlier ones: one Digest line each, within a fixed budget),
   and warnings. Read all of it; for anything more, `recall` it. The
   AGENTS.md rules are loaded through CLAUDE.md (step 3 covers repos where they may not be).
2. A warning that starts with `STOP`: tell the user what it says and how to fix it, then wait. If
   `status` says no task is ready because the next one waits on another part (a `Needs:` field),
   tell the user which part's task to build first and in which folder, then stop. A change request
   it warns about goes to the user too, before you build.
3. Instruction files and lint. If `status` says there's no CLAUDE.md (a plan made in Codex), read
   AGENTS.md now, because it may not be loaded, and offer on a card to add a CLAUDE.md whose only
   line is `@AGENTS.md`; it takes effect from the next session. If it reports lint errors, run
   `lint` to see them all. A CLAUDE.md that doesn't import AGENTS.md means the rules aren't loaded:
   read AGENTS.md now and tell the user. A marker error means someone edited plan.md by hand: tell
   the user, and leave the marker alone (the architect's `reopen` resets it). If the project
   folder sits below the git root, the folders above and beside it are other projects: their
   instruction files may be loaded too, but only this folder's AGENTS.md applies (in a part of a
   program, plus the program block at its root). Never open, edit or report on files outside
   this folder unless the task or a `STOP` warning names them. In a part of a program, the
   contracts AGENTS.md names are the exception: read them, never edit them. The program's root
   part may also read each part's AGENTS.md Commands and run them from that part's folder, but
   never edits a part's files. Ignore `docs/archive/` (earlier versions) unless the task names it.
4. **Model check.** Read `references/models.md`, work out the tier (each task's, for a batch or an
   unattended run), and check your model and effort as its "Check your model first" says, before
   you explore anything.
5. The user named several tasks: with "unattended", read `references/unattended.md`; otherwise (a
   range such as `3.1-3.3`), read `references/batch.md`. Follow that file instead of the loop below.
6. The plan check (step 3 below) runs only when the user typed `confirm` (or `--confirm`) after
   the command, or the session is in plan mode. In plan mode, explore, present the plan check
   through the plan approval, and run `start` only after it's approved.

## One task, supervised (the default)

1. Run `start ID`. It marks the task `[~]` and records the checkpoint.
2. Explore only what the task needs. For a wide search, use the Explore subagent with
   `model: haiku` and ask for a one-page summary. Then make sure every check in the Done when can
   run here: the tools and services its commands call are available, and for a UI task the
   browser tool opens the app (and can download or upload a file, if the check does that). If one
   can't, that's Stop early now, before any code.
3. **Plan check: only with `confirm`.** Without it, go straight to step 4. Settle open points by
   the Latitude rule and record each under Decisions; what isn't yours to settle goes to Stop
   early, as always. The task's `STOP:` field, if it has one, still needs the user: ask it on a
   card at the point it names (before building if it names none), with the evidence it names in
   each option's description. With `confirm`, ask with AskUserQuestion, all in one call (at most 4
   questions), and put the plan on the card itself, because the card is what the user reads:
   - "Task ID plan: <how you'll do it and the files you'll touch, in 2-3 short sentences>.
     Proceed?": **Proceed (Recommended)**, with the check you'll run as its description,
     **Proceed with my change** (typed in the notes), **Stop here**.
   - One question per open point you have, your recommended answer first.
   - The task's `STOP:` decision, if it has one: the options it names, with the evidence in each
     option's description.
   The workflow depends on these answers, so don't go on before them, even in auto mode. Waiting
   for them doesn't end the session: write no progress entry for the pause. **Stop here** means
   end your turn and ask what they want instead; the task stays `[~]`. Without the tool, ask in
   plain text and end your turn. An answer that auto-continued because the user was away counts
   as no answer.
4. Build inside the task's Files, following the essentials and the AGENTS.md rules. A routine M
   task on an Opus or Fable session: write its build notes and hand the typing to a Sonnet worker
   (`references/models.md`, "Delegating a routine task"); every rule in this step binds the build
   notes, and steps 5-9 stay yours. Otherwise build it yourself. Where the docs are silent,
   choose the smallest change that passes the check, and note it for Decisions. For UI, smallest
   never means unstyled: use the design foundation's tokens and components. Under a
   Spec, smallest never means naive: meet all of it (rules, edge cases, budget), not just the
   tests; how is yours to design, unless its Approach names one. If AGENTS.md has a Skills
   section, run its build-step skills first; the essentials' UI design section wins over their
   generic advice. A listed skill that isn't installed: skip it, note it under Gotchas, and never
   install it yourself (`references/included-skills.md` has the command to give the user).
5. **Verify.** Run the Done-when command, then Test (all) from AGENTS.md, and read their real
   output. A task that changes UI: also open it in a browser at the essentials' viewports, walk
   the states the task adds, save the screenshots its Done when names, and look at them. With no
   browser tool, say so under Checks instead of claiming the visual check. The task isn't done
   while any of these fails.
6. **Review.** Give the `blueprint-reviewer` subagent `assets/review-brief.md`, filled with the
   task block, the `diff` output and the check results; for a UI task, add the screenshot paths and AGENTS.md's
   review-step skills; for a task with a Spec, its Spec line. If it isn't installed, use Explore
   with the same brief (Explore can't run skills: run those yourself after its report and add
   their findings).
   You need its report before you go on, so run it in the foreground where Claude Code lets you;
   otherwise wait for its completion notification. Fix the P0 and P1 findings, then rerun step 5.
   Each fix counts as an attempt. List the findings you don't fix (P2, P3) under Left open in the
   entry, not under Gotchas.
7. **Record.** First, if either of these applies, update AGENTS.md, which every later session
   reads in either tool:
   - A command in its Commands failed as written and you found the form that works here: fix
     that line (how the command runs, never what it checks).
   - A gotcha was already in an entry `status` showed you, or it cost an attempt or a paid call
     and a later task could hit it: add one line to `## Known gotchas` (create the section right
     after `## Rules` if it's missing). Task details, open review findings and status never go
     there.
   Then append an entry from `assets/progress-entry.md` to the end of docs/progress.md with
   `Status: done` (and `Plan check: off` unless the user added `confirm`), without reading the
   file first. Its `Digest:` is the one line every later task that builds on this one will see:
   the names, signatures, paths and shapes they consume, at most 280 bytes (`done` refuses
   more). Note an AGENTS.md change under Decisions, and don't repeat a gotcha that Known gotchas
   already holds. Run `done ID`.
8. **Git mode:** read `git status`, stage the task's files plus docs/plan.md, docs/progress.md
   and AGENTS.md (if step 7 changed it) by path (never `.env` or secrets), and commit
   `task ID: <name>`. Never push.
   **Folder mode:** there's nothing to commit; the next `start` takes a new checkpoint.
9. **Hand off and stop:** "Task ID done (<commit hash, or 'folder checkpoint'>). Next: <ID and
   name>, <tier> work. Type `/clear` (or start a new session), switch to <model> at <effort>
   effort, then `/blueprint-solution-builder`. Codex works too: `/new`, `/model` <Codex model> at
   <effort>, then `$blueprint-solution-builder`." Take the tier from the next task's fields, which
   `done` prints, the model and effort from its row in `references/models.md`, and the Codex ones
   from its "Codex in a handoff". If the next task waits on another
   part, name that part's task and folder instead. Don't start another task in this session,
   unless it's in a batch the user named (`references/batch.md`).

## Stop early

Read `references/failure.md` in any of these cases:
- Two attempts at the same failure have failed.
- The task needs something the docs forbid or don't cover: a rule conflict, a doc or plan change,
  a missing file, command or credential, or a dependency that isn't verified.
- The user asks for something outside the task.
- The task turns out too big for this session.

## Never

- Fabricate or estimate output, or say a check passed without running it.
- Weaken, skip or delete a test or check to get green.
- Edit task text or markers in plan.md by hand. Edit the PRD, architecture or essentials only with
  the user's explicit approval, following `references/failure.md`.
- Undo work with `git reset --hard`, `git clean` or by deleting files. Use `restore`.
- Print, log or commit secrets.
- Install a skill or plugin. A listed skill that's missing is skipped and noted, not installed.
- Spawn a subagent without the `model` and `effort` that `references/models.md` gives it, or, in
  supervised mode, delegate core logic under a Spec, a spike, or anything behind a `STOP:`.

## Files in this skill

Open a file only when its mode or step calls for it. The longer references start with a
Contents line that lists their section headings, so even a partial read shows what they cover.

| File | Open when |
|---|---|
| `references/models.md` | Start step 4 (model check), before any subagent spawn, and for each handoff's model |
| `references/batch.md` | Start step 5: a range of tasks without "unattended" |
| `references/unattended.md` | Start step 5: "unattended" |
| `references/failure.md` | Stop early, in any of its cases |
| `references/included-skills.md` | A skill AGENTS.md lists isn't installed: the install command to give the user |
| `assets/review-brief.md` | One task, step 6: the reviewer's brief |
| `assets/progress-entry.md` | One task, step 7: the progress entry |
| `assets/worker-brief.md` | Delegating a routine task (models.md), or each task of an unattended run |
| `assets/handoff-prompt.md` | Stale context (failure.md) |
| `assets/kickoff-prompt.md` | Never by this skill: it is for a user without the skill installed |
| `scripts/blueprint.py` | Run it as "The script" says; don't read it |
