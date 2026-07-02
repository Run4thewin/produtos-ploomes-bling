"""
Carga inicial de produtos Bling -> Ploomes.

Uso:
    python scripts/full_sync.py
    python scripts/full_sync.py --limit 5      # piloto com 5 produtos
    python scripts/full_sync.py --log-file logs/full-sync.log
"""

import argparse
import logging
import sys
import os

# garante que a raiz do projeto está no path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.logging_config import setup_logging
from app.services.sync import ProductSyncService


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga inicial Bling → Ploomes")
    parser.add_argument("--limit", type=int, default=None, help="Limita qtd de produtos (piloto)")
    parser.add_argument("--log-file", default="", help="Caminho para arquivo de log (opcional)")
    args = parser.parse_args()

    os.environ.setdefault("SYNC_LOG_FILE", args.log_file)

    setup_logging()
    logger = logging.getLogger(__name__)

    settings = get_settings()
    if not settings.ploomes_user_key:
        logger.error("PLOOMES_USER_KEY não configurado no .env")
        sys.exit(1)
    if not settings.bling_client_id:
        logger.error("BLING_CLIENT_ID não configurado no .env")
        sys.exit(1)

    logger.info("=== INICIO CARGA INICIAL BLING -> PLOOMES | limit=%s ===", args.limit or "todos")

    result = ProductSyncService().full_sync(limit=args.limit)

    stats = result["stats"]
    logger.info(
        "=== FIM | total=%s created=%s updated=%s skipped=%s errors=%s elapsed=%ss",
        stats["total"],
        stats["created"],
        stats["updated"],
        stats["skipped"],
        stats["errors"],
        result["elapsed_seconds"],
    )

    if stats["errors"] > 0:
        logger.warning("Erros encontrados (%s). Verifique os logs acima.", stats["errors"])
        for item in result.get("errors_detail", []):
            logger.warning(
                "  ERRO bling_id=%s code=%s | %s",
                item.get("bling_id"),
                item.get("code") or "-",
                item.get("error"),
            )

    print(f"\nResultado:")
    print(f"  Total processado : {stats['total']}")
    print(f"  Criados          : {stats['created']}")
    print(f"  Atualizados      : {stats['updated']}")
    print(f"  Ignorados        : {stats['skipped']}")
    print(f"  Erros            : {stats['errors']}")
    print(f"  Tempo            : {result['elapsed_seconds']}s")
    print(f"  Taxa             : {result['products_per_second']} produtos/s")

    sys.exit(1 if stats["errors"] > 0 else 0)


if __name__ == "__main__":
    main()
