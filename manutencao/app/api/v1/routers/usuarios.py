from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, require_permission
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.common import Page
from app.schemas.usuario import UsuarioCreate, UsuarioRead, UsuarioUpdate
from app.services.usuario_service import UsuarioService

router = APIRouter(prefix="/usuarios", tags=["usuarios"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
MODULO = "usuarios"


@router.get("/me", response_model=UsuarioRead)
async def usuario_atual(usuario: CurrentUser) -> Usuario:
    return usuario


@router.post(
    "", response_model=UsuarioRead, status_code=201,
    dependencies=[Depends(require_permission(MODULO, "criar"))],
)
async def criar_usuario(
    dados: UsuarioCreate, session: DbSession, atual: CurrentUser
) -> Usuario:
    # empresa_id vem SEMPRE do usuário logado — nunca do client.
    return await UsuarioService(session).criar(atual.empresa_id, dados)


@router.get(
    "", response_model=Page[UsuarioRead],
    dependencies=[Depends(require_permission(MODULO, "ler"))],
)
async def listar_usuarios(
    session: DbSession,
    atual: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Page[UsuarioRead]:
    itens, total = await UsuarioService(session).listar(atual.empresa_id, page, page_size)
    return Page(items=itens, total=total, page=page, page_size=page_size)


@router.get(
    "/{usuario_id}", response_model=UsuarioRead,
    dependencies=[Depends(require_permission(MODULO, "ler"))],
)
async def obter_usuario(
    usuario_id: UUID, session: DbSession, atual: CurrentUser
) -> Usuario:
    return await UsuarioService(session).obter(atual.empresa_id, usuario_id)


@router.put(
    "/{usuario_id}", response_model=UsuarioRead,
    dependencies=[Depends(require_permission(MODULO, "editar"))],
)
async def atualizar_usuario(
    usuario_id: UUID, dados: UsuarioUpdate, session: DbSession, atual: CurrentUser
) -> Usuario:
    return await UsuarioService(session).atualizar(atual.empresa_id, usuario_id, dados)


@router.delete(
    "/{usuario_id}", status_code=204, response_class=Response,
    dependencies=[Depends(require_permission(MODULO, "excluir"))],
)
async def inativar_usuario(
    usuario_id: UUID, session: DbSession, atual: CurrentUser
):
    await UsuarioService(session).inativar(atual.empresa_id, usuario_id)
    return Response(status_code=204)
