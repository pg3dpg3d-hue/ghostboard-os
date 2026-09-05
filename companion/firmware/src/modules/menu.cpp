// ---------------------------------------------------------------------------
//  menu.cpp — menu racine à deux niveaux : catégories -> modules -> module.
//
//  C'est la glue qui fait de tous les modules « un seul programme ». Chaque
//  catégorie regroupe des modules ; un module à matériel absent affiche un
//  écran « Connect <puce> » (voir hwstub.cpp).
// ---------------------------------------------------------------------------
#include "config.h"
#include "theme.h"
#include "module.h"
#include "menu.h"
#include "wifiscan.h"
#include "deauther.h"
#include "beaconspam.h"
#include "evilportal.h"
#include "sniffer.h"
#include "blespam.h"
#include "hwstub.h"

namespace Menu {

// --- Modules par catégorie ---------------------------------------------------
static const Module WIFI[] = {
    {"Scan (passive)",  WifiScan::wifiscanSetup, WifiScan::wifiscanLoop},
    {"Deauther (DoS)",  Deauther::deautherSetup, Deauther::deautherLoop},
    {"Beacon Spam",     BeaconSpam::setup,       BeaconSpam::loop},
    {"Evil Portal",     EvilPortal::setup,       EvilPortal::loop},
    {"Sniffer",         Sniffer::setup,          Sniffer::loop},
};
static const Module BLE[] = {
    {"BLE Spam",        BleSpam::setup,          BleSpam::loop},
};

// --- Catégories --------------------------------------------------------------
static const Category CATS[] = {
    {"WiFi",       WIFI, sizeof(WIFI) / sizeof(WIFI[0])},
    {"Bluetooth",  BLE,  sizeof(BLE) / sizeof(BLE[0])},
    {"SubGHz",     HwStub::subghz,   1},
    {"Infrared",   HwStub::infrared, 1},
    {"NRF24",      HwStub::nrf24,    1},
    {"NFC",        HwStub::nfc,      1},
    {"iButton",    HwStub::ibutton,  1},
};
static const int CAT_COUNT = sizeof(CATS) / sizeof(CATS[0]);

// --- État de navigation ------------------------------------------------------
static int level = 0;        // 0 catégories, 1 modules, 2 dans un module
static int catSel = 0, catTop = 0;
static int modSel = 0, modTop = 0;
static int activeCat = 0;
static unsigned long lastPress = 0;
static const unsigned long debounce = 200;
static const int ROWS = 4;   // lignes visibles sous l'en-tête

// Dessine une liste défilante générique.
static void drawList(const char *title, int count, int sel, int top,
                     const char *(*label)(int)) {
    u8g2.clearBuffer();
    gbHeader(title);
    u8g2.setFont(u8g2_font_6x10_tr);
    for (int i = 0; i < ROWS; i++) {
        int idx = top + i;
        if (idx >= count) break;
        int y = 26 + i * 11;
        if (idx == sel) u8g2.drawStr(0, y, ">");
        u8g2.drawStr(10, y, label(idx));
    }
    u8g2.setFont(u8g2_font_5x8_tr);
    u8g2.drawStr(0, 63, level == 0 ? "U/D  RIGHT open" : "U/D  RIGHT open  LEFT back");
    u8g2.sendBuffer();
    setNeoPixelColour("0");
}

static const char *catLabel(int i) { return CATS[i].name; }
static const char *modLabel(int i) { return CATS[activeCat].modules[i].name; }

static void draw() {
    if (level == 0) drawList("GHOSTBOARD", CAT_COUNT, catSel, catTop, catLabel);
    else if (level == 1) drawList(CATS[activeCat].name, CATS[activeCat].count,
                                  modSel, modTop, modLabel);
}

// Défilement d'un curseur dans une fenêtre de ROWS lignes.
static void moveSel(int &sel, int &top, int count, int delta) {
    sel = (sel + delta + count) % count;
    if (sel < top) top = sel;
    if (sel >= top + ROWS) top = sel - ROWS + 1;
}

void menuSetup() {
    level = 0; catSel = catTop = 0; modSel = modTop = 0;
    draw();
}

void menuLoop() {
    // Dans un module : on relaie sa boucle.
    if (level == 2) {
        if (CATS[activeCat].modules[modSel].loop()) {
            level = 1;
            draw();
        }
        return;
    }

    unsigned long now = millis();
    if (now - lastPress < debounce) return;

    if (digitalRead(BUTTON_UP_PIN) == LOW) {
        lastPress = now;
        if (level == 0) moveSel(catSel, catTop, CAT_COUNT, -1);
        else            moveSel(modSel, modTop, CATS[activeCat].count, -1);
        draw();
        while (digitalRead(BUTTON_UP_PIN) == LOW);
    } else if (digitalRead(BUTTON_DOWN_PIN) == LOW) {
        lastPress = now;
        if (level == 0) moveSel(catSel, catTop, CAT_COUNT, +1);
        else            moveSel(modSel, modTop, CATS[activeCat].count, +1);
        draw();
        while (digitalRead(BUTTON_DOWN_PIN) == LOW);
    } else if (digitalRead(BTN_PIN_RIGHT) == LOW) {
        lastPress = now;
        while (digitalRead(BTN_PIN_RIGHT) == LOW);   // évite un RIGHT fantôme
        if (level == 0) {
            activeCat = catSel;
            modSel = modTop = 0;
            level = 1;
            draw();
        } else {
            level = 2;
            CATS[activeCat].modules[modSel].setup();
        }
    } else if (digitalRead(BTN_PIN_LEFT) == LOW) {
        lastPress = now;
        while (digitalRead(BTN_PIN_LEFT) == LOW);
        if (level == 1) { level = 0; draw(); }       // retour aux catégories
    }
}

}  // namespace Menu
