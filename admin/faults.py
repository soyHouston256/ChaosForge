"""Bounded Online Boutique adapters. Browser input never selects paths or hosts."""
import copy
import json
import os
import re
import urllib.error
import urllib.request

from controller import Conflict, Rejected

CATALOG = {
    'wrong_port': {'id': 'CF-001', 'label': 'Puerto incorrecto', 'defaults': {'port': 6380}},
    'latency': {'id': 'CF-004', 'label': 'Latencia de Redis', 'defaults': {'latency_ms': 300, 'jitter_ms': 50}},
    'cpu_limit': {'id': 'CF-007', 'label': 'Límite de CPU', 'defaults': {'millicores': 50}},
}
TARGET = 'cartservice'
CONTAINER = 'server'
DIRECT = 'redis-cart:6379'
PROXY = 'chaosforge-proxy:6379'


class AdmissionChanged(Rejected):
    pass


def parameters(kind, values):
    if kind not in CATALOG or not isinstance(values, dict):
        raise Rejected('Mecanismo o parámetros inválidos.')
    result = dict(CATALOG[kind]['defaults'])
    if set(values) - set(result):
        raise Rejected('Parámetros no autorizados.')
    result.update(values)
    bounds = {'port': (6380, 6380), 'latency_ms': (50, 1500), 'jitter_ms': (0, 250), 'millicores': (50, 200)}
    for name, value in result.items():
        low, high = bounds[name]
        if type(value) is not int or not low <= value <= high:
            raise Rejected('Parámetro fuera de rango: ' + name)
    if kind == 'latency' and result['jitter_ms'] > result['latency_ms']:
        raise Rejected('La variación no puede superar la latencia.')
    return result


