#!/usr/bin/env python3
"""Services locaux du cyberdeck. Aucun service réseau résident."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile

VERSION = '0.2.0-pi5-preview'
HOME = Path.home()
STATE = HOME / '.local/state/ghostboard'
STOP = STATE / 'agent.stop'
APPS = {
    'browser': ('Browser', ['ghost-browser']),
    'files': ('Files', ['thunar']),
    'terminal': ('Terminal', ['xfce4-terminal']),
    'editor': ('Text editor', ['mousepad']),
    'wifi': ('Wi-Fi', ['nm-connection-editor']),
    'bluetooth': ('Bluetooth', ['blueman-manager']),
    'audio': ('Audio', ['pavucontrol']),
    'display': ('Display', ['xfce4-display-settings']),
    'settings': ('Settings', ['xfce4-settings-manager']),
    'power': ('Power', ['xfce4-power-manager-settings']),
    'processes': ('Processes', ['xfce4-taskmanager']),
    'calculator': ('Calculator', ['galculator']),
    'media': ('Media player', ['vlc']),
    'office': ('Office', ['libreoffice']),
    'passwords': ('Passwords', ['keepassxc']),
    'screenshots': ('Screenshot', ['xfce4-screenshooter']),
    'serial': ('Serial boards', ['xfce4-terminal', '--hold', '--execute', 'ghost-bruce', 'console']),
    'claude': ('Claude Code', ['xfce4-terminal', '--hold', '--execute', 'ghost-claude']),
    'local-ai': ('Local chat', ['xfce4-terminal', '--hold', '--execute', 'ghost-assistant', 'chat', '--provider', 'local']),
    'assistant': ('Computer use', ['xfce4-terminal', '--hold', '--execute', 'ghost-assistant', 'act']),
    'ai-setup': ('Configure AI', ['xfce4-terminal', '--hold', '--execute', 'ghost-assistant', 'configure']),
    'agent-browser': ('Agent browser', ['ghost-system', 'agent-screen', 'open', 'browser']),
    'agent-assistant': ('Agent screen task', ['xfce4-terminal', '--hold', '--execute', 'ghost-assistant', 'act', '--agent-screen']),
    'updates': ('System updates', ['xfce4-terminal', '--hold', '--execute', 'ghost-system', 'update']),
    'diagnostics': ('Diagnostics', ['xfce4-terminal', '--hold', '--execute', 'ghost-system', 'doctor']),
}


def execute(args, timeout=8):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, '', str(exc)


def read(path, default=''):
    try:
        return Path(path).read_text().strip().strip('\0')
    except OSError:
        return default


def status():
    mem = {}
    for line in read('/proc/meminfo').splitlines():
        k, v = line.split(':', 1)
        mem[k] = int(v.strip().split()[0]) * 1024
    disk = shutil.disk_usage(HOME)
    batteries = []
    for b in Path('/sys/class/power_supply').glob('*'):
        if read(b / 'type') == 'Battery':
            batteries.append({'name': b.name, 'percent': read(b / 'capacity', 'unknown'), 'state': read(b / 'status', 'unknown')})
    temps = []
    for zone in Path('/sys/class/thermal').glob('thermal_zone*'):
        try:
            temps.append({'sensor': read(zone / 'type'), 'celsius': int(read(zone / 'temp')) / 1000})
        except ValueError:
            pass
    rc, network, _ = execute(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE', 'device'])
    return {
        'version': VERSION,
        'board': read('/proc/device-tree/model', platform.machine()),
        'architecture': platform.machine(), 'kernel': platform.release(),
        'session': os.environ.get('XDG_SESSION_TYPE', 'unknown'),
        'display': os.environ.get('DISPLAY'),
        'memory_total': mem.get('MemTotal'), 'memory_available': mem.get('MemAvailable'),
        'disk_free': disk.free, 'disk_total': disk.total,
        'temperatures': temps, 'batteries': batteries,
        'network': network.splitlines() if rc == 0 else [],
        'agent_stopped': STOP.exists(),
        'apps': {k: shutil.which(v[1][0]) is not None for k, v in APPS.items()},
    }


def launch(name):
    if name not in APPS:
        raise ValueError('Unknown application: ' + name)
    cmd = APPS[name][1]
    if not shutil.which(cmd[0]):
        raise RuntimeError(cmd[0] + ' is not installed. Re-run the Pi installer with the full profile.')
    subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def set_stopped(stopped):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if stopped:
        STOP.write_text(dt.datetime.now(dt.timezone.utc).isoformat())
    else:
        STOP.unlink(missing_ok=True)


def agent_environment():
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if not runtime:
        raise RuntimeError('Run inside your Linux desktop session.')
    auth = Path(runtime) / 'ghostboard-agent.Xauthority'
    if not auth.exists():
        raise RuntimeError('Start the agent screen first: ghost-system agent-screen on')
    return {**os.environ, 'DISPLAY': ':91', 'GHOSTBOARD_MCP_DISPLAY': ':91', 'XAUTHORITY': str(auth)}


def agent_screen(action, app=None):
    if action == 'on':
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', '--user', 'start', 'ghostboard-agent-display'], check=True)
    elif action == 'off':
        subprocess.run(['systemctl', '--user', 'stop', 'ghostboard-agent-display'], check=True)
    elif action == 'status':
        return subprocess.call(['systemctl', '--user', '--no-pager', 'status', 'ghostboard-agent-display'])
    elif action == 'open':
        if app not in ('browser', 'editor', 'terminal', 'files'):
            raise ValueError('Choose browser, editor, terminal or files.')
        agent_screen('on')
        import time
        for _ in range(50):
            try:
                env = agent_environment()
                ready = subprocess.run(['xdotool', 'getdisplaygeometry'], env=env, capture_output=True, timeout=2)
                if ready.returncode == 0:
                    break
            except RuntimeError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError('Virtual screen did not start; run ghost-system agent-screen status.')
        cmd = list(APPS[app][1])
        # Éviter que Chromium/Thunar réutilisent leur processus du bureau principal.
        if app == 'browser':
            cmd.append('--user-data-dir=' + str(STATE / 'agent-browser'))
        elif app == 'terminal':
            cmd.append('--disable-server')
        elif app == 'files':
            cmd = ['dbus-run-session', 'thunar']
        subprocess.Popen(cmd, env=env, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0


def doctor():
    s = status()
    checks = []
    def check(name, ok, hint):
        checks.append({'check': name, 'ok': bool(ok), 'hint': '' if ok else hint})
    check('Raspberry Pi 5', 'Raspberry Pi 5' in s['board'], 'Hardware validation requires a Pi 5.')
    check('ARM64', s['architecture'] in ('aarch64', 'arm64'), 'Use Raspberry Pi OS 64-bit.')
    check('X11 desktop', s['session'] == 'x11' and s['display'], 'Select GHOSTBOARD Pi 5 at login.')
    for cmd in ('node', 'xdotool', 'scrot', 'wmctrl', 'chromium', 'nmcli', 'wpctl'):
        check(cmd, shutil.which(cmd), 'Install the base packages with install/ghostboard-pi5.sh.')
    if s['display']:
        rc, _, _ = execute(['xdotool', 'getdisplaygeometry'])
        check('Screen access', rc == 0, 'Run as the desktop user, inside the graphical session.')
    check('Disk space > 2 GiB', s['disk_free'] > 2 * 1024**3, 'Free disk space before updating.')
    check('Computer use enabled', not s['agent_stopped'], 'Run ghost-system resume when ready.')
    rc, out, _ = execute(['vcgencmd', 'get_throttled'])
    if rc == 0:
        try:
            flags = int(out.split('=')[1], 16)
            check('No current throttling/undervoltage', flags & 0xF == 0, out + ': check cooling and power.')
        except (IndexError, ValueError):
            check('Power telemetry', False, out)
    return checks


BACKUP_PATHS = ('.config/ghostboard', '.config/xfce4', '.config/rofi', '.themes/GhostboardSpectral')


def backup(destination, home=HOME):
    """Sauvegarde ciblée ; ne suit jamais les liens vers des secrets externes."""
    dest = Path(destination).expanduser().resolve()
    home = Path(home).resolve()
    if dest.exists():
        raise ValueError('Destination already exists; choose a new archive name.')
    for name in BACKUP_PATHS:
        if dest.is_relative_to(home / name):
            raise ValueError('Archive must be outside the saved directories.')
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.ghost-backup-', dir=dest.parent)
    os.close(fd)
    try:
        with tarfile.open(temp, 'w:gz', dereference=False) as tf:
            for name in BACKUP_PATHS:
                source = home / name
                if source.is_symlink() or not source.exists():
                    continue
                def safe(info):
                    return info if info.isfile() or info.isdir() else None
                tf.add(source, arcname=name, filter=safe)
        os.chmod(temp, 0o600)
        # Création exclusive : un fichier existant n'est jamais écrasé.
        with open(dest, 'xb') as target, open(temp, 'rb') as source:
            os.chmod(dest, 0o600)
            shutil.copyfileobj(source, target)
    finally:
        Path(temp).unlink(missing_ok=True)
    return str(dest)


def restore(archive, home=HOME):
    """Valide toute l'archive, puis copie les fichiers ; aucun extractall."""
    home = Path(home).resolve()
    with tarfile.open(archive, 'r:gz') as tf:
        members = tf.getmembers()
        total = 0
        for m in members:
            total += m.size
            target = home / m.name
            allowed = any(m.name == p or m.name.startswith(p + '/') for p in BACKUP_PATHS)
            if not allowed or '..' in Path(m.name).parts or Path(m.name).is_absolute() or not (m.isfile() or m.isdir()):
                raise ValueError('Unsafe archive member: ' + m.name)
            if not target.resolve().is_relative_to(home):
                raise ValueError('Archive path escapes home: ' + m.name)
            # Refuser aussi les liens internes existants pour ne pas écraser leur cible.
            if any(p.is_symlink() for p in (target, *target.parents) if p != home and home in p.parents):
                raise ValueError('Restore destination contains a symlink: ' + m.name)
        if total > 256 * 1024**2 or len(members) > 10000:
            raise ValueError('Archive exceeds configuration backup limits.')
        STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        rollback = STATE / ('before-restore-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.tar.gz')
        backup(rollback, home)
        for m in members:
            target = home / m.name
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, temp = tempfile.mkstemp(dir=target.parent)
                with os.fdopen(fd, 'wb') as out, tf.extractfile(m) as source:
                    shutil.copyfileobj(source, out)
                os.replace(temp, target)
        return str(rollback)


