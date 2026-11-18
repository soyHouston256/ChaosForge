variable "project_id" {
  type        = string
  description = "ID del proyecto de Google Cloud donde vive el laboratorio."
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "github_repository" {
  type        = string
  description = "Repositorio autorizado a desplegar, como dueño/nombre, con las mayúsculas exactas de GitHub."
  default     = "soyHouston256/ChaosForge"
}

variable "github_branch" {
  type        = string
  description = "Única rama desde la que GitHub Actions puede obtener credenciales."
  default     = "main"
}

variable "billing_account" {
  type        = string
  description = "ID de la cuenta de facturación (XXXXXX-XXXXXX-XXXXXX). Vacío = no crear presupuesto."
  default     = ""
}

variable "budget_amount" {
  type        = number
  description = "Presupuesto mensual, en la moneda de la cuenta de facturación. Solo notifica; no detiene recursos."
  default     = 100
}
