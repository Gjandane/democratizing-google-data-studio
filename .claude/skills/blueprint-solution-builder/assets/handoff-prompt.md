# Handoff prompt (template D.7): end any session on purpose

The builder does this at the end of every task. Use it by hand when a session goes stale (a fixed
bug returns, a rule gets forgotten, files get re-read or answered questions re-asked, an
architecture decision gets contradicted) or the context is filling up (`/context` shows how full it
is). Don't wait until it's full.

```
We're ending this session. Add an entry to docs/progress.md written for someone with no context:
status, what changed, decisions, what we tried that failed and why, gotchas, and the exact next step.
Keep it under 200 words, then show it to me.
```

Then type `/clear` (or start a new session). The next session can be in Claude Code or in Codex;
both pick up from docs/progress.md.
