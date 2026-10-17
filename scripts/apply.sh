#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
require_bucket
[[ -f "$TF/lab.tfplan" ]] || { echo 'Primero ejecuta scripts/plan.sh'; exit 2; }
echo "APPLY facturable en $PROJECT_ID. El presupuesto NO bloquea cobros."
read -r -p 'Escribe CREAR: ' ans
[[ "$ans" == CREAR ]] || exit 1
terraform -chdir="$TF" apply -input=false lab.tfplan
credentials
