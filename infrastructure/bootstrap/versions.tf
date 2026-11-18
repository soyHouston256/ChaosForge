# Bootstrap de una sola vez: crea lo que el laboratorio necesita ANTES de que
# GitHub Actions pueda desplegar. Usa estado local (ignorado por Git) porque el
# bucket de estado remoto es uno de los recursos que crea.
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 6.0" }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# La API de presupuestos exige un proyecto de cuota explícito con credenciales de usuario.
provider "google" {
  alias                 = "billing"
  project               = var.project_id
  billing_project       = var.project_id
  user_project_override = true
}
