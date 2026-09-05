# RECON › Camera Audit — module GHOSTBOARD OS

Couche d'intégration qui branche l'outil d'audit de caméras `auditkit` au
cyberdeck GHOSTBOARD : une TUI clavier pour la dalle 4 pouces, thémée comme le
reste de l'OS, avec rapport HTML servi sur Tailscale pour lecture sur grand
écran.

> **Ce dossier contient la couche d'intégration GHOSTBOARD.** La logique de
> scan (`auditkit`, `camera_audit.py`, la config YAML, le générateur de
> rapport) est TON outil et n'est pas réécrite ici. Le sous-paquet
> `ghostboard/` l'appelle via `ghostboard_hooks.py` (voir plus bas). Sans ce
> câblage, la TUI démarre quand même en mode **DEMO** (données simulées,
> clairement étiquetées) pour que tu puisses juger l'interface.

---

## Intégration deck

### Ce que ça ajoute

| Élément | Rôle |
| --- | --- |
| `ghostboard/` | La TUI Textual : accueil + périmètre, édition des cibles, run live des 6 modules, constats triés par sévérité, rapport HTML servi sur Tailscale |
| `ghostboard/bridge.py` | **Le seul point de couplage** avec `auditkit` : normalise ses `Finding`, lance les modules, sinon bascule en DEMO |
| `ghostboard/theme.py` | Source les couleurs depuis `brand/palette.toml` du dépôt — aucune couleur redéfinie |
| `ghostboard/scope.py` | Barrière de périmètre **côté TUI** : seconde porte, en plus de celle d'`auditkit` |
| `install.sh` | Dépendances système, venv, image Cameradar, groupe docker — idempotent |
| `bin/ghost-recon` | Lanceur (venv + `python -m ghostboard`) |
| `desktop/launchers/ghostboard-recon.desktop` | Entrée **RECON · Camera Audit** du menu GHOSTBOARD |

### Installation sur le deck

```bash
cd /opt/ghostboard-os/camera-audit
./install.sh            # nmap, ffmpeg, docker.io, python3-venv, venv, cameradar, groupe docker
# déconnexion / reconnexion (groupe docker), puis :
./bin/ghost-recon       # ou : menu démarrer › RECON · Camera Audit
```

`install.sh` vérifie chaque binaire et **journalise ce qui manque** dans
`install.log` sans s'arrêter : un module dont la dépendance manque reste
simplement indisponible. Relançable sans effet de bord.

L'installateur de l'OS (`install/steps/50-theme.sh`) pose déjà le lien
`ghost-recon` dans le PATH et le lanceur dans le menu ; `./install.sh` ne
s'occupe que des dépendances lourdes du module.

### Câbler ton auditkit (retirer le bandeau DEMO)

Le pont cherche `ghostboard_hooks.py` à côté de `camera_audit.py`. Copie le
modèle et remplis quatre fonctions qui **appellent ton code** — tu ne réécris
aucune logique de scan :

```bash
cp ghostboard_hooks.py.example ghostboard_hooks.py
$EDITOR ghostboard_hooks.py
```

```python
def load_scope() -> list[str]:          # le périmètre autorisé (CIDR/hôtes)
def iter_findings(targets, emit):       # lance les 6 modules, emit(finding | Event)
def load_last_findings() -> list:       # constats du dernier run (facultatif)
def generate_report(findings, path):    # rapport HTML complet d'auditkit (facultatif)
```

`emit` accepte tes objets `Finding` bruts (le pont les normalise, tolérant sur
les noms de champs — `severity/sev/level`, `host/ip/target`, `module/source`,
`cve/cve_id`…) **ou** un `bridge.Event` pour l'avancement des modules. Si tes
champs sont exotiques, la fonction `normalize()` dans `bridge.py` est le seul
endroit à ajuster.

Alternative : si `auditkit` expose lui-même `load_scope` / `iter_findings`, le
pont l'utilise directement, sans fichier de hooks.

### Utilisation

Tout au clavier (pensé pour le BlackBerry Q20, sans souris) :

| Écran | Touches |
| --- | --- |
| **Welcome** | rappel du périmètre autorisé · `Enter` cibles · `q` quitter |
| **Targets** | édition (une cible par ligne) · validation live contre le périmètre · `F5` lancer |
| **Run** | avancement des 6 modules en direct · `Enter` (une fois fini) constats |
| **Findings** | flèches naviguer · détail au focus · `r` (ré)générer + servir le rapport · `s` serveur on/off · `Esc` accueil |

Les 6 modules : **Discovery (nmap) → RTSP (Cameradar) → ONVIF → Snapshots →
Default creds → CVE cross-ref**. Le recoupement CVE est **informatif** — il
n'est pas vérifié activement contre l'appareil, et l'interface le dit.

### Périmètre — deux barrières

`auditkit` a sa barrière ; `ghostboard/scope.py` en ajoute une **seconde, côté
interface**. Une cible hors du périmètre est refusée AVANT tout paquet, et une
plage plus large que le périmètre (`/16` quand le scope est un `/24`) est
refusée aussi. Deux portes valent mieux qu'une pour un outil qui émet sur le
réseau. **N'audite que des caméras que tu es explicitement autorisé à tester.**

### Rapport sur Tailscale

`r` (re)génère le rapport HTML et le sert **uniquement sur l'IP Tailscale**
(réseau privé chiffré), jamais sur le LAN. Sans Tailscale, repli sur
`127.0.0.1` avec avertissement — pas d'exposition large par défaut. L'URL
s'affiche dans la barre de résumé ; ouvre-la depuis un vrai écran.

### Thème

Les couleurs viennent de `brand/palette.toml` (via `build/theme/share/palette.json`
si présent). Changer un hex dans la palette de l'OS et régénérer le thème
re-thème RECON en même temps. Sévérité : rampe sémantique distincte de l'accent
— **critique** rose/rouge, **élevée** ambre, **moyenne** cyan, **info** atténué —
l'accent violet reste réservé à « ce que fait la machine » (sélection, focus).

### Tests

```bash
python tests/test_units.py     # 33 contrôles — barrière, normalisation, backend démo, rapport (aucune dépendance)
python tests/test_smoke.py     # démarre la TUI et enchaîne les 4 écrans (Textual ; se saute sans lui)
```
