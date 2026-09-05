// ---------------------------------------------------------------------------
//  authtest.cpp — test de robustesse d'un mot de passe Wi-Fi (dictionnaire).
//
//  Réimplémentation clean-room. Scanne les réseaux, laisse choisir une cible,
//  puis — APRÈS confirmation d'autorisation — tente de s'y connecter avec une
//  liste de mots de passe. Un essai réussi = mot de passe trouvé (le réseau est
//  faible). Destiné à auditer TON PROPRE réseau.
//
//  Liste embarquée volontairement courte (pas de SD ici). Quand la carte SD
//  sera câblée (phase 2), on lira un vrai dictionnaire depuis la carte.
// ---------------------------------------------------------------------------
#include "config.h"
#include "theme.h"
#include "authgate.h"
#include "authtest.h"
#include "wordlist.h"   // GB_WORDLIST / GB_WORDLIST_COUNT, générés depuis data/wordlist.txt

namespace AuthTest {

// La wordlist est embarquée depuis data/wordlist.txt (voir tools/gen-wordlist.py).
static const char *const *WORDS = GB_WORDLIST;
static const int WORD_COUNT = GB_WORDLIST_COUNT;

enum State { LIST, RUNNING, DONE };
static State state = LIST;

static int netCount = 0;
static int sel = 0, top = 0;
static const int ROWS = 5;

static int tried = 0;
static bool found = false;
static String foundPwd;
static String targetSsid;
static bool targetOpen = false;

static unsigned long lastPress = 0;
static const unsigned long debounce = 200;

// --- Affichages -------------------------------------------------------------
static void drawList() {
    u8g2.clearBuffer();
    gbHeader("Auth Test");
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
    u8g2.drawStr(0, 63, "U/D  RIGHT test  LEFT");
    u8g2.sendBuffer();
    setNeoPixelColour("scan");
}

static void drawProgress() {
    u8g2.clearBuffer();
    gbHeader("Auth Test");
    u8g2.setFont(u8g2_font_5x8_tr);
    String t = "SSID: " + targetSsid.substring(0, 16);
    u8g2.drawStr(0, 24, t.c_str());
    char buf[26];
    snprintf(buf, sizeof(buf), "Trying: %d / %d", tried, WORD_COUNT);
    u8g2.drawStr(0, 34, buf);
    if (tried > 0 && tried <= WORD_COUNT)
        u8g2.drawStr(0, 44, WORDS[tried - 1]);
    // Barre de progression.
    u8g2.drawFrame(0, 48, 128, 6);
    if (WORD_COUNT) u8g2.drawBox(1, 49, (126 * tried) / WORD_COUNT, 4);
    u8g2.drawStr(0, 63, "LEFT: stop");
    u8g2.sendBuffer();
    setNeoPixelColour("attack");
}

static void drawDone() {
    u8g2.clearBuffer();
    gbHeader("Auth Test");
    u8g2.setFont(u8g2_font_6x10_tr);
    if (found) {
        u8g2.drawStr(0, 28, "WEAK — key found:");
        u8g2.drawStr(0, 42, foundPwd.c_str());
        setNeoPixelColour("attack");
    } else {
        u8g2.drawStr(0, 28, "Not in list.");
        u8g2.setFont(u8g2_font_5x8_tr);
        u8g2.drawStr(0, 42, "Key resisted the test.");
        setNeoPixelColour("ok");
    }
    u8g2.setFont(u8g2_font_5x8_tr);
    u8g2.drawStr(0, 63, "LEFT: back");
    u8g2.sendBuffer();
}

// Tente un mot de passe ; renvoie true si la connexion aboutit.
static bool tryPassword(const char *ssid, const char *pwd) {
    WiFi.disconnect(true, true);
    delay(100);
    WiFi.begin(ssid, pwd);
    unsigned long start = millis();
    // ~7 s max par essai ; on sort tôt sur succès ou échec franc.
    while (millis() - start < 7000) {
        wl_status_t s = WiFi.status();
        if (s == WL_CONNECTED) return true;
        if (s == WL_CONNECT_FAILED || s == WL_NO_SSID_AVAIL) return false;
        // Abandon manuel en cours d'essai.
        if (digitalRead(BTN_PIN_LEFT) == LOW) return false;
        delay(100);
    }
    return false;
}

void setup() {
    state = LIST;
    sel = top = 0;
    tried = 0;
    found = false;
    foundPwd = "";
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    netCount = WiFi.scanNetworks();
    drawList();
}

bool loop() {
    unsigned long now = millis();

    if (state == RUNNING) {
        // Un essai par passage de boucle, pour garder l'écran réactif.
        if (tried < WORD_COUNT && !found) {
            drawProgress();
            if (tryPassword(targetSsid.c_str(), WORDS[tried])) {
                found = true;
                foundPwd = WORDS[tried];
            }
            tried++;
            if (digitalRead(BTN_PIN_LEFT) == LOW) {   // stop demandé
                while (digitalRead(BTN_PIN_LEFT) == LOW);
                WiFi.disconnect(true, true);
                state = DONE;
                drawDone();
                return false;
            }
        }
        if (found || tried >= WORD_COUNT) {
            WiFi.disconnect(true, true);
            state = DONE;
            drawDone();
        }
        return false;
    }

    if (state == DONE) {
        if (digitalRead(BTN_PIN_LEFT) == LOW) {
            while (digitalRead(BTN_PIN_LEFT) == LOW);
            WiFi.mode(WIFI_OFF);
            setNeoPixelColour("0");
            return true;
        }
        return false;
    }

    // --- state == LIST ------------------------------------------------------
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
        targetOpen = (WiFi.encryptionType(sel) == WIFI_AUTH_OPEN);
        if (targetOpen) {
            // Réseau ouvert : rien à deviner.
            found = false;
            tried = 0;
            state = DONE;
            drawDone();
            return false;
        }
        // Message de prévention + confirmation avant le moindre essai.
        if (AuthGate::confirm("Auth Test", "Guesses the key of", "YOUR OWN network.")) {
            tried = 0;
            found = false;
            state = RUNNING;
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

}  // namespace AuthTest
