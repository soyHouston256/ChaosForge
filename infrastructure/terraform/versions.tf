terraform {
  required_version = ">= 1.6.0"
  backend "gcs" {
    bucket = "tider-ops-chaosforge-tfstate"
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
