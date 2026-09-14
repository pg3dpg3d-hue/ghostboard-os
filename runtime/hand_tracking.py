#!/usr/bin/env python3
"""GHOSTBOARD Hand Control — suivi des mains local pour Raspberry Pi 5.

Tout le traitement reste sur le Pi : aucune image n'est envoyée sur Internet,
écrite sur disque ni conservée après traitement. Seuls des points normalisés,
des gestes et des événements en découlent.

Le module est découpé en couches indépendantes et testables sans caméra, sans
Pi et sans serveur graphique :

1. acquisition caméra      -> CameraSource (Picamera2, V4L2/OpenCV, simulée)
2. détection des points    -> HandTrackerBackend (MediaPipe, simulé, Hailo à venir)
3. filtrage/stabilisation  -> OneEuroFilter, PointerSmoother, Calibration
4. reconnaissance gestes   -> GestureRecognizer (indépendant de MediaPipe)
5. conversion en actions   -> ActionSink (xdotool réel, canal local, simulé)
6. interface/état service  -> HandControlEngine, fichiers d'état et de contrôle

La machine d'état de sécurité (DISABLED, ARMED, ACTIVE, PAUSED, STOPPED) et le
respect impératif du fichier STOP partagé de Ghostboard vivent dans l'engine.
"""
from __future__ import annotations

import argparse
import signal
import secrets
from contextlib import ExitStack
import datetime as dt
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

# On réutilise l'infrastructure existante : STOP partagé, VERSION, STATE.
try:  # import souple pour rester testable hors arborescence installée
    import ghostboard as gb
    STATE_DIR = gb.STATE
    STOP_FILE = gb.STOP
    GB_VERSION = gb.VERSION
except Exception:  # pragma: no cover - repli minimal si ghostboard indisponible
    STATE_DIR = Path.home() / '.local/state/ghostboard'
    STOP_FILE = STATE_DIR / 'agent.stop'
    GB_VERSION = 'unknown'

CONFIG_DIR = Path.home() / '.config/ghostboard'
CONFIG_FILE = CONFIG_DIR / 'hand-tracking.json'
STATE_FILE = STATE_DIR / 'hand-control.json'
CONTROL_FILE = STATE_DIR / 'hand-control.cmd'

VERSION = '0.2.0-hand'

# ---------------------------------------------------------------------------
#  Points de la main (contrat MediaPipe : 21 points normalisés par main)
# ---------------------------------------------------------------------------
WRIST = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20
LANDMARK_COUNT = 21

# Gestes reconnus (chaînes stables : sérialisées dans les événements et l'état).
G_MOVE = 'pointer_move'
G_LEFT_CLICK = 'left_click'
G_RIGHT_CLICK = 'right_click'
G_DOUBLE_CLICK = 'double_click'
G_DRAG_START = 'drag_start'
G_DRAG_MOVE = 'drag_move'
G_DRAG_END = 'drag_end'
G_SCROLL = 'scroll'
G_SWIPE_LEFT = 'swipe_left'
G_SWIPE_RIGHT = 'swipe_right'
G_OPEN_PALM = 'open_palm'
G_ZOOM = 'zoom'
G_SPREAD = 'spread'

# Poses instantanées.
P_NONE = 'none'
P_POINT = 'point'
P_PINCH = 'pinch'
P_PINCH_MIDDLE = 'pinch_middle'
P_TWO_FINGER = 'two_finger'
P_OPEN_PALM = 'open_palm'
P_FIST = 'fist'
P_SPREAD = 'spread'
P_UNKNOWN = 'unknown'

# États de la machine de sécurité.
S_DISABLED = 'DISABLED'
S_ARMED = 'ARMED'
S_ACTIVE = 'ACTIVE'
S_PAUSED = 'PAUSED'
S_STOPPED = 'STOPPED'

MODES = ('pointer', 'spatial', 'presentation')
BACKENDS = ('auto', 'mediapipe', 'simulated')  # 'hailo' non pris en charge : voir HailoBackend
CAMERAS = ('auto', 'picamera2', 'v4l2', 'simulated')


# ===========================================================================
#  Configuration
# ===========================================================================
DEFAULT_CONFIG = {
    'backend': 'auto',
    'model_path': str(Path.home() / '.local/share/ghostboard/models/hand_landmarker.task'),
    'preferred_hand': 'auto',
    'require_click_auth': True,
    'driver_switch_ms': 600,
    'driver_proximity': 0.25,
    'bimanual_zoom_deadband': 0.02,
    'sample_timeout_ms': 500,
    'worker_timeout_ms': 15000,
    'click_min_ms': 60,
    'bimanual_zoom_gain': 2.0,
    'camera': 'auto',
    'camera_device': '/dev/video0',
    'analysis_width': 640,
    'analysis_height': 480,
    'target_fps': 30,
    'max_hands': 1,
    'mode': 'pointer',
    'flip_horizontal': True,
    'confidence_threshold': 0.6,
    'dead_zone': 0.008,
    'pointer_speed_limit': 2500.0,
    'one_euro_min_cutoff': 1.2,
    'one_euro_beta': 0.03,
    'one_euro_dcutoff': 1.0,
    'pinch_on': 0.045,
    'pinch_off': 0.075,
    'min_validation_frames': 3,
    'gesture_cooldown_ms': 350,
    'double_click_ms': 450,
    'drag_hold_ms': 450,
    'swipe_velocity': 1.4,
    'swipe_cooldown_ms': 800,
    'scroll_step': 0.03,
    'scroll_gain': 1,
    'zoom_step': 0.02,
    'spread_threshold': 1.2,
    'hand_lost_frames': 5,
    'arming_hold_ms': 900,
    'spatial_channel_host': '127.0.0.1',
    'spatial_channel_port': 0,
    'calibration': {
        'enabled': False,
        'top_left': [0.1, 0.1],
        'top_right': [0.9, 0.1],
        'bottom_right': [0.9, 0.9],
        'bottom_left': [0.1, 0.9],
    },
}

# Bornes de validation : (min, max) ; les clés absentes sont refusées.
_NUMERIC_BOUNDS = {
    'driver_switch_ms': (0, 5000),
    'driver_proximity': (0.02, 1.0),
    'bimanual_zoom_deadband': (0.001, 0.5),
    'sample_timeout_ms': (100, 3000),
    'worker_timeout_ms': (1000, 60000),
    'click_min_ms': (20, 300),
    'bimanual_zoom_gain': (0.1, 10.0),
    'analysis_width': (160, 1920),
    'analysis_height': (120, 1080),
    'target_fps': (1, 120),
    'max_hands': (1, 2),
    'confidence_threshold': (0.0, 1.0),
    'dead_zone': (0.0, 0.2),
    'pointer_speed_limit': (10.0, 100000.0),
    'one_euro_min_cutoff': (0.0001, 100.0),
    'one_euro_beta': (0.0, 10.0),
    'one_euro_dcutoff': (0.0001, 100.0),
    'pinch_on': (0.001, 1.0),
    'pinch_off': (0.001, 2.0),
    'min_validation_frames': (1, 60),
    'gesture_cooldown_ms': (0, 5000),
    'double_click_ms': (50, 2000),
    'drag_hold_ms': (50, 5000),
    'swipe_velocity': (0.1, 20.0),
    'swipe_cooldown_ms': (0, 5000),
    'scroll_step': (0.001, 1.0),
    'scroll_gain': (1, 25),
    'zoom_step': (0.001, 1.0),
    'spread_threshold': (0.5, 5.0),
    'hand_lost_frames': (1, 120),
    'arming_hold_ms': (100, 10000),
    'spatial_channel_port': (0, 65535),
}


def validate_config(config):
    """Valide un dictionnaire de configuration ; lève ValueError si invalide.

    Aucune correction silencieuse : une valeur hors bornes ou un mode inconnu
    est une erreur, pour éviter qu'une configuration douteuse pilote la souris.
    """
    if not isinstance(config, dict):
        raise ValueError('Configuration must be a JSON object.')
    missing = set(DEFAULT_CONFIG) - set(config)
    if missing:
        raise ValueError('Missing configuration keys: ' + ', '.join(sorted(missing)))
    unknown = set(config) - set(DEFAULT_CONFIG)
    if unknown:
        raise ValueError('Unknown configuration keys: ' + ', '.join(sorted(unknown)))
    if config['backend'] not in BACKENDS:
        raise ValueError('backend must be one of ' + ', '.join(BACKENDS))
    if config['camera'] not in CAMERAS:
        raise ValueError('camera must be one of ' + ', '.join(CAMERAS))
    if not isinstance(config['model_path'], str) or not config['model_path']:
        raise ValueError('model_path must be a local path.')
    if config['preferred_hand'] not in ('auto', 'Left', 'Right'):
        raise ValueError('preferred_hand must be auto, Left or Right.')
    if config['mode'] not in MODES:
        raise ValueError('mode must be one of ' + ', '.join(MODES))
    for key in ('flip_horizontal', 'require_click_auth'):
        if not isinstance(config[key], bool):
            raise ValueError(key + ' must be a boolean.')
    if not isinstance(config['camera_device'], str) or not config['camera_device']:
        raise ValueError('camera_device must be a non-empty string.')
    for key, (low, high) in _NUMERIC_BOUNDS.items():
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(key + ' must be a number.')
        if isinstance(DEFAULT_CONFIG[key], int) and not isinstance(value, int):
            raise ValueError(key + ' must be an integer.')
        if not (low <= value <= high):
            raise ValueError(f'{key} must be within [{low}, {high}].')
    if config['pinch_off'] <= config['pinch_on']:
        raise ValueError('pinch_off must be greater than pinch_on (hysteresis).')
    if config['spatial_channel_host'] != '127.0.0.1':
        raise ValueError('spatial_channel_host must be 127.0.0.1.')
    calib = config['calibration']
    if not isinstance(calib, dict):
        raise ValueError('calibration must be an object.')
    if not isinstance(calib.get('enabled'), bool):
        raise ValueError('calibration.enabled must be a boolean.')
    for corner in ('top_left', 'top_right', 'bottom_right', 'bottom_left'):
        pt = calib.get(corner)
        if (not isinstance(pt, (list, tuple)) or len(pt) != 2
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in pt)
                or any(not (0.0 <= v <= 1.0) for v in pt)):
            raise ValueError(f'calibration.{corner} must be two numbers in [0, 1].')
    return config


def load_config(path=None):
    """Charge la configuration en complétant les clés manquantes par les défauts."""
    path = CONFIG_FILE if path is None else path
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    path = Path(path)
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('Configuration file must contain a JSON object.')
        unknown = set(data) - set(DEFAULT_CONFIG)
        if unknown:
            raise ValueError('Unknown configuration keys: ' + ', '.join(sorted(unknown)))
        for key, value in data.items():
            if key == 'calibration' and isinstance(value, dict):
                merged['calibration'].update(value)
            else:
                merged[key] = value
    return validate_config(merged)


