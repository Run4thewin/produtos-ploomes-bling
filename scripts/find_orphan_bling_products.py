"""
Encontra produtos do Bling que nunca apareceram em nenhum pedido de venda nem NF-e.

Analise avulsa (nao persiste tabela nova):
1. Busca o detalhe de cada pedido em bling_orders (produto.id por item) -- unica
   fonte 100% confiavel de "produto foi vendido". Progresso salvo incrementalmente
   em relatorios/.orphan_orders_progress.json para poder retomar se cair no meio.
2. Casa itens de bling_nfe por codigo (quando presente) e por nome normalizado
   (fallback aproximado, mesma logica do backfill de partnumber) contra
   bling_produtos.
3. Produtos do Bling que nao aparecem em nenhuma das duas fontes = orfaos.

Uso:
    python scripts/find_orphan_bling_products.py
    python scripts/find_orphan_bling_products.py --limit-orders 100   # teste rapido
"""

import argparse
import csv
import json
import os
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import httpx
import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.clients.bling import BlingClient
from app.config import get_settings

PROGRESS_PATH = ROOT / "relatorios" / ".orphan_orders_progress.json"


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


def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    return {"done_order_ids": [], "product_ids_in_orders": []}


def save_progress(progress: dict) -> None:
    PROGRESS_PATH.parent.mkdir(exist_ok=True)
    PROGRESS_PATH.write_text(json.dumps(progress), encoding="utf-8")


def fetch_product_ids_from_orders(bling: BlingClient, conn, limit_orders: int | None) -> set[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM bling_orders ORDER BY id")
        order_ids = [row[0] for row in cur.fetchall()]
    if limit_orders:
        order_ids = order_ids[:limit_orders]

    progress = load_progress()
    done = set(progress["done_order_ids"])
    product_ids = set(progress["product_ids_in_orders"])
    pending = [oid for oid in order_ids if oid not in done]

    print(f"Pedidos totais: {len(order_ids)} | ja processados (retomado): {len(done)} | pendentes: {len(pending)}")

    for i, order_id in enumerate(pending, 1):
        try:
            order = bling.get_sales_order(order_id)
            for item in order.get("itens") or []:
                produto_id = (item.get("produto") or {}).get("id")
                if produto_id:
                    product_ids.add(produto_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                pass  # pedido excluido no Bling, ignora
            else:
                print(f"  aviso: erro ao buscar pedido {order_id}: {exc}")
        except Exception as exc:
            print(f"  aviso: erro ao buscar pedido {order_id}: {exc}")

        done.add(order_id)

        if i % 100 == 0:
            progress = {"done_order_ids": list(done), "product_ids_in_orders": list(product_ids)}
            save_progress(progress)
            print(f"  -> {i}/{len(pending)} pedidos processados nesta rodada | produtos unicos ate agora: {len(product_ids)}")

    progress = {"done_order_ids": list(done), "product_ids_in_orders": list(product_ids)}
    save_progress(progress)
    return product_ids


def fetch_product_matches_from_nfe(conn) -> tuple[set[str], set[int]]:
    """Retorna (codigos_batidos_por_codigo, ids_batidos_por_nome_aproximado)."""
    with conn.cursor() as cur:
        cur.execute("SELECT codigo, id, nome FROM bling_produtos WHERE codigo IS NOT NULL AND codigo <> ''")
        codigo_to_id: dict[str, int] = {}
        nome_index: dict[str, set[int]] = {}
        for codigo, pid, nome in cur:
            codigo_to_id[codigo.strip()] = pid
            nome_norm = normalize(nome)
            if nome_norm:
                nome_index.setdefault(nome_norm, set()).add(pid)

        cur.execute("SELECT raw_json->'itens' FROM bling_nfe WHERE raw_json ? 'itens'")
        matched_by_codigo: set[str] = set()
        matched_ids_by_name: set[int] = set()
        for (itens,) in cur:
            for item in itens or []:
                codigo = (item.get("codigo") or "").strip()
                if codigo and codigo in codigo_to_id:
                    matched_by_codigo.add(codigo)
                    continue
                nome_norm = normalize(item.get("descricao"))
                ids = nome_index.get(nome_norm)
                if ids and len(ids) == 1:
                    matched_ids_by_name |= ids

    return matched_by_codigo, matched_ids_by_name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit-orders", type=int, default=None, help="Limita quantos pedidos buscar (teste)")
    args = parser.parse_args()

    settings = get_settings()
    bling = BlingClient(settings)
    conn = get_db_conn()

    print("=== PRODUTOS BLING SEM VINCULO COM VENDA OU NOTA FISCAL ===\n")

    print("1/3 Buscando produto.id nos itens de todos os pedidos de venda (detalhe por pedido)...")
    started = time.monotonic()
    product_ids_in_orders = fetch_product_ids_from_orders(bling, conn, args.limit_orders)
    print(f"Concluido em {time.monotonic() - started:.0f}s | produtos distintos vendidos: {len(product_ids_in_orders)}\n")

    print("2/3 Casando itens de NF-e por codigo e por nome aproximado...")
    codigos_nfe, ids_nfe_por_nome = fetch_product_matches_from_nfe(conn)
    print(f"NF-e: {len(codigos_nfe)} codigos batidos diretamente | {len(ids_nfe_por_nome)} produtos batidos por nome\n")

    print("3/3 Cruzando com o catalogo completo do Bling...")
    with conn.cursor() as cur:
        cur.execute("SELECT id, codigo, nome, preco, situacao FROM bling_produtos")
        rows = cur.fetchall()
    conn.close()

    orphans = []
    total = 0
    for pid, codigo, nome, preco, situacao in rows:
        total += 1
        codigo = (codigo or "").strip()
        used = (
            pid in product_ids_in_orders
            or (codigo and codigo in codigos_nfe)
            or pid in ids_nfe_por_nome
        )
        if not used:
            orphans.append((pid, codigo, nome, preco, situacao))

    print(f"\n=== RESULTADO ===")
    print(f"Total de produtos no Bling: {total}")
    print(f"Com vinculo (pedido e/ou NF-e): {total - len(orphans)}")
    print(f"SEM vinculo (nem pedido, nem NF-e): {len(orphans)} ({len(orphans) / total * 100:.1f}%)")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = ROOT / "relatorios"
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / f"produtos_bling_sem_vinculo_{timestamp}.csv"

    with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["id", "codigo", "nome", "preco", "situacao"])
        for row in orphans:
            writer.writerow(row)

    print(f"\nRelatorio salvo em: {report_path}")


if __name__ == "__main__":
    main()
