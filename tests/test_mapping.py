import unittest

from app.config import Settings
from app.services.mapping import map_bling_to_ploomes, map_ploomes_to_bling


class BlingToPloomesMappingTest(unittest.TestCase):
    def test_maps_product_without_brand(self):
        payload = map_bling_to_ploomes(
            {
                "id": 123,
                "codigo": "ABC123",
                "marca": "",
                "descricaoCurta": "Disjuntor monopolar 20A",
                "preco": 149.9,
                "situacao": "A",
            },
            Settings(),
        )

        self.assertEqual(payload["Name"], "ABC123 Disjuntor monopolar 20A")
        self.assertEqual(payload["Code"], "ABC123")
        self.assertFalse(
            any(
                item.get("FieldKey") == Settings().ploomes_field_fabricante
                for item in payload.get("OtherProperties", [])
            )
        )


class PloomesToBlingMappingTest(unittest.TestCase):
    def test_breve_descricao_falls_back_to_full_name_when_stripping_leaves_nothing(self):
        settings = Settings()
        ploomes_product = {
            "Id": 999,
            "Name": "ACME SKU-123",  # so fabricante + partnumber, nada mais
            "UnitPrice": 100,
            "Suspended": False,
            "OtherProperties": [
                {"FieldKey": settings.ploomes_field_fabricante, "StringValue": "ACME"},
                {"FieldKey": settings.ploomes_field_partnumber, "StringValue": "SKU-123"},
            ],
        }

        payload = map_ploomes_to_bling(ploomes_product, settings)

        self.assertEqual(payload["descricaoCurta"], "ACME SKU-123")
        self.assertEqual(payload["codigo"], "SKU-123")
        self.assertEqual(payload["nome"], "ACME SKU-123")  # nao duplicado


if __name__ == "__main__":
    unittest.main()
