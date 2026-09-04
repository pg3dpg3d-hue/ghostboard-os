#!/usr/bin/env bash
# DESCRIPTION: Chasse aux services systemd inutiles, journal borné, délais
# ============================================================================
#  Objectif : boot < 20 s, RAM au repos < 900 Mo, rien qui tourne pour rien.
#  On désactive, puis on MESURE. Aucun chiffre n'est supposé.
# ============================================================================
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
need_root

step "État avant"
if command -v systemd-analyze >/dev/null 2>&1; then
  systemd-analyze 2>/dev/null | head -1 | sed 's/^/   /' || true
  info "5 unités les plus lentes :"
  systemd-analyze blame 2>/dev/null | head -5 | sed 's/^/     /' || true
fi

step "Services désactivés"
# Chaque ligne ci-dessous est un choix, pas une liste copiée :
#   ModemManager      pas de modem cellulaire sur ce deck
#   bluetooth         l'antenne consomme ; le clavier est en USB
#   cups*             aucune imprimante sur un cyberdeck
#   avahi-daemon      découverte réseau locale, inutile et bavarde
#   packagekit        démon de mise à jour graphique, remplacé par apt
#   apt-daily*        téléchargements en arrière-plan sur batterie : non
#   e2scrub_all       pertinent pour LVM/ext4, sans objet ici
#   NetworkManager-wait-online   bloque le boot jusqu'à obtention d'une IP
for unit in ModemManager.service bluetooth.service \
            cups.service cups-browsed.service cups.socket cups.path \
            avahi-daemon.service avahi-daemon.socket \
            packagekit.service packagekit-offline-update.service \
            apt-daily.timer apt-daily-upgrade.timer \
            e2scrub_all.timer e2scrub_reap.service \
            NetworkManager-wait-online.service \
            systemd-networkd-wait-online.service; do
  if systemctl list-unit-files "$unit" >/dev/null 2>&1 && \
     systemctl is-enabled "$unit" >/dev/null 2>&1; then
    run systemctl disable --now "$unit" >/dev/null 2>&1 && good "désactivé : $unit"
  fi
done

step "Journal"
# Journal borné : sans limite, il grossit indéfiniment sur le NVMe et rallonge
# le démarrage de systemd-journald.
write_file /etc/systemd/journald.conf.d/60-ghostboard.conf <<'JRN'
# GHOSTBOARD OS — journal borné.
[Journal]
Storage=persistent
SystemMaxUse=200M
SystemMaxFileSize=20M
MaxRetentionSec=2week
JRN
run systemctl restart systemd-journald 2>/dev/null || true

step "Délais de démarrage"
# 90 s d'attente par défaut sur une unité bloquée, c'est 90 s de boot perdues
# sur une machine qui vise 20 s.
write_file /etc/systemd/system.conf.d/60-ghostboard.conf <<'SD'
# GHOSTBOARD OS — on n'attend pas 90 s qu'une unité veuille bien démarrer.
[Manager]
DefaultTimeoutStartSec=15s
DefaultTimeoutStopSec=10s
SD

run systemctl daemon-reload
good "délais de démarrage bornés"

say ""
info "La chaîne de démarrage (GRUB, initramfs, /tmp, ordonnanceur NVMe,"
info "gestionnaire de session) est traitée à l'étape 96-boot-chain."
