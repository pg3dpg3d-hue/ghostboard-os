# GHOSTBOARD — firmware compagnon ESP32

Firmware autonome pour la carte ESP32 du cyberdeck (écran OLED + 4 boutons +
LED NeoPixel). Deux modules Wi-Fi, un menu, l'identité GHOSTBOARD.

```
GHOSTBOARD           ← splash au boot
> WiFi Scan (passive)   reconnaissance passive : SSID, RSSI, BSSID, canal
  Deauther  (DoS)       test de résilience : émission de trames 802.11 deauth
```

Le deck (Radxa) ne fait pas tourner ce code : il le **compile et le flashe**
sur la carte, via `ghost-bruce flash`. La carte fonctionne ensuite seule.

## Modules

| Module | Nature | Émission RF |
|---|---|---|
| **WiFi Scan** | Reconnaissance **passive** | Aucune — écoute seulement |
| **Deauther** | **Déni de service** (déconnexion forcée de clients) | Oui — trames deauth |

### ⚠️ Deauther — usage autorisé uniquement

Émettre des trames deauth déconnecte de force les clients d'un point d'accès.
**Ne l'utilise que sur un réseau que tu possèdes, ou pour lequel tu as une
autorisation écrite.** Dans beaucoup de pays, l'émission contre un tiers est
illégale (brouillage / interférence intentionnelle).

Le firmware impose un **écran de confirmation** avant la première émission :

1. Sélectionne un réseau, `RIGHT` → détails.
2. `RIGHT` pour démarrer → l'écran **AUTHORIZED USE ONLY** apparaît.
3. **Maintiens `RIGHT` ~1,5 s** pour confirmer. `LEFT` annule.
4. L'émission ne démarre qu'après cette confirmation. Elle est redemandée à
   chaque entrée dans le module.

Le scan reste libre : c'est de la reconnaissance passive.

## Navigation

| Bouton | Menu | Dans un module |
|---|---|---|
| `UP` / `DOWN` | change de module | déplace la sélection |
| `RIGHT` | ouvre le module | détails / démarrer |
| `LEFT` | — | retour (liste, puis menu) |

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
| émission deauth | rose | `input` `#FF4D8D` (couleur d'alerte) |

## Notes d'intégration (à valider sur la carte)

Je n'ai pas pu compiler/exécuter ce firmware ici (pas de toolchain ESP32 ni de
carte dans l'environnement). Ce qui reste à vérifier sur le matériel réel :

- **broches** de `config.h` conformes à ta carte ;
- **ré-entrée entre modules** : le module Deauther réinitialise entièrement le
  driver Wi-Fi (`esp_wifi_init`) à chaque entrée ; si tu passes de WiFi Scan à
  Deauther sans redémarrer, `esp_wifi_init` peut renvoyer une erreur. En cas de
  reboot au changement de module, ajoute un `esp_wifi_deinit()` au retour menu ;
- **portée / efficacité** de l'émission (dépend de l'antenne et du canal).

## Provenance

La logique de scan et d'injection vient d'un firmware fourni par l'utilisateur.
Elle est **reprise telle quelle** ; les seules modifications GHOSTBOARD sont
balisées `[GB]` dans `src/modules/deauther.cpp` :

- gate d'autorisation avant émission ;
- correction d'un dépassement de tableau (`deauth_frame[26]` → `[24]`, le
  tableau ne fait que 26 octets) ;
- SSID de l'AP unifié (le rebuild au channel-hop utilisait un autre nom) ;
- retour au menu, réinitialisation d'état, couleurs LED de la charte.
