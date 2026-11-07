import io
import json
import os
import sys
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from backend import Kubernetes
from observations import cpu_sample


class CPUObservationTests(unittest.TestCase):
    def test_pod_identity_uses_owner_chain_not_name_prefix(self):
        k = Kubernetes.__new__(Kubernetes)
        def request(path):
            if '/deployments/' in path:
                return {'metadata': {'uid': 'deployment-owner'}, 'spec': {'selector': {'matchLabels': {'app': 'cartservice'}}}}
            if '/replicasets?' in path:
                return {'items': [{'metadata': {'uid': uid, 'ownerReferences': [{'uid': owner, 'controller': True}]}}
                    for uid, owner in [('owned-rs', 'deployment-owner'), ('other-rs', 'another-deployment')]]}
            return {'items': [{'metadata': {'uid': 'uid-' + name, 'name': name,
                       'ownerReferences': [{'uid': owner, 'controller': True}]},
                       'spec': {'containers': [{'name': 'server', 'image': 'test', 'resources': {'limits': {'cpu': '50m'}}}]}}
                    for name, owner in [('cartservice-real', 'owned-rs'), ('cartservice-lookalike', 'other-rs')]]}
        k.request = request
        self.assertEqual(k.owned_pods('cartservice'), ['cartservice-real'])

    def test_metrics_bind_to_current_pods_and_preserve_freshness_and_limits(self):
        k = Kubernetes.__new__(Kubernetes)
        k.pod_inventory = lambda _: [{'pod': 'cartservice-real', 'containers': [
            {'name': 'server', 'resources': {'requests': {'cpu': '50m'}, 'limits': {'cpu': '50m'}}}]}]
        queries = []
        now = time.time()
        def urlopen(req, timeout):
            self.assertLessEqual(timeout, 3)
            if req.full_url.startswith('http://metadata.google.internal/'):
                return io.BytesIO(json.dumps({'access_token': 'test-token-not-real'}).encode())
            query = parse_qs(urlsplit(req.full_url).query)['query'][0]
            queries.append(query)
            value = str(now - 10) if 'timestamp(' in query else '.4'
            return io.BytesIO(json.dumps({'status': 'success', 'data': {'result': [
                {'metric': {'pod': 'cartservice-real', 'container': 'server'}, 'value': [now, value]}]}}).encode())
        with patch('observations.urllib.request.urlopen', urlopen):
            result = cpu_sample(k)
        self.assertEqual(result['coverage'], 'complete')
        self.assertEqual(result['series'][0]['ratio'], .4)
        self.assertEqual(result['series'][0]['effective_resources']['limits']['cpu'], '50m')
        self.assertTrue(all('namespace="boutique"' in q and 'pod=~"cartservice-real"' in q for q in queries))
        self.assertNotIn('test-token', json.dumps(result))
