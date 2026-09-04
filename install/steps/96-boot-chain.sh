#!/usr/bin/env bash
# DESCRIPTION: Chaîne de démarrage — GRUB, initramfs, /tmp, NVMe, session directe
# ============================================================================
#  ÉTAPE SENSIBLE. Elle touche le bootloader, l'initramfs et le gestionnaire de
#  session. Chaque bloc demande confirmation séparément, et chacun est
#  réversible — mais un initramfs raté ne boote plus.
#
#  Prérequis : 00-preflight (donc accès SSH constaté) ET une image du SSD.
#
#  Ordre des gains, du plus gros au plus petit :
#     ~5 s   temporisation GRUB (5 s d'attente par défaut, pour rien)
#     ~1-2 s suppression du gestionnaire de session (LightDM entier)
#     ~0,3 s initramfs réduit aux modules réellement nécessaires
#     marge  /tmp en RAM, ordonnanceur NVMe, verbosité noyau
# ============================================================================
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
need_root
require_step 00-preflight "cette étape touche le bootloader et l'initramfs"

say ""
warn "Cette étape modifie le bootloader et l'initramfs."
warn "Si tu n'as pas fait d'image du SSD, arrête-toi ici et fais-la."
if [[ "$DRY_RUN" != "1" ]]; then
  confirm "Une image du SSD existe, on peut continuer ?" || \
    die "arrêt volontaire — fais l'image d'abord (voir 00-preflight)"
fi

# ---------------------------------------------------------------------------
#  1. GRUB — le plus gros gain unitaire de tout l'OS
# ---------------------------------------------------------------------------
step "GRUB"
info "GRUB attend 5 s au démarrage. Sur un budget de 20 s, c'est un quart."
info "os-prober scanne tous les disques à chaque mise à jour du noyau : sans"
info "second système installé, c'est du temps pur perdu."
if confirm "Ramener la temporisation GRUB à 0 et couper os-prober ?"; then
  backup_file /etc/default/grub
  write_file /etc/default/grub.d/60-ghostboard.cfg <<'GRUBCFG'
# GHOSTBOARD OS — démarrage direct.
# Fichier séparé plutôt qu'édition de /etc/default/grub : une mise à jour de
# paquet ne peut pas l'écraser, et le retirer suffit à tout annuler.

# 0 s d'attente, menu caché. Pour le rouvrir ponctuellement : maintenir Maj
# (BIOS) ou Échap (UEFI) pendant le démarrage.
GRUB_TIMEOUT=0
GRUB_TIMEOUT_STYLE=hidden
# Après un arrêt brutal, GRUB force normalement 30 s de menu. Sur un appareil
# alimenté par powerbank, un arrêt brutal est un lundi ordinaire.
GRUB_RECORDFAIL_TIMEOUT=0
# Aucun autre système sur ce SSD.
GRUB_DISABLE_OS_PROBER=true
GRUB_DISABLE_SUBMENU=y
# Verbosité noyau réduite : moins de rendu console avant que X ne prenne la
# main. loglevel=3 garde les erreurs, coupe le bavardage.
# Les atténuations de sécurité du processeur ne sont PAS touchées.
GRUB_CMDLINE_LINUX_DEFAULT="quiet loglevel=3 nowatchdog nmi_watchdog=0 systemd.show_status=false"
GRUBCFG
  run update-grub && good "GRUB : 0 s d'attente, os-prober coupé"
else
  info "ignoré"
fi

# ---------------------------------------------------------------------------
#  2. initramfs
# ---------------------------------------------------------------------------
step "initramfs"
info "Debian construit un initramfs « most » : tous les pilotes de stockage"
info "imaginables, ~90 Mo à décompresser au démarrage. « dep » ne garde que"
info "les modules que CETTE machine charge réellement."
warn "C'est le changement classique qui empêche de redémarrer si le matériel"
warn "change (nouveau contrôleur, SSD déplacé dans une autre machine)."
info "Retour arrière : démarrer sur une clé live, chroot, remettre MODULES=most,"
info "puis update-initramfs -u."
if confirm "Réduire l'initramfs aux modules réellement utilisés ?"; then
  backup_file /etc/initramfs-tools/initramfs.conf
  write_file /etc/initramfs-tools/conf.d/ghostboard.conf <<'INITRD'
# GHOSTBOARD OS — initramfs minimal.
# dep = uniquement les modules nécessaires au matériel présent.
MODULES=dep
# zstd niveau 1 : la décompression est ce qui compte au démarrage, pas la
# taille du fichier. Niveau 1 décompresse nettement plus vite que le défaut
# pour quelques Mo de plus sur un SSD de 512 Go.
COMPRESS=zstd
COMPRESSLEVEL=1
INITRD
  before="$(du -sh /boot/initrd.img-"$(uname -r)" 2>/dev/null | cut -f1)"
  if run update-initramfs -u -k all; then
    after="$(du -sh /boot/initrd.img-"$(uname -r)" 2>/dev/null | cut -f1)"
    good "initramfs reconstruit : ${before:-?} -> ${after:-?}"
    warn "NE REDÉMARRE PAS sans avoir vérifié que tu peux reprendre la main"
    warn "en SSH ou avec une clé live."
  else
    warn "reconstruction échouée — configuration retirée par sécurité"
    run rm -f /etc/initramfs-tools/conf.d/ghostboard.conf
    run update-initramfs -u -k all || true
  fi
