#!/usr/bin/env python3
"""Installateur Pi 5 indépendant des réglages Intel, reprenable et à échec bloquant."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
BASE = '''ca-certificates curl git python3 python3-venv python3-tk python3-serial
nodejs npm xserver-xorg x11-utils x11-xserver-utils xinit dbus-x11
xfwm4 xfce4-session xfdesktop4 xfce4-panel xfce4-settings xfce4-terminal
xfce4-appfinder xfce4-screenshooter xfce4-whiskermenu-plugin xfce4-notifyd
xfce4-power-manager xfce4-screensaver xfce4-taskmanager thunar thunar-archive-plugin
lightdm lightdm-gtk-greeter network-manager network-manager-gnome bluez blueman openssh-server
pipewire-audio wireplumber pavucontrol alsa-utils espeak-ng polkitd pkexec gnome-keyring
libpam-gnome-keyring libsecret-tools at-spi2-core xdg-desktop-portal xdg-desktop-portal-gtk
xdg-utils desktop-file-utils gvfs gvfs-backends udisks2 upower
rofi wmctrl scrot xdotool xvfb xauth chromium mousepad galculator
papirus-icon-theme adwaita-icon-theme fonts-dejavu-core fontconfig librsvg2-bin
librsvg2-common unzip zip file rsync htop openssh-client cryptsetup'''.split()
FULL = '''build-essential cmake pkg-config libcurl4-openssl-dev gdb tmux ripgrep jq sqlite3
python3-pip python3-dev python3-gpiozero i2c-tools usbutils pciutils v4l-utils poppler-utils
libreoffice-writer libreoffice-calc libreoffice-impress evince vlc
keepassxc engrampa gnome-disk-utility ffmpeg'''.split()
TOOLS = ['ghost-system', 'ghost-assistant', 'ghost-control-center', 'ghost-model', 'ghost-hardware', 'ghost-voice', 'ghost-remote', 'ghost-workspace', 'ghost-codex', 'ghost-spatial', 'ghost-browser',
         'ghost-bruce', 'ghost-run', 'ghost-llm', 'ghost-llm-proxy', 'ghost-claude',
         'ghost-bench', 'ghost-status', 'ghost-theme', 'ghost-vault']


def plan(profile):
    return {
        'target': 'Raspberry Pi 5 / Raspberry Pi OS 64-bit / Debian 13',
        'profile': profile, 'packages': BASE + (FULL if profile == 'full' else []),
        'session': 'XFCE/X11 with LightDM',
        'preserved': ['Pi boot firmware', 'config.txt', 'cmdline.txt', 'kernel', 'native display mode', 'Bluetooth', 'accessibility', 'audio'],
        'installed': ['control center', 'hybrid, visual and voice assistant', 'local 3D spatial workbench', 'computer-use MCP', 'Pi 5 telemetry and fan profiles', 'paired remote development', 'settings backup/restore', 'diagnostics', 'application launchers'],
        'optional': ['Claude Code (--claude)', 'Codex CLI (--codex)', 'BlackBerry Q20 key mapping (--q20)'],
    }


class Installer:
    def __init__(self, user, home, profile):
        self.user, self.home, self.profile = user, Path(home), profile
        self.backup_dir = Path('/var/lib/ghostboard/pi5-backups') / dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.manifest = []
        self.backup_dir.mkdir(parents=True, mode=0o700)
        self.uid = __import__('pwd').getpwnam(user).pw_uid
        self.gid = __import__('pwd').getpwnam(user).pw_gid

    def run(self, args, user=False):
        print('+ ' + ' '.join(map(str, args)), flush=True)
        cmd = list(map(str, args))
        if user:
            cmd = ['runuser', '-u', self.user, '--', 'env', 'HOME=' + str(self.home), *cmd]
        subprocess.run(cmd, check=True)

    def put(self, dest, data, mode=0o644, user=False):
        dest = Path(dest)
        if dest.is_symlink():
            raise ValueError('Refusing to replace symlink: ' + str(dest))
        if isinstance(data, str):
            data = data.encode()
        if dest.exists() and dest.read_bytes() == data:
            os.chmod(dest, mode)
            if user:
                os.chown(dest, self.uid, self.gid)
            return
        if dest.exists():
            saved = self.backup_dir / dest.relative_to('/')
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, saved)
        self.manifest.append({'path': str(dest), 'existed': dest.exists()})
        (self.backup_dir / 'manifest.json').write_text(json.dumps(self.manifest, indent=2))
        missing = []
        parent = dest.parent
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        dest.parent.mkdir(parents=True, exist_ok=True)
        if user:
            for directory in missing:
                os.chown(directory, self.uid, self.gid)
        fd, temp = tempfile.mkstemp(dir=dest.parent)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
            os.chmod(temp, mode)
            if user:
                os.chown(temp, self.uid, self.gid)
            os.replace(temp, dest)
        finally:
            Path(temp).unlink(missing_ok=True)

    def deploy(self, q20=False, claude=False, codex=False):
        self.run(['apt-get', 'update'])
        self.run(['env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get', 'install', '-y', '--no-install-recommends', *plan(self.profile)['packages']])
        fonts = subprocess.run(['apt-cache', 'policy', 'fonts-ibm-plex'], capture_output=True, text=True)
        if re.search(r'Candidate:\s+(?!\(none\))\S+', fonts.stdout):
            self.run(['apt-get', 'install', '-y', '--no-install-recommends', 'fonts-ibm-plex'])
        else:
            print('IBM Plex unavailable in configured repositories; using system font fallback.')
        # Copie pérenne pour les outils qui retrouvent encore le dépôt.
        target = Path('/opt/ghostboard-os')
        for folder in ('theme', 'brand', 'desktop', 'runtime', 'mcp-computer-use', 'spatial', 'tools', 'companion'):
            for source in (REPO / folder).rglob('*'):
                if source.is_file() and '__pycache__' not in source.parts and 'node_modules' not in source.parts:
                    self.put(target / source.relative_to(REPO), source.read_bytes())
        self.run(['npm', 'ci', '--prefix', target / 'spatial', '--omit=dev', '--ignore-scripts', '--no-audit', '--no-fund'])
        for name in TOOLS:
            self.put('/usr/local/bin/' + name, (REPO / 'tools' / name).read_bytes(), 0o755)
        for source in (REPO / 'runtime').glob('*.py'):
            self.put('/usr/local/lib/ghostboard/runtime/' + source.name, source.read_bytes())
        for source in (REPO / 'mcp-computer-use').glob('*'):
            if source.is_file():
                self.put('/usr/local/lib/ghostboard/mcp-computer-use/' + source.name, source.read_bytes())
        self.put('/usr/share/ghostboard/palette.toml', (REPO / 'brand/palette.toml').read_bytes())
        # Générer hors du compte utilisateur, puis déposer chaque fichier avec sauvegarde.
        with tempfile.TemporaryDirectory(prefix='ghost-theme-') as tmp:
            built = Path(tmp) / 'built'
            self.run(['python3', target / 'theme/render-theme.py', '--check'])
            self.run(['python3', target / 'theme/render-theme.py', '--out', built])
            for source in (built / 'share').rglob('*'):
                if source.is_file():
                    self.put(Path('/usr/share/ghostboard') / source.relative_to(built / 'share'), source.read_bytes())
                    if 'icons' in source.relative_to(built / 'share').parts:
                        self.put(self.home / '.local/share' / source.relative_to(built / 'share'), source.read_bytes(), user=True)
            for source in (built / 'themes').rglob('*'):
                if source.is_file():
                    self.put(self.home / '.themes' / source.relative_to(built / 'themes'), source.read_bytes(), user=True)
            for src, dst in [('ghostboard.rasi', '.config/rofi/ghostboard.rasi'), ('terminalrc', '.config/xfce4/terminal/terminalrc'), ('Xresources', '.Xresources')]:
                self.put(self.home / dst, (built / 'share' / src).read_bytes(), user=True)
        # Garder la configuration XFCE personnelle si elle existe déjà.
        for source in (REPO / 'desktop/config').glob('*.xml'):
            dest = self.home / '.config/xfce4/xfconf/xfce-perchannel-xml' / source.name
            if not dest.exists():
                data = source.read_bytes()
                if source.name == 'xfce4-keyboard-shortcuts.xml':
                    data = keyboard_config(data)
                elif source.name == 'xfce4-panel.xml':
                    # Ancrage bas-centre indépendant de la résolution physique.
                    data = data.replace(b'p=0;x=400;y=459', b'p=10;x=0;y=0')
                self.put(dest, data, user=True)
        shortcuts = self.home / '.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml'
        if shortcuts.exists():
            self.put(shortcuts, keyboard_config(shortcuts.read_bytes()), user=True)
        whisker = self.home / '.config/xfce4/panel/whiskermenu-1.rc'
        if not whisker.exists():
            menu = (REPO / 'desktop/config/whiskermenu-1.rc').read_text()
            menu = re.sub(r'^favorites=.*$', 'favorites=ghost-control-center.desktop,ghost-assistant.desktop,ghost-local-ai.desktop,ghostboard-terminal.desktop,ghostboard-browser.desktop,ghostboard-bruce.desktop', menu, flags=re.M)
            self.put(whisker, menu, user=True)
        # Les raccourcis sont chargés à la prochaine session ; pas de manipulation du bus courant.
        for source in (REPO / 'desktop/launchers').glob('*.desktop'):
            if source.name not in ('ghostboard-browser.desktop', 'ghostboard-bruce.desktop', 'ghostboard-terminal.desktop', 'ghostboard-settings.desktop', 'ghostboard-status.desktop'):
                continue
            self.put(self.home / '.local/share/applications' / source.name, source.read_bytes(), user=True)
        for name, label, cmd, terminal in [
            ('ghost-control-center', 'GHOSTBOARD Control Center', 'ghost-control-center', False),
            ('ghost-assistant', 'GHOSTBOARD Assistant', 'xfce4-terminal --hold --execute ghost-assistant act', False),
            ('ghost-system-doctor', 'GHOSTBOARD Diagnostics', 'xfce4-terminal --hold --execute ghost-system doctor', False),
            ('ghost-local-ai', 'GHOSTBOARD Local AI', 'xfce4-terminal --hold --execute ghost-assistant chat --provider local', False),
            ('ghost-spatial', 'GHOSTBOARD Spatial', 'ghost-spatial', False),
        ]:
            self.put('/usr/share/applications/' + name + '.desktop', desktop(label, cmd, terminal))
        self.put('/usr/local/bin/ghostboard-pi5-session', '#!/bin/sh\nexport XDG_CURRENT_DESKTOP=XFCE\nexport XDG_SESSION_TYPE=x11\nexec startxfce4\n', 0o755)
        self.put('/usr/share/xsessions/ghostboard-pi5.desktop', '[Desktop Entry]\nName=GHOSTBOARD Pi 5\nComment=GHOSTBOARD complete desktop\nExec=/usr/local/bin/ghostboard-pi5-session\nTryExec=/usr/local/bin/ghostboard-pi5-session\nType=Application\nDesktopNames=XFCE\n')
        self.put('/etc/lightdm/lightdm.conf.d/90-ghostboard-pi5.conf', '[Seat:*]\nuser-session=ghostboard-pi5\nautologin-session=ghostboard-pi5\n')
        self.put(self.home / '.config/autostart/ghost-control-center.desktop', desktop('GHOSTBOARD Control Center', 'ghost-control-center'), user=True)
        self.put(self.home / '.config/autostart/ghost-bench-ready.desktop', desktop('GHOSTBOARD ready', 'ghost-bench --mark-ready'), user=True)
        # Restaurer les services utiles si une ancienne installation les avait neutralisés.
        for name in ('blueman', 'xfce4-power-manager'):
            system = Path('/etc/xdg/autostart') / (name + '.desktop')
            if system.exists():
                self.put(self.home / '.config/autostart' / system.name, system.read_bytes(), user=True)
        self.run(['usermod', '-aG', 'dialout', self.user])
        self.run(['systemctl', 'enable', 'NetworkManager', 'bluetooth', 'lightdm'])
        self.run(['systemctl', 'set-default', 'graphical.target'])
        # Une session utilisateur séparée : écran différent, mêmes droits de fichiers.
        self.put(self.home / '.config/systemd/user/ghostboard-agent-display.service', '''[Unit]
Description=GHOSTBOARD agent virtual screen (same user, not a security sandbox)
[Service]
ExecStart=/usr/bin/xvfb-run -n 91 -f %t/ghostboard-agent.Xauthority -s "-screen 0 1280x800x24 -nolisten tcp" /usr/bin/dbus-run-session /usr/bin/xfwm4
Restart=on-failure
[Install]
WantedBy=default.target
''', user=True)
        if q20:
            self.put(self.home / '.config/autostart/ghost-q20.desktop', desktop('Q20 keyboard', 'setxkbmap -option altwin:swap_ralt_rwin'), user=True)
        if claude:
            self.run(['npm', 'install', '--prefix', self.home / '.local', '@anthropic-ai/claude-code'], user=True)
            claude_bin = self.home / '.local/node_modules/.bin/claude'
            self.put('/usr/local/bin/claude', '#!/bin/sh\nexec "' + str(claude_bin) + '" "$@"\n', 0o755)
            listing = subprocess.run(['runuser', '-u', self.user, '--', str(claude_bin), 'mcp', 'get', 'ghostboard-computer-use-pi5'], capture_output=True)
            if listing.returncode != 0:
                self.run([claude_bin, 'mcp', 'add', '--scope', 'user', 'ghostboard-computer-use-pi5', '--', 'node', '/usr/local/lib/ghostboard/mcp-computer-use/server.js'], user=True)
        if codex:
            self.run(['npm', 'install', '--prefix', self.home / '.local', '@openai/codex'], user=True)
            codex_bin = self.home / '.local/node_modules/.bin/codex'
            self.put('/usr/local/bin/codex', '#!/bin/sh\nexec "' + str(codex_bin) + '" "$@"\n', 0o755)
            listing = subprocess.run(['runuser', '-u', self.user, '--', str(codex_bin), 'mcp', 'get', 'ghostboard-computer-use-pi5'], capture_output=True)
            if listing.returncode != 0:
                self.run([codex_bin, 'mcp', 'add', 'ghostboard-computer-use-pi5', '--', 'node', '/usr/local/lib/ghostboard/mcp-computer-use/server.js'], user=True)
        self.put('/etc/profile.d/ghostboard-pi5.sh', 'export GHOSTBOARD_REPO=/opt/ghostboard-os\nexport GHOSTBOARD_SHARE=/usr/share/ghostboard\n')
        self.put('/var/lib/ghostboard/pi5-install.json', json.dumps({'version': '0.4.0-pi5-preview', 'profile': self.profile, 'user': self.user, 'backup': str(self.backup_dir)}, indent=2))
        print('\nInstalled. Log out/reboot and select GHOSTBOARD Pi 5. Then run ghost-system doctor.')
        print('Configuration backups: ' + str(self.backup_dir))


def desktop(label, command, terminal=False):
    return f'[Desktop Entry]\nType=Application\nName={label}\nExec={command}\nTerminal={str(terminal).lower()}\nIcon=ghostboard-start\nCategories=System;\n'


def keyboard_config(data):
    root = ET.fromstring(data)
    commands = root.find("./property[@name='commands']")
    if commands is None:
        commands = ET.SubElement(root, 'property', name='commands', type='empty')
    custom = commands.find("./property[@name='custom']")
    if custom is None:
        custom = ET.SubElement(commands, 'property', name='custom', type='empty')
    for key, command in [('<Primary><Alt>Escape', 'ghost-system stop'), ('<Primary><Alt>g', 'ghost-control-center')]:
        existing = next((p for p in custom if p.get('name') == key), None)
        if existing is not None:
            custom.remove(existing)
        ET.SubElement(custom, 'property', name=key, type='string', value=command)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def main():
    ap = argparse.ArgumentParser(description='Install GHOSTBOARD on Raspberry Pi OS 64-bit (Debian 13).')
    ap.add_argument('--profile', choices=['desktop', 'full'], default='full')
    ap.add_argument('--user', default=os.environ.get('SUDO_USER', ''))
    ap.add_argument('--dry-run', action='store_true', help='Print plan only; no writes, packages or root needed.')
    ap.add_argument('--q20', action='store_true', help='Enable optional Right Alt/Super mapping for Q20 keyboard.')
    ap.add_argument('--claude', action='store_true', help='Also install Claude Code from npm; account setup is separate.')
    ap.add_argument('--codex', action='store_true', help='Also install Codex CLI from npm; account setup is separate.')
    args = ap.parse_args()
    if args.dry_run:
        print(json.dumps(plan(args.profile), indent=2))
        return 0
    if platform.system() != 'Linux' or os.geteuid() != 0:
        ap.error('Run with sudo on the Raspberry Pi. --dry-run works anywhere.')
    model = Path('/proc/device-tree/model')
    image_build = os.environ.get('GHOSTBOARD_IMAGE_BUILD') == '1' and Path('/etc/ghostboard-image-build').exists()
    if not image_build and (not model.exists() or 'Raspberry Pi 5' not in model.read_text()):
        ap.error('This installer only supports Raspberry Pi 5.')
    if platform.machine() not in ('aarch64', 'arm64'):
        ap.error('Install Raspberry Pi OS 64-bit first.')
    release = Path('/etc/os-release').read_text()
    if not re.search(r'^VERSION_ID=["\']?13["\']?$', release, re.M) or not Path('/boot/firmware/config.txt').exists():
        ap.error('Use Raspberry Pi OS based on Debian 13 with /boot/firmware/config.txt.')
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*', args.user) or args.user == 'root':
        ap.error('Specify a normal desktop account with --user NAME.')
    import pwd
    import fcntl
    try:
        account = pwd.getpwnam(args.user)
        if account.pw_uid < 1000 or not Path(account.pw_dir).is_dir():
            ap.error('Target must be an existing normal desktop account.')
        session = subprocess.run(['pgrep', '-u', str(account.pw_uid), '-x', 'xfce4-session'], capture_output=True)
        if session.returncode == 0:
            ap.error('Log out of XFCE before installing. Run from SSH or a text console so live settings cannot overwrite new files.')
        with open('/run/lock/ghostboard-pi5.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            Installer(args.user, account.pw_dir, args.profile).deploy(args.q20, args.claude, args.codex)
        return 0
    except (KeyError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print('Installation stopped: ' + str(exc), file=sys.stderr)
        print('Fix the error and rerun. Completed files are compared before replacement; backups are under /var/lib/ghostboard/pi5-backups.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
