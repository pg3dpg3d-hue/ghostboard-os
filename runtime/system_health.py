#!/usr/bin/env python3
"""Read-only, bounded system health aggregation for Ghostboard."""
import concurrent.futures
import json
from pathlib import Path
import subprocess

import ghostboard as gb

SCHEMA_VERSION = 1
STOP = gb.STOP


def _command(command, timeout):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return {'status': 'unavailable', 'ok': True, 'available': False, 'reason': f'{command[0]} not installed'}
    except subprocess.TimeoutExpired:
        return {'status': 'degraded', 'ok': False, 'available': True, 'reason': 'timeout'}
    if result.returncode:
        return {'status': 'degraded', 'ok': False, 'available': True,
                'reason': (result.stderr or result.stdout or f'exit {result.returncode}').strip()[:500]}
    text = result.stdout.strip()
    data = None
    if text:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            pass
    return {'status': 'ok', 'ok': True, 'available': True, 'data': data, 'output': text[:2000]}


def _thermal():
    values = []
    root = Path('/sys/class/thermal')
    for path in root.glob('thermal_zone*/temp') if root.exists() else ():
        try:
            values.append(int(path.read_text().strip()) / 1000.0)
        except (OSError, ValueError):
            continue
    if not values:
        return {'status': 'unavailable', 'ok': True, 'available': False, 'hottest_celsius': None}
    hottest = max(values)
    return {'status': 'degraded' if hottest >= 80 else 'ok', 'ok': hottest < 80,
            'available': True, 'hottest_celsius': hottest}


def _stop(stopped):
    return {'status': 'degraded' if stopped else 'ok', 'ok': not stopped, 'available': True, 'stopped': stopped,
            'reason': 'computer use STOP flag is active' if stopped else ''}


def snapshot(timeout=2.0):
    """Return one read-only health snapshot. External probes run concurrently and are bounded."""
    timeout = min(10.0, max(0.1, float(timeout)))
    stopped = STOP.exists()
    probes = {'stop': _stop(stopped), 'thermal': _thermal()}
    commands = {
        'power': ['vcgencmd', 'get_throttled'],
        'services': ['systemctl', '--user', '--failed', '--no-legend', '--plain'],
        'doctor': ['ghost-system', 'doctor', '--json'],
        'hardware': ['ghost-hardware', 'status'],
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(commands)) as pool:
        futures = {name: pool.submit(_command, command, timeout) for name, command in commands.items()}
        for name, future in futures.items():
            try:
                probes[name] = future.result(timeout=timeout + 0.25)
            except concurrent.futures.TimeoutError:
                probes[name] = {'status': 'degraded', 'ok': False, 'available': True, 'reason': 'timeout'}
            except Exception as exc:
                probes[name] = {'status': 'degraded', 'ok': False, 'available': True, 'reason': str(exc)[:500]}
    required = ('stop', 'doctor')
    degraded = [name for name, probe in probes.items() if probe.get('available', True) and not probe.get('ok', False)]
    overall = 'degraded' if any(name in degraded for name in required) else ('partial' if degraded else 'ok')
    return {'schema_version': SCHEMA_VERSION, 'overall': overall, 'agent_stopped': stopped,
            'degraded': degraded, 'probes': probes}


def format_text(report):
    lines = [f"System health: {report['overall'].upper()}"]
    for name, probe in report['probes'].items():
        detail = probe.get('reason') or ('unavailable' if not probe.get('available', True) else '')
        lines.append(f"{name:10} {probe['status'].upper()}" + (f' — {detail}' if detail else ''))
    return '\n'.join(lines)
