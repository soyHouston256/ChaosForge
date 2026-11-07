import copy
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from backend import Demo, Kubernetes
from controller import Controller, Conflict, Rejected
from faults import AdmissionChanged, Faults


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = self.temp.name + '/state.db'
        self.now = 1000.
        self.backend = Demo()
        self.c = Controller(self.path, self.backend, lambda: self.now)
        for _ in range(3):
            self.sample()

    def tearDown(self):
        self.c.db.close()
        self.temp.cleanup()

    def sample(self, seconds=3):
        self.now += seconds
        self.c.observe()
        self.c.tick()

    def test_three_distinct_mechanisms_effect_and_recovery(self):
        for kind in ('wrong_port', 'latency', 'cpu_limit'):
            with self.subTest(kind=kind):
                for _ in range(5):
                    self.sample()
                self.c.start('cartservice', 120, kind)
                for _ in range(26):
                    self.sample()
                active = self.c.active()
                self.assertEqual(active['state'], 'effect_observed')
                if kind == 'latency':
                    self.assertEqual(self.backend.synthetic_sample(self.now)['http'][0]['status'], 200)
                self.now = active['effect_at'] + 120
                self.c.tick()
                for _ in range(30):
                    self.sample()
                self.assertIsNone(self.c.active())
                self.assertEqual(self.c.snapshot()['history'][0]['result'], 'effect_observed')
                evidence = self.c.evidence(self.c.snapshot()['history'][0]['id'])
                self.assertTrue(any(e['kind'] == 'observation' and e['data'].get('cpu_throttling') for e in evidence['events']))

    def test_external_scale_change_preserved_even_after_restart(self):
        self.c.start('cartservice', 30)
        self.backend.replicas['cartservice'] = 5
        self.now += 31
        self.c.tick()
        self.assertEqual(self.backend.replicas['cartservice'], 5)
        self.assertEqual(self.c.active()['state'], 'conflict')
        self.c.db.close()
        self.c = Controller(self.path, self.backend, lambda: self.now)
        self.c.tick()
        self.assertEqual(self.backend.replicas['cartservice'], 5)

    def test_snapshot_before_uncertain_write_and_restart(self):
        apply = self.backend.faults.apply
        def lost_reply(plan):
            with sqlite3.connect(self.path) as db:
                stored = json.loads(db.execute('SELECT plan FROM experiments').fetchone()[0])
                self.assertEqual(stored['original']['address'], 'redis-cart:6379')
            apply(plan)
            raise TimeoutError()
        self.backend.faults.apply = lost_reply
        self.c.start('cartservice', 120, 'wrong_port')
        self.assertEqual(self.c.active()['state'], 'restoring')
        self.c.db.close()
        self.c = Controller(self.path, self.backend, lambda: self.now)
        for _ in range(10):
            self.sample()
        self.assertIsNone(self.c.active())
        self.assertEqual(self.c.snapshot()['history'][0]['result'], 'write_uncertain')

    def test_no_effect_expires_even_with_missing_telemetry(self):
        self.c.start('cartservice', 120, 'latency')
        self.now += 181
        self.c.tick()
        self.assertEqual(self.c.active()['result'], 'effect_not_observed')
        self.assertEqual(self.backend.faults.toxics, {})
        self.assertEqual(self.c.active()['state'], 'verifying_recovery')
        self.now += 181
        self.c.tick()
        self.assertEqual(self.c.active()['state'], 'recovery_unverified')
        with self.assertRaises(Rejected):
            self.c.start('paymentservice', 30)

    def test_foreign_config_survives_repeated_restore(self):
        self.c.start('cartservice', 120, 'wrong_port')
        self.backend.faults.values['wrong_port'] = {'address': 'redis-cart:6390'}
        for _ in range(2):
            self.c.restore()
            self.c.tick()
            self.assertEqual(self.c.active()['state'], 'conflict')
        self.assertEqual(self.backend.faults.values['wrong_port']['address'], 'redis-cart:6390')

    def test_public_observer_has_no_experiment_truth(self):
        self.c.start('cartservice', 120, 'wrong_port')
        self.sample()
        result = self.c.operational_evidence(1000, self.now + 1)
        serialized = json.dumps(result)
        for forbidden in ('wrong_port', 'CF-001', 'original', 'toxic', 'experiment', 'effect_pending'):
            self.assertNotIn(forbidden, serialized)
        self.assertIn('redis-cart:6380', serialized)  # legitimate operational state
        for start, end in [(float('nan'), 10), (0, float('inf')), (20, 10)]:
            with self.assertRaises(Rejected):
                self.c.operational_evidence(start, end)

    def test_strict_parameters_and_baseline(self):
        for kind, params in [('wrong_port', {'port': 22}), ('latency', {'latency_ms': True}), ('cpu_limit', {'millicores': 1})]:
            with self.assertRaises(Rejected):
                self.c.start('cartservice', 120, kind, params)
        with self.assertRaises(Rejected):
            self.c.start('paymentservice', 120, 'cpu_limit')
        self.now += 70
        with self.assertRaises(Rejected):
            self.c.start('cartservice', 120, 'latency')
        self.assertIsNone(self.c.active())

    def test_cpu_requires_limitation_degradation_and_fresh_samples(self):
        from experiments import effect
        self.c.start('cartservice', 120, 'cpu_limit')
        plan = json.loads(self.c.active()['plan'])
        plan['ready_at'] = self.now
        sample = self.backend.synthetic_sample(self.now + 65)
        self.assertTrue(effect(plan, sample))
        sample['http'][0]['elapsed_ms'] = 20
        self.assertFalse(effect(plan, sample))
        sample['http'][0]['elapsed_ms'] = 300
        sample['cpu_throttling']['series'][0]['sample_time'] = self.now - 100
        self.assertFalse(effect(plan, sample))
        sample['cpu_throttling']['coverage'] = 'unavailable'
        self.assertFalse(effect(plan, sample))

    def test_cpu_admission_change_reconciles_without_credit(self):
        self.c.start('cartservice', 120, 'cpu_limit')
        original = self.backend.faults.matches
        def changed(*args, **kwargs):
            raise AdmissionChanged('admitted a different limit')
        self.backend.faults.matches = changed
        self.sample()
        self.assertEqual(self.c.active()['state'], 'restoring')
        self.assertEqual(self.c.active()['result'], 'admission_changed')
        self.backend.faults.matches = original
        for _ in range(30):
            self.sample()
        self.assertIsNone(self.c.active())
        self.assertEqual(self.backend.faults.values['cpu_limit']['limit'], '300m')


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.obj = {'metadata': {'uid': 'u', 'resourceVersion': '1', 'generation': 2},
            'spec': {'replicas': 1, 'template': {'spec': {'containers': [
                {'name': 'server', 'image': 'us-central1-docker.pkg.dev/google-samples/microservices-demo/cartservice:v0.10.4',
                 'env': [{'name': 'REDIS_ADDR', 'value': 'redis-cart:6379'}, {'name': 'UNRELATED', 'valueFrom': {'secretKeyRef': {'name': 'not-read', 'key': 'x'}}}],
                 'resources': {'requests': {'cpu': '200m', 'memory': '205Mi'}, 'limits': {'cpu': '300m', 'memory': '205Mi'}}}]}}},
            'status': {'observedGeneration': 2, 'replicas': 2, 'updatedReplicas': 1, 'availableReplicas': 1, 'readyReplicas': 1}}
        self.k = Kubernetes.__new__(Kubernetes)
        self.patches = []
        def request(path, body=None, method=None):
            if method == 'POST':
                return {'status': {'allowed': True}}
            if body is not None:
                before = copy.deepcopy(self.obj)
                self.patches.append(body)
                for op in body:
                    tokens = op['path'].strip('/').split('/')
                    current = self.obj
                    for token in tokens[:-1]:
                        current = current[int(token)] if isinstance(current, list) else current[token]
                    key = int(tokens[-1]) if isinstance(current, list) else tokens[-1]
                    if op['op'] == 'test':
                        if current[key] != op['value']:
                            raise RuntimeError('Atomic precondition failed')
                    else:
                        current[key] = op['value']
                self.obj['metadata']['generation'] += 1
                if '?dryRun=All' in path:
                    preview = copy.deepcopy(self.obj)
                    self.obj = before
                    return preview
            return copy.deepcopy(self.obj)
        self.k.request = request
        self.k.pod_inventory = lambda service: [{'pod': 'cartservice-current', 'uid': 'pod-uid',
            'containers': copy.deepcopy(self.obj['spec']['template']['spec']['containers'])}]
        self.f = Faults(self.k, ['wrong_port', 'cpu_limit'])

    def test_old_ready_pod_does_not_prove_rollout(self):
        self.assertFalse(self.k.get('cartservice')['rolled_out'])

    def test_field_patch_preserves_unrelated_and_secret_refs(self):
        original = copy.deepcopy(self.obj['spec']['template']['spec']['containers'][0]['env'][1])
        plan = self.f.prepare('wrong_port', {}, 'run')
        self.assertNotIn('not-read', json.dumps(plan))
        plan = self.f.apply(plan)
        self.f.restore(plan)
        self.f.restore(plan)
        self.assertEqual(len(self.patches), 2)
        self.assertEqual(self.obj['spec']['template']['spec']['containers'][0]['env'][1], original)

    def test_cpu_rollback_preserves_other_resource_changes(self):
        plan = self.f.apply(self.f.prepare('cpu_limit', {}, 'run'))
        resources = self.obj['spec']['template']['spec']['containers'][0]['resources']
        resources['limits']['memory'] = '300Mi'
        self.f.restore(plan)
        self.assertEqual(resources['limits'], {'cpu': '300m', 'memory': '300Mi'})
        self.assertEqual(resources['requests']['cpu'], '200m')

    def test_changed_field_not_overwritten(self):
        plan = self.f.apply(self.f.prepare('wrong_port', {}, 'run'))
        self.obj['spec']['template']['spec']['containers'][0]['env'][0]['value'] = 'redis-cart:6390'
        with self.assertRaises(Conflict):
            self.f.restore(plan)
        self.assertEqual(len(self.patches), 1)

    def test_cpu_dry_run_preserves_original_before_persisted_execution(self):
        self.f.prepare('cpu_limit', {}, 'run')
        resources = self.obj['spec']['template']['spec']['containers'][0]['resources']
        self.assertEqual(resources['limits']['cpu'], '300m')
        self.assertEqual(resources['requests']['cpu'], '200m')

    def test_cpu_rejects_unexpected_resources_on_actual_pod(self):
        self.k.pod_inventory = lambda service: [{'pod': 'cartservice-current', 'containers': [
            {'name': 'server', 'resources': {'requests': {'cpu': '200m'}, 'limits': {'cpu': '250m'}}}]}]
        with self.assertRaises(AdmissionChanged):
            self.f.prepare('cpu_limit', {}, 'run')
        self.assertEqual(self.patches, [])
