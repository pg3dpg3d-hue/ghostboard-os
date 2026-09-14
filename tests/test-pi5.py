#!/usr/bin/env python3
"""Tests sans Pi : restauration réelle en dossier temporaire, API locale, intégration."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
import ghostboard as gb
import assistant
import hardware
import model
import remote
import voice
spec = importlib.util.spec_from_file_location('pi5', ROOT / 'install/pi5.py')
pi5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pi5)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.state = patch.object(gb, 'STATE', self.root / 'state')
        self.state.start()
        self.file = self.home / '.config/ghostboard/assistant.json'
        self.file.parent.mkdir(parents=True)
        self.file.write_text('{"model":"before"}')

    def tearDown(self):
        self.state.stop()
        self.temp.cleanup()

    def test_roundtrip_preserves_rollback(self):
        archive = self.root / 'settings.tar.gz'
        gb.backup(archive, self.home)
        self.file.write_text('{"model":"after"}')
        rollback = gb.restore(archive, self.home)
        self.assertEqual(json.loads(self.file.read_text())['model'], 'before')
        with tarfile.open(rollback) as tf:
            self.assertIn(b'after', tf.extractfile('.config/ghostboard/assistant.json').read())

    def test_no_overwrite(self):
        archive = self.root / 'settings.tar.gz'
        archive.write_bytes(b'important')
        with self.assertRaises(ValueError):
            gb.backup(archive, self.home)
        self.assertEqual(archive.read_bytes(), b'important')

    def test_archive_cannot_be_inside_source(self):
        with self.assertRaises(ValueError):
            gb.backup(self.file.parent / 'recursive.tar.gz', self.home)

    def test_rejects_traversal_and_links_before_writing(self):
        for name, kind in [('../outside', tarfile.REGTYPE), ('.config/ghostboard/../../outside', tarfile.REGTYPE), ('.config/ghostboard/link', tarfile.SYMTYPE), ('/etc/passwd', tarfile.REGTYPE), ('.ssh/id_rsa', tarfile.REGTYPE)]:
            with self.subTest(name=name):
                archive = self.root / 'evil.tar.gz'
                with tarfile.open(archive, 'w:gz') as tf:
                    valid = tarfile.TarInfo('.config/ghostboard/assistant.json')
                    valid.size = 3
                    tf.addfile(valid, io.BytesIO(b'bad'))
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    member.linkname = '/etc/passwd' if kind == tarfile.SYMTYPE else ''
                    tf.addfile(member)
                with self.assertRaises(ValueError):
                    gb.restore(archive, self.home)
                self.assertIn('before', self.file.read_text())

    def test_excludes_unrelated_credentials(self):
        secret = self.home / '.ssh/id_rsa'
        secret.parent.mkdir()
        secret.write_text('secret')
        archive = self.root / 'settings.tar.gz'
        gb.backup(archive, self.home)
        with tarfile.open(archive) as tf:
            self.assertFalse(any('.ssh' in name for name in tf.getnames()))


class InstallerTests(unittest.TestCase):
    def test_plan_preserves_firmware_and_services(self):
        plan = pi5.plan('full')
        self.assertTrue(set(pi5.BASE) <= set(plan['packages']))
        self.assertIn('pipewire-audio', plan['packages'])
        self.assertIn('at-spi2-core', plan['packages'])
        self.assertNotIn('grub-pc', plan['packages'])
        self.assertEqual(len(plan['packages']), len(set(plan['packages'])))
        for tool in pi5.TOOLS:
            self.assertTrue((ROOT / 'tools' / tool).exists(), tool)

    def test_image_recipe_is_pinned_and_has_no_password(self):
        builder = (ROOT / 'image/build-image.sh').read_text()
        config = (ROOT / 'image/rpi-image-gen/config/ghostboard.yaml').read_text()
        layer = (ROOT / 'image/rpi-image-gen/layer/ghostboard-pi5.yaml').read_text()
        self.assertIn('PIN=262d4df5a9f9d4133370465399a7958a7c22cdc7', builder)
        self.assertIn('base: trixie-minbase', config)
        self.assertIn('layer: rpi5', config)
        self.assertNotIn('user1passhash:', config)
        self.assertIn('/etc/ghostboard-image-build', layer)
        self.assertIn('GHOSTBOARD_IMAGE_BUILD=1', layer)

    def test_keyboard_idempotent_and_preserves_custom(self):
        import xml.etree.ElementTree as ET
        xml = b'<channel name="xfce4-keyboard-shortcuts"><property name="commands"><property name="custom"><property name="custom-key" value="custom-command"/></property></property></channel>'
        first = pi5.keyboard_config(xml)
        second = pi5.keyboard_config(first)
        self.assertEqual(first, second)
        self.assertIn(b'custom-command', second)
        root = ET.fromstring(second)
        self.assertEqual(len([p for p in root.iter('property') if p.get('value') == 'ghost-system stop']), 1)

    def test_dry_run_without_root_is_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, str(ROOT / 'install/pi5.py'), '--dry-run'], cwd=folder, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(folder).iterdir()), [])
            self.assertEqual(json.loads(result.stdout)['profile'], 'full')


class HardwareTests(unittest.TestCase):
    def test_fan_profile_block_is_reversible_and_idempotent(self):
        original = '# user setting\ndtoverlay=vc4-kms-v3d\n'
        profiled = hardware.replace_block(original, hardware.PROFILES['balanced'])
        self.assertIn('# user setting', profiled)
        self.assertIn('fan_temp2=67500', profiled)
        self.assertEqual(hardware.replace_block(profiled, hardware.PROFILES['balanced']), profiled)
        self.assertEqual(hardware.replace_block(profiled, []), original)


class ModelTests(unittest.TestCase):
    def test_multimodal_projector_enables_local_vision(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            weights = root / 'vision.gguf'
            projector = root / 'mmproj.gguf'
            server = root / 'llama-server'
            weights.write_bytes(b'GGUFweights')
            projector.write_bytes(b'GGUFprojector')
            server.write_text('#!/bin/sh\n')
            server.chmod(0o755)
            config = root / 'assistant.json'
            with patch.object(Path, 'home', return_value=root), patch.object(model, 'CONFIG', config), \
                 patch.object(model.subprocess, 'run'):
                model.configure(weights, server, projector)
            unit = (root / '.config/systemd/user/ghostboard-local-model.service').read_text()
            self.assertIn('--mmproj', unit)
            self.assertIn('-c 4096', unit)
            self.assertTrue(json.loads(config.read_text())['providers']['local']['vision'])


class VoiceTests(unittest.TestCase):
    def test_configuration_is_private(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model_file = root / 'whisper.gguf'
            model_file.write_bytes(b'model')
            config = root / 'voice.json'
            with patch.object(voice, 'CONFIG', config), contextlib.redirect_stdout(io.StringIO()):
                voice.configure(model_file, 'default', 'fr')
            self.assertEqual(json.loads(config.read_text())['model'], str(model_file.resolve()))
            if os.name != 'nt':
                self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_denied_transcript_never_reaches_assistant(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model_file = root / 'whisper.gguf'
            model_file.write_bytes(b'model')
            config = root / 'voice.json'
            config.write_text(json.dumps({'model': str(model_file), 'device': 'default', 'language': 'fr'}))
            argv = ['ghost-voice', '--seconds', '1']
            with patch.object(voice, 'CONFIG', config), patch.object(sys, 'argv', argv), \
                 patch.object(voice, 'record'), patch.object(voice, 'transcribe', return_value='ouvre le navigateur'), \
                 patch('builtins.input', return_value='n'), patch.object(voice.subprocess, 'call') as call, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(voice.main(), 1)
            call.assert_not_called()

class AssistantTests(unittest.TestCase):
    def test_visual_input_checks_real_file_signature(self):
        part = assistant.image_data(b'\x89PNG\r\n\x1a\n' + b'data')
        self.assertTrue(part['image_url']['url'].startswith('data:image/png;base64,'))
        with self.assertRaises(ValueError):
            assistant.image_data(b'not an image')

    def test_local_visual_analysis_needs_no_share_prompt(self):
        provider = {'base_url': 'http://127.0.0.1:8080/v1', 'model': 'visual', 'vision': True}
        png = assistant.image_data(b'\x89PNG\r\n\x1a\n' + b'data')
        with patch.object(assistant, 'screen_image', return_value=png), \
             patch.object(assistant, 'completion', return_value={'content': 'visible'}), \
             patch('builtins.input') as ask, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(assistant.see(provider, 'describe', ('screen', None)), 0)
        ask.assert_not_called()

    def test_systemd_path_escaping(self):
        self.assertEqual(model.quote('/models/50% $test.gguf'), '"/models/50%% $$test.gguf"')
        with self.assertRaises(ValueError):
            model.quote('/model\nExecStart=bad')

    def test_denied_action_never_executes(self):
        class FakeMCP:
            executed = False
            closed = False
            def __init__(self, **kwargs):
                pass
            def call(self, method, params):
                if method == 'tools/list':
                    return {'tools': [{'name': 'click', 'description': 'click', 'inputSchema': {'type': 'object'}}]}
                FakeMCP.executed = True
            def close(self):
                FakeMCP.closed = True
        reply = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'one', 'type': 'function', 'function': {'name': 'click', 'arguments': '{"x":1,"y":1}'}}]}
        with patch.object(assistant, 'MCP', FakeMCP), patch.object(assistant, 'completion', return_value=reply), patch('builtins.input', side_effect=['y', 'n']), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(assistant.act({'vision': True, 'base_url': 'http://localhost/v1'}, 'test', 1), 1)
        self.assertFalse(FakeMCP.executed)
        self.assertTrue(FakeMCP.closed)

    def test_rejects_remote_http_and_url_credentials(self):
        for url in ['http://example.org/v1', 'https://key@example.org/v1', 'https://example.org/v1?key=secret', 'file:///etc/passwd']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                assistant.validate_provider({'base_url': url, 'model': 'test'})

    def test_missing_key_reported_without_request(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, 'Missing environment'):
            assistant.validate_provider({'base_url': 'https://example.org/v1', 'model': 'test', 'key_env': 'TEST_KEY'})

    def test_local_completion_real_http(self):
        observed = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                observed.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                body = json.dumps({'choices': [{'message': {'role': 'assistant', 'content': 'local reply'}}]}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = assistant.completion({'base_url': f'http://127.0.0.1:{server.server_port}/v1', 'model': 'test'}, [{'role': 'user', 'content': 'hello'}])
            self.assertEqual(result['content'], 'local reply')
            self.assertEqual(observed[0][0], '/v1/chat/completions')
            self.assertEqual(observed[0][1]['model'], 'test')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_mcp_real_handshake_and_catalog(self):
        if not __import__('shutil').which('node'):
            self.skipTest('Node unavailable')
        mcp = assistant.MCP(ROOT / 'mcp-computer-use/server.js')
        try:
            tools = mcp.call('tools/list', {})['tools']
            self.assertTrue({'screenshot', 'drag', 'windows', 'focus_window'} <= {t['name'] for t in tools})
        finally:
            mcp.close()

    def test_text_only_model_cannot_control_screen(self):
        with self.assertRaisesRegex(ValueError, 'image and tool-call'):
            assistant.act({'vision': False}, 'task', 1)

    def test_unknown_app_does_not_execute(self):
        with patch('subprocess.Popen') as popen, self.assertRaises(ValueError):
            gb.launch('arbitrary shell command')
        popen.assert_not_called()

    def test_stop_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            stop = Path(folder) / 'state/agent.stop'
            with patch.object(gb, 'STATE', stop.parent), patch.object(gb, 'STOP', stop):
                gb.set_stopped(True)
                self.assertTrue(stop.exists())
                gb.set_stopped(False)
                self.assertFalse(stop.exists())


class RemoteTests(unittest.TestCase):
    def test_codex_and_claude_use_the_same_remote_mcp(self):
        for tool, prefix in [('codex', 'codex mcp add'), ('claude', 'claude mcp add')]:
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                remote.client_config(tool, 'ghostboard.example.ts.net', 'ghost')
            command = stream.getvalue()
            self.assertIn(prefix, command)
            self.assertIn('ssh -T ghost@ghostboard.example.ts.net', command)
            self.assertIn('mcp-computer-use/server.js', command)

    def test_remote_host_is_not_shell_text(self):
        with self.assertRaises(ValueError):
            remote.client_config('codex', 'host;touch /tmp/bad', 'ghost')


if __name__ == '__main__':
    unittest.main(verbosity=2)
