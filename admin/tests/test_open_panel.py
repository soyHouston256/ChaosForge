"""Local shell-flow checks: all cloud, Kubernetes and port-check commands are mocked."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/abrir-panel.sh'


@unittest.skipUnless(SCRIPT.exists(), 'Access script is not part of the runtime image')
class OpenPanelTests(unittest.TestCase):
    def run_mock(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root/'bin'
            binary.mkdir()
            original = root/'original-config'
            original.write_text('untouched')
            log = root/'calls'
            code = '''import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with open(os.environ['MOCK_LOG'], 'a') as f:
    f.write(json.dumps({'tool':name,'args':sys.argv[1:],'config':os.environ.get('KUBECONFIG')})+'\\n')
mode = os.environ['MOCK_MODE']
if name=='gcloud':
    if sys.argv[1:3]==['auth','list']:
        if mode!='no-auth': print('test-account')
    elif sys.argv[1:3]==['auth','print-access-token']: print('SECRET_TEST_TOKEN')
    else: pathlib.Path(os.environ['KUBECONFIG']).write_text('temporary')
if name=='python3' and mode=='occupied': sys.exit(1)
if name=='kubectl':
    print('Forwarding from 127.0.0.1:8092 -> 8080')
    if mode=='tunnel-failure': sys.exit(7)
'''
            for name in ('gcloud','kubectl','python3','gke-gcloud-auth-plugin'):
                if name=='gke-gcloud-auth-plugin' and mode=='no-plugin': continue
                file = binary/name
                file.write_text('#!'+sys.executable+'\n'+code)
                file.chmod(0o755)
            env = dict(os.environ, PATH=str(binary)+':/usr/bin:/bin', TMPDIR=str(root), KUBECONFIG=str(original), MOCK_LOG=str(log), MOCK_MODE=mode)
            result = subprocess.run(['/bin/bash',str(SCRIPT)],cwd=root,env=env,capture_output=True,text=True,timeout=5)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            self.assertEqual(original.read_text(),'untouched')
            self.assertNotIn('SECRET_TEST_TOKEN',result.stdout+result.stderr)
            self.assertEqual(list(root.glob('chaosforge-panel.*')),[])
            return result,calls

    def test_private_tunnel_from_arbitrary_directory_and_cleanup(self):
        result,calls=self.run_mock('success')
        self.assertEqual(result.returncode,0,result.stderr)
        tunnel=next(c for c in calls if c['tool']=='kubectl')
        self.assertEqual(tunnel['args'],['-n','chaosforge-system','port-forward','--address','127.0.0.1','service/chaosforge-admin','8092:8080'])
        self.assertIn('chaosforge-panel.',tunnel['config'])

    def test_no_login_blocks_cluster_access(self):
        result,calls=self.run_mock('no-auth')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('gcloud auth login',result.stderr)
        self.assertFalse(any('get-credentials' in c['args'] for c in calls))

    def test_occupied_port_blocks_cluster_access(self):
        result,calls=self.run_mock('occupied')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any('get-credentials' in c['args'] for c in calls))

    def test_tunnel_failure_still_cleans_temporary_config(self):
        result,_=self.run_mock('tunnel-failure')
        self.assertEqual(result.returncode,7)

    def test_missing_plugin_explains_installation(self):
        result,_=self.run_mock('no-plugin')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('gcloud components install gke-gcloud-auth-plugin',result.stderr)
