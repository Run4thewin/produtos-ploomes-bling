"""Repository de Usuario — única camada que monta queries e toca a AsyncSession."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.perfil import Perfil
from app.models.usuario import Usuario


class UsuarioRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, usuario_id: UUID) -> Usuario | None:
        return await self.session.get(Usuario, usuario_id)

    async def get_by_id_com_perfil(self, usuario_id: UUID) -> Usuario | None:
        """Carrega o usuário junto do perfil e suas permissões (para checagem de acesso)."""
        stmt = (
            select(Usuario)
            .where(Usuario.id == usuario_id)
            .options(selectinload(Usuario.perfil).selectinload(Perfil.permissoes))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Usuario | None:
        stmt = select(Usuario).where(Usuario.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def listar_por_empresa(
        self, empresa_id: UUID, page: int, page_size: int
    ) -> tuple[list[Usuario], int]:
        base = select(Usuario).where(
            Usuario.empresa_id == empresa_id, Usuario.ativo.is_(True)
        )
        total = await self.session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        stmt = base.order_by(Usuario.nome).offset((page - 1) * page_size).limit(page_size)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(total or 0)

    async def create(self, usuario: Usuario) -> Usuario:
        self.session.add(usuario)
        await self.session.flush()
        return usuario

    async def soft_delete(self, usuario: Usuario) -> None:
        usuario.ativo = False
        await self.session.flush()
