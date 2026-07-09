from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.empresa import Empresa
from app.repositories.empresa import EmpresaRepository
from app.schemas.empresa import EmpresaCreate, EmpresaUpdate
from app.services.errors import Conflito, NaoEncontrado


class EmpresaService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = EmpresaRepository(session)

    async def criar(self, dados: EmpresaCreate) -> Empresa:
        if await self.repo.get_by_cnpj(dados.cnpj):
            raise Conflito(f"Já existe empresa com CNPJ {dados.cnpj}")
        empresa = Empresa(**dados.model_dump())
        await self.repo.create(empresa)
        await self.session.commit()
        await self.session.refresh(empresa)
        return empresa

    async def obter(self, empresa_id: UUID) -> Empresa:
        empresa = await self.repo.get_by_id(empresa_id)
        if not empresa or not empresa.ativo:
            raise NaoEncontrado("Empresa não encontrada")
        return empresa

    async def listar(self, page: int, page_size: int) -> tuple[list[Empresa], int]:
        return await self.repo.listar(page, page_size)

    async def atualizar(self, empresa_id: UUID, dados: EmpresaUpdate) -> Empresa:
        empresa = await self.obter(empresa_id)
        for campo, valor in dados.model_dump(exclude_unset=True).items():
            setattr(empresa, campo, valor)
        await self.session.commit()
        await self.session.refresh(empresa)
        return empresa

    async def inativar(self, empresa_id: UUID) -> None:
        empresa = await self.obter(empresa_id)
        await self.repo.soft_delete(empresa)
        await self.session.commit()
