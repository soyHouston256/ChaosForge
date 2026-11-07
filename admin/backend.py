import json
import os
import ssl
import time
import urllib.error
import urllib.request
import urllib.parse
from controller import SERVICES, Rejected, Conflict


class Kubernetes:
    mode = 'GKE · datos reales'

    def __init__(self):
        base = '/var/run/secrets/kubernetes.io/serviceaccount/'
        self.token_path = base + 'token'
        self.context = ssl.create_default_context(cafile=base + 'ca.crt')
        self.api = 'https://kubernetes.default.svc'
        self.namespace = 'boutique'  # Deliberately not supplied by the browser.
        self.frontend = 'http://frontend.boutique.svc.cluster.local'
        from faults import Faults
        self.faults = Faults(self)

    def request(self, path, body=None, method=None):
        with open(self.token_path) as token:
            headers = {'Authorization': 'Bearer ' + token.read().strip()}
        if body is not None:
            headers['Content-Type'] = 'application/json' if method == 'POST' else 'application/json-patch+json'
        req = urllib.request.Request(self.api + path, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     method=method or ('PATCH' if body is not None else 'GET'))
        try:
            with urllib.request.urlopen(req, context=self.context, timeout=4) as result:
                return json.load(result)
        except urllib.error.HTTPError as exc:
            raise RuntimeError('API Kubernetes respondió HTTP ' + str(exc.code)) from None

    def path(self, service):
        if service not in SERVICES:
            raise Rejected('Servicio no autorizado.')
        return '/apis/apps/v1/namespaces/boutique/deployments/' + service

    def get(self, service):
        obj = self.request(self.path(service))
        status = obj.get('status', {})
        current = status.get('observedGeneration', 0) >= obj['metadata']['generation']
        return {'uid': obj['metadata']['uid'], 'replicas': obj['spec']['replicas'],
                'ready': status.get('readyReplicas', 0) if current else 0,
                'pods': status.get('replicas', 0), 'observed': current,
                'generation': obj['metadata']['generation'],
                'rolled_out': current and all(status.get(k, 0) == obj['spec']['replicas']
                    for k in ('replicas', 'updatedReplicas', 'availableReplicas', 'readyReplicas'))}

    def autoscaled(self, service):
        items = self.request('/apis/autoscaling/v2/namespaces/boutique/horizontalpodautoscalers').get('items', [])
        return any(x['spec']['scaleTargetRef'].get('kind') == 'Deployment' and x['spec']['scaleTargetRef']['name'] == service for x in items)

    def pod_inventory(self, service):
        dep = self.request(self.path(service))
        labels = dep['spec']['selector'].get('matchLabels', {})
        if not labels:
            raise Rejected('Selector vacío.')
        query = '?' + urllib.parse.urlencode({'labelSelector': ','.join(k + '=' + v for k, v in labels.items())})
        replicas = self.request('/apis/apps/v1/namespaces/boutique/replicasets' + query)
        pods = self.request('/api/v1/namespaces/boutique/pods' + query)
        if replicas.get('metadata', {}).get('continue') or pods.get('metadata', {}).get('continue'):
            raise Rejected('Lectura de identidad incompleta.')
        owned = {r['metadata']['uid'] for r in replicas.get('items', []) if any(
            o.get('uid') == dep['metadata']['uid'] and o.get('controller') for o in r['metadata'].get('ownerReferences', []))}
        return [{'pod': p['metadata']['name'], 'uid': p['metadata']['uid'],
                 'containers': [{'name': c['name'], 'resources': c.get('resources', {}), 'image': c['image']}
                                for c in p['spec']['containers']]}
                for p in pods.get('items', []) if not p['metadata'].get('deletionTimestamp') and any(
                    o.get('uid') in owned and o.get('controller') for o in p['metadata'].get('ownerReferences', []))]

    def owned_pods(self, service):
        return [p['pod'] for p in self.pod_inventory(service)]

    def compare_scale(self, service, replicas, uid, expected):
        return self.scale(service, replicas, uid, expected)

    def scale(self, service, replicas, uid, expected=None):
        path = self.path(service) + '/scale'
        current = self.request(path)
        if current['metadata']['uid'] != uid:
            raise Conflict('La identidad del Deployment cambió; restauración requiere revisión del operador.')
        if expected is not None and current['spec']['replicas'] != expected:
            raise Conflict('Réplicas modificadas por otro actor; no se sobrescribirá su cambio.')
        patch = [
            {'op': 'test', 'path': '/metadata/uid', 'value': uid},
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': current['metadata']['resourceVersion']},
        ]
        if expected is not None:
            patch.append({'op': 'test', 'path': '/spec/replicas', 'value': expected})
        self.request(path, patch + [{'op': 'replace', 'path': '/spec/replicas', 'value': replicas}])

    def probe(self):
        results = []
        for path in ('/', '/cart'):
            started = time.monotonic()
            try:
                with urllib.request.urlopen(self.frontend + path, timeout=3) as response:
                    status = response.status
            except urllib.error.HTTPError as exc:
                status = exc.code
            except (OSError, TimeoutError):
                status = None
            results.append({'path': path, 'status': status, 'elapsed_ms': round((time.monotonic() - started) * 1000, 2), 'source': 'HTTP interno a frontend; no valida checkout/pagos'})
        return results


class Demo:
    mode = 'DEMO LOCAL · datos simulados · sin acceso a GCP'

    def __init__(self):
        self.replicas = {name: 1 for name in SERVICES}
        from faults import DemoFaults
        self.faults = DemoFaults(self)

    def get(self, service):
        return {'uid': 'demo-' + service, 'replicas': self.replicas[service], 'ready': self.replicas[service], 'pods': self.replicas[service], 'observed': True, 'rolled_out': True}

    def autoscaled(self, service):
        return False

    def scale(self, service, replicas, uid):
        if uid != 'demo-' + service:
            raise Rejected('Identidad incorrecta.')
        self.replicas[service] = replicas

    def compare_scale(self, service, replicas, uid, expected):
        if self.replicas[service] != expected:
            raise Conflict('Réplicas modificadas por otro actor; no se sobrescribirá su cambio.')
        self.scale(service, replicas, uid)

    def probe(self):
        return [{'path': p, 'status': 200 if all(self.replicas.values()) else 500, 'source': 'Simulación local, no es una solicitud HTTP real'} for p in ('/', '/cart')]

    def synthetic_sample(self, at):
        from faults import TARGET, DIRECT
        address = self.faults.values['wrong_port']['address']
        wrong = address != DIRECT
        cpu = self.faults.values['cpu_limit']
        limited = cpu['limit'] != '300m'
        delay = sum(v['latency_ms'] for v in self.faults.toxics.values())
        return {'at': at, 'captured_at': at, 'service': TARGET, 'source': 'demo', 'synthetic': True,
                'configuration': {'uid': 'demo-' + TARGET, 'generation': 1, 'container': 'server',
                                  'image': 'synthetic', 'redis_address': address, 'cpu': dict(cpu)},
                'deployment': self.get(TARGET), 'coverage': 'complete',
                'http': [{'path': '/cart', 'status': 500 if wrong else 200,
                          'elapsed_ms': 1000 if wrong else 20 + delay + (250 if limited else 0)}],
                'dependency': {'operation': 'Redis PING (synthetic)', 'success': not wrong,
                               'elapsed_ms': 1000 if wrong else 2 + delay},
                'cpu_throttling': {'coverage': 'complete', 'window_seconds': 60, 'queried_at': at,
                    'series': [{'pod': 'demo-cartservice', 'container': 'server', 'sample_time': at,
                                'ratio': .6 if limited else .01}]}}
