"""Repository de Perfil (+ Permissao) — única camada que monta queries e toca a AsyncSession."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.perfil import Perfil
from app.models.permissao import Permissao


class PerfilRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, perfil_id: UUID) -> Perfil | None:
        stmt = (
            select(Perfil)
            .where(Perfil.id == perfil_id)
            .options(selectinload(Perfil.permissoes))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_nome(self, nome: str) -> Perfil | None:
        stmt = (
            select(Perfil)
            .where(Perfil.nome == nome)
            .options(selectinload(Perfil.permissoes))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def listar(self, page: int, page_size: int) -> tuple[list[Perfil], int]:
        base = select(Perfil)
        total = await self.session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        stmt = (
            select(Perfil)
            .options(selectinload(Perfil.permissoes))
            .order_by(Perfil.nivel_acesso)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(total or 0)

    async def get_permissao(self, perfil_id: UUID, modulo: str) -> Permissao | None:
        stmt = select(Permissao).where(
            Permissao.perfil_id == perfil_id, Permissao.modulo == modulo
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, perfil: Perfil) -> Perfil:
        self.session.add(perfil)
        await self.session.flush()
        return perfil