def save_config(config, path=None):
    """Écrit la configuration de façon atomique après validation."""
    validate_config(config)
    path = Path(CONFIG_FILE if path is None else path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.hand-config-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(config, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return str(path)


# ===========================================================================
#  Géométrie et classification de pose (indépendantes de MediaPipe)
# ===========================================================================
def _distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def hand_scale(landmarks):
    """Taille de référence de la main pour rendre les seuils indépendants de la
    distance à la caméra : distance poignet -> base du majeur."""
    scale = _distance(landmarks[WRIST], landmarks[MIDDLE_MCP])
    return scale if scale > 1e-6 else 1e-6


def _finger_extended(landmarks, tip, pip, factor=1.05):
    wrist = landmarks[WRIST]
    return _distance(landmarks[tip], wrist) > _distance(landmarks[pip], wrist) * factor


def fingers_extended(landmarks):
    """Retourne un dict pouce/index/majeur/annulaire/auriculaire -> bool."""
    return {
        'thumb': _finger_extended(landmarks, THUMB_TIP, THUMB_IP, 1.02),
        'index': _finger_extended(landmarks, INDEX_TIP, INDEX_PIP),
        'middle': _finger_extended(landmarks, MIDDLE_TIP, MIDDLE_PIP),
        'ring': _finger_extended(landmarks, RING_TIP, RING_PIP),
        'pinky': _finger_extended(landmarks, PINKY_TIP, PINKY_PIP),
    }


def pinch_ratio(landmarks, tip):
    """Distance pouce -> bout de doigt donné, normalisée par la taille de main."""
    return _distance(landmarks[THUMB_TIP], landmarks[tip]) / hand_scale(landmarks)


class HandSample:
    """Une main détectée sur une image : 21 points normalisés + méta."""

    __slots__ = ('landmarks', 'handedness', 'confidence', 'timestamp')

    def __init__(self, landmarks, handedness='Right', confidence=1.0, timestamp=0.0):
        if len(landmarks) != LANDMARK_COUNT:
            raise ValueError('A hand sample needs exactly 21 landmarks.')
        self.landmarks = [(float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0)
                          for p in landmarks]
        if any(not math.isfinite(v) for point in self.landmarks for v in point):
            raise ValueError('Landmarks must be finite.')
        if handedness not in ('Left', 'Right'):
            raise ValueError('Unknown handedness.')
        if not math.isfinite(float(confidence)) or not 0 <= float(confidence) <= 1:
            raise ValueError('Confidence must be finite and within [0, 1].')
        if not math.isfinite(float(timestamp)):
            raise ValueError('Timestamp must be finite.')
        self.handedness = handedness
        self.confidence = float(confidence)
        self.timestamp = float(timestamp)

    @property
    def index_tip(self):
        return self.landmarks[INDEX_TIP]


# ===========================================================================
#  Filtrage et stabilisation
# ===========================================================================
class OneEuroFilter:
    """Filtre 1€ (Casiez et al.) : peu de latence au mouvement, lisse au repos."""

    def __init__(self, min_cutoff=1.0, beta=0.0, d_cutoff=1.0):
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self._x_prev = None
        self._dx_prev = 0.0
        self._t_prev = None

    @staticmethod
    def _alpha(cutoff, dt_):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt_)

    def filter(self, value, timestamp):
        value = float(value)
        if self._t_prev is None or timestamp <= self._t_prev:
            self._x_prev, self._t_prev, self._dx_prev = value, timestamp, 0.0
            return value
        dt_ = timestamp - self._t_prev
        dx = (value - self._x_prev) / dt_
        a_d = self._alpha(self.d_cutoff, dt_)
        dx_hat = a_d * dx + (1 - a_d) * self._dx_prev
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt_)
        x_hat = a * value + (1 - a) * self._x_prev
        self._x_prev, self._dx_prev, self._t_prev = x_hat, dx_hat, timestamp
        return x_hat

    def reset(self):
        self._x_prev = None
        self._dx_prev = 0.0
        self._t_prev = None


def _solve_linear(matrix, vector):
    """Résout matrix·x = vector (élimination de Gauss, pivot partiel). None si
    quasi singulier. Petite implémentation stdlib : pas de dépendance numpy."""
    n = len(vector)
    a = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        pv = a[col][col]
        for j in range(col, n + 1):
            a[col][j] /= pv
        for r in range(n):
            if r != col and abs(a[r][col]) > 1e-15:
                factor = a[r][col]
                for j in range(col, n + 1):
                    a[r][j] -= factor * a[col][j]
    return [a[i][n] for i in range(n)]


