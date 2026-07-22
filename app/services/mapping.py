import re
from typing import Any

from app.config import Settings


class ProductMappingError(ValueError):
    pass


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def extract_bling_fields(bling_product: dict) -> dict[str, Any]:
    tributacao = bling_product.get("tributacao") or {}
    dimensoes = bling_product.get("dimensoes") or {}

    return {
        "fabricante": _clean(bling_product.get("marca")),
        "partnumber": _clean(bling_product.get("codigo")),
        "breve_descricao": _clean(bling_product.get("descricaoCurta")),
        "preco": float(bling_product.get("preco") or 0),
        "situacao": _clean(bling_product.get("situacao") or "A").upper(),
        "ncm": _clean(tributacao.get("ncm")),
        "peso_liquido": bling_product.get("pesoLiquido"),
        "peso_bruto": bling_product.get("pesoBruto"),
        "largura": dimensoes.get("largura"),
        "altura": dimensoes.get("altura"),
        "profundidade": dimensoes.get("profundidade"),
    }


# O campo Name do Ploomes rejeita (HTTP 400) acima de ~200 chars. Alguns produtos
# no Bling tem descricaoCurta gigante (texto colado por engano) -> truncamos.
PLOOMES_NAME_MAX_LENGTH = 200


def build_product_name(fabricante: str, partnumber: str, breve_descricao: str) -> str:
    prefix = " ".join(part for part in (fabricante, partnumber) if part)
    if prefix and breve_descricao.upper().startswith(prefix.upper()):
        # breve_descricao ja inclui fabricante+partnumber (caso de fallback em
        # extract_ploomes_fields) -- nao duplicar colando o prefixo de novo.
        name = breve_descricao
    else:
        parts = [fabricante, partnumber, breve_descricao]
        name = " ".join(part for part in parts if part)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:PLOOMES_NAME_MAX_LENGTH].strip()


def build_optional_details(fields: dict[str, Any]) -> str:
    details: list[str] = []

    peso = fields.get("peso_liquido") or fields.get("peso_bruto")
    if peso not in (None, "", 0):
        details.append(f"Peso: {peso} kg")

    largura = fields.get("largura")
    altura = fields.get("altura")
    profundidade = fields.get("profundidade")
    if any(v not in (None, "", 0) for v in (largura, altura, profundidade)):
        details.append(
            f"Dimensões: {largura or '-'} x {altura or '-'} x {profundidade or '-'} cm"
        )

    return " | ".join(details)


def _ncm_as_integer(ncm: str) -> int | None:
    digits = re.sub(r"\D", "", ncm)
    if not digits:
        return None
    return int(digits)


def _other_property(field_key: str, value: Any) -> dict | None:
    if value in (None, ""):
        return None
    return {"FieldKey": field_key, "StringValue": str(value)}


def _other_property_int(field_key: str, value: int | None) -> dict | None:
    if value is None:
        return None
    return {"FieldKey": field_key, "IntegerValue": value}


def _other_property_text(field_key: str, value: str) -> dict | None:
    if not value:
        return None
    return {"FieldKey": field_key, "BigStringValue": value}


def build_other_properties(fields: dict[str, Any], settings: Settings) -> list[dict]:
    props: list[dict] = []

    for builder, field_name, value in (
        (_other_property, "ploomes_field_fabricante", fields["fabricante"]),
        (_other_property, "ploomes_field_partnumber", fields["partnumber"]),
        (_other_property_int, "ploomes_field_ncm", _ncm_as_integer(fields["ncm"])),
        (_other_property_text, "ploomes_field_descricao", fields.get("descricao_extra", "")),
    ):
        field_key = getattr(settings, field_name, "")
        if not field_key:
            continue
        item = builder(field_key, value)
        if item:
            props.append(item)

    return props


def validate_required_fields(fields: dict[str, Any], bling_product: dict) -> None:
    missing = []
    if not fields["partnumber"]:
        missing.append("partnumber (codigo)")
    if not fields["breve_descricao"]:
        missing.append("breve descricao (descricaoCurta)")

    if missing:
        bling_id = bling_product.get("id", "?")
        raise ProductMappingError(
            f"Produto Bling {bling_id} sem campos obrigatorios: {', '.join(missing)}"
        )


