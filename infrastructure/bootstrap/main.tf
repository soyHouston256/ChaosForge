locals {
  services = toset([
    "serviceusage.googleapis.com", "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com", "iamcredentials.googleapis.com", "sts.googleapis.com",
    "storage.googleapis.com", "artifactregistry.googleapis.com",
    "compute.googleapis.com", "container.googleapis.com",
    "logging.googleapis.com", "monitoring.googleapis.com", "cloudtrace.googleapis.com",
    "billingbudgets.googleapis.com",
  ])
  deployer_project_roles = toset([
    "roles/container.admin",
    "roles/compute.networkAdmin",
    "roles/serviceusage.serviceUsageAdmin",
  ])
  # En organizaciones nuevas la cuenta Compute predeterminada ya no recibe Editor:
  # sin estos roles los nodos no envían logs ni métricas, y el administrador no
  # puede consultar Managed Prometheus.
  node_project_roles = toset([
    "roles/container.defaultNodeServiceAccount",
    "roles/monitoring.viewer",
  ])
}

data "google_project" "this" {
  project_id = var.project_id
}

resource "google_project_service" "apis" {
  for_each           = local.services
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# --- Estado remoto de Terraform -------------------------------------------------
resource "google_storage_bucket" "tfstate" {
  project                     = var.project_id
  name                        = "${var.project_id}-chaosforge-tfstate"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  versioning {
    enabled = true
  }
  depends_on = [google_project_service.apis]
}

# --- Imágenes del administrador -------------------------------------------------
resource "google_artifact_registry_repository" "chaosforge" {
  project       = var.project_id
  location      = var.region
  repository_id = "chaosforge"
  format        = "DOCKER"
  description   = "Imágenes del administrador de ChaosForge"
  depends_on    = [google_project_service.apis]
}

# --- Identidad de despliegue (sin claves JSON) ----------------------------------
resource "google_service_account" "deployer" {
  project      = var.project_id
  account_id   = "chaosforge-deployer"
  display_name = "ChaosForge Terraform Deployer"
  description  = "Identidad que usa GitHub Actions para desplegar el laboratorio ChaosForge"
  depends_on   = [google_project_service.apis]
}

resource "google_project_iam_member" "deployer" {
  for_each = local.deployer_project_roles
  project  = var.project_id
  role     = each.key
  member   = google_service_account.deployer.member
}

resource "google_storage_bucket_iam_member" "deployer_state" {
  bucket = google_storage_bucket.tfstate.name
  role   = "roles/storage.objectAdmin"
  member = google_service_account.deployer.member
}

resource "google_artifact_registry_repository_iam_member" "deployer_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.chaosforge.location
  repository = google_artifact_registry_repository.chaosforge.name
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.deployer.member
}

# --- Federación GitHub Actions -> Google Cloud (OIDC) ---------------------------
resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "chaosforge-pool"
  display_name              = "ChaosForge GitHub Actions"
  description               = "Identidades federadas para CI/CD de ChaosForge desde GitHub Actions"
  depends_on                = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "ChaosForge GitHub OIDC"
  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository"          = "assertion.repository"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
  }
  attribute_condition = "assertion.repository=='${var.github_repository}' && assertion.repository_owner_id!='' && assertion.ref=='refs/heads/${var.github_branch}'"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_impersonation" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

# --- Cuenta de los nodos (Compute predeterminada) -------------------------------
data "google_compute_default_service_account" "nodes" {
  project    = var.project_id
  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "nodes" {
  for_each = local.node_project_roles
  project  = var.project_id
  role     = each.key
  member   = data.google_compute_default_service_account.nodes.member
}

resource "google_artifact_registry_repository_iam_member" "nodes_reader" {
  project    = var.project_id
  location   = google_artifact_registry_repository.chaosforge.location
  repository = google_artifact_registry_repository.chaosforge.name
  role       = "roles/artifactregistry.reader"
  member     = data.google_compute_default_service_account.nodes.member
}

# Autopilot crea los nodos con la cuenta Compute predeterminada: el desplegador
# necesita poder actuar como ella, y solo como ella.
resource "google_service_account_iam_member" "deployer_acts_as_nodes" {
  service_account_id = data.google_compute_default_service_account.nodes.name
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.deployer.member
}

# --- Presupuesto con alertas (opcional) -----------------------------------------
resource "google_billing_budget" "lab" {
  count           = var.billing_account == "" ? 0 : 1
  provider        = google.billing
  billing_account = var.billing_account
  display_name    = "ChaosForge lab (${var.project_id})"
  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }
  amount {
    specified_amount {
      units = tostring(var.budget_amount)
    }
  }
  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }
  depends_on = [google_project_service.apis]
}
