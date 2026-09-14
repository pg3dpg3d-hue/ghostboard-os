#!/usr/bin/env python3
"""Tests du module de suivi des mains — sans caméra, sans Pi, sans serveur X.

Séquences synthétiques de 21 points ; adaptateur de sortie simulé (aucun test
ne déplace le pointeur) ; canal d'événements simulé. Chaque scénario du cahier
des charges a son test."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
import hand_tracking as h


class FakeDesktop:
    """Autorisation clavier + visibilité curseur simulées (pas d'X11)."""

    def __init__(self, authorized=True):
        self._authorized = authorized
        self.visible_calls = []

    def authorized(self):
        return self._authorized

    def visible(self, visible):
        self.visible_calls.append(visible)


def engine(mode='pointer', state=h.S_ACTIVE, stop='no_such_stop', fail_on=None,
           config=None, authorized=True, desktop=None):
    cfg = config or h.load_config('does-not-exist.json')
    cfg['mode'] = mode
    out = h.RecordingActionSink(fail_on=fail_on)
    ch = h.RecordingEventChannel()
    if desktop is None:
        desktop = FakeDesktop(authorized)
    return h.HandControlEngine(cfg, output=out, channel=ch, screen_size=(800, 480),
                              stop_file=stop, initial_state=state, desktop=desktop)


def feed(eng, samples, t0=0.0, dt=0.05):
    t = t0
    for s in samples:
        if s is not None:
            s.timestamp = t
        eng.process_sample(s, t)
        t += dt
    return t


def names(eng):
    return [a['action'] for a in eng.output.actions]


class ConfigTests(unittest.TestCase):
    def test_defaults_are_valid(self):
        h.validate_config(json.loads(json.dumps(h.DEFAULT_CONFIG)))

    def test_invalid_config_is_rejected(self):
        for bad in [
            {'confidence_threshold': 5.0}, {'mode': 'bogus'}, {'backend': 'hailo'},
            {'target_fps': 0}, {'pinch_on': 0.2, 'pinch_off': 0.1}, {'analysis_width': 10},
            {'flip_horizontal': 'yes'}, {'spatial_channel_port': -1}, {'unknown_key': 1},
        ]:
            cfg = json.loads(json.dumps(h.DEFAULT_CONFIG))
            cfg.update(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                h.validate_config(cfg)

    def test_invalid_calibration_rejected(self):
        cfg = json.loads(json.dumps(h.DEFAULT_CONFIG))
        cfg['calibration']['top_left'] = [2.0, 0.0]
        with self.assertRaises(ValueError):
            h.validate_config(cfg)

    def test_save_and_load_roundtrip_atomic(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'hand-tracking.json'
            cfg = h.load_config(path)
            cfg['mode'] = 'spatial'
            cfg['flip_horizontal'] = False
            h.save_config(cfg, path)
            again = h.load_config(path)
            self.assertEqual(again['mode'], 'spatial')
            self.assertFalse(again['flip_horizontal'])
            # Écriture atomique : aucun fichier temporaire résiduel.
            self.assertEqual([p.name for p in Path(folder).iterdir()], ['hand-tracking.json'])

    def test_unknown_key_in_file_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'hand-tracking.json'
            path.write_text('{"nonsense": 1}')
            with self.assertRaises(ValueError):
                h.load_config(path)


class CalibrationTests(unittest.TestCase):
    def _calib(self, corners, flip=False):
        c = {'enabled': True, 'top_left': corners[0], 'top_right': corners[1],
             'bottom_right': corners[2], 'bottom_left': corners[3]}
        return h.Calibration(c, flip)

    def test_perspective_quad_maps_corners_to_screen_extremes(self):
        # Quadrilatère non rectangulaire (perspective) : coins -> carré unité.
        corners = [(0.20, 0.18), (0.82, 0.24), (0.88, 0.83), (0.14, 0.79)]
        cal = self._calib(corners)
        expected = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        for (cx, cy), (ex, ey) in zip(corners, expected):
            mx, my = cal.map(cx, cy)
            self.assertAlmostEqual(mx, ex, places=3)
            self.assertAlmostEqual(my, ey, places=3)

    def test_center_of_quad_maps_near_center(self):
        corners = [(0.20, 0.18), (0.82, 0.24), (0.88, 0.83), (0.14, 0.79)]
        cal = self._calib(corners)
        cx = sum(c[0] for c in corners) / 4
        cy = sum(c[1] for c in corners) / 4
        mx, my = cal.map(cx, cy)
        # Le centre du quadrilatère tombe près du centre de l'écran.
        self.assertLess(abs(mx - 0.5), 0.12)
        self.assertLess(abs(my - 0.5), 0.12)

    def test_edge_midpoints_are_monotonic(self):
        corners = [(0.20, 0.18), (0.82, 0.24), (0.88, 0.83), (0.14, 0.79)]
        cal = self._calib(corners)
        top_mid = cal.map((0.20 + 0.82) / 2, (0.18 + 0.24) / 2)
        bottom_mid = cal.map((0.14 + 0.88) / 2, (0.79 + 0.83) / 2)
        self.assertLess(top_mid[1], 0.5)     # bord haut -> moitié supérieure
        self.assertGreater(bottom_mid[1], 0.5)  # bord bas -> moitié inférieure

    def test_flip_mirrors_horizontally(self):
        corners = [(0.20, 0.18), (0.82, 0.24), (0.88, 0.83), (0.14, 0.79)]
        cal = self._calib(corners, flip=True)
        # TL calibré -> après miroir, bord droit de l'écran.
        mx, _ = cal.map(*corners[0])
        self.assertAlmostEqual(mx, 1.0, places=3)

    def test_degenerate_corners_fall_back_to_bounding_box(self):
        # Coins colinéaires : homographie impossible -> repli rectangle.
        cal = self._calib([(0.1, 0.1), (0.2, 0.2), (0.3, 0.3), (0.4, 0.4)])
        self.assertIsNone(cal.homography)
        mx, my = cal.map(0.25, 0.25)  # ne lève pas, reste borné
        self.assertTrue(0.0 <= mx <= 1.0 and 0.0 <= my <= 1.0)

    def test_disabled_calibration_is_identity(self):
        c = dict(h.DEFAULT_CONFIG['calibration'])
        c['enabled'] = False
        cal = h.Calibration(c, flip_horizontal=False)
        self.assertEqual(cal.map(0.37, 0.62), (0.37, 0.62))


class PoseTests(unittest.TestCase):
    def test_synthetic_poses_classify(self):
        r = h.GestureRecognizer(h.load_config('none'))
        self.assertEqual(r.classify(h.pointing_hand(0.5, 0.5))[0], h.P_POINT)
        self.assertEqual(r.classify(h.open_palm_hand(0.5, 0.5))[0], h.P_OPEN_PALM)
        self.assertEqual(r.classify(h.open_palm_hand(0.5, 0.5, spread=True))[0], h.P_SPREAD)
        self.assertEqual(r.classify(h.two_finger_hand(0.5, 0.5))[0], h.P_TWO_FINGER)
        self.assertEqual(r.classify(h.pinch_hand(0.5, 0.5))[0], h.P_PINCH)
        self.assertEqual(r.classify(h.pinch_hand(0.5, 0.5, tip=h.MIDDLE_TIP))[0], h.P_PINCH_MIDDLE)

    def test_sample_requires_21_points(self):
        with self.assertRaises(ValueError):
            h.HandSample([(0, 0, 0)] * 20)


class SafetyStateTests(unittest.TestCase):
    def test_no_action_below_confidence_threshold(self):
        eng = engine()
        feed(eng, [h.pinch_hand(0.5, 0.5, confidence=0.2) for _ in range(8)])
        self.assertEqual(eng.output.actions, [])
        self.assertFalse(eng.tracking)

    def test_activation_requires_held_arming_gesture(self):
        eng = engine(state=h.S_ARMED)
        # Un seul frame de pointage ne suffit pas à armer.
        feed(eng, [h.pointing_hand(0.5, 0.5)])
        self.assertEqual(eng.state, h.S_ARMED)
        # Maintenir le pointage au-delà de arming_hold_ms -> ACTIVE.
        feed(eng, [h.pointing_hand(0.5, 0.5) for _ in range(40)], t0=0.05)
        self.assertEqual(eng.state, h.S_ACTIVE)

    def test_armed_state_injects_nothing(self):
        eng = engine(state=h.S_ARMED)
        feed(eng, [h.pinch_hand(0.5, 0.5) for _ in range(5)])
        self.assertEqual(eng.output.actions, [])

    def test_open_palm_pauses(self):
        eng = engine()
        feed(eng, [h.open_palm_hand(0.5, 0.5) for _ in range(6)])
        self.assertEqual(eng.state, h.S_PAUSED)
        # En pause, plus aucune action même en pinçant.
        before = len(eng.output.actions)
        feed(eng, [h.pinch_hand(0.5, 0.5) for _ in range(5)], t0=1.0)
        self.assertEqual(len(eng.output.actions), before)

    def test_resume_requires_rearming(self):
        eng = engine()
        feed(eng, [h.open_palm_hand(0.5, 0.5) for _ in range(6)])
        self.assertEqual(eng.state, h.S_PAUSED)
        eng.resume()
        self.assertEqual(eng.state, h.S_ARMED)


class GestureActionTests(unittest.TestCase):
    def test_left_click(self):
        eng = engine()
        t = feed(eng, [h.pinch_hand(0.5, 0.5), h.pointing_hand(0.5, 0.5)])
        # Vider la fenêtre de double-clic pour matérialiser le clic simple.
        feed(eng, [h.pointing_hand(0.5, 0.5)], t0=t + 0.6)
        clicks = [a for a in eng.output.actions if a['action'] == 'click']
        self.assertEqual(len(clicks), 1)
        self.assertEqual(clicks[0], {'action': 'click', 'button': 'left', 'count': 1})

    def test_right_click(self):
        eng = engine()
        feed(eng, [h.pinch_hand(0.5, 0.5, tip=h.MIDDLE_TIP), h.pointing_hand(0.5, 0.5)])
        clicks = [a for a in eng.output.actions if a['action'] == 'click']
        self.assertEqual(clicks, [{'action': 'click', 'button': 'right', 'count': 1}])

    def test_double_click(self):
        eng = engine()
        # Deux pincements rapides dans la fenêtre de double-clic.
        feed(eng, [h.pinch_hand(0.5, 0.5), h.pointing_hand(0.5, 0.5),
                   h.pinch_hand(0.5, 0.5), h.pointing_hand(0.5, 0.5)])
        clicks = [a for a in eng.output.actions if a['action'] == 'click']
        self.assertEqual(clicks, [{'action': 'click', 'button': 'left', 'count': 2}])

    def test_drag_and_drop(self):
        eng = engine()
        # Pincement maintenu > drag_hold_ms puis relâché : bouton bas puis haut.
        t = feed(eng, [h.pinch_hand(0.5, 0.5) for _ in range(15)])
        feed(eng, [h.pointing_hand(0.5, 0.5)], t0=t)
        seq = [a['action'] for a in eng.output.actions if a['action'] in ('button_down', 'button_up')]
        self.assertEqual(seq, ['button_down', 'button_up'])
        self.assertEqual(eng.output.held, set())

    def test_scroll(self):
        eng = engine()
        feed(eng, [h.two_finger_hand(0.5, 0.5 + 0.02 * i) for i in range(12)])
        scrolls = [a for a in eng.output.actions if a['action'] == 'scroll']
        self.assertTrue(scrolls)
        self.assertEqual(scrolls[0]['direction'], 'down')

    def test_swipe_changes_desktop(self):
        eng = engine()
        feed(eng, [h.pointing_hand(0.2 + 0.09 * i, 0.5) for i in range(6)], dt=0.03)
        desk = [a for a in eng.output.actions if a['action'] == 'desktop']
        self.assertEqual(desk, [{'action': 'desktop', 'relative': 1}])

    def test_swipe_left(self):
        eng = engine()
        feed(eng, [h.pointing_hand(0.8 - 0.09 * i, 0.5) for i in range(6)], dt=0.03)
        desk = [a for a in eng.output.actions if a['action'] == 'desktop']
        self.assertEqual(desk, [{'action': 'desktop', 'relative': -1}])

    def test_tremor_is_filtered(self):
        eng = engine()
        feed(eng, [h.pointing_hand(0.5 + (0.002 if i % 2 else -0.002), 0.5) for i in range(20)])
        moves = [a for a in eng.output.actions if a['action'] == 'move']
        self.assertLessEqual(len(moves), 1)  # seul le point initial

    def test_deliberate_move_passes(self):
        eng = engine()
        feed(eng, [h.pointing_hand(0.3, 0.5), h.pointing_hand(0.7, 0.5)])
        self.assertGreaterEqual(len([a for a in eng.output.actions if a['action'] == 'move']), 1)


class DriverHandTests(unittest.TestCase):
    def _hands(self, rx, lx, rconf=0.95, lconf=0.95):
        return [h.pointing_hand(rx, 0.5, handedness='Right', confidence=rconf),
                h.pointing_hand(lx, 0.5, handedness='Left', confidence=lconf)]

    def test_continuity_ignores_better_confidence_on_other_hand(self):
        eng = engine()
        first = eng.select_driver(self._hands(0.4, 0.6, rconf=0.9, lconf=0.7), 0.0)
        self.assertEqual(first.handedness, 'Right')
        # La main gauche devient bien plus confiante, la droite bouge à peine :
        # le pilote NE doit PAS sauter sur la gauche.
        second = eng.select_driver(self._hands(0.42, 0.6, rconf=0.4, lconf=0.99), 0.05)
        self.assertEqual(second.handedness, 'Right')

    def test_switch_only_after_grace(self):
        eng = engine(config=_with(driver_switch_ms=300))
        eng.select_driver([h.pointing_hand(0.4, 0.5, handedness='Right')], 0.0)
        left = [h.pointing_hand(0.6, 0.5, handedness='Left')]
        # Main pilote disparue : dans le délai de grâce -> pas de transfert.
        self.assertIsNone(eng.select_driver(left, 0.1))
        # Après le délai -> transfert au contrôle de l'autre main.
        self.assertEqual(eng.select_driver(left, 0.5).handedness, 'Left')

    def test_preferred_hand_forces_initial_choice(self):
        eng = engine(config=_with(preferred_hand='Left'))
        chosen = eng.select_driver(self._hands(0.4, 0.6, rconf=0.99, lconf=0.6), 0.0)
        self.assertEqual(chosen.handedness, 'Left')

    def test_temporary_loss_then_same_hand_resumes(self):
        eng = engine(config=_with(driver_switch_ms=400))
        r = [h.pointing_hand(0.4, 0.5, handedness='Right')]
        eng.select_driver(r, 0.0)
        self.assertIsNone(eng.select_driver([], 0.1))          # perte 1 frame
        again = eng.select_driver([h.pointing_hand(0.41, 0.5, handedness='Right')], 0.15)
        self.assertEqual(again.handedness, 'Right')            # même main reprend


class BimanualZoomTests(unittest.TestCase):
    def _two(self, dx, conf=0.95):
        return [h.pointing_hand(0.5 - dx, 0.5, handedness='Right', confidence=conf),
                h.pointing_hand(0.5 + dx, 0.5, handedness='Left', confidence=conf)]

    def _commands(self, eng):
        return [e.get('command') for e in eng.channel.events if e.get('command')]

    def test_appearance_does_not_zoom_immediately(self):
        eng = engine(mode='spatial')
        eng.process_sample(self._two(0.10), 0.0)  # référence établie
        self.assertEqual(self._commands(eng), [])

    def test_two_hand_zoom_in_and_out(self):
        eng = engine(mode='spatial')
        eng.process_sample(self._two(0.10), 0.0)   # ref
        eng.process_sample(self._two(0.25), 0.05)  # écartement -> zoom_in
        self.assertIn('zoom_in', self._commands(eng))
        eng.process_sample(self._two(0.08), 0.10)  # rapprochement -> zoom_out
        self.assertIn('zoom_out', self._commands(eng))

    def test_deadband_suppresses_jitter(self):
        eng = engine(mode='spatial', config=_with(mode='spatial', bimanual_zoom_deadband=0.05))
        eng.process_sample(self._two(0.10), 0.0)
        eng.process_sample(self._two(0.105), 0.05)  # variation < bande morte
        self.assertEqual(self._commands(eng), [])

    def test_hand_disappearance_ends_gesture(self):
        eng = engine(mode='spatial')
        eng.process_sample(self._two(0.10), 0.0)
        eng.process_sample(self._two(0.25), 0.05)   # zoom_in
        zooms = lambda: [c for c in self._commands(eng) if c.startswith('zoom_')]
        n = len(zooms())
        # Une main disparaît : l'état de zoom est nettoyé (ref remise à None).
        eng.process_sample([h.pointing_hand(0.5, 0.5, handedness='Right')], 0.10)
        self.assertIsNone(eng._bimanual_ref)
        # Réapparition très écartée : PAS de zoom géant, une nouvelle ref d'abord.
        eng.process_sample(self._two(0.40), 0.15)
        self.assertEqual(len(zooms()), n)

    def test_pointer_mode_two_hands_do_not_zoom(self):
        eng = engine(mode='pointer')
        eng.process_sample(self._two(0.10), 0.0)
        eng.process_sample(self._two(0.30), 0.05)
        self.assertNotIn('zoom_in', self._commands(eng))


class TemporisationTests(unittest.TestCase):
    def test_validation_duration_blocks_single_frame_palm(self):
        eng = engine(config=_with(min_validation_frames=5))
        feed(eng, [h.open_palm_hand(0.5, 0.5) for _ in range(3)])
        self.assertEqual(eng.state, h.S_ACTIVE)  # pas encore validé
        feed(eng, [h.open_palm_hand(0.5, 0.5) for _ in range(4)], t0=1.0)
        self.assertEqual(eng.state, h.S_PAUSED)

    def test_gesture_cooldown_rate_limits_right_clicks(self):
        eng = engine(config=_with(gesture_cooldown_ms=500))
        # Deux pincements pouce-majeur rapprochés : le second est temporisé.
        feed(eng, [h.pinch_hand(0.5, 0.5, tip=h.MIDDLE_TIP), h.pointing_hand(0.5, 0.5),
                   h.pinch_hand(0.5, 0.5, tip=h.MIDDLE_TIP), h.pointing_hand(0.5, 0.5)], dt=0.05)
        rights = [a for a in eng.output.actions if a.get('button') == 'right']
        self.assertEqual(len(rights), 1)

    def test_swipe_cooldown_prevents_repeats(self):
        eng = engine(config=_with(swipe_cooldown_ms=800))
        # Deux balayages consécutifs très rapprochés -> un seul pris en compte.
        feed(eng, [h.pointing_hand(0.2 + 0.09 * i, 0.5) for i in range(6)], dt=0.03)
        feed(eng, [h.pointing_hand(0.2 + 0.09 * i, 0.5) for i in range(6)], t0=0.20, dt=0.03)
        desk = [a for a in eng.output.actions if a['action'] == 'desktop']
        self.assertEqual(len(desk), 1)


class ExternalClickAuthTests(unittest.TestCase):
    def test_click_blocked_without_keyboard_authorization(self):
        eng = engine(authorized=False)
        t = feed(eng, [h.pinch_hand(0.5, 0.5), h.pointing_hand(0.5, 0.5)])
        feed(eng, [h.pointing_hand(0.5, 0.5)], t0=t + 0.6)
        # Aucun clic système injecté sans F8 maintenu.
        self.assertEqual([a for a in eng.output.actions if a['action'] == 'click'], [])
        commands = [e.get('command') for e in eng.channel.events if e.get('command')]
        self.assertIn('click_needs_key', commands)

    def test_click_allowed_with_keyboard_authorization(self):
        eng = engine(authorized=True)
        t = feed(eng, [h.pinch_hand(0.5, 0.5), h.pointing_hand(0.5, 0.5)])
        feed(eng, [h.pointing_hand(0.5, 0.5)], t0=t + 0.6)
        self.assertEqual([a for a in eng.output.actions if a['action'] == 'click'],
                         [{'action': 'click', 'button': 'left', 'count': 1}])

    def test_missing_authorizer_blocks_by_default(self):
        # require_click_auth mais aucun autorisateur -> on s'abstient (sûr).
        cfg = h.load_config('none')
        eng = h.HandControlEngine(cfg, output=h.RecordingActionSink(),
                                  channel=h.RecordingEventChannel(), screen_size=(800, 480),
                                  stop_file='no_stop', initial_state=h.S_ACTIVE, desktop=None)
        t = feed(eng, [h.pinch_hand(0.5, 0.5), h.pointing_hand(0.5, 0.5)])
        feed(eng, [h.pointing_hand(0.5, 0.5)], t0=t + 0.6)
        self.assertEqual([a for a in eng.output.actions if a['action'] == 'click'], [])

    def test_pointer_movement_does_not_require_authorization(self):
        eng = engine(authorized=False)
        feed(eng, [h.pointing_hand(0.3, 0.5), h.pointing_hand(0.7, 0.5)])
        # Le pointeur peut bouger (préparer l'intention) sans autorisation.
        self.assertTrue([a for a in eng.output.actions if a['action'] == 'move'])

    def test_spatial_commands_are_not_gated(self):
        # Spatial passe par le canal local (interne), pas de clic système : non soumis à F8.
        eng = engine(mode='spatial', authorized=False)
        t = feed(eng, [h.pinch_hand(0.5, 0.5), h.pointing_hand(0.5, 0.5)])
        feed(eng, [h.pointing_hand(0.5, 0.5)], t0=t + 0.6)
        commands = [e.get('command') for e in eng.channel.events if e.get('command')]
        self.assertIn('select', commands)

    def test_presentation_toggle_drives_real_cursor(self):
        desk = FakeDesktop(authorized=True)
        eng = engine(mode='presentation', desktop=desk)
        feed(eng, [h.open_palm_hand(0.5, 0.5) for _ in range(6)])
        self.assertIn(False, desk.visible_calls)  # curseur masqué via XFixes


class RobustnessTests(unittest.TestCase):
    def test_hand_loss_releases_held_buttons(self):
        eng = engine()
        t = feed(eng, [h.pinch_hand(0.5, 0.5) for _ in range(15)])  # glisser en cours
        self.assertEqual(eng.output.held, {'left'})
        feed(eng, [None, None, None], t0=t)
        self.assertEqual(eng.output.held, set())

    def test_output_error_releases_buttons_and_pauses(self):
        eng = engine(fail_on='button_down')
        feed(eng, [h.pinch_hand(0.5, 0.5) for _ in range(15)])
        self.assertIsNotNone(eng.error)
        self.assertEqual(eng.output.held, set())
        self.assertEqual(eng.state, h.S_PAUSED)

    def test_shared_stop_blocks_and_releases(self):
        with tempfile.TemporaryDirectory() as folder:
            stop = Path(folder) / 'agent.stop'
            eng = engine(stop=stop)
            # Démarrer un glisser, puis déclencher le STOP partagé.
            feed(eng, [h.pinch_hand(0.5, 0.5) for _ in range(15)])
            self.assertEqual(eng.output.held, {'left'})
            stop.write_text('stop')
            feed(eng, [h.pinch_hand(0.5, 0.5) for _ in range(3)], t0=1.0)
            self.assertEqual(eng.state, h.S_STOPPED)
            self.assertEqual(eng.output.held, set())
            before = len(eng.output.actions)
            feed(eng, [h.pinch_hand(0.5, 0.5) for _ in range(5)], t0=2.0)
            self.assertEqual(len(eng.output.actions), before)  # rien injecté

    def test_stop_recovery_requires_reactivation(self):
        with tempfile.TemporaryDirectory() as folder:
            stop = Path(folder) / 'agent.stop'
            stop.write_text('stop')
            eng = engine(stop=stop)
            feed(eng, [h.pinch_hand(0.5, 0.5) for _ in range(3)])
            self.assertEqual(eng.state, h.S_STOPPED)
            stop.unlink()
            # Le fichier disparu ne suffit pas : on reste STOPPED.
            feed(eng, [h.pointing_hand(0.5, 0.5) for _ in range(5)], t0=1.0)
            self.assertEqual(eng.state, h.S_STOPPED)
            # Réactivation locale explicite + ré-armement.
            eng.request_active()
            feed(eng, [h.pointing_hand(0.5, 0.5) for _ in range(40)], t0=2.0)
            self.assertEqual(eng.state, h.S_ACTIVE)

    def test_hand_loss_without_drag_is_safe(self):
        eng = engine()
        feed(eng, [None, None])
        self.assertEqual(eng.output.actions, [])
        self.assertFalse(eng.tracking)


class ModeTests(unittest.TestCase):
    def test_mode_change_releases_buttons(self):
        eng = engine()
        feed(eng, [h.pinch_hand(0.5, 0.5) for _ in range(15)])  # glisser -> bouton bas
        self.assertEqual(eng.output.held, {'left'})
        eng.set_mode('presentation')
        self.assertEqual(eng.output.held, set())
        self.assertEqual(eng.mode, 'presentation')

    def test_presentation_swipe_changes_slide(self):
        eng = engine(mode='presentation')
        feed(eng, [h.pointing_hand(0.2 + 0.09 * i, 0.5) for i in range(6)], dt=0.03)
        slides = [a for a in eng.output.actions if a['action'] == 'slide']
        self.assertEqual(slides, [{'action': 'slide', 'direction': 'next'}])

    def test_presentation_palm_toggles_pointer(self):
        eng = engine(mode='presentation')
        self.assertTrue(eng.pointer_visible)
        feed(eng, [h.open_palm_hand(0.5, 0.5) for _ in range(6)])
        self.assertFalse(eng.pointer_visible)
        self.assertEqual(eng.state, h.S_ACTIVE)  # présentation : pas de pause à la paume

    def test_spatial_uses_channel_not_desktop(self):
        eng = engine(mode='spatial')
        # Un clic (pincement rapide) doit produire une commande locale, pas
        # d'injection bureau.
        t = feed(eng, [h.pinch_hand(0.5, 0.5), h.pointing_hand(0.5, 0.5)])
        feed(eng, [h.pointing_hand(0.5, 0.5)], t0=t + 0.6)
        self.assertEqual([a for a in eng.output.actions], [])
        commands = [e.get('command') for e in eng.channel.events if e.get('command')]
        self.assertIn('select', commands)

    def test_spatial_horizontal_drag_rotates_vertical_tilts(self):
        import hand_events
        # Pincement maintenu (drag) qui glisse horizontalement -> rotation.
        eng = engine(mode='spatial')
        t = 0.0
        for x in (0.50, 0.50, 0.56, 0.62, 0.68):  # tenu puis glissé à droite
            eng.process_sample(h.pinch_hand(x, 0.5), t); t += 0.05
        cmds = [e.get('command') for e in eng.channel.events if e.get('command')]
        self.assertTrue(any(c in ('rotate_left', 'rotate_right') for c in cmds))
        # Glissement vertical -> inclinaison (tilt).
        eng2 = engine(mode='spatial')
        t = 0.0
        for y in (0.50, 0.50, 0.56, 0.62, 0.68):
            eng2.process_sample(h.pinch_hand(0.5, y), t); t += 0.05
        cmds2 = [e.get('command') for e in eng2.channel.events if e.get('command')]
        self.assertTrue(any(c in ('tilt_up', 'tilt_down') for c in cmds2))
        # Toute commande Spatial émise est valide pour le pont hand_events.
        for e in eng.channel.events + eng2.channel.events:
            if e.get('mode') == 'spatial' and e.get('command'):
                hand_events.validate_event(e)

    def test_spatial_spread_explodes(self):
        eng = engine(mode='spatial')
        feed(eng, [h.open_palm_hand(0.5, 0.5, spread=True) for _ in range(6)])
        cmds = [e.get('command') for e in eng.channel.events if e.get('command')]
        self.assertIn('explode', cmds)


class PointAndCommandTests(unittest.TestCase):
    def test_event_has_required_fields_and_no_image(self):
        eng = engine()
        feed(eng, [h.pointing_hand(0.3, 0.5), h.pointing_hand(0.7, 0.5)])
        self.assertTrue(eng.channel.events)
        ev = eng.channel.events[-1]
        for key in ('timestamp', 'normalized', 'screen', 'handedness',
                    'gesture', 'confidence', 'mode'):
            self.assertIn(key, ev)
        # Aucune donnée d'image dans l'événement.
        self.assertNotIn('image', json.dumps(ev))

    def test_local_channel_is_loopback_only(self):
        with self.assertRaises(ValueError):
            h.LocalEventChannel(host='8.8.8.8', port=9000)
        # Loopback autorisé, port 0 = émetteur muet (aucun paquet).
        ch = h.LocalEventChannel(host='127.0.0.1', port=0)
        ch.emit({'gesture': 'x'})
        ch.close()


class OutputSafetyTests(unittest.TestCase):
    def test_no_dynamic_shell_command_in_source(self):
        source = (ROOT / 'runtime/hand_tracking.py').read_text(encoding='utf-8')
        self.assertNotIn('shell=True', source)
        self.assertNotIn('os.system', source)
        self.assertNotIn('os.popen', source)

    def test_xdotool_sink_uses_argument_lists_never_shell(self):
        calls = []

        def fake_run(argv, *a, **kw):
            calls.append((argv, kw))
            class R:
                returncode = 0
            return R()

        with patch.object(h.shutil, 'which', return_value='/usr/bin/xdotool'), \
             patch.object(h.subprocess, 'run', side_effect=fake_run):
            sink = h.XdotoolActionSink(display=':0')
            sink.move(123, 45)
            sink.click('left', 2)
            sink.button_down('left')
            sink.button_up('left')
            sink.scroll('down', 3)
            sink.desktop(1)
            sink.slide('next')
        self.assertTrue(calls)
        for argv, kw in calls:
            self.assertIsInstance(argv, list)              # jamais une chaîne
            self.assertEqual(argv[0], 'xdotool')
            self.assertTrue(all(isinstance(a, str) for a in argv))
            self.assertNotIn('shell', kw)                  # jamais shell=True

    def test_move_coordinates_are_integers(self):
        calls = []
        with patch.object(h.shutil, 'which', return_value='/usr/bin/xdotool'), \
             patch.object(h.subprocess, 'run', side_effect=lambda argv, *a, **k: calls.append(argv) or type('R', (), {'returncode': 0})()):
            sink = h.XdotoolActionSink(display=':0')
            sink.move(10.7, 20.2)
        self.assertEqual(calls[0], ['xdotool', 'mousemove', '10', '20'])

    def test_unknown_button_rejected(self):
        with patch.object(h.shutil, 'which', return_value='/usr/bin/xdotool'), \
             patch.object(h.subprocess, 'run'):
            sink = h.XdotoolActionSink(display=':0')
            with self.assertRaises(ValueError):
                sink.click('purple')


class BackendTests(unittest.TestCase):
    def test_simulated_backend_replays_sequence(self):
        seq = [h.pointing_hand(0.5, 0.5), None, h.pinch_hand(0.5, 0.5)]
        backend = h.SimulatedBackend(seq)
        self.assertEqual(len(backend.detect(None, 0.0)), 1)
        self.assertEqual(backend.detect(None, 0.0), [])
        self.assertEqual(len(backend.detect(None, 0.0)), 1)

    def test_hailo_backend_is_not_supported_yet(self):
        with self.assertRaises(NotImplementedError):
            h.HailoBackend()

    def test_simulated_backend_is_explicit(self):
        # make_backend ne bascule PAS silencieusement sur le simulé : il faut le
        # demander explicitement (durcissement Codex). 'auto' exige MediaPipe.
        cfg = h.load_config('none')
        cfg['backend'] = 'simulated'
        self.assertIsInstance(h.make_backend(cfg), h.SimulatedBackend)

    def test_auto_backend_requires_mediapipe_model(self):
        import importlib.util
        if importlib.util.find_spec('mediapipe') is not None:
            self.skipTest('MediaPipe installed; auto would build a real backend.')
        cfg = h.load_config('none')
        cfg['backend'] = 'auto'
        # Sans MediaPipe ni modèle local, l'échec est explicite (pas de repli muet).
        with self.assertRaises(RuntimeError):
            h.make_backend(cfg)


class PerfTests(unittest.TestCase):
    def test_percentile(self):
        self.assertEqual(h._percentile([1, 2, 3, 4], 50), 2.5)
        self.assertAlmostEqual(h._percentile([10, 20, 30, 40, 50], 95), 48.0)

    def test_report_shape(self):
        perf = h.PerfMonitor()
        now = 0.0
        for i in range(30):
            perf.record(0.001, 0.01, 0.012, now)
            now += 0.033
        perf.drop()
        report = perf.report()
        for key in ('fps_capture', 'fps_inference', 'latency_ms_median', 'latency_ms_p95', 'dropped_frames'):
            self.assertIn(key, report)
        self.assertEqual(report['dropped_frames'], 1)

    def test_benchmark_report_labels_simulated_pipeline(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = h.load_config('none')
            cfg['backend'] = 'simulated'
            cfg['camera'] = 'simulated'
            cfg['target_fps'] = 60
            path = Path(folder) / 'hand-tracking.json'
            h.save_config(cfg, path)
            state = Path(folder) / 'hand-control.json'
            out = io.StringIO()
            with patch.object(h, 'CONFIG_FILE', path), patch.object(h, 'STATE_FILE', state), \
                 patch.object(h, '_query_screen_size', return_value=(800, 480)), \
                 contextlib.redirect_stdout(out):
                rc = h.cmd_benchmark(0.3)
            self.assertEqual(rc, 0)
            report = json.loads(out.getvalue())
            self.assertEqual(report['backend'], 'simulated')
            self.assertFalse(report['real_camera'])
            self.assertGreaterEqual(report['frames'], 1)

    def test_benchmark_auto_backend_without_model_does_not_crash(self):
        # make_backend('auto') lève sans modèle : le benchmark doit retomber sur
        # le pipeline simulé plutôt que de planter (régression).
        with tempfile.TemporaryDirectory() as folder:
            cfg = h.load_config('none')
            cfg['backend'] = 'auto'
            cfg['camera'] = 'simulated'
            cfg['model_path'] = str(Path(folder) / 'absent.task')
            path = Path(folder) / 'hand-tracking.json'
            h.save_config(cfg, path)
            state = Path(folder) / 'hand-control.json'
            out = io.StringIO()
            with patch.object(h, 'CONFIG_FILE', path), patch.object(h, 'STATE_FILE', state), \
                 patch.object(h, '_query_screen_size', return_value=(800, 480)), \
                 contextlib.redirect_stdout(out):
                rc = h.cmd_benchmark(0.3)
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(out.getvalue())['backend'], 'simulated')


class HandDepsTests(unittest.TestCase):
    def test_dry_run_is_read_only_and_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(
                [sys.executable, str(ROOT / 'install/hand-deps.py'), '--dry-run'],
                cwd=folder, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(folder).iterdir()), [])  # rien écrit
            plan = json.loads(result.stdout)
            self.assertTrue(plan['model_url'].startswith('https://'))
            self.assertIn('mediapipe', plan)


class LatestFrameBufferTests(unittest.TestCase):
    def test_single_slot_drops_stale_frames(self):
        buf = h.LatestFrameBuffer()
        buf.put('a')
        buf.put('b')
        buf.put('c')  # 'a' et 'b' abandonnées
        frame, dropped = buf.get()
        self.assertEqual(frame, 'c')
        self.assertEqual(dropped, 2)
        # Après lecture, la file est vide et le compteur remis à zéro.
        self.assertEqual(buf.get(), (None, 0))


class StateFileTests(unittest.TestCase):
    def test_status_json_shape(self):
        eng = engine()
        feed(eng, [h.pointing_hand(0.5, 0.5)])
        status = eng.status()
        blob = json.dumps(status)  # doit être sérialisable
        for key in ('state', 'mode', 'tracking', 'held_buttons', 'fps_capture', 'last_event'):
            self.assertIn(key, status)
        self.assertIn(status['state'], (h.S_ACTIVE, h.S_ARMED))
        self.assertIsInstance(json.loads(blob)['held_buttons'], list)

    def test_state_read_write_and_control(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'hand-control.json'
            control = Path(folder) / 'hand-control.cmd'
            h.write_state({'state': h.S_ACTIVE, 'mode': 'pointer'}, state)
            data = h.read_state(state)
            self.assertEqual(data['state'], h.S_ACTIVE)
            self.assertTrue(data['running'])  # écrit à l'instant
            h.write_control({'desired': 'paused'}, control)
            self.assertEqual(h.read_control(control)['desired'], 'paused')

    def test_read_state_missing_is_stopped(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(h.read_state(Path(folder) / 'absent.json')['state'], h.S_DISABLED)

    def test_apply_control_pauses_and_switches_mode(self):
        eng = engine()
        h.apply_control(eng, {'desired': 'paused'})
        self.assertEqual(eng.state, h.S_PAUSED)
        h.apply_control(eng, {'mode': 'spatial'})
        self.assertEqual(eng.mode, 'spatial')


def _with(**overrides):
    cfg = h.load_config('none')
    cfg.update(overrides)
    return h.validate_config(cfg)


class HardeningTests(unittest.TestCase):
    def test_resume_command_is_not_replayed_after_stop(self):
        eng = engine(state=h.S_PAUSED)
        command = {'desired': 'active', 'ts': 1}
        h.apply_control(eng, command)
        eng._release_and(h.S_STOPPED)
        h.apply_control(eng, command)
        self.assertEqual(eng.state, h.S_STOPPED)
        h.apply_control(eng, {'desired': 'active', 'ts': 2})
        self.assertEqual(eng.state, h.S_ARMED)

    def test_nonfinite_samples_rejected(self):
        for value in (float('nan'), float('inf')):
            points = [(0.5, 0.5, 0)] * 21
            points[8] = (value, 0.5, 0)
            with self.assertRaises(ValueError):
                h.HandSample(points)
            with self.assertRaises(ValueError):
                h.pointing_hand(confidence=value)

    def test_fractional_frame_configuration_rejected(self):
        cfg = h.load_config('missing')
        cfg['analysis_width'] = 640.5
        with self.assertRaises(ValueError):
            h.validate_config(cfg)

    def test_hand_loss_restarts_arming_hold(self):
        eng = engine(state=h.S_ARMED)
        feed(eng, [h.pointing_hand()] * 10)
        eng.process_sample(None, 0.6)
        eng.process_sample(h.pointing_hand(), 1.0)
        self.assertEqual(eng.state, h.S_ARMED)

    def test_disabled_status_is_not_running(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'state'
            h.write_state({'state': h.S_DISABLED, 'running': False}, path)
            self.assertFalse(h.read_state(path)['running'])

    def test_observation_never_creates_desktop_output_or_writes_state(self):
        cfg = h.load_config('missing')
        camera = h.SimulatedCamera([h.pointing_hand()] * 3)
        with patch.object(h, 'XdotoolActionSink', side_effect=AssertionError('desktop')), \
             patch.object(h, 'write_state', side_effect=AssertionError('state')), \
             patch.object(h, '_query_screen_size', return_value=(800, 480)):
            h.run_engine(cfg, camera, h.SimulatedBackend(), observe_only=True)

    def test_camera_exception_propagates_and_buffer_clears(self):
        from unittest.mock import Mock
        source = Mock()
        source.read.side_effect = RuntimeError('disconnected')
        camera = h.ThreadedCamera(source)
        camera.start()
        camera._thread.join(1)
        with self.assertRaisesRegex(RuntimeError, 'disconnected'):
            camera.read_latest()
        camera._buf.put(object())
        camera.stop()
        self.assertIsNone(camera._buf.get()[0])
        source.stop.assert_called_once()

    def test_calibration_uses_measured_landmarks_and_closes_resources(self):
        from unittest.mock import Mock
        camera, backend = Mock(), Mock()
        backend.detect.return_value = [h.pointing_hand(0.32, 0.41)]
        with patch.object(h, 'make_camera', return_value=camera), \
             patch.object(h, 'make_backend', return_value=backend), \
             patch.object(h.time, 'sleep'):
            point = h.measure_calibration_point(h.load_config('missing'))
        self.assertAlmostEqual(point[0], 0.32)
        self.assertAlmostEqual(point[1], 0.41)
        camera.stop.assert_called_once()
        backend.close.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
