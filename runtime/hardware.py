#!/usr/bin/env python3
"""Réglages matériels Pi 5 explicites, sauvegardés et réversibles."""
import argparse
import datetime as dt
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile

CONFIG = Path('/boot/firmware/config.txt')
BEGIN = '# BEGIN GHOSTBOARD FAN PROFILE'
END = '# END GHOSTBOARD FAN PROFILE'
PROFILES = {
    'default': [],
    'cool': ['dtparam=fan_temp0=45000', 'dtparam=fan_temp1=55000', 'dtparam=fan_temp2=65000', 'dtparam=fan_temp3=75000'],
    'balanced': ['dtparam=fan_temp0=50000', 'dtparam=fan_temp1=60000', 'dtparam=fan_temp2=67500', 'dtparam=fan_temp3=75000'],
    'quiet': ['dtparam=fan_temp0=55000', 'dtparam=fan_temp1=65000', 'dtparam=fan_temp2=72500', 'dtparam=fan_temp3=80000'],
}


def require_pi():
    model = Path('/proc/device-tree/model')
    if os.geteuid() != 0:
        raise RuntimeError('Run this command with sudo.')
    if not model.exists() or 'Raspberry Pi 5' not in model.read_text(errors='ignore'):
        raise RuntimeError('This hardware command only supports Raspberry Pi 5.')
    if not CONFIG.is_file() or CONFIG.is_symlink():
        raise RuntimeError('/boot/firmware/config.txt is unavailable or is a symbolic link.')


def replace_block(text, lines):
    pattern = re.compile(r'^' + re.escape(BEGIN) + r'$.*?^' + re.escape(END) + r'$\n?', re.M | re.S)
    text = pattern.sub('', text).rstrip() + '\n'
    if lines:
        text += '\n' + BEGIN + '\n' + '\n'.join(lines) + '\n' + END + '\n'
    return text


def fan(profile):
    require_pi()
    original = CONFIG.read_text()
    updated = replace_block(original, PROFILES[profile])
    if updated == original:
        print('Fan profile already active: ' + profile)
        return
    backup = CONFIG.with_name('config.txt.ghostboard-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copy2(CONFIG, backup)
    fd, tmp = tempfile.mkstemp(dir=CONFIG.parent, prefix='.ghostboard-config-')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, CONFIG.stat().st_mode)
        os.replace(tmp, CONFIG)
    finally:
        Path(tmp).unlink(missing_ok=True)
    print(f'Fan profile set to {profile}. Backup: {backup}. Reboot to apply.')


def telemetry():
    commands = [['vcgencmd', 'measure_temp'], ['vcgencmd', 'get_throttled'], ['vcgencmd', 'measure_volts', 'core']]
    for command in commands:
        try:
            value = subprocess.run(command, capture_output=True, text=True, timeout=5)
            print(' '.join(command[1:] or command[:1]) + ': ' + (value.stdout.strip() or value.stderr.strip()))
        except OSError as exc:
            print(command[0] + ': unavailable (' + str(exc) + ')')
    for cooling in Path('/sys/class/thermal').glob('cooling_device*'):
        kind = (cooling / 'type').read_text().strip() if (cooling / 'type').exists() else cooling.name
        if 'fan' in kind.lower():
            current = (cooling / 'cur_state').read_text().strip()
            maximum = (cooling / 'max_state').read_text().strip()
            print(f'{kind}: state {current}/{maximum}')


def main():
    ap = argparse.ArgumentParser(description='GHOSTBOARD Raspberry Pi hardware')
    sub = ap.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    fan_parser = sub.add_parser('fan')
    fan_parser.add_argument('profile', choices=PROFILES)
    args = ap.parse_args()
    try:
        if args.command == 'status':
            telemetry()
        else:
            fan(args.profile)
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
