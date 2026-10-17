#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
credentials
[[ -d "$ROOT/vendor/microservices-demo/kustomize" ]] || "$ROOT/scripts/fetch-boutique.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp -a "$ROOT/vendor/microservices-demo/kustomize/." "$WORK/"
# Agregar el componente oficial de Google Cloud Operations a una copia, no a vendor.
python3 - "$WORK/kustomization.yaml" <<'PYK'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
line = '  - components/google-cloud-operations'
if 'components/google-cloud-operations' not in s:
    if '\ncomponents:' in s:
        s = s.replace('\ncomponents:', '\ncomponents:\n' + line, 1)
    else:
        s += '\ncomponents:\n' + line + '\n'
p.write_text(s)
PYK
kubectl create namespace boutique --dry-run=client -o yaml | kubectl apply -f -
kubectl kustomize "$WORK" >/dev/null
kubectl -n boutique apply -k "$WORK"
echo 'Aplicado. Revisa scripts/validate.sh. Observabilidad debe verificarse manualmente en GCP.'
