# Retomada da carga inicial do Bling

Ponto de parada: **2026-07-21**, ~8.200 requests consumidos no dia (contador local).
Parado a pedido; nada corrompido, nenhum lock preso.

## Como retomar (na ordem)

```bash
cd C:\Users\CMC_DEV_001\Documents\projetos\ploomes_bling_produtos

# 1. Terminar o que ficou pela metade (~1-2k requests)
python -m blng_fetcher.main --entity propostas --mode full --detail changed --pages 999
python -m blng_fetcher.main --entity nfce      --mode full --pages 999   # conta nao usa NFC-e, ~2 req
python -m blng_fetcher.main --entity empresas  --mode full --pages 999   # 1 registro

# 2. Priming das tabelas antigas (~2.334 requests, so listagem, sem detalhe)
python -m blng_fetcher.main --entity produtos --mode full --pages 999    # ~2.147 req
python -m blng_fetcher.main --entity orders   --mode full --pages 999    # ~87 req
python -m blng_fetcher.main --entity pagar    --mode full --pages 999    # ~72 req
python -m blng_fetcher.main --entity receber  --mode full --pages 999    # ~28 req

# Painel de acompanhamento (opcional): http://localhost:8765
python scripts/dashboard.py
```

`--detail changed` faz o registro que ja tem `source_hash` ser pulado sem
re-buscar detalhe. Entao **pode reexecutar qualquer comando acima a vontade**:
ele so gasta quota com o que falta. Nao existe risco de duplicar.

## Estado em 2026-07-21

| Entidade | Linhas | Hash | Situacao |
|---|---|---|---|
| pedidos_compras | 3.694 | 3.694 | ✅ completo |
| propostas | 4.000 | 4.000 | ⏸️ parcial — retomar |
| nfce | 0 | 0 | ⏳ pendente (conta sem NFC-e) |
| empresas | 0 | 0 | ⏳ pendente |
| config (vendedores, categorias, formas_pagamentos, depositos, canais, grupos, contatos_tipos, contas_contabeis, campos_customizados, naturezas) | — | 100% | ✅ completo |
| produtos | 214.636 | 0 | ⏳ falta priming |
| orders | 8.615 | 0 | ⏳ falta priming |
| pagar | 7.111 | 0 | ⏳ falta priming |
| receber | 2.783 | 0 | ⏳ falta priming |
| contacts | 13.479 | 5 | ⏭️ deixar p/ o Job agendado (~13,6k req) |
| nfe | 8.461 | 0 | ⏭️ deixar p/ o Job agendado (~8,5k req) |
| estoques_saldos | 0 | 0 | ⏭️ pulado a pedido (~4,3k req) |

`hash = 0` significa que a tabela ainda nao passou pelo fetcher novo. Os dados
estao la (carregados pelo fetcher antigo); falta so o `source_hash` que liga o
modo incremental.

## Pendencias fora da carga

1. **Deploy do Job** (aguarda OK): `gcloud builds submit --config cloudbuild.pipeline.yaml --project portal-cmc-442413`
   (nao precisa de Docker local — build roda no Cloud Build)
2. **Contador de quota compartilhado**: adicionar `GCS_BUCKET=portal-cmc-442413-bling`
   no `.env` local. Hoje local e producao contam separado, cada um com orcamento
   de 100k contra um teto real de 120k da conta.
3. **Consumo real de producao**: exige `gcloud auth login`, depois
   `gcloud storage cat gs://portal-cmc-442413-bling/bling/quota.json`
4. **Verificar** se o servico de webhooks recebeu `GCS_BUCKET` no deploy — se nao,
   o contador dele e' efemero (zera a cada instancia) e nao protege nada.
5. **Planilha**: 3 abas novas prontas e validadas em dry-run (Pedidos de Compra,
   Propostas Comerciais, Auditoria). Ainda nao foram escritas de verdade.

## Orcamento sugerido (a definir)

- Fetcher/Job/local: `BLING_DAILY_REQUEST_BUDGET=40000`
- Servico de webhooks: `BLING_DAILY_REQUEST_BUDGET=100000`
- Teto real do Bling: 120.000/dia por conta (margem de 20k)
