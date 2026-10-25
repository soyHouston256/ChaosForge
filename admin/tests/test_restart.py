"""Process-level recovery test: SIGKILL, persistent database, fresh server."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


class RestartTests(unittest.TestCase):
    def test_sigkill_recovery_and_single_writer_lock(self):
        with tempfile.TemporaryDirectory() as data:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            command = [sys.executable, str(ROOT/'server.py'), '--demo', '--data', data, '--port', str(port)]
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            url = 'http://127.0.0.1:' + str(port)
            def state():
                with urllib.request.urlopen(url+'/api/state', timeout=1) as response:
                    return json.load(response)
            def wait_ready():
                for _ in range(80):
                    try:
                        return state()
                    except OSError:
                        time.sleep(.05)
                self.fail('Server did not start')
            try:
                initial = wait_ready()
                duplicate = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
                self.assertNotEqual(duplicate.returncode, 0)
                self.assertIn('Ya existe', duplicate.stderr.decode())
                req = urllib.request.Request(url+'/api/start', data=json.dumps({'service':'cartservice','duration':120}).encode(), headers={'X-ChaosForge-Token':initial['csrf']})
                with urllib.request.urlopen(req) as response:
                    ident = json.load(response)['id']
                self.assertIsNotNone(state()['active'])
                process.kill()
                process.wait(timeout=3)
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                recovered = wait_ready()
                for _ in range(40):
                    if recovered['active'] is None:
                        break
                    time.sleep(.1)
                    recovered = state()
                self.assertIsNone(recovered['active'])
                self.assertEqual(recovered['history'][0]['id'], ident)
                self.assertIn('restart_recovery', [e['kind'] for e in recovered['history'][0]['events']])
                self.assertEqual(recovered['history'][0]['original'], 1)
            finally:
                process.terminate()
                process.wait(timeout=5)
