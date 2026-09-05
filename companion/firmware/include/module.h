// ---------------------------------------------------------------------------
//  module.h — contrat minimal d'un module de la carte.
//
//  Le code d'origine expose des paires setup()/loop() indépendantes. On les
//  garde telles quelles ; la seule addition est que loop() renvoie true quand
//  le module veut rendre la main au menu (appui LEFT sur l'écran racine).
// ---------------------------------------------------------------------------
#pragma once

struct Module {
    const char *name;      // libellé dans le menu
    void (*setup)();       // appelé une fois à l'entrée
    bool (*loop)();        // appelé en boucle ; true => retour au menu
};
