# Solo — Pi as the Primary Runtime

## How We Got Here

### The starting point

The requirements identify a clear problem: thoughts and ideas arrive everywhere (Workflowy, Reminders, Bear, WhatsApp, notebook), get captured inconsistently, and are rarely revisited or acted upon. The desired system is a **thinking companion** — not a task manager — that turns raw thoughts into prioritized, actionable thinking work.

The natural first instinct is to build a minimal standalone system: a Python Telegram bot, SQLite, single-shot LLM calls for classification, and a hand-rolled agent loop for `expand`/`review`. This works. It is defensible. Claude's solution documents exactly this path.

### The pivot

Three observations make pi a stronger foundation:

**1. You already live in pi.**

Pi is your daily coding companion. You already understand its command system, its TUI, and its model-switching behavior. Building a separate system means learning and maintaining a second runtime. Using pi means the thinking system and the coding system share the same interface, auth, and mental model.

**2. Pi's runtime is separable from its TUI.**

Pi runs in four modes: interactive (TUI), print, JSON, and RPC. The extension system — tools, commands, events, session management, context window handling, compaction — works in all four modes. The TUI is a frontend; the runtime is the engine.

OpenClaw proves this concretely: it is a pi package that runs the `AgentSessionRuntime` **headlessly** on your Mac, adds a gateway, and bridges Telegram/WhatsApp messages into the agent. The only reason OpenClaw is local-first is because it needs device-local access (contacts, calendar, camera, screen). Solo needs none of that. The same architecture deploys to Railway.

**3. The learning goal favors pi.**

The stated goal is to become effective at **AI engineering and agentic systems**. Standalone Python teaches Telegram bots, SQLite, and LLM API calls — useful, but web services, not agent engineering. Using pi teaches:
- How production agent runtimes handle auth, model registry, and switching
- How event-driven extension architectures work
- How context window management, compaction, and branching keep reasoning sessions productive
- How to deploy a headless agent runtime

These are the infrastructure skills of AI engineering. Building them from scratch is possible, but using a system that exposes every layer lets you inspect, extend, and understand before you replace.

### The decision

Use pi's `AgentSessionRuntime` as the foundation. Implement Solo as a pi extension that starts a Telegram bot, stores thoughts in SQLite, surfaces priorities via commands, and delegates deep reasoning to pi's agent loop when needed. Deploy headlessly on Railway. Use locally with the TUI when at your laptop.

This is not framework cargo-culting. It is using a runtime you already operate, whose internals you can inspect at every layer, to solve a problem it was architected to support.

---

## Thesis

Pi's **runtime and its TUI are separable**.

The `AgentSessionRuntime` is pi's core engine — LLM loop, model registry, tool dispatch, context management, compaction, and the entire extension system. The TUI (interactive mode) is merely a frontend consumer of this runtime. The extension system, SDK, and all runtime APIs work identically with or without the TUI attached.

This is exactly how OpenClaw is built: it is a pi package that runs pi's `AgentSessionRuntime` **headlessly** (no TUI), adds a gateway (Telegram, WhatsApp, HTTP), and bridges channel messages into the agent. OpenClaw's default is `bind: "loopback"` because it needs device-local access — contacts, calendar, camera, screen. Solo doesn't need any of this. For a system with zero device dependencies, the same architecture deploys cleanly to Railway.

**Solo = OpenClaw minus device integrations**, running as a headless Node.js process that happens to embed a world-class agent runtime.

---

## Evidence: OpenClaw on Railway

OpenClaw's doc page `https://docs.openclaw.ai/install/railway` confirms deployment on Railway. Its architecture is:

```json
{
  "gateway": {
    "mode": "local",
    "port": 18789,
    "bind": "loopback",
    "tailscale": { "mode": "off" }
  },
  "channels": {
    "telegram": { "enabled": true, "botToken": "..." },
    "whatsapp": { "enabled": true }
  }
}
```

