// ---------------------------------------------------------------------------
//  authtest.h — test de robustesse d'un mot de passe Wi-Fi (dictionnaire).
//
//  ⚠️  ATTAQUE PAR DICTIONNAIRE EN LIGNE. Tente de s'authentifier à un réseau
//      WPA avec une liste de mots de passe. Destiné à tester TON PROPRE réseau.
//      S'authentifier sans autorisation à un réseau tiers est un accès illégal.
//      Gaté par un écran de prévention avant tout essai.
// ---------------------------------------------------------------------------
#pragma once

namespace AuthTest {
void setup();
bool loop();
}
