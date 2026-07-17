"""Uso LOCAL. Pre-flight: verifica se um Deal esta pronto para GERAR o pedido de
venda no Bling, checando os mesmos portoes que _build_sales_order_payload usa.
So faz GETs (Ploomes e Bling) -- NAO cria pedido, contato nem produto.

Rodar (na raiz do repo):
    $env:PYTHONPATH="."; python verificar_deal.py 1107064301
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.config import get_settings
from app.services.sync_deal_to_bling_order import (
    ITEM_DESCRICAO_MAX_LENGTH,
    DealToBlingOrderSyncService,
    get_other_property,
)

deal_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1107064301

s = get_settings()
svc = DealToBlingOrderSyncService(s)
deal = svc.ploomes.get_deal_by_id(deal_id)
contact = deal.get("Contact") or {}

problems: list[str] = []


def bling_safe(fn, *a):
    """Chama o Bling e devolve (resultado, erro). Bling local precisa de token OAuth."""
    try:
        return fn(*a), None
    except Exception as e:  # noqa: BLE001
        return None, f"{e.__class__.__name__}: {e}"


print(f"Deal {deal_id}: {deal.get('Title')}")
print(f"  pipeline={deal.get('PipelineId')}  stage={deal.get('StageId')}")
print("-" * 60)

# 1) CPF/CNPJ no Ploomes
doc = svc._clean_document(contact.get("CNPJ") or contact.get("CPF"))
if not doc:
    problems.append("Contato sem CPF/CNPJ no Ploomes")
    print("[X] 1. contato sem CPF/CNPJ")
else:
    print(f"[OK] 1. CPF/CNPJ = {doc}")
    # 2) contato no Bling
    bc, err = bling_safe(svc.bling.get_contact_by_document, doc)
    if err:
        print(f"[!] 2. nao consegui checar contato no Bling ({err})")
    elif not bc:
        problems.append("Documento nao cadastrado como contato no Bling")
        print("[X] 2. documento NAO existe no Bling")
    else:
        print(f"[OK] 2. contato Bling id={bc.get('id')}")

# 3) forma de pagamento mapeada
pm = svc._get_property_value(
    deal,
    s.ploomes_deal_payment_method_field,
    value_keys=("ObjectValueName", "StringValue", "IntegerValue"),
)
pmid = svc._lookup_config_map(s.bling_payment_methods, pm)
if not pmid:
    problems.append(f"Forma de pagamento nao mapeada: {pm!r}")
    print(f"[X] 3. forma de pagamento {pm!r} nao mapeada")
else:
    print(f"[OK] 3. forma de pagamento {pm!r} -> bling={pmid}")

# 4/5/6) orcamento, itens, produtos
quote = svc.ploomes.get_latest_quote_by_deal(deal_id)
if not quote:
    problems.append("Deal sem orcamento")
    print("[X] 4. sem orcamento")
else:
    prods = quote.get("Products") or []
    print(f"[OK] 4. orcamento id={quote.get('Id')} itens={len(prods)}")
    if not prods:
        problems.append("Orcamento sem itens")
    for p in prods:
        name = p.get("ProductName") or "?"
        pid = p.get("ProductId")
        if p.get("Quantity") is None:
            problems.append(f"Item '{name}' sem quantidade")
        descricao = (p.get("ProductName") or "").upper()
        if len(descricao) > ITEM_DESCRICAO_MAX_LENGTH:
            problems.append(
                f"Descricao do item > {ITEM_DESCRICAO_MAX_LENGTH} chars ({len(descricao)}): '{name}'"
            )
            print(f"   [X] '{name}': descricao {len(descricao)} chars (max {ITEM_DESCRICAO_MAX_LENGTH})")
        if not pid:
            problems.append(f"Item '{name}' sem ProductId")
            print(f"   [X] '{name}': sem ProductId")
            continue
        pp = svc.ploomes.get_product_by_id(pid)
        pn = get_other_property(pp, s.ploomes_field_partnumber)
        pn = str(pn).strip() if pn else ""
        if not pn:
            problems.append(f"Produto '{name}' sem partnumber (SKU) no Ploomes")
            print(f"   [X] '{name}': sem partnumber (SKU)")
            continue
        bp, err = bling_safe(svc.bling.get_product_by_code, pn)
        if err:
            print(f"   [!] '{name}' SKU={pn}: nao consegui checar no Bling ({err})")
        elif bp:
            print(f"   [OK] '{name}' SKU={pn} -> Bling id={bp.get('id')}")
        else:
            print(f"   [!] '{name}' SKU={pn}: NAO existe no Bling (seria criado no disparo)")

print("-" * 60)
if problems:
    print("BLOQUEIOS (resolver antes de disparar):")
    for pr in problems:
        print(f"  - {pr}")
else:
    print("TUDO OK -> o disparo deve criar o pedido no Bling.")
    print("(lembrete: com chave read-only, o pedido e criado mas o PATCH final da 401")
    print(" -> webhook retorna 502 e o Deal nao e movido. O pedido no Bling existe.)")
