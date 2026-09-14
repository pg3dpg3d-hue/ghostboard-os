"""Authenticated loopback transport for landmarks and safe Spatial commands."""
from collections import deque
import json
import math
import os
from pathlib import Path
import secrets
import socket
import threading
import time

COMMANDS = {'point', 'select', 'orbit', 'release', 'zoom_in', 'zoom_out',
            'explode', 'rotate_left', 'rotate_right', 'tilt_up', 'tilt_down', 'pause'}
ENDPOINT = Path.home() / '.local/state/ghostboard/hand-spatial.json'


def validate_event(event):
    if not isinstance(event, dict) or set(event) - {
        'timestamp', 'normalized', 'screen', 'handedness', 'gesture', 'confidence',
        'mode', 'command', 'amount'}:
        raise ValueError('Invalid event fields.')
    if event.get('mode') != 'spatial' or event.get('command') not in COMMANDS:
        raise ValueError('Unsupported Spatial command.')
    for key, low, high in [('timestamp', 0, 1e12), ('confidence', 0, 1), ('amount', 0, 10)]:
        value = event.get(key, 0)
        if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Invalid ' + key)
    for key, limit in [('normalized', 1), ('screen', 65535)]:
        point = event.get(key)
        if point is None:
            continue
        if (not isinstance(point, (list, tuple)) or len(point) != 2 or
                any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= limit for v in point)):
            raise ValueError('Invalid coordinates.')
    if event.get('handedness') not in ('Left', 'Right'):
        raise ValueError('Invalid handedness.')
    if not isinstance(event.get('gesture'), str) or len(event['gesture']) > 40:
        raise ValueError('Invalid gesture.')
    return event


class Bridge:
    def __init__(self, stop_file, endpoint=ENDPOINT):
        self.stop_file, self.endpoint = Path(stop_file), Path(endpoint)
        self.token = secrets.token_hex(32)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('127.0.0.1', 0))
        self.socket.settimeout(.1)
        self.events = deque(maxlen=128)
        self.sequence = 0
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.last_timestamp = -1

    def start(self):
        from hand_tracking import write_state
        write_state({'port': self.socket.getsockname()[1], 'token': self.token}, self.endpoint)
        os.chmod(self.endpoint, 0o600)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def _run(self):
        while not self.done.is_set():
            try:
                data, address = self.socket.recvfrom(8193)
                if address[0] != '127.0.0.1' or len(data) > 8192:
                    continue
                self.accept(json.loads(data))
            except (OSError, ValueError, TypeError):
                continue

    def accept(self, envelope):
        if not isinstance(envelope, dict) or not secrets.compare_digest(str(envelope.get('token', '')), self.token):
            return False
        event = validate_event(envelope.get('event'))
        now = time.monotonic()
        if self.stop_file.exists() or not 0 <= now - event['timestamp'] <= .5:
            return False
        with self.lock:
            if event['timestamp'] < self.last_timestamp:
                return False
            self.last_timestamp = event['timestamp']
            self.sequence += 1
            self.events.append({'id': self.sequence, 'event': event})
        return True

    def read(self, after=0):
        with self.lock:
            if self.stop_file.exists():
                self.events.clear()
            now = time.monotonic()
            return {'cursor': self.sequence, 'events': [e for e in self.events
                    if e['id'] > after and now - e['event']['timestamp'] <= .5]}

    def close(self):
        self.done.set()
        self.socket.close()
        if hasattr(self, 'thread'):
            self.thread.join(1)
        try:
            if json.loads(self.endpoint.read_text()).get('token') == self.token:
                self.endpoint.unlink()
        except (OSError, ValueError):
            pass


class Channel:
    def __init__(self, endpoint=ENDPOINT):
        self.endpoint = Path(endpoint)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def emit(self, event):
        if event.get('mode') != 'spatial':
            return
        validate_event(event)
        try:
            endpoint = json.loads(self.endpoint.read_text())
        except (OSError, ValueError):
            return  # Spatial need not be running in Pointer/Presentation sessions.
        port = endpoint.get('port')
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Invalid local Spatial port.')
        payload = json.dumps({'token': endpoint['token'], 'event': event}, allow_nan=False).encode()
        if len(payload) > 8192:
            raise ValueError('Event too large.')
        self.socket.sendto(payload, ('127.0.0.1', port))

    def close(self):
        self.socket.close()
