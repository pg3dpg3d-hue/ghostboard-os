# Routing Claude Code to the local model

## What this actually means

Claude Code is Anthropic's CLI. By default it talks to the **Anthropic API** in
the cloud, using Claude models. "Routing it to the local model" means pointing
it at the **on-device model** (LM Studio serving Dolphin) instead — so the
agent runs with no network and nothing leaves the deck.

The catch: **the two APIs are not compatible.**

- Claude Code speaks the **Anthropic Messages API** — `POST /v1/messages`, its
  own JSON shape, its own streaming events (`message_start`,
  `content_block_delta`, `tool_use` blocks…).
- LM Studio speaks the **OpenAI API** — `POST /v1/chat/completions`, a different
  JSON shape, different streaming, different tool-call format.

You cannot just set `ANTHROPIC_BASE_URL=http://localhost:1234/v1` — Claude Code
would POST an Anthropic request and LM Studio would reject it. So GHOSTBOARD
ships a small **translation proxy** that sits between them:

```
  Claude Code ──Anthropic /v1/messages──▶ ghost-llm-proxy ──OpenAI /v1/chat──▶ LM Studio · Dolphin
              ◀──Anthropic SSE events──── (translates both ways) ◀──OpenAI SSE──
```

`ghost-llm-proxy` accepts the Anthropic Messages API, translates each request to
the OpenAI format, calls LM Studio, and translates the answer back into
Anthropic events — text streaming and tool calls included. `ghost-claude --local`
starts it, points Claude Code at it, and cleans it up on exit.

## Using it

```bash
ghost-claude --local        # start proxy, run Claude Code against Dolphin
```

It checks LM Studio is up, launches `ghost-llm-proxy`, sets `ANTHROPIC_BASE_URL`
(+ a dummy `ANTHROPIC_API_KEY`, LM Studio ignores it) and `ANTHROPIC_MODEL` to
the local model, then runs `claude`. The proxy is killed when you exit.

## Honest limitations — read this

This is a **best-effort, unofficial** bridge. Claude Code was built for Claude.

- **A small local model is weak at the agentic loop.** Claude Code's power is
  multi-step tool use — reading files, editing, planning, running commands.
  Dolphin 7–8B does this poorly and unreliably. Expect it to lose the thread,
  misuse tools, or stall on anything beyond simple edits.
- **Speed.** CPU inference on the N100 is a few tokens/second (see
  [LOCAL-LLM.md](LOCAL-LLM.md)). An agent that makes many turns feels very slow.
- **Feature gaps.** Anthropic-specific features Claude Code may use (prompt
  caching headers, certain tool schemas, thinking blocks) have no equivalent on
  a local OpenAI model; the proxy maps what it can and ignores the rest.
- **Tool translation is approximate.** The proxy converts Anthropic tools ↔
  OpenAI function-calling, but a small model's function-calling is shaky, so
  agentic tool use will often be wrong.

**What it's genuinely good for:** quick questions, explaining code, simple
single-file edits, working fully offline — without sending anything to the
cloud. For heavy agentic work, use `ghost-claude` (the real Anthropic API, when
you have a network). Two brains, and you pick per task.

## The translation, precisely

| Anthropic (in) | OpenAI (out to LM Studio) |
| --- | --- |
| `system` (string or blocks) | leading `system` message |
| `messages[].content` text blocks | `content` string |
| assistant `tool_use` block | `assistant.tool_calls[]` (function) |
| user `tool_result` block | `role: "tool"` message with `tool_call_id` |
| `tools[]` (`input_schema`) | `tools[]` (`function.parameters`) |
| `tool_choice` auto/any/tool/none | `auto`/`required`/`{function}`/`none` |
| `image` block | dropped (local model has no vision), noted inline |

Response back: OpenAI `finish_reason` → Anthropic `stop_reason`
(`stop`→`end_turn`, `length`→`max_tokens`, `tool_calls`→`tool_use`); `tool_calls`
→ `tool_use` blocks; streaming deltas → `content_block_delta` (`text_delta` /
`input_json_delta`).

Verified in `tests/test-proxy.sh` (7 checks) against a mock LM Studio: Anthropic
in, OpenAI out, Anthropic back — non-streaming, streaming (the text reconstitutes
exactly), and a tool call round-trip. No Claude Code or LM Studio needed to run
the test.
