"""
scripts/generate_ddl_from_specs.py
Gera scripts/sql/003_bling_new_entities.sql a partir das specs de
blng_fetcher/specs/expansion.py — garante que DDL e spec nunca divergem.

Uso: python scripts/generate_ddl_from_specs.py
(Re-rode sempre que expansion.py mudar; o arquivo e' sobrescrito.)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from blng_fetcher.specs.expansion import EXPANSION_SPECS  # noqa: E402

OUT = ROOT / "scripts" / "sql" / "003_bling_new_entities.sql"

SQL_TYPES = {
    "text": "text",
    "bigint": "bigint",
    "numeric": "numeric",
    "boolean": "boolean",
    "date": "date",
    "timestamp": "timestamp without time zone",
    "jsonb": "jsonb",
}

HEADER = """\
-- 003_bling_new_entities.sql
-- GERADO por scripts/generate_ddl_from_specs.py a partir de
-- blng_fetcher/specs/expansion.py — nao editar a mao; re-gerar.
--
-- Requer privilegio de owner do schema (api_user nao tem CREATE TABLE).
-- Rode com uma credencial admin/postgres:
--   psql "host=<host> port=5432 dbname=<db> user=postgres" \\
--        -f scripts/sql/003_bling_new_entities.sql
--
-- Idempotente (IF NOT EXISTS).

BEGIN;
"""


def render(spec) -> str:
    lines = [f"-- {spec.name} ({spec.endpoint})"]
    lines.append(f"CREATE TABLE IF NOT EXISTS {spec.table} (")
    cols = ["    id                bigint PRIMARY KEY"]
    for f in spec.fields:
        sql_type = SQL_TYPES[f.sql_type]
        cols.append(f"    {f.column:<26} {sql_type}")
    cols += [
        "    created_at        timestamp without time zone NOT NULL DEFAULT now()",
        "    updated_at        timestamp without time zone NOT NULL DEFAULT now()",
        "    raw_json          jsonb",
        "    source_hash       text",
        "    deleted_at        timestamptz",
    ]
    lines.append(",\n".join(cols))
    lines.append(");")
    lines.append(f"GRANT SELECT, INSERT, UPDATE ON {spec.table} TO api_user;")
    return "\n".join(lines)


def main():
    parts = [HEADER]
    skipped = []
    for spec in EXPANSION_SPECS:
        if not spec.enabled and not spec.fields:
            skipped.append(spec)
            continue
        parts.append(render(spec))
        parts.append("")
    if skipped:
        parts.append("-- Sem escopo OAuth nesta conta (tabela criada quando habilitar):")
        for spec in skipped:
            parts.append(f"--   {spec.name} -> {spec.table} ({spec.endpoint})")
        parts.append("")
    parts.append("COMMIT;")
    OUT.write_text("\n".join(parts) + "\n", encoding="utf-8")
    enabled = [s for s in EXPANSION_SPECS if s.enabled or s.fields]
    print(f"{OUT.name}: {len(enabled)} tabelas geradas, {len(skipped)} puladas (sem escopo)")


if __name__ == "__main__":
    main()
