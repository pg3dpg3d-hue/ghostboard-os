#!/usr/bin/env bash
# ============================================================================
#  GHOSTBOARD OS — installateur
# ============================================================================
#  Debian 13 minimale  ->  cyberdeck GHOSTBOARD complet.
#
#      sudo ./install/ghostboard-install.sh --list
#      sudo ./install/ghostboard-install.sh                 # tout, dans l'ordre
#      sudo ./install/ghostboard-install.sh --step 50-theme # une seule étape
#      sudo ./install/ghostboard-install.sh --from 60-nodejs-claude-code
#      sudo ./install/ghostboard-install.sh --dry-run       # ne touche à rien
#
#  Chaque étape est idempotente : la relancer ne casse rien et ne refait que
#  ce qui manque. Un jalon dans /var/lib/ghostboard/steps note ce qui est fait ;
#  --force le contourne.
#
#  Les étapes qui touchent l'affichage, le bootloader ou le gestionnaire de
#  session DEMANDENT confirmation. Elles refusent de démarrer si l'étape de
#  contrôle préalable (00-preflight) n'est pas passée : sans accès SSH de
#  secours, perdre l'écran, c'est perdre la machine.
# ============================================================================
set -uo pipefail

# L'ancien parcours configure GRUB et l'énergie Intel. Refuser sur Raspberry Pi.
if [[ -f /proc/device-tree/model ]] && grep -aq 'Raspberry Pi' /proc/device-tree/model; then
  echo 'Raspberry Pi détecté : utiliser sudo bash install/ghostboard-pi5.sh --profile full' >&2
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$HERE/lib/common.sh"

STEPS_DIR="$HERE/steps"
ONLY=""; FROM=""; FORCE=0; LIST=0

usage() { sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --step)     ONLY="${2:-}"; shift 2 ;;
    --from)     FROM="${2:-}"; shift 2 ;;
    --list)     LIST=1; shift ;;
    --force)    FORCE=1; shift ;;
    --dry-run)  DRY_RUN=1; export DRY_RUN; shift ;;
    --yes|-y)   ASSUME_YES=1; export ASSUME_YES; shift ;;
    --user)     GHOSTBOARD_USER="${2:-}"; export GHOSTBOARD_USER; shift 2 ;;
    -h|--help)  usage; exit 0 ;;
    *)          die "option inconnue : $1  (--help pour l'aide)" ;;
  esac
done

mapfile -t ALL_STEPS < <(find "$STEPS_DIR" -maxdepth 1 -name '*.sh' -printf '%f\n' | sort)
[[ ${#ALL_STEPS[@]} -gt 0 ]] || die "aucune étape trouvée dans $STEPS_DIR"

if [[ "$LIST" == "1" ]]; then
  printf '\n%sÉtapes d'\''installation de GHOSTBOARD OS%s\n\n' "$C_ACCENT" "$C_OFF"
  for s in "${ALL_STEPS[@]}"; do
    name="${s%.sh}"
    desc="$(sed -n 's/^# DESCRIPTION: //p' "$STEPS_DIR/$s" | head -1)"
    state="$(has_stamp "$name" && printf 'fait' || printf '—')"
    printf '  %s%-26s%s %-4s %s%s%s\n' "$C_TEXT" "$name" "$C_OFF" "$state" "$C_DIM" "$desc" "$C_OFF"
  done
  printf '\n'
  exit 0
fi

need_root
mkdir -p "$GHOSTBOARD_STATE" "$GHOSTBOARD_STAMPS" "$GHOSTBOARD_BACKUP"
touch "$GHOSTBOARD_LOG" 2>/dev/null || true

printf '\n%s  GHOSTBOARD OS%s  %sinstallateur%s\n' "$C_ACCENT" "$C_OFF" "$C_DIM" "$C_OFF"
info "dépôt        $GHOSTBOARD_REPO"
info "utilisateur  $GHOSTBOARD_USER  ($GHOSTBOARD_HOME)"
info "journal      $GHOSTBOARD_LOG"
[[ "$DRY_RUN" == "1" ]] && warn "mode à blanc : aucune modification ne sera écrite"

selected=(); started=0
for s in "${ALL_STEPS[@]}"; do
  name="${s%.sh}"
  if [[ -n "$ONLY" ]]; then
    [[ "$name" == "$ONLY" ]] && selected+=("$s")
  elif [[ -n "$FROM" ]]; then
    [[ "$name" == "$FROM" ]] && started=1
    [[ "$started" == "1" ]] && selected+=("$s")
  else
    selected+=("$s")
  fi
done
[[ ${#selected[@]} -gt 0 ]] || die "aucune étape ne correspond (--list pour voir les noms)"

failed=()
for s in "${selected[@]}"; do
  name="${s%.sh}"
  if has_stamp "$name" && [[ "$FORCE" != "1" ]]; then
    step "$name"; info "déjà faite (--force pour rejouer)"
    continue
  fi
  step "$name"
  # Chaque étape tourne dans son propre bash : une étape qui meurt n'emporte
  # pas l'installateur, et on peut reprendre là où ça a cassé.
  if GHOSTBOARD_REPO="$GHOSTBOARD_REPO" GHOSTBOARD_USER="$GHOSTBOARD_USER" \
     DRY_RUN="$DRY_RUN" ASSUME_YES="$ASSUME_YES" \
     bash "$STEPS_DIR/$s"; then
    [[ "$DRY_RUN" == "1" ]] || set_stamp "$name"
  else
    rc=$?
    if [[ "$rc" -eq 75 ]]; then
      warn "étape ignorée volontairement"       # EX_TEMPFAIL = « sautée »
    else
      warn "ÉCHEC de $name (code $rc)"
      failed+=("$name")
    fi
  fi
done

printf '\n'
if [[ ${#failed[@]} -gt 0 ]]; then
  warn "étapes en échec : ${failed[*]}"
  info "journal complet : $GHOSTBOARD_LOG"
  info "reprendre avec : sudo $0 --from ${failed[0]}"
  exit 1
fi
say "  Installation terminée."
info "Prochaine étape : se déconnecter et choisir la session « GHOSTBOARD »."
info "Puis mesurer :   ghost-bench --markdown $GHOSTBOARD_REPO/BENCHMARKS.md"
printf '\n'
