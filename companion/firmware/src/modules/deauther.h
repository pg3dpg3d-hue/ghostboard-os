// ---------------------------------------------------------------------------
//  deauther.h — module d'émission de trames 802.11 deauth.
//
//  ⚠️  OUTIL DE DÉNI DE SERVICE. Émettre des trames deauth déconnecte de force
//      les clients d'un point d'accès. Ne l'utiliser QUE sur un réseau que tu
//      possèdes ou pour lequel tu as une autorisation écrite. Dans beaucoup de
//      pays, l'émission contre un tiers est illégale (brouillage / interférence
//      intentionnelle). Un écran de confirmation protège la première émission.
// ---------------------------------------------------------------------------
#pragma once

namespace Deauther {
void deautherSetup();
bool deautherLoop();   // true => retour au menu
}
