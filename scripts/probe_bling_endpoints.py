"""
scripts/probe_bling_endpoints.py
Sondagem da API Bling v3: descobre quais endpoints existem/temos escopo,
salva JSONs de exemplo (listagem + detalhe) e testa params incrementais.

Uso:
    python scripts/probe_bling_endpoints.py                      # todos
    python scripts/probe_bling_endpoints.py --only vendedores,depositos
    python scripts/probe_bling_endpoints.py --skip-incremental-test

Saida: relatorios/bling_probe/<slug>_list.json, <slug>_detail.json, _summary.json

Custo estimado: ~80-100 requests (1x apenas; nao agendar).
"""
import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.clients.bling import BlingClient  # noqa: E402
from app.clients.rate_limit import DailyQuotaExceeded  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OUT_DIR = ROOT / "relatorios" / "bling_probe"

# Janela no passado remoto: se o filtro for honrado, a listagem volta vazia
# (nao ha registros de 1970). Datas passadas evitam rejeicao de "data futura
# invalida" que uma data 2099 pode causar.
PAST_START = "1970-01-01"
PAST_END = "1970-01-02"
PAST_START_DT = "1970-01-01 00:00:00"
PAST_END_DT = "1970-01-02 00:00:00"


@dataclass
class Probe:
    slug: str                      # nome do arquivo/summary
    path: str                      # endpoint de listagem ("{sample:<slug>}" = id vindo de outro probe)
    detail: str | None = None      # template de detalhe, "{id}" substituido
    incremental: list[str] = field(default_factory=list)  # params candidatos a filtro incremental
    params: dict = field(default_factory=dict)            # params fixos extras na listagem
    singleton: bool = False        # resposta e' um dict unico, nao lista


PROBES: list[Probe] = [
    # --- entidades ja carregadas (probe so' p/ confirmar filtro incremental) ---
    Probe("pedidos-vendas", "pedidos/vendas",
          incremental=["dataAlteracaoInicial", "dataInicial"]),
    Probe("contatos", "contatos",
          incremental=["dataAlteracaoInicial", "dataInclusaoInicial"]),
    Probe("produtos", "produtos", detail="produtos/{id}",
          incremental=["dataAlteracaoInicial", "dataInclusaoInicial"]),
    Probe("nfe", "nfe",
          incremental=["dataAlteracaoInicial", "dataEmissaoInicial"]),
    Probe("contas-pagar", "contas/pagar",
          incremental=["dataAlteracaoInicial", "dataEmissaoInicial", "dataVencimentoInicial"]),
    Probe("contas-receber", "contas/receber",
          incremental=["dataAlteracaoInicial", "dataEmissaoInicial", "dataVencimentoInicial"]),
    Probe("naturezas-operacoes", "naturezas-operacoes"),

    # --- transacionais novas ---
    Probe("pedidos-compras", "pedidos/compras", detail="pedidos/compras/{id}",
          incremental=["dataAlteracaoInicial", "dataInicial"]),
    Probe("propostas-comerciais", "propostas-comerciais", detail="propostas-comerciais/{id}",
          incremental=["dataAlteracaoInicial", "dataInicial"]),
    Probe("nfce", "nfce", detail="nfce/{id}",
          incremental=["dataAlteracaoInicial", "dataEmissaoInicial"]),
    Probe("nfse", "nfse", detail="nfse/{id}",
          incremental=["dataAlteracaoInicial", "dataEmissaoInicial"]),
    Probe("contratos", "contratos", detail="contratos/{id}",
          incremental=["dataAlteracaoInicial", "dataInicial"]),
    Probe("borderos", "borderos", detail="borderos/{id}"),

    # --- config / cadastros ---
    Probe("depositos", "depositos"),
    Probe("vendedores", "vendedores", detail="vendedores/{id}"),
    Probe("categorias-produtos", "categorias/produtos", detail="categorias/produtos/{id}"),
    Probe("categorias-receitas-despesas", "categorias/receitas-despesas"),
    Probe("categorias-lojas", "categorias/lojas"),
    Probe("grupos-produtos", "grupos-produtos"),
    Probe("contatos-tipos", "contatos/tipos"),
    Probe("formas-pagamentos", "formas-pagamentos", detail="formas-pagamentos/{id}"),
    Probe("contas-contabeis", "contas-contabeis"),
    Probe("canais-venda", "canais-venda", detail="canais-venda/{id}"),
    Probe("logisticas", "logisticas", detail="logisticas/{id}"),
    Probe("logisticas-servicos", "logisticas/servicos"),
    Probe("empresas-me", "empresas/me/dados-basicos", singleton=True),
    Probe("campos-customizados-modulos", "campos-customizados/modulos"),
    Probe("situacoes-modulos", "situacoes/modulos"),

    # --- dependentes de amostra de outro probe ---
    Probe("situacoes-por-modulo", "situacoes/modulos/{sample:situacoes-modulos}/situacoes"),
    Probe("campos-customizados", "campos-customizados/modulos/{sample:campos-customizados-modulos}"),
    Probe("estoques-saldos", "estoques/saldos",
          params={"idsProdutos[]": "{sample:produtos}"}),
    # amostras vindas do banco (bling_produtos.formato = 'E'/'V'), se disponivel
    Probe("produtos-estruturas", "produtos/estruturas/{sample:produto-estrutura}"),
    Probe("produtos-variacoes", "produtos/variacoes/{sample:produto-variacao}"),
    Probe("produtos-fornecedores", "produtos/fornecedores",
          params={"idProduto": "{sample:produtos}"}),
    Probe("produtos-lojas", "produtos/lojas",
          params={"idProduto": "{sample:produtos}"}),
]


