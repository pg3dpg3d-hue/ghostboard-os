#!/usr/bin/env python3
"""Validation Linux/X11 : saisie réellement reçue par une application."""
import base64
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from assistant import MCP

if not os.environ.get('DISPLAY'):
    sys.exit('Run with xvfb-run -a python3 tests/test-desktop-live.py')

with tempfile.TemporaryDirectory() as folder:
    dest = Path(folder) / 'received.txt'
    receiver = Path(folder) / 'receive.py'
    receiver.write_text('import pathlib,sys\nline=sys.stdin.readline()\npathlib.Path(sys.argv[1]).write_text(line)\ninput()\n')
    window = subprocess.Popen(['xterm', '-T', 'Ghostboard live test', '-e', sys.executable, str(receiver), str(dest)])
    mcp = None
    try:
        for _ in range(50):
            result = subprocess.run(['xdotool', 'search', '--name', '^Ghostboard live test$'], capture_output=True, text=True)
            if result.returncode == 0:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError('Test window did not appear')
        wid = result.stdout.strip().splitlines()[-1]
        subprocess.run(['xdotool', 'windowfocus', '--sync', wid], check=True)
        mcp = MCP()
        for tool, args in [('type', {'text': 'ghostboard-live-verified', 'delay_ms': 2}), ('key', {'keys': 'Return'})]:
            r = mcp.call('tools/call', {'name': tool, 'arguments': args})
            assert not r.get('isError'), r
        for _ in range(50):
            if dest.exists():
                break
            time.sleep(0.1)
        assert dest.read_text().strip() == 'ghostboard-live-verified'
        shot = mcp.call('tools/call', {'name': 'screenshot', 'arguments': {}})
        image = next(c for c in shot['content'] if c['type'] == 'image')
        png = base64.b64decode(image['data'])
        assert png[:8] == b'\x89PNG\r\n\x1a\n'
        assert len(png) > 100
        print('PASS: real X11 typing received by xterm; screen capture returns PNG.')
    finally:
        if mcp:
            mcp.close()
        window.terminate()
        window.wait(timeout=5)