else
  info "ignoré"
fi

# ---------------------------------------------------------------------------
#  3. /tmp en mémoire
# ---------------------------------------------------------------------------
step "/tmp en RAM"
# Avec 16 Go, écrire les fichiers temporaires sur le NVMe n'a aucun intérêt :
# c'est plus lent, ça use la mémoire flash, et ça survit inutilement au
# redémarrage. tmpfs se limite tout seul à la moitié de la RAM.
if systemctl is-enabled tmp.mount >/dev/null 2>&1; then
  good "/tmp déjà en tmpfs"
else
  run systemctl enable tmp.mount >/dev/null 2>&1 \
    && good "/tmp en tmpfs au prochain démarrage (moins d'écritures NVMe)"
fi

# ---------------------------------------------------------------------------
#  4. NVMe
# ---------------------------------------------------------------------------
step "Ordonnanceur NVMe"
# Un NVMe a des dizaines de files matérielles : tout ordonnanceur logiciel
# ajoute de la latence sans rien réordonner d'utile. `none` est déjà le défaut
# du noyau pour nvme, la règle garantit qu'aucun paquet ne le change.
write_file /etc/udev/rules.d/60-ghostboard-nvme.rules <<'UDEV'
# GHOSTBOARD OS — stockage.
# none : pas d'ordonnanceur logiciel devant un NVMe multi-files.
ACTION=="add|change", KERNEL=="nvme[0-9]*n[0-9]*", ATTR{queue/scheduler}="none"
# rq_affinity=2 : la complétion est traitée sur le cœur qui a émis la requête,
# ce qui évite un réveil inter-cœurs par E/S.
ACTION=="add|change", KERNEL=="nvme[0-9]*n[0-9]*", ATTR{queue/rq_affinity}="2"
# mq-deadline pour un éventuel SSD SATA/USB : là, l'ordonnanceur sert encore.
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="mq-deadline"
UDEV
run udevadm control --reload-rules 2>/dev/null || true
run udevadm trigger --subsystem-match=block 2>/dev/null || true
current="$(cat /sys/block/nvme0n1/queue/scheduler 2>/dev/null || echo 'aucun NVMe')"
good "ordonnanceur NVMe : ${current}"

# ---------------------------------------------------------------------------
#  5. Gestionnaire de session — le deuxième plus gros gain
# ---------------------------------------------------------------------------
step "Ouverture de session"
say ""
info "Deux modes possibles :"
info ""
info "  A. LightDM avec connexion automatique"
info "     Garde l'écran de connexion pour choisir la session ; il démarre,"
info "     s'affiche et se referme aussitôt. Coût : ~1 s et ~40 Mo."
info ""
info "  B. Session directe, SANS gestionnaire de session   [le plus rapide]"
info "     tty1 ouvre la session automatiquement et lance X directement."
info "     LightDM reste installé mais désactivé : une commande pour revenir."
info "     Gain : ~1 à 2 s et ~40 Mo. C'est le mode le plus performant."
say ""
warn "Dans les DEUX cas, la session s'ouvre SANS mot de passe."
warn "Quiconque tient le deck a un shell. Sur un appareil nomade qui embarque"
warn "des identifiants d'API, c'est un vrai choix, pas un détail de confort."
info "Chiffrer le disque (LUKS) est la réponse à ça — pas le mot de passe de session."
say ""

install_session_switcher() {
  write_file /usr/local/bin/ghost-session-mode 0755 <<'MODE'
#!/usr/bin/env bash
# GHOSTBOARD OS — mode d'ouverture de session.
#
#   ghost-session-mode status
#   ghost-session-mode direct    tty1 -> X directement, sans gestionnaire (le plus rapide)
#   ghost-session-mode dm        via LightDM avec connexion automatique
#   ghost-session-mode login     via LightDM AVEC saisie du mot de passe
#
# Bascule à chaud, sans réinstaller. Effet au prochain redémarrage.
set -uo pipefail
USER_NAME="${GHOSTBOARD_USER:-$(logname 2>/dev/null || echo "${SUDO_USER:-$USER}")}"
OVERRIDE=/etc/systemd/system/getty@tty1.service.d/ghostboard-autologin.conf
LDM=/etc/lightdm/lightdm.conf.d/70-ghostboard-autologin.conf

need_root() { [[ "$(id -u)" -eq 0 ]] || { echo "à lancer avec sudo" >&2; exit 1; }; }

case "${1:-status}" in
  status)
    if systemctl is-enabled lightdm >/dev/null 2>&1; then
      if [[ -f "$LDM" ]]; then echo "mode : dm (LightDM, connexion automatique)"
      else echo "mode : login (LightDM, mot de passe demandé)"; fi
    elif [[ -f "$OVERRIDE" ]]; then
      echo "mode : direct (tty1 -> X, sans gestionnaire de session)"
    else
      echo "mode : indéterminé — ni LightDM actif, ni ouverture automatique tty1"
    fi
    ;;
  direct)
    need_root
    mkdir -p "$(dirname "$OVERRIDE")"
    cat > "$OVERRIDE" <<UNIT
