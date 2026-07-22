"""
blng_fetcher/specs/expansion.py
Specs das entidades novas, geradas da sondagem (relatorios/bling_probe/) e
revisadas a mao. DDL correspondente: scripts/sql/003_bling_new_entities.sql.

Notas da sondagem (2026-07-20):
- Filtros de data do Bling so ativam em PAR Inicial+Final.
- Sem escopo OAuth (403) nesta conta: nfse, contratos, logisticas, situacoes
  -> specs enabled=False ate ampliar o app em developer.bling.com.br.
- Sem uso nesta conta (payload vazio): categorias/lojas, produtos/fornecedores,
  produtos/lojas, produtos/estruturas, produtos/variacoes, campos-customizados
  por modulo -> nao carregados (re-sondar se passarem a ser usados).
"""
from __future__ import annotations

import os

from .base import EntitySpec, FieldSpec, _parse_date

# ---------------------------------------------------------------------------
# Transacionais
# ---------------------------------------------------------------------------

PEDIDOS_COMPRAS = EntitySpec(
    name="pedidos_compras",
    endpoint="pedidos/compras",
    table="bling_pedidos_compras",
    window_param="dataInicial",           # honrado (par e solo); filtra pela data do pedido
    window_days_back=90,
    detail_endpoint="pedidos/compras/{id}",
    detail_when="changed",                # itens/parcelas/transporte so no detalhe
    fields=(
        FieldSpec("numero", "numero", sql_type="bigint"),
        FieldSpec("data", "data", sql_type="date", transform=_parse_date),
        FieldSpec("data_prevista", "dataPrevista", sql_type="date", transform=_parse_date),
        FieldSpec("total_produtos", "totalProdutos", sql_type="numeric"),
        FieldSpec("total", "total", sql_type="numeric"),
        FieldSpec("fornecedor_id", "fornecedor.id", sql_type="bigint"),
        FieldSpec("situacao_id", "situacao.id", sql_type="bigint"),
        FieldSpec("situacao_valor", "situacao.valor", sql_type="bigint"),
        FieldSpec("ordem_compra", "ordemCompra"),
        FieldSpec("observacoes", "observacoes"),
        FieldSpec("observacoes_internas", "observacoesInternas"),
        FieldSpec("desconto_valor", "desconto.valor", sql_type="numeric"),
        FieldSpec("desconto_unidade", "desconto.unidade"),
        FieldSpec("categoria_id", "categoria.id", sql_type="bigint"),
        FieldSpec("tributacao_total_icms", "tributacao.totalICMS", sql_type="numeric"),
        FieldSpec("tributacao_total_ipi", "tributacao.totalIPI", sql_type="numeric"),
        FieldSpec("transporte_frete", "transporte.frete", sql_type="numeric"),
        FieldSpec("transporte_transportador", "transporte.transportador"),
        FieldSpec("transporte_frete_por_conta", "transporte.fretePorConta", sql_type="bigint"),
        FieldSpec("transporte_peso_bruto", "transporte.pesoBruto", sql_type="numeric"),
        FieldSpec("transporte_volumes", "transporte.volumes", sql_type="bigint"),
    ),
)

