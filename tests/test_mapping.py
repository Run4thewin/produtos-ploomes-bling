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

    def test_descricao_curta_mirrors_nome(self):
        # descricaoCurta deve ser sempre o mesmo texto de nome, para o item do
        # pedido/NF-e (que puxa a descricao do produto) nunca divergir do que
        # esta cadastrado -- mesmo quando nome inclui o prefixo fabricante+partnumber.
        settings = Settings()
        ploomes_product = {
            "Id": 1000,
            "Name": "Disjuntor monopolar 20A",  # nao comeca com fabricante+partnumber
            "UnitPrice": 50,
            "Suspended": False,
            "OtherProperties": [
                {"FieldKey": settings.ploomes_field_fabricante, "StringValue": "ACME"},
                {"FieldKey": settings.ploomes_field_partnumber, "StringValue": "SKU-999"},
            ],
        }

        payload = map_ploomes_to_bling(ploomes_product, settings)

        self.assertEqual(payload["nome"], "ACME SKU-999 Disjuntor monopolar 20A")
        self.assertEqual(payload["descricaoCurta"], payload["nome"])

    def test_descricao_curta_mirrors_nome_even_when_name_duplicates_prefix(self):
        # Reproduz o caso real observado: o Name do Ploomes ja menciona
        # fabricante+partnumber no FIM do texto (nao no inicio), entao o guard
        # de deduplicacao de build_product_name nao pega e "nome" sai duplicado.
        # descricaoCurta deve espelhar esse "nome" (duplicado e tudo) -- e' o
        # comportamento escolhido: os dois campos nunca divergem entre si.
        settings = Settings()
        ploomes_product = {
            "Id": 1001,
            "Name": "Tampa Partida Retratil Rocadeira Toyama Tbc43sh",
            "UnitPrice": 100,
            "Suspended": False,
            "OtherProperties": [
                {"FieldKey": settings.ploomes_field_fabricante, "StringValue": "Toyama"},
                {"FieldKey": settings.ploomes_field_partnumber, "StringValue": "Tbc43sh"},
            ],
        }

        payload = map_ploomes_to_bling(ploomes_product, settings)

        self.assertEqual(
            payload["nome"],
            "Toyama Tbc43sh Tampa Partida Retratil Rocadeira Toyama Tbc43sh",
        )
        self.assertEqual(payload["descricaoCurta"], payload["nome"])


if __name__ == "__main__":
    unittest.main()
