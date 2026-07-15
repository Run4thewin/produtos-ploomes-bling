import logging
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


class DealToBlingOrderSyncService:
    def __init__(
        self,
        settings: Settings | None = None,
        bling: BlingClient | None = None,
        ploomes: PloomesClient | None = None,
    ):
        self.settings = settings or get_settings()
        self.bling = bling or BlingClient(self.settings)
        self.ploomes = ploomes or PloomesClient(self.settings)

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
        created = self.bling.create_sales_order(payload)
        order_id = created.get("id")
        if not order_id:
            raise RuntimeError(f"Bling criou pedido sem retornar id: {created}")

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

        quote = self.ploomes.get_latest_quote_by_deal(deal["Id"])
        if not quote:
            raise DealOrderValidationError("Deal sem quote/orcamento para gerar pedido")

        payload = self._build_sales_order_payload(deal, quote)
        created = self.bling.create_sales_order(payload)
        sales_order_id = created.get("id")
        if not sales_order_id:
            raise RuntimeError(f"Bling criou pedido de venda sem retornar id: {created}")
        sales_order = self.bling.get_sales_order(sales_order_id)

        purchase_order_id = self._create_linked_purchase_order(payload["itens"], sales_order)

        self._save_order_link(deal["Id"], sales_order_id, purchase_order_id)
        self._mark_deal_purchase_flow_success(deal, sales_order, purchase_order_id, rule)
        self._advance_sales_order_situacao(
            sales_order_id, self.settings.bling_situacao_em_processo_compra
        )

        logger.info(
            "[PURCHASE_FLOW] Pedido de venda %s + pedido de compra %s criados a partir do Deal %s",
            sales_order_id,
            purchase_order_id,
            deal.get("Id"),
        )
        return {
            "action": "created",
            "deal_id": deal.get("Id"),
            "bling_order_id": sales_order_id,
            "bling_order_number": sales_order.get("numero"),
            "bling_purchase_order_id": purchase_order_id,
        }

    def _create_linked_purchase_order(
        self, sales_items: list[dict[str, Any]], sales_order: dict[str, Any]
    ) -> int | None:
        # Sem fornecedor e sem regra de replicacao de itens confirmada -- payload minimo,
        # reaproveitando os itens do pedido de venda. Ver plano: "nao precisa ser preenchido
        # agora" (fornecedor) e "nao aplicar esta regra se nao for necessario" (itens).
        items = [
            {
                "descricao": item.get("descricao"),
                "unidade": item.get("unidade"),
                "quantidade": item.get("quantidade"),
                "valor": item.get("valor"),
                "produto": item.get("produto"),
            }
            for item in sales_items
        ]
        payload: dict[str, Any] = {
            "itens": items,
            "ordemCompra": f"Pedido de venda {sales_order.get('numero') or sales_order.get('id')}",
        }
        try:
            created = self.bling.create_purchase_order(payload)
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "[PURCHASE_FLOW] Falha ao criar pedido de compra vinculado ao pedido de venda %s: %s",
                sales_order.get("id"),
                self._describe_bling_http_error(exc),
            )
            return None
        return created.get("id")

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
        self.ploomes.update_deal(
            deal["Id"],
            {
                "StageId": rule.target_stage_id,
                "OtherProperties": other_properties,
            },
        )

    def _save_order_link(
        self, deal_id: int | str, sales_order_id: int, purchase_order_id: int | None
    ) -> None:
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

    def update_situacao_for_logistics_stage(self, deal_id: int | str) -> dict[str, Any]:
        deal = self.ploomes.get_deal_by_id(deal_id)
        rule = self._find_logistics_rule(deal)
        if not rule:
            return {
                "action": "skipped",
                "reason": "stage_nao_configurado",
                "deal_id": deal.get("Id"),
            }

        link = self._get_order_link(deal["Id"])
        if not link or not link.get("bling_pedido_venda_id"):
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
            self.bling.update_sales_order_situacao(sales_order_id, situacao_id)
        except httpx.HTTPStatusError as exc:
            reason = self._describe_bling_http_error(exc)
            logger.warning(
                "[LOGISTICS] Falha ao mudar situacao do pedido %s: %s", sales_order_id, reason
            )
            return {"action": "error_registered", "deal_id": deal.get("Id"), "reason": reason}

        self._update_order_link_situacao(deal["Id"], situacao_id)
        return {
            "action": "situacao_atualizada",
            "deal_id": deal.get("Id"),
            "bling_order_id": sales_order_id,
            "situacao_id": situacao_id,
        }

    def _get_order_link(self, deal_id: int | str) -> dict[str, Any] | None:
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
            logger.warning(
                "[LOGISTICS] Falha ao ler bling_order_links | deal_id=%s | %s", deal_id, exc
            )
            return None

        if not row:
            return None
        return {"bling_pedido_venda_id": row[0], "bling_pedido_compra_id": row[1]}

    def _update_order_link_situacao(self, deal_id: int | str, situacao_id: int) -> None:
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
            descricao_completa = (product.get("ProductName") or "").upper()
            items.append(
                {
                    "produto": {"id": bling_product["id"]},
                    "unidade": "UN",
                    "quantidade": quantity,
                    "desconto": discount,
                    "valor": unit_price,
                    "aliquotaIPI": 0,
                    "descricao": descricao_completa[:ITEM_DESCRICAO_MAX_LENGTH],
                    "descricaoDetalhada": (
                        descricao_completa
                        if len(descricao_completa) > ITEM_DESCRICAO_MAX_LENGTH
                        else ""
                    ),
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
        if fields["preco"] <= 0:
            missing.append("preco de venda")

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
        parts = [part.strip() for part in days.split("/") if part.strip()]
        if not parts:
            parts = ["0"]

        installment_value = total / len(parts)
        return [
            {
                "dataVencimento": (
                    datetime.today() + timedelta(days=int(float(part)))
                ).strftime("%Y-%m-%d"),
                "valor": installment_value,
                "observacoes": "",
                "formaPagamento": {"id": int(payment_method_id)},
            }
            for part in parts
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
        self.ploomes.update_deal(
            deal["Id"],
            {
                "Title": new_title,
                "StageId": rule.target_stage_id,
                "OtherProperties": [
                    {
                        "FieldKey": self.settings.ploomes_deal_order_field,
                        "StringValue": order_reference,
                    }
                ],
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
