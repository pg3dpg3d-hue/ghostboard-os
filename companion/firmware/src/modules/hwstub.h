// ---------------------------------------------------------------------------
//  hwstub.h — modules « à matériel externe » en attente d'implémentation.
//
//  Phase 1 : ces modules détectent l'absence de leur puce et affichent un
//  écran « Connect <puce> ». Phase 2 : remplacés par les vrais modules
//  (SubGHz/CC1101, IR, NRF24, NFC, iButton).
// ---------------------------------------------------------------------------
#pragma once
#include "module.h"

namespace HwStub {
extern const Module subghz[];
extern const Module infrared[];
extern const Module nrf24[];
extern const Module nfc[];
extern const Module ibutton[];
int subghzCount();
int infraredCount();
int nrf24Count();
int nfcCount();
int ibuttonCount();
}
