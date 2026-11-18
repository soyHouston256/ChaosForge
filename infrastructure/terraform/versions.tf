terraform {
  required_version = ">= 1.6.0"
  # El bucket se pasa en `terraform init -backend-config="bucket=..."`
  # (scripts/common.sh y el workflow lo hacen); así el código no queda atado a una cuenta.
  backend "gcs" {
    prefix = "chaosforge/lab"
  }
  required_providers {
    google = { source = "hashicorp/google", version = "~> 6.0" }
  }
}
provider "google" {
  project = var.project_id
  region  = var.region
}
