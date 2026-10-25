#!/usr/bin/env bash
# Invoked by the protected deploy-admin job. Never applies Terraform or Boutique.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_REF="${1:?Provide the immutable image reference}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
python3 "$ROOT/admin/render_manifest.py" "$IMAGE_REF" > "$WORK/admin.yaml"
# Recheck immediately before changing an existing administrator.
EXISTING_ADMIN="$(kubectl -n chaosforge-system get deployment chaosforge-admin -o name --ignore-not-found)"
if [[ -n "$EXISTING_ADMIN" ]]; then
  bash "$ROOT/scripts/verify-admin.sh" --idle-only
fi
kubectl apply -f "$WORK/admin.yaml"
kubectl -n chaosforge-system rollout status deployment/chaosforge-admin --timeout=600s
