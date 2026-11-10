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
    def test_manifest_targets_match_runtime_allowlist(self):
        import re
        from controller import SERVICES
        manifest = (ROOT / 'admin/k8s/admin.yaml').read_text()
        lists = re.findall(r'resourceNames:\s*\[([^]]+)\]', manifest)
        self.assertEqual(len(lists), 2)
        for names in lists:
            self.assertEqual({name.strip() for name in names.split(',')}, set(SERVICES))

    def test_manifest_separates_observer_and_admin_ports(self):
        manifest = (ROOT / 'admin/k8s/admin.yaml').read_text()
        dockerfile = (ROOT / 'admin/Dockerfile').read_text()
        self.assertIn('- name: observer\n              containerPort: 8080', manifest)
        self.assertIn('- name: admin\n              containerPort: 8081', manifest)
        self.assertIn('- name: observer\n      port: 8080\n      targetPort: observer', manifest)
        self.assertIn('- name: admin\n      port: 8081\n      targetPort: admin', manifest)
        # Probes hit the observer port, which never serves ground truth.
        self.assertEqual(manifest.count('path: /healthz\n              port: observer'), 2)
        self.assertIn('EXPOSE 8080 8081', dockerfile)
        self.assertIn('"--port", "8080", "--admin-port", "8081"', dockerfile)

    def run_fake(self, mode, admin_port='8081'):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            executable = '#!' + sys.executable + '\n'
            (p/'kubectl').write_text(executable + '''import json, os, sys, time
with open(os.environ['CALLS'], 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
args = sys.argv[1:]
if 'port-forward' in args: time.sleep(60)
if 'service' in args and any(a.startswith('jsonpath=') for a in args):
    print(os.environ['ADMIN_PORT'], end=''); sys.exit(0)
if 'get' in args:
    if os.environ['MODE']=='denied': sys.exit(42)
    if os.environ['MODE']=='active': print('deployment.apps/chaosforge-admin')
''')
            (p/'curl').write_text(executable + "import json; print(json.dumps({'active': {'id':'pending'}}))\n")
            for name in ('kubectl', 'curl'):
                (p/name).chmod(0o755)
            env = dict(os.environ, PATH=str(p)+os.pathsep+os.environ['PATH'], MODE=mode, CALLS=str(p/'calls'), ADMIN_PORT=admin_port)
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

    def test_idle_check_reads_ground_truth_on_admin_port(self):
        result, calls = self.run_fake('active')
        forward = next(call for call in calls if 'port-forward' in call)
        self.assertEqual(forward[-2:], ['18080:8080', '18081:8081'])
        self.assertIn('pending experiment', result.stderr)

    def test_idle_check_supports_previous_single_port_release(self):
        result, calls = self.run_fake('active', admin_port='')
        forward = next(call for call in calls if 'port-forward' in call)
        self.assertEqual(forward[-1], '18081:8080')
        self.assertIn('pending experiment', result.stderr)
        self.assertFalse(any('apply' in call for call in calls))

    def test_first_install_only_applies_admin_manifest(self):
        result, calls = self.run_fake('absent')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum('apply' in call for call in calls), 1)
        self.assertTrue(any('rollout' in call and 'deployment/chaosforge-admin' in call for call in calls))
        self.assertFalse(any('boutique' in call or 'scale' in call for call in calls))
