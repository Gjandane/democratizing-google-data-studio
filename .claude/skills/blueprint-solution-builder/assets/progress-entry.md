# Progress entry (template D.5): append to docs/progress.md, newest at the bottom

```markdown
## <YYYY-MM-DD>: Task <id> <name>
- Status: <done | partial | blocked>
- Plan check: <off | confirmed | corrected: what the user changed | unattended>
- What changed: <files and behavior, one or two lines>
- Checks: `<Done-when command>` <PASS or FAIL, with counts>; Test (all) `<command>` <PASS or FAIL, with counts>; <UI tasks: each manual item yes/no, and the screenshot paths>
- Decisions: <choices the docs didn't fix, especially shapes later tasks consume (names, types, paths); for an algorithm, the approach, its parameters and the measured budget; or none>
- Digest: <done entries: ONE line, at most 280 bytes, of what later tasks consume: names, signatures, paths, shapes>
- Tried and failed: <each approach that didn't work, and why; or none>
- Gotchas: <what the next session would trip on; or none>
- Left open: <review findings you chose not to fix, as "P2 <title> - <path>"; or none>
- Next: <Task X.Y. Start by ...  -- or, for partial: the exact next step in this task>
```

Blocked entries add three lines:

```markdown
- Blocked because: <(a) every option breaks a rule | (b) needs a change to PRD, architecture, essentials or plan | (c) something named does not exist | (d) failed twice and the cause can't be named>
- Question: <one answerable sentence>
- Options: A <...> / B <...> / Recommend: <A or B, and why>
```

Write it for someone with no context, in under 200 words, and append it without reading
progress.md first. `Checks` holds real results only. `status` shows What changed, Decisions and
Gotchas to the tasks that depend on this one directly, and only the Digest to the tasks further
on, so the Digest must stand alone: "`load_orders(path) -> list[Order]` in src/orders.py;
`total_cents` is int" helps a later task, "implemented order loading" doesn't. `blueprint.py done`
refuses a done entry without Checks or with no Digest, a Digest over several lines, or one over
280 bytes.
