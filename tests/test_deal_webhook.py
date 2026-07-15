import unittest
from unittest.mock import patch

import httpx

from app.config import Settings
from app.services.ploomes_webhook import parse_ploomes_deal_webhook
from app.services.sync_deal_to_bling_order import DealToBlingOrderSyncService


class FakePloomesClient:
    def __init__(self, deal: dict, quote: dict | None = None, products: dict | None = None):
        self.deal = deal
        self.quote = quote
        self.products = products or {}
        self.updated_deals: list[tuple[int | str, dict]] = []

    def get_deal_by_id(self, deal_id: int | str) -> dict:
        return self.deal

    def get_latest_quote_by_deal(self, deal_id: int | str) -> dict | None:
        return self.quote

    def get_product_by_id(self, product_id: int | str) -> dict:
        return self.products[product_id]

    def update_deal(self, deal_id: int | str, payload: dict) -> dict:
        self.updated_deals.append((deal_id, payload))
        return payload


class FakeBlingClient:
    def __init__(
        self,
        bling_products_by_code: dict | None = None,
        contacts_by_name: dict | None = None,
        purchase_order_error: Exception | None = None,
    ):
        self.created_payload: dict | None = None
        self.created_products: list[dict] = []
        self.bling_products_by_code = bling_products_by_code or {}
        self.contacts_by_name = contacts_by_name or {}
        self.search_contacts_calls: list[str | None] = []
        self.purchase_order_error = purchase_order_error
        self.created_purchase_order_payload: dict | None = None
        self.situacao_updates: list[tuple[int | str, int]] = []

    def get_contact_by_document(self, document_number: str | None) -> dict | None:
        contacts = {
            "12345678000199": {"id": 100, "nome": "Cliente"},
            "98765432000111": {"id": 200, "nome": "Transportadora"},
        }
        return contacts.get(document_number or "")

    def search_contacts(self, pesquisa: str | None = None, limite: int = 20, **kwargs) -> dict:
        self.search_contacts_calls.append(pesquisa)
        contact = self.contacts_by_name.get(pesquisa or "")
        return {"data": [contact] if contact else []}

    def get_product_by_code(self, code: str) -> dict | None:
        return self.bling_products_by_code.get(code)

    def create_product(self, payload: dict) -> dict:
        self.created_products.append(payload)
        return {"id": 500 + len(self.created_products), "codigo": payload.get("codigo")}

    def create_sales_order(self, payload: dict) -> dict:
        self.created_payload = payload
        return {"id": 12345}

    def get_sales_order(self, order_id: int | str) -> dict:
        return {"id": order_id, "numero": "9876"}

    def create_purchase_order(self, payload: dict) -> dict:
        if self.purchase_order_error:
            raise self.purchase_order_error
        self.created_purchase_order_payload = payload
        return {"id": 777}

    def update_sales_order_situacao(self, order_id: int | str, situacao_id: int) -> None:
        self.situacao_updates.append((order_id, situacao_id))


def make_settings(**overrides) -> Settings:
    base = dict(
        ploomes_deal_stage_rules="110001615:110020807:110008939",
        ploomes_deal_error_stage_id=110070771,
        ploomes_deal_order_field="deal_order",
        ploomes_deal_purchase_order_field="deal_po",
        ploomes_deal_payment_method_field="deal_payment",
        ploomes_deal_payment_days_field="deal_days",
        ploomes_deal_payment_days_fallback_field="deal_days_fallback",
        ploomes_deal_internal_notes_field="deal_internal",
        ploomes_deal_external_notes_field="deal_external",
        ploomes_deal_carrier_field="deal_carrier",
        ploomes_deal_freight_type_field="deal_freight_type",
        ploomes_deal_freight_value_field="deal_freight_value",
        bling_payment_methods="BOLETO:5584894",
        bling_freight_methods="CIF:0,FOB:1",
        bling_seller_map="110010961:15596362133",
    )
    base.update(overrides)
    return Settings(**base)


