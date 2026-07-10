import logging
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

logger = logging.getLogger(__name__)

_LIMITERS: dict[str, "ApiRateLimiter"] = {}
_LIMITERS_LOCK = threading.Lock()


class DailyQuotaExceeded(RuntimeError):
    """Sinaliza que o orcamento diario de requisicoes da API foi atingido.

    O chamador deve capturar, salvar o progresso e reexecutar no dia seguinte;
    o contador reseta automaticamente na virada de data (UTC).
    """

    def __init__(self, name: str, budget: int, used: int):
        self.name = name
        self.budget = budget
        self.used = used
        super().__init__(
            f"Orcamento diario de requisicoes {name} atingido: {used}/{budget}. "
            "Progresso preservado; reexecute apos a virada do dia para continuar."
        )


class DailyQuota:
    """Contador diario persistido (arquivo/GCS) para nao estourar a cota da API.

    Carrega o contador do dia corrente, incrementa em memoria e faz flush
    periodico no store. Na virada de data o contador reinicia em zero.
    """

    def __init__(self, name: str, budget: int, store, flush_every: int = 50):
        self.name = name
        self.budget = max(int(budget), 0)
        self._store = store
        self._flush_every = max(int(flush_every), 1)
        self._date: str | None = None
        self._count = 0
        self._pending_flush = 0
        self._loaded = False

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _ensure_loaded(self, today: str) -> None:
        if not self._loaded:
            data = self._store.load() or {}
            if data.get("date") == today:
                self._count = int(data.get("count", 0))
            else:
                self._count = 0
            self._date = today
            self._loaded = True

    def _flush(self) -> None:
        try:
            self._store.save(self._date, self._count)
            self._pending_flush = 0
        except Exception as exc:  # noqa: BLE001 - persistir cota nao deve derrubar a carga
            logger.warning("%s: falha ao persistir contador diario: %s", self.name, exc)

    def check_and_increment(self) -> None:
        today = self._today()
        self._ensure_loaded(today)

        if today != self._date:
            self._date = today
            self._count = 0
            self._pending_flush = 0
            self._flush()

        if self.budget and self._count >= self.budget:
            self._flush()
            raise DailyQuotaExceeded(self.name, self.budget, self._count)

        self._count += 1
        self._pending_flush += 1
        if self._pending_flush >= self._flush_every:
            self._flush()

    @property
    def remaining(self) -> int:
        if not self.budget:
            return -1
        return max(self.budget - self._count, 0)


class ApiRateLimiter:
    def __init__(self, name: str, min_interval_seconds: float = 0.0):
        self.name = name
        self.min_interval_seconds = max(float(min_interval_seconds), 0.0)
        self._lock = threading.Lock()
        self._next_available_at = 0.0
        self._daily_quota: DailyQuota | None = None

    def configure(self, min_interval_seconds: float) -> None:
        with self._lock:
            self.min_interval_seconds = max(float(min_interval_seconds), 0.0)

    def set_daily_quota(self, quota: DailyQuota | None) -> None:
        with self._lock:
            self._daily_quota = quota

    def wait(self) -> None:
        with self._lock:
            if self._daily_quota is not None:
                # Levanta DailyQuotaExceeded antes de gastar a requisicao.
                self._daily_quota.check_and_increment()

            if self.min_interval_seconds <= 0:
                return

            now = time.monotonic()
            delay = self._next_available_at - now
            if delay > 0:
                logger.debug("%s rate limit local; aguardando %.2fs", self.name, delay)
                time.sleep(delay)
            self._next_available_at = time.monotonic() + self.min_interval_seconds

    def wait_after_429(self, delay: float) -> None:
        delay = max(float(delay), 0.0)
        with self._lock:
            self._next_available_at = max(
                self._next_available_at,
                time.monotonic() + delay,
            )
            if delay > 0:
                time.sleep(delay)
            self._next_available_at = time.monotonic()


def retry_after_delay(
    response: httpx.Response,
    fallback_delay: float,
    *,
    max_delay: float,
) -> float:
    retry_after = response.headers.get("Retry-After")
    if not retry_after:
        return fallback_delay

    try:
        delay = float(retry_after)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(retry_after)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError):
            delay = fallback_delay

    return min(max(delay, 0.0), max_delay)


def get_api_rate_limiter(name: str, min_interval_seconds: float) -> ApiRateLimiter:
    with _LIMITERS_LOCK:
        limiter = _LIMITERS.get(name)
        if limiter is None:
            limiter = ApiRateLimiter(name, min_interval_seconds)
            _LIMITERS[name] = limiter
        else:
            limiter.configure(min_interval_seconds)
        return limiter
