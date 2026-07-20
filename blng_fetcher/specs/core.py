"""
blng_fetcher/specs/core.py
Specs das 7 entidades originais do fetcher. As colunas e a logica de extracao
reproduzem exatamente os upserts do main.py antigo — o teste de paridade em
tests/test_entity_specs.py garante isso.
"""
from __future__ import annotations

from .base import EntitySpec, FieldSpec, _fmt_address, _parse_date, _parse_dt


# ---------------------------------------------------------------------------
# orders (pedidos/vendas -> bling_orders)
# ---------------------------------------------------------------------------

def _order_status(o: dict) -> str:
    situacao = o.get("situacao", {})
    return str(situacao.get("id", "") if isinstance(situacao, dict) else situacao)


ORDERS = EntitySpec(
    name="orders",
    endpoint="pedidos/vendas",
    table="bling_orders",
    incremental_param="dataAlteracaoInicial",
    created_at_field=FieldSpec("created_at", "data", sql_type="timestamp", transform=_parse_dt),
    fields=(
        FieldSpec("order_number", compute=lambda o: str(o.get("numero", ""))),
        FieldSpec("status", compute=_order_status),
        FieldSpec("total", sql_type="numeric",
                  compute=lambda o: float(o.get("totalProdutos", 0) or 0)),
        FieldSpec("client_id",
                  compute=lambda o: str((o.get("contato") or {}).get("id", "") or "")),
        FieldSpec("client_name", "contato.nome"),
        FieldSpec("client_email", "contato.email"),
        FieldSpec("client_cpf_cnpj", "contato.numeroDocumento"),
        FieldSpec("client_ie", "contato.ie"),
        FieldSpec("shipping_address",
                  compute=lambda o: _fmt_address(
                      (o.get("transporte") or {}).get("enderecoEntrega") or {})),
        FieldSpec("billing_address", compute=lambda o: None),
    ),
)


# ---------------------------------------------------------------------------
# contacts (contatos -> bling_contacts)
# ---------------------------------------------------------------------------

def _tipos_contato_set(c: dict) -> set[str]:
    return {(t.get("descricao") or "").strip().lower() for t in (c.get("tiposContato") or [])}


def _contact_types(c: dict) -> str | None:
    return ", ".join(
        t.get("descricao") for t in (c.get("tiposContato") or []) if t.get("descricao")
    ) or None


def _indicador_ie_label(c: dict) -> str | None:
    indicador_ie = str(c.get("indicadorIe") or "")
    return {
        "1": "Contribuinte ICMS", "2": "Contribuinte isento", "9": "Nao contribuinte",
    }.get(indicador_ie, indicador_ie or None)


def _endereco_geral(c: dict) -> dict:
    return (c.get("endereco") or {}).get("geral") or {}


def _endereco_cobranca(c: dict) -> dict:
    return (c.get("endereco") or {}).get("cobranca") or {}