def cpu_millis(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+(?:\.\d+)?m?', value):
        raise Rejected('Cantidad de CPU no compatible con este adaptador.')
    return float(value[:-1]) if value.endswith('m') else float(value) * 1000


def container(obj):
    matches = [(i, c) for i, c in enumerate(obj['spec']['template']['spec']['containers']) if c['name'] == CONTAINER]
    if len(matches) != 1:
        raise Rejected('No se encontró el contenedor esperado de Online Boutique.')
    return matches[0]


def owned_fields(obj, kind):
    _, c = container(obj)
    if kind == 'wrong_port':
        entries = [e for e in c.get('env', []) if e['name'] == 'REDIS_ADDR']
        if len(entries) != 1 or set(entries[0]) != {'name', 'value'}:
            raise Rejected('REDIS_ADDR debe ser un valor explícito único; no se leen Secret/ConfigMap.')
        return {'address': entries[0]['value']}
    if kind == 'cpu_limit':
        r = c.get('resources', {})
        try:
            return {'request': r['requests']['cpu'], 'limit': r['limits']['cpu']}
        except KeyError:
            raise Rejected('El adaptador requiere request y limit de CPU explícitos.') from None
    return {}


class Faults:
    def __init__(self, backend, enabled=None):
        self.backend = backend
        self.enabled = (set(os.environ.get('CHAOSFORGE_FAULTS', '').split(',')) if enabled is None else set(enabled)) & set(CATALOG)

    def catalog(self):
        return [dict(item, mechanism=key, targets=[TARGET], durations=[120, 240],
                     enabled=key in self.enabled,
                     reason='Se comprueban permisos, línea base y efecto antes de ejecutar.' if key in self.enabled else 'Preparación del laboratorio pendiente; mecanismo deshabilitado.')
                for key, item in CATALOG.items()]

    def deployment(self):
        return self.backend.request(self.backend.path(TARGET))

    def workload(self):
        obj = self.backend.request(self.backend.path('loadgenerator'))
        if obj['spec'].get('replicas', 0) < 1 or obj.get('status', {}).get('readyReplicas', 0) < 1:
            raise Rejected('CPU requiere el generador de carga disponible y calibrado.')
        return {'uid': obj['metadata']['uid'], 'replicas': obj['spec']['replicas'],
                'containers': [{'name': c['name'], 'image': c['image'],
                    'settings': {e['name']: e['value'] for e in c.get('env', [])
                                 if e['name'] in {'USERS', 'RATE'} and 'value' in e}}
                    for c in obj['spec']['template']['spec']['containers']],
                'observer_interval_seconds': 3,
                'traffic_scope': 'loadgenerator configuration plus sampled GET /cart; other traffic not measured'}

    def admitted_cpu(self, expected):
        pods = self.backend.pod_inventory(TARGET)
        if not pods:
            raise Rejected('No hay pods identificados para comprobar recursos admitidos.')
        for pod in pods:
            matches = [c for c in pod['containers'] if c['name'] == CONTAINER]
            if len(matches) != 1:
                raise Rejected('Contenedor objetivo no identificado en los pods.')
            resource = matches[0]['resources']
            if any(cpu_millis(resource.get(field, {}).get('cpu')) != cpu_millis(expected[name])
                   for name, field in [('request', 'requests'), ('limit', 'limits')]):
                raise AdmissionChanged('Los recursos admitidos del pod difieren de los parámetros previstos.')

    def check_permission(self, resource='deployments', verb='patch', name=TARGET):
        body = {'apiVersion': 'authorization.k8s.io/v1', 'kind': 'SelfSubjectAccessReview',
                'spec': {'resourceAttributes': {'namespace': 'boutique', 'group': 'apps',
                         'resource': resource, 'verb': verb, 'name': name}}}
        result = self.backend.request('/apis/authorization.k8s.io/v1/selfsubjectaccessreviews', body, method='POST')
        if not result.get('status', {}).get('allowed'):
            raise Rejected('Falta permiso de ' + verb + ' sobre ' + resource + '/' + name)

    def proxy(self, suffix='', body=None, method='GET'):
        # Fixed in-cluster service, no URL accepted from the browser or saved labels.
        req = urllib.request.Request('http://chaosforge-proxy.boutique.svc.cluster.local:8474/proxies/cart-redis' + suffix,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json'}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                raw = response.read(65536)
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise RuntimeError('Control del proxy respondió HTTP ' + str(exc.code)) from None

    def prepare(self, kind, values, ident):
        if kind not in self.enabled:
            raise Rejected('Este mecanismo no está habilitado en el laboratorio.')
        values = parameters(kind, values)
        obj = self.deployment()
        _, c = container(obj)
        if not re.fullmatch(r'us-central1-docker\.pkg\.dev/google-samples/microservices-demo/cartservice:v0\.10\.4', c['image']):
            raise Rejected('Revisión de Boutique no validada por este adaptador; revisar compatibilidad.')
        plan = {'version': 1, 'kind': kind, 'service': TARGET, 'container': CONTAINER,
                'uid': obj['metadata']['uid'], 'image': c['image'], 'parameters': values,
                'original': owned_fields(obj, kind), 'baseline_generation': obj['metadata']['generation']}
        if kind == 'wrong_port':
            address = plan['original']['address']
            if address not in (DIRECT, PROXY):
                raise Rejected('Destino de Redis distinto del adaptador validado.')
            plan['applied'] = {'address': address.rsplit(':', 1)[0] + ':' + str(values['port'])}
            self.check_permission()
        elif kind == 'cpu_limit':
            plan['workload'] = self.workload()
            original = plan['original']
            if values['millicores'] >= cpu_millis(original['limit']):
                raise Rejected('El límite debe ser menor que el actual.')
            plan['applied'] = {'limit': str(values['millicores']) + 'm',
                               'request': str(min(cpu_millis(original['request']), values['millicores'])).removesuffix('.0') + 'm'}
            self.check_permission()
            self.admitted_cpu(original)
            preview = self.patch(plan, original, plan['applied'], dry_run=True)
            if owned_fields(preview, kind) != plan['applied']:
                raise Rejected('La admisión dry-run modifica CPU; calibrar antes de inyectar.')
        else:
            if owned_fields(obj, 'wrong_port')['address'] != PROXY:
                raise Rejected('Integrar y validar previamente el proxy; el inyector no cambia la ruta.')
            self.check_permission(verb='get', name='chaosforge-proxy')
            proxy_dep = self.backend.request('/apis/apps/v1/namespaces/boutique/deployments/chaosforge-proxy')
            proxy = self.proxy()
            if not proxy or not proxy.get('enabled') or proxy.get('upstream') != DIRECT or proxy.get('toxics'):
                raise Rejected('Proxy ausente, no saludable o con perturbaciones previas.')
            plan.update(proxy_uid=proxy_dep['metadata']['uid'],
                        proxy_upstream=proxy['upstream'], proxy_listen=proxy['listen'],
                        toxic={'name': 'run-' + ident, 'type': 'latency', 'stream': 'downstream',
                               'toxicity': 1.0, 'attributes': {'latency': values['latency_ms'], 'jitter': values['jitter_ms']}})
        return plan

    def patch(self, plan, expected, desired, dry_run=False):
        obj = self.deployment()
        if obj['metadata']['uid'] != plan['uid']:
            raise Conflict('El Deployment cambió de identidad.')
        current = owned_fields(obj, plan['kind'])
        if current == desired:
            return obj
        if current != expected:
            raise Conflict('El campo fue modificado por otro actor; se conserva su valor.')
        index, c = container(obj)
        base = '/spec/template/spec/containers/' + str(index)
        patch = [{'op': 'test', 'path': '/metadata/uid', 'value': plan['uid']},
                 {'op': 'test', 'path': '/metadata/resourceVersion', 'value': obj['metadata']['resourceVersion']},
                 {'op': 'test', 'path': base + '/name', 'value': CONTAINER}]
        if plan['kind'] == 'wrong_port':
            pos = next(i for i, e in enumerate(c['env']) if e['name'] == 'REDIS_ADDR')
            path = base + '/env/' + str(pos)
            patch += [{'op': 'test', 'path': path, 'value': {'name': 'REDIS_ADDR', 'value': expected['address']}},
                      {'op': 'replace', 'path': path + '/value', 'value': desired['address']}]
        else:
            for name, field in [('request', 'requests'), ('limit', 'limits')]:
                path = base + '/resources/' + field + '/cpu'
                patch += [{'op': 'test', 'path': path, 'value': expected[name]},
                          {'op': 'replace', 'path': path, 'value': desired[name]}]
        return self.backend.request(self.backend.path(TARGET) + ('?dryRun=All' if dry_run else ''), patch)

    def check_proxy_identity(self, plan):
        dep = self.backend.request('/apis/apps/v1/namespaces/boutique/deployments/chaosforge-proxy')
        if dep['metadata']['uid'] != plan['proxy_uid']:
            raise Conflict('El proxy cambió de identidad; requiere reconciliación.')
        proxy = self.proxy()
        if not proxy or proxy.get('upstream') != plan['proxy_upstream'] or proxy.get('listen') != plan['proxy_listen']:
            raise Conflict('La ruta del proxy cambió; no se modificará.')
        return proxy

    def apply(self, plan):
        if plan['kind'] != 'latency':
            obj = self.patch(plan, plan['original'], plan['applied'])
            effective = owned_fields(obj, plan['kind'])
            # Returned admission state is preserved, including mutations by Autopilot.
            return dict(plan, applied=effective, applied_generation=obj['metadata']['generation'],
                        admission_changed=effective != plan['applied'])
        proxy = self.check_proxy_identity(plan)
        if proxy.get('toxics'):
            raise Conflict('Apareció otra perturbación en el proxy antes de aplicar.')
        self.proxy('/toxics', plan['toxic'], 'POST')
        return plan

    def matches(self, plan, restored=False):
        obj = self.deployment()
        if obj['metadata']['uid'] != plan['uid']:
            raise Conflict('El Deployment cambió de identidad.')
        if plan['kind'] != 'latency':
            value = owned_fields(obj, plan['kind'])
            expected = plan['original' if restored else 'applied']
            if value != expected:
                if value not in (plan['original'], plan['applied']):
                    raise Conflict('Configuración modificada por otro actor.')
                return False
            if not restored and (container(obj)[1]['image'] != plan['image'] or
                    (plan['kind'] == 'cpu_limit' and self.workload() != plan['workload'])):
                return False
            ready = self.backend.get(TARGET)['rolled_out']
            if ready and plan['kind'] == 'cpu_limit':
                self.admitted_cpu(expected)
            return ready
        proxy = self.check_proxy_identity(plan)
        if not restored and owned_fields(obj, 'wrong_port')['address'] != PROXY:
            return False
        own = next((t for t in proxy.get('toxics', []) if t['name'] == plan['toxic']['name']), None)
        if own and own != plan['toxic']:
            raise Conflict('La perturbación propia fue modificada por otro actor.')
        if any(t['name'] != plan['toxic']['name'] for t in proxy.get('toxics', [])):
            raise Conflict('Hay una perturbación ajena; no se declarará recuperación.')
        return (own is None) if restored else (own is not None)

    def restore(self, plan):
        if plan['kind'] != 'latency':
            self.patch(plan, plan['applied'], plan['original'])
        else:
            proxy = self.check_proxy_identity(plan)
            own = next((t for t in proxy.get('toxics', []) if t['name'] == plan['toxic']['name']), None)
            if own:
                if own != plan['toxic']:
                    raise Conflict('Perturbación modificada; no se elimina automáticamente.')
                self.proxy('/toxics/' + plan['toxic']['name'], method='DELETE')


class DemoFaults(Faults):
    """Synthetic adapter, never represented as a real fault or real telemetry."""
    def __init__(self, backend):
        super().__init__(backend, CATALOG)
        self.values = {'wrong_port': {'address': DIRECT}, 'cpu_limit': {'request': '200m', 'limit': '300m'}}
        self.toxics = {}

    def prepare(self, kind, values, ident):
        values = parameters(kind, values)
        original = copy.deepcopy(self.values.get(kind, {}))
        applied = ({'address': 'redis-cart:6380'} if kind == 'wrong_port' else
                   {'request': str(values['millicores']) + 'm', 'limit': str(values['millicores']) + 'm'} if kind == 'cpu_limit' else values)
        return {'version': 1, 'kind': kind, 'uid': 'demo-' + TARGET, 'service': TARGET, 'container': CONTAINER,
                'original': original, 'applied': applied, 'parameters': values, 'toxic_id': ident, 'image': 'synthetic'}

    def apply(self, plan):
        if plan['kind'] == 'latency':
            self.toxics[plan['toxic_id']] = plan['applied']
        elif self.values[plan['kind']] != plan['original']:
            raise Conflict('Cambio ajeno simulado.')
        else:
            self.values[plan['kind']] = copy.deepcopy(plan['applied'])
        return plan

    def matches(self, plan, restored=False):
        if plan['kind'] == 'latency':
            value = self.toxics.get(plan['toxic_id'])
            if value is not None and value != plan['applied']:
                raise Conflict('Perturbación modificada.')
            return value is None if restored else value is not None
        value = self.values[plan['kind']]
        if value not in (plan['original'], plan['applied']):
            raise Conflict('Cambio ajeno simulado.')
        return value == plan['original' if restored else 'applied'] and self.backend.get(TARGET)['rolled_out']

    def restore(self, plan):
        self.matches(plan)
        if plan['kind'] == 'latency':
            self.toxics.pop(plan['toxic_id'], None)
        else:
            self.values[plan['kind']] = copy.deepcopy(plan['original'])
