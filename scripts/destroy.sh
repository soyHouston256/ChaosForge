#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
init_tf
echo "DESTROY eliminará el clúster y la VPC de $PROJECT_ID. NO elimina el bucket de estado."
read -r -p 'Escribe DESTRUIR: ' ans
[[ "$ans" == DESTRUIR ]] || exit 1
terraform -chdir="$TF" destroy -input=false
