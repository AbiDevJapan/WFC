"""Step 3 CLI end-to-end tests, including independent profile hash verification."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WORLD=ROOT/'configs'/'warehouse_demo.json'
PROFILE=ROOT/'configs'/'temporal_profile_demo.json'


def run(*args):
    env=dict(os.environ,PYTHONPATH=str(ROOT/'src'))
    return subprocess.run([sys.executable,'-m',*map(str,args)],env=env,
                          cwd=ROOT, capture_output=True, text=True)


class CliTests(unittest.TestCase):
    def test_profile_forward_backward_and_replay(self):
        with tempfile.TemporaryDirectory() as d:
            a,b=Path(d)/'a',Path(d)/'b'
            for folder,days in ((a,(0,30,180,365)),(b,(365,180,30,0))):
                r=run('temporal_wfc.simulate',WORLD,'--temporal-profile',PROFILE,
                      '--days',*days,'--output-dir',folder)
                self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual((a/'event_ledger.json').read_bytes(),
                             (b/'event_ledger.json').read_bytes())
            for name in ('0000.000','0030.000','0180.000','0365.000'):
                fname=f'world_day_{name}.json'
                self.assertEqual((a/fname).read_bytes(),(b/fname).read_bytes())
            v=run('temporal_wfc.verify',WORLD,a,'--temporal-profile',PROFILE)
            self.assertEqual(v.returncode,0,v.stderr)
            self.assertIn('VERIFIED 4 snapshots',v.stdout)
            fail=run('temporal_wfc.verify',WORLD,a)
            self.assertNotEqual(fail.returncode,0)
            self.assertIn('--temporal-profile',fail.stderr)

    def test_corrupted_profile_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/'out'
            r=run('temporal_wfc.simulate',WORLD,'--temporal-profile',PROFILE,
                  '--days',30,'--output-dir',output)
            self.assertEqual(r.returncode,0,r.stderr)
            ledger=output/'event_ledger.json'
            data=json.loads(ledger.read_text())
            data['temporal_profile_sha256']='0'*64
            ledger.write_text(json.dumps(data))
            fail=run('temporal_wfc.verify',WORLD,output,'--temporal-profile',PROFILE)
            self.assertIn('hash mismatch',fail.stderr)


if __name__=='__main__':
    unittest.main()
