"""
bridge.py — adaptateur entre `auditkit` (le scanner) et la TUI GHOSTBOARD.

C'est LE point de couplage, et le seul. La TUI ne connaît qu'un modèle
d'affichage stable (`GhostFinding`, `Severity`, `MODULES`) ; ce fichier le
relie à l'outil réel.

--------------------------------------------------------------------------
  CE QUE LE PONT ATTEND D'`auditkit`  (les « coutures » à câbler)
--------------------------------------------------------------------------
Le pont tente de découvrir automatiquement, dans cet ordre :

  1. un fichier `ghostboard_hooks.py` posé à côté de camera_audit.py, exportant
     des callables explicites  → PRIORITAIRE, c'est le câblage propre ;
  2. des noms usuels dans le paquet `auditkit` (Finding, run_audit, load_scope…).

Si rien n'est trouvé, le pont bascule sur un backend de DÉMONSTRATION, et la
TUI l'affiche EN CLAIR (bandeau « DEMO »). Sur un outil de sécurité, une donnée
simulée ne doit jamais pouvoir passer pour un vrai constat.

Les quatre coutures, si tu dois les câbler à la main dans ghostboard_hooks.py :

    def load_scope() -> list[str]:
        '''CIDR/hôtes autorisés. La barrière de périmètre d'auditkit.'''

    def iter_findings(targets, emit) -> None:
        '''Lance les 6 modules sur `targets`. Pour CHAQUE événement, appelle
        emit(Event(...)). NE PAS réimplémenter le scan ici : appeler auditkit.'''

    def load_last_findings() -> list        # constats du dernier run (objets Finding)
    def generate_report(findings, path)     # (ré)génère le rapport HTML

`normalize(finding)` ci-dessous transforme UN objet Finding d'auditkit en
GhostFinding. Elle est tolérante : attributs OU clés de dict, plusieurs noms
de champs acceptés. Adapte-la si ton Finding est exotique — c'est le seul
endroit où le format d'auditkit est connu.
"""
from __future__ import annotations

import dataclasses
import enum
import importlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Callable, Iterable


# ---------------------------------------------------------------------------
#  Modèle d'affichage — stable, indépendant d'auditkit
# ---------------------------------------------------------------------------
class Severity(enum.IntEnum):
    """Ordonnée : un tri décroissant met les critiques en tête."""
    CRITICAL = 4
    HIGH = 3
    MEDIUM = 2
    INFO = 1

    @property
    def label(self) -> str:
        return {4: "CRITICAL", 3: "HIGH", 2: "MEDIUM", 1: "INFO"}[int(self)]

    @classmethod
    def coerce(cls, value) -> "Severity":
        """Accepte un enum, un entier, ou une chaîne (fr/en, casse libre)."""
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            return cls(max(1, min(4, value)))
        s = str(value).strip().lower()
        table = {
            "critical": cls.CRITICAL, "critique": cls.CRITICAL, "crit": cls.CRITICAL,
            "high": cls.HIGH, "élevée": cls.HIGH, "elevee": cls.HIGH, "haute": cls.HIGH,
            "medium": cls.MEDIUM, "moyenne": cls.MEDIUM, "med": cls.MEDIUM,
            "info": cls.INFO, "informational": cls.INFO, "low": cls.INFO,
            "informatif": cls.INFO,
        }
        return table.get(s, cls.INFO)


# Les 6 modules, dans l'ordre d'enchaînement de l'outil. La clé est stable ;
# le libellé est affiché.
MODULES: list[tuple[str, str]] = [
    ("discovery", "Discovery · nmap"),
    ("rtsp", "RTSP · Cameradar"),
    ("onvif", "ONVIF"),
    ("snapshots", "Snapshots"),
    ("creds", "Default creds"),
    ("cve", "CVE cross-ref"),
]
MODULE_KEYS = [k for k, _ in MODULES]
MODULE_LABEL = dict(MODULES)


