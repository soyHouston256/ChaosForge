#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
echo "Proyecto=$PROJECT_ID Región=$REGION Clúster=$CLUSTER"
gcloud auth list --filter=status:ACTIVE --format='value(account)'
gcloud projects describe "$PROJECT_ID" --format='table(projectId,lifecycleState)'
gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)'
