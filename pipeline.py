"""
pipeline.py — entry point do Cloud Run Job (bling-pipeline, roda 1x/dia via
Cloud Scheduler). Executa em sequência, cada passo so' comeca se o anterior
terminou com sucesso:
  1. blng_fetcher/main.py (--since/--until = dia anterior)  (Bling -> PostgreSQL)
  2. blng_fetcher/main.py --entity estoques_saldos           (saldo atual, sem data)
  3. scripts/sync_to_sheets.py                                (PostgreSQL -> Sheets)
  4. scripts/sync_to_drive_excel.py                           (PostgreSQL -> .xlsx/.xml no Drive)

Por que --since/--until em vez de --mode incremental: a carga foi limitada de
propósito a "somente o dia anterior" (ao invés de watermark contínuo ou janela
de 45-90 dias a cada execução) para conter o consumo da cota diária da API do
Bling. --since/--until não mexe no watermark (bling_sync_state) -- e' uma
janela fixa, então não faz sentido rodar de hora em hora (a mesma consulta se
repetiria o dia inteiro); por isso o Cloud Scheduler passou a disparar 1x/dia.

estoques_saldos fica de fora do --since/--until (o fetcher ignora essa
entidade nesse modo -- ela não busca por data, busca por lote de ids de
produto) e' carregada à parte, no seu próprio modo incremental normal.

Os 3 passos seguintes ficam encadeados aqui (não têm Cloud Scheduler próprio)
de propósito: cada um só lê o que o anterior escreveu -- rodando em sequência
dentro do MESMO processo, nunca leem o banco no meio de uma atualização.
"""
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pipeline")


def run(cmd: list[str]) -> None:
    log.info(">> %s", " ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        log.error("FALHA (exit %s): %s", result.returncode, " ".join(cmd))
        sys.exit(result.returncode)


if __name__ == "__main__":
    ontem = (datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=1)).date().isoformat()
    log.info("Carregando o dia anterior: %s", ontem)

    run([sys.executable, "blng_fetcher/main.py",
         "--entity", "all", "--since", ontem, "--until", ontem, "--pages", "999"])
    run([sys.executable, "blng_fetcher/main.py",
         "--entity", "estoques_saldos", "--mode", "incremental", "--pages", "999"])
    run([sys.executable, "scripts/sync_to_sheets.py"])
    run([sys.executable, "scripts/sync_to_drive_excel.py"])