@dataclasses.dataclass(slots=True)
class GhostFinding:
    """Ce que la TUI affiche. Produit par `normalize()` depuis un Finding."""
    severity: Severity
    title: str
    target: str = ""
    module: str = ""
    detail: str = ""
    cve: str = ""
    evidence: str = ""

    @property
    def module_label(self) -> str:
        return MODULE_LABEL.get(self.module, self.module or "—")


@dataclasses.dataclass(slots=True)
class Event:
    """Émis pendant un run. `kind` ∈ {module_start, finding, module_done,
    log, error, done}."""
    kind: str
    module: str = ""
    finding: "GhostFinding | None" = None
    message: str = ""


# ---------------------------------------------------------------------------
#  Normalisation d'un Finding d'auditkit -> GhostFinding
# ---------------------------------------------------------------------------
def _get(obj, *names, default=""):
    """Lit un attribut OU une clé de dict, en essayant plusieurs noms."""
    for n in names:
        if isinstance(obj, dict):
            if n in obj and obj[n] not in (None, ""):
                return obj[n]
        else:
            v = getattr(obj, n, None)
            if v not in (None, ""):
                return v
    return default


def normalize(finding) -> GhostFinding:
    """Un Finding d'auditkit -> GhostFinding. Tolérante aux variations de noms.

    Le seul endroit du pont qui connaît la forme d'auditkit. Si ton Finding
    utilise d'autres noms de champs, ajoute-les aux tuples ci-dessous."""
    sev = _get(finding, "severity", "sev", "level", "risk", default="info")
    return GhostFinding(
        severity=Severity.coerce(sev),
        title=str(_get(finding, "title", "name", "summary", "issue",
                       default="(sans titre)")),
        target=str(_get(finding, "target", "host", "ip", "address", "endpoint")),
        module=str(_get(finding, "module", "source", "category", "check")).lower(),
        detail=str(_get(finding, "detail", "description", "details", "message",
                        "info")),
        cve=str(_get(finding, "cve", "cve_id", "cveid", "reference")),
        evidence=str(_get(finding, "evidence", "proof", "data", "raw")),
    )


# ---------------------------------------------------------------------------
#  Découverte d'auditkit
# ---------------------------------------------------------------------------
class Backend:
    """Ce que la TUI consomme. Deux implémentations : réelle et démo."""
    is_demo: bool = False
    source: str = "?"

    def scope(self) -> list[str]:
        raise NotImplementedError

    def last_findings(self) -> list[GhostFinding]:
        raise NotImplementedError

    def run(self, targets: list[str], emit: Callable[[Event], None]) -> None:
        raise NotImplementedError

    def make_report(self, findings: list[GhostFinding], out: Path) -> Path:
        raise NotImplementedError


def _load_hooks_module():
    """Cherche ghostboard_hooks.py à côté de camera_audit.py, ou via
    GHOSTBOARD_AUDITKIT_HOOKS."""
    explicit = os.environ.get("GHOSTBOARD_AUDITKIT_HOOKS")
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    # racine du projet camera-audit : deux niveaux au-dessus de ce fichier
    root = Path(__file__).resolve().parent.parent
    candidates += [root / "ghostboard_hooks.py", root / "auditkit" / "ghostboard_hooks.py"]
    for c in candidates:
        if c and c.is_file():
            spec = importlib.util.spec_from_file_location("ghostboard_hooks", c)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            return mod, str(c)
    return None, ""


def _try_import_auditkit():
    try:
        return importlib.import_module("auditkit")
    except Exception:
        return None


