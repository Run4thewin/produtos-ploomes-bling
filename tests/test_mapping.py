import unittest

from app.config import Settings
from app.services.mapping import map_bling_to_ploomes


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


if __name__ == "__main__":
    unittest.main()
