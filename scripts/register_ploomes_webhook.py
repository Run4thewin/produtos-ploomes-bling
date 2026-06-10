"""Registra webhook de produtos no Ploomes (Create/Update)."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from app.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--callback-url", required=True, help="Ex: https://seu-servico/webhooks/ploomes")
    parser.add_argument("--validation-key", required=True, help="Chave de validacao do webhook")
    parser.add_argument(
        "--actions",
        default="create,update",
        help="Acoes separadas por virgula: create,update",
    )
    args = parser.parse_args()

    settings = get_settings()
    headers = {"User-Key": settings.ploomes_user_key, "Content-Type": "application/json"}
    action_map = {"create": 1, "update": 2}

    for action_name in [item.strip().lower() for item in args.actions.split(",") if item.strip()]:
        action_id = action_map.get(action_name)
        if not action_id:
            raise SystemExit(f"Acao invalida: {action_name}")

        payload = {
            "EntityId": settings.ploomes_product_entity_id,
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
        print(f"Webhook registrado: action={action_name} -> {args.callback_url}")


if __name__ == "__main__":
    main()