def solve_homography(src, dst):
    """Transformation projective 3x3 envoyant les 4 points `src` sur `dst`.

    Retourne les 8 coefficients (a..h, i=1) ou None si les points sont dégénérés
    (colinéaires). C'est ce qui permet une vraie correction de perspective :
    la zone calibrée n'a pas à être un rectangle parallèle à la caméra."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rhs.append(u)
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs.append(v)
    return _solve_linear(rows, rhs)


class Calibration:
    """Mappe un point normalisé caméra vers l'espace écran [0,1].

    La calibration capture les quatre coins RÉELS de la zone utile (mesurés par
    le tracker). On calcule alors une **homographie** quadrilatère -> carré unité
    : correction de perspective complète, sans supposer un rectangle parallèle à
    la caméra. Repli sur le rectangle englobant seulement si les coins sont
    dégénérés. L'inversion horizontale (miroir de la caméra frontale) est
    appliquée après la transformation."""

    def __init__(self, calib, flip_horizontal):
        self.enabled = bool(calib.get('enabled'))
        self.flip = bool(flip_horizontal)
        src = [tuple(calib['top_left']), tuple(calib['top_right']),
               tuple(calib['bottom_right']), tuple(calib['bottom_left'])]
        dst = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        self.homography = solve_homography(src, dst) if self.enabled else None
        xs = [c[0] for c in src]
        ys = [c[1] for c in src]
        self.min_x, self.max_x = min(xs), max(xs)
        self.min_y, self.max_y = min(ys), max(ys)

    def _project(self, nx, ny):
        a, b, c, d, e, f, g, hh = self.homography
        denom = g * nx + hh * ny + 1.0
        if abs(denom) < 1e-9:
            return None
        return (a * nx + b * ny + c) / denom, (d * nx + e * ny + f) / denom

    def map(self, nx, ny):
        if self.enabled and self.homography is not None:
            projected = self._project(nx, ny)
            if projected is not None:
                nx, ny = projected
        elif self.enabled and self.max_x - self.min_x > 1e-3 and self.max_y - self.min_y > 1e-3:
            # Repli rectangle englobant si l'homographie est dégénérée.
            nx = (nx - self.min_x) / (self.max_x - self.min_x)
            ny = (ny - self.min_y) / (self.max_y - self.min_y)
        if self.flip:
            nx = 1.0 - nx
        return min(1.0, max(0.0, nx)), min(1.0, max(0.0, ny))


class PointerSmoother:
    """Lissage 1€ + zone morte + compensation de tremblement + limite de vitesse."""

    def __init__(self, config, screen_size):
        self.dead_zone = config['dead_zone']
        self.speed_limit = config['pointer_speed_limit']
        self.calib = Calibration(config['calibration'], config['flip_horizontal'])
        self.fx = OneEuroFilter(config['one_euro_min_cutoff'], config['one_euro_beta'], config['one_euro_dcutoff'])
        self.fy = OneEuroFilter(config['one_euro_min_cutoff'], config['one_euro_beta'], config['one_euro_dcutoff'])
        self.width, self.height = screen_size
        self._px = None
        self._py = None
        self._t = None

    def reset(self):
        self.fx.reset()
        self.fy.reset()
        self._px = self._py = self._t = None

    def update(self, nx, ny, timestamp):
        """Retourne (screen_x, screen_y) entiers, ou None si sous la zone morte."""
        mx, my = self.calib.map(nx, ny)
        sx = self.fx.filter(mx, timestamp)
        sy = self.fy.filter(my, timestamp)
        px = sx * (self.width - 1)
        py = sy * (self.height - 1)
        if self._px is None:
            self._px, self._py, self._t = px, py, timestamp
            return int(round(px)), int(round(py))
        # Zone morte : ignorer les micro-déplacements (tremblement résiduel).
        move_norm = math.hypot(sx - (self._px / (self.width - 1)), sy - (self._py / (self.height - 1)))
        if move_norm < self.dead_zone:
            return None
        # Limite de vitesse : bornage du déplacement par seconde.
        dt_ = max(1e-3, timestamp - self._t)
        max_step = self.speed_limit * dt_
        dx, dy = px - self._px, py - self._py
        dist = math.hypot(dx, dy)
        if dist > max_step and dist > 0:
            scale = max_step / dist
            px = self._px + dx * scale
            py = self._py + dy * scale
        self._px, self._py, self._t = px, py, timestamp
        return int(round(px)), int(round(py))

    @property
    def last_pixel(self):
        if self._px is None:
            return None
        return int(round(self._px)), int(round(self._py))


# ===========================================================================
#  Reconnaissance de gestes (moteur indépendant de MediaPipe)
# ===========================================================================
class Gesture:
    __slots__ = ('kind', 'nx', 'ny', 'direction', 'amount')

    def __init__(self, kind, nx=None, ny=None, direction=None, amount=None):
        self.kind = kind
        self.nx = nx
        self.ny = ny
        self.direction = direction
        self.amount = amount

    def __repr__(self):
        return f'Gesture({self.kind}, dir={self.direction}, amount={self.amount})'


class Telemetry:
    __slots__ = ('pose', 'nx', 'ny', 'confidence', 'hand_present', 'handedness')

    def __init__(self, pose, nx, ny, confidence, hand_present, handedness):
        self.pose = pose
        self.nx = nx
        self.ny = ny
        self.confidence = confidence
        self.hand_present = hand_present
        self.handedness = handedness


class GestureRecognizer:
    """Transforme un flux de HandSample en poses et en événements gestuels.

    Ce moteur ne dépend que de coordonnées normalisées : il fonctionne
    identiquement avec MediaPipe, un backend simulé ou toute autre source de
    21 points."""

    def __init__(self, config):
        self.cfg = config
        self._pinch_active = False
        self._pinch_start_t = 0.0
        self._pinch_is_drag = False
        self._pinch_start_pos = (0.0, 0.0)
        self._middle_active = False
        self._middle_start_t = 0.0
        self._last_right_t = -1e9
        self._pending_tap_t = None
        self._pending_tap_pos = (0.0, 0.0)
        self._last_scroll_pos = None
        self._last_scroll_t = 0.0
        self._last_swipe_t = -1e9
        self._swipe_hist = deque(maxlen=12)
        self._pose_streak_pose = P_NONE
        self._pose_streak = 0
        self._zoom_prev = None
        self._palm_latched = False
        self._spread_latched = False

    # -- classification ----------------------------------------------------
    def classify(self, sample):
        lm = sample.landmarks
        ext = fingers_extended(lm)
        pinch_i = pinch_ratio(lm, INDEX_TIP)
        pinch_m = pinch_ratio(lm, MIDDLE_TIP)
        on, off = self.cfg['pinch_on'], self.cfg['pinch_off']
        # Hystérésis sur le pincement pouce-index.
        if self._pinch_active:
            pinch_index_now = pinch_i < off
        else:
            pinch_index_now = pinch_i < on
        if pinch_index_now:
            return P_PINCH, ext
        if pinch_m < on and not ext['index']:
            return P_PINCH_MIDDLE, ext
        extended_count = sum(ext.values())
        if ext['index'] and ext['middle'] and not ext['ring'] and not ext['pinky']:
            return P_TWO_FINGER, ext
        if ext['index'] and not ext['middle'] and not ext['ring'] and not ext['pinky']:
            return P_POINT, ext
        if extended_count >= 4:
            spread = _distance(lm[INDEX_TIP], lm[PINKY_TIP]) / hand_scale(lm)
            return (P_SPREAD if spread > self.cfg['spread_threshold'] else P_OPEN_PALM), ext
        if extended_count <= 1:
            return P_FIST, ext
        return P_UNKNOWN, ext

    def _stable(self, pose):
        if pose == self._pose_streak_pose:
            self._pose_streak += 1
        else:
            self._pose_streak_pose = pose
            self._pose_streak = 1
        return self._pose_streak >= self.cfg['min_validation_frames']

    # -- boucle ------------------------------------------------------------
    def update(self, sample, now):
        """Retourne (events: list[Gesture], telemetry: Telemetry)."""
        if sample is None:
            self._on_hand_lost()
            return [], Telemetry(P_NONE, None, None, 0.0, False, None)
        pose, ext = self.classify(sample)
        stable = self._stable(pose)
        nx, ny = sample.index_tip[0], sample.index_tip[1]
        events = []

        # Pointeur / glisser : main pointée ou pincée.
        if pose in (P_POINT, P_PINCH, P_TWO_FINGER):
            events.append(Gesture(G_MOVE, nx, ny))

        # --- pincement pouce-index : clic / double-clic / glisser ---------
        if pose == P_PINCH:
            if not self._pinch_active:
                self._pinch_active = True
                self._pinch_start_t = now
                self._pinch_is_drag = False
                self._pinch_start_pos = (nx, ny)
            else:
                moved = _distance((nx, ny), self._pinch_start_pos)
                held_ms = (now - self._pinch_start_t) * 1000
                if not self._pinch_is_drag and (held_ms >= self.cfg['drag_hold_ms'] or moved > 0.06):
                    self._pinch_is_drag = True
                    events.append(Gesture(G_DRAG_START, nx, ny))
                if self._pinch_is_drag:
                    events.append(Gesture(G_DRAG_MOVE, nx, ny))
        else:
            if self._pinch_active:
                held_ms = (now - self._pinch_start_t) * 1000
                self._pinch_active = False
                if self._pinch_is_drag:
                    events.append(Gesture(G_DRAG_END, nx, ny))
                    self._pinch_is_drag = False
                elif held_ms < self.cfg['drag_hold_ms']:
                    self._register_tap(now, (nx, ny), events)

        # --- pincement pouce-majeur : clic droit --------------------------
        if pose == P_PINCH_MIDDLE:
            if not self._middle_active:
                self._middle_active = True
                self._middle_start_t = now
        else:
            if self._middle_active:
                self._middle_active = False
                quick = (now - self._middle_start_t) * 1000 < self.cfg['drag_hold_ms']
                cooldown_ok = (now - self._last_right_t) * 1000 >= self.cfg['gesture_cooldown_ms']
                if quick and cooldown_ok:
                    events.append(Gesture(G_RIGHT_CLICK, nx, ny))
                    self._last_right_t = now

        # --- tap différé -> clic simple si aucun second tap ---------------
        if self._pending_tap_t is not None and (now - self._pending_tap_t) * 1000 > self.cfg['double_click_ms']:
            events.append(Gesture(G_LEFT_CLICK, *self._pending_tap_pos))
            self._pending_tap_t = None

        # --- défilement à deux doigts -------------------------------------
        if pose == P_TWO_FINGER and stable:
            self._update_scroll(nx, ny, now, events)
        else:
            self._last_scroll_pos = None

        # --- paume ouverte -> pause (une seule fois par maintien) ---------
        if pose == P_OPEN_PALM and stable:
            if not self._palm_latched:
                events.append(Gesture(G_OPEN_PALM, nx, ny))
                self._palm_latched = True
        elif pose != P_OPEN_PALM:
            self._palm_latched = False

        # --- écartement -> vue éclatée (une seule fois par maintien) ------
        if pose == P_SPREAD and stable:
            if not self._spread_latched:
                events.append(Gesture(G_SPREAD, nx, ny))
                self._spread_latched = True
        elif pose != P_SPREAD:
            self._spread_latched = False

        # --- zoom (distance pouce-index en pose ouverte/pincée) -----------
        self._update_zoom(sample, pose, events)

        # --- balayage horizontal ------------------------------------------
        self._update_swipe(sample, pose, now, events)

        tel = Telemetry(pose, nx, ny, sample.confidence, True, sample.handedness)
        return events, tel

    def _register_tap(self, now, pos, events):
        if self._pending_tap_t is not None and (now - self._pending_tap_t) * 1000 <= self.cfg['double_click_ms']:
            events.append(Gesture(G_DOUBLE_CLICK, *pos))
            self._pending_tap_t = None
        else:
            self._pending_tap_t = now
            self._pending_tap_pos = pos

    def _update_scroll(self, nx, ny, now, events):
        if self._last_scroll_pos is None:
            self._last_scroll_pos = (nx, ny)
            return
        dy = ny - self._last_scroll_pos[1]
        dx = nx - self._last_scroll_pos[0]
        step = self.cfg['scroll_step']
        if abs(dy) >= step and abs(dy) >= abs(dx):
            amount = min(self.cfg['scroll_gain'], max(1, int(abs(dy) / step)))
            events.append(Gesture(G_SCROLL, nx, ny, direction=('down' if dy > 0 else 'up'), amount=amount))
            self._last_scroll_pos = (nx, ny)
        elif abs(dx) >= step:
            amount = min(self.cfg['scroll_gain'], max(1, int(abs(dx) / step)))
            events.append(Gesture(G_SCROLL, nx, ny, direction=('right' if dx > 0 else 'left'), amount=amount))
            self._last_scroll_pos = (nx, ny)

    def _update_zoom(self, sample, pose, events):
        if pose not in (P_OPEN_PALM, P_SPREAD, P_PINCH):
            self._zoom_prev = None
            return
        ratio = pinch_ratio(sample.landmarks, INDEX_TIP)
        if self._zoom_prev is not None:
            delta = ratio - self._zoom_prev
            if abs(delta) >= self.cfg['zoom_step']:
                events.append(Gesture(G_ZOOM, sample.index_tip[0], sample.index_tip[1],
                                      direction=('in' if delta > 0 else 'out'), amount=abs(delta)))
        self._zoom_prev = ratio

    def _update_swipe(self, sample, pose, now, events):
        wrist_x = sample.landmarks[WRIST][0]
        self._swipe_hist.append((now, wrist_x))
        # Le balayage est un mouvement franc de la main ouverte-pointée ; la
        # paume tenue reste la pause, le pincement reste le clic/glisser, deux
        # doigts restent le défilement : on les exclut pour éviter les conflits.
        if pose not in (P_POINT, P_FIST, P_UNKNOWN):
            return
        if (now - self._last_swipe_t) * 1000 < self.cfg['swipe_cooldown_ms']:
            return
        if len(self._swipe_hist) < 3:
            return
        t0, x0 = self._swipe_hist[0]
        t1, x1 = self._swipe_hist[-1]
        span = t1 - t0
        if span <= 1e-3 or span > 0.6:
            return
        velocity = (x1 - x0) / span
        if abs(velocity) >= self.cfg['swipe_velocity'] and abs(x1 - x0) > 0.2:
            events.append(Gesture(G_SWIPE_RIGHT if velocity > 0 else G_SWIPE_LEFT))
            self._last_swipe_t = now
            self._swipe_hist.clear()

    def _on_hand_lost(self):
        # Une main perdue termine tout pincement en cours ; l'engine relâche
        # les boutons. On ne garde aucun état de geste partiel.
        self._pose_streak_pose = P_NONE
        self._pose_streak = 0
        self._last_scroll_pos = None
        self._swipe_hist.clear()
        self._zoom_prev = None
        self._palm_latched = False
        self._spread_latched = False


# ===========================================================================
#  Adaptateurs de sortie (table interne explicite ; jamais de shell)
# ===========================================================================
class BaseActionSink:
    """Interface d'injection d'actions bureau. Suit les boutons maintenus."""

    BUTTONS = {'left': 1, 'middle': 2, 'right': 3}

    def __init__(self):
        self.held = set()

    def move(self, x, y):
        raise NotImplementedError

    def click(self, button='left', count=1):
        raise NotImplementedError

    def button_down(self, button='left'):
        raise NotImplementedError

    def button_up(self, button='left'):
        raise NotImplementedError

    def scroll(self, direction, amount):
        raise NotImplementedError

    def desktop(self, relative):
        raise NotImplementedError

    def slide(self, direction):
        raise NotImplementedError

    def release_all(self):
        for button in sorted(self.held):
            try:
                self.button_up(button)
            except Exception:
                pass
        # Failed releases remain tracked so the next cleanup can retry.

    def close(self):
        self.release_all()


class RecordingActionSink(BaseActionSink):
    """Adaptateur simulé : enregistre les actions sans toucher au bureau.

    Aucun test ne déplace réellement le pointeur : il utilise ce sink."""

    def __init__(self, fail_on=None, maxlen=None):
        super().__init__()
        self.actions = [] if maxlen is None else deque(maxlen=maxlen)
        self._fail_on = fail_on

    def _record(self, name, **kw):
        if self._fail_on and name == self._fail_on:
            raise RuntimeError('Simulated output failure on ' + name)
        self.actions.append({'action': name, **kw})

    def move(self, x, y):
        self._record('move', x=int(x), y=int(y))

    def click(self, button='left', count=1):
        self._record('click', button=button, count=int(count))

    def button_down(self, button='left'):
        self.held.add(button)
        self._record('button_down', button=button)

    def button_up(self, button='left'):
        self.held.discard(button)
        self._record('button_up', button=button)

    def scroll(self, direction, amount):
        self._record('scroll', direction=direction, amount=int(amount))

    def desktop(self, relative):
        self._record('desktop', relative=int(relative))

    def slide(self, direction):
        self._record('slide', direction=direction)

    @property
    def names(self):
        return [a['action'] for a in self.actions]


class XdotoolActionSink(BaseActionSink):
    """Injection réelle via xdotool. Toujours une liste d'arguments, jamais de
    shell, jamais de texte provenant de la caméra ou d'un modèle."""

    # Table interne explicite : chaque action -> constructeur d'argv figé.
    _WHEEL = {'up': '4', 'down': '5', 'left': '6', 'right': '7'}
    _SLIDE = {'next': 'Right', 'prev': 'Left'}

    def __init__(self, display=None):
        super().__init__()
        self.display = display or os.environ.get('GHOSTBOARD_MCP_DISPLAY') or os.environ.get('DISPLAY') or ':0'
        if not shutil.which('xdotool'):
            raise RuntimeError('xdotool is required for desktop injection.')

    def _run(self, argv):
        # argv est TOUJOURS une liste de chaînes littérales et d'entiers formatés.
        if argv[0] != 'mouseup' and STOP_FILE.exists():
            self.release_all()
            raise RuntimeError('Shared STOP is active.')
        env = {**os.environ, 'DISPLAY': self.display}
        subprocess.run(['xdotool', *[str(a) for a in argv]], env=env,
                       check=True, capture_output=True, timeout=5)

    def move(self, x, y):
        self._run(['mousemove', int(x), int(y)])

    def click(self, button='left', count=1):
        b = self.BUTTONS.get(button)
        if b is None:
            raise ValueError('Unknown button.')
        self._run(['click', '--repeat', int(count), b])

    def button_down(self, button='left'):
        b = self.BUTTONS.get(button)
        if b is None:
            raise ValueError('Unknown button.')
        self.held.add(button)  # Track even if the command times out after injection.
        self._run(['mousedown', b])

    def button_up(self, button='left'):
        b = self.BUTTONS.get(button)
        if b is None:
            raise ValueError('Unknown button.')
        self._run(['mouseup', b])
        self.held.discard(button)

    def scroll(self, direction, amount):
        wheel = self._WHEEL.get(direction)
        if wheel is None:
            raise ValueError('Unknown scroll direction.')
        self._run(['click', '--repeat', int(amount), wheel])

    def desktop(self, relative):
        self._run(['set_desktop', '--relative', int(relative)])

    def slide(self, direction):
        key = self._SLIDE.get(direction)
        if key is None:
            raise ValueError('Unknown slide direction.')
        self._run(['key', key])


