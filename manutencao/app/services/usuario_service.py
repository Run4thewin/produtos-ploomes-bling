from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_senha
from app.models.usuario import Usuario
from app.repositories.perfil import PerfilRepository
from app.repositories.usuario import UsuarioRepository
from app.schemas.usuario import UsuarioCreate, UsuarioUpdate
from app.services.errors import Conflito, NaoEncontrado


class UsuarioService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = UsuarioRepository(session)
        self.perfil_repo = PerfilRepository(session)

    async def criar(self, empresa_id: UUID, dados: UsuarioCreate) -> Usuario:
        if await self.repo.get_by_email(dados.email):
            raise Conflito(f"Já existe usuário com e-mail {dados.email}")
        if not await self.perfil_repo.get_by_id(dados.perfil_id):
            raise NaoEncontrado("Perfil informado não existe")
        usuario = Usuario(
            empresa_id=empresa_id,
            perfil_id=dados.perfil_id,
            nome=dados.nome,
            email=dados.email,
            senha_hash=hash_senha(dados.senha),
            telefone=dados.telefone,
            cargo=dados.cargo,
            foto_url=dados.foto_url,
        )
        await self.repo.create(usuario)
        await self.session.commit()
        await self.session.refresh(usuario)
        return usuario

    async def obter(self, empresa_id: UUID, usuario_id: UUID) -> Usuario:
        usuario = await self.repo.get_by_id(usuario_id)
        # Isolamento multi-tenant: só enxerga usuários da própria empresa.
        if not usuario or not usuario.ativo or usuario.empresa_id != empresa_id:
            raise NaoEncontrado("Usuário não encontrado")
        return usuario

    async def listar(
        self, empresa_id: UUID, page: int, page_size: int
    ) -> tuple[list[Usuario], int]:
        return await self.repo.listar_por_empresa(empresa_id, page, page_size)

    async def atualizar(
        self, empresa_id: UUID, usuario_id: UUID, dados: UsuarioUpdate
    ) -> Usuario:
        usuario = await self.obter(empresa_id, usuario_id)
        valores = dados.model_dump(exclude_unset=True)
        nova_senha = valores.pop("senha", None)
        if "email" in valores and valores["email"] != usuario.email:
            existente = await self.repo.get_by_email(valores["email"])
            if existente and existente.id != usuario.id:
                raise Conflito(f"Já existe usuário com e-mail {valores['email']}")
        if "perfil_id" in valores and not await self.perfil_repo.get_by_id(valores["perfil_id"]):
            raise NaoEncontrado("Perfil informado não existe")
        for campo, valor in valores.items():
            setattr(usuario, campo, valor)
        if nova_senha:
            usuario.senha_hash = hash_senha(nova_senha)
        await self.session.commit()
        await self.session.refresh(usuario)
        return usuario

    async def inativar(self, empresa_id: UUID, usuario_id: UUID) -> None:
        usuario = await self.obter(empresa_id, usuario_id)
        await self.repo.soft_delete(usuario)
        await self.session.commit()
