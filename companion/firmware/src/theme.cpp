// ---------------------------------------------------------------------------
//  theme.cpp — implémentation de l'habillage OLED partagé.
// ---------------------------------------------------------------------------
#include "theme.h"

void gbBootSplash() {
    // Un balayage court : la LED passe par l'accent puis s'éteint, l'écran
    // affiche l'identité. ~600 ms, non bloquant au-delà.
    setNeoPixelColour("scan");
    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_7x14B_tr);
    u8g2.drawStr(18, 30, "GHOSTBOARD");
    u8g2.setFont(u8g2_font_5x8_tr);
    u8g2.drawStr(30, 44, "companion");
    u8g2.drawHLine(0, 50, 128);
    u8g2.sendBuffer();
    delay(600);
    setNeoPixelColour("0");
}

void gbHeader(const char *title) {
    u8g2.setFont(u8g2_font_6x10_tr);
    u8g2.drawStr(0, 10, title);
    u8g2.drawHLine(0, 13, 128);   // filet de séparation, style GHOSTBOARD
}
