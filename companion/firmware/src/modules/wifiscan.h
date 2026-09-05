// ---------------------------------------------------------------------------
//  wifiscan.h — module de reconnaissance Wi-Fi PASSIVE (aucun paquet émis).
// ---------------------------------------------------------------------------
#pragma once

namespace WifiScan {
void wifiscanSetup();
bool wifiscanLoop();   // true => retour au menu
}
