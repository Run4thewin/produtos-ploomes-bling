"""Base declarativa, engine assíncrono e session factory.

Mixins reutilizáveis garantem as colunas comuns exigidas pelo CLAUDE.md:
`id` (UUID), `criado_em`/`atualizado_em` (timestamptz) e `ativo` (soft delete).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.async_url, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


class UUIDPkMixin:
    """Chave primária UUID. No Postgres usa gen_random_uuid() (pgcrypto);
    `default=uuid4` garante o valor mesmo em bancos sem a função (ex: SQLite de teste)."""

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class TimestampMixin:
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
