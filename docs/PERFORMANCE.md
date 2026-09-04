# Performance

Every knob GHOSTBOARD OS turns, what it buys, and how to undo it.

Nothing here is a copied checklist. Each item was chosen for *this* machine — an
Intel N100 with 16 GB of RAM, an NVMe root, a 4-inch panel and a power bank — and
several plausible-looking optimisations were deliberately **rejected**; those are
listed at the end, with the reason.

Verify the lot on the deck with one command:

```bash
ghost-perf          # audits the live system, names the fix for every gap
ghost-perf --fails  # only what's wrong
ghost-perf --json   # machine-readable, exit 1 if anything fails
```

`ghost-perf` reads no install stamps. A step that ran proves nothing: a package
can re-enable a service, an upgrade can overwrite a config, a setting can be
written and never take effect. It inspects the running system.

---

## Boot chain — where the seconds are

Ordered by size of win.

| Knob | Win | What it does | Undo |
| --- | ---: | --- | --- |
| **GRUB timeout → 0** | **~5 s** | GRUB waits 5 s by default. On a 20 s budget that is a quarter of it, spent on a menu nobody opens. `GRUB_RECORDFAIL_TIMEOUT=0` also removes the 30 s penalty menu after an unclean shutdown — routine on a device powered by a power bank. | `rm /etc/default/grub.d/60-ghostboard.cfg && update-grub` |
| **No display manager** | **~1–2 s, ~40 MB** | `ghost-session-mode direct` drops LightDM entirely: tty1 logs in automatically and starts X from the login profile. The win is removing the greeter's own X session and GTK process, not just skipping a password. | `sudo ghost-session-mode dm` (auto-login) or `login` (password) |
| **initramfs `MODULES=dep`** | ~0.3 s | Debian ships a `most` initramfs — every storage driver in existence, ~90 MB to decompress. `dep` keeps only what this machine loads. `zstd -1` decompresses faster than the default at a few MB more on disk. | Boot a live USB, chroot, `rm /etc/initramfs-tools/conf.d/ghostboard.conf`, `update-initramfs -u` |
| **os-prober off** | — | Scans every disk on every kernel update. No second OS here. | Same file as GRUB |
| **`quiet loglevel=3`** | ~0.2 s | Console rendering before X starts is not free. Errors still print. | Same file as GRUB |
| **`DefaultTimeoutStartSec=15s`** | up to 75 s in the bad case | systemd waits 90 s for a stuck unit. On a 20 s target that is absurd. | `rm /etc/systemd/system.conf.d/60-ghostboard.conf` |

**`MODULES=dep` is the one that can stop the machine booting** if the hardware
changes. It is confirm-gated, and the step refuses to run without `00-preflight`
having confirmed an SSH rescue path.

---

## RAM at rest — where the megabytes are

This is where the 900 MB target is won or lost, not in the kernel. A stock XFCE
session carries half a dozen services nobody asked for.

| Service | Cost | Why it goes | Undo |
| --- | ---: | --- | --- |
| **at-spi2** (accessibility bridge) | ~20 MB, 2 processes | Every GTK app starts it, for a screen reader this deck does not have. `NO_AT_BRIDGE=1` means GTK never loads the module at all. | `rm /etc/X11/Xsession.d/90ghostboard-lean` |
| **Thunar daemon** | ~35 MB | XFCE keeps a resident Thunar so the *first* file-manager launch is 300 ms faster. On a deck whose main app is a terminal, that is a permanent cost for a one-time gain. | Delete `~/.config/autostart/thunar.desktop` |
| **tumblerd** (thumbnails) | ~30 MB + CPU | D-Bus-activated the moment Thunar shows a folder, then grinds through images nobody looks at on a 4-inch panel. | Thunar → Preferences → Show thumbnails |
| **gvfs volume monitors** | ~30 MB | One monitor per device family. Cameras (gphoto2, MTP), Apple devices (afc) and online accounts (goa) are all irrelevant here. **udisks2 is kept** — that is what mounts USB sticks. | `systemctl --global unmask gvfs-*-volume-monitor.service` |
| **UPower** | ~10 MB | Polls batteries. A USB-C PD power bank exposes no battery sensor, so it watches nothing. Skipped automatically if the kernel *does* expose a battery. | `systemctl enable --now upower` |
| **xdg-desktop-portal** | ~15 MB, 2 processes | Sandbox plumbing for Flatpak/Snap. No containers here. Opt-in, because a file chooser could care. | `systemctl --global unmask xdg-desktop-portal.service` |

