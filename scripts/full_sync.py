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
from datetime import datetime
from pathlib import Path

# garante que a raiz do projeto está no path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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

    error_file_path = None
    if stats["errors"] > 0:
        logger.warning("Erros encontrados (%s). Verifique os logs acima.", stats["errors"])
        
        # Cria a pasta de logs se ela não existir
        logs_dir = ROOT / "logs"
        logs_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        error_file_path = logs_dir / f"erros_carga_inicial_{timestamp}.txt"
        
        try:
            with open(error_file_path, "w", encoding="utf-8") as f:
                f.write("==================================================\n")
                f.write("RELATORIO DE ERROS - CARGA INICIAL BLING -> PLOOMES\n")
                f.write(f"Data/Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Total de erros: {stats['errors']}\n")
                f.write("==================================================\n\n")
                
                for idx, item in enumerate(result.get("errors_detail", []), 1):
                    f.write(f"{idx}. Produto Bling ID: {item.get('bling_id')} | SKU/Codigo: {item.get('code') or '-'}\n")
                    f.write(f"   Motivo do Erro: {item.get('error')}\n")
                    f.write("-" * 50 + "\n")
            
            logger.info("Relatorio detalhado de erros salvo em: logs/%s", error_file_path.name)
        except Exception as exc:
            logger.error("Nao foi possivel salvar o arquivo de relatorio de erros: %s", exc)

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
    if error_file_path:
        print(f"  Relatorio de Erros: logs/{error_file_path.name}")
    print(f"  Tempo            : {result['elapsed_seconds']}s")
    print(f"  Taxa             : {result['products_per_second']} produtos/s")

    sys.exit(1 if stats["errors"] > 0 else 0)


if __name__ == "__main__":
    main()