# ===========================================================================
#  Point & Command — interface locale d'événements (canal 127.0.0.1)
# ===========================================================================
def hand_event(now, telemetry, screen_xy, gesture, mode, command=None, amount=None):
    """Construit un événement Point & Command sérialisable.

    Aucune image : seulement horodatage monotone (`timestamp`), coordonnées,
    main, geste, confiance et mode. Le schéma correspond à
    hand_events.validate_event afin qu'un événement Spatial puisse transiter par
    le pont local authentifié sans transformation. Support futur d'une commande
    vocale associée au point désigné."""
    ev = {
        'timestamp': round(now, 6),
        'normalized': None if telemetry.nx is None else [round(telemetry.nx, 5), round(telemetry.ny, 5)],
        'screen': None if screen_xy is None else [int(screen_xy[0]), int(screen_xy[1])],
        'handedness': telemetry.handedness,
        'gesture': gesture,
        'confidence': round(telemetry.confidence, 4),
        'mode': mode,
    }
    if command is not None:
        ev['command'] = command
    if amount is not None:
        ev['amount'] = round(min(10.0, max(0.0, amount)), 4)
    return ev


class BaseEventChannel:
    def emit(self, event):
        raise NotImplementedError

    def close(self):
        pass


class RecordingEventChannel(BaseEventChannel):
    """Canal simulé pour les tests : conserve les événements en mémoire."""

    def __init__(self, maxlen=None):
        self.events = [] if maxlen is None else deque(maxlen=maxlen)

    def emit(self, event):
        # On valide en re-sérialisant : un événement doit rester du JSON pur.
        json.dumps(event)
        self.events.append(event)


