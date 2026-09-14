# GHOSTBOARD Pi 5 — 0.2.0, version de développement

Cette livraison ajoute au projet une édition Raspberry Pi 5 installable **sur Raspberry Pi OS 64 bits basé sur Debian 13**. Elle comprend les sources complètes et un installateur. Une carte microSD ou un SSD contenant déjà Raspberry Pi OS est nécessaire. Aucune image disque préinstallée n'est fournie.

Le démarrage réel, l'affichage HDMI/DSI, l'audio, le Bluetooth et les performances doivent encore être vérifiés sur un Pi 5. Les tests exécutés ici sont détaillés dans `VALIDATION.md`. L'installateur télécharge les paquets : Internet est nécessaire pendant l'installation.

## Installation

1. Installer Raspberry Pi OS Lite **64 bits / Debian 13** avec [Raspberry Pi Imager](https://www.raspberrypi.com/software/). Créer le compte utilisateur et configurer le réseau. Un accès SSH est utile pour poursuivre si l'écran n'est pas encore configuré.
2. Démarrer le Pi et vérifier que ce système de base fonctionne. Cette édition conserve ses fichiers de démarrage et son mode d'affichage ; elle ne répare pas une dalle qui ne fonctionne pas sous Raspberry Pi OS.
3. Copier l'archive fournie sur le Pi et l'extraire :

```bash
tar -xzf GHOSTBOARD-Pi5-0.2.0.tar.gz
cd ghostboard-os
bash install/ghostboard-pi5.sh --dry-run
sudo bash install/ghostboard-pi5.sh --profile full --user "$USER"
```

Exécuter l'installation depuis une console texte ou SSH, hors d'une session XFCE active. L'installateur vérifie le modèle de carte, ARM64, Debian 13 et le compte cible. Il s'arrête au premier échec ; après correction, relancer la même commande. Les fichiers remplacés sont sauvegardés sous `/var/lib/ghostboard/pi5-backups/`, avec un manifeste.

4. Redémarrer puis choisir **GHOSTBOARD Pi 5** dans le sélecteur de session LightDM. L'installation ne crée pas de connexion automatique ; si Raspberry Pi OS en avait déjà une, la session associée devient Ghostboard.
5. Le centre de contrôle s'ouvre. Lancer **Diagnostics**, ou :

```bash
ghost-system doctor
```

Le profil `desktop` omet la bureautique, VLC et les outils de compilation pour une installation plus petite. `full` est le profil par défaut. La disposition du thème vise un écran de 800 × 480 ou plus ; aucune résolution n'est forcée au niveau du noyau.

Options supplémentaires :

```bash
# Uniquement pour le clavier Q20 : Alt droite/Super
sudo bash install/ghostboard-pi5.sh --profile full --user "$USER" --q20

# Installation optionnelle de Claude Code via npm, puis connexion au compte séparément
sudo bash install/ghostboard-pi5.sh --profile full --user "$USER" --claude
```

Utiliser **cet installateur Pi 5**. L'ancien `install/ghostboard-install.sh` reste le parcours Radxa/Intel et refuse désormais de s'exécuter sur Raspberry Pi.

## Fonctions livrées

| Fonction | Mise en œuvre |
|---|---|
| Bureau | XFCE/X11, thème Ghostboard, menu, recherche, terminaux, bureaux virtuels |
| Centre de contrôle | Applications, réglages, diagnostics et assistant ; interface native redimensionnable |
| Réseau et périphériques | Interfaces Wi-Fi, Bluetooth, audio PipeWire, affichage et énergie |
| Applications | Chromium, fichiers, éditeur, calculatrice, capture d'écran, gestionnaire de processus |
| Profil complet | LibreOffice, VLC, PDF, KeePassXC, archives, outils de développement et FFmpeg |
| Computer use | Capture, clic, frappe, raccourcis, défilement, liste/activation des fenêtres, glisser-déposer |
| Contrôle utilisateur | Bouton STOP et Ctrl+Alt+Échap ; reprise explicite ; verrouillage du bureau |
| Assistant hybride | Client configurable local/distant compatible chat-completions, avec boucle d'outils MCP |
| Clés API | Variable d'environnement ou trousseau du bureau ; aucune clé dans la configuration JSON |
| Modèle local | Service utilisateur pour un `llama-server` et un modèle GGUF fournis par l'utilisateur |
| Session agent | Écran X11 virtuel optionnel, séparé du pointeur du bureau |
| Maintenance | Diagnostics, mises à jour apt, sauvegarde/restauration ciblée des réglages |
| Compagnon | Console série et sources du firmware existant, conservées sans modification fonctionnelle |

Les logiciels tiers ne sont pas embarqués dans l'archive : leurs paquets sont installés depuis les dépôts configurés sur le Pi. IBM Plex est installé si disponible ; sinon le système utilise une police de repli. Martian Mono n'est pas téléchargée automatiquement dans cette édition.

## Assistant distant et computer use

Dans le centre de contrôle, ouvrir **Assistant → Configure AI**, ou :

```bash
ghost-assistant configure
```

Choisir `cloud`, saisir l'URL de base d'un fournisseur compatible `/chat/completions` et l'identifiant exact d'un modèle acceptant **les images et les appels d'outils**. L'API Anthropic native n'utilise pas ce format ; employer l'intégration Claude Code séparée pour celle-ci. Les tarifs et comptes du fournisseur sont distincts de Ghostboard.

Le configurateur propose de placer la clé dans le trousseau du bureau. Une session avec connexion automatique peut demander le déverrouillage de ce trousseau. On peut aussi fournir la clé via une variable d'environnement dans le terminal où l'assistant est lancé.

```bash
ghost-assistant chat --provider cloud "Explique ce que je peux faire avec ce cyberdeck"
ghost-assistant act --provider cloud "Ouvre le navigateur et recherche la documentation Raspberry Pi"
```

La session demande l'autorisation de partager l'écran avec l'endpoint choisi. Les actions sur les applications sont présentées avant exécution. Limite par défaut : 12 tours de modèle, ajustable avec `--max-steps` entre 1 et 50. Pas de bascule automatique local → cloud, ni de requête IA au démarrage du bureau. Les captures récentes remplacent les précédentes dans le contexte ; les conversations ne sont pas enregistrées sur disque par ce client.

```bash
ghost-system stop
ghost-system resume
```

Le STOP coupe les commandes du serveur MCP. Il ne ferme pas les applications déjà lancées et n'arrête pas les commandes terminal qu'un autre agent aurait lancées hors de ce serveur. Le contenu des fenêtres reste une entrée non fiable : l'approbation des actions et la supervision restent nécessaires.

## IA locale hors ligne

Installer une version ARM64 de [llama.cpp](https://github.com/ggml-org/llama.cpp) et un modèle GGUF adapté à la mémoire disponible. Le téléchargement du moteur et des poids n'est pas automatisé ici. Pour compiler le moteur sur le Pi avec le profil complet :

```bash
git clone https://github.com/ggml-org/llama.cpp.git
cmake -S llama.cpp -B llama.cpp/build -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF
cmake --build llama.cpp/build --config Release -j 2 --target llama-server
ghost-model configure /chemin/vers/modele.gguf --server "$PWD/llama.cpp/build/bin/llama-server"
ghost-model start
ghost-assistant chat --provider local "Bonjour"
```

Conserver le dossier du moteur : le service utilise ce chemin. `ghost-model enable` active le lancement aux prochaines sessions ; `stop`, `disable` et `status` pilotent le service. Le serveur écoute seulement sur `127.0.0.1:8080`, avec un contexte initial de 2 048 tokens. Ce parcours configure le **chat local textuel** ; le contrôle visuel nécessite un moteur/modèle et une configuration multimodale adaptés. Aucun débit ou niveau de qualité n'a été mesuré sur le Pi.

## Écran dédié à l'agent

```bash
ghost-system agent-screen on
ghost-system agent-screen open browser
ghost-assistant act --provider cloud --agent-screen "Utilise le navigateur déjà ouvert"
ghost-system agent-screen status
ghost-system agent-screen off
```

L'écran virtuel fait 1 280 × 800, indépendant de la dalle physique. Le navigateur utilise un profil séparé. **Il s'agit du même compte Linux** : cette séparation graphique n'isole pas les fichiers, les permissions ou le réseau. La fenêtre virtuelle n'apparaît pas sur la dalle ; l'assistant la voit par captures. Un visualiseur interactif intégré n'est pas encore fourni.

## Sauvegarde et mises à jour

```bash
ghost-system backup /chemin/vers/ghostboard-settings.tar.gz
ghost-system restore /chemin/vers/ghostboard-settings.tar.gz
ghost-system update
```

La sauvegarde couvre `.config/ghostboard`, `.config/xfce4`, `.config/rofi` et le thème Ghostboard. Elle n'inclut ni les documents personnels, ni le profil du navigateur, ni les clés SSH, ni le trousseau. La restauration refuse les liens et les chemins sortant des dossiers autorisés, et sauvegarde les réglages précédents avant de les remplacer. Elle restaure les fichiers contenus dans l'archive sans supprimer les fichiers supplémentaires.

Les mises à jour portent sur les paquets apt. Pour mettre à jour les fichiers Ghostboard eux-mêmes, installer une nouvelle archive et relancer l'installateur. Ce mécanisme n'est pas un système de mises à jour A/B. Une image du support de stockage reste nécessaire pour une restauration complète.

## Vérification sur le Pi

Après le premier démarrage :

1. Vérifier clavier, affichage, Wi-Fi, Bluetooth, lecture et enregistrement audio.
2. Ouvrir le navigateur, les fichiers, un terminal et le centre de contrôle.
3. Exécuter `ghost-system doctor --json` et conserver le résultat.
4. Tester une capture puis une saisie dans un éditeur vide ; vérifier l'effet du bouton STOP pendant la saisie.
5. Vérifier le modèle distant après configuration, puis le chat local avec son serveur démarré.
6. Tester sauvegarde/restauration et redémarrage avant de confier des données importantes au système.

La télémétrie batterie n'apparaît que si le matériel l'expose au noyau. Une powerbank USB-C ordinaire peut ne fournir aucune mesure. Voix, mises à jour A/B, image flashable, intégration spécifique batterie et validation matérielle complète restent à développer.

## Provenance

Base : `pg3dpg3d-hue/ghostboard-os`, commit `f9daf5527ce077ef83f0f6146daaf33159f79702`.
Les 157 fichiers de départ ont été récupérés via GitHub et vérifiés par leur empreinte Git. Les modifications de cette livraison sont locales et accompagnées d'un patch. Elles n'ont pas été publiées sur le dépôt distant.
