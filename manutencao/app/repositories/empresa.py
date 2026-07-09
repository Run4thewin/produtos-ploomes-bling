"""Repository de Empresa — única camada que monta queries e toca a AsyncSession."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.empresa import Empresa


class EmpresaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, empresa_id: UUID) -> Empresa | None:
        return await self.session.get(Empresa, empresa_id)

    async def get_by_cnpj(self, cnpj: str) -> Empresa | None:
        stmt = select(Empresa).where(Empresa.cnpj == cnpj)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def listar(self, page: int, page_size: int) -> tuple[list[Empresa], int]:
        base = select(Empresa).where(Empresa.ativo.is_(True))
        total = await self.session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        stmt = (
            base.order_by(Empresa.razao_social)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(total or 0)

    async def create(self, empresa: Empresa) -> Empresa:
        self.session.add(empresa)
        await self.session.flush()
        return empresa

    async def soft_delete(self, empresa: Empresa) -> None:
        empresa.ativo = False
        await self.session.flush()
