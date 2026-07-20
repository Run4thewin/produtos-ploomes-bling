"""
Paridade entre as specs core e as colunas dos upserts antigos do blng_fetcher.
Se este teste quebrar, o refactor mudou o formato das tabelas existentes.
"""
import pytest

from blng_fetcher.specs import SPECS
from blng_fetcher.specs.base import INFRA_COLUMNS
from blng_fetcher.specs.core import CORE_SPECS

# Listas literais copiadas dos INSERTs do main.py antigo (nao editar sem
# migracao consciente das tabelas).
LEGACY_COLUMNS = {
    "bling_orders": [
        "id", "order_number", "status", "total", "created_at", "updated_at",
        "client_id", "client_name", "client_email", "client_cpf_cnpj", "client_ie",
        "shipping_address", "billing_address", "raw_json",
    ],
    "bling_contacts": [
        "id", "name", "document", "person_type", "is_supplier", "is_client",
        "email", "phone", "city", "state", "created_at", "updated_at", "raw_json",
        "internal_code", "trade_name", "contact_types", "country", "is_foreign",
        "email_nfe", "cell_phone", "street", "street_number", "complement",
        "neighborhood", "zip_code", "billing_street", "billing_city", "billing_state",
        "billing_zip_code", "state_registration", "state_registration_status",
        "municipal_registration", "rg", "issuing_agency", "public_agency",
        "birth_date", "gender", "place_of_birth", "credit_limit", "payment_terms",
        "financial_category_id", "seller_id", "contact_persons_count",
    ],
    "bling_nfe": [
        "id", "numero", "serie", "situation", "contact_id", "contact_name",
        "total", "issue_date", "created_at", "updated_at", "raw_json",
    ],
    "bling_contas_pagar": [
        "id", "description", "supplier_id", "supplier_name", "due_date", "value",
        "status", "competency", "category", "created_at", "updated_at", "raw_json",
    ],
    "bling_contas_receber": [
        "id", "description", "contact_id", "contact_name", "due_date", "value",
        "status", "competency", "category", "created_at", "updated_at", "raw_json",
    ],
    "bling_naturezas_operacao": [
        "id", "descricao", "situacao", "padrao", "created_at", "updated_at", "raw_json",
    ],
    "bling_produtos": [
        "id", "codigo", "nome", "descricao_curta", "preco", "situacao", "tipo",
        "formato", "marca", "ncm", "peso_liquido", "peso_bruto", "largura",
        "altura", "profundidade", "created_at", "updated_at", "raw_json",
    ],
}


@pytest.mark.parametrize("spec", CORE_SPECS, ids=lambda s: s.name)
def test_core_spec_columns_match_legacy(spec):
    legacy = set(LEGACY_COLUMNS[spec.table]) - {"id", "created_at", "updated_at", "raw_json"}
    spec_columns = {f.column for f in spec.fields}
    assert spec_columns == legacy, (
        f"{spec.name}: divergencia de colunas.\n"
        f"faltando na spec: {legacy - spec_columns}\n"
        f"sobrando na spec: {spec_columns - legacy}"
    )


@pytest.mark.parametrize("spec", SPECS.values(), ids=lambda s: s.name)
def test_spec_has_no_reserved_or_duplicate_columns(spec):
    columns = [f.column for f in spec.fields]
    assert len(columns) == len(set(columns))
    assert not set(columns) & set(INFRA_COLUMNS)


def test_registry_contains_the_seven_core_entities():
    for name in ("orders", "contacts", "nfe", "pagar", "receber", "naturezas", "produtos"):
        assert name in SPECS


# ---------------------------------------------------------------------------
# Extracao: valores identicos aos upserts antigos p/ payloads representativos
# ---------------------------------------------------------------------------