**Deliberately kept:** dbus, polkit, xfconfd, xfsettingsd (the session does not
start without them), udisks2 (USB sticks), NetworkManager (a portable device
needs Wi-Fi), and the xfwm4 compositor — without it there is no taskbar
translucency, and it costs nothing while idle, unlike an animation.

**Never installed:** any audio stack. That is ~40 MB never spent. Add
`pipewire pipewire-pulse` if you want sound.

Where the megabytes actually are, on the deck:

```bash
ghost-bench          # includes a per-process breakdown, PSS where available
```

---

## Storage

| Knob | What it does |
| --- | --- |
| **`noatime` on /** | Removes a write on every file *read*. Pure win on flash, and less wear. |
| **`/tmp` on tmpfs** | Temporary files stay in RAM. Faster, no NVMe writes, and they do not outlive a reboot. tmpfs caps itself at half of RAM. |
| **NVMe scheduler `none`** | An NVMe has dozens of hardware queues; a software scheduler adds latency without usefully reordering anything. Already the kernel default — the udev rule guarantees no package changes it. A SATA/USB SSD still gets `mq-deadline`, where a scheduler does earn its place. |
| **`rq_affinity=2`** | I/O completion is handled on the core that issued the request, avoiding a cross-core wake-up per I/O. |
| **Weekly TRIM, not `discard`** | Continuous discard adds latency to every delete. `fstrim.timer` batches it. |
| **No swap at 16 GB** | Nothing worth paging to an NVMe. `vm.swappiness=10` for the edge cases. Below 12 GB the installer offers zram instead — compressed RAM, never the flash. |

## Power

The deck runs on a power bank, so watts matter — but not at the cost of a
resident daemon.

**No `power-profiles-daemon`, no TLP.** Both are daemons for a setting that never
changes on a single-supply device, and the OS exposes no UI to drive them.
`ghostboard-power.service` is a **oneshot**: it runs at boot, writes, exits.
Zero resident processes.

- **Governor `powersave`** — on `intel_pstate` this is *not* throttling; it is the
  driver's adaptive algorithm, which ramps on demand. `performance` pins the
  frequency high and buys no perceptible responsiveness.
- **EPP `balance_power`** — keeps burst responsiveness (race-to-idle) while
  dropping idle draw.
- **PCIe ASPM `powersupersave`** — lets the NVMe and its controller drop into low
  power states.
- **USB autosuspend — with HID and CDC excluded.** Putting the BB Q20 keyboard or
  an ESP32 serial bridge to sleep mid-session is exactly the kind of
  "optimisation" that breaks the device. `ghost-perf` has a dedicated check for
  this, because a silent regression here is a dead keyboard.

---

## Rejected, and why

Optimisations that look right for this hardware and are **not** applied:

- **`mitigations=off`.** Would measurably help an N100. Not done: the deck holds
  API credentials and browses the web. Speed is not worth turning off Spectre
  mitigations on a machine that runs untrusted code.
- **`i915.enable_psr` / `enable_fbc`.** Panel Self Refresh and framebuffer
  compression are eDP features. This panel is **HDMI**, so both would be flags
  that do nothing. Not added — a knob that cannot apply is noise in the config.
- **`performance` governor.** Pins frequency high, drains the power bank, and on
  an adaptive `intel_pstate` gains nothing you can feel.
- **Masking tumblerd / at-spi units.** Configuration beats masking: turning
  thumbnails off in Thunar is reversible from a checkbox, whereas a masked unit
  breaks silently the day you want it. Masking is used only where no setting
  exists.
- **Preload / readahead daemons.** A resident process guessing what you will open
  next, on hardware that opens it in milliseconds anyway.
- **Removing NetworkManager for systemd-networkd.** Lighter, yes — and painful
  the first time you need to join a Wi-Fi network from a 4-inch screen.
- **`vm.overcommit` / THP tuning.** No workload here justifies it, and it is the
  kind of change whose effects only show up as a rare crash.

---

## Regression discipline

Two things quietly undo this work: a package upgrade re-enabling a service, and a
new dependency dragging in a daemon. Both are caught the same way:

```bash
ghost-perf --fails     # after every apt upgrade
systemd-analyze blame  # after every package install
```

`ghost-perf` exits `1` when anything is off target, so it can gate a script.