def make_deal(order_reference: str | None = None, stage_id: int = 110020807) -> dict:
    properties = [
        {"FieldKey": "deal_po", "StringValue": "PO-123"},
        {"FieldKey": "deal_payment", "IntegerValue": 1100230750, "ObjectValueName": "Boleto"},
        {"FieldKey": "deal_days", "StringValue": "30/60"},
        {"FieldKey": "deal_internal", "StringValue": "Obs interna"},
        {"FieldKey": "deal_external", "StringValue": "Obs externa"},
        {"FieldKey": "deal_carrier", "ContactValueRegister": "98.765.432/0001-11"},
        {"FieldKey": "deal_freight_type", "ObjectValueName": "CIF"},
        {"FieldKey": "deal_freight_value", "DecimalValue": 10},
    ]
    if order_reference:
        properties.append({"FieldKey": "deal_order", "StringValue": order_reference})

    return {
        "Id": 55,
        "Title": "Venda teste",
        "PipelineId": 110001615,
        "StageId": stage_id,
        "OwnerId": 110010961,
        "Contact": {"Name": "Cliente", "CNPJ": "12.345.678/0001-99", "CPF": None},
        "OtherProperties": properties,
    }


def make_quote() -> dict:
    return {
        "Id": 77,
        "Products": [
            {
                "ProductId": 999,
                "ProductName": "Produto Teste",
                "Quantity": 2,
                "UnitPrice": 100,
                "Discount": 10,
            }
        ],
    }


def make_ploomes_product(settings: Settings, partnumber: str = "SKU-123") -> dict:
    fabricante = "ACME"
    breve_descricao = "Produto Teste"
    return {
        "Id": 999,
        "Name": f"{fabricante} {partnumber} {breve_descricao}",
        "Code": partnumber,
        "UnitPrice": 100,
        "Suspended": False,
        "OtherProperties": [
            {"FieldKey": settings.ploomes_field_partnumber, "StringValue": partnumber},
            {"FieldKey": settings.ploomes_field_fabricante, "StringValue": fabricante},
        ],
    }