class RealBackend(Backend):
    """Relie la TUI aux callables réels. Ne fait AUCUN scan lui-même."""

    def __init__(self, hooks, source: str):
        self._h = hooks
        self.source = source
        self.is_demo = False

    def scope(self) -> list[str]:
        fn = getattr(self._h, "load_scope", None)
        try:
            return list(fn()) if fn else []
        except Exception:
            return []

    def last_findings(self) -> list[GhostFinding]:
        fn = getattr(self._h, "load_last_findings", None)
        if not fn:
            return []
        try:
            return [normalize(f) for f in fn()]
        except Exception:
            return []

    def run(self, targets, emit):
        fn = getattr(self._h, "iter_findings", None)
        if not fn:
            emit(Event("error", message="ghostboard_hooks.iter_findings absent — "
                       "impossible de lancer un vrai scan. Voir bridge.py."))
            emit(Event("done"))
            return
        # On enveloppe l'emit pour normaliser tout Finding qui remonterait brut.
        def wrapped(ev):
            if isinstance(ev, Event):
                emit(ev)
            else:  # tolérance : un hook simple peut émettre un Finding nu
                emit(Event("finding", finding=normalize(ev)))
        fn(list(targets), wrapped)

    def make_report(self, findings, out: Path) -> Path:
        fn = getattr(self._h, "generate_report", None)
        if fn:
            try:
                res = fn([f for f in findings], out)
                return Path(res) if res else out
            except Exception:
                pass
        return _demo_report(findings, out)


def get_backend() -> Backend:
    """Backend réel si auditkit/hooks sont là, sinon démo (étiquetée)."""
    hooks, path = _load_hooks_module()
    if hooks and any(hasattr(hooks, n) for n in ("iter_findings", "load_scope")):
        return RealBackend(hooks, f"ghostboard_hooks.py ({path})")
    ak = _try_import_auditkit()
    if ak and any(hasattr(ak, n) for n in ("iter_findings", "run_audit", "load_scope")):
        # auditkit expose directement les coutures : on l'utilise tel quel.
        return RealBackend(ak, "auditkit")
    return DemoBackend()


# ---------------------------------------------------------------------------
#  Backend de démonstration — clairement étiqueté
# ---------------------------------------------------------------------------
_DEMO_FINDINGS = [
    GhostFinding(Severity.CRITICAL, "RTSP stream exposed without authentication",
                 "192.168.1.42", "rtsp",
                 "Cameradar opened rtsp://192.168.1.42:554/Streaming/Channels/101 "
                 "with no credentials. Live video is world-readable on this segment.",
                 evidence="route=/Streaming/Channels/101  auth=none"),
    GhostFinding(Severity.CRITICAL, "Default credentials accepted (admin/admin)",
                 "192.168.1.51", "creds",
                 "ONVIF device authenticated with a factory default pair. Full PTZ "
                 "and configuration access.", cve="", evidence="admin:admin -> 200 OK"),
    GhostFinding(Severity.HIGH, "ONVIF device information disclosure",
                 "192.168.1.51", "onvif",
                 "GetDeviceInformation returned model, firmware and serial without "
                 "auth — useful for CVE targeting.",
                 evidence="model=DS-2CD2042 fw=V5.4.5"),
    GhostFinding(Severity.HIGH, "Firmware matches known CVE (informational)",
                 "192.168.1.51", "cve",
                 "Firmware V5.4.5 is referenced by a public advisory. Cross-ref is "
                 "INFORMATIONAL — not verified against this device.",
                 cve="CVE-2017-7921",
                 evidence="source=local CVE map, no active exploitation attempted"),
    GhostFinding(Severity.MEDIUM, "Snapshot endpoint reachable",
                 "192.168.1.42", "snapshots",
                 "HTTP snapshot URL returned a JPEG without a session. Confirms the "
                 "stream and leaks the camera's field of view.",
                 evidence="GET /onvif-http/snapshot -> image/jpeg 200"),
    GhostFinding(Severity.MEDIUM, "Telnet port open",
                 "192.168.1.60", "discovery",
                 "nmap found 23/tcp open. Legacy management surface.",
                 evidence="23/tcp open telnet"),
    GhostFinding(Severity.INFO, "Host up, 2 ports open",
                 "192.168.1.42", "discovery",
                 "nmap host discovery: 554/tcp, 80/tcp.",
                 evidence="554/tcp open rtsp · 80/tcp open http"),
]


