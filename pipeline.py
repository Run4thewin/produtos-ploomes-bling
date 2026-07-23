"""
pipeline.py — entry point do Cloud Run Job (bling-pipeline, roda de hora em
hora via Cloud Scheduler). Executa em sequência, cada passo so' comeca se o
anterior terminou com sucesso:
  1. blng_fetcher/main.py       (Bling -> PostgreSQL)
  2. scripts/sync_to_sheets.py  (PostgreSQL -> Google Sheets)
  3. scripts/sync_to_drive_excel.py (PostgreSQL -> .xlsx/.xml no Drive)
     -- SO as 4h (horario de Sao Paulo), nao a cada hora.

O passo 3 e' encadeado aqui (nao tem Cloud Scheduler proprio) de proposito:
scripts/sync_to_drive_excel.py so' LE o banco, entao precisa que o passo 1
(que ESCREVE) ja tenha terminado -- dois Jobs/Schedulers independentes na
mesma hora corririam o risco do export ler o banco no meio de uma
atualizacao (dado "rasgado", parte nova/parte velha). Rodando em sequencia
dentro do MESMO processo, o export so' inicia depois que o fetcher (e o
sheets) realmente concluirem -- se o passo 1 falhar, run() encerra o
processo e o passo 3 nem executa naquela hora.
"""
import logging
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pipeline")

DAILY_EXPORT_HOUR = 4  # horario de America/Sao_Paulo


def run(cmd: list[str]) -> None:
    log.info(">> %s", " ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        log.error("FALHA (exit %s): %s", result.returncode, " ".join(cmd))
        sys.exit(result.returncode)


if __name__ == "__main__":
    # incremental: usa watermark/janela por entidade (bling_sync_state);
    # --pages 999 nao e' custo fixo — o filtro incremental reduz as paginas
    run([sys.executable, "blng_fetcher/main.py",
         "--entity", "all", "--mode", "incremental", "--pages", "999"])
    run([sys.executable, "scripts/sync_to_sheets.py"])

    hora_sp = datetime.now(ZoneInfo("America/Sao_Paulo")).hour
    if hora_sp == DAILY_EXPORT_HOUR:
        log.info("Execucao das %sh (Sao Paulo): rodando export diario Excel/XML.", hora_sp)
        run([sys.executable, "scripts/sync_to_drive_excel.py"])
    else:
        log.info("Execucao das %sh (Sao Paulo): fora da janela do export diario (%sh); pulando.",
                 hora_sp, DAILY_EXPORT_HOUR)
