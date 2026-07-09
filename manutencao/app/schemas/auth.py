from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    senha: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RecuperarSenhaRequest(BaseModel):
    email: EmailStr


class RecuperarSenhaResponse(BaseModel):
    """Em produção o token é enviado por e-mail; em dev é retornado para facilitar testes."""

    detalhe: str
    reset_token: str | None = None


class RedefinirSenhaRequest(BaseModel):
    reset_token: str
    nova_senha: str = Field(min_length=6)
