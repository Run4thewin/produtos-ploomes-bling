from __future__ import annotations

from datetime import datetime, timezone

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    TOKEN_REFRESH,
    TOKEN_RESET,
    criar_access_token,
    criar_refresh_token,
    criar_reset_token,
    decodificar_token,
    hash_senha,
    verificar_senha,
)
from app.repositories.usuario import UsuarioRepository
from app.schemas.auth import AccessToken, TokenPair
from app.services.errors import CredenciaisInvalidas, TokenInvalido


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = UsuarioRepository(session)

    async def login(self, email: str, senha: str) -> TokenPair:
        usuario = await self.repo.get_by_email(email)
        if not usuario or not usuario.ativo or not verificar_senha(senha, usuario.senha_hash):
            raise CredenciaisInvalidas("E-mail ou senha inválidos")
        usuario.ultimo_login = datetime.now(timezone.utc)
        await self.session.commit()
        return TokenPair(
            access_token=criar_access_token(usuario.id),
            refresh_token=criar_refresh_token(usuario.id),
        )

    async def refresh(self, refresh_token: str) -> AccessToken:
        try:
            usuario_id = decodificar_token(refresh_token, TOKEN_REFRESH)
        except jwt.InvalidTokenError as exc:
            raise TokenInvalido("Refresh token inválido ou expirado") from exc
        usuario = await self.repo.get_by_id(usuario_id)
        if not usuario or not usuario.ativo:
            raise TokenInvalido("Usuário inválido para este token")
        return AccessToken(access_token=criar_access_token(usuario.id))

    async def solicitar_reset(self, email: str) -> str | None:
        """Gera um reset token se o e-mail existir. Em produção seria enviado por e-mail;
        aqui é retornado para permitir o fluxo em dev/testes. Retorna None se não existir
        (o router responde com mensagem genérica para não revelar cadastro)."""
        usuario = await self.repo.get_by_email(email)
        if not usuario or not usuario.ativo:
            return None
        return criar_reset_token(usuario.id)

    async def redefinir_senha(self, reset_token: str, nova_senha: str) -> None:
        try:
            usuario_id = decodificar_token(reset_token, TOKEN_RESET)
        except jwt.InvalidTokenError as exc:
            raise TokenInvalido("Token de redefinição inválido ou expirado") from exc
        usuario = await self.repo.get_by_id(usuario_id)
        if not usuario or not usuario.ativo:
            raise TokenInvalido("Usuário inválido para este token")
        usuario.senha_hash = hash_senha(nova_senha)
        await self.session.commit()
