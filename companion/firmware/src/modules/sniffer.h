// ---------------------------------------------------------------------------
//  sniffer.h — capture passive (mode promiscuous) : comptage de trames.
//  Aucune émission : reconnaissance. Pas de gate.
// ---------------------------------------------------------------------------
#pragma once

namespace Sniffer {
void setup();
bool loop();
}
