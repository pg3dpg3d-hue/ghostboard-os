"""
report_server.py — (re)génère le rapport HTML et le sert sur l'IP Tailscale.

Pourquoi Tailscale et pas 0.0.0.0 : le rapport contient des constats de
sécurité. On le sert UNIQUEMENT sur l'interface Tailscale (réseau privé
chiffré), jamais sur le LAN. Sans Tailscale, on retombe sur 127.0.0.1 avec un
avertissement — jamais d'exposition large par défaut.

Aucune dépendance : http.server de la bibliothèque standard suffit.
"""
from __future__ import annotations

import http.server
import socketserver
import subprocess
import threading
from pathlib import Path


def tailscale_ip() -> str | None:
    """Première IPv4 Tailscale, ou None si Tailscale n'est pas monté."""
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True,
                             text=True, timeout=5)
        ip = out.stdout.strip().splitlines()
        return ip[0].strip() if ip and ip[0].strip() else None
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


class ReportServer:
    """Sert un dossier en HTTP sur une adresse précise. Démarrable/arrêtable."""

    def __init__(self, directory: Path, port: int = 8899):
        self.directory = Path(directory)
        self.port = port
        self._httpd: socketserver.TCPServer | None = None
        self._thread: threading.Thread | None = None
        self.bind_ip = "127.0.0.1"
        self.on_tailscale = False

    def url(self, filename: str = "index.html") -> str:
        return f"http://{self.bind_ip}:{self.port}/{filename}"

    def start(self) -> str:
        """Démarre le serveur. Renvoie une note sur l'interface choisie."""
        ip = tailscale_ip()
        if ip:
            self.bind_ip, self.on_tailscale = ip, True
            note = f"servi sur Tailscale : {ip}"
        else:
            self.bind_ip, self.on_tailscale = "127.0.0.1", False
            note = "Tailscale absent — servi sur 127.0.0.1 seulement (local)"

        directory = str(self.directory)

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=directory, **k)

            def log_message(self, *a):  # silencieux : la TUI gère l'affichage
                pass

        # allow_reuse_address : relancer le serveur juste après l'avoir arrêté
        # ne doit pas buter sur un TIME_WAIT.
        socketserver.TCPServer.allow_reuse_address = True
        self._httpd = socketserver.TCPServer((self.bind_ip, self.port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return note

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
