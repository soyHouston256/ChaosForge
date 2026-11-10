import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from backend import Demo
from controller import Controller
from faults import CATALOG
from server import OBSERVER_ROUTES, make_handler


def request(url, body=None, headers=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Servers:
    """One controller behind two ports, as in production: observer and admin."""

    def __init__(self, controller):
        self.servers, self.threads, self.urls = [], [], {}
        for role in ('observer', 'admin'):
            server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(controller, role))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            self.servers.append(server)
            self.threads.append(thread)
            self.urls[role] = 'http://127.0.0.1:' + str(server.server_port)

    def close(self):
        for server, thread in zip(self.servers, self.threads):
            server.shutdown()
            server.server_close()
            thread.join()


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.controller = Controller(self.temp.name + '/db', Demo())
        self.ports = Servers(self.controller)
        self.url = self.ports.urls['admin']
        self.observer = self.ports.urls['observer']
        with urllib.request.urlopen(self.url + '/api/state') as r:
            self.state = json.load(r)

    def tearDown(self):
        self.ports.close()
        self.controller.db.close()
        self.temp.cleanup()

    def post(self, body, headers, base=None):
        return request((base or self.url) + '/api/start', body, headers)[0]

    def test_csrf_origin_and_host(self):
        body = {'service':'cartservice','duration':30}
        self.assertEqual(self.post(body, {}), 403)
        h = {'X-ChaosForge-Token':self.state['csrf'], 'Origin':'https://evil.example'}
        self.assertEqual(self.post(body, h), 403)
        h = {'X-ChaosForge-Token':self.state['csrf'], 'Host':'evil.example'}
        self.assertEqual(self.post(body, h), 403)
        self.assertIsNone(self.controller.active())

    def test_strict_fields_and_working_route(self):
        h = {'X-ChaosForge-Token':self.state['csrf'], 'Origin':self.url}
        self.assertEqual(self.post({'service':'cartservice','duration':30,'command':'echo nope'},h),409)
        self.assertEqual(self.post({'service':'cartservice','duration':30},h),200)
        self.assertEqual(self.post({'service':'paymentservice','duration':30},h),409)
        self.assertIn('simulados', self.state['mode'])
        self.controller.restore()
        self.controller.tick()
        self.assertIsNone(self.controller.active())


