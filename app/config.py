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
    ploomes_web_base_url: str = "https://app10.ploomes.com"
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
    # Enum real da API do Bling para transporte.fretePorConta (inteiro):
    # 0=CIF (remetente), 1=FOB (destinatario), 2=Terceiros, 3/4=transporte proprio, 9=sem transporte.
    # No Ploomes o campo "Transportador" so deve usar CIF/FOB -- mapeamento 1:1.
    bling_freight_methods: str = "CIF:0,FOB:1"
    bling_seller_map: str = (
        "110010966:15596341520,"
        "110010962:15596314450,"
        "110002267:15596475293,"
        "110010967:15596492999,"
        "110003589:15596569525,"
        "110010963:15596543186,"
        "110077864:15596871292,"
        "110010961:15596871291,"
        "110077780:15596871286,"
        "110078522:15596877219,"
    )

    # Ploomes Deals -> Bling: fluxo pedido de venda + pedido de compra + situacao
    # Estagio "Gerar pedido de venda" foi removido do funil -- o gatilho agora e a
    # propria entrada em "Solicitacao de Compra" (pipeline_id:trigger_stage_id:stage_apos_gerar_pedidos,
    # trigger e destino sao o mesmo estagio: o Deal so sai dali quando alguem move manualmente).
    ploomes_deal_purchase_trigger_stage_rules: str = "110001615:110006382:110006382"
    # Estagio que dispara atualizacao de situacao no Bling, sem criar pedido novo (pipeline_id:stage_id)
    ploomes_deal_logistics_stage_rules: str = "110001615:110008939"
    # Ids de situacao no Bling para os pedidos de venda (TBD -- bloqueado por escopo OAuth insuficiente, ver plano)
    bling_situacao_em_processo_compra: int = 0
    bling_situacao_pronto_faturar: int = 0
    # Novo campo customizado no Deal para guardar o id do pedido de compra gerado (TBD -- criar no Ploomes)
    ploomes_deal_purchase_order_id_field: str = ""
    # Deal pulando direto de um desses estagios (Orcamento/Analise de Credito/Analise
    # aprovada) para Logistica, sem passar por "Gerar pedido de venda" -- gera pedido
    # de venda ali mesmo, ja com situacao pronto_faturar. Formato: pipeline_id:origem1,origem2,...:destino
    ploomes_deal_direct_to_logistics_rules: str = (
        "110001615:110006379,110006380,110355350:110008939"
    )

    # Postgres (espelho local bling_produtos, bling_order_links, etc.)
    # Nao usado por nenhum caminho ao vivo do Cloud Run ainda -- ver plano (Risco B)
    # antes de importar app/clients/db.py de dentro de app/main.py.
    db_host: str = ""
    db_port: int = 5432
    db_name: str = ""
    db_user: str = ""
    db_password: str = ""

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
    sync_force_create_ploomes: bool = False
    sync_update_existing_ploomes: bool = True
    # No full-sync, mapeia direto da listagem paginada (100/pag) sem GET /produtos/{id}
    # por item. Reduz ~240k -> ~2.4k requisicoes Bling. Nao preenche marca/NCM/peso/
    # dimensoes (nao vem na listagem). O webhook individual continua usando o detalhe.
    sync_skip_product_detail: bool = True
    # Pre-indexa os Codes ja existentes no Ploomes uma vez (listagem enxuta) e usa
    # o set em memoria em vez de 1 GET de lookup por produto. Torna a carga/retomada
    # muito mais barata no lado Ploomes. So pula a busca pontual quando o produto ja
    # existe e sync_update_existing_ploomes=False (update precisa do Id -> busca pontual).
    sync_preindex_ploomes_codes: bool = True
    sync_preindex_page_size: int = 1000
    reconcile_page_size: int = 100
    http_timeout_seconds: float = 30.0
    bling_min_request_interval_seconds: float = 0.35
    ploomes_min_request_interval_seconds: float = 0.25
    # Orcamento diario de requisicoes ao Bling (limite da API v3 = 120.000/dia).
    # Padrao 100.000 deixa ~20.000 de folga para webhooks/reconcile no mesmo app.
    # 0 desativa o controle de cota.
    bling_daily_request_budget: int = 100000
    # Contador diario persistido (arquivo local; usa gcs_bucket quando definido).
    bling_quota_path: str = ".bling_quota.json"
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
