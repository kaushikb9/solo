# Solo

Personal thinking companion. Captures raw thoughts via Telegram, surfaces what matters via `/top3`. Not a task manager.

This is also a **learn-by-building** project for getting fluent in AI engineering and agentic systems. Each implementation step is documented in `docs/concepts/` so the learning compounds.

## Status

V0 — pre-implementation. Design is settled; code starts next.

## Read first

| Doc | Purpose |
|---|---|
| [`requirements.md`](requirements.md) | Problem statement, design principles, behavior constraints |
| [`claude-solution.md`](claude-solution.md) | Chosen architecture, tech stack, hosting |
| [`pi-solution.md`](pi-solution.md) | Alternate architecture (rejected — kept for context) |
| [`CLAUDE.md`](CLAUDE.md) | Working agreement for agents (and humans) editing this repo |
| [`docs/`](docs/) | Concept primers and Architecture Decision Records |

## Stack

Python 3.12 · `uv` · `python-telegram-bot` (long polling) · SQLite · OpenRouter · Pydantic. Deployed on Railway.

## Local dev

```bash
uv sync                              # install deps
cp .env.example .env                 # fill in secrets
uv run python -m solo.bot            # start bot (long polling)
uv run pytest                        # tests
uv run python scripts/eval.py        # classifier eval
```

## Working with agents

This repo is built to be agent-collaborative. Two layers:

1. **Methodology layer** — install [superpowers](https://github.com/obra/superpowers) once at user level: `/plugin install superpowers@claude-plugins-official`. Gives you `/brainstorm`, `/write-plan`, `/execute-plan`, TDD skill, generic code-reviewer.

2. **Solo-specific layer** — lives in this repo:
   - `CLAUDE.md` — project context and conventions agents must follow
   - `.claude/agents/solo-reviewer.md` — checks LLMClient discipline, traces, prompts-as-files
   - `.claude/commands/concept.md` — `/concept <topic>` writes a noob-friendly primer
   - `.claude/commands/decision.md` — `/decision <topic>` writes an ADR

Use both. Superpowers tells you *how* to build; this repo's scaffolding tells you *what's true about solo*.

## V0 scope

Capture (Telegram) → lazy classifier → `/top3` and `/log`. Plus the agent-engineering hygiene that compounds: structured trace, prompts as files, classifier eval, concept docs.
