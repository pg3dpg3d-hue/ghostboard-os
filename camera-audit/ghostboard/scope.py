"""
scope.py — barrière de périmètre, appliquée côté TUI.

`auditkit` a sa propre barrière ; celle-ci est une SECONDE porte, côté
interface, pour qu'aucune cible hors périmètre ne parte au scan même si le
câblage d'auditkit change. Deux barrières valent mieux qu'une pour un outil qui
envoie des paquets sur un réseau.

Elle valide des cibles (IP, IP:port, hôte) contre une liste d'autorisation
faite de CIDR et d'adresses. Rien n'est deviné : une cible qui ne tombe pas
DANS le périmètre est refusée, pas « probablement OK ».
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass


@dataclass(slots=True)
class Check:
    target: str
    ok: bool
    reason: str


def _networks(scope: list[str]) -> list:
    nets = []
    for entry in scope:
        entry = entry.strip()
        if not entry:
            continue
        try:
            nets.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            # Une entrée non-IP (nom d'hôte autorisé) : comparaison littérale.
            nets.append(entry.lower())
    return nets


def _host_of(target: str) -> str:
    """Retire un éventuel :port. Laisse les hôtes non-IP tels quels."""
    t = target.strip()
    if t.count(":") == 1 and not t.replace(":", "").replace(".", "").isalpha():
        # ip:port ou host:port -> on garde la partie hôte
        host, _, _ = t.rpartition(":")
        return host or t
    return t


def check_target(target: str, scope: list[str]) -> Check:
    host = _host_of(target)
    if not host:
        return Check(target, False, "cible vide")
    nets = _networks(scope)
    if not nets:
        return Check(target, False, "aucun périmètre défini — refus par défaut")
    # Cible en notation réseau (ex. 192.168.1.0/24) : autorisée seulement si
    # elle est ENTIÈREMENT contenue dans un réseau du périmètre. Scanner une
    # plage plus large que le périmètre doit être refusé.
    if "/" in host:
        try:
            tnet = ipaddress.ip_network(host, strict=False)
        except ValueError:
            return Check(target, False, "réseau invalide")
        for n in nets:
            if not isinstance(n, str) and tnet.subnet_of(n):
                return Check(target, True, f"⊆ {n}")
        return Check(target, False, "plage hors du périmètre autorisé")

    try:
        addr = ipaddress.ip_address(host)
        for n in nets:
            if not isinstance(n, str) and addr in n:
                return Check(target, True, f"dans {n}")
        return Check(target, False, "hors du périmètre autorisé")
    except ValueError:
        # Hôte non-IP : autorisé seulement s'il est listé littéralement.
        for n in nets:
            if isinstance(n, str) and host.lower() == n:
                return Check(target, True, "hôte listé")
        return Check(target, False, "hôte non listé dans le périmètre")


def filter_targets(targets: list[str], scope: list[str]) -> tuple[list[str], list[Check]]:
    """Renvoie (cibles_autorisées, tous_les_verdicts)."""
    checks = [check_target(t, scope) for t in targets if t.strip()]
    allowed = [c.target for c in checks if c.ok]
    return allowed, checks