class PloomesDealWebhookTest(unittest.TestCase):
    def test_parse_deal_webhook_extracts_deal_id(self):
        parsed = parse_ploomes_deal_webhook(
            {"EntityId": 2, "ActionId": 2, "New": {"Id": 123}},
            deal_entity_id=2,
        )

        self.assertEqual(parsed["status"], "accepted")
        self.assertEqual(parsed["deal_id"], "123")
        self.assertEqual(parsed["action"], "update")

    def test_service_creates_bling_order_and_updates_deal(self):
        settings = make_settings()
        bling = FakeBlingClient(bling_products_by_code={"SKU-123": {"id": 700}})
        ploomes = FakePloomesClient(
            make_deal(),
            make_quote(),
            products={999: make_ploomes_product(settings)},
        )
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        result = service.create_bling_order_from_deal(55)

        self.assertEqual(result["action"], "created")
        self.assertEqual(result["bling_order_id"], 12345)
        self.assertEqual(bling.created_payload["contato"]["id"], 100)
        self.assertEqual(bling.created_payload["vendedor"]["id"], 15596362133)
        self.assertEqual(len(bling.created_payload["parcelas"]), 2)
        self.assertEqual(bling.created_payload["itens"][0]["produto"]["id"], 700)
        self.assertEqual(bling.created_products, [])
        self.assertEqual(ploomes.updated_deals[0][1]["StageId"], 110008939)

    def test_item_description_over_50_chars_registers_error(self):
        settings = make_settings()
        bling = FakeBlingClient(bling_products_by_code={"SKU-123": {"id": 700}})
        long_name = "Disjuntor Tripolar Merlin Gerin C60N C32 Curva C 400V 6KA Trifasico"
        quote = {
            "Id": 77,
            "Products": [
                {
                    "ProductId": 999,
                    "ProductName": long_name,
                    "Quantity": 2,
                    "UnitPrice": 100,
                    "Discount": 10,
                }
            ],
        }
        ploomes = FakePloomesClient(
            make_deal(),
            quote,
            products={999: make_ploomes_product(settings)},
        )
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        result = service.create_bling_order_from_deal(55)

        self.assertEqual(result["action"], "error_registered")
        self.assertIn("50", result["reason"])
        self.assertIsNone(bling.created_payload)
        self.assertEqual(ploomes.updated_deals[0][1]["StageId"], 110070771)

    def test_item_description_at_exactly_50_chars_is_accepted(self):
        settings = make_settings()
        bling = FakeBlingClient(bling_products_by_code={"SKU-123": {"id": 700}})
        exact_name = "A" * 50
        quote = {
            "Id": 77,
            "Products": [
                {
                    "ProductId": 999,
                    "ProductName": exact_name,
                    "Quantity": 2,
                    "UnitPrice": 100,
                    "Discount": 10,
                }
            ],
        }
        ploomes = FakePloomesClient(
            make_deal(),
            quote,
            products={999: make_ploomes_product(settings)},
        )
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        result = service.create_bling_order_from_deal(55)

        self.assertEqual(result["action"], "created")
        self.assertEqual(bling.created_payload["itens"][0]["descricao"], exact_name)

    def test_service_attempts_bling_order_even_with_existing_reference(self):
        settings = make_settings()
        bling = FakeBlingClient(bling_products_by_code={"SKU-123": {"id": 700}})
        ploomes = FakePloomesClient(
            make_deal("Pedido Bling 9876: https://www.bling.com.br/vendas.php#edit/12345"),
            make_quote(),
            products={999: make_ploomes_product(settings)},
        )
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        result = service.create_bling_order_from_deal(55)

        self.assertEqual(result["action"], "created")
        self.assertEqual(result["bling_order_id"], 12345)
        self.assertIsNotNone(bling.created_payload)
        self.assertEqual(ploomes.updated_deals[0][1]["StageId"], 110008939)

    def test_service_creates_bling_product_when_sku_not_found(self):
        settings = make_settings()
        bling = FakeBlingClient(bling_products_by_code={})
        ploomes = FakePloomesClient(
            make_deal(),
            make_quote(),
            products={999: make_ploomes_product(settings)},
        )
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        result = service.create_bling_order_from_deal(55)

        self.assertEqual(result["action"], "created")
        self.assertEqual(len(bling.created_products), 1)
        self.assertEqual(bling.created_products[0]["codigo"], "SKU-123")
        self.assertEqual(bling.created_payload["itens"][0]["produto"]["id"], 501)

    def test_service_registers_error_when_product_missing_partnumber(self):
        settings = make_settings()
        bling = FakeBlingClient()
        product_without_partnumber = make_ploomes_product(settings)
        product_without_partnumber["OtherProperties"] = [
            item
            for item in product_without_partnumber["OtherProperties"]
            if item["FieldKey"] != settings.ploomes_field_partnumber
        ]
        ploomes = FakePloomesClient(
            make_deal(),
            make_quote(),
            products={999: product_without_partnumber},
        )
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        result = service.create_bling_order_from_deal(55)

        self.assertEqual(result["action"], "error_registered")
        self.assertIn("partnumber", result["reason"])
        self.assertEqual(ploomes.updated_deals[0][1]["StageId"], 110070771)

    def test_reports_all_missing_product_fields_at_once(self):
        # Sem repetir o ciclo de "corrige um campo, tenta de novo, descobre o proximo" --
        # o produto esta sem partnumber E sem fabricante ao mesmo tempo, a mensagem
        # de erro deve listar os dois de uma vez.
        settings = make_settings()
        bling = FakeBlingClient()
        product_missing_fields = make_ploomes_product(settings)
        product_missing_fields["OtherProperties"] = [
            item
            for item in product_missing_fields["OtherProperties"]
            if item["FieldKey"]
            not in (settings.ploomes_field_partnumber, settings.ploomes_field_fabricante)
        ]
        ploomes = FakePloomesClient(
            make_deal(),
            make_quote(),
            products={999: product_missing_fields},
        )
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        result = service.create_bling_order_from_deal(55)

        self.assertEqual(result["action"], "error_registered")
        self.assertIn("partnumber", result["reason"])
        self.assertIn("fabricante", result["reason"])
        self.assertIn(
            "https://app10.ploomes.com/Products/table/product/999", result["reason"]
        )


