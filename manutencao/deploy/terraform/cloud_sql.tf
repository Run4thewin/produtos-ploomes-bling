resource "random_password" "db" {
  length  = 32
  special = false
}

resource "google_sql_database_instance" "main" {
  name             = "${var.service_name}-db"
  database_version = "POSTGRES_16"
  region           = var.region

  deletion_protection = var.db_deletion_protection

  settings {
    tier              = var.db_tier
    availability_type = "ZONAL"

    backup_configuration {
      enabled = true
    }

    ip_configuration {
      # IP público habilitado; o acesso do Cloud Run é feito pelo conector do
      # Cloud SQL (socket unix) com autenticação IAM, sem expor porta ao mundo.
      ipv4_enabled = true
    }
  }

  depends_on = [google_project_service.enabled]
}

resource "google_sql_database" "db" {
  name     = var.db_name
  instance = google_sql_database_instance.main.name
}

resource "google_sql_user" "user" {
  name     = var.db_user
  instance = google_sql_database_instance.main.name
  password = random_password.db.result
}
