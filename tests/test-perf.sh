#!/usr/bin/env bash
# Tests de ghost-perf et de la répartition mémoire de ghost-bench.
#
# Le test central est une NON-RÉGRESSION : la première version de ghost-perf
# détectait les services avec `pgrep -f`, qui compare la ligne de commande
# entière. N'importe quel shell mentionnant « tumblerd » se faisait compter
# comme une instance de tumblerd, et l'audit rapportait des services actifs qui
# n'existaient pas. Un audit qui ment est pire qu'aucun audit.
#
# Note de méthode : le JSON est passé par FICHIER, jamais par une chaîne en
# entrée standard. `python3 - <<'PY' ... PY <<<"$json"` place deux redirections
# sur stdin — la dernière l'emporte, Python lit alors le JSON comme son propre
# programme, et le test passe sans rien vérifier.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ck() { if [[ "$2" == "0" ]]; then echo "  OK  $1"; pass=$((pass+1));
       else echo "  KO  $1${3:+ — $3}"; fail=$((fail+1)); fi; }

export GHOSTBOARD_REPO="$ROOT"

echo "ghost-perf — structure"
./tools/ghost-perf --json > "$TMP/perf.json" 2>/dev/null; rc=$?
[[ "$rc" == "0" || "$rc" == "1" ]]; ck "code de sortie 0 ou 1 (pas de plantage)" $? "rc=$rc"
python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$TMP/perf.json" 2>/dev/null
ck "sortie JSON valide" $?

python3 - "$TMP/perf.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
rs = d["results"]
assert rs, "aucun contrôle exécuté"
assert d["pass"] + d["fail"] + d["skipped"] == len(rs), "compteurs incohérents"
for r in rs:
    assert r["status"] in ("PASS", "FAIL", "N/A"), r
    assert r["check"] and r["domain"] and r["detail"], r
    assert "contrôle en erreur" not in r["detail"], f"contrôle planté : {r}"
    if r["status"] == "FAIL":
        assert r["fix"], f"écart sans commande de correction : {r['check']}"
print(f"    {len(rs)} contrôles sur {len(set(r['domain'] for r in rs))} domaines")
PY
ck "contrôles complets, aucun planté, tout écart a sa correction" $?

python3 - "$TMP/perf.json" <<'PY'
import json, sys
noms = {r["check"] for r in json.load(open(sys.argv[1]))["results"]}
attendus = {"Temporisation GRUB", "initramfs", "Mode d'ouverture de session",
            "/tmp en RAM", "noatime sur /", "Ordonnanceur NVMe",
            "Gouverneur CPU", "Veille USB : entrées exclues",
            "Pont d'accessibilité", "Générateur de vignettes", "Démon Thunar",
            "Moniteurs de volumes", "Pilote d'affichage", "RAM au repos"}
manquants = attendus - noms
assert not manquants, f"contrôles absents : {sorted(manquants)}"
PY
ck "tous les domaines d'optimisation sont couverts" $?

echo
echo "ghost-perf — non-régression : faux positifs de détection de processus"
# Des processus dont la LIGNE DE COMMANDE contient le nom des services
# recherchés, sans être ces services. L'ancienne version les comptait.
pids=()
bash -c 'sleep 25 # tumblerd at-spi2-registryd gvfs-goa-volume-monitor gvfs-mtp-volume-monitor Thunar --daemon' \
  >/dev/null 2>&1 & pids+=($!)
bash -c 'sleep 25 # gvfs-afc-volume-monitor gvfs-gphoto2-volume-monitor' \
  >/dev/null 2>&1 & pids+=($!)
sleep 0.5

./tools/ghost-perf --json > "$TMP/leurre.json" 2>/dev/null
python3 - "$TMP/leurre.json" <<'PY'
import json, sys
by = {r["check"]: r for r in json.load(open(sys.argv[1]))["results"]}
suspects = {
    "Générateur de vignettes": "tumblerd",
    "Démon Thunar": "Thunar --daemon",
    "Moniteurs de volumes": "les moniteurs gvfs",
    "Pont d'accessibilité": "at-spi2-registryd",
}
for check, quoi in suspects.items():
    r = by[check]
    d = r["detail"].lower()
    assert "en cours d'exécution" not in d and "actifs" not in d, \
        f"FAUX POSITIF : « {check} » croit voir {quoi} -> {r['detail']}"
print("    aucun leurre pris pour un service réel")
PY
ck "les processus leurres ne sont pas comptés comme des services" $?
for p in "${pids[@]}"; do kill "$p" 2>/dev/null; done
wait 2>/dev/null

echo
echo "ghost-bench — répartition de la RAM"
./tools/ghost-bench --quick --json > "$TMP/bench.json" 2>/dev/null
python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$TMP/bench.json" 2>/dev/null
ck "sortie JSON valide" $?
python3 - "$TMP/bench.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
rb = d["ram_breakdown"]
assert rb["metric"] in ("PSS", "RSS"), rb
assert rb["top"], "aucune répartition produite"
assert all(r["mb"] >= 0 and r["process"] and r["count"] >= 1 for r in rb["top"]), rb["top"]
assert rb["top"] == sorted(rb["top"], key=lambda r: -r["mb"]), "répartition non triée"
mem = d["memory"]["idle_ram_mb"]
somme = sum(r["mb"] for r in rb["top"])
# En RSS la mémoire partagée est comptée plusieurs fois : on borne large, le
# but est d'attraper une erreur d'unité (Ko pris pour des Mo), pas d'ajuster.
assert somme <= mem * 5, f"répartition ({somme:.0f} Mo) incohérente avec le total ({mem} Mo)"
print(f"    métrique {rb['metric']}, {len(rb['top'])} entrées, tête : "
      f"{rb['top'][0]['process']} ({rb['top'][0]['mb']} Mo)")
PY
ck "répartition triée, cohérente avec la RAM totale" $?

echo
echo "$([[ $fail -eq 0 ]] && echo SUCCÈS || echo ÉCHEC) : $pass réussi(s), $fail échec(s)"
exit $(( fail > 0 ))