class LocalEventChannel(BaseEventChannel):
    """Émetteur JSON en datagrammes UDP, strictement sur boucle locale.

    Utilisé par le mode Spatial et par Point & Command. Aucune API réseau
    externe : l'hôte doit être une adresse de loopback."""

    def __init__(self, host='127.0.0.1', port=0):
        if host not in ('127.0.0.1', '::1', 'localhost'):
            raise ValueError('The local event channel is restricted to loopback.')
        self.host = host
        self.port = int(port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def emit(self, event):
        if not self.port:
            return
        payload = json.dumps(event).encode('utf-8')
        if len(payload) > 8192:
            return
        try:
            self._sock.sendto(payload, (self.host, self.port))
        except OSError:
            pass

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass


# ===========================================================================
#  Machine d'état de sécurité + moteur de contrôle
# ===========================================================================
class HandControlEngine:
    """Relie reconnaissance, sécurité et sortie. Le cœur testable est
    process_sample() : synchrone, sans caméra ni thread."""

    def __init__(self, config, output=None, channel=None, screen_size=(800, 480),
                 stop_file=STOP_FILE, initial_state=S_ARMED, desktop=None):
        self.cfg = config
        self.mode = config['mode']
        self.screen_size = screen_size
        self.stop_file = Path(stop_file)
        self.output = output if output is not None else RecordingActionSink()
        self.channel = channel if channel is not None else RecordingEventChannel()
        # `desktop` (hand_desktop.Desktop, optionnel) : autorisation clavier des
        # clics système (F8 maintenu) et masquage réel du curseur (XFixes).
        self.desktop = desktop
        self.require_click_auth = config['require_click_auth']
        self.recognizer = GestureRecognizer(config)
        self.smoother = PointerSmoother(config, screen_size)
        self.state = initial_state
        self.pointer_visible = True
        self.confidence = 0.0
        self.tracking = False
        self.last_pose = P_NONE
        self.last_event = None
        self.error = None
        self._arm_pose_since = None
        self._lost_frames = 0
        self._spread_cooldown_t = -1e9
        self._perf = PerfMonitor()
        # Conservation de la main pilote (continuité entre frames).
        self._driver_hand = None      # 'Left' / 'Right'
        self._driver_pos = None       # dernière position (nx, ny) du pilote
        self._driver_last_seen = -1e9
        # Zoom à deux mains : référence établie au début du geste.
        self._bimanual_ref = None
        self._spatial_drag_pos = None

    # -- transitions -------------------------------------------------------
    def _release_and(self, new_state):
        try:
            self.output.release_all()
        except Exception:
            pass
        self.smoother.reset()
        self.recognizer = GestureRecognizer(self.cfg)
        self._arm_pose_since = None
        self._bimanual_ref = None
        self._spatial_drag_pos = None
        self.state = new_state

    def pause(self):
        if self.state in (S_ARMED, S_ACTIVE):
            self._release_and(S_PAUSED)

    def resume(self):
        # Reprise = ré-armement explicite : le geste d'armement reste requis.
        if self.state in (S_PAUSED,):
            self.state = S_ARMED
            self._arm_pose_since = None

    def disable(self):
        self._release_and(S_DISABLED)

    def request_active(self):
        if self.state in (S_DISABLED, S_PAUSED, S_STOPPED):
            if self.state == S_STOPPED and self.stop_file.exists():
                return  # le STOP partagé prime : pas de réactivation possible
            self.state = S_ARMED
            self._arm_pose_since = None

    # -- sélection de la main pilote (continuité) --------------------------
    @staticmethod
    def _normalize(sample):
        """Accepte None, un HandSample, ou une liste de HandSample."""
        if sample is None:
            return []
        if isinstance(sample, HandSample):
            return [sample]
        return list(sample)

    def select_driver(self, cands, now):
        """Choisit la main pilote avec continuité : on ne bascule pas sur l'autre
        main pour une confiance momentanément meilleure. On garde la main courante
        (même handedness, proximité de la position précédente) ; à sa disparition,
        on attend driver_switch_ms avant de transférer le contrôle."""
        if not cands:
            return None
        # Continuité : prolonger la main pilote actuelle si elle est présente.
        if self._driver_hand is not None:
            same = [s for s in cands if s.handedness == self._driver_hand]
            if same:
                best = (min(same, key=lambda s: _distance(s.index_tip[:2], self._driver_pos))
                        if self._driver_pos is not None else same[0])
                # On garde la main courante sauf saut invraisemblable (une autre
                # main mal étiquetée avec la même handedness) -> traité en perte.
                if self._driver_pos is None or _distance(best.index_tip[:2], self._driver_pos) <= self.cfg['driver_proximity']:
                    return self._set_driver(best, now)
            # Main pilote absente/incohérente : temporiser avant tout transfert.
            if (now - self._driver_last_seen) * 1000 < self.cfg['driver_switch_ms']:
                return None
        # Nouvelle main pilote : préférence explicite, sinon meilleure confiance.
        pref = self.cfg['preferred_hand']
        if pref in ('Left', 'Right'):
            cands = [s for s in cands if s.handedness == pref] or cands
        return self._set_driver(max(cands, key=lambda s: s.confidence), now)

    def _set_driver(self, sample, now):
        self._driver_hand = sample.handedness
        self._driver_pos = sample.index_tip[:2]
        self._driver_last_seen = now
        return sample

    # -- boucle testable ---------------------------------------------------
    def process_sample(self, sample, now):
        """Traite une image (None, une main, ou une liste de mains).

        Retourne la liste des Gesture pris en compte."""
        hands = self._normalize(sample)
        # 1) STOP partagé : priorité absolue.
        if self.stop_file.exists():
            if self.state != S_STOPPED:
                self._release_and(S_STOPPED)
            self.tracking = bool(hands)
            self.confidence = max((h.confidence for h in hands), default=0.0)
            return []
        # Sortie de STOPPED : jamais automatique. Le fichier STOP disparu ne
        # suffit pas ; il faut une réactivation locale explicite (request_active,
        # via le centre de contrôle ou ghost-hand resume/start). On reste donc
        # STOPPED tant que personne ne réactive.
        if self.state == S_STOPPED:
            self.tracking = bool(hands)
            return []

        if self.state == S_DISABLED:
            return []

        # 2) Mains fiables (au-dessus du seuil de confiance).
        cands = [h for h in hands if h.confidence >= self.cfg['confidence_threshold']]

        # 3) Zoom à deux mains (Spatial, ACTIVE) : prioritaire, court-circuite le
        # reste pour éviter d'activer des gestes incompatibles simultanément.
        if self.state == S_ACTIVE and self.mode == 'spatial' and len(cands) >= 2:
            self.tracking = True
            self.confidence = max(h.confidence for h in cands)
            self._dispatch_bimanual(cands, now)
            return []
        self._bimanual_ref = None

        # 4) Sélection de la main pilote (continuité).
        driver = self.select_driver(cands, now)
        if driver is None:
            self._handle_hand_lost(None, now)
            return []
        self._lost_frames = 0

        events, tel = self.recognizer.update(driver, now)
        self.last_pose = tel.pose
        self.confidence = tel.confidence
        self.tracking = True

        # 3) Armement : geste de pointage maintenu.
        if self.state == S_ARMED:
            self._maybe_arm(tel, now)
            return []

        if self.state == S_PAUSED:
            return []  # aucune action ; reprise via resume()/contrôle

        if self.state != S_ACTIVE:
            return []

        # 4) ACTIVE : conversion des gestes en actions, selon le mode.
        acted = []
        try:
            for ev in events:
                if self._dispatch(ev, tel, now):
                    acted.append(ev)
        except Exception as exc:  # une exception de sortie relâche les boutons
            self.error = str(exc)
            self._release_and(S_PAUSED)  # sûr : requiert un resume + ré-armement
        return acted

    def _maybe_arm(self, tel, now):
        if tel.pose == P_POINT:
            if self._arm_pose_since is None:
                self._arm_pose_since = now
            elif (now - self._arm_pose_since) * 1000 >= self.cfg['arming_hold_ms']:
                self.state = S_ACTIVE
                self.smoother.reset()
        else:
            self._arm_pose_since = None

    def _handle_hand_lost(self, sample, now):
        self._arm_pose_since = None
        self._lost_frames += 1
        self.tracking = False
        self.confidence = sample.confidence if sample else 0.0
        self.recognizer.update(None, now)
        # Relâcher immédiatement tout bouton maintenu (fin de glisser forcée).
        if self.output.held:
            try:
                self.output.release_all()
            except Exception:
                pass
        self.smoother.reset()

    # -- conversion geste -> action selon le mode --------------------------
    def _dispatch(self, ev, tel, now):
        # Pause immédiate à la paume ouverte (sauf en présentation : bascule).
        if ev.kind == G_OPEN_PALM:
            if self.mode == 'presentation':
                self.pointer_visible = not self.pointer_visible
                self._set_cursor_visible(self.pointer_visible)
                self._emit(now, tel, None, ev.kind, command='toggle_pointer')
                return True
            self.pause()
            self._emit(now, tel, None, ev.kind, command='pause')
            return True

        if self.mode == 'spatial':
            return self._dispatch_spatial(ev, tel, now)
        if self.mode == 'presentation':
            return self._dispatch_presentation(ev, tel, now)
        return self._dispatch_pointer(ev, tel, now)

    def _screen_xy(self, ev, now):
        # Retourne None sous la zone morte : le pointeur ne bouge pas (anti-
        # tremblement). Les clics utilisent smoother.last_pixel séparément.
        if ev.nx is None:
            return None
        return self.smoother.update(ev.nx, ev.ny, now)

    def _click_authorized(self):
        """Un clic système dans une application externe ne dit rien au suivi de
        main de sa conséquence (achat, suppression, envoi…). Une validation
        clavier (F8 maintenu) doit l'autoriser. Sans autorisation vérifiable, on
        s'abstient : le suivi positionne le pointeur, mais n'active pas seul un
        contrôle externe sensible. Ne pas retirer cette sécurité pour la fluidité."""
        if not self.require_click_auth:
            return True
        if self.desktop is None:
            return False
        try:
            return bool(self.desktop.authorized())
        except Exception:
            return False

    def _set_cursor_visible(self, visible):
        if self.desktop is not None:
            try:
                self.desktop.visible(visible)
            except Exception:
                pass

    def _dispatch_pointer(self, ev, tel, now):
        if ev.kind in (G_MOVE, G_DRAG_MOVE):
            pt = self._screen_xy(ev, now)
            if pt is None:
                return False
            self.output.move(*pt)
            if ev.kind == G_MOVE:
                self._emit(now, tel, pt, ev.kind)
            return True
        # Clics système : soumis à la validation clavier (application externe).
        if ev.kind in (G_LEFT_CLICK, G_RIGHT_CLICK, G_DOUBLE_CLICK, G_DRAG_START) and not self._click_authorized():
            self._emit(now, tel, self.smoother.last_pixel, ev.kind, command='click_needs_key')
            return True
        if ev.kind == G_LEFT_CLICK:
            self.output.click('left')
            self._emit(now, tel, self.smoother.last_pixel, ev.kind, command='left_click')
            return True
        if ev.kind == G_RIGHT_CLICK:
            self.output.click('right')
            self._emit(now, tel, self.smoother.last_pixel, ev.kind, command='right_click')
            return True
        if ev.kind == G_DOUBLE_CLICK:
            self.output.click('left', 2)
            self._emit(now, tel, self.smoother.last_pixel, ev.kind, command='double_click')
            return True
        if ev.kind == G_DRAG_START:
            self.output.button_down('left')
            self._emit(now, tel, self.smoother.last_pixel, ev.kind, command='drag_start')
            return True
        if ev.kind == G_DRAG_END:
            self.output.button_up('left')
            self._emit(now, tel, self.smoother.last_pixel, ev.kind, command='drag_end')
            return True
        if ev.kind == G_SCROLL:
            self.output.scroll(ev.direction, ev.amount or 1)
            self._emit(now, tel, self.smoother.last_pixel, ev.kind, command='scroll_' + ev.direction)
            return True
        if ev.kind == G_SWIPE_LEFT:
            self.output.desktop(-1)
            self._emit(now, tel, None, ev.kind, command='desktop_prev')
            return True
        if ev.kind == G_SWIPE_RIGHT:
            self.output.desktop(1)
            self._emit(now, tel, None, ev.kind, command='desktop_next')
            return True
        return False

    def _dispatch_presentation(self, ev, tel, now):
        if ev.kind == G_MOVE:
            if not self.pointer_visible:
                return False
            pt = self._screen_xy(ev, now)
            if pt is None:
                return False
            self.output.move(*pt)
            self._emit(now, tel, pt, ev.kind)
            return True
        if ev.kind == G_SWIPE_LEFT:
            self.output.slide('prev')
            self._emit(now, tel, None, ev.kind, command='slide_prev')
            return True
        if ev.kind == G_SWIPE_RIGHT:
            self.output.slide('next')
            self._emit(now, tel, None, ev.kind, command='slide_next')
            return True
        return False

    def _dispatch_bimanual(self, cands, now):
        """Zoom à deux mains : distance poignet-poignet, référence au début du
        geste, zoom relatif. Une bande morte évite le jitter ; la référence est
        avancée à chaque pas pour ne jamais accumuler à l'infini. La disparition
        d'une main termine le geste (self._bimanual_ref remis à None en amont)."""
        a, b = cands[0], cands[1]
        distance = _distance(a.landmarks[WRIST][:2], b.landmarks[WRIST][:2])
        if self._bimanual_ref is None:
            # Début du geste : on fixe la référence, aucun zoom involontaire.
            self._bimanual_ref = distance
            return
        deadband = self.cfg['bimanual_zoom_deadband']
        delta = distance - self._bimanual_ref
        if abs(delta) < deadband:
            return
        amount = min(10.0, abs(delta) * self.cfg['bimanual_zoom_gain'])
        direction = 'in' if delta > 0 else 'out'
        self._bimanual_ref = distance  # avancer la référence : pas d'accumulation
        mid_x = (a.landmarks[WRIST][0] + b.landmarks[WRIST][0]) / 2
        mid_y = (a.landmarks[WRIST][1] + b.landmarks[WRIST][1]) / 2
        tel = Telemetry(P_UNKNOWN, mid_x, mid_y, min(a.confidence, b.confidence), True, a.handedness)
        ev = Gesture(G_ZOOM, mid_x, mid_y, direction=direction, amount=amount)
        try:
            self._dispatch(ev, tel, now)
        except Exception as exc:
            self.error = str(exc)
            self._release_and(S_PAUSED)

    def _dispatch_spatial(self, ev, tel, now):
        # Spatial : aucune injection bureau. On émet des commandes JSON validées
        # (schéma hand_events) sur le canal local — sélectionner, tourner,
        # incliner, zoomer, éclater. Un pincement maintenu établit la référence ;
        # l'axe dominant du déplacement décide rotation (horizontal) ou
        # inclinaison (vertical).
        command = None
        amount = None
        if ev.kind == G_MOVE:
            command = 'point'
        elif ev.kind in (G_LEFT_CLICK, G_DRAG_START):
            command = 'select'
            self._spatial_drag_pos = (ev.nx, ev.ny)  # référence de la manipulation
        elif ev.kind == G_DRAG_MOVE:
            prev = getattr(self, '_spatial_drag_pos', None) or (ev.nx, ev.ny)
            dx, dy = ev.nx - prev[0], ev.ny - prev[1]
            self._spatial_drag_pos = (ev.nx, ev.ny)
            if abs(dx) < 1e-4 and abs(dy) < 1e-4:
                return False
            amount = math.hypot(dx, dy) * 10.0
            if abs(dx) >= abs(dy):
                command = 'rotate_right' if dx > 0 else 'rotate_left'
            else:
                command = 'tilt_down' if dy > 0 else 'tilt_up'
        elif ev.kind == G_DRAG_END:
            command = 'release'
            self._spatial_drag_pos = None
        elif ev.kind == G_ZOOM:
            command = 'zoom_' + (ev.direction or 'in')
            amount = ev.amount
        elif ev.kind == G_SPREAD:
            if (now - self._spread_cooldown_t) * 1000 < 1200:
                return False
            self._spread_cooldown_t = now
            command = 'explode'
        elif ev.kind == G_SWIPE_LEFT:
            command = 'rotate_left'
        elif ev.kind == G_SWIPE_RIGHT:
            command = 'rotate_right'
        else:
            return False
        pt = None
        if ev.nx is not None:
            pt = (int(ev.nx * (self.screen_size[0] - 1)), int(ev.ny * (self.screen_size[1] - 1)))
        self._emit(now, tel, pt, ev.kind, command=command, amount=amount)
        return True

    def _emit(self, now, tel, screen_xy, gesture, command=None, amount=None):
        event = hand_event(now, tel, screen_xy, gesture, self.mode, command, amount)
        self.last_event = event
        try:
            self.channel.emit(event)
        except Exception:
            pass

    # -- état sérialisable -------------------------------------------------
    def status(self):
        return {
            'version': VERSION,
            'state': self.state,
            'mode': self.mode,
            'backend': self.cfg['backend'],
            'camera': self.cfg['camera'],
            'tracking': self.tracking,
            'confidence': round(self.confidence, 4),
            'pose': self.last_pose,
            'pointer_visible': self.pointer_visible,
            'driver_hand': self._driver_hand,
            'preferred_hand': self.cfg['preferred_hand'],
            'click_auth_required': self.require_click_auth,
            'held_buttons': sorted(self.output.held),
            'error': self.error,
            'fps_capture': round(self._perf.fps_capture, 1),
            'fps_inference': round(self._perf.fps_inference, 1),
            'latency_ms': round(self._perf.latency_median, 1),
            'dropped_frames': self._perf.dropped,
            'last_event': self.last_event,
            'pid': os.getpid(),
            'updated': dt.datetime.now(dt.timezone.utc).isoformat(),
        }

    def set_mode(self, mode):
        if mode not in MODES:
            raise ValueError('Unknown mode: ' + str(mode))
        if mode != self.mode:
            try:
                self.output.release_all()
            except Exception:
                pass
            self.mode = mode
            self.recognizer = GestureRecognizer(self.cfg)
            self._arm_pose_since = None
            self._bimanual_ref = None
            self._spatial_drag_pos = None
            self.smoother.reset()

    def close(self):
        try:
            self.output.close()
        finally:
            try:
                self.channel.close()
            finally:
                if self.desktop is not None:
                    try:
                        self.desktop.close()
                    except Exception:
                        pass


# ===========================================================================
#  Mesure de performance (valeurs réelles uniquement)
# ===========================================================================
class PerfMonitor:
    """Fenêtres glissantes de temps de capture/inférence et de latence."""

    def __init__(self, window=120):
        self.capture_times = deque(maxlen=window)
        self.inference_times = deque(maxlen=window)
        self.latencies = deque(maxlen=window)
        self.dropped = 0
        self._cap_stamps = deque(maxlen=window)
        self._inf_stamps = deque(maxlen=window)

    def record(self, capture_s, inference_s, latency_s, now):
        self.capture_times.append(capture_s)
        self.inference_times.append(inference_s)
        self.latencies.append(latency_s)
        self._cap_stamps.append(now)
        self._inf_stamps.append(now)

    def drop(self):
        self.dropped += 1

    @staticmethod
    def _rate(stamps):
        if len(stamps) < 2:
            return 0.0
        span = stamps[-1] - stamps[0]
        return (len(stamps) - 1) / span if span > 0 else 0.0

    @property
    def fps_capture(self):
        return self._rate(self._cap_stamps)

    @property
    def fps_inference(self):
        return self._rate(self._inf_stamps)

    @property
    def latency_median(self):
        if not self.latencies:
            return 0.0
        return _percentile(list(self.latencies), 50) * 1000

    def report(self):
        lat = sorted(self.latencies)
        return {
            'fps_capture': round(self.fps_capture, 2),
            'fps_inference': round(self.fps_inference, 2),
            'latency_ms_median': round(_percentile(lat, 50) * 1000, 2) if lat else None,
            'latency_ms_p95': round(_percentile(lat, 95) * 1000, 2) if lat else None,
            'dropped_frames': self.dropped,
            'frames': len(self.latencies),
        }


def _percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return ordered[int(k)]
    return ordered[f] * (c - k) + ordered[c] * (k - f)


def read_cpu_percent(interval=0.2):
    """Utilisation CPU via /proc/stat (Linux). None si indisponible."""
    stat = Path('/proc/stat')
    if not stat.exists():
        return None
    def snap():
        parts = stat.read_text().splitlines()[0].split()[1:]
        vals = [int(v) for v in parts]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        return sum(vals), idle
    try:
        total0, idle0 = snap()
        time.sleep(interval)
        total1, idle1 = snap()
        dt_total = total1 - total0
        dt_idle = idle1 - idle0
        if dt_total <= 0:
            return None
        return round(100.0 * (1 - dt_idle / dt_total), 1)
    except (OSError, ValueError, IndexError):
        return None


def read_memory_mb():
    status = Path('/proc/self/status')
    if not status.exists():
        return None
    for line in status.read_text().splitlines():
        if line.startswith('VmRSS:'):
            try:
                return round(int(line.split()[1]) / 1024, 1)
            except (ValueError, IndexError):
                return None
    return None


def read_temperature_c():
    for zone in Path('/sys/class/thermal').glob('thermal_zone*'):
        try:
            return round(int((zone / 'temp').read_text().strip()) / 1000.0, 1)
        except (OSError, ValueError):
            continue
    try:
        out = subprocess.run(['vcgencmd', 'measure_temp'], capture_output=True, text=True, timeout=3)
        if out.returncode == 0 and '=' in out.stdout:
            return float(out.stdout.split('=')[1].split("'")[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


# ===========================================================================
#  Backends de détection (interface enfichable)
# ===========================================================================
class HandTrackerBackend:
    """Interface commune : coordonnées normalisées -> HandSample.

    Trois implémentations : MediaPipe (premier moteur), simulée (tests), et un
    emplacement documenté pour une future accélération Hailo."""

    name = 'base'

    def detect(self, frame, timestamp):
        raise NotImplementedError

    def close(self):
        pass


class SimulatedBackend(HandTrackerBackend):
    """Rejoue une séquence de HandSample fournie (ou traite un frame qui EST
    déjà une liste de HandSample). Aucune dépendance externe."""

    name = 'simulated'

    def __init__(self, sequence=None):
        self._sequence = list(sequence) if sequence else None
        self._i = 0

    def detect(self, frame, timestamp):
        if self._sequence is not None:
            if self._i >= len(self._sequence):
                return []
            item = self._sequence[self._i]
            self._i += 1
            return [] if item is None else [item]
        # Un frame simulé peut transporter directement des HandSample.
        if isinstance(frame, HandSample):
            return [frame]
        if isinstance(frame, list) and all(isinstance(x, HandSample) for x in frame):
            return frame
        return []


class MediaPipeBackend(HandTrackerBackend):
    """Tasks VIDEO mode. The model is local; there are no runtime downloads.

    Result confidence is handedness classification confidence, not an exposed
    palm-presence score. Presence/detection/tracking gates run inside Tasks.
    """
    name = 'mediapipe-tasks'

    def __init__(self, max_hands=1, min_confidence=.6, model_path=None):
        model = Path(model_path or DEFAULT_CONFIG['model_path']).expanduser()
        if not model.is_file():
            raise RuntimeError('Hand Landmarker model missing: ' + str(model) +
                               '. Run install/hand-deps.py; no model is downloaded at runtime.')
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions
            from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode
        except (ImportError, AttributeError) as exc:
            raise RuntimeError('MediaPipe Tasks unavailable. Run the pinned install/hand-deps.py setup.') from exc
        self._mp = mp
        self._last_ms = -1
        options = HandLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(model)),
            running_mode=RunningMode.VIDEO, num_hands=max_hands,
            min_hand_detection_confidence=min_confidence,
            min_hand_presence_confidence=min_confidence, min_tracking_confidence=min_confidence)
        self._hands = HandLandmarker.create_from_options(options)

    def detect(self, frame, timestamp):
        ms = max(self._last_ms + 1, int(timestamp * 1000))
        self._last_ms = ms
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=frame)
        try:
            result = self._hands.detect_for_video(image, ms)
        finally:
            image = None
        samples = []
        for landmarks, categories in zip(result.hand_landmarks, result.handedness):
            if not categories:
                continue
            category = categories[0]
            samples.append(HandSample([(p.x, p.y, p.z) for p in landmarks],
                                      category.category_name, category.score, timestamp))
        return samples

    def close(self):
        self._hands.close()