PROPOSTAS_COMERCIAIS = EntitySpec(
    name="propostas",
    endpoint="propostas-comerciais",
    table="bling_propostas_comerciais",
    window_param="dataInicial",           # honrado em par
    window_days_back=90,
    detail_endpoint="propostas-comerciais/{id}",
    detail_when="changed",                # itens/parcelas/observacoes so no detalhe
    fields=(
        FieldSpec("numero", "numero", sql_type="bigint"),
        FieldSpec("data", "data", sql_type="date", transform=_parse_date),
        FieldSpec("situacao", "situacao"),
        FieldSpec("total", "total", sql_type="numeric"),
        FieldSpec("total_produtos", "totalProdutos", sql_type="numeric"),
        FieldSpec("total_outros_itens", "totalOutrosItens", sql_type="numeric"),
        FieldSpec("contato_id", "contato.id", sql_type="bigint"),
        FieldSpec("loja_id", "loja.id", sql_type="bigint"),
        FieldSpec("vendedor_id", "vendedor.id", sql_type="bigint"),
        FieldSpec("desconto", "desconto", sql_type="numeric"),
        FieldSpec("outras_despesas", "outrasDespesas", sql_type="numeric"),
        FieldSpec("garantia", "garantia", sql_type="bigint"),
        FieldSpec("data_proximo_contato", "dataProximoContato",
                  sql_type="date", transform=_parse_date),
        FieldSpec("aos_cuidados_de", "aosCuidadosDe"),
        FieldSpec("introducao", "introducao"),
        FieldSpec("prazo_entrega", "prazoEntrega"),
        FieldSpec("observacoes", "observacoes"),
        FieldSpec("observacao_interna", "observacaoInterna"),
        FieldSpec("transporte_frete_modalidade", "transporte.freteModalidade",
                  sql_type="bigint"),
        FieldSpec("transporte_frete", "transporte.frete", sql_type="numeric"),
        FieldSpec("transporte_quantidade_volumes", "transporte.quantidadeVolumes",
                  sql_type="bigint"),
        FieldSpec("transporte_prazo_entrega", "transporte.prazoEntrega",
                  sql_type="bigint"),
        FieldSpec("transporte_peso_bruto", "transporte.pesoBruto", sql_type="numeric"),
    ),
)

# NFC-e: sem registros nesta conta na sondagem; campos espelham a NF-e
# (mesma familia de payload na API v3). Revisar quando houver dados reais.
NFCE = EntitySpec(
    name="nfce",
    endpoint="nfce",
    table="bling_nfce",
    window_param="dataEmissaoInicial",
    window_days_back=45,
    detail_endpoint="nfce/{id}",
    detail_when="changed",
    fields=(
        FieldSpec("numero", compute=lambda n: str(n.get("numero", ""))),
        FieldSpec("serie",
                  compute=lambda n: str(n["serie"]) if n.get("serie") is not None else None),
        FieldSpec("situation", compute=lambda n: str(n.get("situacao", ""))),
        FieldSpec("contact_id", "contato.id", sql_type="bigint"),
        FieldSpec("contact_name", "contato.nome"),
        FieldSpec("total", "valorNota", sql_type="numeric"),
        FieldSpec("issue_date", "dataEmissao", sql_type="date", transform=_parse_date),
        FieldSpec("chave_acesso", "chaveAcesso"),
        FieldSpec("tipo", "tipo", sql_type="bigint"),
    ),
)

# ---------------------------------------------------------------------------
# Estoque (caso especial: consulta por lotes de ids de bling_produtos)
# ---------------------------------------------------------------------------

ESTOQUES_SALDOS = EntitySpec(
    name="estoques_saldos",
    endpoint="estoques/saldos",
    table="bling_estoques_saldos",
    id_path="produto.id",                 # item nao tem id no topo
    id_batch_source=(
        "SELECT id FROM bling_produtos WHERE deleted_at IS NULL ORDER BY id"),
    id_batch_param="idsProdutos[]",
    id_batch_size=50,
    refresh_hours=int(os.environ.get("BLING_STOCK_REFRESH_HOURS", "6")),
    fields=(
        FieldSpec("produto_codigo", "produto.codigo"),
        FieldSpec("saldo_fisico_total", "saldoFisicoTotal", sql_type="numeric"),
        FieldSpec("saldo_virtual_total", "saldoVirtualTotal", sql_type="numeric"),
        # saldo por deposito fica no raw_json (array "depositos")
    ),
)

# ---------------------------------------------------------------------------
# Config / cadastros (full sweep 1x/dia; 1-2 requests cada)
# ---------------------------------------------------------------------------

