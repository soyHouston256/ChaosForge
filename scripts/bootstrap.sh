#!/usr/bin/env bash
# Prepara un proyecto de Google Cloud vacío para ChaosForge, UNA sola vez:
# APIs, bucket de estado, repositorio de imágenes, identidad de despliegue,
# federación OIDC con GitHub y (opcional) presupuesto con alertas.
# Después publica los valores como variables del repositorio en GitHub.
#
#   PROJECT_ID=mi-proyecto BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX ./scripts/bootstrap.sh
#
# Es idempotente: volver a ejecutarlo no duplica recursos.
source "$(dirname "$0")/common.sh"
BOOT="$ROOT/infrastructure/bootstrap"
GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-soyHouston256/ChaosForge}"

for cmd in terraform gcloud; do
  command -v "$cmd" >/dev/null || { echo "Falta $cmd" >&2; exit 1; }
done
if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
  echo 'Faltan credenciales para Terraform. Ejecuta: gcloud auth application-default login' >&2
  exit 1
fi
if [[ "$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)')" != "True" ]]; then
  echo "El proyecto $PROJECT_ID no tiene facturación activa." >&2
  exit 1
fi

echo "Bootstrap de ChaosForge"
echo "  Proyecto:    $PROJECT_ID"
echo "  Región:      $REGION"
echo "  Repositorio: $GITHUB_REPOSITORY"
if [[ -n "${BILLING_ACCOUNT:-}" ]]; then
  echo "  Presupuesto: cuenta $BILLING_ACCOUNT"
else
  echo "  Presupuesto: no se crea (define BILLING_ACCOUNT para crearlo)"
fi

VARS=(-var "project_id=$PROJECT_ID" -var "region=$REGION" -var "github_repository=$GITHUB_REPOSITORY"
  -var "billing_account=${BILLING_ACCOUNT:-}")
terraform -chdir="$BOOT" init -input=false
terraform -chdir="$BOOT" plan -input=false -out=bootstrap.tfplan "${VARS[@]}"
read -r -p 'Revisa el plan. Escribe BOOTSTRAP para aplicarlo: ' ans
[[ "$ans" == BOOTSTRAP ]] || exit 1
terraform -chdir="$BOOT" apply -input=false bootstrap.tfplan

out() { terraform -chdir="$BOOT" output -raw "$1"; }
# Pares NOMBRE=salida (sin arreglos asociativos: macOS trae bash 3.2).
GH_VARS="GCP_PROJECT_ID=project_id GCP_REGION=region GCP_WIF_PROVIDER=wif_provider GCP_DEPLOY_SA=deploy_service_account GCP_STATE_BUCKET=state_bucket"
echo
if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  for pair in $GH_VARS; do
    gh variable set "${pair%%=*}" --repo "$GITHUB_REPOSITORY" --body "$(out "${pair#*=}")"
  done
  echo "Variables publicadas en github.com/$GITHUB_REPOSITORY (Settings → Variables)."
else
  echo 'gh no está disponible o sin sesión. Crea estas variables a mano en'
  echo "github.com/$GITHUB_REPOSITORY → Settings → Secrets and variables → Actions → Variables:"
  for pair in $GH_VARS; do printf '  %s = %s\n' "${pair%%=*}" "$(out "${pair#*=}")"; done
fi
echo
echo 'Siguiente: Actions → "ChaosForge - Auth check and deployment" → verify-auth.'
