"""Hash de senha (passlib/bcrypt) e emissão/validação de JWT (access, refresh, reset)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Tipos de token emitidos pela aplicação
TOKEN_ACCESS = "access"
TOKEN_REFRESH = "refresh"
TOKEN_RESET = "reset"


def hash_senha(senha: str) -> str:
    return _pwd_context.hash(senha)


def verificar_senha(senha: str, senha_hash: str) -> bool:
    return _pwd_context.verify(senha, senha_hash)


def _criar_token(subject: UUID, tipo: str, expira_em: timedelta) -> str:
    settings = get_settings()
    agora = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "type": tipo,
        "iat": int(agora.timestamp()),
        "exp": int((agora + expira_em).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def criar_access_token(usuario_id: UUID) -> str:
    settings = get_settings()
    return _criar_token(usuario_id, TOKEN_ACCESS, timedelta(minutes=settings.access_token_min))


def criar_refresh_token(usuario_id: UUID) -> str:
    settings = get_settings()
    return _criar_token(usuario_id, TOKEN_REFRESH, timedelta(days=settings.refresh_token_days))


def criar_reset_token(usuario_id: UUID) -> str:
    settings = get_settings()
    return _criar_token(usuario_id, TOKEN_RESET, timedelta(minutes=settings.reset_token_min))


def decodificar_token(token: str, tipo_esperado: str) -> UUID:
    """Decodifica e valida o token, garantindo o `type`. Lança jwt.InvalidTokenError se inválido."""
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
    if payload.get("type") != tipo_esperado:
        raise jwt.InvalidTokenError("tipo de token inesperado")
    return UUID(payload["sub"])
