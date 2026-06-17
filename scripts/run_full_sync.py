"""Carga inicial Bling -> Ploomes com logs completos."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.logging_config import setup_logging
from app.services.sync import ProductSyncService


def main() -> None:
    parser = argparse.ArgumentParser(description="Full sync Bling -> Ploomes")
    parser.add_argument(
        "--log-file",
        help="Arquivo de log (default: logs/full-sync-YYYYMMDD-HHMMSS.log)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        help="Workers paralelos (default: SYNC_WORKERS do .env ou 5)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Processa apenas os N primeiros produtos (ex: 5 para teste piloto)",
    )
    args = parser.parse_args()

    settings = get_settings()
    if args.log_file:
        settings.sync_log_file = args.log_file
    elif not settings.sync_log_file:
        log_dir = ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        settings.sync_log_file = str(log_dir / f"full-sync-{timestamp}.log")

    if args.workers:
        settings.sync_workers = max(1, args.workers)

    setup_logging(settings)

    result = ProductSyncService(settings).full_sync(limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
