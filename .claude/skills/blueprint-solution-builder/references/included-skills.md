# Included skills: companion skills the workflow can use

The same file ships in both blueprint-solution skills, in Claude Code (`~/.claude/skills/`) and in
Codex (`~/.agents/skills/`). Keep all four copies identical.

The architect proposes skills from this catalog at planning time, the user picks, and the picks
go into the `## Skills` section of the AGENTS.md block. That section is what builders, workers and
reviewers in both tools read. This file is the catalog behind it: what each skill is for, the step
where it runs, and how to check and install it.

## Rules

- The project docs win. The essentials' `## UI design` section is the design brief. A skill's
  generic advice never overrides it, a non-goal, a Done when or AGENTS.md. Where they disagree,
  follow the docs and record the conflict under Decisions.
- A skill helps; it is never a dependency. No Done when may need a skill to pass. If a listed
  skill isn't installed in the tool you run in, skip it, say so once under Gotchas, and continue.
- Installing changes the user's setup: only with the user's yes in this session. A plugin loads
  in the next session (in Claude Code, `/reload-plugins` loads it sooner).
- Run a skill at the step AGENTS.md names, on that task's files. Workers and reviewers use only
  the skills listed there, and only when their brief names them.
- To add a skill to this catalog: check its source first (publisher, license, last commit, and
  what it installs: skills, hooks, MCP servers, scripts), then add its row and section with the
  date you checked. Never add one on reputation alone.

## Catalog

The first three apply only to a product with a UI. grilling is the architect's own interview
method for any product, never a builder skill.

| Skill | Step | What it adds | Checked |
|---|---|---|---|
| grilling | plan (the interview, architect only) | Matt Pocock's design-tree interview: batches of every question whose prerequisites are settled, each with a recommended answer, until no decision is left open | 2026-10-18 |
| frontend-design | plan (design direction), build (UI code) | A design lead's method: a compact token plan (palette, type, layout) reviewed against generic defaults; a quality floor (responsive, visible focus, reduced motion, contrast); UI copy rules | 2026-10-06 |
| ui-ux-pro-max | plan (design direction), build (lookups) | A local design database: `--design-system` proposes a style, palette, fonts, effects and anti-patterns for a product type; 119 UX rules; stack guides (React, Vue, Tailwind and more) | 2026-10-06 |
| web-design-guidelines | review (each UI task), final audit | Vercel's Web Interface Guidelines: about 100 checklist rules (accessibility, focus, forms, motion, layout, i18n, dark mode), reported as file:line | 2026-10-06 |

## grilling

- Source: Matt Pocock, `mattpocock/skills`, plugin `mattpocock-skills` (v1.3.1 when checked) in
  `claude-plugins-official`, MIT. It installs 27 skills and no hooks or MCP servers. Only
  `grilling` is used here; `grill-me` and `grill-with-docs` call it, but only the user can
  invoke those two.
- Claude Code: `/plugin install mattpocock-skills@claude-plugins-official`. The skill's name is
  `mattpocock-skills:grilling`.
- Codex: nothing to install. The Codex architect carries a summary of the method in
  `references/interview.md` ("Grill mode").
- Plan: the architect's grill mode invokes it (`references/interview.md`, "Grill mode"), and the
  rules there win over it: one scope per session, a save after every batch, about four batches
  per session.
- It never goes on the companion-skill card or into AGENTS.md's Skills section: builders,
  workers and reviewers don't interview.

## frontend-design

- Source: Anthropic, `anthropics/claude-plugins-official`, plugin `frontend-design`: one skill,
  no hooks or servers, about 60 tokens per session and 2.3k when invoked.
- Claude Code: `/plugin install frontend-design@claude-plugins-official` (if that marketplace is
  missing: `/plugin marketplace add anthropics/claude-plugins-official` first). The skill's name
  is `frontend-design:frontend-design`.
- Codex: copy `plugins/frontend-design/skills/frontend-design/` from that repo to
  `~/.agents/skills/frontend-design/`; mention it as `$frontend-design`.
- Plan: once the user has picked a look and feel, use its first pass (a compact token plan, then
  a review of that plan against the brief) to write the essentials' UI design section.
- Build: load it before writing UI code. Its push for a distinctive look yields to the UI design
  section; its quality floor and copy rules always apply.

## ui-ux-pro-max

- Source: nextlevelbuilder, `nextlevelbuilder/ui-ux-pro-max-skill`, MIT. The plugin installs 7
  skills: `ui-ux-pro-max` (the one this workflow uses) plus `slides`, `design`, `brand`,
  `banner-design`, `design-system` and `ui-styling`, about 700 tokens per session in all. Its
  search script needs Python 3 and no other packages.
- Claude Code: `/plugin marketplace add nextlevelbuilder/ui-ux-pro-max-skill`, then
  `/plugin install ui-ux-pro-max@ui-ux-pro-max-skill`. The skill's name is
  `ui-ux-pro-max:ui-ux-pro-max`; its SKILL.md gives the script's exact path.
- Codex: `npx ui-ux-pro-max-cli init --ai universal --global` writes
  `~/.agents/skills/ui-ux-pro-max/`. With the Claude plugin already installed, copying its
  `.claude/skills/ui-ux-pro-max/` folder there instead gives the same, already-tested version:
  then replace `${CLAUDE_PLUGIN_ROOT}/.claude/skills/ui-ux-pro-max` in its SKILL.md with
  `$HOME/.agents/skills/ui-ux-pro-max`.
- Plan: run its `--design-system` search with the product type, the domain and 2-3 style words
  (add `--density 8` for a dashboard or tool), and offer the result as one of the look-and-feel
  options. Leave out `--persist`: decisions go into the essentials, never into a second design
  file.
- Build: when a UI question comes up (a UX rule, a component pattern, stack advice), run one
  focused search (`--domain ux`, or `--stack` with the project's stack) instead of guessing.
- Its other six skills stay out of blueprint tasks: never invoke `slides`, `design`, `brand`,
  `banner-design`, `design-system` or `ui-styling` from one.

## web-design-guidelines

- Source: Vercel, `vercel-labs/agent-skills`, folder `skills/web-design-guidelines`: one 1 KB
  SKILL.md, not a plugin. Each run fetches its rules from
  `https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md` (MIT).
  Ask WebFetch for that file's full text verbatim; if what comes back looks summarized, say so.
- Claude Code: save that SKILL.md as `~/.claude/skills/web-design-guidelines/SKILL.md`. The
  skill's name is `web-design-guidelines`. The `blueprint-reviewer` agent has the Skill and
  WebFetch tools it needs to run it.
- Codex: save the same file as `~/.agents/skills/web-design-guidelines/SKILL.md`; mention it as
  `$web-design-guidelines`. A read-only reviewer sandbox usually can't fetch the rules. There, the
  builder runs it after the review and adds its findings to the same list.
- Review: run it on the task's changed UI files only. Grade each finding P0-P3 like the rest: a
  missing label, focus state or keyboard path on a changed control is P1; wording and spacing nits
  are P3. Some rules are opinions (Title Case buttons, URL-synced state). A rule the essentials
  settle otherwise, or one beyond the target (a POC needs no deep links), is not a finding.
- Final audit: run it on all UI source files.

## Checking what's installed

- Claude Code: the skill appears in the session's skills list. In a shell, `claude plugin list`
  shows plugins (the desktop app bundles its own `claude`, which may not be on PATH); user skills
  live in `~/.claude/skills/<name>/`.
- Codex: `~/.agents/skills/<name>/SKILL.md`, or the project's `.agents/skills/<name>/`, exists.
