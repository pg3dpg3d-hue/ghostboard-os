// ---------------------------------------------------------------------------
//  menu.cpp — menu racine. UP/DOWN choisit, RIGHT entre, LEFT (dans un module)
//  rend la main ici. C'est la glue qui fait des deux modules « un programme ».
// ---------------------------------------------------------------------------
#include "config.h"
#include "theme.h"
#include "module.h"
#include "menu.h"
#include "wifiscan.h"
#include "deauther.h"

namespace Menu {

// Table des modules. Ajouter une entrée ici suffit à l'exposer au menu.
static const Module MODULES[] = {
    {"WiFi Scan  (passive)", WifiScan::wifiscanSetup, WifiScan::wifiscanLoop},
    {"Deauther   (DoS)",     Deauther::deautherSetup, Deauther::deautherLoop},
};
static const int MODULE_COUNT = sizeof(MODULES) / sizeof(MODULES[0]);

static int selected = 0;
static int active = -1;          // -1 = on est dans le menu ; sinon index du module
static unsigned long lastPress = 0;
static const unsigned long debounce = 200;

static void drawMenu() {
    u8g2.clearBuffer();
    gbHeader("GHOSTBOARD");
    u8g2.setFont(u8g2_font_6x10_tr);
    for (int i = 0; i < MODULE_COUNT; i++) {
        int y = 26 + i * 12;
        if (i == selected) u8g2.drawStr(0, y, ">");
        u8g2.drawStr(10, y, MODULES[i].name);
    }
    u8g2.setFont(u8g2_font_5x8_tr);
    u8g2.drawStr(0, 63, "UP/DN move  RIGHT open");
    u8g2.sendBuffer();
    setNeoPixelColour("0");
}

void menuSetup() {
    selected = 0;
    active = -1;
    drawMenu();
}

void menuLoop() {
    // --- Dans un module : on relaie sa boucle ; true => retour menu ---------
    if (active >= 0) {
        if (MODULES[active].loop()) {
            active = -1;
            drawMenu();
        }
        return;
    }

    // --- Dans le menu : navigation -----------------------------------------
    unsigned long now = millis();
    if (now - lastPress < debounce) return;

    if (digitalRead(BUTTON_UP_PIN) == LOW) {
        selected = (selected - 1 + MODULE_COUNT) % MODULE_COUNT;
        lastPress = now;
        drawMenu();
        while (digitalRead(BUTTON_UP_PIN) == LOW);
    } else if (digitalRead(BUTTON_DOWN_PIN) == LOW) {
        selected = (selected + 1) % MODULE_COUNT;
        lastPress = now;
        drawMenu();
        while (digitalRead(BUTTON_DOWN_PIN) == LOW);
    } else if (digitalRead(BTN_PIN_RIGHT) == LOW) {
        lastPress = now;
        while (digitalRead(BTN_PIN_RIGHT) == LOW);   // évite un RIGHT fantôme dans le module
        active = selected;
        MODULES[active].setup();
    }
}

}  // namespace Menu
