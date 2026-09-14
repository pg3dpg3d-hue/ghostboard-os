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
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
import hand_tracking as h


def engine(mode='pointer', state=h.S_ACTIVE, stop='no_such_stop', fail_on=None, config=None):
    cfg = config or h.load_config('does-not-exist.json')
    cfg['mode'] = mode
    out = h.RecordingActionSink(fail_on=fail_on)
    ch = h.RecordingEventChannel()
    return h.HandControlEngine(cfg, output=out, channel=ch, screen_size=(800, 480),
                              stop_file=stop, initial_state=state)


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


class PointAndCommandTests(unittest.TestCase):
    def test_event_has_required_fields_and_no_image(self):
        eng = engine()
        feed(eng, [h.pointing_hand(0.3, 0.5), h.pointing_hand(0.7, 0.5)])
        self.assertTrue(eng.channel.events)
        ev = eng.channel.events[-1]
        for key in ('timestamp_monotonic', 'normalized', 'screen', 'handedness',
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

    def test_auto_backend_falls_back_to_simulated_without_mediapipe(self):
        import importlib.util
        if importlib.util.find_spec('mediapipe') is not None:
            self.skipTest('MediaPipe installed; auto would pick it.')
        cfg = h.load_config('none')
        cfg['backend'] = 'auto'
        self.assertIsInstance(h.make_backend(cfg), h.SimulatedBackend)


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