OpenClaw runs as a **launchd daemon** on macOS (`ai.openclaw.gateway.plist`) and via equivalent service managers on Linux/Windows. The `gateway` command runs `openclaw gateway --port 18789` — not `openclaw interactive`. It is a server process. Channels connect via Telegram's outbound polling, not inbound HTTP. The gateway exists for webhooks and HTTP integrations; Telegram doesn't need it.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       Railway Container (Node.js)                       │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │              Headless Pi Runtime (AgentSessionRuntime)           │   │
│  │                                                                  │   │
│  │  ┌────────────┐     input event      ┌─────────────────────┐   │   │
│  │  │ Telegram   │ ───────────────────> │ Solo Extension   │   │   │
│  │  │ Bot        │   (intercepted)      │   (solo.ts)      │   │   │
│  │  │ (polling)  │                      │                     │   │   │
│  │  └────────────┘                      │  ┌───────────────┐  │   │   │
│  │           ^                          │  │  SQLite       │  │   │   │
│  │           │ reply                     │  │  (mounted     │  │   │   │
│  │           └──────────────────────────│  │   volume)     │  │   │   │
│  │                                      │  └───────────────┘  │   │   │
│  │                                      │                     │   │   │
│  │                                      │  Commands:          │   │   │
│  │                                      │   /top3  /log       │   │   │
│  │                                      │   /expand  /review  │   │   │
│  │                                      │   /commit           │   │   │
│  │                                      └─────────────────────┘   │   │
│  │                                                     │           │   │
│  │                                                     v           │   │
│  │                                      ┌─────────────────────┐   │   │
│  │                                      │   Pi Agent Core     │   │   │
│  │                                      │  (LLM loop, tools,  │   │   │
│  │                                      │   streaming)        │   │   │
│  │                                      └─────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  No TUI. No interactive mode. No terminal. Just a Node.js daemon.       │
└─────────────────────────────────────────────────────────────────────────┘
```

The extension auto-discovers from `.pi/extensions/solo/`. The Telegram bot runs as part of the extension. One process. One container. One deploy.

---

## Addressing the Core Counter-Argument

The strongest case against using pi is pedagogical: *"Frameworks hide the interesting parts. Owning the loop teaches what frameworks abstract."*

This is valid, but misidentifies what pi is.

**Pi is not a framework.** It is a coding harness whose extension system exposes every layer of the agent runtime as an interceptable event:

| Event | What You See/Control |
|---|---|
| `input` | Every message before it hits the LLM. You can block, transform, or handle. |
| `before_agent_start` | The full system prompt and message chain before the LLM call. |
| `context` | Every message about to be sent. You can filter, inject, reorder. |
| `tool_call` | Every tool invocation with mutable arguments. You can block or modify. |
| `tool_result` | Every tool result before it goes back to the LLM. You can rewrite it. |
| `turn_start` / `turn_end` | Full visibility into each reasoning step. |

Using pi's runtime does not hide the agent loop — it *surfaces it as an event stream you can inspect and manipulate*. You learn how production runtimes handle auth, model switching, context window management, compaction, and tool dispatch. These are the **infrastructure** skills of AI engineering.

If you want to hand-roll a tool-use loop for `expand`, you still can — inside the extension, using direct API calls. Pi doesn't force you to use its loop. It gives you the option.

---

## How Each Requirement Maps

### 1. Frictionless Capture

**Telegram:** Extension's async factory starts a Telegram bot. On each message:

```typescript
bot.on("message", (msg) => {
  if (!msg.text) return;
  chatId = msg.chat.id;
  pi.sendUserMessage(`capture: ${msg.text}`, { source: "extension" });
});
```

The `input` handler intercepts before the LLM sees it:

```typescript
pi.on("input", async (event, _ctx) => {
  if (event.text?.startsWith("capture: ")) {
    const text = event.text.slice(9);
    db.prepare("INSERT INTO entries (raw_text, created_at) VALUES (?, ?)")
      .run(text, Date.now());
    if (chatId) bot.sendMessage(chatId, "✓");
    return { action: "handled" }; // Silent. Zero tokens.
  }
  return { action: "continue" };
});
```

**CLI/local:** When at your laptop: `cd ~/solo && pi`. The extension loads from `.pi/extensions/`. Type a thought — the `input` handler intercepts it silently. Same friction as Telegram, no separate tool needed. Pi is already your terminal companion.

**Offline:** Telegram fails (no internet). CLI path works (local pi + SQLite). Same constraint as standalone.

### 2. Classification & Summarization

Direct API calls **outside** pi's agent loop. The approach borrows from Claude's solution but uses `openai` SDK pointed at OpenRouter (single key, every model):

```typescript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "https://openrouter.ai/api/v1",
  apiKey: process.env.OPENROUTER_API_KEY,
});

