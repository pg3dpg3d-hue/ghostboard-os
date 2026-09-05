// ---------------------------------------------------------------------------
//  sniffer.cpp — capture passive Wi-Fi (mode promiscuous).
//
//  Réimplémentation clean-room. Compte les trames par grande famille (gestion
//  / contrôle / données) sur le canal courant, avec saut de canal automatique.
//  Purement réceptif : rien n'est émis, aucun payload n'est stocké — c'est un
//  compteur d'activité, pas un enregistreur.
// ---------------------------------------------------------------------------
#include "config.h"
#include "theme.h"
#include "sniffer.h"

namespace Sniffer {

static volatile uint32_t mgmt = 0, ctrl = 0, data = 0;
static uint8_t channel = 1;
static unsigned long lastHop = 0;
static bool autohop = true;

// Callback promiscuous : on ne lit que le type de trame (2 bits du 1er octet).
static void onPacket(void *buf, wifi_promiscuous_pkt_type_t type) {
    switch (type) {
        case WIFI_PKT_MGMT: mgmt++; break;
        case WIFI_PKT_CTRL: ctrl++; break;
        case WIFI_PKT_DATA: data++; break;
        default: break;
    }
}

static void drawStatus() {
    u8g2.clearBuffer();
    gbHeader("WiFi Sniffer");
    u8g2.setFont(u8g2_font_5x8_tr);
    char buf[26];
    snprintf(buf, sizeof(buf), "Channel: %d %s", channel, autohop ? "(hop)" : "(lock)");
    u8g2.drawStr(0, 24, buf);
    snprintf(buf, sizeof(buf), "Mgmt: %lu", (unsigned long)mgmt);
    u8g2.drawStr(0, 34, buf);
    snprintf(buf, sizeof(buf), "Ctrl: %lu", (unsigned long)ctrl);
    u8g2.drawStr(0, 42, buf);
    snprintf(buf, sizeof(buf), "Data: %lu", (unsigned long)data);
    u8g2.drawStr(0, 50, buf);
    u8g2.drawStr(0, 63, "U/D chan  RIGHT hop  LEFT");
    u8g2.sendBuffer();
    setNeoPixelColour("scan");
}

static void setChannel(uint8_t c) {
    channel = c;
    esp_wifi_set_channel(channel, WIFI_SECOND_CHAN_NONE);
}

void setup() {
    mgmt = ctrl = data = 0;
    channel = 1;
    autohop = true;
    WiFi.mode(WIFI_MODE_NULL);
    esp_wifi_start();
    esp_wifi_set_promiscuous(true);
    esp_wifi_set_promiscuous_rx_cb(&onPacket);
    setChannel(channel);
    drawStatus();
}

bool loop() {
    unsigned long now = millis();

    if (digitalRead(BUTTON_UP_PIN) == LOW) {
        while (digitalRead(BUTTON_UP_PIN) == LOW);
        autohop = false;
        setChannel((channel % 13) + 1);
        drawStatus();
    } else if (digitalRead(BUTTON_DOWN_PIN) == LOW) {
        while (digitalRead(BUTTON_DOWN_PIN) == LOW);
        autohop = false;
        setChannel(channel <= 1 ? 13 : channel - 1);
        drawStatus();
    } else if (digitalRead(BTN_PIN_RIGHT) == LOW) {
        while (digitalRead(BTN_PIN_RIGHT) == LOW);
        autohop = !autohop;               // bascule saut auto / canal figé
        drawStatus();
    } else if (digitalRead(BTN_PIN_LEFT) == LOW) {
        while (digitalRead(BTN_PIN_LEFT) == LOW);
        esp_wifi_set_promiscuous(false);
        WiFi.mode(WIFI_OFF);
        setNeoPixelColour("0");
        return true;
    }

    if (autohop && now - lastHop > 400) {
        setChannel((channel % 13) + 1);
        lastHop = now;
    }

    static unsigned long lastDraw = 0;
    if (now - lastDraw > 400) { drawStatus(); lastDraw = now; }
    return false;
}

}  // namespace Sniffer
