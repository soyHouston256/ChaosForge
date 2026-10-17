#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
credentials
NS=boutique
# Experimento v0: outage de cartservice, NO Redis. Tiempo máximo 60s.
ORIGINAL="$(kubectl -n "$NS" get deploy/cartservice -o jsonpath='{.spec.replicas}')"
[[ "$ORIGINAL" =~ ^[0-9]+$ ]] || { echo 'Réplicas no válidas'; exit 2; }
restore(){ kubectl -n "$NS" scale deploy/cartservice --replicas="$ORIGINAL" || true; }
trap restore EXIT INT TERM
echo 'CHAOS-001: cartservice fuera 60s (NO es Redis outage). Solo boutique.'
read -r -p 'Escribe CAOS: ' ans
[[ "$ans" == CAOS ]] || exit 1
mkdir -p "$ROOT/.evidence"
printf '{"scenario":"cartservice-unavailable","original_replicas":%s,"start_utc":"%s"}
' "$ORIGINAL" "$(date -u +%FT%TZ)" > "$ROOT/.evidence/latest.json"
kubectl -n "$NS" scale deploy/cartservice --replicas=0
sleep 60
restore
kubectl -n "$NS" rollout status deployment/cartservice --timeout=300s
trap - EXIT INT TERM
