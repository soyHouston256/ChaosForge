#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
credentials
kubectl -n boutique get deploy,pods,svc
kubectl -n boutique rollout status deployment/frontend --timeout=300s
printf '
Frontend external:
'; kubectl -n boutique get svc frontend-external
printf '
Logs recientes (muestra):
'; kubectl -n boutique logs deploy/frontend --tail=8 || true
