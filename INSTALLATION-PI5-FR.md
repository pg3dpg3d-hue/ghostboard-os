# GHOSTBOARD Pi 5 — 0.3.0, version de développement

Cette livraison ajoute au projet une édition Raspberry Pi 5 installable **sur Raspberry Pi OS 64 bits basé sur Debian 13**. Elle comprend les sources complètes et un installateur. Une carte microSD ou un SSD contenant déjà Raspberry Pi OS est nécessaire. Aucune image disque préinstallée n'est fournie.

Le démarrage réel, l'affichage HDMI/DSI, l'audio, le Bluetooth et les performances doivent encore être vérifiés sur un Pi 5. Les tests exécutés ici sont détaillés dans `VALIDATION.md`. L'installateur télécharge les paquets : Internet est nécessaire pendant l'installation.

## Installation

1. Installer Raspberry Pi OS Lite **64 bits / Debian 13** avec [Raspberry Pi Imager](https://www.raspberrypi.com/software/). Créer le compte utilisateur et configurer le réseau. Un accès SSH est utile pour poursuivre si l'écran n'est pas encore configuré.
2. Démarrer le Pi et vérifier que ce système de base fonctionne. Cette édition conserve ses fichiers de démarrage et son mode d'affichage ; elle ne répare pas une dalle qui ne fonctionne pas sous Raspberry Pi OS.
3. Copier l'archive fournie sur le Pi et l'extraire :

```bash
tar -xzf GHOSTBOARD-Pi5-0.3.0.tar.gz
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

# Installation optionnelle des deux agents de développement, puis connexion séparée aux comptes
sudo bash install/ghostboard-pi5.sh --profile full --user "$USER" --codex --claude
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
| Matériel | Télémétrie Pi et profils de ventilation réversibles pour le ventilateur officiel |
| Voix | Enregistrement ALSA et transcription locale par whisper.cpp avant confirmation |
| Vision locale | Écran, caméra, PNG/JPEG/WebP et première page PDF avec modèle multimodal llama.cpp |
| Contrôle Internet | Appairage SSH ou Tailscale ; serveur MCP commun à Codex et Claude |
| Image | Recette reproductible pour rpi-image-gen officiel, épinglé sur un commit connu |
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

Conserver le dossier du moteur : le service utilise ce chemin. `ghost-model enable` active le lancement aux prochaines sessions ; `stop`, `disable` et `status` pilotent le service. Le serveur écoute seulement sur `127.0.0.1:8080`, avec un contexte initial de 4 096 tokens. Ce parcours configure le **chat local textuel** ; le contrôle visuel nécessite un moteur/modèle et une configuration multimodale adaptés. Aucun débit ou niveau de qualité n'a été mesuré sur le Pi.

## Agent visuel local

Avec une version récente de `llama-server`, fournir un modèle visuel GGUF et le projecteur GGUF qui lui correspond exactement :

```bash
ghost-model configure /modeles/vision.gguf \
  --mmproj /modeles/mmproj-vision.gguf \
  --server /chemin/vers/llama-server
ghost-model start

# Comprendre l'écran sans agir
ghost-assistant see --provider local --screen "Décris précisément ce qui est affiché"

# Comprendre une caméra, une image ou la première page d'un PDF
ghost-assistant see --provider local --camera /dev/video0 "Que vois-tu ?"
ghost-assistant see --provider local --file manuel.pdf "Explique cette page"

# Observer l'écran et le contrôler localement, avec confirmation des actions
ghost-assistant act --provider local "Ouvre le gestionnaire de fichiers"
```

Les fichiers visuels sont limités à 16 Mio et vérifiés par leur signature. Le mode local envoie les images seulement au serveur lié à `127.0.0.1`. Un fournisseur distant demande une confirmation avant le partage. Le texte visible dans l'écran, la caméra ou le document est toujours marqué comme contenu non fiable. Le Pi 5 partage sa mémoire entre le bureau et le modèle ; commencer avec un modèle quantifié compact et mesurer la température, la RAM et la latence.

## Commande vocale locale

Installer `whisper-cli` pour ARM64 et télécharger soi-même un modèle whisper.cpp. Ghostboard n'embarque ni binaire ni poids tiers. Configurer ensuite le chemin et le microphone :

```bash
ghost-voice --configure /chemin/vers/ggml-small.bin --device default --language fr
ghost-voice --mode chat --provider local
ghost-voice --mode act --provider cloud --seconds 8
```

Le microphone est enregistré localement avec ALSA. La transcription est affichée et doit être confirmée avant d'être envoyée au modèle choisi. Les fichiers audio et texte temporaires sont supprimés à la fin. `--speak` utilise la voix hors ligne d'`espeak-ng` pour accuser réception.

## Contrôle par Internet, Codex et Claude

Le moteur de contrôle s'exécute sur le Pi : le PC principal peut donc être éteint. Le moyen recommandé est un réseau privé Tailscale, afin de ne pas publier SSH directement sur Internet. Installer Tailscale depuis sa documentation Linux officielle, connecter le Pi au compte, puis lancer :

```bash
sudo ghost-remote internet-enable
ghost-remote status
```

Cette commande active `tailscaled`, connecte le Pi et active Tailscale SSH. La politique SSH du tailnet doit autoriser uniquement les comptes et appareils voulus. Depuis une machine déjà connectée au même tailnet, générer la commande d'enregistrement MCP :

```bash
ghost-remote client-config --tool codex --host ghostboard.nom-tailnet.ts.net --user ghost
ghost-remote client-config --tool claude --host ghostboard.nom-tailnet.ts.net --user ghost
```

Exécuter la ligne produite sur la machine qui héberge Codex ou Claude. Les deux clients démarrent alors le même serveur MCP sur le Pi à travers SSH. Pour faire du Pi une machine de développement autonome, installer Codex CLI et Claude Code directement dessus, puis créer un dépôt de travail inscriptible :

```bash
sudo bash install/ghostboard-pi5.sh --profile full --user "$USER" --codex --claude
ghost-workspace init
ghost-workspace status
ghost-codex
ghost-claude
```

Les deux agents démarrent dans `~/Ghostboard`, un vrai clone Git de la branche Pi 5. Ils peuvent y lire et écrire le code, lancer les tests, créer des branches et préparer des commits. Les comptes Codex et Claude doivent être connectés séparément. Le dépôt système sous `/opt/ghostboard-os` reste la copie installée ; le développement se fait dans le clone utilisateur afin d'éviter les modifications root accidentelles. Après revue, réinstaller la branche testée pour appliquer les changements au système.

Un appairage OpenSSH à clé publique reste disponible pour un réseau privé sans Tailscale :

```bash
sudo ghost-remote enable --user "$USER" --public-key ~/controleur.pub
sudo ghost-remote disable --user "$USER"
```

La clé appairée donne les droits complets du compte de bureau. Le STOP physique ou `Ctrl+Alt+Échap` bloque les nouvelles commandes du serveur MCP. Une session Codex hébergée ailleurs doit être connectée au tailnet ou disposer d'un connecteur MCP HTTPS dédié ; cette conversation ne peut pas découvrir seule une adresse privée.

## Matériel et ventilation

```bash
ghost-hardware status
sudo ghost-hardware fan cool
sudo ghost-hardware fan balanced
sudo ghost-hardware fan quiet
sudo ghost-hardware fan default
```

Les profils s'appliquent au ventilateur officiel géré par le firmware du Pi 5. La commande sauvegarde `config.txt`, remplace seulement son bloc Ghostboard et demande un redémarrage. `default` retire ce bloc pour revenir aux seuils du firmware Raspberry Pi. `quiet` autorise une température plus haute : la température et les alertes de sous-tension doivent être surveillées sur le cyberdeck assemblé.

## Construire une image flashable

La recette utilise `raspberrypi/rpi-image-gen` épinglé au commit `262d4df5a9f9d4133370465399a7958a7c22cdc7` (version 2.8.0 au moment de cette livraison). Le chemin pris en charge est un hôte Raspberry Pi OS/Debian 64 bits. Depuis la racine du dépôt :

```bash
# OpenSSL demande le mot de passe sans l'afficher et n'écrit que son empreinte.
openssl passwd -6 > ~/ghostboard.passhash
bash image/build-image.sh --password-hash-file ~/ghostboard.passhash --install-deps
```

Le script vérifie l'empreinte du mot de passe, prépare une source temporaire, construit une image Pi 5 Trixie et efface la configuration privée à la sortie. `--install-deps` autorise explicitement l'installation des dépendances de construction sur l'hôte. Sans cette option, elles doivent déjà être présentes. La recette elle-même est validée statiquement ici ; la génération complète reste à exécuter sur Linux.

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
