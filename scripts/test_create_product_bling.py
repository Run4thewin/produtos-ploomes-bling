"""Testa criacao de produto no Bling a partir de dados do Ploomes."""

import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.clients.bling import BlingClient
from app.config import get_settings
from app.services.mapping import map_ploomes_to_bling
from app.services.sync_ploomes_to_bling import PloomesToBlingSyncService

logging.basicConfig(level=logging.INFO)


def main() -> None:
    settings = get_settings()
    test_code = f"TEST-PLOOMES-BLING-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    ploomes_fake = {
        "Id": 0,
        "Code": test_code,
        "Name": f"SCHNEIDER {test_code} Contator auxiliar 220V",
        "UnitPrice": 189.5,
        "Suspended": False,
        "OtherProperties": [
            {
                "FieldKey": settings.ploomes_field_fabricante,
                "StringValue": "SCHNEIDER",
            },
            {
                "FieldKey": settings.ploomes_field_partnumber,
                "StringValue": test_code,
            },
            {
                "FieldKey": settings.ploomes_field_ncm,
                "IntegerValue": 85364900,
            },
            {
                "FieldKey": settings.ploomes_field_descricao,
                "BigStringValue": "Peso: 0.35 kg | Dimensões: 12 x 8 x 6 cm",
            },
        ],
    }

    payload = map_ploomes_to_bling(ploomes_fake, settings)
    print("Payload Bling:", payload)

    service = PloomesToBlingSyncService(settings)
    bling = BlingClient(settings)
    existing = bling.get_product_by_code(test_code)
    if existing:
        print(f"Produto ja existe no Bling: {existing.get('id')}")
        return

    result = service.upsert_from_ploomes_product(ploomes_fake, action="create")
    print("RESULT:", result)


if __name__ == "__main__":
    main()
