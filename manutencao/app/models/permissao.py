from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.perfil import Perfil


class Permissao(UUIDPkMixin, Base):
    __tablename__ = "permissao"
    __table_args__ = (UniqueConstraint("perfil_id", "modulo", name="uq_permissao_perfil_modulo"),)

    perfil_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("perfil.id"), nullable=False
    )
    modulo: Mapped[str] = mapped_column(String(60), nullable=False)
    pode_criar: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    pode_ler: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    pode_editar: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    pode_excluir: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)

    perfil: Mapped["Perfil"] = relationship(back_populates="permissoes")
