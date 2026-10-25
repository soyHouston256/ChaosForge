"""Exercise deployment guards with fake kubectl/curl; never contact a cluster."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
IMAGE = 'us-central1-docker.pkg.dev/tider-ops/chaosforge/chaosforge-admin@sha256:' + 'a' * 64


@unittest.skipUnless((ROOT/'scripts/deploy-admin.sh').exists(), 'Repository deployment scripts are not part of the runtime image')
class PipelineTests(unittest.TestCase):
    def run_fake(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            executable = '#!' + sys.executable + '\n'
            (p/'kubectl').write_text(executable + '''import json, os, sys, time
with open(os.environ['CALLS'], 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
args = sys.argv[1:]
if 'port-forward' in args: time.sleep(60)
if 'get' in args:
    if os.environ['MODE']=='denied': sys.exit(42)
    if os.environ['MODE']=='active': print('deployment.apps/chaosforge-admin')
''')
            (p/'curl').write_text(executable + "import json; print(json.dumps({'active': {'id':'pending'}}))\n")
            for name in ('kubectl', 'curl'):
                (p/name).chmod(0o755)
            env = dict(os.environ, PATH=str(p)+os.pathsep+os.environ['PATH'], MODE=mode, CALLS=str(p/'calls'))
            result = subprocess.run(['bash', str(ROOT/'scripts/deploy-admin.sh'), IMAGE], env=env, text=True, capture_output=True, timeout=10)
            calls = [json.loads(line) for line in (p/'calls').read_text().splitlines()]
            return result, calls

    def test_read_permission_failure_blocks_apply(self):
        result, calls = self.run_fake('denied')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any('apply' in call for call in calls))

    def test_pending_experiment_blocks_apply(self):
        result, calls = self.run_fake('active')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('pending experiment', result.stderr)
        self.assertFalse(any('apply' in call for call in calls))

    def test_first_install_only_applies_admin_manifest(self):
        result, calls = self.run_fake('absent')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum('apply' in call for call in calls), 1)
        self.assertTrue(any('rollout' in call and 'deployment/chaosforge-admin' in call for call in calls))
        self.assertFalse(any('boutique' in call or 'scale' in call for call in calls))
