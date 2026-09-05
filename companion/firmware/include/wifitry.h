// ---------------------------------------------------------------------------
//  wifitry.h — tentative de connexion WPA (partagée par Auth Test et Brute).
// ---------------------------------------------------------------------------
#pragma once

namespace WifiTry {
// Tente de s'associer à `ssid` avec `pwd`. Renvoie true si connecté avant le
// timeout. Sort tôt sur échec franc, et si LEFT est pressé (abandon).
bool attempt(const char *ssid, const char *pwd, unsigned long timeoutMs = 7000);
}
