// ---------------------------------------------------------------------------
//  hwstub.cpp — placeholders gatés pour les catégories à matériel externe.
//
//  Chaque entrée affiche ce qu'il faut câbler. Dès que la puce est présente
//  (macro HW_* + broches dans hardware.h) ET que le vrai module est écrit
//  (phase 2), on remplace ces placeholders dans menu.cpp.
// ---------------------------------------------------------------------------
#include "config.h"
#include "hardware.h"
#include "hwstub.h"

namespace HwStub {

// Fabrique un couple setup/loop qui montre le gate d'une puce donnée, puis
// attend LEFT. Une paire de fonctions par puce (pointeurs de fonction C).
#define GATE(fn, chip, needs)                              \
    static void fn##Setup() { gbDrawHardwareGate(chip, needs); } \
    static bool fn##Loop() {                               \
        if (digitalRead(BTN_PIN_LEFT) == LOW) {            \
            while (digitalRead(BTN_PIN_LEFT) == LOW);       \
            return true;                                   \
        }                                                  \
        return false;                                      \
    }

GATE(sub,  "CC1101",  "CC1101 SPI module")
GATE(ir,   "IR",      "IR TX/RX LED")
GATE(nrf,  "NRF24",   "NRF24L01 SPI")
GATE(nfcg, "NFC",     "ST25R3916 SPI")
GATE(ibtn, "IBUTTON", "1-Wire pad")

const Module subghz[]   = {{"Read / TX / Jammer", subSetup, subLoop}};
const Module infrared[] = {{"TX-B-Gone / Remote", irSetup, irLoop}};
const Module nrf24[]    = {{"Spectrum scan", nrfSetup, nrfLoop}};
const Module nfc[]      = {{"Read / emulate", nfcgSetup, nfcgLoop}};
const Module ibutton[]  = {{"Read / emulate", ibtnSetup, ibtnLoop}};

int subghzCount()   { return 1; }
int infraredCount() { return 1; }
int nrf24Count()    { return 1; }
int nfcCount()      { return 1; }
int ibuttonCount()  { return 1; }

}  // namespace HwStub
