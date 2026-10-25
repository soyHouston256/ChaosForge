#!/usr/bin/env bash
# Abre el panel real mediante un túnel privado. No despliega ni provoca fallos.
set -euo pipefail

for tool in gcloud kubectl python3; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Falta $tool. Instálalo y vuelve a ejecutar este script." >&2
    exit 1
  fi
done
if ! command -v gke-gcloud-auth-plugin >/dev/null 2>&1; then
  echo 'Falta gke-gcloud-auth-plugin en PATH. Instálalo con:' >&2
  echo '  gcloud components install gke-gcloud-auth-plugin' >&2
  exit 1
fi
if ! ACTIVE_ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)')" || [[ -z "$ACTIVE_ACCOUNT" ]]; then
  echo 'No hay una sesión gcloud activa. Ejecuta: gcloud auth login' >&2
  exit 1
fi
unset ACTIVE_ACCOUNT
# Validar la credencial sin mostrar ni guardar el token.
if ! gcloud auth print-access-token >/dev/null 2>/dev/null; then
  echo 'La sesión gcloud no pudo renovarse. Revisa tu conexión y ejecuta: gcloud auth login' >&2
  exit 1
fi
python3 - <<'PY'
import socket
import sys
with socket.socket() as sock:
    try:
        sock.bind(('127.0.0.1', 8092))
    except OSError:
        print('No se puede usar 127.0.0.1:8092. Si ya tienes un túnel abierto, usa http://127.0.0.1:8092 o ciérralo con Ctrl+C antes de reintentar. No se detuvo ningún proceso.', file=sys.stderr)
        sys.exit(1)
PY

WORK="$(mktemp -d "${TMPDIR:-/tmp}/chaosforge-panel.XXXXXX")"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export KUBECONFIG="$WORK/kubeconfig"
if ! gcloud container clusters get-credentials chaosforge-lab --project=tider-ops --region=us-central1; then
  echo 'No se pudo acceder al clúster. Revisa la sesión, permisos y conectividad; no se cambió tu kubeconfig habitual.' >&2
  exit 1
fi
printf '\nPanel: http://127.0.0.1:8092\n'
printf 'Espera a que aparezca "Forwarding from" y abre la URL. Mantén esta terminal abierta.\n'
printf 'Ctrl+C cierra el túnel y elimina el kubeconfig temporal.\n\n'
# Sin exec: el shell conserva el trap de limpieza cuando termina kubectl.
kubectl -n chaosforge-system port-forward --address 127.0.0.1 service/chaosforge-admin 8092:8080