def _safe_json(response) -> dict | list | None:
    try:
        return response.json()
    except Exception:
        return None


def _resolve_sample(value: str, sample_ids: dict[str, int | str]) -> str | None:
    """Substitui "{sample:<slug>}" pelo primeiro id capturado do probe <slug>."""
    if "{sample:" not in str(value):
        return str(value)
    for slug, sample_id in sample_ids.items():
        token = "{sample:" + slug + "}"
        if token in value:
            return value.replace(token, str(sample_id))
    return None  # amostra necessaria ainda nao disponivel


def probe_list(bling: BlingClient, probe: Probe, sample_ids: dict) -> dict:
    result: dict = {"slug": probe.slug, "path": probe.path}

    path = _resolve_sample(probe.path, sample_ids)
    params = {}
    for k, v in probe.params.items():
        resolved = _resolve_sample(v, sample_ids)
        if resolved is None:
            result["status"] = "skipped"
            result["reason"] = f"sem amostra para param {k}"
            return result
        params[k] = resolved
    if path is None:
        result["status"] = "skipped"
        result["reason"] = "sem amostra para o path"
        return result

    if not probe.singleton:
        params.setdefault("pagina", 1)
        params.setdefault("limite", 3)

    response = bling._request("GET", path, params=params)
    body = _safe_json(response)
    result["http_status"] = response.status_code
    result["resolved_path"] = path

    if response.status_code != 200:
        result["status"] = {403: "sem_escopo", 404: "nao_existe"}.get(
            response.status_code, "erro")
        result["error_body"] = body
        return result

    data = (body or {}).get("data")
    if probe.singleton and isinstance(data, dict):
        data = [data]
    data = data or []
    result["status"] = "ok"
    result["records_seen"] = len(data)

    (OUT_DIR / f"{probe.slug}_list.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    first_id = None
    if data and isinstance(data[0], dict):
        first_id = data[0].get("id")
        result["list_fields"] = sorted(data[0].keys())
    if first_id is not None:
        sample_ids[probe.slug] = first_id

    # detalhe
    if probe.detail and first_id is not None:
        detail_path = probe.detail.format(id=first_id)
        response = bling._request("GET", detail_path)
        detail = (_safe_json(response) or {}).get("data") if response.status_code == 200 else None
        result["detail_http_status"] = response.status_code
        if detail:
            (OUT_DIR / f"{probe.slug}_detail.json").write_text(
                json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
            result["detail_fields"] = sorted(detail.keys())
            result["detail_only_fields"] = sorted(
                set(detail.keys()) - set(result.get("list_fields", [])))
    return result


def probe_incremental(bling: BlingClient, probe: Probe, sample_ids: dict,
                      had_records: bool) -> dict[str, str]:
    """
    Testa cada param candidato com uma janela 1970-01-01..1970-01-02, enviando
    o PAR Inicial+Final (varios filtros do Bling so ativam em par):
      - 400            -> formato invalido (tenta datetime) ou param rejeitado
      - 200 + vazio    -> filtro HONRADO (nao ha registros em 1970)
      - 200 + registros-> param IGNORADO pela API (nao confiavel)
    So conclusivo quando a listagem sem filtro tinha registros.
    Tambem testa o param Inicial sozinho (sem Final), para saber se o par e'
    obrigatorio — util p/ watermark aberto ("tudo desde X").
    """
    verdicts: dict[str, str] = {}
    path = _resolve_sample(probe.path, sample_ids)

    def attempt(params: dict) -> str:
        response = bling._request(
            "GET", path, params={"pagina": 1, "limite": 3, **params})
        if response.status_code == 400:
            return "rejeitado_400"
        if response.status_code != 200:
            return f"erro_{response.status_code}"
        data = (_safe_json(response) or {}).get("data") or []
        if not data:
            return "honrado" if had_records else "vazio_inconclusivo"
        return "ignorado"

    for param in probe.incremental:
        param_final = param.replace("Inicial", "Final")
        has_pair = param_final != param
        for fmt_start, fmt_end in ((PAST_START, PAST_END), (PAST_START_DT, PAST_END_DT)):
            pair_params = {param: fmt_start}
            if has_pair:
                pair_params[param_final] = fmt_end
            verdict = attempt(pair_params)
            if verdict != "rejeitado_400":
                break
        verdicts[param] = verdict

        # o filtro funciona sem o Final? (watermark aberto)
        if has_pair and verdict == "honrado":
            solo = attempt({param: PAST_START})
            verdicts[f"{param}__solo"] = solo
    return verdicts


def _seed_samples_from_db(sample_ids: dict) -> None:
    """Busca no banco ids de produtos estrutura/variacao p/ probes dependentes."""
    import os
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.environ["DB_HOST"], port=int(os.environ.get("DB_PORT", 5432)),
            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
        )
        with conn.cursor() as cur:
            for formato, slug in (("E", "produto-estrutura"), ("V", "produto-variacao")):
                cur.execute(
                    "SELECT id FROM bling_produtos WHERE formato = %s LIMIT 1", (formato,))
                row = cur.fetchone()
                if row:
                    sample_ids[slug] = row[0]
        conn.close()
    except Exception as exc:  # noqa: BLE001 - amostras do banco sao opcionais
        logger.warning("Sem amostras do banco (%s); probes dependentes serao pulados.", exc)


def _merge_summary(new_results: list[dict]) -> list[dict]:
    """Preserva resultados anteriores ao rodar com --only."""
    path = OUT_DIR / "_summary.json"
    previous: list[dict] = []
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            previous = []
    merged = {r["slug"]: r for r in previous if isinstance(r, dict) and r.get("slug")}
    for r in new_results:
        if r.get("slug"):
            merged[r["slug"]] = r
    order = [p.slug for p in PROBES]
    return sorted(merged.values(), key=lambda r: order.index(r["slug"])
                  if r["slug"] in order else 999)


def main():
    parser = argparse.ArgumentParser(description="Sondagem de endpoints Bling v3")
    parser.add_argument("--only", help="slugs separados por virgula")
    parser.add_argument("--skip-incremental-test", action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    only = set(args.only.split(",")) if args.only else None

    bling = BlingClient()
    sample_ids: dict[str, int | str] = {}
    _seed_samples_from_db(sample_ids)
    summary: list[dict] = []

    for probe in PROBES:
        if only and probe.slug not in only:
            continue
        logger.info("== Probe: %s (%s)", probe.slug, probe.path)
        try:
            result = probe_list(bling, probe, sample_ids)
            if (not args.skip_incremental_test and probe.incremental
                    and result.get("status") == "ok"):
                result["incremental"] = probe_incremental(
                    bling, probe, sample_ids,
                    had_records=result.get("records_seen", 0) > 0)
        except DailyQuotaExceeded as exc:
            logger.warning("Quota diaria atingida (%s); parando a sondagem.", exc)
            summary.append({"slug": probe.slug, "status": "quota"})
            break
        except Exception as exc:  # noqa: BLE001 - sondagem nao deve abortar tudo
            logger.warning("Probe %s falhou: %s", probe.slug, exc)
            result = {"slug": probe.slug, "status": "excecao", "error": str(exc)}
        summary.append(result)
        logger.info("   -> %s", result.get("status"))

    summary = _merge_summary(summary)
    (OUT_DIR / "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Sondagem concluida. Resumo em %s", OUT_DIR / "_summary.json")

    ok = [r["slug"] for r in summary if r.get("status") == "ok"]
    bad = [(r["slug"], r.get("status")) for r in summary if r.get("status") != "ok"]
    logger.info("OK (%s): %s", len(ok), ", ".join(ok))
    for slug, status in bad:
        logger.info("PROBLEMA: %s -> %s", slug, status)


if __name__ == "__main__":
    main()
