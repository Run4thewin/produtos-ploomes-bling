from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_permission
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.perfil import PerfilCreate, PerfilRead, PerfilUpdate
from app.services.perfil_service import PerfilService

router = APIRouter(prefix="/perfis", tags=["perfis"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
MODULO = "perfis"


@router.post(
    "", response_model=PerfilRead, status_code=201,
    dependencies=[Depends(require_permission(MODULO, "criar"))],
)
async def criar_perfil(dados: PerfilCreate, session: DbSession) -> PerfilRead:
    return await PerfilService(session).criar(dados)


@router.get(
    "", response_model=Page[PerfilRead],
    dependencies=[Depends(require_permission(MODULO, "ler"))],
)
async def listar_perfis(
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Page[PerfilRead]:
    itens, total = await PerfilService(session).listar(page, page_size)
    return Page(items=itens, total=total, page=page, page_size=page_size)


@router.get(
    "/{perfil_id}", response_model=PerfilRead,
    dependencies=[Depends(require_permission(MODULO, "ler"))],
)
async def obter_perfil(perfil_id: UUID, session: DbSession) -> PerfilRead:
    return await PerfilService(session).obter(perfil_id)


@router.put(
    "/{perfil_id}", response_model=PerfilRead,
    dependencies=[Depends(require_permission(MODULO, "editar"))],
)
async def atualizar_perfil(
    perfil_id: UUID, dados: PerfilUpdate, session: DbSession
) -> PerfilRead:
    return await PerfilService(session).atualizar(perfil_id, dados)
