#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
credentials
# Recuperación de emergencia; baseline por defecto=1 (ajustar si cambias las réplicas)
ORIGINAL=1
if [[ -f "$ROOT/.evidence/latest.json" ]]; then ORIGINAL="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["original_replicas"])' "$ROOT/.evidence/latest.json")"; fi
kubectl -n boutique scale deploy/cartservice --replicas="$ORIGINAL"
kubectl -n boutique rollout status deploy/cartservice --timeout=300s
