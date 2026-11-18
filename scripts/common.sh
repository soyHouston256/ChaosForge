#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF="$ROOT/infrastructure/terraform"
# El proyecto no está escrito en el código: sale de PROJECT_ID o, si falta,
# del proyecto activo de gcloud.
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" ]]; then
  echo 'FALTA PROJECT_ID. Usa: export PROJECT_ID=tu-proyecto (o gcloud config set project tu-proyecto)' >&2
  exit 2
fi
REGION="${REGION:-us-central1}"
CLUSTER="${CLUSTER:-chaosforge-lab}"
STATE_BUCKET="${STATE_BUCKET:-${PROJECT_ID}-chaosforge-tfstate}"
export PROJECT_ID REGION CLUSTER STATE_BUCKET
export TF_VAR_project_id="$PROJECT_ID" TF_VAR_region="$REGION" TF_VAR_cluster_name="$CLUSTER"
require_bucket() {
  gcloud storage buckets describe "gs://$STATE_BUCKET" --project="$PROJECT_ID" >/dev/null 2>&1 || {
    echo "No existe gs://$STATE_BUCKET; primero ejecuta scripts/bootstrap.sh" >&2
    exit 2
  }
}
# El estado siempre es remoto; el bucket lo crea scripts/bootstrap.sh.
init_tf() {
  terraform -chdir="$TF" init -input=false -reconfigure -backend-config="bucket=$STATE_BUCKET"
}
credentials(){ gcloud container clusters get-credentials "$CLUSTER" --project "$PROJECT_ID" --region "$REGION"; }
