"""Testa criacao de produto no Ploomes com o mapeamento Bling -> Ploomes."""

import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.clients.ploomes import PloomesClient
from app.config import get_settings
from app.services.mapping import build_product_name, map_bling_to_ploomes

logging.basicConfig(level=logging.INFO)


def main() -> None:
    settings = get_settings()
    client = PloomesClient(settings)

    test_code = f"TEST-BLING-SYNC-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    bling_fake = {
        "id": 0,
        "codigo": test_code,
        "marca": "SCHNEIDER",
        "descricaoCurta": "Disjuntor monopolar 20A",
        "preco": 149.9,
        "situacao": "A",
        "pesoLiquido": 0.25,
        "dimensoes": {"largura": 10, "altura": 5, "profundidade": 8},
        "tributacao": {"ncm": "85362000"},
    }

    expected_name = build_product_name(
        bling_fake["marca"],
        bling_fake["codigo"],
        bling_fake["descricaoCurta"],
    )
    payload = map_bling_to_ploomes(bling_fake, settings)
    print("Nome esperado:", expected_name)
    print("Payload:", payload)

    existing = client.get_product_by_code(test_code)
    if existing:
        print(f"Produto ja existe: Id={existing['Id']}")
        return

    try:
        result = client.create_product(payload)
    except httpx.HTTPStatusError as exc:
        print(f"CREATE_FAIL status={exc.response.status_code}")
        print(exc.response.text)
        raise SystemExit(1) from exc

    created = result.get("value", [result])[0] if result.get("value") else result
    print("CREATE_OK")
    print(f"Id={created.get('Id')} Code={created.get('Code')} Name={created.get('Name')}")

    found = client.get_product_by_code(test_code)
    if not found:
        print("CONFIRM_FAIL: produto nao encontrado apos criacao")
        raise SystemExit(1)

    print("CONFIRM_OK")
    print(
        f"Id={found.get('Id')} Name={found.get('Name')} "
        f"UnitPrice={found.get('UnitPrice')} GroupId={found.get('GroupId')}"
    )


if __name__ == "__main__":
    main()
