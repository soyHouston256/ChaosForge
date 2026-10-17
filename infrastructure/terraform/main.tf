locals {
  services = toset([
    "container.googleapis.com", "compute.googleapis.com", "logging.googleapis.com",
    "monitoring.googleapis.com", "cloudtrace.googleapis.com"
  ])
}
resource "google_project_service" "apis" {
  for_each = local.services
  project = var.project_id
  service = each.key
  disable_on_destroy = false
}
resource "google_compute_network" "lab" {
  project = var.project_id
  name = "chaosforge-lab-vpc"
  auto_create_subnetworks = false
  depends_on = [google_project_service.apis]
}
resource "google_compute_subnetwork" "lab" {
  project = var.project_id
  name = "chaosforge-lab-subnet"
  region = var.region
  network = google_compute_network.lab.id
  ip_cidr_range = "10.40.0.0/20"
  secondary_ip_range {
    range_name = "pods"
    ip_cidr_range = "10.48.0.0/16"
  }
  secondary_ip_range {
    range_name = "services"
    ip_cidr_range = "10.49.0.0/20"
  }
}
resource "google_container_cluster" "lab" {
  project = var.project_id
  name = var.cluster_name
  location = var.region
  enable_autopilot = true
  network = google_compute_network.lab.id
  subnetwork = google_compute_subnetwork.lab.id
  deletion_protection = false # Lab-only; destroy protegido por confirmación en scripts
  ip_allocation_policy {
    cluster_secondary_range_name = "pods"
    services_secondary_range_name = "services"
  }
  depends_on = [google_project_service.apis]
}
