#!/usr/bin/env python3
"""Provisionnement reproductible des dépendances de GHOSTBOARD Hand Control.

Aucune roue apt épinglée fiable de MediaPipe n'existe pour Debian 13 ARM64 ;
on installe donc MediaPipe dans un venv dédié (versions épinglées) et on
télécharge le modèle Hand Landmarker **une seule fois**, hors exécution. Le
moteur ne télécharge jamais rien au runtime.

Ce script ne masque pas les échecs : si l'installation ou le téléchargement
échoue, il l'indique clairement et laisse le système sur le backend simulé.

    python3 install/hand-deps.py --dry-run     # affiche le plan, n'écrit rien
    python3 install/hand-deps.py               # venv + pip + modèle
    python3 install/hand-deps.py --skip-deps   # modèle seulement
    python3 install/hand-deps.py --sha256 <hex>  # vérifie l'empreinte du modèle

Le modèle provient du dépôt officiel MediaPipe. L'URL est épinglée ; fournir
`--sha256` pour une vérification stricte (recommandé). Sans empreinte attendue,
le script calcule et AFFICHE le SHA-256 téléchargé afin que vous puissiez le
figer ensuite.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request

HOME = Path.home()
DEFAULT_VENV = HOME / '.local/share/ghostboard/hand-venv'
DEFAULT_MODEL = HOME / '.local/share/ghostboard/models/hand_landmarker.task'
# Modèle officiel MediaPipe Hand Landmarker (float16). URL épinglée.
MODEL_URL = ('https://storage.googleapis.com/mediapipe-models/hand_landmarker/'
             'hand_landmarker/float16/1/hand_landmarker.task')
# Versions épinglées. À confirmer sur le Pi 5 réel (Debian 13 ARM64) ; ajustables
# via --mediapipe-version / --numpy-version sans modifier le code.
DEFAULT_MEDIAPIPE = '0.10.18'
DEFAULT_NUMPY = '1.26.4'
MODEL_MIN_BYTES = 1_000_000  # un .task valide fait plusieurs Mo


def plan(args):
    return {
        'venv': str(args.venv),
        'model_path': str(args.model_path),
        'model_url': MODEL_URL,
        'mediapipe': None if args.skip_deps else args.mediapipe_version,
        'numpy': None if args.skip_deps else args.numpy_version,
        'install_deps': not args.skip_deps,
        'download_model': not args.skip_model,
        'expected_sha256': args.sha256,
    }


def create_venv(venv):
    if not (venv / 'pyvenv.cfg').exists():
        print('+ creating venv at ' + str(venv))
        subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True)
    python = venv / ('Scripts' if os.name == 'nt' else 'bin') / ('python.exe' if os.name == 'nt' else 'python')
    if not python.exists():
        raise RuntimeError('venv python not found at ' + str(python))
    return python


def install_deps(python, mediapipe_version, numpy_version):
    subprocess.run([str(python), '-m', 'pip', 'install', '--upgrade', 'pip'], check=True)
    # Versions épinglées, pas d'installation globale.
    packages = [f'numpy=={numpy_version}', f'mediapipe=={mediapipe_version}']
    print('+ pip install ' + ' '.join(packages))
    result = subprocess.run([str(python), '-m', 'pip', 'install', *packages])
    if result.returncode != 0:
        raise RuntimeError(
            'MediaPipe could not be installed for this platform/Python. '
            'Confirm a version available for Debian 13 ARM64 and pass it with '
            '--mediapipe-version, or keep the simulated backend. The failure is '
            'not hidden: hand control stays on the simulated backend until this '
            'succeeds.')


def download_model(model_path, expected_sha256):
    model_path.parent.mkdir(parents=True, exist_ok=True)
    print('+ downloading model from ' + MODEL_URL)
    fd, tmp = tempfile.mkstemp(dir=model_path.parent, prefix='.hand-model-')
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(fd, 'wb') as out:
            with urllib.request.urlopen(MODEL_URL, timeout=120) as response:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    digest.update(chunk)
                    out.write(chunk)
        if size < MODEL_MIN_BYTES:
            raise RuntimeError(f'Downloaded model is too small ({size} bytes); aborting.')
        got = digest.hexdigest()
        if expected_sha256 and got.lower() != expected_sha256.lower():
            raise RuntimeError(f'Model SHA-256 mismatch: got {got}, expected {expected_sha256}.')
        os.chmod(tmp, 0o644)
        os.replace(tmp, model_path)
        print(f'  model saved to {model_path} ({size} bytes)')
        print('  SHA-256: ' + got)
        if not expected_sha256:
            print('  Pin this hash with --sha256 next time for strict verification.')
    finally:
        Path(tmp).unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description='Provision GHOSTBOARD Hand Control dependencies.')
    ap.add_argument('--venv', type=Path, default=DEFAULT_VENV)
    ap.add_argument('--model-path', type=Path, default=DEFAULT_MODEL)
    ap.add_argument('--mediapipe-version', default=DEFAULT_MEDIAPIPE)
    ap.add_argument('--numpy-version', default=DEFAULT_NUMPY)
    ap.add_argument('--sha256', default=None, help='Expected model SHA-256 (recommended).')
    ap.add_argument('--skip-deps', action='store_true', help='Do not install Python deps.')
    ap.add_argument('--skip-model', action='store_true', help='Do not download the model.')
    ap.add_argument('--dry-run', action='store_true', help='Print the plan; write nothing.')
    args = ap.parse_args()

    if args.dry_run:
        print(json.dumps(plan(args), indent=2))
        return 0
    try:
        if not args.skip_deps:
            python = create_venv(args.venv)
            install_deps(python, args.mediapipe_version, args.numpy_version)
        if not args.skip_model:
            download_model(args.model_path, args.sha256)
        print('\nDone. Point ghost-hand at the venv Python to use MediaPipe, e.g.:')
        print('  ' + str(args.venv / ("Scripts" if os.name == "nt" else "bin") / "python") +
              ' /usr/local/bin/ghost-hand start')
        print('The model path is ' + str(args.model_path) + ' (config key model_path).')
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError, urllib.error.URLError) as exc:
        print('hand-deps failed: ' + str(exc), file=sys.stderr)
        print('Hand control remains on the simulated backend until this is fixed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
