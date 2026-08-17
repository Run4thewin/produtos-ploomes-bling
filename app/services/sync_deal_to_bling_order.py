import logging
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.clients.bling import BlingClient
from app.clients.db import get_db_conn
from app.clients.ploomes import PloomesClient
from app.config import Settings, get_settings
from app.services.mapping import (
    ProductMappingError,
    extract_ploomes_fields,
    get_other_property,
    map_ploomes_to_bling,
)

logger = logging.getLogger(__name__)

# O campo descricao do item de pedido no Bling rejeita (HTTP 400) acima de 50 chars.
ITEM_DESCRICAO_MAX_LENGTH = 50

# Circuit breaker contra loop de auto-disparo: o proprio update_deal() que os
# fluxos usam pra marcar sucesso (Title/StageId/OtherProperties) dispara um novo
# webhook de "update" do Ploomes para o mesmo Deal. Se o vinculo Deal->pedido nao
# ficar consistente apos a criacao (ver incidente Deal 1107321216, 2026-08-07:
# 39 pedidos duplicados em ~5min no fluxo de faturamento parcial, porque o pedido
# novo nunca era gravado no campo fonte-de-verdade), cada webhook auto-disparado
# recria outro pedido no Bling indefinidamente. Este limite bloqueia qualquer
# segunda criacao de pedido para o mesmo Deal dentro da janela, independente de
# qual fluxo/bug especifico a esta causando.
ORDER_CREATION_COOLDOWN_SECONDS = 120


class DealOrderValidationError(Exception):
    pass


@dataclass(frozen=True)
class StageRule:
    pipeline_id: int
    source_stage_id: int
    target_stage_id: int


@dataclass(frozen=True)
class PurchaseTriggerRule:
    pipeline_id: int
    trigger_stage_id: int
    target_stage_id: int


@dataclass(frozen=True)
class LogisticsRule:
    pipeline_id: int
    stage_id: int


@dataclass(frozen=True)
class DirectToLogisticsRule:
    pipeline_id: int
    source_stage_ids: frozenset[int]
    target_stage_id: int


