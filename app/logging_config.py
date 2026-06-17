import logging
import sys
from pathlib import Path

from app.config import Settings


def setup_logging(settings: Settings | None = None) -> None:
    from app.config import get_settings

    settings = settings or get_settings()
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger()
    if root.handlers:
        return

    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        stream=sys.stdout,
        force=True,
    )

    if settings.sync_log_file:
        log_path = Path(settings.sync_log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
        logging.getLogger().addHandler(file_handler)
        logging.getLogger(__name__).info("Log de sync gravado em %s", log_path.resolve())
