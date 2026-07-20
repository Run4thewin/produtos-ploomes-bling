"""
Testes do motor generico: canonizacao, diff campo a campo, hash e SQL gerado.
Sem rede e sem banco.
"""
from datetime import date, datetime
from decimal import Decimal

from blng_fetcher import engine
from blng_fetcher.specs import SPECS
from blng_fetcher.specs.base import EntitySpec, FieldSpec


def test_canon_numeric_equivalence():
    # Decimal do banco vs float da API nao podem gerar falso positivo
    assert engine.canon(10) == engine.canon(10.0) == engine.canon(Decimal("10.00"))
    assert engine.canon(0.1) == engine.canon(Decimal("0.1"))
    assert engine.canon(1200.5) == engine.canon(Decimal("1200.50"))
    assert engine.canon(10) != engine.canon(10.01)


def test_canon_types():
    assert engine.canon(None) is None
    assert engine.canon(True) == "true"
    assert engine.canon(False) == "false"
    assert engine.canon(datetime(2026, 7, 1, 10, 0)) == "2026-07-01T10:00:00"
    assert engine.canon(date(2026, 7, 1)) == "2026-07-01"
    assert engine.canon("abc") == "abc"


def _mini_spec(**kwargs):
    return EntitySpec(
        name="mini", endpoint="mini", table="bling_mini",
        fields=(
            FieldSpec("nome", "nome"),
            FieldSpec("valor", "valor", sql_type="numeric"),
            FieldSpec("interno", "interno", audit=False),
        ),
        **kwargs,
    )


def test_diff_row_only_audited_changes():
    spec = _mini_spec()
    old = {"nome": "A", "valor": Decimal("10.00"), "interno": "x"}
    new = {"nome": "B", "valor": 10.0, "interno": "y"}
    changes = engine.diff_row(spec, old, new)
    # valor 10.00 == 10.0 (sem mudanca); interno nao e' auditado; so nome muda
    assert changes == [("nome", "A", "B")]


def test_diff_row_none_transitions():
    spec = _mini_spec()
    changes = engine.diff_row(spec, {"nome": None, "valor": 1}, {"nome": "A", "valor": None})
    assert ("nome", None, "A") in changes
    assert ("valor", "1", None) in changes


def test_source_hash_stable_and_sensitive():
    a = {"id": 1, "nome": "X", "aninhado": {"b": 2, "a": 1}}
    b = {"aninhado": {"a": 1, "b": 2}, "nome": "X", "id": 1}  # mesma coisa, outra ordem
    c = {"id": 1, "nome": "Y", "aninhado": {"a": 1, "b": 2}}
    assert engine.compute_source_hash(a) == engine.compute_source_hash(b)
    assert engine.compute_source_hash(a) != engine.compute_source_hash(c)


def test_build_upsert_sql_shape():
    sql = engine.build_upsert_sql(SPECS["produtos"])
    assert sql.startswith("INSERT INTO bling_produtos (id, codigo, nome,")
    assert "ON CONFLICT (id) DO UPDATE SET" in sql
    # created_at nunca e' sobrescrito no conflito
    assert "created_at = EXCLUDED.created_at" not in sql
    for col in ("updated_at", "raw_json", "source_hash", "deleted_at"):
        assert f"{col} = EXCLUDED.{col}" in sql


def test_upsert_sql_all_core_specs():
    for spec in SPECS.values():
        sql = engine.build_upsert_sql(spec)
        assert f"INSERT INTO {spec.table} " in sql
        assert "VALUES %s" in sql


def test_entity_key_single_and_composite():
    spec = SPECS["orders"]
    assert engine.entity_key(spec, {"id": 5}) == "5"
