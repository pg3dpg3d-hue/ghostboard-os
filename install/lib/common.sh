# ============================================================================
#  GHOSTBOARD OS — bibliothèque commune aux étapes d'installation
#  Sourcé par ghostboard-install.sh et par chaque étape. Pas exécutable seul.
# ============================================================================
# shellcheck shell=bash

GHOSTBOARD_REPO="${GHOSTBOARD_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
GHOSTBOARD_SHARE="${GHOSTBOARD_SHARE:-/usr/share/ghostboard}"
GHOSTBOARD_STATE="${GHOSTBOARD_STATE:-/var/lib/ghostboard}"
GHOSTBOARD_STAMPS="$GHOSTBOARD_STATE/steps"
GHOSTBOARD_BACKUP="$GHOSTBOARD_STATE/backups"
GHOSTBOARD_LOG="${GHOSTBOARD_LOG:-/var/log/ghostboard-install.log}"

# Compte cible : celui qui utilise le deck, pas root. `sudo` le renseigne.
GHOSTBOARD_USER="${GHOSTBOARD_USER:-${SUDO_USER:-${USER:-$(id -un)}}}"
GHOSTBOARD_HOME="$(getent passwd "$GHOSTBOARD_USER" 2>/dev/null | cut -d: -f6)"
GHOSTBOARD_HOME="${GHOSTBOARD_HOME:-$HOME}"

DRY_RUN="${DRY_RUN:-0}"
ASSUME_YES="${ASSUME_YES:-0}"

# ---- couleurs (palette de la marque, repli si non installée) ---------------
_hex() { local h="${1#\#}"; printf '\033[38;2;%d;%d;%dm' "0x${h:0:2}" "0x${h:2:2}" "0x${h:4:2}"; }
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  C_ACCENT="$(_hex A855F7)"; C_INPUT="$(_hex FF4D8D)"
  C_DIM="$(_hex 6E6880)";    C_TEXT="$(_hex D6D2E0)"; C_OFF=$'\033[0m'
else
  C_ACCENT=""; C_INPUT=""; C_DIM=""; C_TEXT=""; C_OFF=""
fi

_ts() { date '+%Y-%m-%d %H:%M:%S'; }
_journal() { printf '%s %s\n' "$(_ts)" "$*" >> "$GHOSTBOARD_LOG" 2>/dev/null || true; }

say()   { printf '%s%s%s\n'      "$C_TEXT"   "$*" "$C_OFF"; _journal "$*"; }
step()  { printf '\n%s── %s%s\n' "$C_ACCENT" "$*" "$C_OFF"; _journal "== $*"; }
info()  { printf '   %s%s%s\n'   "$C_DIM"    "$*" "$C_OFF"; _journal "   $*"; }
good()  {
  # En mode à blanc, ne jamais annoncer une action comme faite : l'installateur
  # doit pouvoir être lu sans se demander ce qui a réellement été écrit.
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '   %s[à blanc]%s %s\n' "$C_DIM" "$C_OFF" "$*"
  else
    printf '   %s✓%s %s\n' "$C_ACCENT" "$C_OFF" "$*"
  fi
  _journal " ok $*"
}
warn()  { printf '   %s!%s %s\n' "$C_INPUT"  "$C_OFF" "$*"; _journal " !! $*"; }
die()   { printf '\n%serreur :%s %s\n' "$C_INPUT" "$C_OFF" "$*" >&2; _journal "ERREUR $*"; exit 1; }

need_root() {
  [[ "$(id -u)" -eq 0 ]] || die "cette étape doit être lancée avec sudo"
}

# ---- confirmation ----------------------------------------------------------
# Toute opération lourde ou risquée passe par ici. --yes la court-circuite,
# mais il faut l'avoir demandé explicitement.
confirm() {
  local prompt="$1"
  [[ "$ASSUME_YES" == "1" ]] && { info "$prompt -> oui (--yes)"; return 0; }
  local reply
  printf '   %s%s%s [o/N] ' "$C_INPUT" "$prompt" "$C_OFF"
  read -r reply </dev/tty || return 1
  [[ "$reply" =~ ^[oOyY]$ ]]
}

# ---- exécution -------------------------------------------------------------
run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '   %s[à blanc]%s %s\n' "$C_DIM" "$C_OFF" "$*"
    return 0
  fi
  _journal "\$ $*"
  "$@"
}

