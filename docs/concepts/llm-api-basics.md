# LLM API basics

## What problem this solves

You want a piece of software to ask a language model a question and use the answer. The LLM lives on someone else's servers (OpenAI, Anthropic, Google, OpenRouter). You need a way to send a structured request and get back a structured response — reliably, observably, and without hand-rolling HTTP for every call.

## The core idea

An LLM API call is a **stateless HTTP POST** with three things in the body:

1. **A model identifier** — e.g. `minimax/minimax-m2.7`. The provider routes your request to the right weights.
2. **A list of messages** — each tagged with a `role` (`system`, `user`, or `assistant`). The model reads the list top-to-bottom and predicts the next assistant message.
3. **Knobs** — temperature (randomness), max tokens (cap on output length), `response_format` (force JSON shape), tools (functions the model can call).

You get back: the assistant's reply, plus accounting metadata (`prompt_tokens`, `completion_tokens`, model used). You pay per token in and per token out, at different rates.

**Stateless** is the key word. The model does not remember previous calls. If you want a multi-turn conversation, you send the entire history every time. This is why prompts and conversations grow expensive — you re-pay for the same context on every turn.

## How solo uses it

- `solo.llm.LLMClient` (`src/solo/llm.py`) wraps `openai.AsyncOpenAI` pointed at OpenRouter's base URL. Every call routes through this one class.
- `LLMClient.chat(messages, model=...)` — raw multi-message call.
- `LLMClient.structured(prompt_name, schema, model=...)` — loads a `.md` prompt, sends it, parses the response into a pydantic class. This is what the classifier uses.
- We use **OpenRouter** as a single endpoint that proxies to many providers — one API key, many models. Lets us swap `minimax/minimax-m2.7` → `moonshotai/kimi-k2.6` by changing one env var.

## Common gotchas

- **Stateless means you re-pay for context.** A 10-turn chat with a 5KB system prompt sends that prompt 10 times. Prompt caching (a separate concept) is how you avoid this on long histories.
- **Model IDs change.** `gpt-5-mini` today might be deprecated next quarter. Pin in env vars, not in code.
- **Token counts are not character counts.** Roughly 4 characters per token in English; varies by tokenizer. Always read the actual `usage` field, never estimate.
- **Errors are silent in shape but loud in body.** A 200 response can still contain `{"error": ...}` in the body for some providers. The OpenAI SDK normalizes most of this, but inspect `response.choices[0].message.content` defensively when wiring a new provider.

## Further reading

- OpenAI's chat completions reference: https://platform.openai.com/docs/api-reference/chat
- OpenRouter model catalogue: https://openrouter.ai/models
