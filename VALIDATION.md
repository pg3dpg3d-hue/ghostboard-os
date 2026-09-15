# Validation — GHOSTBOARD Pi 5 0.4.0

Validation locale : Windows, Python 3.12, Node.js. Aucun Pi 5, serveur X11 Linux ou moteur IA distant disponible dans cette session.

| Vérification | Résultat |
|---|---|
| Python integration and backup tests | PASS |
| Hand control — 84 synthetic-sequence tests | PASS |
| MCP regressions with simulated X11 | PASS |
| MCP protocol without X11 | PASS |
| Native control center layout | PASS |
| Python compilation | PASS |
| MCP JavaScript syntax | PASS |
| Spatial JavaScript syntax | PASS |
| Theme legibility and consistency | PASS |
| Theme generation | PASS |
| Pi installer dry run | PASS |
| Shell syntax (29 scripts) | PASS |
| XFCE XML configuration | PASS |

Le contrôle gestuel (`tests/test-hand-tracking.py`, 49 tests) est validé avec des séquences synthétiques de 21 points, un adaptateur de sortie simulé (aucun test ne déplace le pointeur) et un canal d'événements simulé : seuil de confiance, armement maintenu, clic gauche/droit, double-clic, glisser-déposer, défilement, balayage, filtrage du tremblement, temporisation/validation, perte de la main, libération des boutons après erreur, blocage par le STOP partagé et reprise exigeant une réactivation, changement de mode, configuration invalide rejetée, sortie JSON, file d'une seule image, canal local restreint au loopback, backend Hailo non pris en charge, et absence de commande shell construite dynamiquement. L'outil MCP `hand_status` (lecture seule) est couvert par `tests/test-mcp.js`.

Les tests Python utilisent de vrais fichiers temporaires, un serveur HTTP local de test et le transport MCP réel. Ils vérifient aussi la recette d’image, les profils de ventilation réversibles, la vision locale, le refus d’une commande vocale, les configurations MCP distantes de Codex et Claude, ainsi que le confinement des fichiers servis par Spatial. Le test MCP réel crée un dépôt temporaire, y lit et écrit des fichiers, exécute une commande Node, refuse une sortie de dossier et vérifie que le STOP bloque une écriture distante. Les tests de régression MCP simulent uniquement les processus X11. Les widgets du centre de contrôle ont été créés sur Windows aux dimensions 760 × 430 et 800 × 480.

GHOSTBOARD Spatial a été ouvert dans un vrai Chromium local avec Three.js 0.186.0. Le cube STL de calibration a été rendu et reconnu à 20 × 20 × 20 mm et 12 triangles. La syntaxe JavaScript, le verrou de dépendances et les routes locales protégées font partie de la validation reproductible.

La génération du thème a produit les ressources GTK, XFWM, rofi, palette et boutons PNG. Le convertisseur SVG → PNG n’est pas présent sur l’hôte Windows ; il figure dans les paquets de l’installateur Linux.

## Non exécuté ici

- Construction complète de l’image avec rpi-image-gen, faute d’hôte Linux compatible dans cette session.
- Installation apt complète sous Raspberry Pi OS et disponibilité finale de tous les paquets.
- Installation et authentification réelles de Codex CLI, Claude Code et Tailscale sur ARM64.
- Connexion MCP réelle à travers Tailscale SSH entre deux machines.
- Démarrage réel ARM64, connexion LightDM/XFCE, pilotes HDMI/DSI, Wi-Fi, Bluetooth, audio et batterie.
- Télémétrie et réglage réel du ventilateur actif.
- Capture caméra, lecture PDF et inférence multimodale réelle par llama.cpp.
- Enregistrement ALSA et transcription réelle par whisper.cpp.
- Contrôle réel d’une application X11, session Xvfb séparée et verrouillage du bureau.
- Accélération GPU de Spatial, modèles 3D volumineux et gestes tactiles sur la dalle finale.
- Appels à un fournisseur IA réel, stockage dans le trousseau Linux et inférence locale sur Pi.
- Suivi des mains sur matériel : capture Picamera2/V4L2 réelle, détection MediaPipe sur ARM64, latence/FPS réels, injection xdotool sur la dalle, service systemd utilisateur en session graphique, et calibration en direct. Le backend Hailo n'est ni implémenté ni validé.

Le workflow `.github/workflows/pi5-validation.yml` prépare un conteneur Debian 13 avec Xvfb et inclut une saisie réellement reçue par xterm, une capture PNG, les outils de dépôt distant, Three.js épinglé et la résolution des paquets. Cette CI vérifie le logiciel x86_64, pas le matériel ARM64.

Pour valider X11 sur Linux :

```bash
xvfb-run -a -s "-screen 0 800x480x24 -nolisten tcp" python3 tests/test-desktop-live.py
```

