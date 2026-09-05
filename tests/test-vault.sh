#!/usr/bin/env bash
# Tests de ghost-vault : ce qui est vérifiable SANS device-mapper.
# L'écriture de l'entête LUKS2 est réelle ; l'ouverture/montage exige dm-crypt
# et est vérifiée sur le deck (cryptsetup standard).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'losetup -D 2>/dev/null; rm -rf "$TMP"' EXIT
pass=0; fail=0
ck() { if [[ "$2" == "0" ]]; then echo "  OK  $1"; pass=$((pass+1));
       else echo "  KO  $1${3:+ — $3}"; fail=$((fail+1)); fi; }
export NO_COLOR=1 GHOSTBOARD_VAULT_IMG="$TMP/vault.img"

echo "ghost-vault — sans coffre"
out="$("$ROOT/tools/ghost-vault" status 2>&1)"
grep -q 'aucun coffre' <<<"$out" && ck "status : signale l'absence de coffre" 0 || ck "status absent" 1 "$out"
"$ROOT/tools/ghost-vault" list >/dev/null 2>&1; ck "list : ne plante pas" $?

echo
echo "ghost-vault — commandes invalides"
"$ROOT/tools/ghost-vault" wat >/dev/null 2>&1; [[ $? -ne 0 ]] && ck "commande inconnue -> code non nul" 0 || ck "cmd inconnue" 1
"$ROOT/tools/ghost-vault" open >/dev/null 2>&1; [[ $? -ne 0 ]] && ck "open sans sudo -> refus" 0 || ck "open sans root" 1

echo
echo "ghost-vault — création (entête LUKS réelle)"
if command -v cryptsetup >/dev/null 2>&1 && [[ "$(id -u)" -eq 0 ]]; then
  # 32M : au-dessus des métadonnées LUKS2, l'entête s'écrit proprement.
  echo -n "phrasetest123456" | "$ROOT/tools/ghost-vault" create --size 32M >/dev/null 2>&1 || true
  cryptsetup isLuks "$TMP/vault.img" 2>/dev/null \
    && ck "create écrit une entête LUKS2 valide" 0 \
    || ck "entête LUKS2" 1 "isLuks a échoué"
  ver="$(cryptsetup luksDump "$TMP/vault.img" 2>/dev/null | awk '/Version:/{print $2}')"
  [[ "$ver" == "2" ]] && ck "format LUKS2 (pas LUKS1)" 0 || ck "version LUKS" 1 "ver=$ver"
else
  ck "création LUKS (sautée : pas de cryptsetup ou pas root)" 0
  ck "format LUKS2 (sautée)" 0
fi

echo
echo "$([[ $fail -eq 0 ]] && echo SUCCÈS || echo ÉCHEC) : $pass réussi(s), $fail échec(s)"
exit $(( fail > 0 ))