# GHOSTBOARD OS — ouverture automatique sur tty1.
# Le gain vient de la SUPPRESSION du gestionnaire de session, pas seulement de
# l'absence de mot de passe : plus de serveur X du greeter, plus de session GTK
# intermédiaire, plus de bascule de VT.
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $USER_NAME --noclear %I \$TERM
UNIT
    systemctl disable lightdm >/dev/null 2>&1 || true
    systemctl set-default graphical.target >/dev/null 2>&1 || true
    systemctl daemon-reload
    echo "mode direct armé. X sera lancé par le profil de connexion de $USER_NAME."
    echo "Effet au prochain redémarrage."
    ;;
  dm|login)
    need_root
    rm -f "$OVERRIDE"
    if [[ "$1" == "dm" ]]; then
      mkdir -p "$(dirname "$LDM")"
      cat > "$LDM" <<CONF
[Seat:*]
autologin-user=$USER_NAME
autologin-user-timeout=0
autologin-session=ghostboard
CONF
      groupadd -f autologin && usermod -aG autologin "$USER_NAME"
    else
      rm -f "$LDM"
    fi
    systemctl enable lightdm >/dev/null 2>&1 || true
    systemctl daemon-reload
    echo "mode $1 armé. Effet au prochain redémarrage."
    ;;
  *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
MODE

  # Sans gestionnaire de session, c'est le profil de connexion qui lance X.
  # `startx` place le client dans un X déjà démarré : ghostboard-session y joue
  # l'animation puis passe la main à XFCE, exactement comme sous LightDM.
  write_file "$GHOSTBOARD_HOME/.bash_profile" <<'PROFILE'
# GHOSTBOARD OS — démarrage de la session graphique depuis tty1.
# Ne s'applique QU'À tty1 : une connexion SSH ou un autre VT reste en texte,
# ce qui est la porte de secours quand l'affichage ne va pas.
[[ -f ~/.bashrc ]] && . ~/.bashrc

if [[ -z "${DISPLAY:-}" && "${XDG_VTNR:-}" == "1" && "${GHOSTBOARD_NO_X:-0}" != "1" ]]; then
  exec startx /usr/local/bin/ghostboard-session -- vt1 -keeptty -nolisten tcp
fi
PROFILE
  run chown "$GHOSTBOARD_USER" "$GHOSTBOARD_HOME/.bash_profile" 2>/dev/null || true
}

install_session_switcher

if confirm "Passer en session DIRECTE, sans gestionnaire de session (mode B) ?"; then
  run /usr/local/bin/ghost-session-mode direct
  good "session directe armée"
  info "revenir : sudo ghost-session-mode dm   (ou login pour le mot de passe)"
elif confirm "Activer au moins la connexion automatique LightDM (mode A) ?"; then
  run /usr/local/bin/ghost-session-mode dm
  good "connexion automatique LightDM armée"
else
  info "aucun changement — mot de passe demandé au démarrage"
fi

# ---------------------------------------------------------------------------
#  6. Modules noyau
# ---------------------------------------------------------------------------
step "Modules noyau"
# Le service bluetooth est déjà désactivé (étape 95), mais le module se charge
# quand même à la détection du contrôleur et garde la radio alimentée.
if confirm "Empêcher le chargement du Bluetooth (radio et pile désactivées) ?"; then
  write_file /etc/modprobe.d/ghostboard-blacklist.conf <<'BL'
# GHOSTBOARD OS — matériel non utilisé.
# Le clavier BB Q20 est en USB, les cartes ESP32 aussi. La radio Bluetooth
# consomme sans rien servir. Retirer ce fichier pour la réactiver.
blacklist btusb
blacklist bluetooth
blacklist btintel
blacklist btbcm
blacklist btrtl
BL
  good "Bluetooth non chargé au prochain démarrage"
else
  info "Bluetooth conservé"
fi

say ""
warn "REDÉMARRE, puis vérifie tout d'un coup :"
info "  ghost-perf        audit de chaque réglage, avec la commande de correction"
info "  ghost-bench       chiffres réels face aux cibles"
