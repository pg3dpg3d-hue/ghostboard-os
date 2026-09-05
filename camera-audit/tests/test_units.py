#!/usr/bin/env python3
"""
Tests unitaires du module RECON — sans Textual, exécutables partout.

Couvre ce qui doit être juste quoi qu'il arrive : la barrière de périmètre
(une cible hors scope NE DOIT PAS partir au scan), la normalisation d'un
Finding d'auditkit, et le tri par sévérité.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ghostboard import bridge, scope  # noqa: E402

_p = _f = 0


def ck(label, cond):
    global _p, _f
    if cond:
        print("  OK  " + label); _p += 1
    else:
        print("  KO  " + label); _f += 1


print("Barrière de périmètre")
SC = ["192.168.1.0/24", "10.0.0.5"]
ck("IP in scope autorisée", scope.check_target("192.168.1.42", SC).ok)
ck("IP:port in scope autorisée", scope.check_target("192.168.1.42:554", SC).ok)
ck("IP hôte unique autorisée", scope.check_target("10.0.0.5", SC).ok)
ck("CIDR ⊆ périmètre autorisé", scope.check_target("192.168.1.0/24", SC).ok)
ck("IP hors scope REFUSÉE", not scope.check_target("8.8.8.8", SC).ok)
ck("autre sous-réseau REFUSÉ", not scope.check_target("192.168.2.10", SC).ok)
ck("CIDR plus large REFUSÉ", not scope.check_target("192.168.0.0/16", SC).ok)
ck("périmètre vide -> tout REFUSÉ", not scope.check_target("192.168.1.42", []).ok)
allowed, checks = scope.filter_targets(["192.168.1.5", "8.8.8.8", "10.0.0.5"], SC)
ck("filter_targets ne garde que l'autorisé", allowed == ["192.168.1.5", "10.0.0.5"])

print("\nCoercition de sévérité")
ck("'critique' -> CRITICAL", bridge.Severity.coerce("critique") == bridge.Severity.CRITICAL)
ck("'High' -> HIGH", bridge.Severity.coerce("High") == bridge.Severity.HIGH)
ck("'moyenne' -> MEDIUM", bridge.Severity.coerce("moyenne") == bridge.Severity.MEDIUM)
ck("entier 4 -> CRITICAL", bridge.Severity.coerce(4) == bridge.Severity.CRITICAL)
ck("inconnu -> INFO (défaut sûr)", bridge.Severity.coerce("???") == bridge.Severity.INFO)
ck("ordre : CRITICAL > HIGH > MEDIUM > INFO",
   bridge.Severity.CRITICAL > bridge.Severity.HIGH > bridge.Severity.MEDIUM
   > bridge.Severity.INFO)

print("\nNormalisation d'un Finding d'auditkit")
# objet à attributs
class F:
    severity = "élevée"; title = "ONVIF leak"; host = "192.168.1.51"
    check = "ONVIF"; description = "info disclosure"; cve_id = "CVE-2017-7921"
g = bridge.normalize(F())
ck("attribut severity fr -> HIGH", g.severity == bridge.Severity.HIGH)
ck("champ host -> target", g.target == "192.168.1.51")
ck("champ check -> module", g.module == "onvif")
ck("champ cve_id -> cve", g.cve == "CVE-2017-7921")
# dict
gd = bridge.normalize({"severity": "critical", "title": "x", "ip": "1.2.3.4",
                       "source": "rtsp", "details": "y"})
ck("dict normalisé", gd.severity == bridge.Severity.CRITICAL and gd.target == "1.2.3.4")
ck("module inconnu -> libellé brut", bridge.normalize({"module": "weird"}).module_label == "weird")
ck("module connu -> libellé", gd.module_label == "RTSP · Cameradar")

print("\nBackend démo")
be = bridge.get_backend()
ck("sans auditkit -> démo", be.is_demo)
ck("démo : périmètre non vide", len(be.scope()) >= 1)
fs = be.last_findings()
ck("démo : 7 findings", len(fs) == 7)
ck("démo : au moins 2 critiques",
   sum(1 for f in fs if f.severity == bridge.Severity.CRITICAL) >= 2)
ordered = sorted(fs, key=lambda f: -int(f.severity))
ck("tri décroissant met un CRITICAL en tête",
   ordered[0].severity == bridge.Severity.CRITICAL)

# run() émet bien les 6 modules + done
evs = []
be.run(["192.168.1.0/24"], evs.append)
starts = [e.module for e in evs if e.kind == "module_start"]
ck("run émet les 6 modules dans l'ordre", starts == bridge.MODULE_KEYS)
ck("run se termine par 'done'", evs[-1].kind == "done")

print("\nRapport HTML (repli)")
import tempfile
out = Path(tempfile.mkdtemp()) / "r.html"
be.make_report(fs, out)
html = out.read_text(encoding="utf-8")
ck("rapport écrit", out.exists() and len(html) > 500)
ck("titre GHOSTBOARD", "GHOSTBOARD" in html)
ck("couleur critique de la palette présente", "#FF4D8D" in html)
ck("CVE listée", "CVE-2017-7921" in html)

print(f"\n{'SUCCÈS' if _f == 0 else 'ÉCHEC'} : {_p} réussi(s), {_f} échec(s)")
sys.exit(1 if _f else 0)
