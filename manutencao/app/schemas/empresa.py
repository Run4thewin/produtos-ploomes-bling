from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class EmpresaBase(BaseModel):
    razao_social: str
    nome_fantasia: str | None = None
    cnpj: str
    segmento: str | None = None
    endereco: str | None = None
    cidade: str | None = None
    uf: str | None = None
    cep: str | None = None
    telefone: str | None = None
    email: EmailStr | None = None
    logo_url: str | None = None


class EmpresaCreate(EmpresaBase):
    pass


class EmpresaUpdate(BaseModel):
    razao_social: str | None = None
    nome_fantasia: str | None = None
    cnpj: str | None = None
    segmento: str | None = None
    endereco: str | None = None
    cidade: str | None = None
    uf: str | None = None
    cep: str | None = None
    telefone: str | None = None
    email: EmailStr | None = None
    logo_url: str | None = None


class EmpresaRead(EmpresaBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ativo: bool
    criado_em: datetime
    atualizado_em: datetime