DEPOSITOS = EntitySpec(
    name="depositos", endpoint="depositos", table="bling_depositos",
    small_config=True, refresh_hours=24,
    fields=(
        FieldSpec("descricao", "descricao"),
        FieldSpec("situacao", "situacao", sql_type="bigint"),
        FieldSpec("padrao", "padrao", sql_type="boolean"),
        FieldSpec("desconsiderar_saldo", "desconsiderarSaldo", sql_type="boolean"),
    ),
)

VENDEDORES = EntitySpec(
    name="vendedores", endpoint="vendedores", table="bling_vendedores",
    small_config=True, refresh_hours=24,
    detail_endpoint="vendedores/{id}",
    detail_when="changed",                # comissoes so no detalhe (fica no raw_json)
    fields=(
        FieldSpec("desconto_limite", "descontoLimite", sql_type="numeric"),
        FieldSpec("loja_id", "loja.id", sql_type="bigint"),
        FieldSpec("contato_id", "contato.id", sql_type="bigint"),
        FieldSpec("contato_nome", "contato.nome"),
        FieldSpec("contato_situacao", "contato.situacao"),
    ),
)

CATEGORIAS_PRODUTOS = EntitySpec(
    name="categorias_produtos", endpoint="categorias/produtos",
    table="bling_categorias_produtos",
    small_config=True, refresh_hours=24,
    fields=(
        FieldSpec("descricao", "descricao"),
        FieldSpec("categoria_pai_id", "categoriaPai.id", sql_type="bigint"),
    ),
)

CATEGORIAS_RECEITAS_DESPESAS = EntitySpec(
    name="categorias_receitas_despesas", endpoint="categorias/receitas-despesas",
    table="bling_categorias_receitas_despesas",
    small_config=True, refresh_hours=24,
    fields=(
        FieldSpec("descricao", "descricao"),
        FieldSpec("id_categoria_pai", "idCategoriaPai", sql_type="bigint"),
        FieldSpec("tipo", "tipo", sql_type="bigint"),
        FieldSpec("id_grupo_dre", "idGrupoDre", sql_type="bigint"),
    ),
)

GRUPOS_PRODUTOS = EntitySpec(
    name="grupos_produtos", endpoint="grupos-produtos", table="bling_grupos_produtos",
    small_config=True, refresh_hours=24,
    fields=(
        FieldSpec("nome", "nome"),
        FieldSpec("grupo_produto_pai_id", "grupoProdutoPai.id", sql_type="bigint"),
        FieldSpec("grupo_produto_pai_nome", "grupoProdutoPai.nome"),
    ),
)

CONTATOS_TIPOS = EntitySpec(
    name="contatos_tipos", endpoint="contatos/tipos", table="bling_contatos_tipos",
    small_config=True, refresh_hours=24,
    fields=(
        FieldSpec("descricao", "descricao"),
    ),
)

FORMAS_PAGAMENTOS = EntitySpec(
    name="formas_pagamentos", endpoint="formas-pagamentos",
    table="bling_formas_pagamentos",
    small_config=True, refresh_hours=24,
    detail_endpoint="formas-pagamentos/{id}",
    detail_when="changed",                # condicao/destino/taxas so no detalhe
    fields=(
        FieldSpec("descricao", "descricao"),
        FieldSpec("tipo_pagamento", "tipoPagamento", sql_type="bigint"),
        FieldSpec("situacao", "situacao", sql_type="bigint"),
        FieldSpec("fixa", "fixa", sql_type="boolean"),
        FieldSpec("padrao", "padrao", sql_type="bigint"),
        FieldSpec("finalidade", "finalidade", sql_type="bigint"),
        FieldSpec("juros", "juros", sql_type="numeric"),
        FieldSpec("multa", "multa", sql_type="numeric"),
        FieldSpec("condicao", "condicao"),
        FieldSpec("destino", "destino", sql_type="bigint"),
        FieldSpec("utiliza_dias_uteis", "utilizaDiasUteis", sql_type="boolean"),
        FieldSpec("taxas_aliquota", "taxas.aliquota", sql_type="numeric"),
        FieldSpec("taxas_valor", "taxas.valor", sql_type="numeric"),
        FieldSpec("taxas_prazo", "taxas.prazo", sql_type="bigint"),
    ),
)

