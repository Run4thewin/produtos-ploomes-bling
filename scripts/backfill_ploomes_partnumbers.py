"""
Preenche o partnumber (SKU) dos produtos do Ploomes casando pelo nome exato com o Bling.

Para cada produto do Ploomes sem partnumber cadastrado, procura um produto na tabela
local bling_produtos (espelho do catalogo do Bling, carregado via blng_fetcher) cujo
nome normalizado seja identico. Se achar exatamente um, grava o Code nativo e o campo
customizado partnumber no Ploomes. Nomes ambiguos (mais de um produto no Bling com o
mesmo nome normalizado) ou sem correspondencia sao apenas reportados, nunca gravados
automaticamente.

Por padrao roda em modo dry-run (nao grava nada). Use --apply para gravar de fato.

O lado Bling e 100% local (SELECT no Postgres) -- nao consome nenhuma requisicao da
cota diaria do Bling. So o lado Ploomes (listagem + update_product) usa a API real,
via PloomesClient (rate-limited).

Pre-requisito: rode antes `python -m blng_fetcher.main --entity produtos --pages 999`
para popular/atualizar a tabela bling_produtos.

Uso:
    python scripts/backfill_ploomes_partnumbers.py                # dry-run, gera relatorio
    python scripts/backfill_ploomes_partnumbers.py --apply        # grava os matches unicos
    python scripts/backfill_ploomes_partnumbers.py --limit 50     # testa com poucos produtos
"""

import argparse
import csv
import os
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.clients.ploomes import PloomesClient
from app.config import get_settings
from app.services.mapping import get_other_property


def normalize(value: str | None) -> str:
    if not value:
        return ""
    without_accents = unicodedata.normalize("NFKD", str(value))
    ascii_value = without_accents.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_value.lower().split())


def get_db_conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def build_bling_name_index(conn) -> dict[str, str | None]:
    """Mapeia nome_normalizado -> codigo a partir da tabela local bling_produtos.

    Valor None marca nome ambiguo (mais de um codigo distinto com o mesmo nome
    normalizado) -- esses nomes nao sao usados para gravar automaticamente.
    """
    seen_codes: dict[str, set[str]] = defaultdict(set)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT codigo, nome FROM bling_produtos WHERE codigo IS NOT NULL AND codigo <> ''"
        )
        count = 0
        for codigo, nome in cur:
            codigo = (codigo or "").strip()
            nome_norm = normalize(nome)
            if codigo and nome_norm:
                seen_codes[nome_norm].add(codigo)
            count += 1

    index: dict[str, str | None] = {
        nome: (next(iter(codes)) if len(codes) == 1 else None) for nome, codes in seen_codes.items()
    }
    ambiguous = sum(1 for v in index.values() if v is None)
    print(
        f"Indice Bling pronto (local): {count} produtos lidos de bling_produtos | "
        f"{len(index)} nomes distintos ({ambiguous} ambiguos ignorados)."
    )
    return index


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="Grava os matches unicos no Ploomes (default: dry-run)")
    parser.add_argument("--limit", type=int, default=None, help="Limita quantos produtos Ploomes processar (teste)")
    parser.add_argument("--page-size", type=int, default=200, help="Tamanho de pagina na listagem do Ploomes")
    args = parser.parse_args()

    settings = get_settings()
    ploomes = PloomesClient(settings)
    conn = get_db_conn()

    print("=== BACKFILL PARTNUMBER PLOOMES <- BLING (por nome exato, via banco local) ===")
    print(f"Modo: {'APLICANDO (grava no Ploomes)' if args.apply else 'DRY-RUN (so relatorio)'}\n")

    print("1/2 Indexando produtos do Bling por nome (tabela local bling_produtos)...")
    bling_index = build_bling_name_index(conn)
    conn.close()

    print("\n2/2 Percorrendo produtos do Ploomes sem partnumber...")
    matched: list[dict] = []
    ambiguous: list[dict] = []
    not_found: list[dict] = []
    already_has = 0
    processed = 0

    for product in ploomes.iter_products(page_size=args.page_size):
        if args.limit and processed >= args.limit:
            break

        existing_partnumber = get_other_property(product, settings.ploomes_field_partnumber)
        if (existing_partnumber and str(existing_partnumber).strip()) or (product.get("Code") or "").strip():
            already_has += 1
            continue

        processed += 1
        nome_norm = normalize(product.get("Name"))
        codigo = bling_index.get(nome_norm)

        row = {
            "ploomes_id": product.get("Id"),
            "nome": product.get("Name"),
            "codigo_encontrado": codigo,
        }

        if nome_norm not in bling_index:
            not_found.append(row)
        elif codigo is None:
            ambiguous.append(row)
        else:
            matched.append(row)
            if args.apply:
                ploomes.update_product(
                    product["Id"],
                    {
                        "Code": codigo,
                        "OtherProperties": [
                            {"FieldKey": settings.ploomes_field_partnumber, "StringValue": codigo}
                        ],
                    },
                )

        if processed % 500 == 0:
            print(f"  -> {processed} produtos Ploomes sem partnumber avaliados...")

    print("\n=== RESULTADO ===")
    print(f"Ja tinham partnumber/Code: {already_has}")
    print(f"Avaliados (sem partnumber): {processed}")
    print(f"  -> match unico {'gravado' if args.apply else '(dry-run, nao gravado)'}: {len(matched)}")
    print(f"  -> ambiguo (nome bate em >1 produto Bling): {len(ambiguous)}")
    print(f"  -> sem correspondencia no Bling: {len(not_found)}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = ROOT / "relatorios"
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / f"backfill_partnumbers_{timestamp}.csv"

    with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["categoria", "ploomes_id", "nome", "codigo_encontrado"])
        for row in matched:
            writer.writerow(["match_unico", row["ploomes_id"], row["nome"], row["codigo_encontrado"]])
        for row in ambiguous:
            writer.writerow(["ambiguo", row["ploomes_id"], row["nome"], ""])
        for row in not_found:
            writer.writerow(["sem_correspondencia", row["ploomes_id"], row["nome"], ""])

    print(f"\nRelatorio salvo em: {report_path}")
    if not args.apply:
        print("\nNenhuma gravacao foi feita (dry-run). Revise o relatorio e rode com --apply para gravar os matches unicos.")


if __name__ == "__main__":
    main()
