"""End-to-end archive smoke tests for Step 2's CLI and saved event replay."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / 'configs' / 'warehouse_demo.json'


def run_module(module, *args):
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT / 'src')
    return subprocess.run([sys.executable, '-m', module, *map(str, args)],
                          cwd=ROOT, env=env, text=True, capture_output=True)


class EndToEndTests(unittest.TestCase):
    def test_forward_backward_outputs_and_replay_verification(self):
        with tempfile.TemporaryDirectory() as d:
            first, second = Path(d) / 'forward', Path(d) / 'backward'
            a = run_module('temporal_wfc.simulate', DEMO, '--days', 0, 30, 180,
                           '--output-dir', first)
            b = run_module('temporal_wfc.simulate', DEMO, '--days', 180, 30, 0,
                           '--output-dir', second)
            self.assertEqual(a.returncode, 0, a.stderr)
            self.assertEqual(b.returncode, 0, b.stderr)
            self.assertEqual((first / 'event_ledger.json').read_bytes(),
                             (second / 'event_ledger.json').read_bytes())
            for day in ('0000.000', '0030.000', '0180.000'):
                name = f'world_day_{day}.json'
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
            verified = run_module('temporal_wfc.verify', DEMO, first)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertIn('VERIFIED 3 snapshots', verified.stdout)

    def test_corrupted_export_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / 'demo'
            result = run_module('temporal_wfc.simulate', DEMO, '--days', 30,
                                '--output-dir', output)
            self.assertEqual(result.returncode, 0, result.stderr)
            path = output / 'world_day_0030.000.json'
            data = json.loads(path.read_text(encoding='utf-8'))
            data['objects'][0]['pose']['x_m'] = 0.123456
            path.write_text(json.dumps(data), encoding='utf-8')
            failed = run_module('temporal_wfc.verify', DEMO, output)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn('snapshot mismatch', failed.stderr)


if __name__ == '__main__':
    unittest.main()
