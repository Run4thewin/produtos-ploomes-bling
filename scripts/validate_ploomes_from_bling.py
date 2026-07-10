"""
Valida se os produtos do Ploomes que tem Code (SKU) preenchido estao com os
campos corretos em relacao ao produto correspondente no Bling.

Usa a mesma logica de comparacao do reconcile() (app/services/mapping.diff_fields),
mas busca os dados do Bling na tabela local bling_produtos em vez de bater na API
(evita ~200k GETs individuais).

Uso:
    python scripts/validate_ploomes_from_bling.py                # relatorio completo
    python scripts/validate_ploomes_from_bling.py --limit 500     # amostra rapida
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.clients.ploomes import PloomesClient
from app.config import get_settings
from app.services.mapping import diff_fields


def get_db_conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def build_bling_index_by_codigo(conn) -> dict[str, dict]:
    """codigo -> dict no formato bruto da API do Bling (via raw_json ja salvo)."""
    index: dict[str, dict] = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT codigo, raw_json FROM bling_produtos WHERE codigo IS NOT NULL AND codigo <> ''"
        )
        for codigo, raw_json in cur:
            codigo = (codigo or "").strip()
            if codigo:
                index[codigo] = raw_json
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="Limita quantos produtos Ploomes validar (teste)")
    parser.add_argument("--page-size", type=int, default=200, help="Tamanho de pagina na listagem do Ploomes")
    args = parser.parse_args()

    settings = get_settings()
    ploomes = PloomesClient(settings)
    conn = get_db_conn()

    print("=== VALIDACAO PLOOMES <- BLING (produtos com Code preenchido) ===\n")
    print("1/2 Indexando produtos do Bling por codigo (tabela local bling_produtos)...")
    bling_index = build_bling_index_by_codigo(conn)
    conn.close()
    print(f"Indice pronto: {len(bling_index)} codigos Bling.\n")

    print("2/2 Validando produtos do Ploomes com Code preenchido...")
    ok = 0
    divergent: list[dict] = []
    orphan: list[dict] = []  # Code no Ploomes nao existe (mais) no Bling
    evaluated = 0

    field_counter: Counter = Counter()

    for product in ploomes.iter_products(page_size=args.page_size):
        code = (product.get("Code") or "").strip()
        if not code:
            continue
        if args.limit and evaluated >= args.limit:
            break
        evaluated += 1

        bling_product = bling_index.get(code)
        if not bling_product:
            orphan.append({"ploomes_id": product.get("Id"), "code": code, "name": product.get("Name")})
            continue

        divergences = diff_fields(bling_product, product, settings)
        if divergences:
            for f in divergences:
                field_counter[f] += 1
            divergent.append(
                {
                    "ploomes_id": product.get("Id"),
                    "code": code,
                    "name": product.get("Name"),
                    "campos_divergentes": ",".join(divergences),
                }
            )
        else:
            ok += 1

        if evaluated % 5000 == 0:
            print(f"  -> {evaluated} produtos avaliados... (ok={ok} divergentes={len(divergent)} orfaos={len(orphan)})")

    print("\n=== RESULTADO ===")
    print(f"Total avaliado (Ploomes com Code preenchido): {evaluated}")
    print(f"  -> OK (identico ao Bling): {ok} ({ok / evaluated * 100:.1f}%)" if evaluated else "  -> OK: 0")
    print(f"  -> Divergente (algum campo diferente): {len(divergent)}")
    print(f"  -> Orfao (Code nao existe mais no Bling local): {len(orphan)}")

    if field_counter:
        print("\nCampos mais divergentes:")
        for field, count in field_counter.most_common():
            print(f"  {field}: {count}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = ROOT / "relatorios"
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / f"validacao_ploomes_bling_{timestamp}.csv"

    with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["categoria", "ploomes_id", "code", "name", "campos_divergentes"])
        for row in divergent:
            writer.writerow(["divergente", row["ploomes_id"], row["code"], row["name"], row["campos_divergentes"]])
        for row in orphan:
            writer.writerow(["orfao", row["ploomes_id"], row["code"], row["name"], ""])

    print(f"\nRelatorio salvo em: {report_path}")


if __name__ == "__main__":
    main()
