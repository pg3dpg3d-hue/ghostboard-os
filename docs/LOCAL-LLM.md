# Local LLM — LM Studio · Dolphin

The deck's reasoning now runs **on the machine**. LM Studio serves a model
(Dolphin) behind an OpenAI-compatible API on `http://127.0.0.1:1234/v1`, and
`ghost-llm` is GHOSTBOARD's client for it: streaming, brand-coloured, **zero
dependencies** (Python stdlib only), instant to start, works over SSH.

This is an architecture change from the original brief (which put reasoning in
the cloud). Both now coexist: **local by default, cloud when you want it.**

| Path | When | Tool |
| --- | --- | --- |
| **Local** — LM Studio · Dolphin, on-device | always, incl. offline | `ghost-llm` |
| **Cloud** — Claude Code, agentic + tools | online, heavier work | `ghost-claude` |

## Setup

LM Studio is a downloaded app (not apt) — install it once from lmstudio.ai
(x86_64 AppImage), then:

1. Load a **Dolphin** model (Discover / My Models).
2. Start the server — Developer tab → Start Server, or `lms server start --port 1234`.
3. `ghost-llm --check` — confirms the endpoint and shows the active model.

`install/steps/65-local-llm.sh` writes the config and, if the `lms` CLI is
present, offers to start the server automatically at session login (a
`--user` systemd service, no system daemon).

## Using it

```bash
ghost-llm                         # streaming chat (REPL)
ghost-llm "explain nmap -sn"      # one question, one answer, exit
echo "summarise" | ghost-llm -    # read the prompt from a pipe
ghost-llm --check                 # endpoint reachable? model loaded?
ghost-llm --models                # what LM Studio is serving
```

Menu: **AI · Local LLM**. Palette (`Super+Space`): type `llm`.

REPL commands: `/reset`, `/system <text>`, `/model [name]`, `/models`,
`/stats` (last exchange's tok/s), `/save <file>`, `/help`, `Ctrl+D` to quit.
Colours follow the OS convention — **accent violet** is the model, **pink** is
what you type.

Because it's a plain streaming CLI, it composes: pipe a file in, pipe the
answer to another tool, or call `ghost-llm -q` from a script.

## Configuration

Resolution order (first wins):

1. env `GHOSTBOARD_LLM_BASE` / `GHOSTBOARD_LLM_MODEL` / `GHOSTBOARD_LLM_KEY`
2. `~/.config/ghostboard/llm.json`
3. `/usr/share/ghostboard/llm.json` (written by the installer)
4. defaults — base `http://127.0.0.1:1234/v1`, `model: "auto"`, key `lm-studio`

`model: "auto"` makes `ghost-llm` pick the served model whose id contains
`dolphin` (case-insensitive), else the first one — so loading a different
Dolphin build needs no config change. LM Studio ignores the API key, but the
OpenAI protocol requires one, hence the placeholder.

## Will the model fit? — the RAM guard

An 18 GB model on a 16 GB (max, soldered) deck cannot fit in RAM; forcing it
makes LM Studio page weights from the SSD on every token — **unusable** (well
under 1 tok/s) and hard on the SSD. So `ghost-llm` checks at startup and warns
(never blocks). The warning goes to **stderr**, so `ghost-llm - > out.txt` is
never polluted.

| Deck RAM | Model that fits (q4) | Notes |
| --- | ---: | --- |
| **8 GB** | **≤ ~5 GB** — 7–8B q4, or a 3B | an 8 GB model does **not** fit here |
| **16 GB** | **≤ ~12 GB** — 14B q4, tight 20–22B q4 | an 8 GB model fits comfortably |

The guard reads `MemAvailable` and, when it can, the loaded model's on-disk size
(via `lms ps --json`, LM Studio's native `/api/v0/models`, then a scan of the
models directory — the OpenAI API doesn't expose size). It also flags live
memory pressure (swap in use → already paging). Tune it in `llm.json`:
`ram_check` (default true) and `ram_reserve_gb` (headroom kept for OS + desktop
+ KV cache, default 2.0), or disable per-call with `--no-ram-check`.
`ghost-llm --check` prints the verdict: **fits in RAM**, or the exact shortfall.

## The N100 reality

Inference is on the **CPU** — the N100 has no usable GPU for this. Expect a few
tokens per second, not cloud speed. Guidance:

- **8 GB RAM** → a **Dolphin 3B** (q4) is the sweet spot; a 7B will load but
  crawl and pressure the 900 MB idle target.
- **16 GB RAM** → a **7B** (q4) is usable; a 3B stays snappier on the panel.

`ghost-status` shows a **Local LLM** line: `up` with the model name, or the
exact reason it isn't (server down / no model). When the network is gone,
`ghost-claude` now points you here — the deck still reasons, locally.

## How ghost-llm talks to LM Studio

Standard OpenAI wire protocol, so it works against anything that speaks it
(LM Studio, llama.cpp server, Ollama's `/v1`, …) if you ever switch:

- `GET  {base}/models` → pick the model
- `POST {base}/chat/completions` with `"stream": true` → parse the
  `text/event-stream` (`data: {json}` lines, `delta.content`, `[DONE]`)

Verified against a mock OpenAI server in `tests/test-llm.sh` (7 checks:
model listing, Dolphin auto-detect, streaming, pipe input, model override,
and a clear error + non-zero exit when the endpoint is down).
