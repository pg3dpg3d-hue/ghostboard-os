#!/usr/bin/env python3
"""Appairage SSH à clé publique pour MCP distant, sans démon propriétaire."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

SSHD = Path('/etc/ssh/sshd_config.d/90-ghostboard-remote.conf')
MARK = 'ghostboard-remote:'
SERVER = '/usr/local/lib/ghostboard/mcp-computer-use/server.js'


def normal_user(name):
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*', name) or name == 'root':
        raise ValueError('Specify a normal Linux account.')
    import pwd
    account = pwd.getpwnam(name)
    if account.pw_uid < 1000 or not Path(account.pw_dir).is_dir():
        raise ValueError('The desktop account does not exist.')
    return account


def read_key(path):
    value = Path(path).expanduser().read_text().strip()
    parts = value.split()
    allowed = ('ssh-ed25519', 'ssh-rsa', 'ecdsa-sha2-nistp256', 'sk-ssh-ed25519@openssh.com')
    if len(parts) < 2 or parts[0] not in allowed or not re.fullmatch(r'[A-Za-z0-9+/=]+', parts[1]):
        raise ValueError('Expected one OpenSSH public key.')
    return parts[0] + ' ' + parts[1]


def write_private(path, text, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix='.ghostboard-remote-')
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def enable(user, public_key):
    if os.geteuid() != 0:
        raise RuntimeError('Run enable with sudo.')
    account = normal_user(user)
    key = read_key(public_key)
    fingerprint = hashlib.sha256(key.encode()).hexdigest()[:16]
    auth = Path(account.pw_dir) / '.ssh/authorized_keys'
    if auth.parent.is_symlink() or auth.is_symlink():
        raise ValueError('Refusing symbolic links in the SSH configuration path.')
    existing = auth.read_text().splitlines() if auth.exists() else []
    existing = [line for line in existing if MARK not in line]
    existing.append(f'restrict {key} {MARK}{fingerprint}')
    write_private(auth, '\n'.join(existing) + '\n')
    os.chown(auth.parent, account.pw_uid, account.pw_gid)
    os.chmod(auth.parent, 0o700)
    os.chown(auth, account.pw_uid, account.pw_gid)
    config = f'''# Managed by ghost-remote. Remove with: sudo ghost-remote disable --user {user}
Match User {user}
    PubkeyAuthentication yes
    PasswordAuthentication no
    KbdInteractiveAuthentication no
'''
    previous = SSHD.read_text() if SSHD.exists() else None
    write_private(SSHD, config, 0o644)
    try:
        subprocess.run(['sshd', '-t'], check=True)
    except subprocess.SubprocessError:
        if previous is None:
            SSHD.unlink(missing_ok=True)
        else:
            write_private(SSHD, previous, 0o644)
        raise
    subprocess.run(['systemctl', 'enable', '--now', 'ssh'], check=True)
    subprocess.run(['systemctl', 'reload', 'ssh'], check=True)
    print(f'Remote control paired for {user}. Key fingerprint tag: {fingerprint}')
    print('The paired key has shell-level access to this account. Keep the private key protected.')


def disable(user):
    if os.geteuid() != 0:
        raise RuntimeError('Run disable with sudo.')
    account = normal_user(user)
    auth = Path(account.pw_dir) / '.ssh/authorized_keys'
    if auth.parent.is_symlink() or auth.is_symlink():
        raise ValueError('Refusing symbolic links in the SSH configuration path.')
    if auth.exists():
        lines = [line for line in auth.read_text().splitlines() if MARK not in line]
        write_private(auth, ('\n'.join(lines) + '\n') if lines else '')
        os.chown(auth, account.pw_uid, account.pw_gid)
    SSHD.unlink(missing_ok=True)
    subprocess.run(['sshd', '-t'], check=True)
    subprocess.run(['systemctl', 'reload', 'ssh'], check=True)
    print('Ghostboard remote key and SSH policy removed.')


def client_config(tool, host, user):
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,255}', host) or not re.fullmatch(r'[a-z_][a-z0-9_-]*', user):
        raise ValueError('Invalid host or user.')
    target = f'{user}@{host}'
    command = ['ssh', '-T', target, 'env', 'DISPLAY=:0', f'XAUTHORITY=/home/{user}/.Xauthority', 'node', SERVER]
    if tool == 'claude':
        print('claude mcp add --scope user ghostboard-pi5 -- ' + ' '.join(command))
    elif tool == 'codex':
        print('codex mcp add ghostboard-pi5 -- ' + ' '.join(command))
    else:
        print(json.dumps({'mcpServers': {'ghostboard-pi5': {'type': 'stdio', 'command': command[0], 'args': command[1:]}}}, indent=2))


def internet_enable():
    if os.geteuid() != 0:
        raise RuntimeError('Run internet-enable with sudo.')
    if not Path('/usr/bin/tailscale').exists() and not Path('/usr/local/bin/tailscale').exists():
        raise RuntimeError('Install Tailscale from https://tailscale.com/docs/install/linux first.')
    subprocess.run(['systemctl', 'enable', '--now', 'tailscaled'], check=True)
    subprocess.run(['tailscale', 'up'], check=True)
    subprocess.run(['tailscale', 'set', '--ssh'], check=True)
    subprocess.run(['tailscale', 'status'], check=True)
    subprocess.run(['tailscale', 'ip'], check=True)
    print('Internet access enabled through the private tailnet. Review its SSH access policy.')


def main():
    ap = argparse.ArgumentParser(description='GHOSTBOARD paired remote control')
    sub = ap.add_subparsers(dest='command', required=True)
    pair = sub.add_parser('enable')
    pair.add_argument('--user', required=True)
    pair.add_argument('--public-key', required=True)
    off = sub.add_parser('disable')
    off.add_argument('--user', required=True)
    cfg = sub.add_parser('client-config')
    cfg.add_argument('--tool', choices=['claude', 'codex', 'json'], required=True)
    cfg.add_argument('--host', required=True)
    cfg.add_argument('--user', default='ghost')
    sub.add_parser('internet-enable')
    sub.add_parser('status')
    args = ap.parse_args()
    try:
        if args.command == 'enable':
            enable(args.user, args.public_key)
        elif args.command == 'disable':
            disable(args.user)
        elif args.command == 'client-config':
            client_config(args.tool, args.host, args.user)
        elif args.command == 'internet-enable':
            internet_enable()
        else:
            active = subprocess.run(['systemctl', 'is-active', 'ssh'], capture_output=True, text=True).stdout.strip()
            print('SSH: ' + (active or 'unknown'))
            print('Ghostboard policy: ' + ('enabled' if SSHD.exists() else 'disabled'))
            if shutil.which('tailscale'):
                state = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True).returncode
                print('Tailscale: ' + ('connected' if state == 0 else 'installed, offline'))
            else:
                print('Tailscale: not installed')
        return 0
    except (KeyError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
