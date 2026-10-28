# Headless: one task, nobody watching

This session was started with `headless` and a task ID, usually by `scripts/overnight.py` running
`claude -p` or `codex exec`. It is a single turn, and nobody reads it until morning, so every
point where the skill would ask the user has a fixed answer below. Everything else runs exactly
as the supervised loop says: `start`, build (or delegate), verify, review, record, `done`, commit.

## Fixed answers

| Where the skill would ask the user | Headless answer |
|---|---|
| `status` prints a `STOP` warning, a change request, or a wait on another part's task | End now. Run nothing else and write nothing. Report `stopped` |
| The task has a `STOP:` field, or is `Size: L` and the run didn't allow L tasks | End now, the same way |
| No CLAUDE.md (a plan made in Codex) | Read AGENTS.md now; note the missing CLAUDE.md under Gotchas |
| The model check (in Codex, the model line) | Skip it; the runner chose the model and effort for this task's tier |
| The plan check, or `confirm` | Off. The entry says `Plan check: unattended` |
| failure.md cases (a)-(c): a new dependency, a doc change, a missing file, command, tool or credential | Block the task as failure.md's "Blocking a task" says, with the question and options a person can answer in the morning. Docs and the Dependencies table stay as they are |
| A tool call or command is denied | Case (c): name the denied call under `Question:` and the permission that would allow it under `Options:` |
| Two attempts fail | failure.md as written: `restore`, a `partial` entry, commit the entry. The runner starts a fresh session that resumes the task |

## Finishing

The session is done when the task's marker has moved (`[x]`, or `[!]`), or a `partial` entry is
committed with the marker still `[~]`, or you ended at a fixed answer above. Then:
1. Stop every server, watcher or browser you started.
2. End your reply with one line the runner logs:
   `HEADLESS RESULT: <ID> <done | partial | blocked | stopped>: <one sentence>`

One task per session: the runner starts the next one in a fresh session. Work stays local and
unpushed, inside this project folder.
