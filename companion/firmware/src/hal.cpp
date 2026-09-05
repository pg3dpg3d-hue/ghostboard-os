// ---------------------------------------------------------------------------
//  hal.cpp — couche matérielle : écran, boutons, LED NeoPixel.
//
//  Tout ce qui touche au matériel est ici, pour que les modules (WifiScan,
//  Deauther) restent de la pure logique. Les couleurs viennent de
//  theme_colors.h, lui-même généré depuis brand/palette.toml.
// ---------------------------------------------------------------------------
#include "config.h"
#include "theme_colors.h"
#include <Adafruit_NeoPixel.h>

// Écran partagé (déclaré extern dans config.h). Rotation 0 par défaut.
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

static Adafruit_NeoPixel g_pixel(NEOPIXEL_COUNT, NEOPIXEL_PIN, NEO_GRB + NEO_KHZ800);

void setNeoPixelColour(const String &name) {
    uint32_t c;
    // "white"/"orange" sont conservés comme alias du code d'origine, mais
    // pointent désormais sur les couleurs de la charte GHOSTBOARD.
    if (name == "0" || name == "off") {
        c = g_pixel.Color(GB_NEO_OFF);
    } else if (name == "scan" || name == "white") {
        c = g_pixel.Color(GB_NEO_SCAN);
    } else if (name == "attack" || name == "orange") {
        c = g_pixel.Color(GB_NEO_ATTACK);
    } else if (name == "ok") {
        c = g_pixel.Color(GB_NEO_OK);
    } else {
        c = g_pixel.Color(GB_NEO_OFF);
    }
    g_pixel.setPixelColor(0, c);
    g_pixel.show();
}

void ghostHardwareInit() {
    u8g2.begin();

    pinMode(BUTTON_UP_PIN, INPUT_PULLUP);
    pinMode(BUTTON_DOWN_PIN, INPUT_PULLUP);
    pinMode(BTN_PIN_RIGHT, INPUT_PULLUP);
    pinMode(BTN_PIN_LEFT, INPUT_PULLUP);

    g_pixel.begin();
    g_pixel.setBrightness(40);   // 4" en intérieur : inutile d'éblouir
    setNeoPixelColour("0");
}
