# GHOSTBOARD — firmware compagnon ESP32

Firmware autonome pour la carte ESP32 du cyberdeck (écran OLED + 4 boutons +
LED NeoPixel). Deux modules Wi-Fi, un menu, l'identité GHOSTBOARD.

```
GHOSTBOARD            ← splash au boot ; menu à deux niveaux
> WiFi                    Scan · Deauther · Beacon Spam · Evil Portal · Sniffer
                          Auth Test · Brute Force · Handshake
  Bluetooth               BLE Spam
  SubGHz                  (nécessite un CC1101)
  Infrared                (nécessite une LED IR)
  NRF24                   (nécessite un NRF24L01)
  NFC                     (nécessite un ST25R3916)
  iButton                 (nécessite un pad 1-Wire)
```

Le deck (Radxa) ne fait pas tourner ce code : il le **compile et le flashe**
sur la carte, via `ghost-bruce flash`. La carte fonctionne ensuite seule.

Les modules WiFi/BLE sont des **réimplémentations clean-room** inspirées des
fonctions du firmware ESP-HACK (AGPL-3.0) : aucune ligne n'en est copiée, donc
ce projet garde sa propre licence.

## Modules

### WiFi

| Module | Nature | Émission RF | Matériel |
|---|---|---|---|
| **Scan** | Reconnaissance **passive** | Aucune | ESP32 seul |
| **Deauther** | **DoS** — déconnexion forcée de clients | trames deauth | ESP32 seul |
| **Beacon Spam** | Diffusion de **faux SSID** | balises 802.11 | ESP32 seul |
| **Evil Portal** | AP factice + **portail captif** capturant les identifiants | AP ouvert | ESP32 seul |
| **Sniffer** | Comptage de trames (**passif**, mode promiscuous) | Aucune | ESP32 seul |
| **Auth Test** | Teste la robustesse d'une clé WPA (dictionnaire en ligne) | tentatives d'auth | ESP32 seul |
| **Brute Force** | Génère les combinaisons à la volée et les teste (jeu + longueur) | tentatives d'auth | ESP32 seul |
| **Handshake** | Capture le handshake WPA (EAPOL) pour un crack **hors-ligne** | trames deauth | ESP32 seul |

### Bluetooth

| Module | Nature | Matériel |
|---|---|---|
| **BLE Spam** | Flood d'annonces d'appairage (Apple / Swift Pair / Fast Pair) | ESP32 seul (BLE) |

### Matériel externe (phase 2)

Ces catégories sont dans le menu mais **inertes** tant que la puce n'est pas
câblée : chaque entrée affiche un écran « Connect &lt;puce&gt; ». Voir
[Feuille de route matériel](#feuille-de-route-matériel).

| Catégorie | Puce requise | Fonctions visées |
|---|---|---|
| **SubGHz** | CC1101 (SPI) | lecture/TX/RAW, spectre, brute-force, jammer |
| **Infrared** | LED IR TX/RX | TV-B-Gone, télécommande universelle |
| **NRF24** | NRF24L01 (SPI) | scan de spectre 2,4 GHz |
| **NFC** | ST25R3916 (SPI) | lecture / émulation |
| **iButton** | pad 1-Wire | lecture / émulation |

> Les **jeux** d'ESP-HACK (Snake, Doom…) ne sont volontairement pas repris.

### ⚠️ Émission — usage autorisé uniquement

**Deauther, Beacon Spam, Evil Portal, BLE Spam et Handshake émettent** ;
**Auth Test** tente de s'authentifier. Perturber un réseau, piéger des utilisateurs tiers ou
s'authentifier sans autorisation est illégal dans beaucoup de pays (brouillage /
interférence intentionnelle, capture de données, accès non autorisé). **Ne les
utilise que sur ton propre matériel, ou avec une autorisation écrite.**