def test_orders_extraction_matches_legacy_logic():
    order = {
        "id": 123,
        "numero": 456,
        "situacao": {"id": 9, "valor": 1},
        "totalProdutos": 99.9,
        "data": "2026-07-01 10:00:00",
        "contato": {
            "id": 55, "nome": "Cliente X", "email": "x@y.z",
            "numeroDocumento": "123", "ie": "isento",
        },
        "transporte": {"enderecoEntrega": {
            "endereco": "Rua A", "numero": "10", "bairro": "Centro",
            "municipio": "SP", "uf": "SP", "cep": "01000-000",
        }},
    }
    row = SPECS["orders"].extract_row(order)
    assert row["order_number"] == "456"
    assert row["status"] == "9"
    assert row["total"] == 99.9
    assert row["client_id"] == "55"
    assert row["client_name"] == "Cliente X"
    assert row["shipping_address"] == "Rua A, 10, Centro, SP, SP, 01000-000"
    assert row["billing_address"] is None
    # situacao escalar (formato antigo da API)
    row2 = SPECS["orders"].extract_row({"situacao": 7})
    assert row2["status"] == "7"


def test_contacts_extraction_matches_legacy_logic():
    contact = {
        "id": 1,
        "nome": "Fornecedor Y",
        "numeroDocumento": "999",
        "tipo": "J",
        "tiposContato": [{"descricao": "Fornecedor"}, {"descricao": "Cliente"}],
        "telefone": "",
        "celular": "11 99999-0000",
        "endereco": {
            "geral": {"municipio": "Campinas", "uf": "SP", "endereco": "Rua B",
                      "numero": "20", "cep": "13000-000"},
            "cobranca": {"municipio": "Valinhos", "uf": "SP"},
        },
        "indicadorIe": 1,
        "financeiro": {"limiteCredito": 5000, "categoria": {"id": 42}},
        "vendedor": {"id": 77},
        "dadosAdicionais": {"dataNascimento": "1990-05-01"},
        "pessoasContato": [{}, {}],
    }
    row = SPECS["contacts"].extract_row(contact)
    assert row["is_supplier"] is True
    assert row["is_client"] is True
    assert row["phone"] == "11 99999-0000"  # telefone vazio -> celular
    assert row["city"] == "Campinas"
    assert row["billing_city"] == "Valinhos"
    assert row["state_registration_status"] == "Contribuinte ICMS"
    assert row["financial_category_id"] == "42"
    assert row["seller_id"] == "77"
    assert row["contact_persons_count"] == 2
    assert row["birth_date"] is not None and str(row["birth_date"]) == "1990-05-01"
    assert row["is_foreign"] is False
    # contato minimo da listagem (sem detalhe) nao explode
    row_min = SPECS["contacts"].extract_row({"id": 2, "nome": "Z"})
    assert row_min["is_supplier"] is False
    assert row_min["city"] is None
    assert row_min["contact_persons_count"] == 0


def test_nfe_total_fallback_to_items():
    nfe = {"id": 5, "numero": 10, "serie": 1, "situacao": 6,
           "itens": [{"valorTotal": 10.5}, {"valorTotal": 4.5}]}
    row = SPECS["nfe"].extract_row(nfe)
    assert row["total"] == 15.0
    assert row["serie"] == "1"
    assert row["situation"] == "6"
    nfe2 = {"id": 6, "valorNota": 99}
    assert SPECS["nfe"].extract_row(nfe2)["total"] == 99.0
    assert SPECS["nfe"].extract_row(nfe2)["serie"] is None


def test_contas_extraction():
    conta = {"id": 9, "historico": "Aluguel", "contato": {"id": 3, "nome": "Imob"},
             "vencimento": "2026-08-01", "valor": 1200.5, "situacao": 1,
             "competencia": "2026-07-01",
             "categoria": {"descricao": "Despesas"},
             "contaContabil": {"descricao": "Receitas"}}
    pagar = SPECS["pagar"].extract_row(conta)
    receber = SPECS["receber"].extract_row(conta)
    assert pagar["supplier_name"] == "Imob"
    assert pagar["category"] == "Despesas"
    assert receber["category"] == "Receitas"
    assert pagar["value"] == 1200.5
    assert str(pagar["due_date"]) == "2026-08-01"


def test_produtos_extraction():
    produto = {"id": 7, "codigo": "ABC", "nome": "Peca", "preco": None,
               "tributacao": {"ncm": "8409.99.90"},
               "dimensoes": {"largura": 10, "altura": 5, "profundidade": 2}}
    row = SPECS["produtos"].extract_row(produto)
    assert row["preco"] == 0.0  # preco None -> 0 (paridade com o antigo)
    assert row["ncm"] == "8409.99.90"
    assert row["largura"] == 10
