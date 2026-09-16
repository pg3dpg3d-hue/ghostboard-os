#!/usr/bin/env python3
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
import system_health as health

class HealthTests(unittest.TestCase):
    def test_missing_optional_tools_are_not_fatal(self):
        with patch.object(health, 'STOP', Mock(exists=Mock(return_value=False))), patch.object(health, '_thermal', return_value={'status':'unavailable','ok':True,'available':False,'hottest_celsius':None}), patch.object(health, '_command') as cmd:
            cmd.side_effect=lambda command, timeout: {'status':'ok','ok':True,'available':True,'data':[]} if 'doctor' in command else {'status':'unavailable','ok':True,'available':False}
            report=health.snapshot(.1)
        self.assertEqual(report['overall'], 'ok')
    def test_doctor_failure_degrades_snapshot(self):
        def probe(command, timeout):
            return {'status':'degraded','ok':False,'available':True,'reason':'bad'} if 'doctor' in command else {'status':'ok','ok':True,'available':True}
        with patch.object(health, 'STOP', Mock(exists=Mock(return_value=False))), patch.object(health, '_command', side_effect=probe):
            report=health.snapshot(.1)
        self.assertEqual(report['overall'], 'degraded')
    def test_stop_is_read_once_and_consistent(self):
        with patch.object(health, 'STOP', Mock(exists=Mock(return_value=True))) as stop_path, patch.object(health, '_command', return_value={'status':'ok','ok':True,'available':True}):
            report=health.snapshot(.1)
        stop_path.exists.assert_called_once()
        self.assertTrue(report['agent_stopped']); self.assertTrue(report['probes']['stop']['stopped'])
    def test_timeout_is_clamped(self):
        seen=[]
        def probe(command, timeout): seen.append(timeout); return {'status':'ok','ok':True,'available':True}
        with patch.object(health, 'STOP', Mock(exists=Mock(return_value=False))), patch.object(health, '_command', side_effect=probe): health.snapshot(999)
        self.assertEqual(set(seen), {10.0})
    def test_format_text(self):
        report={'overall':'partial','probes':{'x':{'status':'degraded','ok':False,'available':True,'reason':'oops'}}}
        self.assertIn('oops', health.format_text(report))

if __name__ == '__main__': unittest.main()