class DealToBlingOrderSyncService:
    # Estado do circuit breaker fica na classe (nao na instancia): main.py cria um
    # DealToBlingOrderSyncService novo a cada webhook, entao um lock de instancia
    # nao pegaria chamadas repetidas para o mesmo Deal em requisicoes diferentes.
    _last_order_created_at: dict[str, float] = {}
    _order_creation_lock = threading.Lock()

    def __init__(
        self,
        settings: Settings | None = None,
        bling: BlingClient | None = None,
        ploomes: PloomesClient | None = None,
    ):
        self.settings = settings or get_settings()
        self.bling = bling or BlingClient(self.settings)
        self.ploomes = ploomes or PloomesClient(self.settings)

    def _check_duplicate_creation_guard(self, deal_id: Any) -> None:
        key = str(deal_id)
        now = time.monotonic()
        with self._order_creation_lock:
            last = self._last_order_created_at.get(key)
        if last is not None and (now - last) < ORDER_CREATION_COOLDOWN_SECONDS:
            raise DealOrderValidationError(
                "Pedido Bling ja criado para este Deal ha menos de "
                f"{ORDER_CREATION_COOLDOWN_SECONDS}s -- bloqueado para evitar "
                "duplicidade (circuit breaker contra loop de webhook)"
            )

    def _record_order_creation(self, deal_id: Any) -> None:
        with self._order_creation_lock:
            self._last_order_created_at[str(deal_id)] = time.monotonic()

    def create_bling_order_from_deal(self, deal_id: int | str) -> dict[str, Any]:
        logger.info("[DEAL_ORDER] INICIO deal_id=%s | buscando Deal no Ploomes", deal_id)
        deal = self.ploomes.get_deal_by_id(deal_id)
        logger.info(
            "[DEAL_ORDER] Deal carregado | deal_id=%s pipeline_id=%s stage_id=%s title=%s",
            deal.get("Id"),
            deal.get("PipelineId"),
            deal.get("StageId"),
            deal.get("Title") or "-",
        )

        try:
            result = self._create_bling_order_from_deal(deal)
            logger.info(
                "[DEAL_ORDER] FIM deal_id=%s action=%s",
                deal_id,
                result.get("action"),
            )
            return result
        except DealOrderValidationError as exc:
            logger.warning("Deal Ploomes %s nao processado: %s", deal_id, exc)
            self._mark_deal_error(deal["Id"], str(exc))
            return {
                "action": "error_registered",
                "deal_id": str(deal_id),
                "reason": str(exc),
            }
        except RuntimeError as exc:
            logger.warning("Erro operacional ao processar Deal Ploomes %s: %s", deal_id, exc)
            self._mark_deal_error(deal["Id"], str(exc))
            return {
                "action": "error_registered",
                "deal_id": str(deal_id),
                "reason": str(exc),
            }
        except httpx.HTTPStatusError as exc:
            reason = self._describe_bling_http_error(exc)
            logger.warning("Erro Bling ao processar Deal Ploomes %s: %s", deal_id, reason)
            self._mark_deal_error(deal["Id"], reason)
            return {
                "action": "error_registered",
                "deal_id": str(deal_id),
                "reason": reason,
            }

    def _create_bling_order_from_deal(self, deal: dict[str, Any]) -> dict[str, Any]:
        rule = self._find_stage_rule(deal)
        if not rule:
            logger.info(
                "[DEAL_ORDER] SKIP deal_id=%s | stage nao configurado pipeline_id=%s stage_id=%s",
                deal.get("Id"),
                deal.get("PipelineId"),
                deal.get("StageId"),
            )
            return {
                "action": "skipped",
                "reason": "stage_nao_configurado",
                "deal_id": deal.get("Id"),
                "pipeline_id": deal.get("PipelineId"),
                "stage_id": deal.get("StageId"),
            }

        logger.info(
            "[DEAL_ORDER] Stage aceito | deal_id=%s pipeline_id=%s stage_origem=%s stage_destino=%s",
            deal.get("Id"),
            rule.pipeline_id,
            rule.source_stage_id,
            rule.target_stage_id,
        )

        # Ploomes dispara o webhook varias vezes para a mesma mudanca (e o proprio
        # update_deal que marca sucesso reaciona um novo webhook); sem esta checagem
        # cada repeticao recria outro pedido -- mesma protecao ja existente no fluxo
        # de compra (_create_purchase_flow_from_deal).
        existing = self._get_order_link(deal)
        if existing and existing.get("bling_pedido_venda_id"):
            logger.info(
                "[DEAL_ORDER] SKIP deal_id=%s | pedido %s ja vinculado",
                deal.get("Id"),
                existing["bling_pedido_venda_id"],
            )
            return {
                "action": "skipped",
                "reason": "pedido_ja_vinculado",
                "deal_id": deal.get("Id"),
                "bling_order_id": existing["bling_pedido_venda_id"],
            }

        logger.info("[DEAL_ORDER] Buscando ultima quote | deal_id=%s", deal.get("Id"))
        quote = self.ploomes.get_latest_quote_by_deal(deal["Id"])
        if not quote:
            raise DealOrderValidationError("Deal sem quote/orcamento para gerar pedido")
        logger.info(
            "[DEAL_ORDER] Quote carregada | deal_id=%s quote_id=%s items=%s",
            deal.get("Id"),
            quote.get("Id"),
            len(quote.get("Products") or []),
        )

        payload = self._build_sales_order_payload(deal, quote)
        logger.info(
            "[DEAL_ORDER] Payload Bling montado | deal_id=%s contato_id=%s items=%s parcelas=%s vendedor_id=%s total_itens=%.2f",
            deal.get("Id"),
            payload.get("contato", {}).get("id"),
            len(payload.get("itens") or []),
            len(payload.get("parcelas") or []),
            payload.get("vendedor", {}).get("id", "-"),
            sum(
                float(item.get("quantidade") or 0) * float(item.get("valor") or 0)
                for item in payload.get("itens") or []
            ),
        )
        logger.info("[DEAL_ORDER] Criando pedido no Bling | deal_id=%s", deal.get("Id"))
        self._check_duplicate_creation_guard(deal["Id"])
        created = self.bling.create_sales_order(payload)
        order_id = created.get("id")
        if not order_id:
            raise RuntimeError(f"Bling criou pedido sem retornar id: {created}")
        self._record_order_creation(deal["Id"])

        logger.info(
            "[DEAL_ORDER] Pedido criado no Bling | deal_id=%s bling_order_id=%s",
            deal.get("Id"),
            order_id,
        )
        logger.info("[DEAL_ORDER] Buscando pedido criado no Bling | order_id=%s", order_id)
        order = self.bling.get_sales_order(order_id)
        logger.info(
            "[DEAL_ORDER] Pedido Bling carregado | deal_id=%s bling_order_id=%s numero=%s",
            deal.get("Id"),
            order_id,
            order.get("numero") or "-",
        )
        self._mark_deal_success(deal, order, rule)

        logger.info(
            "Pedido Bling criado a partir do Deal %s: %s",
            deal.get("Id"),
            order_id,
        )
        return {
            "action": "created",
            "deal_id": deal.get("Id"),
            "bling_order_id": order_id,
            "bling_order_number": order.get("numero"),
        }

    def create_purchase_flow_from_deal(self, deal_id: int | str) -> dict[str, Any]:
        logger.info("[PURCHASE_FLOW] INICIO deal_id=%s | buscando Deal no Ploomes", deal_id)
        deal = self.ploomes.get_deal_by_id(deal_id)

        try:
            result = self._create_purchase_flow_from_deal(deal)
            logger.info("[PURCHASE_FLOW] FIM deal_id=%s action=%s", deal_id, result.get("action"))
            return result
        except DealOrderValidationError as exc:
            logger.warning("Deal Ploomes %s nao processado (fluxo compra): %s", deal_id, exc)
            self._mark_deal_error(deal["Id"], str(exc))
            return {"action": "error_registered", "deal_id": str(deal_id), "reason": str(exc)}
        except RuntimeError as exc:
            logger.warning("Erro operacional no fluxo de compra do Deal Ploomes %s: %s", deal_id, exc)
            self._mark_deal_error(deal["Id"], str(exc))
            return {"action": "error_registered", "deal_id": str(deal_id), "reason": str(exc)}
        except httpx.HTTPStatusError as exc:
            reason = self._describe_bling_http_error(exc)
            logger.warning("Erro Bling no fluxo de compra do Deal Ploomes %s: %s", deal_id, reason)
            self._mark_deal_error(deal["Id"], reason)
            return {"action": "error_registered", "deal_id": str(deal_id), "reason": reason}

    def _create_purchase_flow_from_deal(self, deal: dict[str, Any]) -> dict[str, Any]:
        rule = self._find_purchase_trigger_rule(deal)
        if not rule:
            return {
                "action": "skipped",
                "reason": "stage_nao_configurado",
                "deal_id": deal.get("Id"),
                "pipeline_id": deal.get("PipelineId"),
                "stage_id": deal.get("StageId"),
            }

        # O Ploomes dispara o webhook varias vezes para a mesma mudanca, e o Deal
        # permanece no estagio-gatilho (origem = destino). Sem esta checagem cada
        # webhook tenta criar outro pedido: o Bling recusa a duplicata ("informacoes
        # identicas a ultima venda salva") e o Deal acaba no estagio de erro mesmo
        # tendo gerado o pedido com sucesso na primeira chamada.
        existing = self._get_order_link(deal)
        if existing and existing.get("bling_pedido_venda_id"):
            logger.info(
                "[PURCHASE_FLOW] SKIP deal_id=%s | pedido %s ja vinculado",
                deal.get("Id"),
                existing["bling_pedido_venda_id"],
            )
            return {
                "action": "skipped",
                "reason": "pedido_ja_vinculado",
                "deal_id": deal.get("Id"),
                "bling_order_id": existing["bling_pedido_venda_id"],
            }

        quote = self.ploomes.get_latest_quote_by_deal(deal["Id"])
        if not quote:
            raise DealOrderValidationError("Deal sem quote/orcamento para gerar pedido")

        payload = self._build_sales_order_payload(deal, quote)
        self._check_duplicate_creation_guard(deal["Id"])
        created = self.bling.create_sales_order(payload)
        sales_order_id = created.get("id")
        if not sales_order_id:
            raise RuntimeError(f"Bling criou pedido de venda sem retornar id: {created}")
        self._record_order_creation(deal["Id"])
        sales_order = self.bling.get_sales_order(sales_order_id)

        # Nao cria mais pedido de compra vinculado nesta etapa -- so o pedido de venda.
        self._save_order_link(deal["Id"], sales_order_id, None)
        self._mark_deal_purchase_flow_success(deal, sales_order, None, rule)
        self._advance_sales_order_situacao(
            sales_order_id, self.settings.bling_situacao_em_processo_compra
        )

        logger.info(
            "[PURCHASE_FLOW] Pedido de venda %s criado a partir do Deal %s",
            sales_order_id,
            deal.get("Id"),
        )
        return {
            "action": "created",
            "deal_id": deal.get("Id"),
            "bling_order_id": sales_order_id,
            "bling_order_number": sales_order.get("numero"),
            "bling_purchase_order_id": None,
        }

    def _advance_sales_order_situacao(self, sales_order_id: int, situacao_id: int) -> None:
        if not situacao_id:
            logger.info(
                "[PURCHASE_FLOW] situacao nao configurada (id=0) | pedido=%s | pulando transicao",
                sales_order_id,
            )
            return
        try:
            self.bling.update_sales_order_situacao(sales_order_id, situacao_id)
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "[PURCHASE_FLOW] Falha ao mudar situacao do pedido %s para %s: %s",
                sales_order_id,
                situacao_id,
                self._describe_bling_http_error(exc),
            )

    def _mark_deal_purchase_flow_success(
        self,
        deal: dict[str, Any],
        sales_order: dict[str, Any],
        purchase_order_id: int | None,
        rule: PurchaseTriggerRule,
    ) -> None:
        order_id = sales_order.get("id")
        order_number = sales_order.get("numero") or order_id
        title = deal.get("Title") or ""
        new_title = title if str(title).startswith(str(order_number)) else f"{order_number} - {title}"
        order_reference = (
            f"Pedido Bling {order_number}: "
            f"https://www.bling.com.br/vendas.php#edit/{order_id}"
        )
        other_properties = [
            {"FieldKey": self.settings.ploomes_deal_order_field, "StringValue": order_reference},
        ]
        if purchase_order_id and self.settings.ploomes_deal_purchase_order_id_field:
            other_properties.append(
                {
                    "FieldKey": self.settings.ploomes_deal_purchase_order_id_field,
                    "IntegerValue": purchase_order_id,
                }
            )
        if self.settings.ploomes_deal_sales_order_id_field:
            other_properties.append(
                {
                    "FieldKey": self.settings.ploomes_deal_sales_order_id_field,
                    "StringValue": str(order_id),
                }
            )
        self.ploomes.update_deal(
            deal["Id"],
            {
                "Title": new_title,
                "StageId": rule.target_stage_id,
                "OtherProperties": other_properties,
            },
        )

    def _save_order_link(
        self, deal_id: int | str, sales_order_id: int, purchase_order_id: int | None
    ) -> None:
        # Com o campo do Deal configurado, o vinculo vive no Ploomes -- nao usa Postgres.
        if self.settings.ploomes_deal_sales_order_id_field:
            return
        try:
            conn = get_db_conn(self.settings)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO bling_order_links
                            (ploomes_deal_id, bling_pedido_venda_id, bling_pedido_compra_id, updated_at)
                        VALUES (%s, %s, %s, now())
                        ON CONFLICT (ploomes_deal_id) DO UPDATE SET
                            bling_pedido_venda_id = EXCLUDED.bling_pedido_venda_id,
                            bling_pedido_compra_id = EXCLUDED.bling_pedido_compra_id,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (deal_id, sales_order_id, purchase_order_id),
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(
                "[PURCHASE_FLOW] Falha ao gravar bling_order_links | deal_id=%s | %s", deal_id, exc
            )

    def record_deal_stage_transition(self, deal_id: int | str) -> int | None:
        # Chamado uma vez por webhook, ANTES de qualquer regra de estagio, para que
        # toda transicao do Deal fique registrada -- mesmo quando nenhuma regra bate
        # no estagio atual. E o que permite detectar, mais tarde, um Deal que pulou
        # direto de um estagio anterior para Logistica sem passar por Solicitacao de
        # Compra (ver _find_direct_to_logistics_rule).
        deal = self.ploomes.get_deal_by_id(deal_id)
        return self._record_and_get_previous_stage(deal["Id"], deal.get("StageId"))

    def update_situacao_for_logistics_stage(
        self, deal_id: int | str, previous_stage_id: int | None = None
    ) -> dict[str, Any]:
        deal = self.ploomes.get_deal_by_id(deal_id)
        rule = self._find_logistics_rule(deal)
        if not rule:
            return {
                "action": "skipped",
                "reason": "stage_nao_configurado",
                "deal_id": deal.get("Id"),
            }

        link = self._get_order_link(deal)
        if not link or not link.get("bling_pedido_venda_id"):
            direct_rule = self._find_direct_to_logistics_rule(deal)
            if direct_rule and previous_stage_id in direct_rule.source_stage_ids:
                logger.info(
                    "[LOGISTICS_DIRECT] Deal %s pulou direto de %s para Logistica | gerando pedido de venda",
                    deal.get("Id"),
                    previous_stage_id,
                )
                return self._create_sales_order_direct_to_logistics(deal)
            return {
                "action": "skipped",
                "reason": "pedido_nao_vinculado",
                "deal_id": deal.get("Id"),
            }

        situacao_id = self.settings.bling_situacao_pronto_faturar
        if not situacao_id:
            logger.info(
                "[LOGISTICS] situacao pronto_faturar nao configurada (id=0) | deal_id=%s | pulando",
                deal.get("Id"),
            )
            return {
                "action": "skipped",
                "reason": "situacao_nao_configurada",
                "deal_id": deal.get("Id"),
            }

        sales_order_id = link["bling_pedido_venda_id"]

        try:
            # 1. Carrega o pedido original
            original_order = self.bling.get_sales_order(sales_order_id)
            
            # 2. Carrega a quote do deal duplicado (itens que vao ficar de saldo)
            quote = self.ploomes.get_latest_quote_by_deal(deal["Id"])

            # 3. Compara os itens e descobre se houve reducao
            # Usa so _build_items aqui (sem contato/forma de pagamento/pedido de compra
            # do cliente) -- essa comparacao roda pra QUALQUER Deal que chega em
            # Logistica com pedido ja vinculado, faturamento parcial ou nao. Exigir os
            # campos completos de criacao de pedido aqui travava a atualizacao de
            # situacao (o caso comum, sem faturamento parcial) sempre que o Deal nao
            # tinha o campo "numero do pedido de compra do cliente" preenchido, mesmo
            # sem precisar criar pedido nenhum. Ver DealToBlingOrderSyncService.
            #
            # Sem quote no Ploomes nao ha como comparar itens -- trata como "sem
            # diferenca" e segue pro update de situacao normal em vez de abortar.
            # A maioria dos Deals que chega aqui nao e faturamento parcial; travar
            # a atualizacao de situacao inteira por falta de quote afetava qualquer
            # Deal, nao so o caso de duplicado/saldo que essa checagem existe pra cobrir.
            if quote:
                original_items = original_order.get("itens") or []
                deal_items, _deal_total = self._build_items(quote)
                items_to_invoice, items_to_keep = self._calculate_partial_billing_split(
                    original_items, deal_items
                )
            else:
                logger.info(
                    "[LOGISTICS] Deal %s sem quote no Ploomes -- pulando comparacao de "
                    "faturamento parcial, seguindo com update de situacao normal.",
                    deal.get("Id"),
                )
                items_to_invoice, items_to_keep = [], []

            if items_to_invoice:
                logger.info(
                    "[LOGISTICS_PARTIAL] Diferenca de itens detectada para Deal %s. Faturando %s itens e mantendo %s itens no saldo.",
                    deal.get("Id"), len(items_to_invoice), len(items_to_keep)
                )

                # So agora, com faturamento parcial confirmado, monta o payload
                # completo (contato, forma de pagamento, pedido de compra do
                # cliente etc.) -- aqui sim um pedido novo vai ser criado no Bling
                # e esses campos sao obrigatorios de verdade.
                deal_payload = self._build_sales_order_payload(deal, quote)
                new_payload = deal_payload.copy()
                new_payload["itens"] = items_to_invoice
                
                # Injeta timestamp nas observacoes internas para evitar que o Bling
                # bloqueie a venda como "idêntica à última" no caso de retentativas
                base_obs = new_payload.get("observacoesInternas") or ""
                new_payload["observacoesInternas"] = f"{base_obs}\nFaturamento Parcial: {int(time.time())}".strip()
                
                # Recalcula parcelas baseadas no novo total a faturar
                total_to_invoice = sum(float(item.get("quantidade") or 0) * float(item.get("valor") or 0) for item in items_to_invoice)
                payment_method_name = self._get_property_value(deal, self.settings.ploomes_deal_payment_method_field, value_keys=("ObjectValueName", "StringValue", "IntegerValue"))
                payment_method_id = self._lookup_config_map(self.settings.bling_payment_methods, payment_method_name)
                payment_days = self._payment_days(deal)
                freight_value = self._get_property_value(deal, self.settings.ploomes_deal_freight_value_field)
                if freight_value is not None:
                     total_to_invoice += float(freight_value)
                if payment_method_id:
                     new_payload["parcelas"] = self._build_installments(total_to_invoice, payment_days, payment_method_id)

                self._check_duplicate_creation_guard(deal["Id"])
                created_new = self.bling.create_sales_order(new_payload)
                new_order_id = created_new.get("id")
                if new_order_id:
                     self._record_order_creation(deal["Id"])
                     if self.settings.bling_situacao_em_processo_compra:
                          self._advance_sales_order_situacao(new_order_id, self.settings.bling_situacao_em_processo_compra)
                     if situacao_id:
                          self.bling.update_sales_order_situacao(new_order_id, situacao_id)
                     
                     # Atualiza o titulo do deal duplicado (que agora representa o faturamento parcial/novo pedido)
                     # Para faturamento parcial manual o titulo/referencia do novo pedido
                     new_order = self.bling.get_sales_order(new_order_id)
                     # Passamos uma StageRule mock para forçar o sucesso e vinculação.
                     # Vamos apenas invocar _mark_deal_success que já trata tudo.
                     rule_mock = StageRule(
                          pipeline_id=deal.get("PipelineId") or 0,
                          source_stage_id=deal.get("StageId") or 0,
                          target_stage_id=deal.get("StageId") or 0
                     )
                     self._mark_deal_success(deal, new_order, rule_mock)
                     # Atualizamos no banco legacy caso precise
                     self._save_order_link(deal["Id"], new_order_id, None)

                     logger.info("[LOGISTICS_PARTIAL] Novo pedido criado para faturamento parcial: %s", new_order_id)
                
                # Passo C: Atualiza o pedido original para manter apenas o saldo
                if items_to_keep:
                    update_payload = {"itens": items_to_keep}
                    # Opcionalmente recalcular parcelas do pedido original aqui se a API do Bling exigir para PUT.
                    self.bling.update_sales_order(sales_order_id, update_payload)
                    logger.info("[LOGISTICS_PARTIAL] Pedido original %s atualizado com o saldo de %s itens.", sales_order_id, len(items_to_keep))
                
                # Para fins de rastreio, consideramos o deal processado com base no original
                # Note: Precisamos definir onde o link do *novo* pedido de venda deve ficar salvo.
                # Como o Deal que disparou a acao foi o duplicado, atualizamos a situacao do pedido original (que agora eh o saldo)
                # se necessario.

            else:
                # Fluxo normal, sem faturamento parcial
                if situacao_id:
                    self._update_situacao_tolerando_mesma_situacao(sales_order_id, situacao_id)

        except DealOrderValidationError as exc:
             logger.warning("[LOGISTICS] Erro de validacao Deal %s: %s", deal.get("Id"), exc)
             self._mark_deal_error(deal["Id"], str(exc))
             return {"action": "error_registered", "deal_id": deal.get("Id"), "reason": str(exc)}
        except httpx.HTTPStatusError as exc:
            reason = self._describe_bling_http_error(exc)
            logger.warning(
                "[LOGISTICS] Falha ao interagir com Bling para pedido %s: %s", sales_order_id, reason
            )
            self._mark_deal_error(deal["Id"], reason)
            return {"action": "error_registered", "deal_id": deal.get("Id"), "reason": reason}

        if situacao_id:
             self._update_order_link_situacao(deal["Id"], situacao_id)

        # Garante que o campo do Deal mostre o link do pedido, nao o motivo de
        # um erro anterior (ver _mark_deal_error -- grava no mesmo campo). Toda
        # vez que a situacao e' confirmada com sucesso aqui (incluindo o caso
        # "ja estava na situacao certa"), restaura/reafirma o link -- mas so' se
        # o campo estiver realmente diferente, pra nao gerar um PATCH (e portanto
        # um novo webhook) a cada processamento sem necessidade real (ver
        # incidente do Deal 1107321216 no topo do arquivo).
        self._restore_order_link_field(deal, sales_order_id, original_order.get("numero"))

        self._notify_logistics_email(deal, sales_order_id)

        return {
            "action": "situacao_atualizada",
            "deal_id": deal.get("Id"),
            "bling_order_id": sales_order_id,
            "situacao_id": situacao_id,
        }

    def _notify_logistics_email(self, deal: dict[str, Any], sales_order_id: int) -> None:
        # Best-effort: falha ao notificar nao pode derrubar a atualizacao real de
        # situacao, que ja aconteceu com sucesso quando isto e' chamado.
        if not self.settings.send_mail_service_url:
            return
        try:
            order = self.bling.get_sales_order(sales_order_id)
            html = self._build_logistics_email_html(deal, order)
            deal_id = deal.get("Id")
            numero = order.get("numero") or sales_order_id
            recipients = [
                addr.strip()
                for addr in self.settings.logistics_notification_email_to.split(",")
                if addr.strip()
            ]
            owner_email = self._owner_email_for_deal(deal)
            if owner_email and owner_email not in recipients:
                recipients.append(owner_email)
            response = httpx.post(
                self.settings.send_mail_service_url.rstrip("/") + "/send-email",
                json={
                    "to": recipients,
                    "subject": f"Pedido {numero} entrou em Logistica -- {deal.get('Title', '')}",
                    "html": html,
                },
                timeout=15.0,
            )
            response.raise_for_status()
            logger.info(
                "[LOGISTICS_EMAIL] Notificacao enviada | deal_id=%s pedido=%s",
                deal_id,
                sales_order_id,
            )
        except Exception as exc:  # noqa: BLE001 - notificacao nunca pode propagar erro
            logger.warning(
                "[LOGISTICS_EMAIL] Falha ao enviar notificacao | deal_id=%s pedido=%s | %s",
                deal.get("Id"),
                sales_order_id,
                exc,
            )

    def _build_logistics_email_html(
        self, deal: dict[str, Any], order: dict[str, Any]
    ) -> str:
        deal_id = deal.get("Id")
        contact = deal.get("Contact") or {}
        contact_name = contact.get("Name") or deal.get("ContactName") or "-"
        numero = order.get("numero") or "-"
        order_id = order.get("id") or ""
        situacao = (order.get("situacao") or {}).get("valor") or "-"
        total = order.get("total")
        total_fmt = f"R$ {float(total):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if total is not None else "-"

        deal_link = f"{self.settings.ploomes_web_base_url}/deal/{deal_id}"
        bling_link = f"https://www.bling.com.br/vendas.php#edit/{order_id}" if order_id else ""

        rows = []
        for raw_item in order.get("itens") or []:
            item = raw_item.get("item") if isinstance(raw_item.get("item"), dict) else raw_item
            descricao = item.get("descricao") or item.get("codigo") or "-"
            qtd = item.get("quantidade") or 0
            valor_unit = item.get("valor") or item.get("valorunidade") or 0
            try:
                subtotal = float(qtd) * float(valor_unit)
            except (TypeError, ValueError):
                subtotal = 0
            rows.append(
                f"<tr>"
                f"<td style='padding:4px 8px;border:1px solid #ddd'>{descricao}</td>"
                f"<td style='padding:4px 8px;border:1px solid #ddd;text-align:right'>{qtd}</td>"
                f"<td style='padding:4px 8px;border:1px solid #ddd;text-align:right'>R$ {float(valor_unit):,.2f}</td>"
                f"<td style='padding:4px 8px;border:1px solid #ddd;text-align:right'>R$ {subtotal:,.2f}</td>"
                f"</tr>"
            )
        items_table = (
            "<table style='border-collapse:collapse;margin-top:8px'>"
            "<tr style='background:#f2f2f2'>"
            "<th style='padding:4px 8px;border:1px solid #ddd'>Item</th>"
            "<th style='padding:4px 8px;border:1px solid #ddd'>Qtd</th>"
            "<th style='padding:4px 8px;border:1px solid #ddd'>Valor Unit.</th>"
            "<th style='padding:4px 8px;border:1px solid #ddd'>Subtotal</th>"
            "</tr>" + "".join(rows) + "</table>"
        ) if rows else "<p><em>Sem itens retornados pelo Bling.</em></p>"

        links_html = f"<p><a href='{deal_link}'>Abrir Deal no Ploomes</a>"
        if bling_link:
            links_html += f" &nbsp;|&nbsp; <a href='{bling_link}'>Abrir pedido no Bling</a>"
        links_html += "</p>"

        return f"""
        <div style="font-family:Arial,sans-serif;font-size:14px;color:#222">
          <p>O pedido de venda abaixo acaba de entrar na etapa de <strong>Logistica</strong>.</p>
          <table style='border-collapse:collapse;margin-top:8px'>
            <tr><td style='padding:4px 8px;font-weight:bold'>Deal</td><td style='padding:4px 8px'>{deal.get('Title', '-')} (Id {deal_id})</td></tr>
            <tr><td style='padding:4px 8px;font-weight:bold'>Cliente</td><td style='padding:4px 8px'>{contact_name}</td></tr>
            <tr><td style='padding:4px 8px;font-weight:bold'>Pedido Bling</td><td style='padding:4px 8px'>{numero}</td></tr>
            <tr><td style='padding:4px 8px;font-weight:bold'>Situacao</td><td style='padding:4px 8px'>{situacao}</td></tr>
            <tr><td style='padding:4px 8px;font-weight:bold'>Valor total</td><td style='padding:4px 8px'>{total_fmt}</td></tr>
          </table>
          {items_table}
          {links_html}
        </div>
        """

    def _calculate_partial_billing_split(self, original_items: list[dict[str, Any]], deal_items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        # Helper method to calculate the difference between the original bling order and the new deal (saldo)
        
        # Build maps for easy lookup by product ID
        orig_map = {}
        for item in original_items:
            # Bling returns item as {"item": {"codigo": ..., "quantidade": ..., "produto": {"id": ...}}}
            # depending on the endpoint GET vs POST payload. Normalize to just extracting product id and quantity.
            
            # GET /pedidos/vendas returns:
            # "itens": [ {"item": {"descricao": ..., "quantidade": ..., "codigo": ...}} ] 
            # Or similar structure. We need to be careful with the exact Bling GET format.
            # Assuming standard V3 format:
            prod_id = item.get("produto", {}).get("id") or item.get("item", {}).get("produto", {}).get("id")
            if prod_id:
                orig_map[str(prod_id)] = float(item.get("quantidade") or item.get("item", {}).get("quantidade") or 0)
                
        deal_map = {}
        for item in deal_items:
            prod_id = item.get("produto", {}).get("id")
            if prod_id:
                deal_map[str(prod_id)] = {
                    "item": item,
                    "qty": float(item.get("quantidade") or 0)
                }
                
        items_to_invoice = []
        items_to_keep = deal_items # As per logic, the deal has the items to keep (saldo)
        
        has_difference = False
        
        for orig_prod_id, orig_qty in orig_map.items():
            if orig_prod_id in deal_map:
                deal_qty = deal_map[orig_prod_id]["qty"]
                if deal_qty < orig_qty:
                    has_difference = True
                    invoice_qty = orig_qty - deal_qty
                    invoice_item = deal_map[orig_prod_id]["item"].copy()
                    invoice_item["quantidade"] = invoice_qty
                    
                    # Fix comission base based on new qty
                    unit_price = float(invoice_item.get("valor") or 0)
                    if "comissao" in invoice_item:
                         invoice_item["comissao"]["base"] = invoice_qty * unit_price
                         
                    items_to_invoice.append(invoice_item)
            else:
                 # Original item is completely missing from the deal -> invoice it completely
                 has_difference = True
                 # We need to recreate the item payload from the original order to invoice it.
                 # For simplicity, since the deal_items doesn't have it, we'd need to fetch the product details
                 # or use the original item structure. 
                 # To be safe, we should ideally find it in the original_items list and format it.
                 # Let's find the original item and format it for POST
                 for o_item in original_items:
                      o_prod_id = str(o_item.get("produto", {}).get("id") or o_item.get("item", {}).get("produto", {}).get("id"))
                      if o_prod_id == orig_prod_id:
                           raw_item = o_item.get("item") or o_item
                           items_to_invoice.append({
                               "produto": {"id": int(orig_prod_id)},
                               "quantidade": orig_qty,
                               "valor": float(raw_item.get("valor") or raw_item.get("valorunidade") or 0),
                               "descricao": raw_item.get("descricao", ""),
                               # Other fields like discount might be needed, but this handles the core
                           })
                           break
                           
        if has_difference:
             return items_to_invoice, items_to_keep
        return [], []

    def _create_sales_order_direct_to_logistics(self, deal: dict[str, Any]) -> dict[str, Any]:
        # Deal pulou direto de um estagio anterior (Orcamento/Analise de Credito/
        # Analise aprovada) para Logistica, sem passar por "Gerar pedido de venda".
        # Cria o pedido de venda aqui mesmo, ja com situacao pronto_faturar -- sem
        # pedido de compra, ja que esse caminho nao passou pelo fluxo de compra.
        try:
            quote = self.ploomes.get_latest_quote_by_deal(deal["Id"])
            if not quote:
                raise DealOrderValidationError("Deal sem quote/orcamento para gerar pedido")

            payload = self._build_sales_order_payload(deal, quote)
            self._check_duplicate_creation_guard(deal["Id"])
            created = self.bling.create_sales_order(payload)
            sales_order_id = created.get("id")
            if not sales_order_id:
                raise RuntimeError(f"Bling criou pedido de venda sem retornar id: {created}")
            self._record_order_creation(deal["Id"])
            sales_order = self.bling.get_sales_order(sales_order_id)
        except DealOrderValidationError as exc:
            logger.warning("[LOGISTICS_DIRECT] Deal %s nao processado: %s", deal.get("Id"), exc)
            self._mark_deal_error(deal["Id"], str(exc))
            return {"action": "error_registered", "deal_id": deal.get("Id"), "reason": str(exc)}
        except RuntimeError as exc:
            logger.warning(
                "[LOGISTICS_DIRECT] Erro operacional Deal %s: %s", deal.get("Id"), exc
            )
            self._mark_deal_error(deal["Id"], str(exc))
            return {"action": "error_registered", "deal_id": deal.get("Id"), "reason": str(exc)}
        except httpx.HTTPStatusError as exc:
            reason = self._describe_bling_http_error(exc)
            logger.warning("[LOGISTICS_DIRECT] Erro Bling Deal %s: %s", deal.get("Id"), reason)
            self._mark_deal_error(deal["Id"], reason)
            return {"action": "error_registered", "deal_id": deal.get("Id"), "reason": reason}

        self._save_order_link(deal["Id"], sales_order_id, None)

        situacao_id = self.settings.bling_situacao_pronto_faturar
        if situacao_id:
            try:
                self.bling.update_sales_order_situacao(sales_order_id, situacao_id)
                self._update_order_link_situacao(deal["Id"], situacao_id)
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "[LOGISTICS_DIRECT] Falha ao mudar situacao do pedido %s: %s",
                    sales_order_id,
                    self._describe_bling_http_error(exc),
                )
        else:
            logger.info(
                "[LOGISTICS_DIRECT] situacao pronto_faturar nao configurada (id=0) | pedido=%s | pulando",
                sales_order_id,
            )

        order_number = sales_order.get("numero") or sales_order_id
        title = deal.get("Title") or ""
        new_title = title if str(title).startswith(str(order_number)) else f"{order_number} - {title}"
        order_reference = (
            f"Pedido Bling {order_number}: "
            f"https://www.bling.com.br/vendas.php#edit/{sales_order_id}"
        )
        other_properties = [
            {
                "FieldKey": self.settings.ploomes_deal_order_field,
                "StringValue": order_reference,
            }
        ]
        if self.settings.ploomes_deal_sales_order_id_field:
            other_properties.append(
                {
                    "FieldKey": self.settings.ploomes_deal_sales_order_id_field,
                    "StringValue": str(sales_order_id),
                }
            )
        self.ploomes.update_deal(deal["Id"], {"Title": new_title, "OtherProperties": other_properties})

        logger.info(
            "[LOGISTICS_DIRECT] Pedido de venda %s criado direto para Logistica a partir do Deal %s",
            sales_order_id,
            deal.get("Id"),
        )
        return {
            "action": "created",
            "deal_id": deal.get("Id"),
            "bling_order_id": sales_order_id,
            "bling_order_number": sales_order.get("numero"),
        }

    def _record_and_get_previous_stage(
        self, deal_id: int | str, current_stage_id: Any
    ) -> int | None:
        try:
            conn = get_db_conn(self.settings)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT last_seen_stage_id FROM ploomes_deal_stage_tracking "
                        "WHERE ploomes_deal_id = %s",
                        (deal_id,),
                    )
                    row = cur.fetchone()
                    previous_stage_id = row[0] if row else None

                    cur.execute(
                        """
                        INSERT INTO ploomes_deal_stage_tracking
                            (ploomes_deal_id, last_seen_stage_id, updated_at)
                        VALUES (%s, %s, now())
                        ON CONFLICT (ploomes_deal_id) DO UPDATE SET
                            last_seen_stage_id = EXCLUDED.last_seen_stage_id,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (deal_id, current_stage_id),
                    )
                conn.commit()
            finally:
                conn.close()
            return previous_stage_id
        except Exception as exc:
            logger.warning(
                "[STAGE_TRACKING] Falha ao ler/gravar ploomes_deal_stage_tracking | deal_id=%s | %s",
                deal_id,
                exc,
            )
            return None

    def _get_order_link(self, deal: dict[str, Any]) -> dict[str, Any] | None:
        # Fonte de verdade preferencial: campo do Deal no Ploomes (dispensa Postgres).
        # Quando o campo esta configurado, ele decide sozinho: campo vazio = confirmado
        # sem pedido (nao cai no fallback Postgres, que nao tem conectividade real com
        # o Cloud Run -- ver _save_order_link, que pelo mesmo motivo nem tenta gravar
        # la quando este campo esta configurado).
        field = self.settings.ploomes_deal_sales_order_id_field
        if field:
            raw = get_other_property(deal, field)
            if raw in (None, ""):
                return None
            try:
                return {"bling_pedido_venda_id": int(raw), "bling_pedido_compra_id": None}
            except (TypeError, ValueError):
                logger.warning(
                    "[LOGISTICS] Campo do pedido no Deal com valor invalido | deal_id=%s | %r",
                    deal.get("Id"),
                    raw,
                )
                return None

        # Fallback legado (so quando o campo do Deal nao esta configurado): bling_order_links (Postgres).
        deal_id = deal.get("Id")
        try:
            conn = get_db_conn(self.settings)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT bling_pedido_venda_id, bling_pedido_compra_id "
                        "FROM bling_order_links WHERE ploomes_deal_id = %s",
                        (deal_id,),
                    )
                    row = cur.fetchone()
            finally:
                conn.close()
        except Exception as exc:
            # Nao pode tratar falha de leitura como "sem pedido vinculado": os
            # chamadores usam esse resultado pra decidir se criam um pedido novo
            # no Bling. Se o vinculo existe mas nao conseguimos confirmar por
            # falha (ex: Postgres fora do ar), retornar None aqui cria duplicata
            # a cada retry do webhook -- por isso propaga o erro em vez de
            # assumir silenciosamente que nao ha pedido.
            raise RuntimeError(
                f"Falha ao consultar vinculo de pedido do Deal {deal_id}: {exc}"
            ) from exc

        if not row:
            return None
        return {"bling_pedido_venda_id": row[0], "bling_pedido_compra_id": row[1]}

    def _update_order_link_situacao(self, deal_id: int | str, situacao_id: int) -> None:
        # Com o campo do Deal configurado, o vinculo vive no Ploomes -- nao usa Postgres.
        if self.settings.ploomes_deal_sales_order_id_field:
            return
        try:
            conn = get_db_conn(self.settings)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE bling_order_links SET last_situacao_id = %s, updated_at = now() "
                        "WHERE ploomes_deal_id = %s",
                        (situacao_id, deal_id),
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(
                "[LOGISTICS] Falha ao atualizar bling_order_links | deal_id=%s | %s", deal_id, exc
            )

    def _restore_order_link_field(
        self, deal: dict[str, Any], order_id: int | str, order_number: Any
    ) -> None:
        # Best-effort: se falhar, o pior caso e' o campo continuar com o que
        # tinha antes -- nunca deve derrubar o fluxo principal, que ja
        # completou com sucesso quando isto e' chamado.
        deal_id = deal.get("Id")
        try:
            order_reference = (
                f"Pedido Bling {order_number or order_id}: "
                f"https://www.bling.com.br/vendas.php#edit/{order_id}"
            )
            current = get_other_property(deal, self.settings.ploomes_deal_order_field)
            if current == order_reference:
                return
            self.ploomes.update_deal(
                deal_id,
                {
                    "OtherProperties": [
                        {
                            "FieldKey": self.settings.ploomes_deal_order_field,
                            "StringValue": order_reference,
                        }
                    ],
                },
            )
            logger.info(
                "[LOGISTICS] Link do pedido restaurado no campo do Deal | deal_id=%s pedido=%s",
                deal_id,
                order_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[LOGISTICS] Falha ao restaurar link do pedido no campo do Deal | deal_id=%s | %s",
                deal_id,
                exc,
            )

    def _find_purchase_trigger_rule(self, deal: dict[str, Any]) -> PurchaseTriggerRule | None:
        pipeline_id = int(deal.get("PipelineId") or 0)
        stage_id = int(deal.get("StageId") or 0)
        for rule in self._purchase_trigger_rules():
            if rule.pipeline_id == pipeline_id and rule.trigger_stage_id == stage_id:
                return rule
        return None

    def _purchase_trigger_rules(self) -> list[PurchaseTriggerRule]:
        rules = []
        for item in self.settings.ploomes_deal_purchase_trigger_stage_rules.split(","):
            parts = [part.strip() for part in item.split(":")]
            if len(parts) != 3 or not all(parts):
                continue
            rules.append(PurchaseTriggerRule(*(int(part) for part in parts)))
        return rules

    def _find_logistics_rule(self, deal: dict[str, Any]) -> LogisticsRule | None:
        pipeline_id = int(deal.get("PipelineId") or 0)
        stage_id = int(deal.get("StageId") or 0)
        for rule in self._logistics_rules():
            if rule.pipeline_id == pipeline_id and rule.stage_id == stage_id:
                return rule
        return None

    def _logistics_rules(self) -> list[LogisticsRule]:
        rules = []
        for item in self.settings.ploomes_deal_logistics_stage_rules.split(","):
            parts = [part.strip() for part in item.split(":")]
            if len(parts) != 2 or not all(parts):
                continue
            rules.append(LogisticsRule(*(int(part) for part in parts)))
        return rules

    def _find_direct_to_logistics_rule(
        self, deal: dict[str, Any]
    ) -> DirectToLogisticsRule | None:
        pipeline_id = int(deal.get("PipelineId") or 0)
        for rule in self._direct_to_logistics_rules():
            if rule.pipeline_id == pipeline_id:
                return rule
        return None

    def _direct_to_logistics_rules(self) -> list[DirectToLogisticsRule]:
        # Formato: pipeline_id:origem1,origem2,...:destino (uma unica regra, nao
        # multiplas separadas por virgula -- a virgula aqui separa as origens).
        raw = self.settings.ploomes_deal_direct_to_logistics_rules.strip()
        if not raw:
            return []
        parts = raw.split(":")
        if len(parts) != 3:
            return []
        pipeline_id_str, origins_str, target_str = (part.strip() for part in parts)
        origin_ids = frozenset(
            int(item.strip()) for item in origins_str.split(",") if item.strip()
        )
        if not pipeline_id_str or not origin_ids or not target_str:
            return []
        return [
            DirectToLogisticsRule(
                pipeline_id=int(pipeline_id_str),
                source_stage_ids=origin_ids,
                target_stage_id=int(target_str),
            )
        ]

    def _build_sales_order_payload(self, deal: dict[str, Any], quote: dict[str, Any]) -> dict[str, Any]:
        contact = deal.get("Contact") or {}
        document = self._clean_document(contact.get("CNPJ") or contact.get("CPF"))
        if not document:
            raise DealOrderValidationError("Contato do Deal sem CPF/CNPJ")

        logger.info(
            "[DEAL_ORDER] Buscando contato no Bling | deal_id=%s documento_final=%s",
            deal.get("Id"),
            document[-4:],
        )
        bling_contact = self.bling.get_contact_by_document(document)
        if not bling_contact:
            name = contact.get("Name") or deal.get("ContactName") or document
            raise DealOrderValidationError(f"Cliente {name} CPF/CNPJ {document} nao cadastrado no Bling")
        logger.info(
            "[DEAL_ORDER] Contato Bling encontrado | deal_id=%s bling_contact_id=%s",
            deal.get("Id"),
            bling_contact.get("id"),
        )

        items, total = self._build_items(quote)
        purchase_order = self._get_property_value(
            deal,
            self.settings.ploomes_deal_purchase_order_field,
        )
        if not purchase_order:
            raise DealOrderValidationError(
                "Deal sem numero do pedido de compra do cliente "
                "(campo obrigatorio para gerar pedido no Bling)"
            )
        payment_method_name = self._get_property_value(
            deal,
            self.settings.ploomes_deal_payment_method_field,
            value_keys=("ObjectValueName", "StringValue", "IntegerValue"),
        )
        payment_method_id = self._lookup_config_map(
            self.settings.bling_payment_methods,
            payment_method_name,
        )
        if not payment_method_id:
            raise DealOrderValidationError(f"Forma de pagamento nao mapeada: {payment_method_name}")
        logger.info(
            "[DEAL_ORDER] Pagamento mapeado | deal_id=%s forma=%s bling_forma_id=%s dias=%s",
            deal.get("Id"),
            payment_method_name,
            payment_method_id,
            self._payment_days(deal),
        )

        payment_days = self._payment_days(deal)
        external_notes = self._get_property_value(
            deal,
            self.settings.ploomes_deal_external_notes_field,
        )
        internal_notes = self._get_property_value(
            deal,
            self.settings.ploomes_deal_internal_notes_field,
        )
        freight_value = self._get_property_value(
            deal,
            self.settings.ploomes_deal_freight_value_field,
        )
        if freight_value is not None:
            total += float(freight_value)

        payload: dict[str, Any] = {
            "data": datetime.now().strftime("%Y-%m-%dT%H:%M:%S-03:00"),
            "dataSaida": "",
            "contato": {"id": bling_contact["id"]},
            "numeroPedidoCompra": purchase_order,
            "outrasDespesas": 0,
            "observacoes": external_notes,
            "observacoesInternas": internal_notes,
            "tributacao": {
                "totalICMS": 0,
                "totalIPI": 0,
            },
            "loja": {"id": 0},
            "itens": items,
            "parcelas": self._build_installments(total, payment_days, payment_method_id),
        }

        seller_id = self._lookup_config_map(self.settings.bling_seller_map, deal.get("OwnerId"))
        if seller_id:
            payload["vendedor"] = {"id": int(seller_id)}

        transport = self._build_transport(deal, freight_value)
        if transport:
            payload["transporte"] = transport
            logger.info(
                "[DEAL_ORDER] Transporte mapeado | deal_id=%s frete_por_conta=%s transportadora_id=%s frete=%s",
                deal.get("Id"),
                transport.get("fretePorConta"),
                transport.get("contato", {}).get("id", "-"),
                transport.get("frete", "-"),
            )

        return payload

    def _build_items(self, quote: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
        items = []
        total = 0.0
        for product in quote.get("Products") or []:
            quantity = product.get("Quantity")
            if quantity is None:
                raise DealOrderValidationError(
                    f"Item {product.get('ProductName', '')} sem quantidade informada"
                )

            unit_price = float(product.get("UnitPrice") or 0)
            discount = float(product.get("Discount") or 0)
            quantity_float = float(quantity)
            total += self._apply_discount(unit_price, discount) * quantity_float
            bling_product = self._resolve_bling_product_for_item(product)
            descricao = (product.get("ProductName") or "").upper()
            if len(descricao) > ITEM_DESCRICAO_MAX_LENGTH:
                raise DealOrderValidationError(
                    f"Item {descricao} com descricao maior que {ITEM_DESCRICAO_MAX_LENGTH} "
                    f"caracteres ({len(descricao)})"
                )
            items.append(
                {
                    "produto": {"id": bling_product["id"]},
                    "unidade": "UN",
                    "quantidade": quantity,
                    "desconto": discount,
                    "valor": unit_price,
                    "aliquotaIPI": 0,
                    "descricao": descricao,
                    "descricaoDetalhada": "",
                    "comissao": {
                        "base": quantity_float * unit_price,
                        "aliquota": 1.5,
                    },
                }
            )

        if not items:
            raise DealOrderValidationError("Quote sem produtos para gerar pedido")
        return items, total

    def _resolve_bling_product_for_item(self, quote_item: dict[str, Any]) -> dict[str, Any]:
        ploomes_product_id = quote_item.get("ProductId")
        if not ploomes_product_id:
            raise DealOrderValidationError(
                f"Item {quote_item.get('ProductName', '')} sem ProductId do Ploomes"
            )

        ploomes_product = self.ploomes.get_product_by_id(ploomes_product_id)
        partnumber = get_other_property(ploomes_product, self.settings.ploomes_field_partnumber)
        partnumber = str(partnumber).strip() if partnumber else ""
        if not partnumber:
            raise DealOrderValidationError(
                self._describe_missing_product_fields(ploomes_product, missing_partnumber=True)
            )

        bling_product = self.bling.get_product_by_code(partnumber)
        if bling_product:
            logger.info(
                "[DEAL_ORDER] Produto vinculado no Bling | ploomes_product_id=%s partnumber=%s bling_product_id=%s",
                ploomes_product_id,
                partnumber,
                bling_product.get("id"),
            )
            return bling_product

        try:
            payload = map_ploomes_to_bling(ploomes_product, self.settings)
        except ProductMappingError as exc:
            raise DealOrderValidationError(
                f"Produto Ploomes {ploomes_product_id} nao pode ser criado no Bling: {exc} - "
                f"{self._ploomes_product_url(ploomes_product_id)}"
            ) from exc
        payload["codigo"] = partnumber
        bling_product = self.bling.create_product(payload)
        logger.info(
            "[DEAL_ORDER] Produto criado no Bling | ploomes_product_id=%s partnumber=%s bling_product_id=%s",
            ploomes_product_id,
            partnumber,
            bling_product.get("id"),
        )
        return bling_product

    def _describe_missing_product_fields(
        self, ploomes_product: dict[str, Any], missing_partnumber: bool = False
    ) -> str:
        # Reporta de uma vez todos os campos obrigatorios que estao faltando no produto,
        # em vez de bloquear so pelo partnumber e deixar o usuario descobrir os outros
        # (fabricante, breve descricao, preco) num segundo round de tentativa.
        fields = extract_ploomes_fields(ploomes_product, self.settings)
        missing = []
        if missing_partnumber:
            missing.append("partnumber (SKU)")
        if not fields["fabricante"]:
            missing.append("fabricante")
        if not fields["breve_descricao"]:
            missing.append("breve descricao")

        ploomes_id = ploomes_product.get("Id", "?")
        return (
            f"Produto Ploomes {ploomes_id} sem campos obrigatorios: {', '.join(missing)} - "
            f"{self._ploomes_product_url(ploomes_id)}"
        )

    def _ploomes_product_url(self, ploomes_product_id: Any) -> str:
        return f"{self.settings.ploomes_web_base_url}/Products/table/product/{ploomes_product_id}"

    def _build_transport(
        self,
        deal: dict[str, Any],
        freight_value: Any,
    ) -> dict[str, Any]:
        freight_name = self._get_property_value(
            deal,
            self.settings.ploomes_deal_freight_type_field,
            value_keys=("ObjectValueName", "StringValue", "IntegerValue"),
        )
        if not freight_name:
            raise DealOrderValidationError("Tipo de frete nao informado")

        freight_code = self._lookup_config_map(self.settings.bling_freight_methods, freight_name)
        if not freight_code:
            raise DealOrderValidationError(f"Tipo de frete nao mapeado: {freight_name}")

        carrier = self._resolve_bling_carrier(deal)
        # fretePorConta e um inteiro na API do Bling (0=CIF, 1=FOB, 2=Terceiros, 3/4=proprio, 9=sem transporte).
        transport: dict[str, Any] = {"fretePorConta": int(freight_code)}
        if carrier:
            transport["contato"] = {"id": carrier["id"]}
        if freight_value is not None:
            transport["frete"] = float(freight_value)
        return transport

    def _resolve_bling_carrier(self, deal: dict[str, Any]) -> dict[str, Any] | None:
        carrier_document = self._clean_document(
            self._get_property_value(
                deal,
                self.settings.ploomes_deal_carrier_field,
                value_keys=("ContactValueRegister",),
            )
        )
        carrier = self.bling.get_contact_by_document(carrier_document)
        if carrier:
            return carrier

        carrier_name = self._get_property_value(
            deal,
            self.settings.ploomes_deal_carrier_field,
            value_keys=("ContactValueName",),
        )
        if not carrier_name:
            return None

        result = self.bling.search_contacts(pesquisa=carrier_name, limite=1)
        contacts = result.get("data", [])
        return contacts[0] if contacts else None

    def _build_installments(
        self,
        total: float,
        payment_days: str | int | float | None,
        payment_method_id: str,
    ) -> list[dict[str, Any]]:
        days = str(payment_days or 0)
        raw_parts = [part.strip() for part in days.split("/") if part.strip()]
        if not raw_parts:
            raw_parts = ["0"]
        # Bling nao aceita parcela com vencimento no mesmo dia da emissao;
        # prazo 0 sempre vira 1 dia, para qualquer forma de pagamento.
        parts = [int(float(part)) or 1 for part in raw_parts]

        installment_value = total / len(parts)
        return [
            {
                "dataVencimento": (
                    datetime.today() + timedelta(days=days_offset)
                ).strftime("%Y-%m-%d"),
                "valor": installment_value,
                "observacoes": "",
                "formaPagamento": {"id": int(payment_method_id)},
            }
            for days_offset in parts
        ]

    def _payment_days(self, deal: dict[str, Any]) -> Any:
        value = self._get_property_value(deal, self.settings.ploomes_deal_payment_days_field)
        if value is not None:
            return value
        return self._get_property_value(
            deal,
            self.settings.ploomes_deal_payment_days_fallback_field,
        )

    def _find_stage_rule(self, deal: dict[str, Any]) -> StageRule | None:
        pipeline_id = int(deal.get("PipelineId") or 0)
        stage_id = int(deal.get("StageId") or 0)
        for rule in self._stage_rules():
            if rule.pipeline_id == pipeline_id and rule.source_stage_id == stage_id:
                return rule
        return None

    def _stage_rules(self) -> list[StageRule]:
        rules = []
        for item in self.settings.ploomes_deal_stage_rules.split(","):
            parts = [part.strip() for part in item.split(":")]
            if len(parts) != 3 or not all(parts):
                continue
            rules.append(StageRule(*(int(part) for part in parts)))
        return rules

    def _owner_email_for_deal(self, deal: dict[str, Any]) -> str | None:
        owner_id = deal.get("OwnerId")
        if not owner_id:
            return None
        try:
            return self.ploomes.get_user_email(owner_id)
        except Exception as exc:  # noqa: BLE001 - nunca deve impedir a notificacao principal
            logger.warning(
                "[EMAIL] Falha ao buscar e-mail do responsavel | deal_id=%s owner_id=%s | %s",
                deal.get("Id"),
                owner_id,
                exc,
            )
            return None

    def _mark_deal_error(self, deal_id: int | str, message: str) -> None:
        logger.info(
            "[DEAL_ORDER] Marcando Deal com erro | deal_id=%s error_stage_id=%s mensagem=%s",
            deal_id,
            self.settings.ploomes_deal_error_stage_id,
            message[:200],
        )
        self.ploomes.update_deal(
            deal_id,
            {
                "StageId": self.settings.ploomes_deal_error_stage_id,
                "OtherProperties": [
                    {
                        "FieldKey": self.settings.ploomes_deal_order_field,
                        "StringValue": message[:500],
                    }
                ],
            },
        )
        self._notify_error_email(deal_id, message)

    def _notify_error_email(self, deal_id: int | str, message: str) -> None:
        # Best-effort, mesma logica de _notify_logistics_email: notificar nunca
        # pode derrubar o fluxo principal (o Deal ja foi marcado com erro acima,
        # independente do envio de e-mail funcionar ou nao).
        if not self.settings.send_mail_service_url:
            return
        try:
            deal_link = f"{self.settings.ploomes_web_base_url}/deal/{deal_id}"
            recipients = ["gabriel.santos@cmcimportacao.com"]
            try:
                deal = self.ploomes.get_deal_by_id(deal_id)
                owner_email = self._owner_email_for_deal(deal)
                if owner_email and owner_email not in recipients:
                    recipients.append(owner_email)
            except Exception:  # noqa: BLE001 - falha ao achar responsavel nao impede o e-mail base
                pass
            html = f"""
            <div style="font-family:Arial,sans-serif;font-size:14px;color:#222">
              <p><strong>Falha na automacao Ploomes -&gt; Bling</strong> para o Deal {deal_id}.</p>
              <table style='border-collapse:collapse;margin-top:8px'>
                <tr><td style='padding:4px 8px;font-weight:bold'>Deal</td><td style='padding:4px 8px'><a href='{deal_link}'>{deal_link}</a></td></tr>
                <tr><td style='padding:4px 8px;font-weight:bold'>Erro</td><td style='padding:4px 8px'>{message[:1000]}</td></tr>
              </table>
              <p><em>O Deal foi movido para o estagio de erro e o motivo foi salvo no campo do Deal.
              Esta automacao nao vai tentar de novo sozinha ate o Deal mudar de estagio.</em></p>
            </div>
            """
            response = httpx.post(
                self.settings.send_mail_service_url.rstrip("/") + "/send-email",
                json={
                    "to": recipients,
                    "subject": f"[ERRO] Automacao Bling falhou -- Deal {deal_id}",
                    "html": html,
                },
                timeout=15.0,
            )
            response.raise_for_status()
            logger.info("[ERROR_EMAIL] Notificacao de erro enviada | deal_id=%s", deal_id)
        except Exception as exc:  # noqa: BLE001 - notificacao nunca pode propagar erro
            logger.warning(
                "[ERROR_EMAIL] Falha ao enviar notificacao de erro | deal_id=%s | %s",
                deal_id,
                exc,
            )

    def _mark_deal_success(
        self,
        deal: dict[str, Any],
        order: dict[str, Any],
        rule: StageRule,
    ) -> None:
        order_id = order.get("id")
        order_number = order.get("numero") or order_id
        title = deal.get("Title") or ""
        new_title = title if str(title).startswith(str(order_number)) else f"{order_number} - {title}"
        order_reference = (
            f"Pedido Bling {order_number}: "
            f"https://www.bling.com.br/vendas.php#edit/{order_id}"
        )
        logger.info(
            "[DEAL_ORDER] Marcando Deal com sucesso | deal_id=%s stage_destino=%s order_id=%s order_number=%s",
            deal.get("Id"),
            rule.target_stage_id,
            order_id,
            order_number,
        )
        other_properties = [
            {
                "FieldKey": self.settings.ploomes_deal_order_field,
                "StringValue": order_reference,
            }
        ]
        # Sem isto, _get_order_link nunca enxerga o pedido criado por este metodo
        # (usado pelo fluxo legado e pelo faturamento parcial) e cada webhook
        # seguinte -- inclusive o que o proprio update_deal abaixo dispara --
        # recria outro pedido (ver ORDER_CREATION_COOLDOWN_SECONDS).
        if self.settings.ploomes_deal_sales_order_id_field and order_id:
            other_properties.append(
                {
                    "FieldKey": self.settings.ploomes_deal_sales_order_id_field,
                    "StringValue": str(order_id),
                }
            )
        self.ploomes.update_deal(
            deal["Id"],
            {
                "Title": new_title,
                "StageId": rule.target_stage_id,
                "OtherProperties": other_properties,
            },
        )

    def _get_property_value(
        self,
        deal: dict[str, Any],
        field_key: str,
        value_keys: tuple[str, ...] | None = None,
    ) -> Any:
        keys = value_keys or (
            "StringValue",
            "BigStringValue",
            "IntegerValue",
            "DecimalValue",
            "ObjectValueName",
            "ContactValueRegister",
            "DateTimeValue",
        )
        for item in deal.get("OtherProperties") or []:
            if item.get("FieldKey") != field_key:
                continue
            for value_key in keys:
                value = item.get(value_key)
                if value not in (None, ""):
                    return value
        return None

    def _lookup_config_map(self, config: str, key: Any) -> str | None:
        if key is None:
            return None
        normalized_key = self._normalize_key(str(key))
        for item in config.split(","):
            if ":" not in item:
                continue
            raw_key, value = item.split(":", 1)
            if self._normalize_key(raw_key) == normalized_key:
                return value.strip()
        return None

    def _clean_document(self, value: Any) -> str | None:
        if value is None:
            return None
        digits = "".join(char for char in str(value) if char.isdigit())
        return digits or None

    def _normalize_key(self, value: str) -> str:
        without_accents = unicodedata.normalize("NFKD", value)
        ascii_value = without_accents.encode("ascii", "ignore").decode("ascii")
        return " ".join(ascii_value.lower().split())

    def _apply_discount(self, price: float, discount_percent: float) -> float:
        return price - (price * (discount_percent / 100))

    def _is_same_situacao_error(self, exc: httpx.HTTPStatusError) -> bool:
        # Bling recusa PATCH de situacao pra uma situacao igual a atual (erro de
        # validacao, nao um no-op silencioso). Do ponto de vista da automacao isso
        # nao e' uma falha: o resultado desejado (pedido na situacao X) ja foi
        # alcancado, so' nao foi ESTA chamada que fez. Tratar como erro real
        # levava o Deal pra pendencia e sobrescrevia o link do pedido no campo
        # do Deal com a mensagem de erro (ver Deal 1107128022, pedido 8978).
        try:
            body = exc.response.json()
        except ValueError:
            return False
        fields = (body.get("error") or {}).get("fields") or []
        return any("mesma situa" in (f.get("msg") or "").lower() for f in fields)

    def _update_situacao_tolerando_mesma_situacao(
        self, order_id: int | str, situacao_id: int
    ) -> None:
        try:
            self.bling.update_sales_order_situacao(order_id, situacao_id)
        except httpx.HTTPStatusError as exc:
            if not self._is_same_situacao_error(exc):
                raise
            logger.info(
                "[LOGISTICS] Pedido %s ja estava na situacao %s -- nada a fazer.",
                order_id,
                situacao_id,
            )

    def _describe_bling_http_error(self, exc: httpx.HTTPStatusError) -> str:
        try:
            body = exc.response.json()
        except ValueError:
            return f"Bling retornou {exc.response.status_code}: {exc.response.text[:300]}"

        error = body.get("error") or {}
        message = error.get("description") or error.get("message")
        fields = error.get("fields") or []
        if fields:
            field_messages = ", ".join(
                f"{field.get('element', '?')}: {field.get('msg', '')}" for field in fields
            )
            message = f"{message} ({field_messages})" if message else field_messages
        return message or f"Bling retornou {exc.response.status_code}: {body}"
