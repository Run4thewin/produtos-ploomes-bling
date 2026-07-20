"""
pipeline.py — entry point do Cloud Run Job.
Executa em sequência:
  1. blng_fetcher/main.py  (Bling → PostgreSQL)
  2. scripts/sync_to_sheets.py  (PostgreSQL → Google Sheets)
"""
import logging
import subprocess
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pipeline")


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
