// ---------------------------------------------------------------------------
//  bruteforce.h — génère et teste des combinaisons à la volée (brute-force WPA).
//
//  ⚠️  ATTAQUE EN LIGNE. Génère les combinaisons instantanément, mais chaque
//      essai WPA prend ~4 s : exploitable seulement sur un très petit espace.
//      Destiné à TON réseau. Gaté par un écran de prévention.
// ---------------------------------------------------------------------------
#pragma once

namespace BruteForce {
void setup();
bool loop();
}
