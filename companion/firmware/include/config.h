// ---------------------------------------------------------------------------
//  config.h — câblage et objets globaux de la carte compagnon GHOSTBOARD.
//
//  ⚠️  LES BROCHES CI-DESSOUS DÉPENDENT DE TA CARTE. Vérifie-les avant de
//      flasher : un mauvais brochage n'endommage rien mais l'écran/les
//      boutons resteront muets. Valeurs par défaut = ESP32 WROOM + OLED I2C
//      SSD1306 128x64 + 4 boutons + 1 NeoPixel. Adapte pour ta carte (Bruce,
//      CYD, T-Display, etc.).
//
//  Ce fichier remplace le config.h / icon.h attendus par le code d'origine :
//  il rassemble tout ce que les modules supposent présent (u8g2, boutons,
//  setNeoPixelColour, en-têtes Wi-Fi/ESP-IDF).
// ---------------------------------------------------------------------------
#pragma once

#include <Arduino.h>
#include <WiFi.h>
#include <U8g2lib.h>

// En-têtes ESP-IDF utilisés par le module Deauther (injection 802.11 brute).
extern "C" {
#include "esp_wifi.h"
#include "esp_err.h"
#include "nvs_flash.h"
}

// --- Broches des boutons -----------------------------------------------------
//  INPUT_PULLUP : bouton relié à la masse, LOW = appuyé.
#ifndef BUTTON_UP_PIN
#define BUTTON_UP_PIN    32
#endif
#ifndef BUTTON_DOWN_PIN
#define BUTTON_DOWN_PIN  33
#endif
#ifndef BTN_PIN_LEFT
#define BTN_PIN_LEFT     25
#endif
#ifndef BTN_PIN_RIGHT
#define BTN_PIN_RIGHT    26
#endif

// --- NeoPixel ----------------------------------------------------------------
#ifndef NEOPIXEL_PIN
#define NEOPIXEL_PIN     27
#endif
#ifndef NEOPIXEL_COUNT
#define NEOPIXEL_COUNT   1
#endif

// --- Écran OLED I2C (SSD1306 128x64) -----------------------------------------
//  Objet u8g2 partagé par tous les modules. Défini dans hal.cpp.
//  Pour un écran SPI ou un contrôleur différent, remplace le type ici et
//  l'instanciation dans hal.cpp — c'est le seul endroit à toucher.
extern U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2;

// --- API LED (implémentée dans hal.cpp) --------------------------------------
//  Conserve l'API "par nom" du code d'origine. Noms reconnus :
//     "0"/"off"  éteint      "scan"    accent violet (activité)
//     "attack"   rose alerte "ok"      vert confirmation
//     "white"    alias de "scan"  (compat code d'origine)
//     "orange"   alias de "attack"(compat code d'origine)
void setNeoPixelColour(const String &name);

// --- Initialisation matérielle commune (hal.cpp) -----------------------------
void ghostHardwareInit();   // écran + boutons + LED, une seule fois au boot