def map_bling_to_ploomes(bling_product: dict, settings: Settings) -> dict:
    fields = extract_bling_fields(bling_product)
    validate_required_fields(fields, bling_product)

    descricao_extra = build_optional_details(fields)
    if descricao_extra:
        fields["descricao_extra"] = descricao_extra

    payload: dict[str, Any] = {
        "Name": build_product_name(
            fields["fabricante"],
            fields["partnumber"],
            fields["breve_descricao"],
        ),
        "Code": fields["partnumber"],
        "UnitPrice": fields["preco"],
        "Suspended": fields["situacao"] != "A",
    }

    if settings.ploomes_group_id:
        payload["GroupId"] = settings.ploomes_group_id

    other_properties = build_other_properties(fields, settings)
    if other_properties:
        payload["OtherProperties"] = other_properties

    return payload


def expected_ploomes_view(bling_product: dict, settings: Settings) -> dict[str, Any]:
    fields = extract_bling_fields(bling_product)
    validate_required_fields(fields, bling_product)

    return {
        "Name": build_product_name(
            fields["fabricante"],
            fields["partnumber"],
            fields["breve_descricao"],
        ),
        "Code": fields["partnumber"],
        "UnitPrice": fields["preco"],
        "Suspended": fields["situacao"] != "A",
        "Fabricante": fields["fabricante"],
        "Partnumber": fields["partnumber"],
        "NCM": _ncm_as_integer(fields["ncm"]),
    }


def get_other_property(ploomes_product: dict, field_key: str) -> Any:
    for item in ploomes_product.get("OtherProperties") or []:
        if item.get("FieldKey") == field_key:
            for key in ("StringValue", "IntegerValue", "BigStringValue", "DecimalValue"):
                if item.get(key) is not None:
                    return item.get(key)
    return None


def diff_fields(
    bling_product: dict,
    ploomes_product: dict,
    settings: Settings | None = None,
) -> list[str]:
    from app.config import get_settings

    settings = settings or get_settings()

    try:
        expected = expected_ploomes_view(bling_product, settings)
    except ProductMappingError:
        return ["campos_obrigatorios"]

    divergences = []
    for field in ("Name", "Code", "UnitPrice", "Suspended"):
        current = ploomes_product.get(field)
        exp = expected[field]
        if field == "UnitPrice":
            if float(current or 0) != float(exp):
                divergences.append(field)
        elif current != exp:
            divergences.append(field)

    for field_name, setting_name in (
        ("Fabricante", "ploomes_field_fabricante"),
        ("Partnumber", "ploomes_field_partnumber"),
        ("NCM", "ploomes_field_ncm"),
    ):
        field_key = getattr(settings, setting_name, "")
        if not field_key:
            continue
        current = get_other_property(ploomes_product, field_key)
        exp = expected.get(field_name)
        if field_name == "NCM":
            if current != exp and str(current or "") != str(exp or ""):
                divergences.append(field_name)
        elif (current or "") != (exp or ""):
            divergences.append(field_name)

    return divergences


def parse_breve_descricao_from_name(name: str, fabricante: str, partnumber: str) -> str:
    remainder = _clean(name)
    if fabricante and remainder.upper().startswith(fabricante.upper()):
        remainder = remainder[len(fabricante) :].strip()
    if partnumber and remainder.upper().startswith(partnumber.upper()):
        remainder = remainder[len(partnumber) :].strip()
    return remainder


