from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PermissaoBase(BaseModel):
    modulo: str
    pode_criar: bool = False
    pode_ler: bool = True
    pode_editar: bool = False
    pode_excluir: bool = False


class PermissaoCreate(PermissaoBase):
    pass


class PermissaoRead(PermissaoBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    perfil_id: UUID


class PerfilBase(BaseModel):
    nome: str
    descricao: str | None = None
    nivel_acesso: int


class PerfilCreate(PerfilBase):
    permissoes: list[PermissaoCreate] = []


class PerfilUpdate(BaseModel):
    nome: str | None = None
    descricao: str | None = None
    nivel_acesso: int | None = None


class PerfilRead(PerfilBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    criado_em: datetime
    atualizado_em: datetime
    permissoes: list[PermissaoRead] = []
