// ---------------------------------------------------------------------------
//  beaconspam.cpp — émission de fausses balises 802.11.
//
//  Réimplémentation clean-room (aucun code ESP-HACK). Construit une trame
//  beacon standard et diffuse une liste de SSID en changeant de canal. Passe
//  par le gate d'autorisation partagé avant toute émission.
// ---------------------------------------------------------------------------
#include "config.h"
#include "theme.h"
#include "authgate.h"
#include "beaconspam.h"

namespace BeaconSpam {

// Faux SSID diffusés (au choix, sans prétention). Modifiable librement.
static const char *SSIDS[] = {
    "GHOSTBOARD", "FBI Surveillance Van", "Pretty Fly for a WiFi",
    "Loading...", "Mom Use This One", "Hidden Network",
    "Virus.exe", "Tell My WiFi Love Her", "Area 51",
    "It Hurts When IP",
};
static const int SSID_COUNT = sizeof(SSIDS) / sizeof(SSIDS[0]);

static bool running = false;
static uint32_t frames = 0;
static uint8_t channel = 1;
static unsigned long lastHop = 0;

// NB : le contournement du sanity-check (ieee80211_raw_frame_sanity_check) est
// défini une seule fois, dans deauther.cpp ; il vaut pour tout le firmware.

// Squelette d'une trame beacon 802.11. Les octets SSID/BSSID/canal sont
// renseignés à l'émission.
static uint8_t tmpl[] = {
    0x80, 0x00,                                     // frame control : beacon
    0x00, 0x00,                                     // duration
    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,             // destination : broadcast
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,             // source (MAC aléatoire)
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,             // BSSID (= source)
    0x00, 0x00,                                     // seq/frag
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, // timestamp
    0x64, 0x00,                                     // beacon interval (100 TU)
    0x01, 0x04,                                     // capability info
    0x00, 0x00,                                     // tag SSID : id, longueur (rempli)
};
// Tag "supported rates" + tag "DS parameter" (canal), ajoutés après le SSID.
static const uint8_t rates[] = {0x01, 0x08, 0x82, 0x84, 0x8B, 0x96, 0x24, 0x30, 0x48, 0x6C};

static void sendBeacon(const char *ssid) {
    uint8_t pkt[128];
    int n = sizeof(tmpl);
    memcpy(pkt, tmpl, n);

    // MAC source/BSSID aléatoire mais localement administrée.
    uint8_t mac[6] = {0x02, (uint8_t)random(256), (uint8_t)random(256),
                      (uint8_t)random(256), (uint8_t)random(256), (uint8_t)random(256)};
    memcpy(&pkt[10], mac, 6);
    memcpy(&pkt[16], mac, 6);

    int slen = strlen(ssid);
    if (slen > 32) slen = 32;
    pkt[37] = slen;                 // longueur du tag SSID
    memcpy(&pkt[38], ssid, slen);
    n = 38 + slen;

    memcpy(&pkt[n], rates, sizeof(rates));   // supported rates
    n += sizeof(rates);
    pkt[n++] = 0x03;                // DS parameter set
    pkt[n++] = 0x01;
    pkt[n++] = channel;             // canal courant

    esp_wifi_80211_tx(WIFI_IF_AP, pkt, n, false);
    frames++;
}

static void drawStatus() {
    u8g2.clearBuffer();
    gbHeader("Beacon Spam");
    u8g2.setFont(u8g2_font_5x8_tr);
    u8g2.drawStr(0, 26, running ? "Status: BROADCASTING" : "Status: idle");
    char buf[24];
    snprintf(buf, sizeof(buf), "SSIDs: %d", SSID_COUNT);
    u8g2.drawStr(0, 36, buf);
    snprintf(buf, sizeof(buf), "Frames: %lu  Ch:%d", (unsigned long)frames, channel);
    u8g2.drawStr(0, 46, buf);
    u8g2.drawStr(0, 63, running ? "RIGHT stop   LEFT back" : "RIGHT start  LEFT back");
    u8g2.sendBuffer();
    setNeoPixelColour(running ? "attack" : "0");
}

void setup() {
    running = false;
    frames = 0;
    channel = 1;
    WiFi.mode(WIFI_MODE_AP);
    esp_wifi_start();
    drawStatus();
}

bool loop() {
    // RIGHT : démarrer (via gate) / arrêter.
    if (digitalRead(BTN_PIN_RIGHT) == LOW) {
        while (digitalRead(BTN_PIN_RIGHT) == LOW);
        if (running) {
            running = false;
        } else if (AuthGate::confirm("Beacon Spam", "Floods fake SSIDs", "on the air.")) {
            running = true;
        }
        drawStatus();
    }

    if (digitalRead(BTN_PIN_LEFT) == LOW) {
        while (digitalRead(BTN_PIN_LEFT) == LOW);
        running = false;
        WiFi.mode(WIFI_OFF);
        setNeoPixelColour("0");
        return true;
    }

    if (running) {
        for (int i = 0; i < SSID_COUNT; i++) sendBeacon(SSIDS[i]);
        // Saut de canal ~toutes les 250 ms pour couvrir la bande 2,4 GHz.
        if (millis() - lastHop > 250) {
            channel = (channel % 11) + 1;
            esp_wifi_set_channel(channel, WIFI_SECOND_CHAN_NONE);
            lastHop = millis();
        }
        static unsigned long lastDraw = 0;
        if (millis() - lastDraw > 500) { drawStatus(); lastDraw = millis(); }
    }
    return false;
}

}  // namespace BeaconSpam
