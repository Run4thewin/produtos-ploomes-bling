from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Bling OAuth
    bling_client_id: str = ""
    bling_client_secret: str = ""
    bling_api_base: str = "https://api.bling.com.br/Api/v3"

    # Ploomes
    ploomes_user_key: str = ""
    ploomes_api_base: str = "https://api2.ploomes.com"
    ploomes_group_id: int = 0
    ploomes_field_fabricante: str = "product_5DCA9FE9-D9C8-4C33-B7D9-A0E783E36CDB"
    ploomes_field_partnumber: str = "product_5F984A7A-AF01-4054-AEC7-702568153273"
    ploomes_field_ncm: str = "product_FF802FFC-60F9-4409-A91B-70F8D2A77E82"
    ploomes_field_descricao: str = "product_21B2B4C1-4DFD-4381-822E-A8F6F1E556A7"
    ploomes_product_entity_id: int = 10
    ploomes_webhook_validation_key: str = ""

    # Token persistence (local file or GCS on Cloud Run)
    bling_tokens_path: str = "tokens.json"
    # Projeto legado com OAuth Selenium e tokens compartilhados
    legacy_ploomes_bling_path: str = (
        r"C:\Users\CMC_DEV_001\Documents\projetos\cmc\automacao\ploomes_bling"
    )
    gcs_bucket: str = ""

    # GCP / Cloud Run
    gcp_project: str = ""
    cloud_tasks_location: str = "us-central1"
    cloud_tasks_queue: str = "ploomes-bling-products"
    service_url: str = ""
    use_cloud_tasks: bool = False
    cloud_tasks_service_account: str = ""

    # Protect internal endpoints (Cloud Tasks + Cloud Scheduler)
    internal_secret: str = ""

    # Sync tuning
    reconcile_page_size: int = 100
    http_timeout_seconds: float = 30.0
    sync_workers: int = 5
    sync_progress_every: int = 25
    sync_log_file: str = ""

    @property
    def cloud_tasks_enabled(self) -> bool:
        return self.use_cloud_tasks and bool(
            self.gcp_project and self.service_url
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
