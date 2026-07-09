output "service_url" {
  description = "URL pública do serviço Cloud Run."
  value       = google_cloud_run_v2_service.api.uri
}

output "instance_connection_name" {
  description = "Connection name do Cloud SQL (PROJECT:REGION:INSTANCE)."
  value       = google_sql_database_instance.main.connection_name
}

output "artifact_registry_repo" {
  description = "Caminho do repositório Docker no Artifact Registry."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}

output "db_password" {
  description = "Senha gerada do usuário do banco (sensível)."
  value       = random_password.db.result
  sensitive   = true
}
