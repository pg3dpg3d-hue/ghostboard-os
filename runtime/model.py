#!/usr/bin/env python3
"""Gestion d'un serveur llama.cpp installé par l'utilisateur et d'un modèle GGUF."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from assistant import CONFIG, DEFAULT


def quote(value):
    if any(c in str(value) for c in ('\n', '\r', '\0')):
        raise ValueError('Invalid path.')
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'


def configure(model, binary):
    model = Path(model).expanduser().resolve()
    binary = Path(binary).expanduser().resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError('Install llama-server for ARM64 first; pass its path with --server.')
    with model.open('rb') as f:
        if f.read(4) != b'GGUF':
            raise ValueError('Expected a GGUF model file.')
    unit = Path.home() / '.config/systemd/user/ghostboard-local-model.service'
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(f'''[Unit]
Description=GHOSTBOARD local model (llama.cpp)
[Service]
ExecStart={quote(binary)} -m {quote(model)} --host 127.0.0.1 --port 8080 --alias ghost-local -c 2048 -t 4
Restart=on-failure
RestartSec=10
NoNewPrivileges=yes
PrivateTmp=yes
[Install]
WantedBy=default.target
''')
    config = json.loads(CONFIG.read_text()) if CONFIG.exists() else json.loads(json.dumps(DEFAULT))
    config.setdefault('providers', {})['local'] = {'base_url': 'http://127.0.0.1:8080/v1', 'model': 'ghost-local', 'key_env': '', 'vision': False}
    CONFIG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(config, f, indent=2)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    print('Configured. Run ghost-model start, then ghost-assistant chat --provider local.')
    print('The GGUF must fit alongside the desktop and context; measure performance on your Pi.')


def main():
    ap = argparse.ArgumentParser(description='GHOSTBOARD local model service')
    sub = ap.add_subparsers(dest='action', required=True)
    conf = sub.add_parser('configure')
    conf.add_argument('model')
    conf.add_argument('--server', default=shutil.which('llama-server') or '/usr/local/bin/llama-server')
    for name in ('start', 'stop', 'status', 'enable', 'disable'):
        sub.add_parser(name)
    args = ap.parse_args()
    try:
        if args.action == 'configure':
            configure(args.model, args.server)
            return 0
        return subprocess.call(['systemctl', '--user', '--no-pager', args.action, 'ghostboard-local-model.service'])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
