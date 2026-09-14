# Validation — GHOSTBOARD Pi 5 0.4.0

Validation locale : Windows, Python 3.12, Node.js. Aucun Pi 5, serveur X11 Linux ou moteur IA distant disponible dans cette session.

| Vérification | Résultat |
|---|---|
| Python integration and backup tests | PASS |
| Hand control — 49 synthetic-sequence tests | PASS |
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
