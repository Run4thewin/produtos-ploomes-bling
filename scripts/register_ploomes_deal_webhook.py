"""Registra webhook de Deals no Ploomes para gerar pedido no Bling."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from app.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--callback-url",
        required=True,
        help="Ex: https://seu-servico/webhooks/ploomes/deals?validation_key=...",
    )
    parser.add_argument("--validation-key", required=True, help="Chave de validacao do webhook")
    parser.add_argument(
        "--entity-id",
        type=int,
        default=None,
        help="EntityId de Deals no Ploomes. Padrao: PLOOMES_DEAL_ENTITY_ID.",
    )
    parser.add_argument(
        "--actions",
        default="update",
        help="Acoes separadas por virgula: create,update,delete",
    )
    args = parser.parse_args()

    settings = get_settings()
    entity_id = args.entity_id or settings.ploomes_deal_entity_id
    if not entity_id:
        raise SystemExit("Informe --entity-id ou configure PLOOMES_DEAL_ENTITY_ID.")

    headers = {"User-Key": settings.ploomes_user_key, "Content-Type": "application/json"}
    action_map = {"create": 1, "update": 2, "delete": 3}

    for action_name in [item.strip().lower() for item in args.actions.split(",") if item.strip()]:
        action_id = action_map.get(action_name)
        if not action_id:
            raise SystemExit(f"Acao invalida: {action_name}")

        payload = {
            "EntityId": entity_id,
            "ActionId": action_id,
            "CallbackUrl": args.callback_url,
            "ValidationKey": args.validation_key,
        }
        response = httpx.post(
            f"{settings.ploomes_api_base}/Webhooks",
            headers=headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        print(f"Webhook Deal registrado: action={action_name} -> {args.callback_url}")


if __name__ == "__main__":
    main()
