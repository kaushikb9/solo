# CLAUDE.md

See [`AGENTS.md`](AGENTS.md) — canonical agent guidance for this repo (tool-agnostic).

Claude-Code-specific scaffolding lives in [`.claude/`](.claude/):

- `.claude/settings.json` — pre-allowed commands
- `.claude/commands/concept.md` — `/concept <topic>` bootstraps a concept primer
- `.claude/commands/decision.md` — `/decision <topic>` bootstraps an ADR
- `.claude/agents/solo-reviewer.md` — solo-conventions reviewer (run before claiming a change is done, alongside the generic `code-reviewer`)

The `solo-reviewer` agent's *content* — the convention checklist — applies across all tools, even though the file is invoked via Claude Code's Agent tool. Read it for the rules.

For superpowers plugin guidance and the universal workflow, see [`AGENTS.md`](AGENTS.md).
