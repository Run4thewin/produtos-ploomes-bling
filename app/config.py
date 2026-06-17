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

    # Ploomes Deals -> Bling sales orders
    ploomes_deal_entity_id: int = 2
    ploomes_deal_stage_rules: str = (
        "110005492:110022662:110022663,"
        "110001615:110020807:110008939"
    )
    ploomes_deal_error_stage_id: int = 110070771
    ploomes_deal_order_field: str = "deal_50071B8C-A01B-49C1-83D3-AA666C588A95"
    ploomes_deal_purchase_order_field: str = "deal_943CBBDC-AF6A-47DD-8AC0-A6E039BFB82C"
    ploomes_deal_payment_method_field: str = "deal_BFAEEEE4-2B09-4420-87BE-30C7C375C93B"
    ploomes_deal_payment_days_field: str = "deal_429C6DEE-E08F-4D96-844B-CA8FDB433EC8"
    ploomes_deal_payment_days_fallback_field: str = "deal_EA16A707-10CA-4B9D-A019-41EA30BBBAD9"
    ploomes_deal_internal_notes_field: str = "deal_A3DE71E8-ACFC-4C64-BD58-9166109DB90F"
    ploomes_deal_external_notes_field: str = "deal_2541512D-3A3C-4CE0-B66B-A44171501238"
    ploomes_deal_carrier_field: str = "deal_420302F3-BA11-4497-BAEF-E67EFD07FD9B"
    ploomes_deal_freight_type_field: str = "deal_7BC53E9B-AF8C-408F-A1CD-8B2C753C77DD"
    ploomes_deal_freight_value_field: str = "deal_59F2936E-3DC3-4621-A019-578D1AA2D1DA"
    bling_payment_methods: str = (
        "Boleto - Bling Conta:4165732,"
        "BOLETO:5584894,"
        "CARTAO DE CREDITO:1366426,"
        "CARTÃO DE CRÉDITO:1366426,"
        "Deposito em conta:4119280,"
        "Cartao de Credito - Bling Conta:4169411,"
        "Cartão de Crédito - Bling Conta:4169411,"
        "PIX:4165733"
    )
    bling_freight_methods: str = (
        "CIF:R,"
        "FOB:D,"
        "Frete por conta de terceiros:T,"
        "Sedex:4119280,"
        "Transporte proprio pelo destinatario:4,"
        "Transporte proprio pelo remetente:3"
    )
    bling_seller_map: str = (
        "110010961:15596362133,"
        "110010966:15596341520,"
        "110010962:15596314450,"
        "110002267:15596475293,"
        "110010967:15596492999,"
        "110003589:15596569525,"
        "110010963:15596543186"
    )

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
