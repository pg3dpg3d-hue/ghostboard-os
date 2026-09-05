// ---------------------------------------------------------------------------
//  module.h — contrat des modules et regroupement en catégories.
//
//  Un Module garde le contrat d'origine (setup + loop renvoyant true pour
//  rendre la main). Les Category regroupent les modules par famille (WiFi,
//  Bluetooth, SubGHz…) : le menu devient à deux niveaux, indispensable dès
//  qu'on dépasse deux ou trois entrées sur un écran de 64 px de haut.
// ---------------------------------------------------------------------------
#pragma once

struct Module {
    const char *name;      // libellé dans le sous-menu
    void (*setup)();       // appelé une fois à l'entrée
    bool (*loop)();        // appelé en boucle ; true => retour au sous-menu
};

struct Category {
    const char *name;          // libellé dans le menu racine
    const Module *modules;     // tableau de modules
    int count;                 // nombre de modules
};
