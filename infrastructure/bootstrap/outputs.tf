output "project_id" { value = var.project_id }
output "project_number" { value = data.google_project.this.number }
output "region" { value = var.region }
output "state_bucket" { value = google_storage_bucket.tfstate.name }
output "wif_provider" { value = google_iam_workload_identity_pool_provider.github.name }
output "deploy_service_account" { value = google_service_account.deployer.email }
output "image_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.chaosforge.repository_id}/chaosforge-admin"
}