# ---- jalons d'idempotence --------------------------------------------------
stamp_path()  { printf '%s/%s' "$GHOSTBOARD_STAMPS" "$1"; }
has_stamp()   { [[ -f "$(stamp_path "$1")" ]]; }
set_stamp()   { mkdir -p "$GHOSTBOARD_STAMPS"; date -Is > "$(stamp_path "$1")"; }
clear_stamp() { rm -f "$(stamp_path "$1")"; }

# ---- prérequis entre étapes ------------------------------------------------
# En exécution réelle, une étape sensible refuse de démarrer sans son prérequis.
# En mode à blanc, elle se contente de le SIGNALER : sinon `--dry-run` ne peut
# pas montrer le plan complet sur une machine neuve, ce qui est précisément le
# moment où on veut le lire.
require_step() { # nom_étape raison
  local step="$1" why="${2:-}"
  has_stamp "$step" && return 0
  if [[ "$DRY_RUN" == "1" ]]; then
    warn "[à blanc] prérequis non satisfait : $step${why:+ ($why)}"
    return 0
  fi
  die "lance d'abord : sudo ./install/ghostboard-install.sh --step $step${why:+
  ($why)}"
}

# ---- paquets ---------------------------------------------------------------
apt_install() {
  local missing=()
  for pkg in "$@"; do
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q '^install ok installed$' \
      || missing+=("$pkg")
  done
  if [[ ${#missing[@]} -eq 0 ]]; then
    info "déjà installé : $*"
    return 0
  fi
  info "installation : ${missing[*]}"
  run env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing[@]}" \
    || die "échec de l'installation de : ${missing[*]}"
}

apt_refresh() {
  # Une fois par exécution suffit : les étapes s'enchaînent en quelques minutes.
  [[ -n "${_APT_REFRESHED:-}" ]] && return 0
  info "mise à jour de l'index des paquets"
  run env DEBIAN_FRONTEND=noninteractive apt-get update -qq || die "apt-get update a échoué"
  _APT_REFRESHED=1
}

# ---- fichiers --------------------------------------------------------------
# Toute écriture système passe par ici : sauvegarde horodatée avant écrasement,
# et rien n'est réécrit si le contenu est déjà identique (idempotence).
backup_file() {
  local f="$1"
  [[ -e "$f" ]] || return 0
  local dst="$GHOSTBOARD_BACKUP/$(date +%Y%m%d-%H%M%S)$(printf '%s' "$f" | tr '/' '_')"
  [[ "$DRY_RUN" == "1" ]] && { info "[à blanc] sauvegarderait $f"; return 0; }
  mkdir -p "$GHOSTBOARD_BACKUP"
  run cp -a "$f" "$dst" && info "sauvegarde : $f -> $dst"
}

install_file() { # source destination [mode]
  local src="$1" dst="$2" mode="${3:-0644}"
  [[ -f "$src" ]] || die "fichier source absent : $src"
  if [[ -f "$dst" ]] && cmp -s "$src" "$dst"; then
    info "à jour : $dst"
    return 0
  fi
  backup_file "$dst"
  run install -D -m "$mode" "$src" "$dst" && good "écrit : $dst"
}

# Écrit un fichier depuis stdin, avec les mêmes garanties qu'install_file.
write_file() { # destination [mode]
  local dst="$1" mode="${2:-0644}" tmp
  tmp="$(mktemp)"
  cat > "$tmp"
  if [[ -f "$dst" ]] && cmp -s "$tmp" "$dst"; then
    info "à jour : $dst"; rm -f "$tmp"; return 0
  fi
  backup_file "$dst"
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '   %s[à blanc]%s écrirait %s (%s lignes)\n' "$C_DIM" "$C_OFF" "$dst" "$(wc -l < "$tmp")"
    rm -f "$tmp"; return 0
  fi
  install -D -m "$mode" "$tmp" "$dst" && good "écrit : $dst"
  rm -f "$tmp"
}

# Exécute une commande en tant qu'utilisateur du deck (et non root).
as_user() {
  if [[ "$(id -u)" -eq 0 && "$GHOSTBOARD_USER" != "root" ]]; then
    run sudo -u "$GHOSTBOARD_USER" -H "$@"
  else
    run "$@"
  fi
}

# ---- matériel --------------------------------------------------------------
is_intel_n100() { grep -qi 'N100' /proc/cpuinfo 2>/dev/null; }
ram_gb()        { awk '/MemTotal/{printf "%.0f", $2/1024/1024}' /proc/meminfo; }
has_nvme()      { lsblk -dno NAME,ROTA 2>/dev/null | awk '$2==0' | grep -q nvme; }
root_device()   { findmnt -no SOURCE / 2>/dev/null; }
