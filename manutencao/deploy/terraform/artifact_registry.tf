resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = "manutencao"
  description   = "Imagens do backend de manutenção"
  format        = "DOCKER"

  depends_on = [google_project_service.enabled]
}
