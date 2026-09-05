// ---------------------------------------------------------------------------
//  theme_colors.h — GÉNÉRÉ depuis brand/palette.toml. Ne pas éditer à la main.
//  Régénérer :  companion/firmware/tools/gen-theme.py
//
//  Couleurs de la LED NeoPixel (l'OLED est monochrome). Triplets R,G,B
//  passés tels quels à Adafruit_NeoPixel::Color().
// ---------------------------------------------------------------------------
#pragma once

#define GB_NEO_OFF       0, 0, 0   // repos / veille
#define GB_NEO_SCAN      168, 85, 247   // accent #A855F7 — scan / activité
#define GB_NEO_ATTACK    255, 77, 141   // input #FF4D8D — émission deauth (alerte)
#define GB_NEO_OK        46, 204, 113   // confirmation ponctuelle
