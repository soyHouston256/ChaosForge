#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
init_tf
terraform -chdir="$TF" fmt -check
terraform -chdir="$TF" validate
terraform -chdir="$TF" plan -input=false -out=lab.tfplan
