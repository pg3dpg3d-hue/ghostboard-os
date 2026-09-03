# GHOSTBOARD OS

**CUSTOM HARDWARE. READY TO EXPLORE.**

A lightweight, instant desktop for the GHOSTBOARD cyberdeck: Debian 13 + XFCE,
themed from a single palette file, with Claude Code at the centre and on-device
computer use exposed to it over MCP.

Windows 11 in structure — floating centred taskbar, rounded corners, mica
translucency, a floating start menu with search on top. GHOSTBOARD in skin —
near-black ground, one spectral violet accent, monospace only where there is
terminal or data.

![Boot animation](docs/boot-animation.png)

---

## Target hardware

| Part | Spec |
| --- | --- |
| Board | Radxa X4 — Intel N100, **16 GB RAM** |
| Storage | M.2 2230 NVMe, **512 GB**, OS boots from it |
| Display | 4-inch HDMI panel, **800 × 480** — constraint #1 |
| Keyboard | BlackBerry Q20 (BB Q20 PMOD) over USB HID |
| Power | USB-C PD power bank — every watt counts |
| Companion | ESP32 boards running **Bruce** (M5Stick, T-Embed, CYD), plugged in over USB |

800 × 480 is the constraint that decides everything else: 15 px font floor,
34 px taskbar, thin scrollbars, no desktop icons, full-screen by default.

## Performance targets

| Target | Value |
| --- | --- |
| Boot to usable desktop | **< 20 s** |
| RAM at rest, desktop loaded | **< 900 MB** |
| GPU loop after boot | **none** — the WebGL context is destroyed |
| App launch | immediate — NVMe is there to be used |

Measured with `ghost-bench`, recorded in [BENCHMARKS.md](BENCHMARKS.md).
Numbers in that file come from the deck itself, never from an estimate.

---

## Install order

Run the steps in order. Each one is idempotent — re-running it fixes only what
is missing. Steps that touch the display, bootloader or session manager ask for
confirmation first.

```bash
git clone <this-repo> /opt/ghostboard-os
cd /opt/ghostboard-os

sudo ./install/ghostboard-install.sh --list        # what will run
sudo ./install/ghostboard-install.sh --dry-run     # writes nothing, shows everything
sudo ./install/ghostboard-install.sh               # the real thing
```

### Before you start — read this

1. **Get SSH working first.** `00-preflight` refuses to let the display step run
   without it. If the panel goes dark, SSH is the only way back in.
   Tailscale is strongly recommended: a LAN-only SSH is useless once the deck
   leaves the house.
   ```bash
   sudo apt install openssh-server && sudo systemctl enable --now ssh
   curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up
   ```
2. **Image the SSD.** From another machine, drive in a USB enclosure:
   ```bash
   sudo dd if=/dev/nvme0n1 bs=64M status=progress | zstd -T0 > ghostboard-base.img.zst
   ```
   This is the only guaranteed way back if the bootloader or the panel breaks.

### The steps

| Step | What it does |
| --- | --- |
| `00-preflight` | Surveys the real hardware, compares it to target, checks the SSH rescue path. **Gate for the risky steps.** |
| `10-base-system` | Base packages, `en_US.UTF-8`, `noatime` on root, weekly TRIM, swappiness, power profile |
| `20-display-800x480` | Forces the 800 × 480 mode in Xorg and the kernel. **Arms a 3-minute auto-revert.** |
| `30-keyboard-bbq20` | Repeat rate for a thumb keyboard, XKB overlay mapping Right Alt → Super |
| `40-xfce-desktop` | XFCE component by component (never the `xfce4` metapackage), LightDM, default config |
| `50-theme` | IBM Plex Mono + Martian Mono, renders the whole theme from the palette, installs the tools |
| `60-nodejs-claude-code` | Node 22 LTS from NodeSource, Claude Code under a user-owned npm prefix |
| `70-mcp-computer-use` | The computer-use MCP server, registered with Claude Code; dedicated agent display installed but off |
| `80-boot-animation` | Chromium, three.js, the WebGL splash, and the `GHOSTBOARD` session entry |
| `90-ghost-bruce` | pyserial, `dialout` membership, udev rules for ESP32 USB bridges |
| `95-perf-tuning` | Disables services that earn nothing on a deck, bounds the journal, then measures |

Then **reboot**, pick the **GHOSTBOARD** session at the login screen, and:

