#!/usr/bin/env bash
# DESCRIPTION: Outil ghost-bruce, accès série et règles udev pour cartes ESP32
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
need_root
apt_refresh

step "Dépendances série"
apt_install python3-serial picocom

step "Accès aux ports série"
if id -nG "$GHOSTBOARD_USER" | tr ' ' '\n' | grep -qx dialout; then
  good "$GHOSTBOARD_USER est déjà dans le groupe dialout"
else
  run usermod -aG dialout "$GHOSTBOARD_USER"
  good "$GHOSTBOARD_USER ajouté au groupe dialout"
  warn "il faut se déconnecter/reconnecter pour que ça prenne effet"
fi

step "Règles udev"
# Deux effets : accès en écriture sans root, et un lien stable /dev/ghostbruce*
# pour ne pas dépendre de l'ordre de branchement.
write_file /etc/udev/rules.d/70-ghostboard-bruce.rules <<'UDEV'
# GHOSTBOARD OS — cartes ESP32 sous firmware Bruce.
# Ponts USB-série courants du parc ESP32 : CP210x, CH340/CH9102, FTDI,
# et l'USB natif des ESP32-S2/S3.
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", GROUP="dialout", MODE="0660", SYMLINK+="ghostbruce-cp210x"
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", GROUP="dialout", MODE="0660", SYMLINK+="ghostbruce-ch340"
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="55d4", GROUP="dialout", MODE="0660", SYMLINK+="ghostbruce-ch9102"
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", GROUP="dialout", MODE="0660", SYMLINK+="ghostbruce-ftdi"
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", GROUP="dialout", MODE="0660", SYMLINK+="ghostbruce-esp"
UDEV
run udevadm control --reload-rules 2>/dev/null || true
run udevadm trigger --subsystem-match=tty 2>/dev/null || true
good "règles udev en place"

step "Outil"
install_file "$GHOSTBOARD_REPO/tools/ghost-bruce" /usr/local/bin/ghost-bruce 0755
run install -d -m 0755 "$GHOSTBOARD_HOME/.local/share/applications"
install_file "$GHOSTBOARD_REPO/desktop/launchers/ghostboard-bruce.desktop" \
  "$GHOSTBOARD_HOME/.local/share/applications/ghostboard-bruce.desktop"
run chown -R "$GHOSTBOARD_USER" "$GHOSTBOARD_HOME/.local" 2>/dev/null || true

say ""
info "Branche une carte, puis : ghost-bruce list"