Les performances du Pi n’ont pas été mesurées. La livraison comprend un installateur et une recette d’image reproductible ; l’image elle-même doit encore être construite et qualifiée sur Linux puis démarrée sur un Pi 5.

## Audit Hand Control — 14 septembre 2026

Corrections vérifiées sur Windows/Python 3.12 : 58 tests Hand Control, 28 tests
Pi5, 14 régressions MCP et 30 contrôles MCP sans X11 ; disposition Tk,
compileall et syntaxe Node passent. Aucun chiffre matériel n'a été mesuré.

Le bilan initial surestimait plusieurs fonctions. La calibration lit désormais
12 échantillons réels par coin, exige au moins 6 détections fiables et refuse
les mouvements excessifs ; elle reste à essayer avec une caméra physique.
Le benchmark n'injecte plus d'événements et ne modifie plus l'état du service.
Les commandes de reprise ne sont plus rejouées, les erreurs caméra remontent,
la capture est cadencée et la dernière image est libérée à l'arrêt.

Limites encore ouvertes : le backend MediaPipe utilise toujours l'API historique
`solutions.hands`, pas Tasks Hand Landmarker. La disponibilité Debian 13 ARM64
et la recette de dépendances ne sont pas validées. Spatial dispose d'un émetteur
UDP, pas d'un récepteur intégré vérifié. Le masquage du pointeur Presentation
est un événement, pas une implémentation X11. Les FPS caméra et inférence sont
encore calculés depuis les mêmes observations ; ils ne constituent pas deux
mesures indépendantes. STOP est contrôlé avant chaque commande, mais aucune
borne de latence d'arrêt n'est garantie pendant un appel natif bloquant.
Un clic générique ne sait pas distinguer une validation sensible : la garantie
absolue annoncée précédemment n'est pas implémentée. Ne pas utiliser ce module
pour confirmer des achats, suppressions, messages ou changements de sécurité.

## Suite Hand Control — 14 septembre 2026 (extensions)

Vérifié sur Windows/Python 3.12 : 84 tests Hand Control, 28 tests Pi5, 14
régressions MCP, 30 contrôles MCP sans X11, disposition Tk, compileall (dont les
nouveaux modules et `install/hand-deps.py`) et syntaxe Node. Aucun chiffre
matériel mesuré. Fonctions reprises depuis l'état réel du travail précédent :

- **Backend MediaPipe Tasks** (mode VIDEO, modèle `.task` local, aucun
  téléchargement au runtime) confirmé ; `make_backend` ne bascule plus
  silencieusement sur le simulé (test mis à jour). Le benchmark retombe
  explicitement sur le pipeline simulé quand le modèle est absent (régression
  corrigée + test).
- **`install/hand-deps.py`** ajouté (était référencé mais manquant) :
  provisionnement reproductible venv + modèle épinglé, empreinte SHA-256 affichée,
  échec explicite ; `--dry-run` testé.
- **Correction de perspective** : `Calibration` calcule une homographie
  quadrilatère → écran (repli rectangle si dégénéré). Tests : coins, centre,
  bords, quadrilatère non rectangulaire, miroir, cas dégénéré.
- **Main pilote** : continuité par handedness + proximité, temporisation avant
  transfert, `preferred_hand`. Tests : continuité malgré une meilleure confiance
  adverse, transfert après délai, perte temporaire, préférence forcée.
- **Zoom à deux mains** : référence au début du geste, bande morte, référence
  avancée (pas d'accumulation), nettoyage à la disparition d'une main. Tests :
  zoom in/out, pas de zoom à l'apparition, bande morte, fin de geste, mode
  Pointer non concerné.
- **Spatial** : rotation (horizontal) / inclinaison (vertical) distinctes,
  `select`, `explode` ; schéma d'événement réconcilié avec `hand_events`
  (validé) et pont authentifié `hand_events.Bridge`/`Channel` câblé dans
  `run_engine`. Tests : rotate/tilt, explode, validation du schéma.
- **Masquage curseur Presentation** réel via XFixes (`hand_desktop.Desktop`).
- **Clic externe soumis à validation clavier F8** (`Desktop.authorized()`,
  XQueryKeymap) ; sans autorisation vérifiable, le clic système n'est pas injecté.
  Tests : bloqué sans F8, autorisé avec F8, absence d'autorisateur = blocage,
  Spatial non concerné, déplacement du pointeur libre.

Limites encore ouvertes (à valider sur matériel) : voir la section « Limites » de
`INSTALLATION-PI5-FR.md`. Le pipeline isolé multiprocessus (`hand_pipeline.py`)
et le pont Spatial sont fournis et testables unitairement, mais leur intégration
bout-en-bout avec une caméra réelle et l'application Spatial reste à qualifier sur
un Pi 5. La garantie absolue sur les clics sensibles n'existe toujours pas : la
validation F8 réduit le risque mais ne connaît pas la sémantique du bouton pointé.
