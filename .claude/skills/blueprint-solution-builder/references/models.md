# Models: which model does which work (Claude Code only)

The session model is the brain: it plans, specifies, designs algorithms, decides how a task is
built, and verifies. Subagents are the hands: they search and type out work that is already
decided. Heavy logic never goes to a cheaper model. The Codex copies of these skills have their
own models.md with Codex models ("Codex in a handoff" sums it up); neither changes a shared
format. Keep this file identical in both skills.

Contents: Tiers · The session · Subagents · Check your model first · Delegating a routine task ·
Codex in a handoff · Gotchas

## Tiers

Work out a task's tier from its fields in docs/plan.md; never add a field for it.
- **deep**: it has `Spec:` or `STOP:`, or `Size: L`, or it is 1.1 (the walking skeleton). Spikes
  and the design foundation carry a `STOP:`, so they are deep.
- **routine**: anything else.

## The session

Models from weakest to strongest: haiku, sonnet, opus, fable (`best` is Fable where the user has
it, otherwise Opus).

| Work | Recommended | Lowest without a card | Effort |
|---|---|---|---|
| Architect session, every mode | `best` | opus | high |
| Builder, deep task | opus; `best` for a spike or a hard Spec | opus | high |
| Builder, routine M task | opus, delegating to a sonnet worker | sonnet (then build it yourself) | medium |
| Builder, routine S task, or a batch | sonnet | sonnet | medium |
| Builder, unattended run | opus | sonnet | medium |

## Subagents

Pass `model` and `effort` on every spawn, as below, so a fallback agent (Explore, general-purpose)
doesn't inherit the session's model. The Agent tool takes `haiku`, `sonnet`, `opus` or `fable`
(not `best`).

| Subagent | model | effort |
|---|---|---|
| `blueprint-reviewer`, or Explore standing in for it (every audit and review) | opus; fable when the session runs Fable | high |
| Explore, brownfield map | sonnet | - |
| Explore, narrow search | haiku | - |
| `blueprint-worker`, deep task (unattended only) | opus | high |
| `blueprint-worker`, routine task | sonnet | medium |
| `blueprint-worker`, mechanical piece (optional) | haiku | low |

## Check your model first

Do this right after `status`, before reading anything else: a model switch later drops the prompt
cache, so the whole context is re-read at full price.
1. Your system prompt names the model you run on; `status` prints the effort. Find the row for this
   work in "The session". A batch takes the row of its deepest task (an S task with a `Spec:` is
   deep).
2. Go on without a word if the model is at or above the lowest without a card, the effort is at or
   above the row's, and you aren't Fable on routine work.
3. Otherwise ask on one AskUserQuestion card: "<Mode, or task ID> is <tier> work: <one reason, e.g.
   'it designs the ranking algorithm'>. Recommended: <model> at <effort> effort."
   - **Switch (Recommended)**: "I'll stop here. Type `/model <alias>` and `/effort <level>` (in the
     desktop app, its model and effort menus), then run the same command again. The files keep
     the state."
   - **Continue on <current model>**: the trade-off in a few words (a quality risk, or the cost).
4. **Switch:** repeat how to switch and end your turn. Write nothing to the docs and don't run
   `start`. **Continue:** go on, and don't ask again this session. An answer that auto-continued
   because the user was away counts as Continue: this card advises, it isn't a STOP, and an
   unattended run must not stall on it.
5. Handoffs name the model for the next session: from the architect, the first ready task's row;
   from the builder, the next task's row; when a handoff sends the user to the architect, `best`
   at high. The "Codex works too" part names the Codex model ("Codex in a handoff").

## Delegating a routine task

A routine M task on an Opus or Fable session: you decide how it's built, and a Sonnet worker
types it out. A routine S task, a batch, a deep task or a Sonnet session: build it yourself.
1. Explore what the task needs (Explore with `model: haiku` for a wide search).
2. Write the build notes, 10-30 lines: the files, each new function or component with its
   signature, the data shapes, the edge cases, the test that makes Done when fail before the
   change, and the essentials rules that apply. No code beyond signatures and the task's
   `verbatim` blocks.
3. Spawn `blueprint-worker` with `model: sonnet` and `effort: medium`, in the foreground, with the
   builder's `assets/worker-brief.md` filled in, including the build notes.
4. Rerun the Done-when command and Test (all) yourself; the worker's report is a claim. Then review
   as SKILL.md says.
5. Send the P0 and P1 findings or failing checks back to the same worker once, with SendMessage.
   After that, fix it yourself or go to Stop early. Each round counts as an attempt.
6. You write the progress entry: the build notes in one line under Decisions, plus the worker's
   deviations and Gotchas.

In supervised mode, never delegate core logic under a Spec, a spike, anything behind a `STOP:`, or
a fix the worker already failed. (An unattended run delegates every task, and a deep one goes to an
Opus worker.) In a deep task you may still hand a self-contained mechanical piece (fixtures, a
rename across files, copying tokens) to a haiku worker, with exact instructions in its brief.

## Codex in a handoff

The Codex skills' models.md adds a **frontier** tier: a task with `Spec:` and also `STOP:` (a
spike) or `Size: L`. For the "Codex works too" part of a handoff, name the next task's Codex
setting: frontier, `gpt-6-astra` at high; any other deep task, `gpt-6.1-sol` at high; routine,
`gpt-6.1-sol` at low (Light). To the architect: `gpt-6.1-sol` at high, or `gpt-6-astra` at high
for a program's root. In Codex the user switches with `/model` (in the app, `/model` and
`/reasoning`).

## Gotchas

- A skill's `model:` frontmatter lasts one turn, and the session model resumes silently on the next
  prompt. That's why this file uses a card, not frontmatter.
- `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` makes Claude Code ignore every subagent model here, and an
  organization's `availableModels` allowlist can swap one. If a subagent's work looks weaker than
  its tier, ask the user to check `/status` and those settings.
- A family alias resolves to the session's exact model when the session is in that family, so an
  Opus session's `opus` reviewer is the same model at its own effort.
