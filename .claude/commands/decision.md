---
description: Write an Architecture Decision Record in docs/decisions/
---

Write an ADR (Architecture Decision Record) for: $ARGUMENTS

Steps:
1. Find the next sequence number — list `docs/decisions/`, take the highest existing NNNN, add 1.
2. Slugify the topic (lowercase, hyphens).
3. Create `docs/decisions/NNNN-<slug>.md` with:
   - **Status**: proposed | accepted | superseded by NNNN
   - **Date**: YYYY-MM-DD
   - **Context**: what's the situation, what forces are at play
   - **Decision**: what was chosen
   - **Consequences**: what becomes easier, what becomes harder
   - **Alternatives considered**: one line each, with reason rejected
4. Add an entry to `docs/decisions/README.md` index.
5. Confirm path and key points.

Keep it tight (~250 words). The point is recording the *why*, not exhaustive prose.
