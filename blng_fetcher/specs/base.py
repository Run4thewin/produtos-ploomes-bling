"""
blng_fetcher/specs/base.py
Dataclasses de definicao declarativa de entidade (EntitySpec/FieldSpec)
e helpers de parsing compartilhados pelas specs e pelo engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from typing import Any, Callable, Literal

# Colunas de infraestrutura geridas pelo engine — implicitas em toda tabela,
# nunca declaradas em EntitySpec.fields e nunca auditadas no diff.
INFRA_COLUMNS = ("id", "created_at", "updated_at", "raw_json", "source_hash", "deleted_at")


# ---------------------------------------------------------------------------
# Helpers de parsing (movidos do main.py antigo; reutilizados pelas specs)
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    s = str(value)
    if s.startswith("0000"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                # DD/MM/YYYY: usado pelo detalhe de /caixas (a listagem do mesmo
                # endpoint usa ISO — o Bling e' inconsistente entre os dois).
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:26], fmt)
        except ValueError:
            continue
    return None


def _parse_date(value) -> date | None:
    dt = _parse_dt(value)
    return dt.date() if dt else None


def _fmt_address(addr: dict) -> str | None:
    if not addr:
        return None
    parts = [
        addr.get("endereco"), addr.get("numero"), addr.get("complemento"),
        addr.get("bairro"), addr.get("municipio"), addr.get("uf"), addr.get("cep"),
    ]
    return ", ".join(p for p in parts if p) or None


def _dig(item: dict, path: str) -> Any:
    """Navega "contato.nome" em dicts aninhados; None se qualquer nivel faltar."""
    value: Any = item
    for key in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FieldSpec:
    column: str                                     # nome da coluna SQL
    path: str | None = None                         # caminho no JSON ("contato.nome")
    sql_type: str = "text"                          # text|bigint|numeric|boolean|date|timestamp|jsonb
    transform: Callable[[Any], Any] | None = None   # ex.: _parse_dt, float, str
    compute: Callable[[dict], Any] | None = None    # derivados (ignora path/transform)
    audit: bool = True                              # participa do diff/historico?

    def extract(self, item: dict) -> Any:
        if self.compute is not None:
            return self.compute(item)
        value = _dig(item, self.path) if self.path else None
        if self.transform is not None:
            return self.transform(value)
        return value


@dataclass(frozen=True)
class EntitySpec:
    name: str                                 # "orders"
    endpoint: str                             # "pedidos/vendas"
    table: str                                # "bling_orders"
    fields: tuple[FieldSpec, ...]             # sem id/infra (implicitos)
    enabled: bool = True                      # False: sem escopo OAuth ainda
    # incremental
    incremental_param: str | None = None      # "dataAlteracaoInicial" (None = sem suporte)
    incremental_param_final: str | None = None
    watermark_overlap_minutes: int = 10
    # janela deslizante p/ entidades sem dataAlteracao (ex.: nfe por emissao).
    # A sondagem provou que os filtros do Bling so ativam em PAR Inicial+Final.
    window_param: str | None = None           # "dataEmissaoInicial"
    window_param_final: str | None = None     # "dataEmissaoFinal"
    window_days_back: int = 45
    # detalhe
    detail_endpoint: str | None = None        # "contatos/{id}"
    detail_when: Literal["never", "changed", "always"] = "never"
    # classificacao
    small_config: bool = False                # full sweep barato (1-2 req)
    refresh_hours: int = 1                    # small_config normalmente 24
    # casos especiais
    list_params: dict = field(default_factory=dict)
    singleton: bool = False                   # resposta "data" e' um dict unico
    id_path: str = "id"                       # caminho do id no item ("produto.id")
    id_sql_type: str = "bigint"               # tipo do id/PK (empresas usa hash text)
    conflict_columns: tuple[str, ...] = ("id",)
    id_batch_source: str | None = None        # SQL que produz ids p/ iterar
    id_batch_param: str | None = None         # "idsProdutos[]"
    id_batch_size: int = 50
    endpoint_template: str | None = None      # "situacoes/modulos/{id}/situacoes"
    # semantica especial: created_at vem de um campo da API (caso bling_orders)
    created_at_field: FieldSpec | None = None

    def __post_init__(self):
        columns = [f.column for f in self.fields]
        duplicated = {c for c in columns if columns.count(c) > 1}
        if duplicated:
            raise ValueError(f"{self.name}: colunas duplicadas {duplicated}")
        reserved = set(columns) & set(INFRA_COLUMNS)
        if reserved:
            raise ValueError(f"{self.name}: colunas reservadas usadas {reserved}")

    @property
    def audited_columns(self) -> tuple[str, ...]:
        return tuple(f.column for f in self.fields if f.audit)

    def extract_row(self, item: dict) -> dict[str, Any]:
        """Extrai {coluna: valor} das FieldSpecs (sem colunas de infra)."""
        return {f.column: f.extract(item) for f in self.fields}
