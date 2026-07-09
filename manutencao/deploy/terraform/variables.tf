variable "project_id" {
  type        = string
  description = "ID do projeto GCP."
}

variable "region" {
  type        = string
  description = "Região dos recursos (Cloud Run, Cloud SQL, Artifact Registry)."
  default     = "us-central1"
}

variable "service_name" {
  type        = string
  description = "Nome base do serviço (usado em Cloud Run, instância SQL, etc.)."
  default     = "manutencao-api"
}

variable "image" {
  type        = string
  description = "Imagem do container (ex: us-central1-docker.pkg.dev/PROJ/manutencao/api:latest)."
}

variable "db_tier" {
  type        = string
  description = "Tier da instância Cloud SQL."
  default     = "db-f1-micro"
}

variable "db_name" {
  type        = string
  default     = "manutencao"
}

variable "db_user" {
  type        = string
  default     = "manutencao"
}

variable "db_deletion_protection" {
  type        = bool
  description = "Proteção contra exclusão da instância Cloud SQL."
  default     = false
}

variable "allow_unauthenticated" {
  type        = bool
  description = "Permite acesso público (allUsers como run.invoker)."
  default     = true
}

variable "min_instances" {
  type    = number
  default = 0
}

variable "max_instances" {
  type    = number
  default = 2
}

variable "seed_on_start" {
  type        = bool
  description = "Se true, roda o seed (perfis + admin) no start do container."
  default     = true
}
