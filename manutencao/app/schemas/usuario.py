from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UsuarioBase(BaseModel):
    nome: str
    email: EmailStr
    perfil_id: UUID
    telefone: str | None = None
    cargo: str | None = None
    foto_url: str | None = None


class UsuarioCreate(UsuarioBase):
    senha: str = Field(min_length=6)


class UsuarioUpdate(BaseModel):
    nome: str | None = None
    email: EmailStr | None = None
    perfil_id: UUID | None = None
    telefone: str | None = None
    cargo: str | None = None
    foto_url: str | None = None
    senha: str | None = Field(default=None, min_length=6)


class UsuarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    empresa_id: UUID
    perfil_id: UUID
    nome: str
    email: EmailStr
    telefone: str | None = None
    cargo: str | None = None
    foto_url: str | None = None
    ativo: bool
    ultimo_login: datetime | None = None
    criado_em: datetime
    atualizado_em: datetime