CONTACTS = EntitySpec(
    name="contacts",
    endpoint="contatos",
    table="bling_contacts",
    incremental_param="dataAlteracaoInicial",
    detail_endpoint="contatos/{id}",
    detail_when="changed",
    created_at_field=FieldSpec("created_at", "dataCriacao", sql_type="timestamp",
                               transform=_parse_dt),
    fields=(
        FieldSpec("name", "nome"),
        FieldSpec("document", "numeroDocumento"),
        FieldSpec("person_type", "tipo"),
        FieldSpec("is_supplier", sql_type="boolean",
                  compute=lambda c: "fornecedor" in _tipos_contato_set(c)),
        FieldSpec("is_client", sql_type="boolean",
                  compute=lambda c: "cliente" in _tipos_contato_set(c)),
        FieldSpec("email", "email"),
        FieldSpec("phone", compute=lambda c: c.get("telefone") or c.get("celular")),
        FieldSpec("city", "endereco.geral.municipio"),
        FieldSpec("state", "endereco.geral.uf"),
        FieldSpec("internal_code", compute=lambda c: c.get("codigo") or None),
        FieldSpec("trade_name", compute=lambda c: c.get("fantasia") or None),
        FieldSpec("contact_types", compute=_contact_types),
        FieldSpec("country", compute=lambda c: (c.get("pais") or {}).get("nome") or None),
        FieldSpec("is_foreign", sql_type="boolean", compute=lambda c: c.get("tipo") == "E"),
        FieldSpec("email_nfe", compute=lambda c: c.get("emailNotaFiscal") or None),
        FieldSpec("cell_phone", compute=lambda c: c.get("celular") or None),
        FieldSpec("street", compute=lambda c: _endereco_geral(c).get("endereco") or None),
        FieldSpec("street_number", compute=lambda c: _endereco_geral(c).get("numero") or None),
        FieldSpec("complement", compute=lambda c: _endereco_geral(c).get("complemento") or None),
        FieldSpec("neighborhood", compute=lambda c: _endereco_geral(c).get("bairro") or None),
        FieldSpec("zip_code", compute=lambda c: _endereco_geral(c).get("cep") or None),
        FieldSpec("billing_street",
                  compute=lambda c: _endereco_cobranca(c).get("endereco") or None),
        FieldSpec("billing_city",
                  compute=lambda c: _endereco_cobranca(c).get("municipio") or None),
        FieldSpec("billing_state", compute=lambda c: _endereco_cobranca(c).get("uf") or None),
        FieldSpec("billing_zip_code",
                  compute=lambda c: _endereco_cobranca(c).get("cep") or None),
        FieldSpec("state_registration", compute=lambda c: c.get("ie") or None),
        FieldSpec("state_registration_status", compute=_indicador_ie_label),
        FieldSpec("municipal_registration",
                  compute=lambda c: c.get("inscricaoMunicipal") or None),
        FieldSpec("rg", compute=lambda c: c.get("rg") or None),
        FieldSpec("issuing_agency", compute=lambda c: c.get("orgaoEmissor") or None),
        FieldSpec("public_agency", compute=lambda c: c.get("orgaoPublico") or None),
        FieldSpec("birth_date", sql_type="date",
                  compute=lambda c: _parse_date((c.get("dadosAdicionais") or {}).get("dataNascimento"))),
        FieldSpec("gender", compute=lambda c: (c.get("dadosAdicionais") or {}).get("sexo") or None),
        FieldSpec("place_of_birth",
                  compute=lambda c: (c.get("dadosAdicionais") or {}).get("naturalidade") or None),
        FieldSpec("credit_limit", sql_type="numeric",
                  compute=lambda c: (c.get("financeiro") or {}).get("limiteCredito") or None),
        FieldSpec("payment_terms",
                  compute=lambda c: (c.get("financeiro") or {}).get("condicaoPagamento") or None),
        FieldSpec("financial_category_id",
                  compute=lambda c: str(((c.get("financeiro") or {}).get("categoria") or {}).get("id") or "") or None),
        FieldSpec("seller_id",
                  compute=lambda c: str((c.get("vendedor") or {}).get("id") or "") or None),
        FieldSpec("contact_persons_count", sql_type="bigint",
                  compute=lambda c: len(c.get("pessoasContato") or [])),
    ),
)


# ---------------------------------------------------------------------------
# nfe (nfe -> bling_nfe)
# ---------------------------------------------------------------------------

def _nfe_total(n: dict) -> float | None:
    total = n.get("valorNota")
    if total is None:
        itens = n.get("itens") or []
        total = sum(i.get("valorTotal", 0) for i in itens) or None
    return float(total) if total is not None else None


NFE = EntitySpec(
    name="nfe",
    endpoint="nfe",
    table="bling_nfe",
    window_param="dataEmissaoInicial",
    window_days_back=45,
    detail_endpoint="nfe/{id}",
    detail_when="changed",
    fields=(
        FieldSpec("numero", compute=lambda n: str(n.get("numero", ""))),
        FieldSpec("serie",
                  compute=lambda n: str(n["serie"]) if n.get("serie") is not None else None),
        FieldSpec("situation", compute=lambda n: str(n.get("situacao", ""))),
        FieldSpec("contact_id", "contato.id", sql_type="bigint"),
        FieldSpec("contact_name", "contato.nome"),
        FieldSpec("total", sql_type="numeric", compute=_nfe_total),
        FieldSpec("issue_date", "dataEmissao", sql_type="date", transform=_parse_date),
    ),
)


