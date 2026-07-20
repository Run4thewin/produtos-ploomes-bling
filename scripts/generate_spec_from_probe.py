"""
scripts/generate_spec_from_probe.py
Gera rascunhos de FieldSpec (python) e CREATE TABLE (sql) a partir dos JSONs
salvos por probe_bling_endpoints.py.

Uso:
    python scripts/generate_spec_from_probe.py                  # todos os slugs com JSON
    python scripts/generate_spec_from_probe.py --only vendedores

Saida: relatorios/bling_probe/drafts/<slug>_spec.py e <slug>_table.sql

Os rascunhos DEVEM ser revisados a mao antes de entrar em
blng_fetcher/specs/expansion.py e scripts/sql/003_bling_new_entities.sql:
- amostras pequenas podem inferir tipo errado (int que na verdade e' decimal);
- objetos aninhados sao achatados 1 nivel; arrays ficam so' no raw_json.
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
PROBE_DIR = ROOT / "relatorios" / "bling_probe"
DRAFT_DIR = PROBE_DIR / "drafts"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")

# colunas de infraestrutura geridas pelo engine — nunca viram FieldSpec
RESERVED = {"id", "created_at", "updated_at", "raw_json", "source_hash", "deleted_at"}


def snake(name: str) -> str:
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.replace("-", "_").lower()


def infer(value) -> tuple[str, str | None]:
    """-> (sql_type, transform)"""
    if isinstance(value, bool):
        return "boolean", None
    if isinstance(value, int):
        return "bigint", None
    if isinstance(value, float):
        return "numeric", "float"
    if isinstance(value, str):
        if DATETIME_RE.match(value):
            return "timestamp", "_parse_dt"
        if DATE_RE.match(value):
            return "date", "_parse_date"
    return "text", None


def collect_fields(sample: dict) -> list[dict]:
    """Achata escalares do topo + escalares de dicts de 1 nivel."""
    fields: list[dict] = []
    seen: set[str] = set()

    def add(column: str, path: str, value):
        if column in RESERVED or column in seen:
            return
        seen.add(column)
        sql_type, transform = infer(value)
        fields.append({"column": column, "path": path,
                       "sql_type": sql_type, "transform": transform,
                       "sample": value})

    for key, value in sample.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, (dict, list)):
                    continue  # nivel 2+ fica no raw_json
                add(f"{snake(key)}_{snake(sub_key)}", f"{key}.{sub_key}", sub_value)
        elif isinstance(value, list):
            continue  # arrays ficam no raw_json
        elif key != "id":
            add(snake(key), key, value)
    return fields


def merge_samples(samples: list[dict]) -> list[dict]:
    """Une campos de varias amostras (a 1a ocorrencia nao-nula define o tipo)."""
    merged: dict[str, dict] = {}
    for sample in samples:
        for f in collect_fields(sample):
            existing = merged.get(f["column"])
            if existing is None:
                merged[f["column"]] = f
            elif existing["sample"] is None and f["sample"] is not None:
                merged[f["column"]] = f  # refina tipo com valor nao-nulo
    return list(merged.values())


def render_spec(slug: str, fields: list[dict]) -> str:
    name = slug.replace("-", "_")
    lines = [
        f"# Rascunho gerado de {slug}_detail.json/{slug}_list.json — REVISAR antes de usar.",
        f'{name.upper()}_FIELDS: tuple[FieldSpec, ...] = (',
    ]
    for f in fields:
        args = [f'"{f["column"]}"', f'"{f["path"]}"']
        if f["sql_type"] != "text":
            args.append(f'sql_type="{f["sql_type"]}"')
        if f["transform"]:
            args.append(f'transform={f["transform"]}')
        lines.append(f"    FieldSpec({', '.join(args)}),  # ex: {f['sample']!r}")
    lines.append(")")
    return "\n".join(lines) + "\n"


def render_table(slug: str, fields: list[dict]) -> str:
    table = "bling_" + slug.replace("-", "_")
    cols = ["    id               bigint PRIMARY KEY"]
    for f in fields:
        cols.append(f"    {f['column']:<20} {f['sql_type']}")
    cols += [
        "    created_at       timestamp NOT NULL DEFAULT now()",
        "    updated_at       timestamp NOT NULL DEFAULT now()",
        "    raw_json         jsonb",
        "    source_hash      text",
        "    deleted_at       timestamptz",
    ]
    body = ",\n".join(cols)
    return (
        f"-- Rascunho gerado da sondagem — REVISAR antes de usar.\n"
        f"CREATE TABLE IF NOT EXISTS {table} (\n{body}\n);\n"
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO api_user;\n"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="slugs separados por virgula")
    args = parser.parse_args()
    only = set(args.only.split(",")) if args.only else None

    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    slugs = sorted({p.name.rsplit("_", 1)[0] for p in PROBE_DIR.glob("*_list.json")})

    for slug in slugs:
        if only and slug not in only:
            continue
        samples: list[dict] = []
        detail = PROBE_DIR / f"{slug}_detail.json"
        if detail.exists():
            samples.append(json.loads(detail.read_text(encoding="utf-8")))
        listing = PROBE_DIR / f"{slug}_list.json"
        if listing.exists():
            samples.extend(json.loads(listing.read_text(encoding="utf-8")))
        samples = [s for s in samples if isinstance(s, dict)]
        if not samples:
            print(f"{slug}: sem amostras, pulando")
            continue

        fields = merge_samples(samples)
        (DRAFT_DIR / f"{slug}_spec.py").write_text(render_spec(slug, fields), encoding="utf-8")
        (DRAFT_DIR / f"{slug}_table.sql").write_text(render_table(slug, fields), encoding="utf-8")
        print(f"{slug}: {len(fields)} campos -> drafts/{slug}_spec.py + _table.sql")


if __name__ == "__main__":
    main()