CONTAS_CONTABEIS = EntitySpec(
    name="contas_contabeis", endpoint="contas-contabeis", table="bling_contas_contabeis",
    small_config=True, refresh_hours=24,
    fields=(
        FieldSpec("descricao", "descricao"),
        FieldSpec("saldo_inicial", "saldoInicial", sql_type="numeric"),
        FieldSpec("data_inicio_transacoes", "dataInicioTransacoes"),
    ),
)

CANAIS_VENDA = EntitySpec(
    name="canais_venda", endpoint="canais-venda", table="bling_canais_venda",
    small_config=True, refresh_hours=24,
    detail_endpoint="canais-venda/{id}",
    detail_when="changed",                # filiais so no detalhe (fica no raw_json)
    fields=(
        FieldSpec("descricao", "descricao"),
        FieldSpec("tipo", "tipo"),
        FieldSpec("situacao", "situacao", sql_type="bigint"),
    ),
)

CAMPOS_CUSTOMIZADOS_MODULOS = EntitySpec(
    name="campos_customizados_modulos", endpoint="campos-customizados/modulos",
    table="bling_campos_customizados_modulos",
    small_config=True, refresh_hours=24,
    fields=(
        FieldSpec("nome", "nome"),
        FieldSpec("modulo", "modulo"),
        FieldSpec("agrupador", "agrupador"),
    ),
)

EMPRESAS = EntitySpec(
    name="empresas", endpoint="empresas/me/dados-basicos", table="bling_empresas",
    small_config=True, refresh_hours=24,
    singleton=True,
    id_sql_type="text",                   # id vem como hash string, nao bigint
    fields=(
        FieldSpec("nome", "nome"),
        FieldSpec("cnpj", "cnpj"),
        FieldSpec("email", "email"),
        FieldSpec("data_contrato", "dataContrato", sql_type="date",
                  transform=_parse_date),
    ),
)

# ---------------------------------------------------------------------------
# Sem escopo OAuth nesta conta (403 na sondagem) — habilitar apos ampliar o
# app no developer.bling.com.br, re-sondar e preencher os campos.
# ---------------------------------------------------------------------------

NFSE = EntitySpec(
    name="nfse", endpoint="nfse", table="bling_nfse",
    enabled=False, fields=(),
)

CONTRATOS = EntitySpec(
    name="contratos", endpoint="contratos", table="bling_contratos",
    enabled=False, fields=(),
)

LOGISTICAS = EntitySpec(
    name="logisticas", endpoint="logisticas", table="bling_logisticas",
    enabled=False, fields=(),
)

SITUACOES_MODULOS = EntitySpec(
    name="situacoes_modulos", endpoint="situacoes/modulos",
    table="bling_situacoes_modulos",
    enabled=False, fields=(),
)


EXPANSION_SPECS: tuple[EntitySpec, ...] = (
    PEDIDOS_COMPRAS, PROPOSTAS_COMERCIAIS, NFCE, ESTOQUES_SALDOS,
    DEPOSITOS, VENDEDORES, CATEGORIAS_PRODUTOS, CATEGORIAS_RECEITAS_DESPESAS,
    GRUPOS_PRODUTOS, CONTATOS_TIPOS, FORMAS_PAGAMENTOS, CONTAS_CONTABEIS,
    CANAIS_VENDA, CAMPOS_CUSTOMIZADOS_MODULOS, EMPRESAS,
    NFSE, CONTRATOS, LOGISTICAS, SITUACOES_MODULOS,
)
