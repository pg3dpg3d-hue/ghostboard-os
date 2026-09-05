// ---------------------------------------------------------------------------
//  main.cpp — point d'entrée du firmware compagnon GHOSTBOARD.
//
//  Amorçage matériel, splash d'identité, puis le menu prend la main. Toute la
//  logique vit dans les modules (src/modules/) ; ici on ne fait que câbler.
// ---------------------------------------------------------------------------
#include "config.h"
#include "theme.h"
#include "modules/menu.h"

void setup() {
    Serial.begin(115200);
    ghostHardwareInit();   // écran + boutons + LED
    gbBootSplash();        // identité GHOSTBOARD
    Menu::menuSetup();
}

void loop() {
    Menu::menuLoop();
}
