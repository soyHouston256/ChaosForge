import json
import os
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from backend import Demo, Kubernetes
from controller import Controller, Rejected


class Fake(Demo):
    def __init__(self):
        super().__init__()
        self.writes = []
        self.fail_scale = False
        self.http_bad = False
        self.hpa = False
        self.before_scale = lambda: None

    def scale(self, service, replicas, uid):
        self.before_scale()
        super().scale(service, replicas, uid)
        self.writes.append((service, replicas))
        if self.fail_scale:
            raise TimeoutError('API response lost')

    def probe(self):
        if self.http_bad:
            return [{'path': '/', 'status': 500}]
        return super().probe()

    def autoscaled(self, service):
        return self.hpa


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = self.temp.name + '/state.db'
        self.now = 1000
        self.backend = Fake()
        self.controller = Controller(self.path, self.backend, lambda: self.now)

    def tearDown(self):
        self.controller.db.close()
        self.temp.cleanup()

    def test_state_committed_before_mutation(self):
        import sqlite3
        def check():
            with sqlite3.connect(self.path) as db:
                row = db.execute('SELECT original,deadline,state FROM experiments').fetchone()
                self.assertEqual(row, (1, 1060, 'injecting'))
        self.backend.before_scale = check
        self.controller.start('cartservice', 60)

    def test_concurrent_starts_only_one_writes(self):
        barrier = threading.Barrier(2)
        def attempt(service):
            barrier.wait()
            try:
                self.controller.start(service, 30)
                return True
            except Rejected:
                return False
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(attempt, service) for service in ('cartservice', 'paymentservice')]
            self.assertEqual(sum(f.result() for f in futures), 1)
        self.assertEqual(len(self.backend.writes), 1)

    def test_deadline_restores_original_only(self):
        self.backend.replicas['cartservice'] = 3
        self.controller.start('cartservice', 30)
        self.now = 1029
        self.controller.tick()
        self.assertEqual(self.backend.replicas['cartservice'], 0)
        self.now = 1030
        self.controller.tick()
        self.assertIsNone(self.controller.active())
        self.assertEqual(self.backend.writes, [('cartservice', 0), ('cartservice', 3)])
        self.assertEqual(self.backend.replicas['paymentservice'], 1)

    def test_restart_recovers_before_saved_deadline(self):
        self.controller.start('cartservice', 120)
        self.controller.db.close()
        self.controller = Controller(self.path, self.backend, lambda: self.now)
        self.assertEqual(self.controller.active()['state'], 'restoring')
        self.controller.tick()
        self.assertEqual(self.backend.replicas['cartservice'], 1)
        self.assertIsNone(self.controller.active())

    def test_ambiguous_injection_is_restored(self):
        self.backend.fail_scale = True
        self.controller.start('cartservice', 30)
        self.assertEqual(self.controller.active()['state'], 'restoring')
        self.backend.fail_scale = False
        self.controller.tick()
        self.assertEqual(self.backend.replicas['cartservice'], 1)

    def test_restoration_failure_retries_and_blocks(self):
        self.controller.start('cartservice', 30)
        self.controller.restore()
        self.backend.fail_scale = True
        self.controller.tick()
        self.assertEqual(self.controller.active()['state'], 'restoring')
        with self.assertRaises(Rejected):
            self.controller.start('paymentservice', 30)
        self.backend.fail_scale = False
        self.controller.tick()
        self.assertIsNone(self.controller.active())

    def test_pod_ready_is_not_http_recovery(self):
        self.controller.start('cartservice', 30)
        self.controller.restore()
        self.backend.http_bad = True
        self.controller.tick()
        self.assertEqual(self.controller.active()['state'], 'verifying')
        self.now += 181
        self.controller.tick()
        self.assertIn('180', self.controller.active()['issue'])
        self.backend.http_bad = False
        self.controller.tick()
        self.assertIsNone(self.controller.active())

    def test_invalid_targets_durations_and_hpa(self):
        for service, duration in [('redis-cart', 30), ('../frontend', 30), ('cartservice', True), ('cartservice', 31), ('cartservice', '30')]:
            with self.assertRaises(Rejected):
                self.controller.start(service, duration)
        self.backend.hpa = True
        with self.assertRaises(Rejected):
            self.controller.start('cartservice', 30)
        self.assertEqual(self.backend.writes, [])

    def test_unhealthy_baseline_no_mutation(self):
        self.backend.http_bad = True
        with self.assertRaises(Rejected):
            self.controller.start('cartservice', 30)
        self.assertIsNone(self.controller.active())
        self.assertEqual(self.backend.writes, [])

    def test_restore_without_owned_experiment_does_nothing(self):
        self.backend.replicas['paymentservice'] = 0
        self.controller.restore()
        self.controller.tick()
        self.assertEqual(self.backend.writes, [])
        self.assertEqual(self.backend.replicas['paymentservice'], 0)

    def test_kubernetes_uid_and_resource_version_guards(self):
        k = Kubernetes.__new__(Kubernetes)
        calls = []
        def request(path, body=None):
            calls.append((path, body))
            return {'metadata': {'uid': 'new-identity', 'resourceVersion': '17'}}
        k.request = request
        with self.assertRaises(Rejected):
            k.scale('cartservice', 1, 'old-identity')
        self.assertEqual(len(calls), 1)
        k.scale('cartservice', 1, 'new-identity')
        self.assertEqual(calls[-1][1][1], {'op':'test','path':'/metadata/resourceVersion','value':'17'})
        with self.assertRaises(Rejected):
            k.path('frontend')
