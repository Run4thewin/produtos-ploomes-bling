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


# ---------------------------------------------------------------------------
# Resiliencia: detalhe indisponivel nao pode corromper dados nem "fixar" o hash
# ---------------------------------------------------------------------------

class _FakeBling:
    """Simula o BlingClient: listagem ok, detalhe sempre falhando."""
    def __init__(self):
        self.detail_calls = 0


class _FakeConn:
    """Conexao minima: o engine faz commit() para soltar a transacao antes
    das chamadas HTTP (ver _process_page)."""
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def test_detail_failure_leaves_hash_null_for_new_record(monkeypatch):
    """Registro novo com detalhe falho e' gravado SEM source_hash, para que a
    proxima execucao o detecte como 'mudado' e complete os dados."""
    spec = SPECS["contacts"]
    monkeypatch.setattr(engine, "fetch_detail", lambda *a, **k: None)

    captured = {}
    monkeypatch.setattr(engine, "upsert_rows",
                        lambda conn, s, prepared: captured.setdefault("prep", prepared))
    monkeypatch.setattr(engine, "record_history", lambda *a, **k: 0)
    monkeypatch.setattr(engine, "select_existing", lambda *a, **k: {})

    stats = engine.LoadStats(entity=spec.name)
    conn = _FakeConn()
    engine._process_page(_FakeBling(), conn, spec,
                         [{"id": 1, "nome": "X"}], "run", "changed", stats)

    assert conn.commits >= 1, "transacao deve ser solta antes das chamadas HTTP"
    assert stats.detail_failures == 1
    assert captured["prep"][0]["source_hash"] is None, (
        "hash nao pode ser gravado quando o detalhe falhou — o registro ficaria "
        "permanentemente incompleto")


def test_detail_failure_does_not_overwrite_existing_good_data(monkeypatch):
    """Registro existente com detalhe falho e' PULADO, preservando as colunas
    que so vem do detalhe (senao viraria NULL)."""
    spec = SPECS["contacts"]
    monkeypatch.setattr(engine, "fetch_detail", lambda *a, **k: None)

    captured = {}
    monkeypatch.setattr(engine, "upsert_rows",
                        lambda conn, s, prepared: captured.setdefault("prep", prepared))
    monkeypatch.setattr(engine, "record_history", lambda *a, **k: 0)
    monkeypatch.setattr(
        engine, "select_existing",
        lambda *a, **k: {1: {"source_hash": "hash-antigo", "deleted_at": None,
                             "name": "Nome Bom", "city": "Campinas"}})

    stats = engine.LoadStats(entity=spec.name)
    engine._process_page(_FakeBling(), _FakeConn(), spec,
                         [{"id": 1, "nome": "X"}], "run", "changed", stats)

    assert stats.detail_failures == 1
    assert captured["prep"] == [], "nada deve ser gravado — dados bons seriam perdidos"


# ---------------------------------------------------------------------------
# Singleton (ex.: empresas/me/dados-basicos): 1 unico registro, nunca pagina.
# Regressao: sem o corte explicito, o loop rebuscava o mesmo item ate
# max_pages (999 em producao), desperdicando quota todo dia.
# ---------------------------------------------------------------------------

def test_singleton_entity_stops_after_first_page(monkeypatch):
    spec = SPECS["empresas"]
    assert spec.singleton, "precondicao: empresas deve ser singleton"

    calls = {"fetch_page": 0}

    def fake_fetch_page(bling, endpoint, page, page_size, extra_params):
        calls["fetch_page"] += 1
        return [{"id": "abc123", "nome": "Empresa X"}]

    monkeypatch.setattr(engine, "fetch_page", fake_fetch_page)
    monkeypatch.setattr(engine, "select_existing", lambda *a, **k: {})
    monkeypatch.setattr(engine, "upsert_rows", lambda *a, **k: 1)
    monkeypatch.setattr(engine, "record_history", lambda *a, **k: 0)

    stats = engine.load_entity(_FakeBling(), _FakeConn(), spec,
                               mode="full", max_pages=999, page_size=100)

    assert calls["fetch_page"] == 1, (
        f"singleton deve parar apos 1 pagina; chamou fetch_page {calls['fetch_page']}x")
    assert stats.completed is True


# ---------------------------------------------------------------------------
# Carga avulsa por --since/--until (blng_fetcher/main.py): deve montar o
# filtro nativo do Bling corretamente e jamais tocar bling_sync_state.
# ---------------------------------------------------------------------------

def test_custom_range_builds_incremental_filter_and_skips_sync_state(monkeypatch):
    from blng_fetcher import main as fetcher_main

    spec = SPECS["orders"]  # tem incremental_param = dataAlteracaoInicial
    captured = {}

    def fake_load_entity(bling, conn, spec_, *, mode, max_pages, page_size,
                         run_id, extra_params, detail_when_override, **_):
        captured["extra_params"] = extra_params
        captured["mode"] = mode
        return engine.LoadStats(entity=spec_.name, status="ok", completed=True)

    monkeypatch.setattr(engine, "load_entity", fake_load_entity)
    # se o codigo tentar ler/gravar sync_state aqui, o teste quebra (funcoes
    # nao mockadas explodiriam ao tentar usar _FakeConn como conexao real)
    import blng_fetcher.state as sync_state_mod
    monkeypatch.setattr(sync_state_mod, "get_state",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("nao deveria ler sync_state")))
    monkeypatch.setattr(sync_state_mod, "save_state",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("nao deveria gravar sync_state")))

    fetcher_main.run_entity_custom_range(
        _FakeBling(), _FakeConn(), spec,
        since="2026-07-20", until="2026-07-21",
        max_pages=999, page_size=100, detail="auto",
    )

    assert captured["extra_params"] == {
        "dataAlteracaoInicial": "2026-07-20",
        "dataAlteracaoFinal": "2026-07-21",
    }
    assert captured["mode"] == "full"


def test_custom_range_warns_when_entity_has_no_date_filter(monkeypatch, caplog):
    from blng_fetcher import main as fetcher_main

    spec = SPECS["receber"]  # confirmado na sondagem: ignora todos os filtros
    assert not spec.incremental_param and not spec.window_param

    captured = {}
    monkeypatch.setattr(
        engine, "load_entity",
        lambda bling, conn, spec_, **k: captured.setdefault("extra_params", k["extra_params"])
        or engine.LoadStats(entity=spec_.name))

    with caplog.at_level("WARNING"):
        fetcher_main.run_entity_custom_range(
            _FakeBling(), _FakeConn(), spec,
            since="2026-07-20", until="2026-07-21",
            max_pages=1, page_size=100, detail="auto",
        )

    assert captured["extra_params"] == {}
    assert any("nao suporta filtro de data" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _item_id: o Bling e' inconsistente entre listagem/detalhe do mesmo endpoint
# (ex.: /caixas devolve id como string na listagem, numero no detalhe).
# Regressao: sem normalizar, "WHERE id = ANY(%s)" quebra (bigint = text).
# ---------------------------------------------------------------------------

def test_item_id_normalizes_numeric_string_to_int():
    spec = SPECS["caixas"]
    assert engine._item_id(spec, {"id": "26410354010"}) == 26410354010
    assert isinstance(engine._item_id(spec, {"id": "26410354010"}), int)
    assert engine._item_id(spec, {"id": 26410354010}) == 26410354010


def test_item_id_keeps_non_numeric_string_as_is():
    spec = SPECS["empresas"]  # id e' um hash, nao numero
    assert engine._item_id(spec, {"id": "0eb83224356c67486524da1f45246af0"}) \
        == "0eb83224356c67486524da1f45246af0"
