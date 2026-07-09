from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.perfil import Perfil
from app.models.permissao import Permissao
from app.repositories.perfil import PerfilRepository
from app.schemas.perfil import PerfilCreate, PerfilUpdate
from app.services.errors import Conflito, NaoEncontrado


class PerfilService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PerfilRepository(session)

    async def criar(self, dados: PerfilCreate) -> Perfil:
        if await self.repo.get_by_nome(dados.nome):
            raise Conflito(f"Já existe perfil com nome '{dados.nome}'")
        perfil = Perfil(
            nome=dados.nome,
            descricao=dados.descricao,
            nivel_acesso=dados.nivel_acesso,
            permissoes=[Permissao(**p.model_dump()) for p in dados.permissoes],
        )
        await self.repo.create(perfil)
        await self.session.commit()
        return await self.repo.get_by_id(perfil.id)

    async def obter(self, perfil_id: UUID) -> Perfil:
        perfil = await self.repo.get_by_id(perfil_id)
        if not perfil:
            raise NaoEncontrado("Perfil não encontrado")
        return perfil

    async def listar(self, page: int, page_size: int) -> tuple[list[Perfil], int]:
        return await self.repo.listar(page, page_size)

    async def atualizar(self, perfil_id: UUID, dados: PerfilUpdate) -> Perfil:
        perfil = await self.obter(perfil_id)
        for campo, valor in dados.model_dump(exclude_unset=True).items():
            setattr(perfil, campo, valor)
        await self.session.commit()
        return await self.repo.get_by_id(perfil.id)