class DemoBackend(Backend):
    is_demo = True
    source = "DEMO (auditkit introuvable)"

    def scope(self) -> list[str]:
        # Périmètre de démonstration : un /24 privé. Sur le deck, auditkit
        # fournit le vrai périmètre.
        return ["192.168.1.0/24"]

    def last_findings(self) -> list[GhostFinding]:
        return list(_DEMO_FINDINGS)

    def run(self, targets, emit):
        import random
        import time
        for key, _label in MODULES:
            emit(Event("module_start", module=key))
            time.sleep(0.25)  # simulate work; la vraie durée vient d'auditkit
            for f in _DEMO_FINDINGS:
                if f.module == key:
                    emit(Event("finding", module=key, finding=f))
                    time.sleep(0.12)
            emit(Event("module_done", module=key))
        emit(Event("done", message="DEMO terminé — aucun réseau n'a été scanné."))

    def make_report(self, findings, out: Path) -> Path:
        return _demo_report(findings, out)


def _demo_report(findings: list[GhostFinding], out: Path) -> Path:
    """Rapport HTML minimal, aux couleurs GHOSTBOARD. Sert de repli quand
    auditkit n'expose pas son propre générateur."""
    from . import theme
    pal = theme.load_palette()
    rows = []
    order = {4: "critical", 3: "high", 2: "medium", 1: "info"}
    for f in sorted(findings, key=lambda x: -int(x.severity)):
        sev = order[int(f.severity)]
        rows.append(
            f'<tr class="{sev}"><td class="sev">{f.severity.label}</td>'
            f'<td>{_esc(f.title)}</td><td class="mono">{_esc(f.target)}</td>'
            f'<td>{_esc(f.module_label)}</td><td>{_esc(f.detail)}'
            + (f'<div class="ev">{_esc(f.evidence)}</div>' if f.evidence else "")
            + (f'<div class="cve">{_esc(f.cve)}</div>' if f.cve else "")
            + "</td></tr>")
    html = _REPORT_HTML.format(
        bg=pal["bg"], panel=pal["panel"], sep=pal["separator"], accent=pal["accent"],
        text=pal["text"], dim=pal["text_dim"],
        crit=pal["sev_critical"], high=pal["sev_high"],
        med=pal["sev_medium"], info=pal["sev_info"],
        n=len(findings), rows="\n".join(rows) or
        '<tr><td colspan="5" class="mono">Aucun constat.</td></tr>')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


_REPORT_HTML = """<!doctype html><html lang="en"><meta charset="utf-8">
<title>GHOSTBOARD RECON — Camera Audit</title>
<style>
 :root {{ color-scheme: dark; }}
 body {{ margin:0; background:{bg}; color:{text};
   font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:14px; line-height:1.55; }}
 header {{ padding:22px 26px; border-bottom:1px solid {sep}; }}
 h1 {{ margin:0; font-size:20px; letter-spacing:3px; color:{accent}; font-weight:600; }}
 .sub {{ color:{dim}; font-size:12px; letter-spacing:2px; margin-top:6px; }}
 table {{ border-collapse:collapse; width:100%; }}
 th,td {{ text-align:left; padding:10px 14px; border-bottom:1px solid {sep};
   vertical-align:top; }}
 th {{ font-size:10px; letter-spacing:2px; text-transform:uppercase; color:{dim}; }}
 td.sev {{ font-weight:700; white-space:nowrap; }}
 tr.critical td.sev {{ color:{crit}; }} tr.high td.sev {{ color:{high}; }}
 tr.medium td.sev {{ color:{med}; }} tr.info td.sev {{ color:{info}; }}
 .mono {{ font-variant-numeric:tabular-nums; color:{dim}; }}
 .ev {{ color:{dim}; font-size:12px; margin-top:5px; }}
 .cve {{ color:{high}; font-size:12px; margin-top:4px; }}
 tr.critical td:nth-child(2) {{ box-shadow: inset 3px 0 {crit}; }}
 tr.high td:nth-child(2) {{ box-shadow: inset 3px 0 {high}; }}
</style>
<header><h1>GHOSTBOARD · RECON</h1>
<div class="sub">CAMERA AUDIT — {n} FINDINGS · CUSTOM HARDWARE. READY TO EXPLORE.</div></header>
<table><thead><tr><th>Severity</th><th>Finding</th><th>Target</th><th>Module</th>
<th>Detail</th></tr></thead><tbody>
{rows}
</tbody></table></html>"""