async function classifyEntry(raw: string) {
  const response = await client.chat.completions.create({
    model: "anthropic/claude-sonnet-4",
    messages: [{ role: "user", content: classifyPrompt(raw) }],
    response_format: { type: "json_object" },
  });
  // Parse structured output, store in SQLite
}
```

**Lazy (V0):** When `/top3` is invoked, batch-classify unclassified rows first, then query.

**Eager (V1):** `setInterval` in the extension periodically classifies oldest entries. No cron.

### 3. Structured Trace Table — Borrowed Pattern

Every LLM call gets a row — exactly as Claude's solution proposes, but in SQLite:

```sql
CREATE TABLE llm_calls (
  id INTEGER PRIMARY KEY,
  run_id TEXT,
  model TEXT,
  prompt_hash TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  latency_ms INTEGER,
  cost_usd REAL,
  created_at INTEGER
);
```

~20 lines of instrumentation code. Pays back forever in cost visibility and debugging. This is not optional — it's table stakes.

### 4. Prompts as Files — Borrowed Pattern

Classification prompt lives in `prompts/classify.md`:

```
Classify the following thought into one of: idea, note, hard_task, soft_task.

Thought: {{raw}}

Respond in JSON: {"type": "...", "title": "...", "summary": "..."}
```

Loaded at runtime with string replacement. Diffable, versionable, swappable per model. Same eval harness (`evals/classify.jsonl` + `scripts/eval.ts`) to turn prompt iteration from vibes into a number.

### 5. Structured Storage

SQLite is the **only durable store**:

```sql
CREATE TABLE entries (
  id INTEGER PRIMARY KEY,
  raw_text TEXT,
  title TEXT,
  summary TEXT,
  type TEXT,
  created_at INTEGER,
  last_seen_at INTEGER,
  duplicate_of INTEGER REFERENCES entries(id)
);
```

Mounted as persistent Railway volume (`/data/solo.db`).

Pi's session JSONL is **working memory only** — reasoning context for current `expand`/`review` sessions. Compaction bounds it. SQLite survives forever.

**Future:** When a Mac CLI or second surface is needed, migrate to **Turso** — hosted SQLite over the wire. Railway bot and Mac CLI connect to the same DB. Same SQL, drop-in via `libsql` package.

### 6. Surfacing Priorities

`/top3` is a registered pi command:

```typescript
pi.registerCommand("top3", {
  handler: async (_args, ctx) => {
    await classifyUnclassified(); // batch classify
    const rows = db
      .prepare("SELECT * FROM entries WHERE type = 'soft_task' ORDER BY last_seen_at DESC LIMIT 10")
      .all();
    const scored = rows.map(rank);
    const top3 = scored.slice(0, 3);
    return formatTop3(top3); // Reply sent back to Telegram
  }
});
```

Users invoke via Telegram (`/top3`) or terminal (`/top3`). Same handler.

`/log` is similar — query, group by type, render.

### 7. Expand (Where Pi's Loop Earns Its Keep)

`/expand <id>` injects the entry into pi's context and triggers the agent loop:

```typescript
pi.registerCommand("expand", {
  handler: async (args, ctx) => {
    const entry = db.get(parseInt(args));
    await ctx.sendUserMessage(
      `Expand this thought into structured output.\n\n"""\n${entry.raw_text}\n"""`,
      { deliverAs: "steer" }
    );
  }
});
```

Pi handles:
- Iterative reasoning
- Tool use (if tools are registered)
- Streaming response accumulation
- Context window management and compaction
- Token cost tracking

**Alternative:** You can hand-roll the loop inside the extension using direct API calls if you want full control. Pi doesn't force its loop — it offers it.

### 8. Review (Pattern Detection)

`/review` loads entries from SQLite into pi context, triggers reasoning pass. Pi's loop + tool calls detect themes, suggest connections. Too many entries for context? Query summaries or subsets from SQLite first.

### 9. Commit to Apple Reminders

`/commit <id>` calls `osascript`. **Requires Mac.** When running headlessly on Railway, this command returns `"commit: requires local Mac"`. The user runs `commit` when using pi locally. A future Mac-side companion (polling Turso for `pending_commits`) solves this at V2 — out of scope for V0.

---

## Why This Wins Over Standalone Python

| Concern | Standalone (Python) | Pi Extension (TypeScript) |
|---|---|---|
| **Process count** | Bot + classifier process + pi for expand = 3+ | 1 |
| **Language** | Python + TS (when expand needs a loop) | TypeScript only |
| **LLM management** | Custom `LLMClient` wrapper (~30 lines) | Pi handles auth, models, switching via env vars |
| **Agent loop for expand** | Build from scratch (~100 lines) or import framework | Pi's loop available; or hand-roll inside extension |
| **Context management** | Manual prompt construction, no compaction | Automatic compaction, branching, tree — battle-tested |
| **Trace table** | Build yourself | Same — you build it either way |
| **Prompts as files / evals** | Build yourself | Same — you build it either way |
| **CLI capture** | Separate script | Pi itself (already open, extension intercepts input) |
| **Local TUI for deep thinking** | None — just text back and forth | Full pi TUI when you `cd ~/solo && pi` |
| **Hosting** | Railway, $5/mo | Railway, $5/mo — same |
| **Offline capture** | PI_CLI script | Pi terminal — same |

The irreducible advantage is **context management at scale**. When `expand` reasoning sessions grow long, pi's compaction, tree navigation (`/tree`), and branching keep them productive. Standalone Python would need to rebuild all of this — or accept that long reasoning sessions degrade quietly.

---

## V0 Scope

1. **`solo.ts` extension** in `.pi/extensions/solo/`
2. **SQLite schema** — entries table + llm_calls trace table (`db.ts`)
3. **Telegram bot** — starts in extension's async factory, polls for messages
4. **`input` capture interceptor** — stores raw, returns `handled`
5. **`/top3` command** — lazy classify (OpenRouter API call) + query + render
6. **`/log` command** — query grouped by type
7. **Prompts as files** — `prompts/classify.md`, loaded at runtime
8. **Eval harness** — `evals/classify.jsonl` + `scripts/eval.ts`
9. **Entry point** — `index.ts` using `createAgentSessionFromServices`

Nothing else. No `expand`, no `review`, no `commit`. If `/top3` isn't trustworthy after a week, nothing else matters.

---

## Running Modes

### Railway (Headless, Primary)

```typescript
// index.ts
import {
  createAgentSessionRuntime,
  createAgentSessionServices,
  createAgentSessionFromServices,
  SessionManager,
} from "@mariozechner/pi-coding-agent";

