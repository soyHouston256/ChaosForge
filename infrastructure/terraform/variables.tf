variable "project_id" {
  type        = string
  description = "ID del proyecto de Google Cloud. Sin valor por defecto: se pasa con TF_VAR_project_id."
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "cluster_name" {
  type    = string
  default = "chaosforge-lab"
}
