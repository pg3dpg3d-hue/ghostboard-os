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
# Le deck tourne sur powerbank : chaque watt compte. `powersave` sur un N100
# reste très réactif — le gouverneur monte en fréquence à la demande.
apt_install power-profiles-daemon
if command -v powerprofilesctl >/dev/null 2>&1; then
  run powerprofilesctl set balanced 2>/dev/null || true
  good "profil d'énergie : balanced (powerprofilesctl set power-saver pour aller plus loin)"
fi