def parse_optional_details_from_text(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not text:
        return result

    peso_match = re.search(r"Peso:\s*([0-9]+(?:[.,][0-9]+)?)\s*kg", text, re.IGNORECASE)
    if peso_match:
        result["peso_liquido"] = float(peso_match.group(1).replace(",", "."))

    dim_match = re.search(
        r"Dimens[oõ]es:\s*([0-9]+(?:[.,][0-9]+)?)\s*x\s*"
        r"([0-9]+(?:[.,][0-9]+)?)\s*x\s*([0-9]+(?:[.,][0-9]+)?)\s*cm",
        text,
        re.IGNORECASE,
    )
    if dim_match:
        result["largura"] = float(dim_match.group(1).replace(",", "."))
        result["altura"] = float(dim_match.group(2).replace(",", "."))
        result["profundidade"] = float(dim_match.group(3).replace(",", "."))

    return result


def extract_ploomes_fields(ploomes_product: dict, settings: Settings) -> dict[str, Any]:
    fabricante = _clean(
        get_other_property(ploomes_product, settings.ploomes_field_fabricante)
    )
    partnumber = _clean(
        get_other_property(ploomes_product, settings.ploomes_field_partnumber)
        or ploomes_product.get("Code")
    )
    descricao_campo = _clean(
        get_other_property(ploomes_product, settings.ploomes_field_descricao)
    )
    name = _clean(ploomes_product.get("Name"))
    breve_descricao = parse_breve_descricao_from_name(name, fabricante, partnumber)
    if not breve_descricao and descricao_campo and "peso:" not in descricao_campo.lower():
        breve_descricao = descricao_campo
    if not breve_descricao:
        # Nome era so "{fabricante} {partnumber}" (nada sobrou apos tirar os prefixos) ou
        # nao segue essa convencao -- usa o nome completo em vez de deixar vazio.
        breve_descricao = name

    optional = parse_optional_details_from_text(descricao_campo)
    ncm_value = get_other_property(ploomes_product, settings.ploomes_field_ncm)

    return {
        "fabricante": fabricante,
        "partnumber": partnumber,
        "breve_descricao": breve_descricao,
        "preco": float(ploomes_product.get("UnitPrice") or 0),
        "situacao": "I" if ploomes_product.get("Suspended") else "A",
        "ncm": _clean(ncm_value),
        **optional,
    }


def validate_ploomes_required_fields(fields: dict[str, Any], ploomes_product: dict) -> None:
    missing = []
    if not fields["fabricante"]:
        missing.append("fabricante")
    if not fields["partnumber"]:
        missing.append("partnumber (Code)")
    if not fields["breve_descricao"]:
        missing.append("breve descricao")

    if missing:
        ploomes_id = ploomes_product.get("Id", "?")
        raise ProductMappingError(
            f"Produto Ploomes {ploomes_id} sem campos obrigatorios: {', '.join(missing)}"
        )


def map_ploomes_to_bling(ploomes_product: dict, settings: Settings) -> dict:
    fields = extract_ploomes_fields(ploomes_product, settings)
    validate_ploomes_required_fields(fields, ploomes_product)

    nome = build_product_name(
        fields["fabricante"],
        fields["partnumber"],
        fields["breve_descricao"],
    )
    payload: dict[str, Any] = {
        "nome": nome,
        "codigo": fields["partnumber"],
        "preco": fields["preco"],
        "tipo": "P",
        "formato": "S",
        "situacao": fields["situacao"],
        # descricaoCurta espelha o nome (mesmo texto) para nao divergir do que
        # aparece no item do pedido/NF-e, que puxa a descricao do produto.
        "descricaoCurta": nome,
        "marca": fields["fabricante"],
        "unidade": "UN",
    }

    if fields.get("peso_liquido") not in (None, "", 0):
        payload["pesoLiquido"] = float(fields["peso_liquido"])
        payload["pesoBruto"] = float(fields["peso_liquido"])

    dimensoes = {}
    if fields.get("largura") not in (None, "", 0):
        dimensoes["largura"] = float(fields["largura"])
    if fields.get("altura") not in (None, "", 0):
        dimensoes["altura"] = float(fields["altura"])
    if fields.get("profundidade") not in (None, "", 0):
        dimensoes["profundidade"] = float(fields["profundidade"])
    if dimensoes:
        payload["dimensoes"] = dimensoes

    if fields["ncm"]:
        payload["tributacao"] = {"ncm": fields["ncm"]}

    return payload
