# Solo

Personal thinking companion. Captures raw thoughts via Telegram, surfaces what matters via `/top`. Not a task manager.

This is also a **learn-by-building** project for getting fluent in AI engineering and agentic systems. Each implementation step is documented in `docs/concepts/` so the learning compounds.

## Status

**V0 complete.** Capture (`bot.py`), lazy classifier (`classifier.py`), `/top` and `/log` commands, `llm_calls` trace table, prompts-as-files, classifier eval harness (`scripts/eval.py`). V1 (`/expand` — first hand-rolled agent loop) is next.

## Read first

| Doc | Purpose |
|---|---|
| [`AGENTS.md`](AGENTS.md) | **Canonical agent guidance — tool-agnostic.** Read first if you're an agent (Claude Code, Pi, Codex, etc.) |
| [`docs/requirements.md`](docs/requirements.md) | Problem statement, design principles, behavior constraints |
| [`docs/architecture.md`](docs/architecture.md) | Chosen architecture, tech stack, hosting |
| [`docs/alternates/pi-runtime.md`](docs/alternates/pi-runtime.md) | Alternate architecture (rejected — kept for context) |
| [`docs/status.md`](docs/status.md) | Current state, what's done, what's next |
| [`docs/concepts/`](docs/concepts/) | AI/agent concept primers (compound learning) |
| [`docs/decisions/`](docs/decisions/) | Architecture Decision Records made during implementation |

## Stack

Python 3.12 · `uv` · `python-telegram-bot` (long polling) · SQLite · OpenRouter · Pydantic. Currently deployed on local but can be hosted anywhere.

## Local dev

```bash
uv sync                              # install deps
cp .env.example .env                 # fill in secrets
uv run python -m solo                # start bot (long polling)
uv run pytest                        # tests
uv run python scripts/eval.py        # classifier eval
```

## Environment

Copy `.env.example` to `.env` and fill in:

| Var | Required | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | From @BotFather. |
| `SOLO_ALLOWED_CHATS` | yes | Comma-separated Telegram chat IDs allowed to talk to the bot. Get yours from @userinfobot. |
| `OPENROUTER_API_KEY` | yes (slice 2 onward) | From [openrouter.ai/keys](https://openrouter.ai/keys). One key, many models. |
| `SOLO_CLASSIFY_MODEL` | yes (slice 3 onward) | Model used by the lazy classifier. Default `minimax/minimax-m2.7`. |
| `SOLO_EXPAND_MODEL` | not in V0 | Model for V1 `expand`/`review`. Default `moonshotai/kimi-k2.6`. |
| `SOLO_DB_PATH` | yes | Path to the SQLite file. Default `./data/solo.db`. |

`OPENROUTER_API_KEY` is the only model-API credential — solo routes everything through OpenRouter.

## Working with agents

This repo is tool-agnostic. The canonical guidance is [`AGENTS.md`](AGENTS.md), read by any agent on any tool.

The author works across multiple setups: Claude Code (Opus 4.7) with the [superpowers](https://github.com/obra/superpowers) plugin, Pi with Kimi-K2.6, Codex with GPT 5.5. Tool-specific scaffolding lives in `.claude/` (Claude Code only); the conventions themselves are universal — see `AGENTS.md` for the per-tool notes.

## V0 scope

Capture (Telegram) → lazy classifier → `/top` and `/log`. Plus the agent-engineering hygiene that compounds: structured trace, prompts as files, classifier eval, concept docs.
