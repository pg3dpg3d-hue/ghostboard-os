// ---------------------------------------------------------------------------
//  hardware.h — broches et présence des périphériques OPTIONNELS.
//
//  Ta carte de base = ESP32 + OLED + boutons + NeoPixel. Les modules SubGHz,
//  IR, NRF24, NFC et iButton exigent une puce supplémentaire. Ce fichier
//  centralise leur brochage (à définir quand tu câbles la puce) et un garde-
//  fou d'affichage commun : un module à matériel absent montre un écran
//  « Connect <puce> » au lieu de planter ou d'émettre dans le vide.
//
//  Convention : tant que la macro de broche n'est pas définie ci-dessous, le
//  module se considère « non câblé » et reste inerte. Décommente/renseigne les
//  broches quand la puce est présente, puis recompile.
// ---------------------------------------------------------------------------
#pragma once

#include "config.h"

// --- CC1101 (SubGHz 315/433/868/915 MHz) — SPI ------------------------------
// #define HW_CC1101
// #define CC1101_SCK   18
// #define CC1101_MISO  19
// #define CC1101_MOSI  23
// #define CC1101_CS     5
// #define CC1101_GDO0  22
// #define CC1101_GDO2  21

// --- Infrarouge — LED TX + récepteur démodulé -------------------------------
// #define HW_IR
// #define IR_TX_PIN     4
// #define IR_RX_PIN    15

// --- NRF24L01 (2,4 GHz) — SPI -----------------------------------------------
// #define HW_NRF24
// #define NRF24_CE     16
// #define NRF24_CS     17

// --- NFC ST25R3916 — SPI ----------------------------------------------------
// #define HW_NFC
// #define NFC_CS       13

// --- iButton / 1-Wire -------------------------------------------------------
// #define HW_IBUTTON
// #define IBUTTON_PIN  14

// --- Carte SD (captures, portails, journaux) — SPI --------------------------
// #define HW_SD
// #define SD_CS        27

// ---------------------------------------------------------------------------
//  Garde-fou commun. Un module dont le matériel n'est pas compilé appelle
//  gbHardwareGate("CC1101") au setup : l'écran affiche quoi câbler, et loop()
//  n'a plus qu'à renvoyer l'appui LEFT. Renvoie true si le matériel est
//  présent (le module peut continuer), false s'il faut afficher le gate.
// ---------------------------------------------------------------------------
bool gbHardwarePresent(const char *chip);   // vrai si HW_<chip> compilé
void gbDrawHardwareGate(const char *chip, const char *needs);
