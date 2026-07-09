from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.empresa import Empresa
    from app.models.perfil import Perfil


class Usuario(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "usuario"
    __table_args__ = (Index("ix_usuario_empresa_id", "empresa_id"),)

    empresa_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("empresa.id"), nullable=False)
    perfil_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("perfil.id"), nullable=False)
    nome: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    telefone: Mapped[str | None] = mapped_column(String(20))
    cargo: Mapped[str | None] = mapped_column(String(100))
    foto_url: Mapped[str | None] = mapped_column(String(500))
    ultimo_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    empresa: Mapped["Empresa"] = relationship(back_populates="usuarios")
    perfil: Mapped["Perfil"] = relationship(back_populates="usuarios")
