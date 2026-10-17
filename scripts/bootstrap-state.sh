
#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

BUCKET="tider-ops-chaosforge-tfstate"
BUCKET_URI="gs://${BUCKET}"

echo "ChaosForge - Terraform State Bootstrap"
echo "Proyecto: ${PROJECT_ID}"
echo "Bucket: ${BUCKET_URI}"

# Comprobar acceso al bucket.
if gcloud storage buckets describe "$BUCKET_URI" \
  --project="$PROJECT_ID" >/dev/null 2>&1; then

  echo "Bucket existente. No se creará nuevamente."

else
  echo "No se pudo consultar el bucket."
  echo "Verifica si existe y si tienes permisos."
  echo "No se creará automáticamente para evitar duplicados."
  exit 1
fi

# Comprobar que el versionado está habilitado.
VERSIONING=$(gcloud storage buckets describe "$BUCKET_URI" \
  --format="value(versioning_enabled)")

if [[ "$VERSIONING" == "True" || "$VERSIONING" == "true" ]]; then
  echo "Versionado habilitado."
else
  echo "ERROR: El versionado no está habilitado."
  exit 1
fi

echo "Terraform State verificado correctamente."
