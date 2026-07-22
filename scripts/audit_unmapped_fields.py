"""
scripts/audit_unmapped_fields.py
Compara o raw_json realmente gravado com as colunas mapeadas nas specs e
aponta campos que a API devolve mas nao viram coluna tipada.

Usa os dados ja no banco (nao gasta quota da API).

Uso:
    python scripts/audit_unmapped_fields.py
    python scripts/audit_unmapped_fields.py --entity contacts --sample 500
    python scripts/audit_unmapped_fields.py --min-fill 10   # so >=10% preenchido
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

import os  # noqa: E402

from blng_fetcher.specs import SPECS  # noqa: E402
from blng_fetcher.specs.base import INFRA_COLUMNS  # noqa: E402


def _env(k, d=""):
    return os.environ.get(k, d).strip().strip('"')


def connect():
    last = None
    for _ in range(5):
        try:
            return psycopg2.connect(
                host=_env("DB_HOST"), port=int(_env("DB_PORT", "5432") or 5432),
                dbname=_env("DB_NAME"), user=_env("DB_USER"),
                password=_env("DB_PASSWORD"), connect_timeout=15,
            )
        except psycopg2.OperationalError as exc:
            last = exc
            time.sleep(3)
    raise last


def snake(name: str) -> str:
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.replace("-", "_").lower()


def flatten(obj: dict, prefix: str = "") -> dict:
    """Achata escalares do topo + escalares de dicts de 1 nivel (mesma regra
    do gerador de specs). Arrays viram marcador [] para sinalizar coleção."""
    out = {}
    for k, v in obj.items():
        path = f"{prefix}{k}"
        if isinstance(v, dict):
            for sk, sv in v.items():
                if isinstance(sv, (dict, list)):
                    continue
                out[f"{path}.{sk}"] = sv
        elif isinstance(v, list):
            out[f"{path}[]"] = v
        else:
            out[path] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entity", help="so uma entidade")
    ap.add_argument("--sample", type=int, default=300, help="registros amostrados")
    ap.add_argument("--min-fill", type=float, default=1.0,
                    help="%% minimo de preenchimento p/ reportar (default 1)")
    args = ap.parse_args()

    conn = connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema='public' AND table_name LIKE 'bling\\_%'"
    )
    existing = {r[0] for r in cur.fetchall()}

    targets = [SPECS[args.entity]] if args.entity else sorted(
        SPECS.values(), key=lambda s: s.name)

    for spec in targets:
        if not spec.enabled or spec.table not in existing:
            continue
        cur.execute(
            f"SELECT raw_json FROM {spec.table} WHERE raw_json IS NOT NULL LIMIT %s",
            (args.sample,),
        )
        rows = [r[0] for r in cur.fetchall()]
        if not rows:
            continue

        mapped = {f.path for f in spec.fields if f.path}
        mapped |= {f.column for f in spec.fields}
        # colunas derivadas de compute nao tem path; usa o nome snake como pista
        mapped |= {snake(c) for c in mapped if c}

        counts: dict[str, int] = {}
        for raw in rows:
            data = raw if isinstance(raw, dict) else json.loads(raw)
            for path, val in flatten(data).items():
                if val in (None, "", [], {}, 0):
                    continue
                counts[path] = counts.get(path, 0) + 1

        faltando = []
        for path, n in counts.items():
            base = path.rstrip("[]")
            if base in mapped or snake(base.replace(".", "_")) in mapped:
                continue
            if base == spec.id_path or base == "id":
                continue
            if snake(base.split(".")[-1]) in {snake(c) for c in mapped}:
                continue
            pct = n / len(rows) * 100
            if pct >= args.min_fill:
                faltando.append((pct, path, n))

        if not faltando:
            continue
        print(f"\n=== {spec.name}  ({spec.table}, amostra={len(rows)}) ===")
        for pct, path, n in sorted(faltando, reverse=True):
            tipo = "lista" if path.endswith("[]") else "campo"
            print(f"  {pct:5.1f}%  {path:45} {tipo}")

    conn.close()


if __name__ == "__main__":
    main()
