"""Testes unitários da montagem de URL do banco (local vs Cloud SQL)."""
from __future__ import annotations

from app.core.config import Settings


def test_url_local_por_partes():
    s = Settings(db_user="u", db_password="p", db_name="db", db_host="h", db_port=5433)
    assert s.async_url == "postgresql+asyncpg://u:p@h:5433/db"
    assert s.sync_url == "postgresql+psycopg://u:p@h:5433/db"


def test_url_cloud_sql_socket():
    s = Settings(
        db_user="u", db_password="p", db_name="db",
        instance_connection_name="proj:reg:inst",
    )
    assert s.async_url == "postgresql+asyncpg://u:p@/db?host=/cloudsql/proj:reg:inst"
    assert s.sync_url == "postgresql+psycopg://u:p@/db?host=/cloudsql/proj:reg:inst"


def test_senha_url_encoded():
    s = Settings(db_user="u", db_password="pa/ss@:word", db_name="db")
    assert "pa%2Fss%40%3Aword" in s.async_url


def test_database_url_explicito_tem_prioridade():
    s = Settings(database_url="postgresql+asyncpg://x:y@host/dbx")
    assert s.async_url == "postgresql+asyncpg://x:y@host/dbx"
    # sync derivado troca o driver.
    assert s.sync_url == "postgresql+psycopg://x:y@host/dbx"


def test_database_url_sync_explicito():
    s = Settings(
        database_url="postgresql+asyncpg://x:y@host/dbx",
        database_url_sync="postgresql+psycopg://a:b@host/dby",
    )
    assert s.sync_url == "postgresql+psycopg://a:b@host/dby"
