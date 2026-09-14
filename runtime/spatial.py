#!/usr/bin/env python3
"""Serveur local durci et lanceur de GHOSTBOARD Spatial."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import urllib.parse


def roots():
    app = Path('/opt/ghostboard-os/spatial')
    if not app.exists():
        app = Path(__file__).resolve().parents[1] / 'spatial'
    return app.resolve(), (app / 'node_modules/three').resolve()


def resolve_request(raw_path, app, vendor):
    path = urllib.parse.unquote(urllib.parse.urlsplit(raw_path).path)
    if path == '/':
        target, base = app / 'index.html', app
    elif path.startswith('/app/'):
        target, base = app / path.removeprefix('/app/'), app
    elif path.startswith('/vendor/'):
        target, base = vendor / path.removeprefix('/vendor/'), vendor
    else:
        raise ValueError('not found')
    target = target.resolve()
    if target != base and not target.is_relative_to(base):
        raise ValueError('path traversal')
    if not target.is_file():
        raise ValueError('not found')
    return target


class Handler(BaseHTTPRequestHandler):
    app, vendor = roots()

    def do_HEAD(self):
        self.send_file(False)

    def do_GET(self):
        self.send_file(True)

    def send_file(self, body):
        try:
            target = resolve_request(self.path, self.app, self.vendor)
            data = target.read_bytes()
        except (OSError, ValueError):
            self.send_error(404)
            return
        kind = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        self.send_response(200)
        self.send_header('Content-Type', kind + ('; charset=utf-8' if kind.startswith('text/') or kind in ('application/javascript', 'application/json') else ''))
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self'; img-src 'self' data: blob:; worker-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        if body:
            self.wfile.write(data)

    def log_message(self, format, *args):
        pass


def main():
    ap = argparse.ArgumentParser(description='GHOSTBOARD local 3D spatial workbench')
    ap.add_argument('--serve-only', action='store_true')
    ap.add_argument('--port', type=int, default=0)
    args = ap.parse_args()
    app, vendor = roots()
    if not (app / 'index.html').is_file() or not (vendor / 'build/three.module.js').is_file():
        print('Spatial runtime is incomplete. Re-run the Pi installer to install the pinned Three.js package.', file=sys.stderr)
        return 1
    Handler.app, Handler.vendor = app, vendor
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    url = f'http://127.0.0.1:{server.server_port}/'
    print(url, flush=True)
    if args.serve_only:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    browser = next((shutil.which(name) for name in ('chromium', 'chromium-browser', 'google-chrome-stable') if shutil.which(name)), None)
    if not browser:
        print('Chromium is not installed.', file=sys.stderr)
        server.server_close()
        return 1
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    profile = Path.home() / '.local/state/ghostboard/spatial-browser'; profile.mkdir(parents=True, exist_ok=True)
    try:
        return subprocess.call([browser, '--app=' + url, '--user-data-dir=' + str(profile), '--no-first-run', '--disable-background-networking'])
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


if __name__ == '__main__':
    sys.exit(main())
