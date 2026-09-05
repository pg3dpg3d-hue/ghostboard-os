// ---------------------------------------------------------------------------
//  wifitry.cpp — tentative de connexion WPA partagée (Auth Test + Brute Force).
// ---------------------------------------------------------------------------
#include "config.h"
#include "wifitry.h"

namespace WifiTry {

bool attempt(const char *ssid, const char *pwd, unsigned long timeoutMs) {
    WiFi.disconnect(true, true);
    delay(80);
    WiFi.begin(ssid, pwd);
    unsigned long start = millis();
    while (millis() - start < timeoutMs) {
        wl_status_t s = WiFi.status();
        if (s == WL_CONNECTED) return true;
        // Échec franc : mauvaise clé ou AP hors de portée -> on n'attend pas.
        if (s == WL_CONNECT_FAILED || s == WL_NO_SSID_AVAIL) return false;
        if (digitalRead(BTN_PIN_LEFT) == LOW) return false;   // abandon
        delay(80);
    }
    return false;
}

}  // namespace WifiTry
