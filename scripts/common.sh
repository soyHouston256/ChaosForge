#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF="$ROOT/infrastructure/terraform"
PROJECT_ID="${PROJECT_ID:-tider-ops}"
REGION="${REGION:-us-central1}"
CLUSTER="${CLUSTER:-chaosforge-lab}"
export TF_VAR_project_id="$PROJECT_ID" TF_VAR_region="$REGION" TF_VAR_cluster_name="$CLUSTER"
# STATE_BUCKET debe pasarse explicitamente; nunca use el estado local sin querer.
require_bucket() { [[ -n "${STATE_BUCKET:-}" ]] || { echo 'FALTA STATE_BUCKET; primero ejecuta scripts/bootstrap-state.sh'; exit 2; }; }
init_tf(){ require_bucket; terraform -chdir="$TF" init -input=false -backend-config="bucket=$STATE_BUCKET" -backend-config="prefix=chaosforge/lab"; }
credentials(){ gcloud container clusters get-credentials "$CLUSTER" --project "$PROJECT_ID" --region "$REGION"; }