class FreightCodeTypeTest(unittest.TestCase):
    def test_frete_por_conta_is_sent_as_integer(self):
        # Bling espera transporte.fretePorConta como inteiro (confirmado em pedidos reais:
        # 0=CIF, 1=FOB), nao como string -- regressao de bug real corrigido nesta sessao.
        settings = make_settings()
        service = DealToBlingOrderSyncService(
            settings, bling=FakeBlingClient(), ploomes=FakePloomesClient(make_deal())
        )

        transport = service._build_transport(make_deal(), freight_value=None)

        self.assertIsInstance(transport["fretePorConta"], int)
        self.assertEqual(transport["fretePorConta"], 0)


class TransportCarrierResolutionTest(unittest.TestCase):
    def _deal_with_carrier(self, register: str | None = None, name: str | None = None) -> dict:
        deal = make_deal()
        deal["OtherProperties"] = [
            p for p in deal["OtherProperties"] if p["FieldKey"] != "deal_carrier"
        ]
        prop: dict = {"FieldKey": "deal_carrier"}
        if register:
            prop["ContactValueRegister"] = register
        if name:
            prop["ContactValueName"] = name
        deal["OtherProperties"].append(prop)
        return deal

    def test_resolves_carrier_by_document(self):
        settings = make_settings()
        bling = FakeBlingClient()
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=FakePloomesClient(make_deal()))
        deal = self._deal_with_carrier(register="98.765.432/0001-11", name="Transportadora")

        transport = service._build_transport(deal, freight_value=None)

        self.assertEqual(transport["contato"]["id"], 200)
        self.assertEqual(bling.search_contacts_calls, [])

    def test_falls_back_to_name_when_document_missing(self):
        settings = make_settings()
        bling = FakeBlingClient(contacts_by_name={"CORREIOS": {"id": 900, "nome": "CORREIOS"}})
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=FakePloomesClient(make_deal()))
        deal = self._deal_with_carrier(register=None, name="CORREIOS")

        transport = service._build_transport(deal, freight_value=None)

        self.assertEqual(transport["contato"]["id"], 900)
        self.assertEqual(bling.search_contacts_calls, ["CORREIOS"])

    def test_stays_silent_when_carrier_not_found_anywhere(self):
        settings = make_settings()
        bling = FakeBlingClient()
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=FakePloomesClient(make_deal()))
        deal = self._deal_with_carrier(register=None, name="TRANSPORTADORA INEXISTENTE")

        transport = service._build_transport(deal, freight_value=None)

        self.assertNotIn("contato", transport)


class FakeCursor:
    def __init__(self, fetchone_result=None, fetchone_results=None):
        # fetchone_results (lista) tem prioridade: cada chamada de fetchone() consome
        # o proximo item da fila, na ordem em que as queries acontecem. fetchone_result
        # (singular) e mantido para os testes mais antigos, com um unico resultado fixo.
        self.fetchone_queue = list(fetchone_results) if fetchone_results is not None else None
        self.fetchone_result = fetchone_result
        self.executed: list[tuple] = []

    def execute(self, sql, params=None) -> None:
        self.executed.append((sql, params))

    def fetchone(self):
        if self.fetchone_queue is not None:
            return self.fetchone_queue.pop(0) if self.fetchone_queue else None
        return self.fetchone_result

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


class FakeDbConn:
    def __init__(self, fetchone_result=None, fetchone_results=None):
        self.cursor_obj = FakeCursor(fetchone_result, fetchone_results)
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