```bash
sudo ghost-display-guard keep    # only if the panel actually works
ghost-bench --markdown /opt/ghostboard-os/BENCHMARKS.md
```

Resume a failed run with `--from <step>`; force a completed one with `--force`.

---

## Re-theming: one file

`brand/palette.toml` is the **only** place a colour, font or interface metric is
written by hand. Everything else is generated from it — GTK 2/3/4, window
decorations, the terminal, the wallpaper, the taskbar, the start button icon,
and the boot animation.

```bash
$EDITOR brand/palette.toml     # change one hex
sudo ghost-theme apply         # regenerates everything
ghost-theme reload             # or log out and back in
```

`ghost-theme apply` refuses to install a palette that fails its own legibility
check — contrast ratios and the 15 px font floor are verified before anything is
written. Run `ghost-theme check` on its own to see the numbers.

| Role | Hex | Meaning |
| --- | --- | --- |
| Background | `#08070C` | Desktop, window bodies |
| Panel | `#14111C` | Taskbar, start menu, raised surfaces |
| Separator | `#251F35` | Borders, rules, field outlines |
| Accent | `#A855F7` | Active state — **what the machine is doing** |
| Input | `#FF4D8D` | **What you type**, and errors |
| Text | `#D6D2E0` | Primary text |
| Text dim | `#6E6880` | Labels, placeholders |

One accent colour. `input` is not a second accent: it is a semantic marker for
your keystrokes and for failure, and it is used for nothing else.

Fonts: **Martian Mono** for the logotype and window titles only, **IBM Plex
Mono** everywhere else, 15 px floor.

---

## Architecture

```
  Cloud                          The deck (Radxa X4, N100)
  ─────                          ─────────────────────────
  Anthropic API  ◄──────────►   Claude Code
   (reasoning)                    │  terminal + files
                                  │
                                  ▼  MCP, stdio
                             ghostboard-computer-use
                                  │  screenshot · click · type · key
                                  ▼
                             X display (:0, or :1 for a dedicated agent screen)
```

No model runs locally. The N100 does not have the power for it and does not need
it: reasoning is remote, **control of the screen is on-device**.

### Computer use over MCP

`mcp-computer-use/server.js` — **zero npm dependencies**, on purpose. It starts
in ~25 ms, there is nothing to update on the deck, and the MCP JSON-RPC handling
is 80 lines. Capture uses `scrot`, input uses `xdotool`; both are invoked on
demand and nothing runs in the background.

| Tool | Purpose |
| --- | --- |
| `screenshot` | PNG of the screen, **native 800 × 480, never rescaled** (~512 image tokens) |
| `click` | Absolute click; off-screen coordinates are rejected with an explicit error |
| `type` | Literal text, per-character |
| `key` | X11 combinations — `Return`, `ctrl+c`, `super` |
| `scroll` | Needed: 480 px of height, most lists overflow |
| `screen_info` | Geometry and pointer without paying for an image |

```bash
node tests/test-mcp.js       # 22 checks against a live X server
```

### Dedicated agent session (installed, off by default)

By default the agent sees your desktop. To give it a screen of its own:

```bash
ghost-agent-session on       # Xvfb :1 at 800 × 480, MCP switched to it
ghost-agent-session status
ghost-agent-session off
```

Costs nothing while off. The virtual screen is exactly 800 × 480, so click
coordinates stay valid whichever mode you use. See
[docs/agent-session.md](docs/agent-session.md).

---

## Boot animation

The GHOSTBOARD logotype condenses out of a particle cloud — WebGL, three.js,
~1.4 s — and then **the GL context is explicitly destroyed**
(`WEBGL_lose_context`, all buffers disposed). Nothing keeps rendering afterwards.
This is the only animation in the OS.

It runs from a session wrapper (`/usr/local/bin/ghostboard-session`), not from
autostart, so it is the first thing drawn — no desktop flash underneath. Fallback
order: `prefers-reduced-motion` → static logotype; WebGL failure → static
logotype; hung frame loop → the launcher kills the window at the palette's
`timeout_ms`. In all three cases the session opens normally.

```bash
ghost-boot-splash                          # play it without rebooting
GHOSTBOARD_BOOT=0 ghostboard-session       # skip it once
```

To turn it off for good: `boot.enabled = false` in `brand/palette.toml`, then
`sudo ghost-theme apply`.

Particle count, phase durations and the timeout all live in the palette's
`[boot]` section. Particles are sampled from the rasterised logotype at runtime,
so changing the font or the wordmark needs no mesh regeneration.