def main():
    ap = argparse.ArgumentParser(description='GHOSTBOARD system tools')
    sub = ap.add_subparsers(dest='command', required=True)
    for name in ('status', 'doctor', 'apps', 'stop', 'resume', 'update', 'lock'):
        p = sub.add_parser(name)
        if name in ('status', 'doctor'):
            p.add_argument('--json', action='store_true')
    sub.add_parser('open').add_argument('app', choices=APPS)
    sub.add_parser('backup').add_argument('archive')
    sub.add_parser('restore').add_argument('archive')
    screen = sub.add_parser('agent-screen')
    screen.add_argument('action', choices=['on', 'off', 'status', 'open'])
    screen.add_argument('app', nargs='?')
    args = ap.parse_args()
    try:
        if args.command == 'status':
            print(json.dumps(status(), indent=2))
        elif args.command == 'doctor':
            checks = doctor()
            if args.json:
                print(json.dumps(checks, indent=2))
            else:
                for c in checks:
                    print(('OK   ' if c['ok'] else 'CHECK ') + c['check'] + (' — ' + c['hint'] if c['hint'] else ''))
            return 0 if all(c['ok'] for c in checks) else 1
        elif args.command == 'apps':
            for name, (label, cmd) in APPS.items():
                print(f'{name:14} {label:20} {"installed" if shutil.which(cmd[0]) else "missing"}')
        elif args.command == 'open':
            launch(args.app)
        elif args.command == 'agent-screen':
            return agent_screen(args.action, args.app)
        elif args.command in ('stop', 'resume'):
            set_stopped(args.command == 'stop')
            print('Computer use stopped.' if args.command == 'stop' else 'Computer use enabled.')
        elif args.command == 'backup':
            print(backup(args.archive))
        elif args.command == 'restore':
            if input('Restore Ghostboard configuration? Existing settings will be backed up. [y/N] ').lower() != 'y':
                return 1
            print('Restored. Previous configuration: ' + restore(args.archive))
        elif args.command == 'lock':
            set_stopped(True)
            return subprocess.call(['xflock4'])
        elif args.command == 'update':
            if platform.system() != 'Linux':
                raise RuntimeError('Updates require Linux.')
            # apt conserve sa confirmation et ne supprime aucun paquet automatiquement.
            rc = subprocess.call(['sudo', 'apt-get', 'update'])
            return rc or subprocess.call(['sudo', 'apt-get', 'upgrade'])
    except (ValueError, RuntimeError, OSError, tarfile.TarError, subprocess.SubprocessError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