class PurchaseFlowTest(unittest.TestCase):
    TRIGGER_SETTINGS = dict(
        ploomes_deal_purchase_trigger_stage_rules="110001615:110020372:110006382",
    )

    def test_creates_sales_and_purchase_order_and_moves_deal(self):
        settings = make_settings(**self.TRIGGER_SETTINGS)
        bling = FakeBlingClient(bling_products_by_code={"SKU-123": {"id": 700}})
        ploomes = FakePloomesClient(
            make_deal(stage_id=110020372),
            make_quote(),
            products={999: make_ploomes_product(settings)},
        )
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        with patch("app.services.sync_deal_to_bling_order.get_db_conn", return_value=FakeDbConn()):
            result = service.create_purchase_flow_from_deal(55)

        self.assertEqual(result["action"], "created")
        self.assertEqual(result["bling_order_id"], 12345)
        self.assertEqual(result["bling_purchase_order_id"], 777)
        self.assertNotIn("fornecedor", bling.created_purchase_order_payload)
        self.assertEqual(len(bling.created_purchase_order_payload["itens"]), 1)
        self.assertIn("9876", bling.created_purchase_order_payload["ordemCompra"])
        self.assertEqual(ploomes.updated_deals[0][1]["StageId"], 110006382)
        self.assertEqual(bling.situacao_updates, [])  # bling_situacao_em_processo_compra=0 por padrao

    def test_skips_when_stage_does_not_match_trigger(self):
        settings = make_settings(**self.TRIGGER_SETTINGS)
        bling = FakeBlingClient()
        ploomes = FakePloomesClient(make_deal(stage_id=999999))
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        result = service.create_purchase_flow_from_deal(55)

        self.assertEqual(result["action"], "skipped")
        self.assertIsNone(bling.created_payload)

    def test_purchase_order_failure_does_not_block_sales_order(self):
        settings = make_settings(**self.TRIGGER_SETTINGS)
        error_response = httpx.Response(400, json={"error": {"message": "campo invalido"}}, request=httpx.Request("POST", "http://x"))
        bling = FakeBlingClient(
            bling_products_by_code={"SKU-123": {"id": 700}},
            purchase_order_error=httpx.HTTPStatusError("erro", request=error_response.request, response=error_response),
        )
        ploomes = FakePloomesClient(
            make_deal(stage_id=110020372),
            make_quote(),
            products={999: make_ploomes_product(settings)},
        )
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        with patch("app.services.sync_deal_to_bling_order.get_db_conn", return_value=FakeDbConn()):
            result = service.create_purchase_flow_from_deal(55)

        self.assertEqual(result["action"], "created")
        self.assertEqual(result["bling_order_id"], 12345)
        self.assertIsNone(result["bling_purchase_order_id"])

    def test_advances_situacao_when_configured(self):
        settings = make_settings(
            **self.TRIGGER_SETTINGS, bling_situacao_em_processo_compra=99
        )
        bling = FakeBlingClient(bling_products_by_code={"SKU-123": {"id": 700}})
        ploomes = FakePloomesClient(
            make_deal(stage_id=110020372),
            make_quote(),
            products={999: make_ploomes_product(settings)},
        )
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        with patch("app.services.sync_deal_to_bling_order.get_db_conn", return_value=FakeDbConn()):
            service.create_purchase_flow_from_deal(55)

        self.assertEqual(bling.situacao_updates, [(12345, 99)])


class LogisticsStageTest(unittest.TestCase):
    LOGISTICS_SETTINGS = dict(
        ploomes_deal_logistics_stage_rules="110001615:110008939",
    )

    def test_updates_situacao_when_link_found(self):
        settings = make_settings(
            **self.LOGISTICS_SETTINGS, bling_situacao_pronto_faturar=42
        )
        bling = FakeBlingClient()
        ploomes = FakePloomesClient(make_deal(stage_id=110008939))
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        with patch(
            "app.services.sync_deal_to_bling_order.get_db_conn",
            return_value=FakeDbConn(fetchone_result=(12345, 777)),
        ):
            result = service.update_situacao_for_logistics_stage(55)

        self.assertEqual(result["action"], "situacao_atualizada")
        self.assertEqual(bling.situacao_updates, [(12345, 42)])

    def test_skips_when_no_link_found(self):
        settings = make_settings(
            **self.LOGISTICS_SETTINGS, bling_situacao_pronto_faturar=42
        )
        bling = FakeBlingClient()
        ploomes = FakePloomesClient(make_deal(stage_id=110008939))
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        with patch(
            "app.services.sync_deal_to_bling_order.get_db_conn",
            return_value=FakeDbConn(fetchone_result=None),
        ):
            result = service.update_situacao_for_logistics_stage(55)

        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["reason"], "pedido_nao_vinculado")
        self.assertEqual(bling.situacao_updates, [])

    def test_skips_when_stage_does_not_match(self):
        settings = make_settings(**self.LOGISTICS_SETTINGS)
        bling = FakeBlingClient()
        ploomes = FakePloomesClient(make_deal(stage_id=999999))
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        result = service.update_situacao_for_logistics_stage(55)

        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["reason"], "stage_nao_configurado")

    def test_skips_when_situacao_not_configured(self):
        settings = make_settings(**self.LOGISTICS_SETTINGS)  # bling_situacao_pronto_faturar=0 (default)
        bling = FakeBlingClient()
        ploomes = FakePloomesClient(make_deal(stage_id=110008939))
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        with patch(
            "app.services.sync_deal_to_bling_order.get_db_conn",
            return_value=FakeDbConn(fetchone_result=(12345, 777)),
        ):
            result = service.update_situacao_for_logistics_stage(55)

        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["reason"], "situacao_nao_configurada")
        self.assertEqual(bling.situacao_updates, [])


