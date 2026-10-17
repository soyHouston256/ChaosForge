#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
# Ejecutar una sola vez desde Cloud Shell con permisos Storage Admin sobre este proyecto.
NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
BUCKET="${STATE_BUCKET:-chaosforge-tfstate-${NUMBER}}"
echo "Se creará el bucket gs://$BUCKET para Terraform State (facturable)."
read -r -p 'Escribe ESTADO para continuar: ' ans
[[ "$ans" == ESTADO ]] || exit 1
gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1 || gcloud storage buckets create "gs://$BUCKET" --project="$PROJECT_ID" --location="$REGION" --uniform-bucket-level-access
gcloud storage buckets update "gs://$BUCKET" --versioning
printf '
Usa: export STATE_BUCKET=%q
' "$BUCKET"
echo 'No borrar este bucket mientras exista infraestructura Terraform.'
