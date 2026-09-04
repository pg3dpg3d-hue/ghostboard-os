#!/usr/bin/env bash
# ============================================================================
#  GHOSTBOARD OS — RECON › Camera Audit — installation
# ============================================================================
#  Idempotent : relançable sans rien casser. Chaque binaire est vérifié, et ce
#  qui manque est journalisé plutôt que supposé présent.
#
#  Fait :
#    - paquets système : nmap, ffmpeg, docker.io, python3-venv
#    - venv Python dédié + requirements.txt (auditkit) + la TUI (textual)
#    - pré-tirage de l'image Docker ullaakut/cameradar
#    - ajout de l'utilisateur au groupe docker
#
#  Ne touche PAS au système au-delà de ça : ni service, ni règle réseau.
#  Sur le deck GHOSTBOARD, à lancer depuis ./camera-audit :
#      ./install.sh
# ============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv"
LOG="$HERE/install.log"
CAMERADAR_IMAGE="${CAMERADAR_IMAGE:-ullaakut/cameradar}"
TARGET_USER="${SUDO_USER:-$USER}"

: > "$LOG"
missing=()   # binaires réclamés mais absents à la fin
warned=0

# --- couleurs (palette GHOSTBOARD si dispo, sinon repli) --------------------
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  A=$'\033[38;2;168;85;247m'; I=$'\033[38;2;255;77;141m'
  D=$'\033[38;2;110;104;128m'; G=$'\033[38;2;95;215;164m'; Z=$'\033[0m'
else A=""; I=""; D=""; G=""; Z=""; fi

log()  { printf '%s %s\n' "$(date -Is)" "$*" >> "$LOG"; }
say()  { printf '%s\n' "$*"; log "$*"; }
step() { printf '\n%s── %s%s\n' "$A" "$*" "$Z"; log "== $*"; }
ok()   { printf '   %s✓%s %s\n' "$G" "$Z" "$*"; log " ok $*"; }
info() { printf '   %s%s%s\n' "$D" "$*" "$Z"; log "    $*"; }
warn() { printf '   %s!%s %s\n' "$I" "$Z" "$*"; log " !! $*"; warned=$((warned+1)); }

need_bin() {  # nom_binaire  [paquet]
  if command -v "$1" >/dev/null 2>&1; then
    ok "$1 présent — $("$1" --version 2>&1 | head -1 | cut -c1-46)"
    return 0
  fi
  warn "$1 ABSENT${2:+ (paquet $2)}"
  missing+=("$1")
  return 1
}

# ---------------------------------------------------------------------------
say "GHOSTBOARD OS — RECON › Camera Audit — installation"
info "journal : $LOG"
info "utilisateur cible : $TARGET_USER"

