"""Process-level recovery test: SIGKILL, persistent database, fresh server."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def free_ports(count):
    socks = [socket.socket() for _ in range(count)]
    try:
        for sock in socks:
            sock.bind(('127.0.0.1', 0))
        return [sock.getsockname()[1] for sock in socks]
    finally:
        for sock in socks:
            sock.close()


def status(url):
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


class RestartTests(unittest.TestCase):
    def test_two_ports_and_graceful_sigterm(self):
        with tempfile.TemporaryDirectory() as data:
            port, admin_port = free_ports(2)
            process = subprocess.Popen([sys.executable, str(ROOT/'server.py'), '--demo', '--data', data,
                                        '--port', str(port), '--admin-port', str(admin_port)],
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            observer, admin = 'http://127.0.0.1:%d' % port, 'http://127.0.0.1:%d' % admin_port
            try:
                for _ in range(80):
                    try:
                        if status(admin + '/api/state') == 200:
                            break
                    except OSError:
                        time.sleep(.05)
                else:
                    self.fail('Server did not start')
                self.assertEqual(status(observer + '/healthz'), 200)
                self.assertEqual(status(observer + '/api/state'), 404)
                self.assertEqual(status(observer + '/'), 404)
                process.send_signal(signal.SIGTERM)
                out, _ = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0)
                self.assertIn('observador http://localhost:%d' % port, out)
                self.assertIn('administración http://localhost:%d' % admin_port, out)
                for url in (observer, admin):
                    with self.assertRaises(OSError):
                        urllib.request.urlopen(url + '/healthz', timeout=1)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

    def test_same_port_for_observer_and_admin_is_refused(self):
        with tempfile.TemporaryDirectory() as data:
            result = subprocess.run([sys.executable, str(ROOT/'server.py'), '--demo', '--data', data,
                                     '--port', '18555', '--admin-port', '18555'], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('--admin-port', result.stderr)

    def test_sigkill_recovery_and_single_writer_lock(self):
        with tempfile.TemporaryDirectory() as data:
            port, admin_port = free_ports(2)
            command = [sys.executable, str(ROOT/'server.py'), '--demo', '--data', data, '--port', str(port), '--admin-port', str(admin_port)]
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            url = 'http://127.0.0.1:' + str(admin_port)
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
