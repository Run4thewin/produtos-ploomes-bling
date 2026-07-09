"""Dependencies comuns: autenticação (get_current_user) e autorização (require_permission)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TOKEN_ACCESS, decodificar_token
from app.db.session import get_db
from app.models.usuario import Usuario
from app.repositories.usuario import UsuarioRepository
from app.services.errors import SemPermissao, TokenInvalido

_bearer = HTTPBearer(auto_error=True)

# Ações da rota -> flag correspondente em `permissao`.
_ACAO_FLAG = {
    "criar": "pode_criar",
    "ler": "pode_ler",
    "editar": "pode_editar",
    "excluir": "pode_excluir",
}


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Usuario:
    try:
        usuario_id = decodificar_token(credentials.credentials, TOKEN_ACCESS)
    except jwt.InvalidTokenError as exc:
        raise TokenInvalido("Token de acesso inválido ou expirado") from exc
    usuario = await UsuarioRepository(session).get_by_id_com_perfil(usuario_id)
    if not usuario or not usuario.ativo:
        raise TokenInvalido("Usuário inválido ou inativo")
    return usuario


CurrentUser = Annotated[Usuario, Depends(get_current_user)]


def require_permission(modulo: str, acao: str) -> Callable[..., Usuario]:
    """Dependency-factory: garante que o perfil do usuário tem a flag da ação no módulo."""
    flag = _ACAO_FLAG[acao]

    async def _checar(usuario: CurrentUser) -> Usuario:
        permitido = any(
            p.modulo == modulo and getattr(p, flag)
            for p in usuario.perfil.permissoes
        )
        if not permitido:
            raise SemPermissao(f"Sem permissão para '{acao}' no módulo '{modulo}'")
        return usuario

    return _checar
