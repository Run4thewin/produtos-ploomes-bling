"""Exceções de domínio. Os routers/handlers mapeiam para códigos HTTP em app/main.py."""
from __future__ import annotations


class DomainError(Exception):
    """Base para erros de regra de negócio."""


class NaoEncontrado(DomainError):
    """Recurso inexistente (HTTP 404)."""


class Conflito(DomainError):
    """Violação de unicidade / estado conflitante (HTTP 409)."""


class CredenciaisInvalidas(DomainError):
    """Login inválido (HTTP 401)."""


class TokenInvalido(DomainError):
    """Token JWT ausente, expirado ou de tipo incorreto (HTTP 401)."""


class SemPermissao(DomainError):
    """Usuário autenticado sem permissão para o módulo/ação (HTTP 403)."""
