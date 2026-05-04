---
description: Write or expand a noob-friendly AI concept primer in docs/concepts/
---

You are creating or updating an AI-engineering concept primer for someone new to the AI world. The topic is: $ARGUMENTS

Steps:
1. Slugify the topic (lowercase, hyphens). Check if `docs/concepts/<slug>.md` already exists.
2. If it exists, read it and consider expanding rather than rewriting. If not, create it.
3. Use this structure:
   - **What problem this solves** — plain language, no jargon
   - **The core idea** — explained as if to a smart friend who's new to AI
   - **How solo uses it** — link to the actual file/function in this repo (use file_path:line_number)
   - **Common gotchas** — what trips people up
   - **Further reading** — only links you've actually verified are good
4. If new, add an entry to `docs/concepts/README.md` index in alphabetical order.
5. Confirm the path and what was added.

Length target: 300–500 words. Concrete examples > exhaustive theory.
