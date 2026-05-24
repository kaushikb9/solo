# AGENTS.md

Canonical agent guidance for solo. Applies to **any** agent working on this repo — Claude Code, Pi, Codex, Cursor, or otherwise. Tool-specific files like `CLAUDE.md` are pointers to this file.

---

## Project context

Solo is a personal thinking companion built by kb. Telegram captures raw thoughts → SQLite stores them → an LLM classifier runs lazily when `/top` is invoked → ranked priorities are returned. **It is not a task manager.** 90% deterministic pipeline; the agent loop only appears in V1 (`expand`, `review`).

This project is also a **learning vehicle** for AI engineering. Every implementation step that introduces a new AI concept must produce a primer in `docs/concepts/`. Every architectural decision made during implementation gets an ADR in `docs/decisions/`. The goal is compounding learnings.

## Tool matrix (the author works across multiple setups)

| Tool | Model | Notes |
|---|---|---|
| Claude Code | Opus 4.7 | superpowers plugin installed at user level; uses `.claude/` for repo-local commands and agents |
| Pi | Kimi-K2.6 | uses Pi's runtime / extension model |
| Codex | GPT 5.5 | reads `AGENTS.md` natively |

Project conventions in this file are **invariant across tools**. Tool-specific scaffolding (slash commands, subagent definitions, plugin systems) is adapted per tool — see the "Per-tool notes" section at the bottom.

---

## Read first, in this order

| # | Doc | Purpose |
|---|---|---|
| 1 | This file (`AGENTS.md`) | conventions, rituals, workflow |
| 2 | `docs/requirements.md` | problem statement, design principles, behavior constraints |
| 3 | `docs/architecture.md` | chosen architecture, stack, hosting (the load-bearing design doc) |
| 4 | `docs/alternates/pi-runtime.md` | rejected alternate — skim for "why not framework X" context |
| 5 | `docs/status.md` | current state, what's done, what's next |

---

## Constraints to honor

- **Capture must never fail.** If capture breaks, the system breaks. Wrap capture handlers defensively; everything else can fail loudly.
- **Pull, not push.** No notifications, no daily digests, no proactive suggestions. User asks → system responds.
- **Silent by default.** Capture replies with `captured` and nothing else. Don't add commentary the user didn't ask for.
- **No frameworks for the agent loop.** Hand-roll it. Pi/OpenClaw/Hermes are explicitly rejected as runtime dependencies. See `docs/architecture.md` §2-3.

## Engineering conventions

- **All LLM calls go through `solo.llm.LLMClient`.** Never import `openai` / `anthropic` outside `src/solo/llm.py`. The wrapper writes trace rows; bypassing it loses observability.
- **Every LLM call writes a row to the `llm_calls` trace table.** Non-negotiable — cost visibility and debugging depend on it.
- **Prompts live in `src/solo/prompts/*.md`.** Loaded at runtime. Never inline multi-line f-string prompts. Diffable, swappable per model.
- **Use `pydantic` for structured LLM outputs.** Don't parse JSON by hand.
- **Use `uv` for everything.** No `pip install`, no `venv` activation, no `poetry`.

---

## V0 scope (only)

1. Telegram bot writes raw entries to SQLite
2. Lazy classifier when `/top` is invoked
3. `/top` and `/log` commands
4. `llm_calls` trace table written on every LLM call
5. Prompts as files in `src/solo/prompts/`
6. Classifier eval harness (`evals/classify.jsonl` + `scripts/eval.py`)

Out of V0: `expand`, `review`, `commit`, dedup, embeddings, agent loops, web UI.

---

## Workflow (universal)

Use a brainstorm → plan → execute (TDD) → review → verify → ship cycle. Specifics vary by tool — see "Per-tool notes" below for shortcuts. The cycle itself is invariant:

