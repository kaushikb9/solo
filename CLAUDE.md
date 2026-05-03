# Agent Working Agreement

This file is the contract for agents (and humans) editing solo. Read it before writing code or proposing changes.

## Read first, in this order

1. `requirements.md` — problem statement and design principles
2. `claude-solution.md` — chosen architecture and stack rationale
3. `pi-solution.md` — alternate architecture (skim — useful for "why not framework X")
4. This file — conventions, rituals, commands

## Project shape (one paragraph)

Solo is a personal thinking companion. Telegram captures raw thoughts → SQLite stores them → an LLM classifier runs lazily when `/top3` is invoked → ranked priorities are returned. **It is not a task manager.** 90% deterministic pipeline; the agent loop only appears in V1 (`expand`, `review`).

## Constraints to honor

- **Capture must never fail.** If capture breaks, the system breaks. Wrap capture handlers defensively; everything else can fail loudly.
- **Pull, not push.** No notifications, no daily digests, no proactive suggestions. User asks → system responds.
- **Silent by default.** Capture replies with `captured` and nothing else. Don't add commentary the user didn't ask for.
- **No frameworks for the agent loop.** Hand-roll it. Pi/OpenClaw/Hermes are explicitly rejected as runtime dependencies. See `claude-solution.md` §2-3.

## Engineering conventions

- **All LLM calls go through `solo.llm.LLMClient`.** Never import `openai`/`anthropic` outside `src/solo/llm.py`. The wrapper writes trace rows; bypassing it loses observability.
- **Every LLM call writes a row to the `llm_calls` trace table.** Non-negotiable — cost visibility and debugging depend on it.
- **Prompts live in `src/solo/prompts/*.md`.** Loaded at runtime. Never inline multi-line f-string prompts. Diffable, swappable per model.
- **Use `pydantic` for structured LLM outputs.** Don't parse JSON by hand.
- **Use `uv` for everything.** No `pip install`, no `venv` activation, no `poetry`.

## V0 scope (only)

1. Telegram bot writes raw entries to SQLite
2. Lazy classifier when `/top3` is invoked
3. `/top3` and `/log` commands
4. `llm_calls` trace table written on every LLM call
5. Prompts as files in `src/solo/prompts/`
6. Classifier eval harness (`evals/classify.jsonl` + `scripts/eval.py`)

Out of V0: `expand`, `review`, `commit`, dedup, embeddings, agent loops, web UI.

## Workflow (use superpowers)

This repo assumes the [superpowers](https://github.com/obra/superpowers) plugin is installed at user level (`/plugin install superpowers@claude-plugins-official`). Superpowers exposes its workflow as **Skills** (invoked via the Skill tool), not slash commands. Use them in order:

1. **`superpowers:brainstorming`** — required before any creative work. Explores intent, requirements, and design before code.
2. **`superpowers:writing-plans`** — for any multi-step task, write a plan before touching code.
3. **`superpowers:using-git-worktrees`** — create an isolated worktree before executing the plan.
4. **`superpowers:executing-plans`** or **`superpowers:subagent-driven-development`** — execute the plan with review checkpoints, optionally splitting independent tasks across subagents.
5. **`superpowers:test-driven-development`** — write the failing test first when implementing a feature or bugfix.
6. **`superpowers:systematic-debugging`** — for any bug, test failure, or unexpected behavior, before proposing fixes.
7. **`superpowers:requesting-code-review`** — when work is feature-complete. Plus run the `solo-reviewer` agent in `.claude/agents/` for solo-specific convention checks.
8. **`superpowers:verification-before-completion`** — required before claiming work is done. Runs tests, lint, eval; demands evidence before assertions.
9. **`superpowers:finishing-a-development-branch`** — decide merge / PR / cleanup once verified.

For UI/observable behavior changes, run the bot locally and exercise the path manually. Type-checking and tests verify code correctness, not feature correctness.

## Documentation rituals (the compound-learning system)

The user is intentionally treating this project as a learning vehicle. Two rituals make the learning compound:

### Concept primers — `docs/concepts/<topic>.md`

When implementing something that uses a new AI/agent concept (structured outputs, tool use, embeddings, evals, agent loops, prompt caching, etc.), **write or expand the primer for it in the same change**. Assume the reader is new to AI.

Format:
- **What problem this solves** (plain language)
- **The core idea** (explained as if to a smart friend new to AI)
- **How solo uses it** (link to the actual file/function)
- **Common gotchas**
- **Further reading** (only links you've verified)

Length: 300–500 words. Concrete > exhaustive. Use `/concept <topic>` to bootstrap.

### Decisions — `docs/decisions/NNNN-<slug>.md`

When making a non-trivial architectural decision *during implementation*, write a short ADR. Top-level decisions made before code already live in `claude-solution.md` and don't need duplicating.

Format:
- **Status**: proposed | accepted | superseded
- **Context**: what's the situation, what forces are at play
- **Decision**: what was chosen
- **Consequences**: what becomes easier, what becomes harder
- **Alternatives considered**: one line each, with reason rejected

Use `/decision <topic>` to bootstrap.

## Common commands

```bash
uv sync                              # install deps
uv run python -m solo.bot            # run bot (long polling)
uv run pytest                        # tests
uv run python scripts/eval.py        # classifier eval
uv run ruff check .                  # lint
uv run ruff format .                 # format
```

## When in doubt

- Structural change? Write a one-paragraph proposal in chat first. Don't refactor speculatively.
- Beyond V0? Don't build it without explicit ask.
- New AI concept used? Write the primer in the same change.
- Confused about design? Re-read `claude-solution.md` before guessing.
- About to commit? Run both reviewers (`code-reviewer` and `solo-reviewer`).