SUDO=""
if [[ "$(id -u)" -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then SUDO="sudo"; else
    warn "ni root ni sudo — l'installation des paquets système sera sautée"
  fi
fi

# ---------------------------------------------------------------------------
step "Paquets système"
PKGS=(nmap ffmpeg docker.io python3-venv)
if command -v apt-get >/dev/null 2>&1 && [[ -n "$SUDO" || "$(id -u)" -eq 0 ]]; then
  # On n'installe QUE ce qui manque : apt sur des paquets déjà là est un no-op,
  # mais éviter l'appel réseau rend le script plus rapide en relance.
  to_install=()
  for p in "${PKGS[@]}"; do
    dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed' \
      || to_install+=("$p")
  done
  if [[ ${#to_install[@]} -gt 0 ]]; then
    info "installation : ${to_install[*]}"
    if $SUDO env DEBIAN_FRONTEND=noninteractive apt-get update -qq >>"$LOG" 2>&1 \
       && $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            "${to_install[@]}" >>"$LOG" 2>&1; then
      ok "paquets installés"
    else
      warn "échec apt-get — voir $LOG"
    fi
  else
    ok "tous les paquets système déjà présents"
  fi
else
  warn "apt-get indisponible ou pas de privilège — installe à la main : ${PKGS[*]}"
fi

step "Vérification des binaires"
need_bin nmap nmap
need_bin ffmpeg ffmpeg
need_bin docker docker.io
need_bin python3 python3

# ---------------------------------------------------------------------------
step "Environnement Python"
if [[ ! -d "$VENV" ]]; then
  if python3 -m venv "$VENV" >>"$LOG" 2>&1; then ok "venv créé : $VENV"
  else warn "création du venv impossible — python3-venv manquant ?"; fi
else
  ok "venv déjà présent : $VENV"
fi

if [[ -x "$VENV/bin/pip" ]]; then
  "$VENV/bin/pip" install -q --upgrade pip >>"$LOG" 2>&1 || true
  # requirements.txt d'auditkit (s'il existe), puis la TUI.
  if [[ -f "$HERE/requirements.txt" ]]; then
    info "installation de requirements.txt (auditkit)"
    "$VENV/bin/pip" install -q -r "$HERE/requirements.txt" >>"$LOG" 2>&1 \
      && ok "dépendances auditkit installées" \
      || warn "échec requirements.txt — voir $LOG"
  else
    warn "requirements.txt absent (auditkit non présent dans ce dossier)"
  fi
  info "installation de la TUI (textual)"
  "$VENV/bin/pip" install -q -r "$HERE/requirements-ghostboard.txt" >>"$LOG" 2>&1 \
    && ok "TUI installée" || warn "échec installation TUI — voir $LOG"
  # auditkit lui-même, si packagé (setup.py/pyproject à la racine).
  if [[ -f "$HERE/setup.py" || -f "$HERE/pyproject.toml" ]]; then
    "$VENV/bin/pip" install -q -e "$HERE" >>"$LOG" 2>&1 \
      && ok "auditkit installé en editable" \
      || info "auditkit non installable en paquet (lancé par chemin, sans doute)"
  fi
else
  warn "pip absent dans le venv — étape Python sautée"
fi

# ---------------------------------------------------------------------------
step "Image Docker Cameradar"
if command -v docker >/dev/null 2>&1; then
  if docker image inspect "$CAMERADAR_IMAGE" >/dev/null 2>&1; then
    ok "$CAMERADAR_IMAGE déjà présente"
  elif docker info >/dev/null 2>&1; then
    info "pré-tirage de $CAMERADAR_IMAGE (peut prendre une minute)"
    if docker pull "$CAMERADAR_IMAGE" >>"$LOG" 2>&1; then
      ok "image tirée"
    else
      warn "échec du pull — réseau ? démon docker ? voir $LOG"
    fi
  else
    warn "démon docker injoignable (droits ?) — image non tirée"
    info "après l'ajout au groupe docker + reconnexion : docker pull $CAMERADAR_IMAGE"
  fi
else
  warn "docker absent — Cameradar (module RTSP) ne fonctionnera pas"
fi

# ---------------------------------------------------------------------------
step "Groupe docker"
if getent group docker >/dev/null 2>&1; then
  if id -nG "$TARGET_USER" | tr ' ' '\n' | grep -qx docker; then
    ok "$TARGET_USER est déjà dans le groupe docker"
  elif [[ -n "$SUDO" || "$(id -u)" -eq 0 ]]; then
    if $SUDO usermod -aG docker "$TARGET_USER" >>"$LOG" 2>&1; then
      ok "$TARGET_USER ajouté au groupe docker"
      warn "déconnecte-toi puis reconnecte-toi pour que ça prenne effet"
    else
      warn "usermod a échoué — voir $LOG"
    fi
  else
    warn "ajout au groupe docker impossible sans privilège"
    info "sudo usermod -aG docker $TARGET_USER"
  fi
else
  warn "groupe docker inexistant — docker.io est-il bien installé ?"
fi

# ---------------------------------------------------------------------------
step "Bilan"
if [[ ${#missing[@]} -gt 0 ]]; then
  warn "binaires manquants : ${missing[*]}"
  info "le module correspondant restera indisponible tant qu'ils manquent"
fi
if [[ "$warned" -eq 0 ]]; then
  say "${G}Installation complète, aucun avertissement.${Z}"
else
  say "${I}Installation terminée avec $warned avertissement(s) — voir ci-dessus et $LOG.${Z}"
fi
say ""
say "Lancer la TUI :"
say "   $HERE/bin/ghost-recon        (ou : RECON › Camera Audit dans le menu)"
say "Vérifier sans scanner (backend démo si auditkit absent) :"
say "   $VENV/bin/python -m ghostboard"

# Un binaire manquant n'est pas un échec d'install (le deck peut les ajouter
# plus tard) ; seul un venv/TUI cassé l'est.
[[ -x "$VENV/bin/python" ]] || exit 1
exit 0