---

## Offline (degraded) mode

Reasoning is in the cloud, so **without a network Claude Code cannot answer**.
The deck says so plainly instead of failing obscurely, and stays useful:

- `ghost-claude` probes the Anthropic API before launching. If it is unreachable
  it tells you, lists what still works, and asks before continuing anyway.
- `ghost-status` shows network, API reachability, memory, boot time, attached
  Bruce boards.

There is **no background network poller and no tray indicator**. That is
deliberate: a daemon polling for connectivity is exactly the kind of thing that
"runs in the background for nothing". State is computed when you ask for it.

Fully usable offline: terminal, editor, file manager, `ghost-bruce` (serial
console, board WebUI), `ghost-bench`, `ghost-status`.

---

## ghost-bruce

```bash
ghost-bruce list                 # detected boards, USB bridge, model, serial
ghost-bruce console              # colour-coded serial console — Ctrl+] to quit
ghost-bruce send "help"          # one command, print the reply
ghost-bruce webui                # start the board's WebUI and open it
ghost-bruce -d /dev/ttyUSB0 info
```

Detection walks `/sys/class/tty` up to the parent USB device and reads
`idVendor`/`idProduct` — CP210x, CH340/CH9102, FTDI and native ESP32-S2/S3 USB
are recognised by ID; anything else is still listed, just unnamed.

In the console, the board speaks in **accent violet** and you type in **input
pink** — the same convention as everywhere else in the OS.

> The exact serial command that starts the WebUI, and its address, depend on
> your Bruce firmware version and whether the board is in AP or client mode.
> Both are overridable: `--command` and `--url`. The default assumes AP mode at
> `192.168.4.1`.

```bash
bash tests/test-bruce.sh         # 12 detection checks against a fake sysfs tree
```

---

## Layout

```
brand/palette.toml          SOURCE OF TRUTH — the only hand-written colours
theme/
  ghostpalette.py           palette loading, colour maths, pure-Python PNG writer
  render-theme.py           palette -> the entire system theme
  templates/                structure, with {{keys}} where colour goes
desktop/
  config/                   XFCE panel, wm, xsettings, shortcuts, whisker menu
  launchers/                the pinned apps
boot-animation/             index.html, boot.js, vendor + font fetchers
mcp-computer-use/server.js  the MCP server (no dependencies)
tools/                      ghost-bruce, ghost-bench, ghost-theme, ghost-status,
                            ghost-claude, ghost-browser, ghost-boot-splash,
                            ghostboard-session
install/                    orchestrator, lib/common.sh, steps/
tests/                      test-mcp.js, test-bruce.sh
```

## Tests

```bash
bash tests/run-all.sh
```

| Suite | Covers |
| --- | --- |
| `tests/test-config.sh` | XFCE XML, `.desktop` entries, JSON, full theme generation, every SVG/PNG artefact, shell/Python/Node syntax |
| `tests/test-bruce.sh` | Board detection against a synthetic sysfs tree — CP210x, CH340, native ESP32 USB, access errors |
| `tests/test-mcp.js` | MCP handshake, tool catalogue, and `screenshot`/`click`/`type`/`key` executing against a real X server |

`run-all.sh` also asserts that `--dry-run` leaves `/etc/fstab` untouched.

## Recovery

| Symptom | Way out |
| --- | --- |
| Black screen after the display step | Do nothing. The guard restores the previous config after 3 minutes. |
| Panel works, want to keep it | `sudo ghost-display-guard keep` |
| Session will not start | Pick **Xfce Session** at the login screen — it is left installed on purpose |
| No graphical session at all | `Ctrl+Alt+F2` for a text console, or SSH |
| Theme looks wrong | `ghost-theme check`, then `sudo ghost-theme apply` |
| A step broke | `sudo ./install/ghostboard-install.sh --from <step>`; log in `/var/log/ghostboard-install.log` |
| Config file overwritten | Timestamped copies in `/var/lib/ghostboard/backups/` |

---

## Language

The OS interface is **English** — launchers, menus, system messages, and these
docs. Source comments are in **French**, matching how the project is maintained.

## Licence and third parties

- **three.js** — MIT, fetched at install time, pinned version, checksummed
- **Martian Mono** (Evil Martians) and **IBM Plex Mono** (IBM) — SIL Open Font Licence
- Neither is vendored in this repository; both are fetched by the install scripts