class HailoBackend(HandTrackerBackend):  # pragma: no cover - non implémenté
    """Emplacement documenté pour l'accélérateur Hailo (AI HAT+).

    NON PRIS EN CHARGE tant qu'un modèle de suivi des mains compatible Hailo
    n'est pas réellement intégré et testé sur le matériel. Ne prétends pas le
    supporter avant cette validation."""

    name = 'hailo'

    def __init__(self, *_, **__):
        raise NotImplementedError(
            'Hailo hand tracking is not implemented or validated yet. '
            'A compatible model must be integrated and tested on real hardware '
            'before this backend is enabled.')


def make_backend(config):
    if config['backend'] == 'simulated':
        return SimulatedBackend()
    return MediaPipeBackend(config['max_hands'], config['confidence_threshold'], config['model_path'])


# ===========================================================================
#  Sources caméra (Picamera2 prioritaire, V4L2/OpenCV en repli)
# ===========================================================================
class CameraSource:
    name = 'base'

    def start(self):
        raise NotImplementedError

    def read(self):
        """Retourne l'image la plus récente (format backend) ou None."""
        raise NotImplementedError

    def stop(self):
        pass


class SimulatedCamera(CameraSource):
    """Caméra simulée : émet une séquence d'objets opaques (HandSample ou None).
    Sert aux tests et au benchmark hors matériel : une image par itération."""

    name = 'simulated'

    def __init__(self, sequence=None, fps=30):
        self._sequence = list(sequence) if sequence else None
        self._i = 0
        self._fps = fps

    def start(self):
        return self

    def read(self):
        if self._sequence is None:
            return None
        if self._i >= len(self._sequence):
            return None
        item = self._sequence[self._i]
        self._i += 1
        return item

    def read_latest(self):
        # Pas d'abandon d'image : le simulateur livre chaque image.
        return self.read(), 0

    def stop(self):
        self._sequence = None


class LatestFrameBuffer:
    """File d'une seule image récente : une image non consommée est abandonnée
    (jamais accumulée). Compte les abandons pour la mesure de charge."""

    def __init__(self):
        self._lock = threading.Lock()
        self._frame = None
        self._has = False
        self._dropped = 0

    def put(self, frame):
        with self._lock:
            if self._has:
                self._dropped += 1
            self._frame = frame
            self._has = True

    def get(self):
        with self._lock:
            frame = self._frame if self._has else None
            dropped = self._dropped
            self._frame, self._has, self._dropped = None, False, 0
            return frame, dropped


class ThreadedCamera:
    """Enveloppe une source réelle dans un thread de capture qui ne conserve que
    l'image la plus récente. L'inférence en retard fait abandonner les anciennes
    images ; la mémoire ne croît jamais."""

    def __init__(self, source, fps=30):
        self.fps = fps
        self.captured = 0
        self.dropped = 0
        self.first_capture = None
        self.last_capture = None
        self.error = None
        self._source = source
        self.name = getattr(source, 'name', 'camera')
        self._buf = LatestFrameBuffer()
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        self._source.start()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                frame = self._source.read()
                if frame is None:
                    raise RuntimeError('Camera stream closed.')
                if self._stop.is_set():
                    break
                ended = time.monotonic()
                self.captured += 1
                self.first_capture = self.first_capture if self.first_capture is not None else ended
                self.last_capture = ended
                self._buf.put((frame, started, ended - started))
                frame = None
                self._stop.wait(max(0, 1 / self.fps - (time.monotonic() - started)))
        except Exception as exc:
            self.error = exc
        finally:
            frame = None

    def read_latest(self):
        if self.error:
            raise RuntimeError('Camera capture failed: ' + str(self.error)) from self.error
        packet, dropped = self._buf.get()
        self.dropped += dropped
        return packet, dropped

    def statistics(self):
        span = (self.last_capture or 0) - (self.first_capture or 0)
        return {'captured_frames': self.captured, 'fps_capture': (self.captured - 1) / span if span > 0 else 0,
                'dropped_frames': self.dropped}

    def set_fps(self, fps):
        self.fps = fps

    def stop(self):
        self._stop.set()
        try:
            self._source.stop()
        finally:
            if self._thread:
                self._thread.join(timeout=2)
            self._buf.get()  # Drop the last unconsumed image.


class Picamera2Source(CameraSource):  # pragma: no cover - nécessite le matériel
    name = 'picamera2'

    def __init__(self, width=640, height=480):
        try:
            from picamera2 import Picamera2
        except Exception as exc:
            raise RuntimeError('Picamera2/libcamera is not available.') from exc
        self._picam = Picamera2()
        self._config = self._picam.create_preview_configuration(
            main={'format': 'BGR888', 'size': (width, height)}, buffer_count=2, queue=False)
        self._picam.configure(self._config)

    def start(self):
        self._picam.start()
        return self

    def read(self):
        return self._picam.capture_array()

    def stop(self):
        try:
            self._picam.stop()
            self._picam.close()
        except Exception:
            pass


class V4L2Source(CameraSource):  # pragma: no cover - nécessite le matériel
    name = 'v4l2'

    def __init__(self, device='/dev/video0', width=640, height=480):
        try:
            import cv2
        except Exception as exc:
            raise RuntimeError('OpenCV (cv2) is not available for the V4L2 backend.') from exc
        self._cv2 = cv2
        index = device
        if isinstance(device, str) and device.startswith('/dev/video'):
            index = int(device.replace('/dev/video', '') or 0)
        self._cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    def start(self):
        if not self._cap.isOpened():
            raise RuntimeError('Could not open the V4L2 camera.')
        return self

    def read(self):
        ok, frame = self._cap.read()
        if not ok:
            return None
        return self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)

    def stop(self):
        try:
            self._cap.release()
        except Exception:
            pass


def make_camera(config):  # pragma: no cover - dépend du matériel
    choice = config['camera']
    w, h = config['analysis_width'], config['analysis_height']
    if choice == 'simulated':
        return SimulatedCamera(fps=config['target_fps'])
    if choice == 'picamera2':
        return Picamera2Source(w, h)
    if choice == 'v4l2':
        return V4L2Source(config['camera_device'], w, h)
    # auto : Picamera2 en priorité, puis V4L2.
    try:
        return Picamera2Source(w, h)
    except RuntimeError:
        return V4L2Source(config['camera_device'], w, h)


# ===========================================================================
#  État partagé, contrôle inter-processus et calibration
# ===========================================================================
def write_state(status, path=None):
    path = Path(STATE_FILE if path is None else path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.hand-state-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(status, stream, indent=2)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def read_state(path=None):
    path = Path(STATE_FILE if path is None else path)
    if not path.exists():
        return {'state': S_DISABLED, 'running': False,
                'note': 'Hand control is not running. Start it with ghost-hand start.'}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'state': 'unknown', 'running': False}
    # Le service est considéré « vivant » si l'état a été écrit récemment.
    fresh = (time.time() - path.stat().st_mtime) < 5
    if not isinstance(data, dict):
        return {'state': S_DISABLED, 'running': False}
    data['running'] = fresh and data.get('state') != S_DISABLED and data.get('running', True)
    return data


