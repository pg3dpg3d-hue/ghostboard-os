#!/usr/bin/env bash
# DESCRIPTION: Paquets de base, locale, réglages NVMe et mémoire
# ============================================================================
#  Socle minimal. Aucun environnement de bureau ici : on pose les outils dont
#  toutes les étapes suivantes dépendent, et les réglages disque/mémoire.
# ============================================================================
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
need_root
apt_refresh

# Volontairement court. Chaque paquet ajouté ici est un paquet à démarrer,
# à mettre à jour et à surveiller sur une machine qui vise 20 s de boot.
apt_install \
  ca-certificates curl wget gnupg \
  python3 python3-venv \
  git build-essential pkg-config \
  pciutils usbutils lsb-release \
  zstd unzip \
  htop iotop \
  network-manager \
  openssh-server

step "Langue et clavier système"
# Interface de l'OS en anglais (décision produit), fuseau horaire local.
if ! grep -q '^en_US.UTF-8 UTF-8' /etc/locale.gen 2>/dev/null; then
  backup_file /etc/locale.gen
  run sed -i 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
  run locale-gen
fi
write_file /etc/default/locale <<'LOCALE'
# GHOSTBOARD OS — interface en anglais.
LANG=en_US.UTF-8
LC_ALL=en_US.UTF-8
LOCALE

step "Racine NVMe"
root_src="$(root_device)"
if findmnt -no OPTIONS / | grep -q noatime; then
  good "/ déjà monté en noatime"
else
  info "Ajout de noatime sur / : supprime une écriture à chaque lecture de fichier."
  info "Sur un NVMe c'est du gain net, et de la durée de vie en plus."
  if confirm "Modifier /etc/fstab pour ajouter noatime sur / ?"; then
    backup_file /etc/fstab
    # On ne touche qu'à la ligne de la racine, et seulement si relatime/defaults y est.
    run sed -i -E '/[[:space:]]\/[[:space:]]/ s/(defaults|relatime)/\1,noatime/' /etc/fstab
    good "noatime ajouté — actif au prochain redémarrage"
  else
    info "ignoré"
  fi
fi

# TRIM hebdomadaire plutôt que discard en continu : discard à chaque
# suppression ajoute de la latence sur le chemin d'écriture.
if systemctl list-unit-files fstrim.timer >/dev/null 2>&1; then
  run systemctl enable fstrim.timer >/dev/null 2>&1 && good "fstrim.timer activé (TRIM hebdomadaire)"
fi

step "Mémoire"
ram="$(ram_gb)"
if [[ "$ram" -ge 12 ]]; then
  good "${ram} Go : pas de swap ni de zram nécessaires"
  # swappiness bas : avec 16 Go, échanger sur le NVMe n'a aucun intérêt et
  # coûte de la latence.
  write_file /etc/sysctl.d/60-ghostboard-memory.conf <<'SYSCTL'
# GHOSTBOARD OS — 16 Go de RAM : on n'échange qu'en dernier recours.
vm.swappiness = 10
vm.vfs_cache_pressure = 50
# Écritures différées plus longtemps : moins de réveils du NVMe, moins de watts.
vm.dirty_writeback_centisecs = 1500
SYSCTL
else
  warn "${ram} Go : zram recommandé"
  if confirm "Installer zram-tools (compression mémoire) ?"; then
    apt_install zram-tools
    write_file /etc/default/zramswap <<'ZRAM'
# GHOSTBOARD OS — zram : swap compressé en RAM, jamais sur le NVMe.
ALGO=zstd
PERCENT=50
PRIORITY=100
ZRAM
    run systemctl enable --now zramswap 2>/dev/null || true
  fi
fi
run sysctl --system >/dev/null 2>&1 || true

step "Énergie"
# Le deck tourne sur powerbank : chaque watt compte.
#
# PAS de power-profiles-daemon ni de TLP : ce sont des démons résidents pour un
# réglage qui ne change jamais sur un appareil à alimentation unique, et l'OS
# n'expose aucune interface pour les piloter. Un oneshot au démarrage fait le
# même travail pour zéro processus résident.
#
# Gouverneur `powersave` + EPP `balance_power` sur intel_pstate : contrairement
# à ce que le nom suggère, `powersave` sur intel_pstate n'est PAS un bridage —
# c'est l'algorithme adaptatif du pilote, qui monte en fréquence à la demande.
# `performance` fige la fréquence haute et ne gagne rien en réactivité perçue.
write_file /etc/systemd/system/ghostboard-power.service <<'PWR'
[Unit]
Description=GHOSTBOARD — réglage d'énergie (oneshot, aucun démon résident)
After=multi-user.target
ConditionPathExists=/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/ghost-power-tune

[Install]
WantedBy=multi-user.target
PWR

write_file /usr/local/bin/ghost-power-tune 0755 <<'TUNE'
#!/bin/sh
# GHOSTBOARD OS — réglage d'énergie appliqué une fois au démarrage.
# Aucun démon : ce script s'exécute, écrit, et sort.
set -u

for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
  [ -w "$g" ] && echo powersave > "$g" 2>/dev/null
done

# EPP : indique au processeur l'arbitrage perf/énergie. balance_power garde la
# réactivité en rafale (race-to-idle) tout en baissant la consommation au repos.
for e in /sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference; do
  [ -w "$e" ] && echo balance_power > "$e" 2>/dev/null
done

# ASPM PCIe : laisse le NVMe et le contrôleur descendre en état bas.
[ -w /sys/module/pcie_aspm/parameters/policy ] && \
  echo powersupersave > /sys/module/pcie_aspm/parameters/policy 2>/dev/null

# Mise en veille automatique de l'USB — SAUF les périphériques d'entrée et les
# ponts série. Endormir le clavier BB Q20 ou une carte ESP32 en pleine console
# série est exactement le genre d'« optimisation » qui casse l'appareil.
for d in /sys/bus/usb/devices/*/power/control; do
  dev="${d%/power/control}"
  cls="$(cat "$dev/bDeviceClass" 2>/dev/null || echo "")"
  # 03 = HID (clavier, trackpad) ; 02/0a = CDC (ports série ESP32)
  case "$cls" in 03|02|0a) continue ;; esac
  if [ -d "$dev" ] && grep -qsE '^(03|02|0a)' "$dev"/*/bInterfaceClass 2>/dev/null; then
    continue
  fi
  [ -w "$d" ] && echo auto > "$d" 2>/dev/null
done
exit 0
TUNE

run systemctl daemon-reload
run systemctl enable ghostboard-power.service >/dev/null 2>&1 \
  && good "réglage d'énergie : oneshot au démarrage, zéro démon résident"
