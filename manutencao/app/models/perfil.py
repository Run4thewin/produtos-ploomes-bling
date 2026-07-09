from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.permissao import Permissao
    from app.models.usuario import Usuario


class Perfil(UUIDPkMixin, TimestampMixin, Base):
    """Perfil global do sistema (sem empresa_id). nivel_acesso: 1=admin, 2=gestor, 3=técnico, 4=leitura."""

    __tablename__ = "perfil"

    nome: Mapped[str] = mapped_column(String(60), nullable=False)
    descricao: Mapped[str | None] = mapped_column(String(200))
    nivel_acesso: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    permissoes: Mapped[list["Permissao"]] = relationship(
        back_populates="perfil", cascade="all, delete-orphan"
    )
    usuarios: Mapped[list["Usuario"]] = relationship(back_populates="perfil")
