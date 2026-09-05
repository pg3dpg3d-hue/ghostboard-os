#!/usr/bin/env python3
"""
gen-wordlist.py — embarque data/wordlist.txt dans le firmware (include/wordlist.h).

Pas de carte SD sur la carte de base : la wordlist du module Auth Test est donc
compilée dans le binaire. Ce script lit data/wordlist.txt (un mot de passe par
ligne, # = commentaire) et génère un tableau C.

WPA impose des clés de 8 à 63 caractères : les entrées hors plage sont écartées
(elles ne peuvent pas être une clé WPA). Les doublons sont supprimés en gardant
l'ordre d'apparition.

Usage :
    tools/gen-wordlist.py            # écrit include/wordlist.h
    tools/gen-wordlist.py --check    # échoue si le header est périmé (CI)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIRMWARE = HERE.parent
SRC = FIRMWARE / "data" / "wordlist.txt"
OUT = FIRMWARE / "include" / "wordlist.h"

WPA_MIN, WPA_MAX = 8, 63


def load_words(path: Path) -> tuple[list[str], int]:
    words: list[str] = []
    seen: set[str] = set()
    skipped = 0
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        # On ne .strip() pas tout : un mot de passe peut finir par une espace.
        # Mais on retire le saut de ligne et on ignore les lignes de commentaire.
        line = raw.rstrip("\r\n")
        if not line or line.lstrip().startswith("#"):
            continue
        if not (WPA_MIN <= len(line) <= WPA_MAX):
            skipped += 1
            continue
        if line in seen:
            continue
        seen.add(line)
        words.append(line)
    return words, skipped


def c_escape(s: str) -> str:
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\t":
            out.append("\\t")
        elif 32 <= ord(ch) < 127:
            out.append(ch)
        else:
            # Octets UTF-8 échappés : une clé WPA peut contenir n'importe quoi.
            for b in ch.encode("utf-8"):
                out.append(f"\\x{b:02x}")
    return "".join(out)


def render(words: list[str]) -> str:
    lines = [
        "// -------------------------------------------------------------------------",
        "//  wordlist.h — GÉNÉRÉ depuis data/wordlist.txt. Ne pas éditer à la main.",
        "//  Régénérer :  companion/firmware/tools/gen-wordlist.py",
        "//",
        "//  Wordlist embarquée du module Auth Test. Stockée en flash (.rodata).",
        "// -------------------------------------------------------------------------",
        "#pragma once",
        "",
        f"static const int GB_WORDLIST_COUNT = {len(words)};",
        "static const char *const GB_WORDLIST[] = {",
    ]
    if words:
        for w in words:
            lines.append(f'    "{c_escape(w)}",')
    else:
        # Un tableau vide n'est pas valide en C : on met un placeholder neutre
        # et COUNT=0 pour que le module affiche « liste vide ».
        lines.append('    "",')
    lines.append("};")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="échoue si wordlist.h ne correspond plus à wordlist.txt")
    args = ap.parse_args()

    if not SRC.exists():
        print(f"wordlist introuvable : {SRC}", file=sys.stderr)
        return 2
    words, skipped = load_words(SRC)
    content = render(words)

    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != content:
            print("wordlist.h est périmé — relance tools/gen-wordlist.py", file=sys.stderr)
            return 1
        print(f"wordlist.h à jour ({len(words)} entrées).")
        return 0

    OUT.write_text(content, encoding="utf-8")
    msg = f"écrit {OUT.relative_to(FIRMWARE.parent.parent)} — {len(words)} entrées"
    if skipped:
        msg += f" ({skipped} hors plage 8–63 écartées)"
    print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
