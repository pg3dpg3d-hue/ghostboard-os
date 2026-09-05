// ---------------------------------------------------------------------------
//  authgate.h — confirmation d'autorisation avant une émission active.
//
//  Tout module qui ÉMET (deauth, beacon spam, evil portal, BLE spam) passe par
//  ce garde-fou avant la première émission : écran d'avertissement + appui long
//  sur RIGHT. C'est la version partagée de la barrière du module Deauther.
// ---------------------------------------------------------------------------
#pragma once

namespace AuthGate {
// Affiche l'avertissement et bloque jusqu'à décision de l'utilisateur.
//   line1/line2 : deux lignes décrivant l'acte (ex. "Beacon spam floods",
//                 "fake SSIDs on air").
// Renvoie true si confirmé (RIGHT maintenu ~1,5 s), false si annulé (LEFT).
bool confirm(const char *title, const char *line1, const char *line2);
}