class DirectToLogisticsTest(unittest.TestCase):
    SETTINGS_KWARGS = dict(
        ploomes_deal_logistics_stage_rules="110001615:110008939",
        ploomes_deal_direct_to_logistics_rules="110001615:110006379,110006380,110355350:110008939",
        bling_situacao_pronto_faturar=42,
    )

    def test_creates_sales_order_when_jump_recognized(self):
        settings = make_settings(**self.SETTINGS_KWARGS)
        bling = FakeBlingClient(bling_products_by_code={"SKU-123": {"id": 700}})
        ploomes = FakePloomesClient(
            make_deal(stage_id=110008939),
            make_quote(),
            products={999: make_ploomes_product(settings)},
        )
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        # 1a leitura: previous_stage_id = 110006380 (Analise de Credito, esta na lista
        # configurada). 2a leitura: nenhum vinculo existente ainda (None).
        with patch(
            "app.services.sync_deal_to_bling_order.get_db_conn",
            return_value=FakeDbConn(fetchone_results=[(110006380,), None]),
        ):
            result = service.update_situacao_for_logistics_stage(55)

        self.assertEqual(result["action"], "created")
        self.assertEqual(result["bling_order_id"], 12345)
        self.assertEqual(bling.situacao_updates, [(12345, 42)])
        self.assertEqual(ploomes.updated_deals[0][1]["OtherProperties"][0]["FieldKey"], "deal_order")

    def test_skips_when_previous_stage_not_in_configured_list(self):
        settings = make_settings(**self.SETTINGS_KWARGS)
        bling = FakeBlingClient()
        ploomes = FakePloomesClient(make_deal(stage_id=110008939))
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        # previous_stage_id = 110006378 ("Novos Lead's"), fora da lista configurada.
        with patch(
            "app.services.sync_deal_to_bling_order.get_db_conn",
            return_value=FakeDbConn(fetchone_results=[(110006378,), None]),
        ):
            result = service.update_situacao_for_logistics_stage(55)

        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["reason"], "pedido_nao_vinculado")
        self.assertIsNone(bling.created_payload)

    def test_skips_when_deal_seen_for_the_first_time(self):
        settings = make_settings(**self.SETTINGS_KWARGS)
        bling = FakeBlingClient()
        ploomes = FakePloomesClient(make_deal(stage_id=110008939))
        service = DealToBlingOrderSyncService(settings, bling=bling, ploomes=ploomes)

        # nenhuma linha de rastreamento ainda (primeira vez que vemos esse Deal) e
        # nenhum vinculo de pedido -- os dois fetchone() retornam None.
        with patch(
            "app.services.sync_deal_to_bling_order.get_db_conn",
            return_value=FakeDbConn(fetchone_results=[None, None]),
        ):
            result = service.update_situacao_for_logistics_stage(55)

        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["reason"], "pedido_nao_vinculado")
        self.assertIsNone(bling.created_payload)


if __name__ == "__main__":
    unittest.main()
