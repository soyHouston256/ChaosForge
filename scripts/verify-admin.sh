#!/usr/bin/env bash
# GETs and authorization reviews only: never calls /api/start or /api/restore.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
PF_PID=''
cleanup() {
  if [[ -n "$PF_PID" ]]; then kill "$PF_PID" 2>/dev/null || true; wait "$PF_PID" 2>/dev/null || true; fi
  rm -rf "$WORK"
}
trap cleanup EXIT
kubectl -n chaosforge-system port-forward --address 127.0.0.1 service/chaosforge-admin 18080:8080 > "$WORK/port-forward.log" 2>&1 &
PF_PID=$!
for attempt in {1..30}; do
  if curl --fail --silent --max-time 30 http://127.0.0.1:18080/api/state > "$WORK/state.json"; then break; fi
  if ! kill -0 "$PF_PID" 2>/dev/null; then cat "$WORK/port-forward.log"; exit 1; fi
  sleep 1
done
python3 - "$WORK/state.json" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    state = json.load(f)
if state['active'] is not None:
    raise SystemExit('Administrator has a pending experiment. Finish it before deploying; no automatic restoration was requested.')
if state['mode'] != 'GKE · datos reales':
    raise SystemExit('Expected the real Kubernetes backend')
if len(state['services']) != 6 or any(s.get('error') or s.get('uid','').startswith('demo-') or not s.get('uid') for s in state['services']):
    raise SystemExit('Cannot read all six authorized Deployments')
print('Real service reads OK; no active experiment. No secrets or CSRF token printed.')
PY
if [[ "${1:-}" == '--idle-only' ]]; then exit 0; fi
kubectl -n chaosforge-system get service chaosforge-admin -o json > "$WORK/service.json"
kubectl -n chaosforge-system get pvc chaosforge-state -o json > "$WORK/pvc.json"
kubectl -n chaosforge-system get networkpolicy private-admin -o json > "$WORK/networkpolicy.json"
kubectl -n chaosforge-system get deployment chaosforge-admin -o json > "$WORK/deployment.json"
python3 - "$WORK" <<'PY'
import json, os, pathlib, sys
p = pathlib.Path(sys.argv[1])
svc = json.loads((p/'service.json').read_text())
pvc = json.loads((p/'pvc.json').read_text())
assert svc['spec']['type'] == 'ClusterIP' and not svc['spec'].get('externalIPs'), 'Service must stay private'
assert pvc['status']['phase'] == 'Bound', 'Persistent volume is not Bound'
policy = json.loads((p/'networkpolicy.json').read_text())
deploy = json.loads((p/'deployment.json').read_text())
assert policy['spec'].get('ingress', []) == [] and 'Ingress' in policy['spec']['policyTypes'], 'Ingress must be denied'
assert deploy['spec']['replicas'] == 1, 'Exactly one administrator is supported'
if os.environ.get('IMAGE_REF'):
    assert deploy['spec']['template']['spec']['containers'][0]['image'] == os.environ['IMAGE_REF'], 'Wrong deployed digest'
assert any(v.get('persistentVolumeClaim',{}).get('claimName') == 'chaosforge-state' for v in deploy['spec']['template']['spec']['volumes']), 'Deployment must use persistent state'
print('Private ClusterIP, ingress policy, single replica and Bound PVC verified')
PY
# Runs fixed diagnostic code with the pod's own identity. No impersonation grant needed.
kubectl -n chaosforge-system exec -i deployment/chaosforge-admin -- python - < "$ROOT/admin/verify_permissions.py"
kubectl -n chaosforge-system exec deployment/chaosforge-admin -- python -c 'import os, sqlite3; assert os.path.isfile("/data/experiments.sqlite3"); db=sqlite3.connect("file:/data/experiments.sqlite3?mode=ro",uri=True); assert db.execute("PRAGMA quick_check").fetchone()[0]=="ok"; db.close(); print("Persistent SQLite database readable and healthy")'
kubectl -n chaosforge-system get networkpolicy private-admin
