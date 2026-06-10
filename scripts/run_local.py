"""CLI local para carga inicial e reconciliacao sem Cloud Run."""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.sync import ProductSyncService

logging.basicConfig(level=logging.INFO)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync local Bling -> Ploomes")
    parser.add_argument(
        "command",
        choices=["full-sync", "reconcile", "reconcile-dry"],
        help="full-sync: carga inicial | reconcile: corrige divergencias",
    )
    args = parser.parse_args()

    service = ProductSyncService()

    if args.command == "full-sync":
        print(service.full_sync())
    elif args.command == "reconcile":
        print(service.reconcile(apply_fixes=True))
    else:
        print(service.reconcile(apply_fixes=False))


if __name__ == "__main__":
    main()
