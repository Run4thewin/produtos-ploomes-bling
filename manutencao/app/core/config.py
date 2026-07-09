from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Banco de dados ---------------------------------------------------
    # Opção A (dev/local): informe a URL completa em DATABASE_URL / DATABASE_URL_SYNC.
    # Opção B (Cloud Run + Cloud SQL): informe as partes abaixo; a senha vem do
    #   Secret Manager (DB_PASSWORD) e, com INSTANCE_CONNECTION_NAME setado, a
    #   conexão usa o socket unix /cloudsql/<connection_name>.
    database_url: str = ""
    database_url_sync: str = ""

    db_user: str = "postgres"
    db_password: str = "postgres"
    db_name: str = "manutencao"
    db_host: str = "localhost"
    db_port: int = 5432
    # Cloud SQL: PROJECT:REGION:INSTANCE (ativa conexão via socket unix)
    instance_connection_name: str = ""

    # --- Segurança / JWT --------------------------------------------------
    jwt_secret: str = "dev-insecure-secret-change-me"
    jwt_alg: str = "HS256"
    access_token_min: int = 30
    refresh_token_days: int = 7
    reset_token_min: int = 30

    debug: bool = True

    def _build_url(self, driver: str) -> str:
        user = quote_plus(self.db_user)
        pwd = quote_plus(self.db_password)
        if self.instance_connection_name:
            # Cloud SQL via socket unix (Cloud Run monta em /cloudsql/<name>).
            return (
                f"postgresql+{driver}://{user}:{pwd}@/{self.db_name}"
                f"?host=/cloudsql/{self.instance_connection_name}"
            )
        return f"postgresql+{driver}://{user}:{pwd}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def async_url(self) -> str:
        """URL usada pela aplicação (driver asyncpg)."""
        return self.database_url or self._build_url("asyncpg")

    @property
    def sync_url(self) -> str:
        """URL síncrona usada SOMENTE por migrações Alembic (driver psycopg)."""
        if self.database_url_sync:
            return self.database_url_sync
        if self.database_url:
            return self.database_url.replace("+asyncpg", "+psycopg")
        return self._build_url("psycopg")


@lru_cache
def get_settings() -> Settings:
    return Settings()