def write_control(command, path=None):
    """Écrit une requête de contrôle atomique lue par l'engine en fonctionnement."""
    path = Path(CONTROL_FILE if path is None else path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    command = {**command, 'ts': time.time()}
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.hand-ctl-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(command, stream)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def read_control(path=None):
    path = Path(CONTROL_FILE if path is None else path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def apply_control(engine, command):
    """Applique une requête de contrôle à un engine en marche."""
    if not isinstance(command, dict) or not command:
        return
    if command == getattr(engine, '_last_control', None):
        return
    engine._last_control = dict(command)
    desired = command.get('desired')
    if desired == 'paused':
        engine.pause()
    elif desired == 'active':
        engine.request_active()
    elif desired == 'disabled':
        engine.disable()
    mode = command.get('mode')
    if mode in MODES:
        engine.set_mode(mode)


# ===========================================================================
#  Fonctions CLI
# ===========================================================================
def _query_screen_size(default=(800, 480)):
    if not shutil.which('xdotool'):
        return default
    try:
        out = subprocess.run(['xdotool', 'getdisplaygeometry'], capture_output=True,
                             text=True, timeout=5,
                             env={**os.environ, 'DISPLAY': os.environ.get('DISPLAY', ':0')})
        w, h = out.stdout.split()
        return int(w), int(h)
    except (OSError, ValueError, subprocess.SubprocessError):
        return default


def cmd_status(as_json):
    state = read_state()
    if as_json:
        print(json.dumps(state, indent=2))
        return 0
    running = state.get('running')
    print('GHOSTBOARD Hand Control')
    print('  service   : ' + ('running' if running else 'stopped'))
    print('  state     : ' + str(state.get('state', 'unknown')))
    print('  mode      : ' + str(state.get('mode', load_config()['mode'])))
    if running:
        print('  camera    : ' + str(state.get('camera')))
        print('  backend   : ' + str(state.get('backend')))
        print('  tracking  : ' + str(state.get('tracking')))
        print('  confidence: ' + str(state.get('confidence')))
        print('  fps (cap) : ' + str(state.get('fps_capture')))
        print('  fps (inf) : ' + str(state.get('fps_inference')))
        print('  latency ms: ' + str(state.get('latency_ms')))
        print('  dropped   : ' + str(state.get('dropped_frames')))
        held = state.get('held_buttons') or []
        print('  buttons   : ' + (', '.join(held) if held else 'none held'))
    if STOP_FILE.exists():
        print('  NOTE: shared STOP is active. Run ghost-system resume, then re-activate.')
    return 0


def cmd_pause():
    write_control({'desired': 'paused'})
    print('Pause requested.')
    return 0


def cmd_resume():
    if STOP_FILE.exists():
        print('Shared STOP is active. Run ghost-system resume first.', file=sys.stderr)
        return 1
    write_control({'desired': 'active'})
    print('Resume requested. Hold the pointing gesture to re-arm.')
    return 0


def cmd_stop():
    write_control({'desired': 'disabled'})
    # Arrêt du service utilisateur s'il tourne ; sans échec bloquant.
    if shutil.which('systemctl'):
        subprocess.run(['systemctl', '--user', 'stop', 'ghostboard-hand.service'],
                       capture_output=True)
    print('Hand control stopped.')
    return 0


def cmd_mode(mode):
    config = load_config()
    config['mode'] = mode
    save_config(config)
    write_control({'mode': mode})
    print('Mode set to ' + mode + '.')
    return 0


def cmd_doctor(as_json):
    config = None
    checks = []

    def check(name, ok, hint=''):
        checks.append({'check': name, 'ok': bool(ok), 'hint': '' if ok else hint})

    try:
        config = load_config()
        check('Configuration valid', True)
    except (OSError, ValueError) as exc:
        check('Configuration valid', False, str(exc))

    def has_module(mod):
        import importlib.util
        return importlib.util.find_spec(mod) is not None

    check('MediaPipe available', has_module('mediapipe'),
          'Install a MediaPipe build for ARM64, or use the simulated backend.')
    check('Picamera2 available', has_module('picamera2'),
          'Camera Module 3 uses Picamera2/libcamera. USB cameras can use V4L2/OpenCV.')
    check('OpenCV available (V4L2 fallback)', has_module('cv2'),
          'Install python3-opencv for USB (V4L2) cameras.')
    check('xdotool available', shutil.which('xdotool') is not None,
          'xdotool injects pointer actions on X11.')
    cameras = sorted(str(p) for p in Path('/dev').glob('video*')) if Path('/dev').exists() else []
    check('Camera device present', bool(cameras),
          'No /dev/video* found. Hand control installs without a camera; connect one to use it.')
    check('Shared STOP inactive', not STOP_FILE.exists(),
          'Run ghost-system resume to clear the shared stop flag.')
    check('Not disabled by default note', True)

    if as_json:
        print(json.dumps({'checks': checks, 'cameras': cameras,
                          'backend_selected': config['backend'] if config else None}, indent=2))
    else:
        for c in checks:
            print(('OK    ' if c['ok'] else 'CHECK ') + c['check'] + (' — ' + c['hint'] if c['hint'] else ''))
        if cameras:
            print('Cameras: ' + ', '.join(cameras))
    # Doctor est informatif : l'absence de caméra ou de MediaPipe n'est pas un
    # échec (repli simulé documenté). Seule une configuration invalide l'est.
    config_ok = next((c['ok'] for c in checks if c['check'] == 'Configuration valid'), True)
    return 0 if config_ok else 1


def run_engine(config=None, camera=None, backend=None, duration=None, on_status=None,
               output=None, observe_only=False):
    """Boucle principale : capture -> détection -> gestes -> actions.

    File d'une seule image récente : si l'inférence prend du retard, les images
    plus anciennes sont abandonnées et comptées (jamais accumulées en mémoire).
    """
    config = config or load_config()
    validate_config(config)
    screen = _query_screen_size()
    if output is None:
        output = RecordingActionSink(maxlen=1) if observe_only else XdotoolActionSink()
    # Canal Spatial : le pont local authentifié de Codex (hand_events). Il ignore
    # les événements non-spatial et reste muet si aucun pont n'écoute.
    desktop = None
    if observe_only:
        channel = RecordingEventChannel(maxlen=1)
    else:
        try:
            import hand_events
            channel = hand_events.Channel()
        except Exception:
            channel = RecordingEventChannel(maxlen=1)
        # Autorisation clavier des clics externes (F8) + masquage réel du curseur.
        try:
            import hand_desktop
            desktop = hand_desktop.Desktop(os.environ.get('DISPLAY'))
        except Exception:
            desktop = None

    backend = backend if backend is not None else make_backend(config)
    try:
        camera = camera if camera is not None else make_camera(config)
    except Exception:
        backend.close()
        output.close()
        channel.close()
        if desktop is not None:
            desktop.close()
        raise
    # File d'une seule image récente : les sources réelles passent par un thread
    # de capture qui abandonne les anciennes images. Le simulateur livre tout.
    if not hasattr(camera, 'read_latest'):
        camera = ThreadedCamera(camera, config['target_fps'])
    engine = HandControlEngine(config, output=output, channel=channel, screen_size=screen, desktop=desktop)
    perf = engine._perf

    started = time.monotonic()
    last_state_write = 0.0
    try:
        camera.start()
        while True:
            loop_start = time.monotonic()
            # Recalculé à chaque tour : la réduction adaptative de cadence agit.
            interval = 1.0 / config['target_fps']
            if duration is not None and (loop_start - started) >= duration:
                break
            # Contrôle inter-processus.
            if not observe_only:
                apply_control(engine, read_control())
            if engine.stop_file.exists():
                engine._release_and(S_STOPPED)
                break
            if engine.state == S_DISABLED:
                break  # ghost-hand stop : sortie propre (boutons relâchés dans finally)
            # Capture : image la plus récente + nombre d'images abandonnées.
            t_cap = time.monotonic()
            frame, dropped = camera.read_latest()
            for _ in range(dropped):
                perf.drop()
            capture_s = time.monotonic() - t_cap
            if frame is None:
                if isinstance(camera, SimulatedCamera):
                    break  # séquence simulée épuisée
                # Pas de nouvelle image : relâcher tout bouton maintenu si la
                # caméra semble s'être arrêtée, puis attendre.
                if engine.output.held:
                    engine.process_sample(None, time.monotonic())
                time.sleep(interval)
                continue
            t_inf = time.monotonic()
            try:
                samples = backend.detect(frame, t_inf)
            finally:
                frame = None
            inference_s = time.monotonic() - t_inf
            now = time.monotonic()
            # On transmet TOUTES les mains : la persistance de la main pilote et
            # le zoom à deux mains sont décidés dans l'engine.
            if not observe_only:
                engine.process_sample(samples, now)
            perf.record(capture_s, inference_s, now - loop_start, now)
            # État partagé (throttle) + réduction automatique si surcharge.
            if not observe_only and now - last_state_write > 0.5:
                status = engine.status()
                write_state(status)
                if on_status:
                    on_status(status)
                last_state_write = now
            _adaptive_pace(perf, config)
            if isinstance(camera, ThreadedCamera):
                camera.fps = config['target_fps']
            elapsed = time.monotonic() - loop_start
            if elapsed < interval:
                time.sleep(interval - elapsed)
    finally:
        with ExitStack() as cleanup:
            cleanup.callback(backend.close)
            cleanup.callback(camera.stop)
            cleanup.callback(engine.close)
            frame = None
        if not observe_only:
            write_state({**engine.status(), 'state': S_STOPPED if engine.state == S_STOPPED else S_DISABLED, 'running': False})
    return perf


def _adaptive_pace(perf, config):
    """Réduit la cadence cible si la latence médiane dépasse le budget image.

    Ne touche jamais à la mémoire : la file reste d'une seule image."""
    if len(perf.latencies) < 20:
        return
    budget = 1.0 / config['target_fps']
    if perf.latency_median / 1000 > budget * 1.5 and config['target_fps'] > 10:
        config['target_fps'] = max(10, int(config['target_fps'] * 0.8))


def cmd_benchmark(seconds):
    """Mesure réelle du pipeline configuré. Aucun résultat fabriqué : si aucune
    caméra/aucun MediaPipe n'est disponible, mesure le pipeline simulé et
    l'indique clairement dans le rapport."""
    config = load_config()
    screen = _query_screen_size()
    # Backend réel si disponible, sinon simulé (étiqueté comme tel). make_backend
    # ne bascule PAS seul sur le simulé (durcissement) : on rattrape ici pour que
    # le benchmark reste exécutable, en indiquant clairement le pipeline simulé.
    try:
        backend = make_backend(config)
    except RuntimeError:
        backend = SimulatedBackend()
    real_camera = False
    try:
        camera = make_camera(config)
        real_camera = config['camera'] != 'simulated'
    except Exception:
        camera = None
    if camera is None or isinstance(backend, SimulatedBackend):
        # Pipeline simulé : séquence synthétique pour mesurer les temps réels.
        seq = _demo_sequence(int(seconds * config['target_fps']))
        camera = SimulatedCamera(seq, fps=config['target_fps'])
        backend = SimulatedBackend()
        real_camera = False

    engine_perf = run_engine(config=config, camera=camera, backend=backend, duration=seconds, observe_only=True)
    report = engine_perf.report()
    report.update({
        'seconds_requested': seconds,
        'backend': backend.name,
        'camera': getattr(camera, 'name', 'unknown'),
        'real_camera': real_camera,
        'cpu_percent': read_cpu_percent(),
        'memory_mb': read_memory_mb(),
        'temperature_c': read_temperature_c(),
        'note': ('Real camera/backend measured.' if real_camera and backend.name != 'simulated'
                 else 'Simulated pipeline: timings are real measurements of the simulated path, '
                      'not real-camera throughput. Run on a Pi 5 with a camera and MediaPipe for hardware figures.'),
    })
    print(json.dumps(report, indent=2))
    return 0


def _demo_sequence(count):
    """Génère une séquence synthétique de HandSample (pointage qui se déplace)."""
    seq = []
    for i in range(max(1, count)):
        t = i / 30.0
        x = 0.4 + 0.2 * math.sin(i / 10.0)
        seq.append(pointing_hand(x, 0.5, timestamp=t))
    return seq


# ---------------------------------------------------------------------------
#  Générateurs de main synthétiques (partagés avec les tests et la démo)
# ---------------------------------------------------------------------------
def _base_hand():
    """Squelette neutre : poignet en bas, tous les doigts repliés vers la paume.

    Un doigt replié a son bout ramené vers le MCP (plus proche du poignet que la
    phalange PIP) : c'est ce qui le distingue d'un doigt tendu."""
    return {
        WRIST: (0.5, 0.95, 0.0),
        # Pouce ramené le long de la paume (bout proche du poignet).
        THUMB_CMC: (0.45, 0.88, 0.0), THUMB_MCP: (0.44, 0.82, 0.0),
        THUMB_IP: (0.45, 0.79, 0.0), THUMB_TIP: (0.48, 0.80, 0.0),
        INDEX_MCP: (0.50, 0.70, 0.0), INDEX_PIP: (0.50, 0.65, 0.0),
        INDEX_DIP: (0.50, 0.68, 0.0), INDEX_TIP: (0.50, 0.72, 0.0),
        MIDDLE_MCP: (0.54, 0.70, 0.0), MIDDLE_PIP: (0.54, 0.65, 0.0),
        MIDDLE_DIP: (0.54, 0.68, 0.0), MIDDLE_TIP: (0.54, 0.72, 0.0),
        RING_MCP: (0.58, 0.70, 0.0), RING_PIP: (0.58, 0.65, 0.0),
        RING_DIP: (0.58, 0.68, 0.0), RING_TIP: (0.58, 0.72, 0.0),
        PINKY_MCP: (0.62, 0.70, 0.0), PINKY_PIP: (0.62, 0.65, 0.0),
        PINKY_DIP: (0.62, 0.68, 0.0), PINKY_TIP: (0.62, 0.72, 0.0),
    }


def _to_list(mapping):
    return [mapping[i] for i in range(LANDMARK_COUNT)]


def _extend(mapping, mcp, pip, dip, tip, dx, length=0.35):
    """Étend un doigt vers le haut à partir de son MCP (repère 'main levée')."""
    bx, by, _ = mapping[mcp]
    mapping[pip] = (bx + dx * 0.1, by - length * 0.4, 0.0)
    mapping[dip] = (bx + dx * 0.15, by - length * 0.7, 0.0)
    mapping[tip] = (bx + dx * 0.2, by - length, 0.0)


def _translate(mapping, ref, x, y):
    """Translate toute la main pour amener le point `ref` sur (x, y).

    Déplace aussi le poignet : indispensable pour que le balayage (basé sur le
    poignet) et le pointage (basé sur l'index) restent cohérents."""
    rx, ry, _ = mapping[ref]
    dx, dy = x - rx, y - ry
    for i in range(LANDMARK_COUNT):
        px, py, pz = mapping[i]
        mapping[i] = (px + dx, py + dy, pz)
    return mapping


def pointing_hand(x=0.5, y=0.5, handedness='Right', confidence=0.95, timestamp=0.0):
    """Index tendu, autres doigts repliés — pose de pointage/armement.

    (x, y) est la position du bout de l'index ; toute la main est translatée."""
    m = _base_hand()
    _extend(m, INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP, 0.0, 0.4)
    _translate(m, INDEX_TIP, x, y)
    return HandSample(_to_list(m), handedness, confidence, timestamp)


def open_palm_hand(x=0.5, y=0.5, handedness='Right', confidence=0.95, timestamp=0.0, spread=False):
    m = _base_hand()
    _extend(m, INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP, -0.3 if spread else -0.1, 0.4)
    _extend(m, MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP, 0.0, 0.42)
    _extend(m, RING_MCP, RING_PIP, RING_DIP, RING_TIP, 0.1, 0.4)
    _extend(m, PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP, 0.3 if spread else 0.15, 0.35)
    # Pouce écarté sur le côté.
    m[THUMB_IP] = (0.34, 0.72, 0.0)
    m[THUMB_TIP] = (0.28, 0.66, 0.0)
    if spread:
        # Écarter davantage index et auriculaire pour la vue éclatée.
        ix, iy, _ = m[INDEX_TIP]
        px, py, _ = m[PINKY_TIP]
        m[INDEX_TIP] = (ix - 0.12, iy, 0.0)
        m[PINKY_TIP] = (px + 0.12, py, 0.0)
    _translate(m, INDEX_TIP, x, y)
    return HandSample(_to_list(m), handedness, confidence, timestamp)


def pinch_hand(x=0.5, y=0.5, tip=INDEX_TIP, handedness='Right', confidence=0.95, timestamp=0.0):
    """Pouce et un doigt joints (pincement). tip=INDEX_TIP ou MIDDLE_TIP.

    (x, y) est le point de contact du pincement."""
    m = _base_hand()
    if tip == INDEX_TIP:
        m[INDEX_TIP] = (x, y, 0.0)
        m[INDEX_DIP] = (x, y + 0.04, 0.0)
        m[INDEX_PIP] = (x, y + 0.08, 0.0)
        m[THUMB_TIP] = (x + 0.005, y + 0.005, 0.0)
        m[THUMB_IP] = (x + 0.03, y + 0.05, 0.0)
    else:
        # Pincement pouce-majeur : index NON tendu.
        m[MIDDLE_TIP] = (x, y, 0.0)
        m[MIDDLE_DIP] = (x, y + 0.04, 0.0)
        m[MIDDLE_PIP] = (x, y + 0.08, 0.0)
        m[THUMB_TIP] = (x + 0.005, y + 0.005, 0.0)
        m[THUMB_IP] = (x + 0.03, y + 0.05, 0.0)
        m[INDEX_TIP] = (0.50, 0.72, 0.0)  # replié
    _translate(m, THUMB_TIP, x, y)
    return HandSample(_to_list(m), handedness, confidence, timestamp)


def two_finger_hand(x=0.5, y=0.5, handedness='Right', confidence=0.95, timestamp=0.0):
    """Index et majeur tendus (défilement). (x, y) suit le bout de l'index."""
    m = _base_hand()
    _extend(m, INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP, -0.05, 0.4)
    _extend(m, MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP, 0.05, 0.42)
    _translate(m, INDEX_TIP, x, y)
    return HandSample(_to_list(m), handedness, confidence, timestamp)


def calibrate(interactive=True):
    """Calibration guidée des quatre coins de la zone utile.

    Sur le Pi, l'interface graphique 800x480 (Tk) guide l'utilisateur. Ici, un
    mode non interactif écrit une calibration par défaut activée, utile pour les
    tests et l'automatisation."""
    config = load_config()
    if not interactive:
        config['calibration']['enabled'] = True
        save_config(config)
        print('Calibration written (non-interactive defaults).')
        return 0
    try:
        return _calibrate_gui(config)
    except Exception as exc:  # repli terminal si Tk indisponible
        print('Graphical calibration unavailable (' + str(exc) + '). Using guided terminal mode.')
        return _calibrate_terminal(config)


def measure_calibration_point(config):
    """Capture actual landmarks only; never inject input or retain an image."""
    if STOP_FILE.exists():
        raise RuntimeError('Shared STOP is active.')
    with ExitStack() as cleanup:
        backend = make_backend(config)
        cleanup.callback(backend.close)
        if isinstance(backend, SimulatedBackend):
            raise RuntimeError('Calibration requires a real tracking backend.')
        camera = make_camera(config)
        cleanup.callback(camera.stop)
        camera.start()
        points = []
        for _ in range(12):
            if STOP_FILE.exists():
                raise RuntimeError('Shared STOP is active.')
            frame = camera.read()
            try:
                if frame is None:
                    raise RuntimeError('Camera stream closed.')
                samples = backend.detect(frame, time.monotonic())
            finally:
                frame = None
            if samples and samples[0].confidence >= config['confidence_threshold']:
                points.append(samples[0].index_tip[:2])
            time.sleep(1 / config['target_fps'])
        if len(points) < 6:
            raise RuntimeError('Keep the index visible and steady; insufficient valid samples.')
        result = [_percentile([p[i] for p in points], 50) for i in (0, 1)]
        if any(not 0 <= v <= 1 for v in result):
            raise ValueError('Index is outside the camera image.')
        if max(math.dist(p, result) for p in points) > 0.06:
            raise ValueError('Hand moved too much; retry the corner.')
        return result


def _calibrate_terminal(config):
    print('Reach each corner of the usable camera area and press Enter.')
    corners = ['top_left', 'top_right', 'bottom_right', 'bottom_left']
    result = {}
    for corner in corners:
        input('  Move your index to the ' + corner.replace('_', ' ') + ' corner, then press Enter...')
        # Sans caméra en direct on garde la valeur par défaut du coin.
        result[corner] = measure_calibration_point(config)
    config['calibration'].update(result)
    config['calibration']['enabled'] = True
    save_config(config)
    print('Calibration saved.')
    return 0


def _calibrate_gui(config):  # pragma: no cover - nécessite Tk et une caméra
    import tkinter as tk
    captured = {}
    corners = [('top_left', 0.1, 0.1), ('top_right', 0.9, 0.1),
               ('bottom_right', 0.9, 0.9), ('bottom_left', 0.1, 0.9)]
    root = tk.Tk()
    root.title('GHOSTBOARD Hand Control — Calibration')
    root.geometry('800x480')
    label = tk.Label(root, font=('sans-serif', 18), wraplength=700)
    label.pack(expand=True)
    state = {'i': 0}

    def show():
        if state['i'] >= len(corners):
            for name, _, _ in corners:
                config['calibration'][name] = captured.get(name, config['calibration'][name])
            config['calibration']['enabled'] = True
            save_config(config)
            root.destroy()
            return
        name = corners[state['i']][0]
        label.config(text=f'Point at the {name.replace("_", " ")} corner of your usable area,\nthen press Space. ({state["i"]+1}/4)')

    def capture(_):
        name = corners[state['i']][0]
        # Sur matériel réel : lire une image et détecter le bout de l'index.
        try:
            captured[name] = measure_calibration_point(config)
        except (RuntimeError, ValueError, OSError) as exc:
            label.config(text=str(exc) + '\nPress Space to retry or Escape to cancel.')
            return
        state['i'] += 1
        show()

    root.bind('<space>', capture)
    root.bind('<Escape>', lambda _: root.destroy())
    show()
    root.mainloop()
    if len(captured) != 4:
        print('Calibration cancelled; configuration unchanged.')
        return 1
    print('Calibration saved.')
    return 0


def cmd_start(foreground):
    if STOP_FILE.exists():
        print('Shared STOP is active. Run ghost-system resume first.', file=sys.stderr)
        return 1
    # Nettoyer une éventuelle requête de contrôle obsolète.
    Path(CONTROL_FILE).unlink(missing_ok=True)
    if foreground or not shutil.which('systemctl'):
        print('Starting hand control (foreground). Hold the pointing gesture to arm. Ctrl+C to stop.')
        try:
            run_engine()
        except KeyboardInterrupt:
            print('\nStopped.')
        return 0
    result = subprocess.run(['systemctl', '--user', 'start', 'ghostboard-hand.service'],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print('Could not start the user service. Run "ghost-hand start --foreground" instead.',
              file=sys.stderr)
        print(result.stderr.strip(), file=sys.stderr)
        return 1
    print('Hand control service started. Hold the pointing gesture to arm.')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='ghost-hand', description='GHOSTBOARD Hand Control')
    sub = ap.add_subparsers(dest='command', required=True)
    p_start = sub.add_parser('start', help='Start hand control (armed; hold pointing to activate).')
    p_start.add_argument('--foreground', action='store_true', help='Run the engine in this terminal.')
    sub.add_parser('run', help='Run the engine loop directly (used by the systemd service).')
    sub.add_parser('pause', help='Pause immediately.')
    sub.add_parser('resume', help='Resume (re-arming required).')
    sub.add_parser('stop', help='Stop hand control and release any held buttons.')
    p_status = sub.add_parser('status', help='Show current status.')
    p_status.add_argument('--json', action='store_true')
    p_mode = sub.add_parser('mode', help='Set the active profile.')
    p_mode.add_argument('mode', choices=MODES)
    p_cal = sub.add_parser('calibrate', help='Calibrate the usable camera area.')
    p_cal.add_argument('--non-interactive', action='store_true')
    p_doc = sub.add_parser('doctor', help='Diagnose dependencies and camera.')
    p_doc.add_argument('--json', action='store_true')
    p_bench = sub.add_parser('benchmark', help='Measure real pipeline performance.')
    p_bench.add_argument('--seconds', type=float, default=30)
    args = ap.parse_args(argv)
    try:
        if args.command == 'start':
            return cmd_start(args.foreground)
        if args.command == 'run':
            run_engine()
            return 0
        if args.command == 'pause':
            return cmd_pause()
        if args.command == 'resume':
            return cmd_resume()
        if args.command == 'stop':
            return cmd_stop()
        if args.command == 'status':
            return cmd_status(args.json)
        if args.command == 'mode':
            return cmd_mode(args.mode)
        if args.command == 'calibrate':
            return calibrate(interactive=not args.non_interactive)
        if args.command == 'doctor':
            return cmd_doctor(args.json)
        if args.command == 'benchmark':
            if not 1 <= args.seconds <= 600:
                raise ValueError('--seconds must be between 1 and 600.')
            return cmd_benchmark(args.seconds)
    except (ValueError, RuntimeError, OSError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
