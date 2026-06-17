import unittest

from app.config import Settings
from app.services.ploomes_webhook import parse_ploomes_deal_webhook
from app.services.sync_deal_to_bling_order import DealToBlingOrderSyncService


class FakePloomesClient:
    def __init__(self, deal: dict, quote: dict | None = None):
        self.deal = deal
        self.quote = quote
        self.updated_deals: list[tuple[int | str, dict]] = []

    def get_deal_by_id(self, deal_id: int | str) -> dict:
        return self.deal

    def get_latest_quote_by_deal(self, deal_id: int | str) -> dict | None:
        return self.quote

    def update_deal(self, deal_id: int | str, payload: dict) -> dict:
        self.updated_deals.append((deal_id, payload))
        return payload


class FakeBlingClient:
    def __init__(self):
        self.created_payload: dict | None = None

    def get_contact_by_document(self, document_number: str | None) -> dict | None:
        contacts = {
            "12345678000199": {"id": 100, "nome": "Cliente"},
            "98765432000111": {"id": 200, "nome": "Transportadora"},
        }
        return contacts.get(document_number or "")

    def create_sales_order(self, payload: dict) -> dict:
        self.created_payload = payload
        return {"id": 12345}

    def get_sales_order(self, order_id: int | str) -> dict:
        return {"id": order_id, "numero": "9876"}


def make_settings() -> Settings:
    return Settings(
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
        bling_freight_methods="CIF:R",
        bling_seller_map="110010961:15596362133",
    )


def make_deal(order_reference: str | None = None) -> dict:
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
        "StageId": 110020807,
        "OwnerId": 110010961,
        "Contact": {"Name": "Cliente", "CNPJ": "12.345.678/0001-99", "CPF": None},
        "OtherProperties": properties,
    }


def make_quote() -> dict:
    return {
        "Id": 77,
        "Products": [
            {
                "ProductName": "Produto Teste",
                "Quantity": 2,
                "UnitPrice": 100,
                "Discount": 10,
            }
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
        bling = FakeBlingClient()
        ploomes = FakePloomesClient(make_deal(), make_quote())
        service = DealToBlingOrderSyncService(make_settings(), bling=bling, ploomes=ploomes)

        result = service.create_bling_order_from_deal(55)

        self.assertEqual(result["action"], "created")
        self.assertEqual(result["bling_order_id"], 12345)
        self.assertEqual(bling.created_payload["contato"]["id"], 100)
        self.assertEqual(bling.created_payload["vendedor"]["id"], 15596362133)
        self.assertEqual(len(bling.created_payload["parcelas"]), 2)
        self.assertEqual(ploomes.updated_deals[0][1]["StageId"], 110008939)

    def test_service_skips_existing_bling_order_reference(self):
        bling = FakeBlingClient()
        ploomes = FakePloomesClient(
            make_deal("Pedido Bling 9876: https://www.bling.com.br/vendas.php#edit/12345"),
            make_quote(),
        )
        service = DealToBlingOrderSyncService(make_settings(), bling=bling, ploomes=ploomes)

        result = service.create_bling_order_from_deal(55)

        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["reason"], "already_processed")
        self.assertIsNone(bling.created_payload)
        self.assertEqual(ploomes.updated_deals, [])


if __name__ == "__main__":
    unittest.main()
