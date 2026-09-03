# Hardware survey

`00-preflight` writes the real survey to
`/var/lib/ghostboard/hardware-survey.txt` at install time and compares it to the
target below. It does not stop on a mismatch — it names it and asks.

## Declared target

| Part | Spec |
| --- | --- |
| SoC | Intel N100 (Alder Lake-N, 4 cores) |
| RAM | 16 GB |
| Storage | M.2 2230 NVMe, 512 GB |
| Display | HDMI, 800 × 480, ~4 inch |
| Keyboard | BlackBerry Q20 (BB Q20 PMOD), USB HID |
| Power | USB-C PD power bank |
| Companion | ESP32 under Bruce, USB serial |

## Where the build happened

GHOSTBOARD OS was **written and tested in a headless cloud container**, not on
the deck. The gap, recorded honestly:

| Expected | Present in the build container |
| --- | --- |
| Intel N100 | Xeon vCPU, KVM guest |
| Debian 13 | Ubuntu 24.04 |
| NVMe | virtio block device |
| 800 × 480 HDMI panel | none — `/sys/class/drm` absent; `Xvfb` at 800 × 480 used for tests |
| BB Q20 over USB HID | none |
| ESP32 boards | none — detection tested against a synthetic sysfs tree |

Everything that could be executed was executed (see BENCHMARKS.md). Everything
that needs the real board is marked as such and left for the deck.

## What to check on first boot

```bash
lscpu | grep -E 'Model name|CPU\(s\)'
free -h
lsblk -o NAME,SIZE,ROTA,MODEL
for c in /sys/class/drm/card*-*; do
  [ -f "$c/status" ] && echo "$(basename "$c") $(cat "$c/status") $(head -1 "$c/modes" 2>/dev/null)"
done
lsusb
ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null
```

## Panel notes

Small HDMI panels frequently ship a wrong or absent EDID, and X then picks a
mode the panel cannot show. `20-display-800x480` forces the mode in two places —
`video=<output>:800x480@60` on the kernel command line, and an explicit Modeline
in `xorg.conf.d`. The Modeline is `cvt 800 480 60` output, not a guess.

`DisplaySize 102 61` pins the DPI to something appropriate for a 4-inch panel.
Without it, X computes DPI from a bogus EDID and font sizes go wrong.

## Keyboard notes

The BB Q20 enumerates as a plain USB HID keyboard — no driver needed. What it
lacks is keys: no Super, no arrow cluster, no number row.

`30-keyboard-bbq20` maps **Right Alt → Super** so the start menu is one press,
and leaves `Ctrl+Space` bound to the same action so you are never dependent on a
single remap. Repeat delay is raised to 500 ms: on a thumb keyboard the default
660 ms / 25 Hz makes every correction overshoot.

Keycodes vary by PMOD firmware. To adapt:

```bash
xev -event keyboard          # press the key, read the keycode
sudo $EDITOR /usr/share/X11/xkb/symbols/ghostboard
setxkbmap -option ghostboard:bbq20
```
