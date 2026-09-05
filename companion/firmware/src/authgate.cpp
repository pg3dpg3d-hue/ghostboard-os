// ---------------------------------------------------------------------------
//  authgate.cpp — confirmation d'autorisation partagée.
// ---------------------------------------------------------------------------
#include "authgate.h"
#include "config.h"
#include "theme.h"

namespace AuthGate {

static const unsigned long HOLD_MS = 1500;

static void draw(const char *title, const char *l1, const char *l2, int pct) {
    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_6x10_tr);
    u8g2.drawStr(0, 10, title);
    u8g2.drawHLine(0, 13, 128);
    u8g2.setFont(u8g2_font_5x8_tr);
    u8g2.drawStr(0, 24, "AUTHORIZED USE ONLY.");
    u8g2.drawStr(0, 33, l1);
    u8g2.drawStr(0, 42, l2);
    // Jauge de maintien pour matérialiser l'appui long.
    u8g2.drawFrame(0, 46, 128, 6);
    if (pct > 0) u8g2.drawBox(1, 47, (126 * pct) / 100, 4);
    u8g2.drawStr(0, 63, "HOLD RIGHT ok   LEFT no");
    u8g2.sendBuffer();
}

bool confirm(const char *title, const char *line1, const char *line2) {
    setNeoPixelColour("attack");
    draw(title, line1, line2, 0);

    unsigned long holdStart = 0;
    for (;;) {
        if (digitalRead(BTN_PIN_LEFT) == LOW) {          // annulation
            while (digitalRead(BTN_PIN_LEFT) == LOW);
            setNeoPixelColour("0");
            return false;
        }
        if (digitalRead(BTN_PIN_RIGHT) == LOW) {          // maintien
            if (holdStart == 0) holdStart = millis();
            unsigned long held = millis() - holdStart;
            if (held >= HOLD_MS) {
                while (digitalRead(BTN_PIN_RIGHT) == LOW);
                return true;                              // LED reste "attack"
            }
            draw(title, line1, line2, (int)((held * 100) / HOLD_MS));
        } else {
            if (holdStart != 0) { holdStart = 0; draw(title, line1, line2, 0); }
        }
        delay(10);
    }
}

}  // namespace AuthGate
