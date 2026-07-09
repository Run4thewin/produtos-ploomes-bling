from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.auth import (
    AccessToken,
    LoginRequest,
    RecuperarSenhaRequest,
    RecuperarSenhaResponse,
    RedefinirSenhaRequest,
    RefreshRequest,
    TokenPair,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/login", response_model=TokenPair)
async def login(dados: LoginRequest, session: DbSession) -> TokenPair:
    return await AuthService(session).login(dados.email, dados.senha)


@router.post("/refresh", response_model=AccessToken)
async def refresh(dados: RefreshRequest, session: DbSession) -> AccessToken:
    return await AuthService(session).refresh(dados.refresh_token)


@router.post("/recuperar-senha", response_model=RecuperarSenhaResponse)
async def recuperar_senha(
    dados: RecuperarSenhaRequest, session: DbSession
) -> RecuperarSenhaResponse:
    token = await AuthService(session).solicitar_reset(dados.email)
    # Resposta genérica para não revelar se o e-mail existe; em dev o token é retornado.
    return RecuperarSenhaResponse(
        detalhe="Se o e-mail estiver cadastrado, um link de redefinição foi enviado.",
        reset_token=token if get_settings().debug else None,
    )


@router.post("/redefinir-senha", status_code=204, response_class=Response)
async def redefinir_senha(dados: RedefinirSenhaRequest, session: DbSession):
    await AuthService(session).redefinir_senha(dados.reset_token, dados.nova_senha)
    return Response(status_code=204)
