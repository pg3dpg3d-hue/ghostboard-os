#!/usr/bin/env python3
"""Commande vocale locale : ALSA -> whisper.cpp -> confirmation -> assistant."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import re

CONFIG = Path.home() / '.config/ghostboard/voice.json'


def configure(model, device, language):
    model = Path(model).expanduser().resolve()
    if not model.is_file():
        raise ValueError('The whisper.cpp model does not exist.')
    if not re.fullmatch(r'[A-Za-z0-9_.:,/-]{1,80}', device) or not re.fullmatch(r'[A-Za-z-]{2,16}|auto', language):
        raise ValueError('Invalid microphone device or language.')
    CONFIG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'model': str(model), 'device': device, 'language': language}, stream, indent=2)
    os.chmod(CONFIG, 0o600)
    print('Voice configured. Run ghost-voice --mode chat or ghost-voice --mode act.')


def record(seconds, destination, device):
    command = ['arecord', '-q', '-D', device, '-f', 'S16_LE', '-r', '16000', '-c', '1', '-d', str(seconds), str(destination)]
    subprocess.run(command, check=True, timeout=seconds + 10)


def transcribe(wav, model, language):
    binary = shutil.which('whisper-cli') or shutil.which('whisper')
    if not binary:
        raise RuntimeError('Install whisper.cpp and make whisper-cli available in PATH.')
    prefix = wav.with_suffix('')
    command = [binary, '-m', str(model), '-f', str(wav), '-l', language, '-otxt', '-of', str(prefix), '-nt', '-np']
    subprocess.run(command, check=True, timeout=300)
    transcript = prefix.with_suffix('.txt')
    if not transcript.exists():
        raise RuntimeError('whisper-cli did not create a transcript.')
    return ' '.join(transcript.read_text().split())


def main():
    ap = argparse.ArgumentParser(description='GHOSTBOARD offline voice command')
    ap.add_argument('--model', help='Local whisper.cpp model file')
    ap.add_argument('--configure', metavar='MODEL', help='Save the model path and microphone settings.')
    ap.add_argument('--mode', choices=['chat', 'act'], default='chat')
    ap.add_argument('--provider', choices=['local', 'cloud'], default='local')
    ap.add_argument('--seconds', type=int, default=8)
    ap.add_argument('--device', default='default')
    ap.add_argument('--language', default='fr')
    ap.add_argument('--speak', action='store_true', help='Read a short acknowledgement with espeak-ng.')
    args = ap.parse_args()
    try:
        if args.configure:
            configure(args.configure, args.device, args.language)
            return 0
        saved = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
        model = Path(args.model or saved.get('model', '')).expanduser().resolve()
        args.device = saved.get('device', args.device) if not args.model else args.device
        args.language = saved.get('language', args.language) if not args.model else args.language
        if not model.is_file() or not 1 <= args.seconds <= 60:
            raise ValueError('Provide an existing model and a duration from 1 to 60 seconds.')
        with tempfile.TemporaryDirectory(prefix='ghost-voice-') as folder:
            wav = Path(folder) / 'voice.wav'
            print(f'Listening for {args.seconds} seconds…')
            record(args.seconds, wav, args.device)
            text = transcribe(wav, model, args.language)
        if not text:
            raise RuntimeError('No speech recognized.')
        print('Recognized: ' + text)
        if input('Send this request to the assistant? [y/N] ').lower() != 'y':
            return 1
        if args.speak and shutil.which('espeak-ng'):
            subprocess.run(['espeak-ng', '-v', args.language, 'Demande reçue'], timeout=10)
        return subprocess.call(['ghost-assistant', args.mode, '--provider', args.provider, text])
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
