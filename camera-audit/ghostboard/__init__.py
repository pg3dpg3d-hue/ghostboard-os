"""
GHOSTBOARD OS — couche d'intégration « RECON › Camera Audit ».

Ce paquet est le PONT entre l'OS GHOSTBOARD et l'outil d'audit `auditkit`
existant. Il ne réécrit AUCUNE logique de scan : il importe `auditkit`,
normalise ses `Finding` vers un modèle d'affichage, et présente le tout dans
une TUI Textual pensée pour l'écran 4 pouces du deck.

Séparation volontaire :
  - `auditkit`  (l'outil de l'opérateur) fait le scan et produit les Finding.
  - `ghostboard` (ce paquet)             affiche, trie, sert le rapport.

Si les noms de classes ou de fonctions d'`auditkit` diffèrent de ce que le
pont suppose, UN SEUL fichier change — `bridge.py` — pas la TUI.
"""
__version__ = "1.0.0"
