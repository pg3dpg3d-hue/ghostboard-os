#!/usr/bin/env bash
# DESCRIPTION: Relevé du matériel réel, filet de sécurité SSH, écart avec la cible
# ============================================================================
#  Rien n'est installé ici. On regarde, on compare, on prévient.
#
#  Cette étape est un VERROU : les étapes qui touchent l'écran, le bootloader
#  ou le gestionnaire de session refusent de démarrer tant qu'elle n'est pas
#  passée. Si tu perds l'affichage, le SSH est la seule porte d'entrée qui
#  reste — il doit exister AVANT qu'on touche à quoi que ce soit.
# ============================================================================
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
need_root

TARGET_RAM_GB=16
TARGET_SSD_GB=512
TARGET_W=800
TARGET_H=480

warnings=0
note() { warn "$*"; warnings=$((warnings + 1)); }

# ---- CPU -------------------------------------------------------------------
cpu_model="$(awk -F': ' '/model name/{print $2; exit}' /proc/cpuinfo)"
say "CPU          $cpu_model  ($(nproc) cœurs)"
if is_intel_n100; then
  good "Intel N100 confirmé — c'est la cible"
else
  note "CPU attendu : Intel N100 (Radxa X4). Trouvé : $cpu_model"
  info "     L'installation continue, mais les réglages d'énergie et les"
  info "     chiffres de BENCHMARKS.md ne vaudront que pour CE processeur."
fi

# ---- RAM -------------------------------------------------------------------
ram="$(ram_gb)"
say "RAM          ${ram} Go"
if [[ "$ram" -ge $((TARGET_RAM_GB - 2)) ]]; then
  good "conforme à la configuration déclarée (${TARGET_RAM_GB} Go)"
else
  note "RAM déclarée : ${TARGET_RAM_GB} Go, mesurée : ${ram} Go"
  info "     Avec moins de 16 Go, activer zram : voir 10-base-system.sh"
fi

# ---- stockage --------------------------------------------------------------
root_dev="$(root_device)"
say "Racine       $root_dev"
lsblk -dno NAME,SIZE,ROTA,MODEL | while read -r n s r m; do
  kind="$([[ "$r" == "0" ]] && echo SSD || echo "disque rotatif")"
  info "  /dev/$n  $s  $kind  $m"
done
if has_nvme; then
  good "NVMe détecté — l'OS peut booter dessus"
else
  note "aucun NVMe détecté. La cible est un M.2 2230 NVMe de ${TARGET_SSD_GB} Go."
fi
root_gb="$(df -BG --output=size / | tail -1 | tr -dc '0-9')"
[[ "${root_gb:-0}" -lt 40 ]] && note "racine de ${root_gb} Go : très juste pour un bureau + navigateur"

# ---- écran -----------------------------------------------------------------
say "Écran"
found_panel=0
if [[ -d /sys/class/drm ]]; then
  for card in /sys/class/drm/card*-*; do
    [[ -f "$card/status" ]] || continue
    st="$(cat "$card/status")"
    [[ "$st" == "connected" ]] || continue
    conn="$(basename "$card")"
    mode="$(head -1 "$card/modes" 2>/dev/null)"
    info "  $conn  $st  ${mode:-mode inconnu}"
    found_panel=1
    [[ "$mode" == "${TARGET_W}x${TARGET_H}" ]] && good "dalle ${TARGET_W}x${TARGET_H} vue par le noyau"
  done
else
  note "/sys/class/drm absent : aucun pilote graphique (machine sans tête ?)"
fi
[[ "$found_panel" == "0" ]] && note "aucune sortie vidéo connectée détectée"

# ---- clavier ---------------------------------------------------------------
say "Claviers USB"
kbd_found=0
if command -v lsusb >/dev/null 2>&1; then
  while read -r line; do
    info "  $line"; kbd_found=1
  done < <(lsusb 2>/dev/null | grep -iE 'keyboard|hid|blackberry|solder' || true)
fi
for dev in /sys/class/input/input*; do
  [[ -f "$dev/name" ]] || continue
  name="$(cat "$dev/name")"
  if [[ "$name" =~ [Kk]eyboard|BB|Q20 ]]; then info "  input : $name"; kbd_found=1; fi
done
[[ "$kbd_found" == "0" ]] && note "aucun clavier détecté (BlackBerry Q20 attendu en USB HID)"

# ---- cartes ESP32 ----------------------------------------------------------
boards="$(ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null | wc -l)"
say "Ports série  ${boards} (cartes ESP32/Bruce branchées)"

# ============================================================================
#  FILET DE SÉCURITÉ — la partie qui compte vraiment
# ============================================================================
step "Filet de sécurité"

ssh_ok=0
if systemctl is-active --quiet ssh 2>/dev/null || systemctl is-active --quiet sshd 2>/dev/null; then
  good "serveur SSH actif"
  ssh_ok=1
  for a in $(hostname -I 2>/dev/null); do info "  ssh $GHOSTBOARD_USER@$a"; done
else
  note "AUCUN SERVEUR SSH ACTIF"
  info "     C'est le seul moyen de reprendre la main si l'écran tombe."
  info "     sudo apt install openssh-server && sudo systemctl enable --now ssh"
fi

if command -v tailscale >/dev/null 2>&1; then
  if tailscale status >/dev/null 2>&1; then
    good "Tailscale connecté : $(tailscale ip -4 2>/dev/null | head -1)"
    ssh_ok=1
  else
    note "Tailscale installé mais pas connecté (sudo tailscale up)"
  fi
else
  info "Tailscale non installé. Fortement recommandé sur un deck nomade :"
  info "  le SSH local ne sert à rien si tu n'es pas sur le même réseau."
  info "  curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up"
fi

# ---- image du SSD ----------------------------------------------------------
say ""
warn "AVANT d'aller plus loin : fais une image du SSD."
info "  Depuis une autre machine, SSD en boîtier USB :"
info "    sudo dd if=/dev/nvme0n1 bs=64M status=progress | zstd -T0 > ghostboard-base.img.zst"
info "  C'est le seul retour en arrière garanti si le bootloader ou l'écran cassent."

# ---- verdict ---------------------------------------------------------------
say ""
if [[ "$ssh_ok" == "0" ]]; then
  warn "Pas d'accès de secours détecté."
  confirm "Continuer SANS filet SSH (déconseillé) ?" || \
    die "arrêt volontaire. Installe openssh-server, puis relance."
fi
if [[ "$warnings" -gt 0 ]]; then
  say ""
  warn "$warnings écart(s) avec le matériel cible (voir ci-dessus)."
  confirm "Poursuivre l'installation malgré ces écarts ?" || \
    die "arrêt volontaire."
fi

# Trace du relevé : BENCHMARKS.md et le README s'y réfèrent.
run mkdir -p "$GHOSTBOARD_STATE"
if [[ "$DRY_RUN" == "1" ]]; then
  info "[à blanc] relevé matériel non écrit"
else
{
  echo "# Relevé matériel — $(date -Is)"
  echo "cpu=$cpu_model"
  echo "cores=$(nproc)"
  echo "ram_gb=$ram"
  echo "root_device=$root_dev"
  echo "root_gb=$root_gb"
  echo "nvme=$(has_nvme && echo oui || echo non)"
  echo "ssh_rescue=$([[ "$ssh_ok" == "1" ]] && echo oui || echo non)"
  echo "warnings=$warnings"
} > "$GHOSTBOARD_STATE/hardware-survey.txt"
  good "relevé écrit dans $GHOSTBOARD_STATE/hardware-survey.txt"
fi