# ---------------------------------------------------------------------------
# pagar (contas/pagar -> bling_contas_pagar)
# ---------------------------------------------------------------------------

CONTAS_PAGAR = EntitySpec(
    name="pagar",
    endpoint="contas/pagar",
    table="bling_contas_pagar",
    window_param="dataVencimentoInicial",
    window_days_back=90,
    fields=(
        FieldSpec("description", "historico"),
        FieldSpec("supplier_id", "contato.id", sql_type="bigint"),
        FieldSpec("supplier_name", "contato.nome"),
        FieldSpec("due_date", "vencimento", sql_type="date", transform=_parse_date),
        FieldSpec("value", sql_type="numeric",
                  compute=lambda c: float(c.get("valor", 0) or 0)),
        FieldSpec("status", compute=lambda c: str(c.get("situacao", ""))),
        FieldSpec("competency", "competencia", sql_type="date", transform=_parse_date),
        FieldSpec("category", "categoria.descricao"),
    ),
)


# ---------------------------------------------------------------------------
# receber (contas/receber -> bling_contas_receber)
# ---------------------------------------------------------------------------

CONTAS_RECEBER = EntitySpec(
    name="receber",
    endpoint="contas/receber",
    table="bling_contas_receber",
    # Sondagem 2026-07: contas/receber IGNORA todos os filtros de data
    # (vencimento/emissao, par ou solo) — unica transacional em full scan.
    # O source_hash mantem o custo de banco baixo; o custo de API e' o numero
    # de paginas da base.
    fields=(
        FieldSpec("description", "historico"),
        FieldSpec("contact_id", "contato.id", sql_type="bigint"),
        FieldSpec("contact_name", "contato.nome"),
        FieldSpec("due_date", "vencimento", sql_type="date", transform=_parse_date),
        FieldSpec("value", sql_type="numeric",
                  compute=lambda c: float(c.get("valor", 0) or 0)),
        FieldSpec("status", compute=lambda c: str(c.get("situacao", ""))),
        FieldSpec("competency", "competencia", sql_type="date", transform=_parse_date),
        FieldSpec("category", "contaContabil.descricao"),
    ),
)


# ---------------------------------------------------------------------------
# naturezas (naturezas-operacoes -> bling_naturezas_operacao)
# ---------------------------------------------------------------------------

NATUREZAS = EntitySpec(
    name="naturezas",
    endpoint="naturezas-operacoes",
    table="bling_naturezas_operacao",
    small_config=True,
    refresh_hours=24,
    fields=(
        FieldSpec("descricao", "descricao"),
        FieldSpec("situacao", "situacao"),
        FieldSpec("padrao", sql_type="boolean", compute=lambda n: bool(n.get("padrao"))),
    ),
)


# ---------------------------------------------------------------------------
# produtos (produtos -> bling_produtos)
# ---------------------------------------------------------------------------

PRODUTOS = EntitySpec(
    name="produtos",
    endpoint="produtos",
    table="bling_produtos",
    incremental_param="dataAlteracaoInicial",
    fields=(
        FieldSpec("codigo", "codigo"),
        FieldSpec("nome", "nome"),
        FieldSpec("descricao_curta", "descricaoCurta"),
        FieldSpec("preco", sql_type="numeric",
                  compute=lambda p: float(p.get("preco", 0) or 0)),
        FieldSpec("situacao", "situacao"),
        FieldSpec("tipo", "tipo"),
        FieldSpec("formato", "formato"),
        FieldSpec("marca", "marca"),
        FieldSpec("ncm", "tributacao.ncm"),
        FieldSpec("peso_liquido", "pesoLiquido", sql_type="numeric"),
        FieldSpec("peso_bruto", "pesoBruto", sql_type="numeric"),
        FieldSpec("largura", "dimensoes.largura", sql_type="numeric"),
        FieldSpec("altura", "dimensoes.altura", sql_type="numeric"),
        FieldSpec("profundidade", "dimensoes.profundidade", sql_type="numeric"),
    ),
)


CORE_SPECS: tuple[EntitySpec, ...] = (
    ORDERS, CONTACTS, NFE, CONTAS_PAGAR, CONTAS_RECEBER, NATUREZAS, PRODUTOS,
)
