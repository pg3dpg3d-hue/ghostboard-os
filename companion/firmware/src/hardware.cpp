// ---------------------------------------------------------------------------
//  hardware.cpp — présence des périphériques optionnels + écran « Connect ».
// ---------------------------------------------------------------------------
#include "hardware.h"
#include "theme.h"
#include <string.h>

bool gbHardwarePresent(const char *chip) {
    // La présence est décidée à la compilation (macro HW_<chip> dans
    // hardware.h) : ces puces sont sur bus SPI/1-Wire, pas hot-plug, et sans
    // brochage défini il n'y a rien à sonder.
    if (!strcmp(chip, "CC1101")) {
#ifdef HW_CC1101
        return true;
#else
        return false;
#endif
    }
    if (!strcmp(chip, "IR")) {
#ifdef HW_IR
        return true;
#else
        return false;
#endif
    }
    if (!strcmp(chip, "NRF24")) {
#ifdef HW_NRF24
        return true;
#else
        return false;
#endif
    }
    if (!strcmp(chip, "NFC")) {
#ifdef HW_NFC
        return true;
#else
        return false;
#endif
    }
    if (!strcmp(chip, "IBUTTON")) {
#ifdef HW_IBUTTON
        return true;
#else
        return false;
#endif
    }
    return false;
}

void gbDrawHardwareGate(const char *chip, const char *needs) {
    u8g2.clearBuffer();
    gbHeader(chip);
    u8g2.setFont(u8g2_font_5x8_tr);
    u8g2.drawStr(0, 26, "Hardware not wired.");
    u8g2.drawStr(0, 36, "Needs:");
    u8g2.drawStr(0, 46, needs);
    u8g2.drawStr(0, 63, "LEFT: back");
    u8g2.sendBuffer();
    setNeoPixelColour("0");
}
