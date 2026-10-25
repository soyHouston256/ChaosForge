import json
import os
import ssl
import urllib.error
import urllib.request
from controller import SERVICES, Rejected


class Kubernetes:
    mode = 'GKE · datos reales'

    def __init__(self):
        base = '/var/run/secrets/kubernetes.io/serviceaccount/'
        self.token_path = base + 'token'
        self.context = ssl.create_default_context(cafile=base + 'ca.crt')
        self.api = 'https://kubernetes.default.svc'
        self.namespace = 'boutique'  # Deliberately not supplied by the browser.
        self.frontend = 'http://frontend.boutique.svc.cluster.local'

    def request(self, path, body=None):
        with open(self.token_path) as token:
            headers = {'Authorization': 'Bearer ' + token.read().strip()}
        if body is not None:
            headers['Content-Type'] = 'application/json-patch+json'
        req = urllib.request.Request(self.api + path, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     method='PATCH' if body is not None else 'GET')
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
                'pods': status.get('replicas', 0), 'observed': current}

    def autoscaled(self, service):
        items = self.request('/apis/autoscaling/v2/namespaces/boutique/horizontalpodautoscalers').get('items', [])
        return any(x['spec']['scaleTargetRef'].get('kind') == 'Deployment' and x['spec']['scaleTargetRef']['name'] == service for x in items)

    def scale(self, service, replicas, uid):
        path = self.path(service) + '/scale'
        current = self.request(path)
        if current['metadata']['uid'] != uid:
            raise Rejected('La identidad del Deployment cambió; restauración requiere revisión del operador.')
        self.request(path, [
            {'op': 'test', 'path': '/metadata/uid', 'value': uid},
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': current['metadata']['resourceVersion']},
            {'op': 'replace', 'path': '/spec/replicas', 'value': replicas},
        ])

    def probe(self):
        results = []
        for path in ('/', '/cart'):
            try:
                with urllib.request.urlopen(self.frontend + path, timeout=3) as response:
                    status = response.status
            except urllib.error.HTTPError as exc:
                status = exc.code
            except (OSError, TimeoutError):
                status = None
            results.append({'path': path, 'status': status, 'source': 'HTTP interno a frontend; no valida checkout/pagos'})
        return results


class Demo:
    mode = 'DEMO LOCAL · datos simulados · sin acceso a GCP'

    def __init__(self):
        self.replicas = {name: 1 for name in SERVICES}

    def get(self, service):
        return {'uid': 'demo-' + service, 'replicas': self.replicas[service], 'ready': self.replicas[service], 'pods': self.replicas[service], 'observed': True}

    def autoscaled(self, service):
        return False

    def scale(self, service, replicas, uid):
        if uid != 'demo-' + service:
            raise Rejected('Identidad incorrecta.')
        self.replicas[service] = replicas

    def probe(self):
        return [{'path': p, 'status': 200 if all(self.replicas.values()) else 500, 'source': 'Simulación local, no es una solicitud HTTP real'} for p in ('/', '/cart')]