- **Auth Test** est un audit de robustesse : il essaie une liste de mots de passe
  contre un réseau WPA pour voir s'il cède. Sur **ton** réseau = légitime. Sur un
  réseau tiers = accès illégal. La wordlist est **embarquée** (voir
  [Wordlist](#wordlist-auth-test)).
- **Brute Force** génère les combinaisons à la volée (jeu de caractères +
  longueur) au lieu d'une liste. La génération est instantanée, mais chaque essai
  WPA prend ~4 s **en ligne** : l'écran affiche l'**ETA du plein espace** avant de
  lancer. Réaliste seulement sur un tout petit espace (ex. clé connue à 8
  chiffres) — sinon c'est des années. Ce n'est pas un crack hors-ligne.
- **Handshake** est la **bonne** méthode d'audit WPA : au lieu de tester des clés
  en ligne, il capture **une fois** le handshake à quatre voies (EAPOL) qu'un
  client rejoue à la (re)connexion, puis on casse **hors-ligne** sur le deck. Le
  module écoute en promiscuous sur le canal de la cible et envoie des **deauth**
  ciblés pour forcer une reconnexion ; dès qu'il a ≥ 2 trames EAPOL, `RIGHT` les
  **dumpe sur le port série** (protocole `GBHS-*`). L'outil deck
  [`ghost-crack`](#crack-hors-ligne-ghost-crack) en fait un `.pcap` et lance
  `aircrack-ng`. Hors-ligne, on teste des milliers de clés/s (vs ~4 s/essai) —
  mais un dictionnaire ne trouve qu'une clé **devinable** : une clé forte résiste.

Chaque module actif impose un **écran de confirmation** avant la première action
(barrière partagée, `authgate.cpp`) :

1. `RIGHT` pour démarrer → l'écran **AUTHORIZED USE ONLY** apparaît.
2. **Maintiens `RIGHT` ~1,5 s** pour confirmer (une jauge se remplit). `LEFT`
   annule.
3. L'action (émission ou essai d'auth) ne démarre qu'après confirmation,
   redemandée à chaque entrée.

**Scan** et **Sniffer** restent libres : ce sont de la reconnaissance passive,
aucune émission.

## Navigation

Menu à deux niveaux : **catégories → modules → module**.

| Bouton | Catégories | Liste de modules | Dans un module |
|---|---|---|---|
| `UP` / `DOWN` | change de catégorie | change de module | déplace la sélection |
| `RIGHT` | ouvre la catégorie | ouvre le module | détails / démarrer |
| `LEFT` | — | retour aux catégories | retour (liste, puis menu) |

## Compiler / flasher

Depuis le deck, le plus simple :

```sh
ghost-bruce flash                 # compile + flashe (port auto-détecté)
ghost-bruce flash --build-only    # compile seulement (vérifie que ça build)
ghost-bruce flash -e esp32-usb    # cartes à USB natif (ESP32-S3/C3)
```

Ou directement avec PlatformIO :

```sh
cd companion/firmware
pio run                 # compile
pio run -t upload       # compile + flashe
```

## Câblage (à vérifier)

Les broches sont dans **`include/config.h`** et supposent un ESP32 WROOM +
OLED I2C SSD1306 128×64 + 4 boutons + 1 NeoPixel. **Vérifie-les pour ta
carte** (Bruce, CYD, T-Display…) avant de flasher — un mauvais brochage ne
casse rien mais laisse l'écran/les boutons muets. C'est le seul fichier à
adapter pour un autre écran (type u8g2) ou d'autres broches.

## Couleurs

L'OLED est monochrome ; c'est la **LED NeoPixel** qui porte la charte, et ses
couleurs ne sont **pas codées en dur** : elles viennent de `brand/palette.toml`
(la source unique du projet) via le générateur, comme tout le reste de
GHOSTBOARD.

```sh
tools/gen-theme.py            # régénère include/theme_colors.h depuis la palette
tools/gen-theme.py --check    # échoue si le header est périmé (utilisé par les tests)
```

| État carte | LED | Origine palette |
|---|---|---|
| repos | éteinte | — |
| scan / activité | violet | `accent` `#A855F7` |
| émission (deauth, spam, portail) | rose | `input` `#FF4D8D` (couleur d'alerte) |

## Wordlist (Auth Test)

Pas de carte SD sur la carte de base : la wordlist du module **Auth Test** est
**compilée dans le firmware**. Elle vit en clair dans un fichier texte que tu
édites librement :

```
companion/firmware/data/wordlist.txt     # un mot de passe par ligne ; # = commentaire
```

Un générateur la transforme en tableau C (`include/wordlist.h`). Il est lancé
**automatiquement au build** (pré-script PlatformIO), donc le flux est simplement :

```sh
# 1. mets ta liste dans data/wordlist.txt
# 2. flashe : la liste est régénérée puis embarquée
ghost-bruce flash
```

À la main si besoin :

```sh
tools/gen-wordlist.py            # écrit include/wordlist.h
tools/gen-wordlist.py --check    # échoue si le header est périmé (tests)
```

La liste fournie par défaut (~2700 entrées) est produite par un outil d'autorat,
`tools/make-wordlist.py` : mots de passe les plus courants + racines FR/EN
déclinées (mot + année/chiffres, capitalisation) + suites clavier/numériques.
Elle **ne contient pas** les clés par défaut des box (aléatoires, uniques par
appareil) : un dictionnaire ne trouve qu'une clé **faible ou courante**. Sur
ESP32 chaque essai prend quelques secondes ⇒ ~2700 essais = plusieurs heures.

```sh
tools/make-wordlist.py           # régénère data/wordlist.txt (liste par défaut)
tools/make-wordlist.py --max 800 # version courte, plus rapide à parcourir
```

Règles de génération : WPA impose des clés de **8 à 63 caractères** — les entrées
hors plage sont écartées (impossibles comme clé WPA), les doublons supprimés,
l'ordre conservé. La liste tient en flash (≈4 Mo) ; pour un très gros dictionnaire
(millions d'entrées), c'est la **carte SD** qui prendra le relais en phase 2.

## Crack hors-ligne (`ghost-crack`)

Le module **Handshake** capture, le deck casse — **hors-ligne**. Contrairement à
Auth Test / Brute Force (essais en ligne, ~4 s chacun), on ne touche plus au
réseau une fois le handshake en main : `aircrack-ng` teste des milliers de
clés/s en local.

```sh
# prérequis deck (une fois)
sudo apt install aircrack-ng python3-serial

# 1. sur la carte : WiFi > Handshake > choisir la cible > confirmer >
#    attendre "HANDSHAKE CAPTURED" > RIGHT (dump série)

# 2. sur le deck : tout d'un coup — capture + crack + AFFICHE LA CLÉ
ghost-crack auto -o maison.pcap
ghost-crack auto -o maison.pcap -w /usr/share/wordlists/rockyou.txt

# … ou en deux temps si tu préfères garder le pcap séparément :
ghost-crack capture -o maison.pcap        # dump série -> .pcap
ghost-crack run maison.pcap               # crack hors-ligne -> clé

ghost-crack info          # aircrack-ng / pyserial / carte détectés
```

Le `.pcap` est standard (DLT 105, 802.11) : lisible aussi par Wireshark,
hcxtools, etc. Le protocole série `GBHS-*` (émis par le firmware) est décrit en
tête de `tools/ghost-crack` ; `ghost-crack capture --replay <dump.txt>` rejoue
un dump texte sans carte (utilisé par les tests).

> Même hors-ligne, un dictionnaire ne révèle qu'une clé **faible ou courante**.
> Une clé forte (ou la clé aléatoire d'usine d'une box) **résiste** — c'est le
> résultat attendu d'un audit, pas un échec de l'outil.

## Feuille de route matériel

Les catégories SubGHz / Infrared / NRF24 / NFC / iButton sont présentes au menu
mais **inertes** : `gbHardwarePresent()` renvoie faux tant que la macro `HW_*`
correspondante n'est pas définie dans `include/hardware.h`, et le module affiche
alors « Connect &lt;puce&gt; ».

Pour activer une catégorie (phase 2) :

1. Câble la puce et **renseigne ses broches** dans `include/hardware.h`, puis
   décommente la macro `HW_<puce>`.
2. Le vrai module remplacera le placeholder de `hwstub.cpp`. Bibliothèques
   pressenties (à ajouter dans `platformio.ini` le moment venu) :
   - **CC1101** → `SmartRC-CC1101-Driver-Lib` (SubGHz brut) ;
   - **IR** → `crankyoldgit/IRremoteESP8266` (TX/RX + TV-B-Gone) ;
   - **NRF24** → `nRF24/RF24` (scan de spectre) ;
   - **iButton** → `OneWire` ;
   - **NFC (ST25R3916)** → pilote vendeur ST (le plus lourd).

## Notes d'intégration (à valider sur la carte)

Je n'ai pas pu compiler/exécuter ce firmware ici (pas de toolchain ESP32 ni de
carte dans l'environnement). Ce qui reste à vérifier sur le matériel réel :

- **broches** de `config.h` conformes à ta carte ;
- **ré-entrée entre modules** : Deauther/Beacon/Evil Portal touchent au driver
  Wi-Fi (init/mode/stop) à chaque entrée. Le menu remet le Wi-Fi à `WIFI_OFF` au
  retour, mais l'enchaînement Scan → Deauther (`esp_wifi_init`) est à vérifier ;
  en cas de reboot, ajouter un `esp_wifi_deinit()` au retour menu ;
- **BLE Spam** : les charges d'annonce et la randomisation d'adresse (NimBLE)
  déclenchent des popups variables selon la cible et la version d'OS ;
- **Evil Portal** : capture en RAM uniquement (pas de SD) — le compteur et le
  dernier identifiant sont à l'écran ;
- **portée / efficacité** des émissions (antenne, canal, puissance).

## Provenance

Le module **Deauther** vient d'un firmware fourni par l'utilisateur, **repris
tel quel** ; les modifications GHOSTBOARD sont balisées `[GB]` dans
`src/modules/deauther.cpp` (gate d'autorisation, correction du dépassement de
tableau, SSID unifié, retour menu, couleurs LED).

Les modules **Beacon Spam, Evil Portal, Sniffer, BLE Spam et Handshake** sont
des **réimplémentations clean-room** inspirées des fonctions du firmware
[ESP-HACK](https://github.com/Teapot174/ESP-HACK) (AGPL-3.0) : **aucune ligne
n'en a été copiée**, afin que GHOSTBOARD conserve sa propre licence. Les **jeux**
d'ESP-HACK ne sont pas repris. Le matériel externe (SubGHz/IR/NRF24/NFC/iButton)
est câblé au menu mais implémenté en phase 2.
