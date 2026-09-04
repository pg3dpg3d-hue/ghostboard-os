#!/usr/bin/env bash
# DESCRIPTION: Audit et mesure — dernière étape, ne modifie rien
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

step "Audit des réglages"
info "Chaque optimisation est vérifiée sur le système VIVANT, pas supposée"
info "appliquée parce qu'un script est passé."
say ""
if [[ -x /usr/local/bin/ghost-perf ]]; then
  /usr/local/bin/ghost-perf || true
else
  warn "ghost-perf absent — relance l'étape 50-theme"
fi

step "Mesure"
say ""
if [[ -x /usr/local/bin/ghost-bench ]]; then
  /usr/local/bin/ghost-bench --quick || true
else
  warn "ghost-bench absent — relance l'étape 50-theme"
fi

say ""
warn "Ces chiffres sont pris AVANT redémarrage : ni GRUB, ni initramfs, ni le"
warn "mode de session ne sont encore en vigueur, et le temps de boot mesuré"
warn "est celui de l'ancienne configuration."
say ""
info "Après redémarrage, dans une session GHOSTBOARD :"
info "  ghost-perf                                    tout doit être au vert"
info "  ghost-bench --markdown $GHOSTBOARD_REPO/BENCHMARKS.md"
info "C'est cette dernière commande qui remplit le tableau de BENCHMARKS.md."
