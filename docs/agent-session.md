# Dedicated agent session

By default, the computer-use MCP server drives `:0` — your desktop. The agent
sees what you see, and clicks where you would click.

That is the simplest setup and the right default. But it means the agent sees
everything on your screen, and that you and it fight over the same pointer.

## Turning it on

```bash
ghost-agent-session on       # starts Xvfb :1, points the MCP server at it
ghost-agent-session status
ghost-agent-session off      # back to :0
```

Restart Claude Code after switching — the display is read from the MCP server's
environment at startup.

## What it actually does

`ghostboard-agent-display.service` starts `Xvfb :1 -screen 0 800x480x24` and an
`xfwm4` on it, then `GHOSTBOARD_MCP_DISPLAY=:1` is written into the MCP server's
entry in `~/.claude.json`.

The virtual screen is **exactly 800 × 480**, the same as the panel. This is not
cosmetic: click coordinates the agent learned on one display stay valid on the
other, so you can switch modes without the agent's spatial reasoning going
stale.

## Why it ships off

- Two X servers is more RAM than one, on a deck with a 900 MB resting budget.
- An empty `:1` has no panel, no launchers and no session bus, so anything the
  agent is supposed to drive has to be started on it explicitly.
- The first boot should be debugged with one screen, not two.

The whole mechanism is installed either way, so switching is a command, not a
reinstall.

## Running something on the agent's screen

```bash
DISPLAY=:1 xfce4-terminal &
DISPLAY=:1 ghost-browser https://example.org &
```

To watch what the agent is doing, from another machine or a second TTY:

```bash
sudo apt install x11vnc
x11vnc -display :1 -localhost -nopw &
```

## Security note

The MCP server has no notion of a "safe" region: whatever is on the display it
is pointed at, it can read and click. On `:0` that includes any window you have
open — password managers, mail, keys in a terminal. That is the honest reason to
consider `:1` once the deck is past its first boot.
