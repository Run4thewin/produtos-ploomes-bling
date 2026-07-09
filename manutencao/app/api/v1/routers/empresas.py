from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_permission
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.empresa import EmpresaCreate, EmpresaRead, EmpresaUpdate
from app.services.empresa_service import EmpresaService

router = APIRouter(prefix="/empresas", tags=["empresas"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
MODULO = "empresas"


@router.post(
    "", response_model=EmpresaRead, status_code=201,
    dependencies=[Depends(require_permission(MODULO, "criar"))],
)
async def criar_empresa(dados: EmpresaCreate, session: DbSession) -> EmpresaRead:
    return await EmpresaService(session).criar(dados)


@router.get(
    "", response_model=Page[EmpresaRead],
    dependencies=[Depends(require_permission(MODULO, "ler"))],
)
async def listar_empresas(
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Page[EmpresaRead]:
    itens, total = await EmpresaService(session).listar(page, page_size)
    return Page(items=itens, total=total, page=page, page_size=page_size)


@router.get(
    "/{empresa_id}", response_model=EmpresaRead,
    dependencies=[Depends(require_permission(MODULO, "ler"))],
)
async def obter_empresa(empresa_id: UUID, session: DbSession) -> EmpresaRead:
    return await EmpresaService(session).obter(empresa_id)


@router.put(
    "/{empresa_id}", response_model=EmpresaRead,
    dependencies=[Depends(require_permission(MODULO, "editar"))],
)
async def atualizar_empresa(
    empresa_id: UUID, dados: EmpresaUpdate, session: DbSession
) -> EmpresaRead:
    return await EmpresaService(session).atualizar(empresa_id, dados)


@router.delete(
    "/{empresa_id}", status_code=204, response_class=Response,
    dependencies=[Depends(require_permission(MODULO, "excluir"))],
)
async def inativar_empresa(empresa_id: UUID, session: DbSession):
    await EmpresaService(session).inativar(empresa_id)
    return Response(status_code=204)
