// ---------------------------------------------------------------------------
//  beaconspam.h — émission de fausses balises 802.11 (faux réseaux).
//
//  ⚠️  ÉMISSION ACTIVE. Inonde l'air de faux SSID. Usage autorisé uniquement
//      (ton propre matériel / autorisation écrite). Gaté avant émission.
// ---------------------------------------------------------------------------
#pragma once

namespace BeaconSpam {
void setup();
bool loop();
}
