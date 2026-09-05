# Encryption on the deck

The GHOSTBOARD session opens **without a password** (direct session, for speed).
So anyone holding the deck has a shell — and it carries secrets: the Claude API
key, the local-LLM config, SSH keys, RECON reports. Two layers protect them,
and they are not the same thing.

| | Full-disk encryption (FDE) | The vault (`ghost-vault`) |
| --- | --- | --- |
| Protects | **everything** — the whole OS, root included | just the secrets you put in it |
| When set up | **at Debian install time** (encrypted LVM) | any time, non-destructive |
| Unlock | passphrase at boot, before the OS starts | passphrase at login (or on demand) |
| Retrofit on a running system | **no** (needs reinstall) | **yes** |

**Use both if you can:** FDE for the disk, the vault to keep secrets isolated
even from a logged-in session. If you can't reinstall, the vault alone still
keeps your API keys off a cleartext disk.

## Full-disk encryption — the proper way (install time)

FDE cannot be added safely to a running root by a script — it's a
partitioning/bootloader decision. Do it when you install Debian on the NVMe:

1. Debian installer → **Guided – use entire disk and set up encrypted LVM**.
2. Choose a strong passphrase (this is what you type at every boot).
3. Finish the install, then run GHOSTBOARD's `install/ghostboard-install.sh`
   on top as usual.

At boot, the initramfs prompts for the passphrase before the OS loads. On this
panel, the prompt is text-mode and readable. `ghost-status` then shows
`Encryption: full disk (LUKS)`.

> Retrofitting FDE in place (`cryptsetup reencrypt`) exists but is genuinely
> risky and slow, and can't be tested from here — reinstalling with encrypted
> LVM is the honest recommendation.

## The vault — secrets, non-destructive

```bash
sudo ghost-vault create        # 2 GB LUKS2 container, choose a passphrase
sudo ghost-vault open          # unlock + mount; links secrets into it
ghost-vault status             # present? open? which secrets protected
sudo ghost-vault protect ~/.ssh
sudo ghost-vault close
```

Protected by default: `~/.claude`, `~/.config/anthropic` (Claude API creds),
`~/.config/ghostboard`, `~/.cache/ghostboard/recon`. On first `open`, an existing
directory is **moved** into the vault and replaced by a symlink — and a
timestamped `.pre-vault` copy is kept, so nothing is ever lost. When the vault
is closed, those symlinks dangle and apps simply prompt for credentials again.

The container is a file (`/var/lib/ghostboard/vault.img`) by default, or a
dedicated partition with `--device /dev/nvme0n1pX` (`create` reformats it, with
a typed confirmation). It's **LUKS2, aes-xts-plain64, 512-bit** — the cryptsetup
default. `install/steps/07-luks-vault.sh` can create it and wire a login prompt
(a `sudoers` line lets `ghost-vault open/close` run without a root password —
the **vault passphrase is always asked**).

## Threat model, honestly

- The vault protects secrets **at rest** — a lost or stolen powered-off deck, or
  a running deck with the vault closed. Once you `open` it, the secrets are
  readable by your session (that's the point).
- The vault does **not** protect the OS, logs, or anything outside it. That's
  what FDE is for.
- Neither defends against a compromised running system. Encryption is about a
  device leaving your hands, not about malware while you're using it.

## Verification note

The LUKS2 **header creation** (`ghost-vault create`) is tested in
`tests/test-vault.sh` — it writes a real, valid LUKS2 header. The
**open/mount** path needs the kernel's device-mapper, which the build
container doesn't have, so that path is standard `cryptsetup` verified on the
deck, not here. Same honesty as the rest of the repo: measured where possible,
marked where not.
