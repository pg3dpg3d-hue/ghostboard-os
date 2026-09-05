// ---------------------------------------------------------------------------
//  handshake.h — capture d'un handshake WPA (EAPOL), pour crack HORS-LIGNE.
//
//  ⚠️  ÉMET des trames deauth (force une reconnexion pour capturer le handshake)
//      puis DUMPE les trames EAPOL sur le port série. Gaté par un écran de
//      prévention. Ne casse rien lui-même : le crack se fait ensuite sur le
//      deck, hors-ligne, avec `ghost-crack`. Destiné à TON réseau.
// ---------------------------------------------------------------------------
#pragma once

namespace Handshake {
void setup();
bool loop();
}