const cwd = process.cwd();
const services = await createAgentSessionServices({ cwd });
const { session } = await createAgentSessionFromServices({
  services,
  sessionManager: SessionManager.create(cwd),
});
await session.bindExtensions({}); // loads solo.ts
setInterval(() => {}, 1 << 30);   // keep alive
```

Push to GitHub → Railway auto-deploys. Two env vars: `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`.

### Local Mac (TUI Available)

```bash
cd ~/solo && pi
```

Extension loads from `.pi/extensions/`. Full TUI. `commit` to Reminders works. Type thoughts directly — the `input` handler intercepts. Best of both worlds.

---

## Risks

| Risk | Assessment |
|---|---|
| Pi session JSONL grows | Compaction handles this automatically. SQLite is the durable store. |
| Extension crashes | Railway auto-restarts. Same as any daemon. |
| `ctx.ui` methods in headless | `notify` is no-op; `confirm` returns default. Don't rely on them for headless. |
| Telegram polling conflicts | `node-telegram-bot-api` uses its own event loop; non-blocking. |
| Pi version updates | Lock `@mariozechner/pi-coding-agent` in package.json. |
| Offline Telegram | Same as standalone. Use pi locally when offline. |
| `commit` needs Mac | Acceptable for V0. Runs locally when at laptop. |

---

## Honest Assessment

The standalone Python approach is not wrong. It will work. It is simpler in some dimensions (Python ecosystem familiarity, less runtime surface to understand). But it pays a hidden cost: building infrastructure that pi already provides (auth, models, compaction, context window management), and accepting a ceiling on reasoning session quality when `expand`/`review` arrive.

The question is not "which is simpler?" — it's **"which teaches more about AI engineering?"**

- **Standalone Python** teaches: Telegram bots, SQLite, LLM API calls, Python web services.
- **Pi-based** teaches: All of the above, plus how production agent runtimes handle auth, model switching, context management, compaction, and event-driven extension architecture.

The stated goal is to become effective at **AI engineering and agentic systems**. Using pi — a production agent runtime you can inspect and extend at every layer — is aligned with that goal.