1. **Brainstorm** — clarify intent, requirements, edge cases. Don't jump to code.
2. **Write plan** — for any multi-step change, write the plan first. Save it durably (a markdown file in the worktree if your tool doesn't have a built-in plan store).
3. **Isolate** — work in a branch or worktree. Don't accumulate unrelated changes.
4. **Execute (TDD when feasible)** — write the failing test first; implement to green; refactor.
5. **Review** — both general code-quality review AND solo-conventions review (see `.claude/agents/solo-reviewer.md` — the rules apply across tools even when the agent file is Claude-specific).
6. **Verify** — run all of:
   - `uv run pytest`
   - `uv run ruff check .`
   - If classifier touched: `uv run python scripts/eval.py`
   - If user-facing behavior changed: run the bot locally and exercise the changed path
   No success claims without evidence.
7. **Ship** — merge / PR / cleanup. Update `docs/status.md` as part of the change.

---

## Documentation rituals (the compound-learning system)

### Concept primers — `docs/concepts/<topic>.md`

When implementing something that uses a new AI/agent concept (structured outputs, tool use, embeddings, evals, agent loops, prompt caching, etc.), **write or expand the primer for it in the same change**. Assume the reader is new to AI.

Format:
- **What problem this solves** (plain language)
- **The core idea** (explained as if to a smart friend new to AI)
- **How solo uses it** (link to the file/function with `file_path:line_number`)
- **Common gotchas**
- **Further reading** (only links you've verified)

Length: 300–500 words. Concrete > exhaustive.

### Decisions — `docs/decisions/NNNN-<slug>.md`

When making a non-trivial architectural decision *during implementation*, write a short ADR. Top-level decisions made before code already live in `docs/architecture.md` and don't need duplicating.

Format:
- **Status**: proposed | accepted | superseded by NNNN
- **Date**: YYYY-MM-DD
- **Context**: what's the situation, what forces are at play
- **Decision**: what was chosen
- **Consequences**: what becomes easier, what becomes harder
- **Alternatives considered**: one line each, with reason rejected

Length: ~250 words. Recording the *why* matters more than exhaustive prose.

### Status — `docs/status.md`

Update `docs/status.md` as part of any non-trivial change. Cross-machine work makes this load-bearing — without it, the next agent on the next machine has no "where were we" anchor. Keep it short and dated.

---

## Common commands

```bash
uv sync                              # install deps
uv run python -m solo                # run bot (long polling)
uv run pytest                        # tests
uv run python scripts/eval.py        # classifier eval
uv run ruff check .                  # lint
uv run ruff format .                 # format
```

---

## When in doubt

- Structural change? Write a one-paragraph proposal first. Don't refactor speculatively.
- Beyond V0? Don't build it without explicit ask.
- New AI concept used? Write the primer in the same change.
- Confused about design? Re-read `docs/architecture.md` before guessing.
- About to commit? Run the verification cycle.

---

## Per-tool notes

### Claude Code (Opus 4.7)

- **superpowers plugin** is installed at user level (`/plugin install superpowers@claude-plugins-official`). Use its skills:
  - `superpowers:brainstorming` — required before any creative work
  - `superpowers:writing-plans` — for multi-step tasks
  - `superpowers:using-git-worktrees` — isolate before executing
  - `superpowers:executing-plans` / `superpowers:subagent-driven-development`
  - `superpowers:test-driven-development`
  - `superpowers:systematic-debugging`
  - `superpowers:requesting-code-review`
  - `superpowers:verification-before-completion`
  - `superpowers:finishing-a-development-branch`
- **Repo-local scaffolding** in `.claude/`:
  - `.claude/settings.json` — pre-allowed commands
  - `.claude/commands/concept.md` — `/concept <topic>` bootstraps a primer
  - `.claude/commands/decision.md` — `/decision <topic>` bootstraps an ADR
  - `.claude/agents/solo-reviewer.md` — solo-conventions reviewer
- Always run **both** the generic `code-reviewer` and `solo-reviewer` before claiming done.

### Pi (Kimi-K2.6)

- Pi has its own plan/execute primitives — use them in place of superpowers' skills.
- The `solo-reviewer` agent file in `.claude/agents/` is Claude-Code-specific in *how it's invoked*, but its **content is the convention checklist**. Read it before submitting any change.
- Pi's extension system is *not* used for solo (we explicitly rejected Pi as a runtime — see `docs/alternates/pi-runtime.md`). Use Pi as a coding assistant only.

### Codex (GPT 5.5)

- Codex reads `AGENTS.md` natively — that's this file.
- Use Codex's plan-then-implement pattern. Run the same verification cycle (tests + lint + eval).
- The `.claude/` directory is ignored by Codex — but `.claude/agents/solo-reviewer.md`'s content is still the convention checklist; read it before submitting.

### Other tools

If you're using a tool not listed here, the rule is: **read this file, run the verification cycle, write concept primers and ADRs as you go.** Tool-specific scaffolding may not exist; the conventions still do.
