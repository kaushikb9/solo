# docs

Two living folders, both write-as-you-go:

| Folder | Purpose |
|---|---|
| [`concepts/`](concepts/) | Noob-friendly primers on AI/agent concepts as solo encounters them. The compound-learning system. |
| [`decisions/`](decisions/) | Architecture Decision Records for non-trivial choices made during implementation. |

Two slash commands bootstrap entries:
- `/concept <topic>` — new concept primer
- `/decision <topic>` — new ADR

Top-level architectural decisions made before code already live in [`architecture.md`](architecture.md) and don't need duplicating as ADRs.

Other docs in this folder:
- [`requirements.md`](requirements.md) — problem statement, design principles
- [`architecture.md`](architecture.md) — chosen architecture, stack, hosting
- [`alternates/pi-runtime.md`](alternates/pi-runtime.md) — rejected Pi-runtime architecture (kept for context)
- [`status.md`](status.md) — current state, what's done, what's next
