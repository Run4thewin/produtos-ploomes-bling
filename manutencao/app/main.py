from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.routers import auth, empresas, perfis, usuarios
from app.services.errors import (
    Conflito,
    CredenciaisInvalidas,
    DomainError,
    NaoEncontrado,
    SemPermissao,
    TokenInvalido,
)

app = FastAPI(
    title="Aplicativo de Manutenção — API",
    version="0.1.0",
    description="Backend de gestão de manutenção industrial (multi-tenant).",
)

# Mapeamento de exceções de domínio -> HTTP.
_STATUS_POR_ERRO: dict[type[DomainError], int] = {
    NaoEncontrado: 404,
    Conflito: 409,
    CredenciaisInvalidas: 401,
    TokenInvalido: 401,
    SemPermissao: 403,
}


@app.exception_handler(DomainError)
async def _domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    status = next(
        (s for tipo, s in _STATUS_POR_ERRO.items() if isinstance(exc, tipo)), 400
    )
    return JSONResponse(status_code=status, content={"detail": str(exc)})


@app.get("/health", tags=["infra"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


_API_V1 = "/api/v1"
app.include_router(auth.router, prefix=_API_V1)
app.include_router(empresas.router, prefix=_API_V1)
app.include_router(perfis.router, prefix=_API_V1)
app.include_router(usuarios.router, prefix=_API_V1)
