"""Read-only effective authorization checks, executed inside the admin container.
SelfSubjectAccessReview asks Kubernetes about a permission; it does not exercise it.
"""
import json
import ssl
import urllib.request
from pathlib import Path

base = Path('/var/run/secrets/kubernetes.io/serviceaccount')
context = ssl.create_default_context(cafile=str(base/'ca.crt'))
headers = {'Authorization': 'Bearer ' + (base/'token').read_text().strip(), 'Content-Type': 'application/json'}
checks = [
    ('get', 'apps', 'deployments', '', 'cartservice', True),
    ('patch', 'apps', 'deployments', 'scale', 'cartservice', True),
    ('patch', 'apps', 'deployments', 'scale', 'frontend', True),
    ('patch', 'apps', 'deployments', 'scale', 'redis-cart', True),
    ('list', '', 'secrets', '', '', False),
    ('create', '', 'pods', 'exec', '', False),
    ('delete', '', 'pods', '', '', False),
]
for service in ('frontend', 'redis-cart', 'checkoutservice', 'emailservice', 'adservice', 'loadgenerator', 'paymentservice', 'productcatalogservice', 'shippingservice', 'currencyservice', 'recommendationservice'):
    checks.extend([('get', 'apps', 'deployments', '', service, True), ('patch', 'apps', 'deployments', 'scale', service, True)])
checks.append(('list', 'autoscaling', 'horizontalpodautoscalers', '', '', True))
for verb, group, resource, subresource, name, expected in checks:
    body = {'apiVersion': 'authorization.k8s.io/v1', 'kind': 'SelfSubjectAccessReview', 'spec': {'resourceAttributes': {
        'namespace': 'boutique', 'verb': verb, 'group': group, 'resource': resource,
        'subresource': subresource, 'name': name}}}
    req = urllib.request.Request('https://kubernetes.default.svc/apis/authorization.k8s.io/v1/selfsubjectaccessreviews',
                                 headers=headers, data=json.dumps(body).encode(), method='POST')
    with urllib.request.urlopen(req, context=context, timeout=10) as response:
        result = json.load(response)['status']['allowed']
    print('%s %s/%s %s: %s' % (verb, resource, subresource, name, result))
    if result != expected:
        raise SystemExit('Effective RBAC differs from the intended permissions')
