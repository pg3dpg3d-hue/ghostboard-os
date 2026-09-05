#!/usr/bin/env python3
"""
make-wordlist.py — compose une wordlist WPA réaliste dans data/wordlist.txt.

Outil d'AUTORAT (à lancer à la main quand on veut régénérer la liste source).
À ne pas confondre avec gen-wordlist.py, qui transforme data/wordlist.txt en
include/wordlist.h au build.

La liste vise les candidats *probables* d'une clé choisie par un humain :
  - mots de passe les plus courants (≥ 8 caractères) ;
  - racines (mots FR/EN + prénoms) déclinées avec des suffixes usuels
    (chiffres, années, ponctuation) et une variante capitalisée ;
  - suites numériques et « marches clavier » classiques.

Elle NE contient PAS les clés par défaut des box (Freebox/Livebox/SFR/Orange…) :
celles-ci sont aléatoires et uniques par appareil — un dictionnaire ne les
trouve pas. Ce module teste donc surtout une clé *modifiée par l'utilisateur*.

WPA impose 8 à 63 caractères : le reste est filtré. Sortie dédupliquée, triée
par longueur puis alpha pour que les essais courts (plus probables) passent en
premier.

Usage :
    tools/make-wordlist.py            # écrit data/wordlist.txt
    tools/make-wordlist.py --max 5000 # plafonne la taille
"""
from __future__ import annotations

import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "data" / "wordlist.txt"

WPA_MIN, WPA_MAX = 8, 63

# --- Mots de passe très courants (≥ 8), tels quels ---------------------------
COMMON = [
    "12345678", "123456789", "1234567890", "123456789a", "12345678910",
    "password", "password1", "password123", "passw0rd", "motdepasse",
    "azertyui", "azerty123", "qwertyui", "qwerty123", "1qaz2wsx",
    "iloveyou", "sunshine", "princess", "football", "baseball",
    "welcome1", "admin123", "administrator", "superman", "batman12",
    "trustno1", "whatever", "computer", "internet", "starwars",
    "michael1", "jennifer", "chocolat", "changeme", "abcd1234",
    "aaaaaaaa", "11111111", "00000000", "123123123", "654321789",
    "pokemon1", "dragon123", "monkey123", "master123", "shadow12",
    "liverpool", "arsenal1", "chelsea1", "juventus", "barcelona",
    "azertyuiop", "qwertyuiop", "motdepasse1", "bonjour1", "coucou123",
    "soleil123", "vacances1", "nintendo", "playstation", "samsung1",
]

# --- Racines déclinées avec suffixes -----------------------------------------
ROOTS = [
    "password", "motdepasse", "admin", "root", "love", "amour", "soleil",
    "bonjour", "coucou", "chocolat", "maison", "famille", "julie", "marie",
    "thomas", "nicolas", "sophie", "camille", "lucas", "chloe", "manon",
    "hugo", "leo", "emma", "louis", "jules", "sarah", "david", "michel",
    "pierre", "paul", "jacques", "france", "paris", "lyon", "marseille",
    "football", "tennis", "guitare", "musique", "cinema", "internet",
    "orange", "freebox", "livebox", "bouygues", "netflix", "google",
    "welcome", "master", "dragon", "monkey", "shadow", "ninja", "hunter",
    "summer", "winter", "azerty", "qwerty", "azertyuiop", "secret",
]
SUFFIXES = [
    "", "1", "12", "123", "1234", "12345", "123456", "!", "01", "02",
    "1!", "2!", "00", "99", "007", "69", "77", "88", "666", "!!",
    "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026",
]

# --- Suites numériques / marches clavier -------------------------------------
def sequences() -> list[str]:
    out: list[str] = []
    # Chiffres répétés (00000000 .. 99999999) et suites croissantes.
    for d in "0123456789":
        out.append(d * 8)
        out.append(d * 10)
    out += ["12345678", "23456789", "34567890", "87654321", "98765432",
            "09876543", "13579246", "24681357", "11223344", "12211221",
            "10203040", "12312312", "14141414", "10101010", "12344321"]
    # Marches clavier.
    out += ["asdfghjk", "zxcvbnm1", "1q2w3e4r", "q1w2e3r4", "!qaz2wsx",
            "azsxdcfv", "poiuytre", "lkjhgfds", "qazwsxedc", "1qazxsw2"]
    return out


def capitalize(w: str) -> str:
    return w[:1].upper() + w[1:] if w else w


def build() -> list[str]:
    seen: set[str] = set()
    words: list[str] = []

    def add(w: str) -> None:
        if WPA_MIN <= len(w) <= WPA_MAX and w not in seen:
            seen.add(w)
            words.append(w)

    for w in COMMON:
        add(w)
    for w in sequences():
        add(w)
    for root in ROOTS:
        for suf in SUFFIXES:
            add(root + suf)
            add(capitalize(root) + suf)

    # Essais courts d'abord (plus probables), puis ordre alpha stable.
    words.sort(key=lambda s: (len(s), s))
    return words


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=0, help="plafonne le nombre d'entrées")
    args = ap.parse_args()

    words = build()
    if args.max and len(words) > args.max:
        words = words[: args.max]

    header = (
        "# Wordlist WPA du module Auth Test — audit de TON réseau uniquement.\n"
        "# Générée par tools/make-wordlist.py. Un mot de passe par ligne.\n"
        "# WPA = 8 à 63 caractères ; hors plage écarté à l'embarquement.\n"
        "# NB : ne contient pas les clés par défaut des box (aléatoires, uniques).\n"
        "# Un dictionnaire ne trouve qu'une clé FAIBLE ou COURANTE.\n"
    )
    OUT.write_text(header + "\n".join(words) + "\n", encoding="utf-8")
    print(f"écrit {OUT.name} — {len(words)} entrées "
          f"(longueurs {min(len(w) for w in words)}–{max(len(w) for w in words)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
