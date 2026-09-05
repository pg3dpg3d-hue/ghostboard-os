// ---------------------------------------------------------------------------
//  theme.h — habillage OLED partagé (l'écran est monochrome : la charte
//  s'exprime par la typo et la mise en page, la couleur passe par la LED).
// ---------------------------------------------------------------------------
#pragma once

#include "config.h"

// Splash d'amorçage : identité GHOSTBOARD au démarrage de la carte.
void gbBootSplash();

// En-tête commun à tous les écrans : titre en haut + filet de séparation.
// Laisse le curseur de dessin prêt pour le corps (y >= 22).
void gbHeader(const char *title);