class PortIsolationTests(unittest.TestCase):
    """Ground truth (state, evidence, panel, POSTs) only on the admin port."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.controller = Controller(self.temp.name + '/db', Demo())
        self.ports = Servers(self.controller)
        self.admin, self.observer = self.ports.urls['admin'], self.ports.urls['observer']
        status, body = request(self.admin + '/api/state')
        self.assertEqual(status, 200)
        self.csrf = json.loads(body)['csrf']
        status, body = request(self.admin + '/api/start', {'service': 'cartservice', 'duration': 30},
                               {'X-ChaosForge-Token': self.csrf, 'Origin': self.admin})
        self.assertEqual(status, 200)
        self.ident = json.loads(body)['id']
        now = self.controller.clock()
        self.window = '/api/observations?start=%s&end=%s' % (now - 60, now + 60)

    def tearDown(self):
        self.ports.close()
        self.controller.restore()
        self.controller.db.close()
        self.temp.cleanup()

    def test_route_matrix(self):
        evidence = '/api/evidence/' + self.ident
        expected = {
            '/healthz': (200, 200),
            self.window: (200, 200),
            '/api/state': (200, 404),
            evidence: (200, 404),
            '/api/evidence/unknown': (404, 404),
            '/': (200, 404),
            '/app.js': (200, 404),
            '/style.css': (200, 404),
            '/nope': (404, 404),
        }
        for path, (admin, observer) in expected.items():
            with self.subTest(path=path):
                self.assertEqual(request(self.admin + path)[0], admin)
                status, body = request(self.observer + path)
                self.assertEqual(status, observer)
                if status == 404:
                    # Same opaque answer for real and unknown routes: no route discovery.
                    self.assertEqual(json.loads(body), {'error': 'Ruta desconocida.'})

    def test_observer_rejects_every_post_even_with_valid_token(self):
        headers = {'X-ChaosForge-Token': self.csrf, 'Origin': self.observer}
        self.controller.restore()
        self.controller.tick()
        for path, body in (('/api/start', {'service': 'cartservice', 'duration': 30}), ('/api/restore', {})):
            with self.subTest(path=path):
                self.assertEqual(request(self.observer + path, body, headers)[0], 404)
        self.assertIsNone(self.controller.active())

    def test_observer_keeps_localhost_guard(self):
        status, _ = request(self.observer + self.window, headers={'Host': 'evil.example'})
        self.assertEqual(status, 403)

    def test_observer_routes_are_exactly_the_tider_surface(self):
        self.assertEqual(OBSERVER_ROUTES, {'/healthz', '/api/observations'})
        with self.assertRaises(ValueError):
            make_handler(self.controller, 'both')


FORBIDDEN_KEYS = {'id', 'experiment', 'experiments', 'mechanism', 'cause', 'target', 'targets', 'actor', 'original',
                  'original_replicas', 'restored', 'rollback', 'events', 'history', 'active', 'state', 'result',
                  'effect_at', 'deadline', 'duration', 'parameters', 'issue', 'csrf', 'evidence', 'started', 'finished'}


def walk(value, keys, strings):
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(key)
            walk(item, keys, strings)
    elif isinstance(value, list):
        for item in value:
            walk(item, keys, strings)
    elif isinstance(value, str):
        strings.append(value)


class ObserverPayloadTests(unittest.TestCase):
    """Observer responses during real (demo) experiments never name them."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 1000.
        self.backend = Demo()
        self.controller = Controller(self.temp.name + '/db', self.backend, lambda: self.now)
        self.ports = Servers(self.controller)

    def tearDown(self):
        self.ports.close()
        self.controller.db.close()
        self.temp.cleanup()

    def sample(self, seconds=3):
        self.now += seconds
        self.controller.observe()
        self.controller.tick()

    def test_no_ground_truth_fields_in_observer_payload(self):
        idents = []
        for _ in range(5):
            self.sample()
        start = self.now
        for kind in ('wrong_port', 'latency', 'cpu_limit'):
            idents.append(self.controller.start('cartservice', 120, kind))
            for _ in range(26):
                self.sample()
            self.now = self.controller.active()['effect_at'] + 120
            self.controller.tick()
            for _ in range(30):
                self.sample()
            self.assertIsNone(self.controller.active())
        idents.append(self.controller.start('cartservice', 30))
        for _ in range(3):
            self.sample()
        self.assertEqual(len(set(idents)), 4)
        status, body = request('%s/api/observations?start=%s&end=%s' % (self.ports.urls['observer'], start, self.now + 1))
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertGreater(len(payload['observations']), 100)
        keys, strings = set(), []
        walk(payload, keys, strings)
        self.assertEqual(keys & FORBIDDEN_KEYS, set())
        raw = body.decode()
        for ident in idents:
            self.assertNotIn(ident, raw)
        for kind, item in CATALOG.items():
            for marker in (kind, item['id'], item['label']):
                self.assertNotIn(marker, raw)
        self.assertNotIn('scale_zero', raw)
        self.assertNotIn('CF-0', raw)
        # No ChaosForge labels/annotations (chaosforge.<x>/... or chaosforge/...).
        self.assertFalse([s for s in strings if s.startswith(('chaosforge.', 'chaosforge/'))])
        self.assertFalse([k for k in keys if 'chaosforge' in k.lower()])
        # Known residual (design P9): the configured destination may be the in-cluster
        # proxy host, the same value the Cartographer reads from the Deployment spec.
        addresses = {o['configuration']['redis_address'] for o in payload['observations'] if 'configuration' in o}
        self.assertLessEqual(addresses, {'redis-cart:6379', 'redis-cart:6380', 'chaosforge-proxy:6379'})


if __name__ == '__main__':
    unittest.main()
