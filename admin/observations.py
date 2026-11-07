"""Neutral operational samples, collected independently of experiment state.

No experiment IDs, mechanisms, actor labels, or rollback snapshots are exported.
"""
import json
import math
import socket
import time
import urllib.parse
import urllib.request

from faults import CONTAINER, DIRECT, PROXY, TARGET, container, owned_fields


def public_config(obj):
    _, c = container(obj)
    address = owned_fields(obj, 'wrong_port')['address']
    # Only the explicitly permitted non-secret destination is exposed.
    host, sep, port = address.rpartition(':')
    if not sep or host not in ('redis-cart', 'chaosforge-proxy') or not port.isdigit():
        address = '[unsupported destination]'
    return {'uid': obj['metadata']['uid'], 'generation': obj['metadata']['generation'],
            'image': c['image'], 'container': CONTAINER, 'redis_address': address,
            'cpu': owned_fields(obj, 'cpu_limit')}


def cpu_sample(backend):
    """Managed Prometheus, restricted to pods owned by this Deployment."""
    inventory = backend.pod_inventory(TARGET)
    pods = [p['pod'] for p in inventory]
    if not pods:
        return {'coverage': 'missing', 'reason': 'No hay pods identificados.'}
    query_labels = {'project_id': 'tider-ops', 'cluster': 'chaosforge-lab', 'location': 'us-central1',
                    'namespace': 'boutique', 'container': CONTAINER}
    selector = ','.join(k + '=' + json.dumps(v) for k, v in query_labels.items())
    selector += ',pod=~' + json.dumps('|'.join(pods))
    period = 'container_cpu_cfs_periods_total{' + selector + '}'
    throttled = 'container_cpu_cfs_throttled_periods_total{' + selector + '}'
    queries = {
        'ratio': 'sum by(pod,container)(rate(' + throttled + '[60s])) / sum by(pod,container)(rate(' + period + '[60s]))',
        'sample_time': 'max by(pod,container)(timestamp(' + period + '))',
    }
    req = urllib.request.Request('http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
                                 headers={'Metadata-Flavor': 'Google'})
    with urllib.request.urlopen(req, timeout=2) as response:
        token = json.load(response)['access_token']
    results = {}
    for key, query in queries.items():
        params = urllib.parse.urlencode({'query': query})
        req = urllib.request.Request('https://monitoring.googleapis.com/v1/projects/tider-ops/location/global/prometheus/api/v1/query?' + params,
                                     headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.load(response)
        if data.get('status') != 'success' or data.get('warnings'):
            return {'coverage': 'incomplete', 'reason': 'Consulta de métricas incompleta.'}
        results[key] = {s['metric']['pod']: float(s['value'][1]) for s in data.get('data', {}).get('result', [])}
    values = [{'pod': p['pod'], 'container': CONTAINER, 'ratio': results['ratio'].get(p['pod']),
               'sample_time': results['sample_time'].get(p['pod']),
               'effective_resources': next((c['resources'] for c in p['containers'] if c['name'] == CONTAINER), None)} for p in inventory]
    complete = all(v['ratio'] is not None and math.isfinite(v['ratio']) and 0 <= v['ratio'] <= 1 and v['sample_time'] is not None
                   and 0 <= time.time() - v['sample_time'] <= 90 and v['effective_resources'] for v in values)
    return {'coverage': 'complete' if complete else 'incomplete', 'series': values,
            'window_seconds': 60, 'source': 'GKE Managed Prometheus; throttled periods / total periods',
            'mapping': 'ReplicaSet owner UID and pod owner UID'}


def capture(backend, now=None):
    at = time.time() if now is None else now
    if hasattr(backend, 'synthetic_sample'):
        return backend.synthetic_sample(at)
    sample = {'at': at, 'service': TARGET, 'source': 'operational_observer', 'synthetic': False}
    try:
        obj = backend.faults.deployment()
        sample['configuration'] = public_config(obj)
        sample['deployment'] = backend.get(TARGET)
        sample['http'] = backend.probe()
        address = sample['configuration']['redis_address']
        host, sep, port = address.rpartition(':')
        if sep and host in ('redis-cart', 'chaosforge-proxy') and port in ('6379', '6380'):
            started = time.monotonic()
            ok = False
            try:
                with socket.create_connection((host + '.boutique.svc.cluster.local', int(port)), timeout=1) as conn:
                    conn.sendall(b'*1\r\n$4\r\nPING\r\n')
                    ok = conn.recv(64) == b'+PONG\r\n'
            except OSError:
                pass
            sample['dependency'] = {'operation': 'Redis PING via configured destination', 'success': ok,
                                    'elapsed_ms': round((time.monotonic() - started) * 1000, 2)}
        if 'cpu_limit' in backend.faults.enabled:
            # Sampling cadence is independent of whether an experiment exists.
            cached = getattr(backend, '_cpu_sample', None)
            if cached is None or at - cached[0] >= 30:
                try:
                    value = cpu_sample(backend)
                except Exception:
                    value = {'coverage': 'unavailable', 'reason': 'Lectura de métricas no disponible.'}
                backend._cpu_sample = (at, value)
            sample['cpu_throttling'] = dict(backend._cpu_sample[1], queried_at=backend._cpu_sample[0])
        sample['coverage'] = 'complete' if 'dependency' in sample else 'incomplete'
    except Exception:
        sample.update(coverage='unavailable', reason='No se pudo completar la observación operativa.')
    sample['captured_at'] = time.time() if now is None else now
    return sample


def latency(sample):
    return next((p.get('elapsed_ms') for p in sample.get('http', []) if p['path'] == '/cart'), None)


def healthy(sample):
    return sample.get('coverage') == 'complete' and sample.get('deployment', {}).get('rolled_out') \
        and sample.get('dependency', {}).get('success') and bool(sample.get('http')) \
        and all(p['status'] == 200 for p in sample['http']) and latency(sample) is not None


def throttle(sample, after=0):
    cpu = sample.get('cpu_throttling', {})
    if cpu.get('coverage') != 'complete' or not cpu.get('series'):
        return None
    if any(s['sample_time'] < after or not 0 <= sample['at'] - s['sample_time'] <= 90
           or not math.isfinite(s['ratio']) or not 0 <= s['ratio'] <= 1 for s in cpu['series']):
        return None
    return max(s['ratio'] for s in cpu['series'])
