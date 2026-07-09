"""Fixtures de teste. Usa SQLite em memória (aiosqlite) para rodar sem Postgres —
o schema é criado a partir de Base.metadata; a migração Alembic é validada à parte
contra Postgres (ver README)."""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.security import criar_access_token, hash_senha
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.empresa import Empresa
from app.models.perfil import Perfil
from app.models.permissao import Permissao
from app.models.usuario import Usuario

# Módulos usados nas permissões dos perfis de teste.
MODULOS = ["empresas", "perfis", "usuarios", "equipamentos", "manutencoes"]


def _perm(modulo: str, criar=False, ler=True, editar=False, excluir=False) -> Permissao:
    return Permissao(
        modulo=modulo,
        pode_criar=criar,
        pode_ler=ler,
        pode_editar=editar,
        pode_excluir=excluir,
    )


def _perfil_admin() -> Perfil:
    return Perfil(
        nome="Admin",
        nivel_acesso=1,
        permissoes=[_perm(m, True, True, True, True) for m in MODULOS],
    )


def _perfil_leitura() -> Perfil:
    return Perfil(
        nome="Leitura",
        nivel_acesso=4,
        permissoes=[_perm(m, False, True, False, False) for m in MODULOS],
    )


def _perfil_sem_acesso() -> Perfil:
    # Perfil válido mas sem nenhuma permissão (nem leitura).
    return Perfil(nome="SemAcesso", nivel_acesso=4, permissoes=[])


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sessionmaker_(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(sessionmaker_):
    async def _override_get_db():
        async with sessionmaker_() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def dados(sessionmaker_):
    """Popula 2 empresas, 3 perfis e vários usuários. Retorna ids e tokens úteis."""
    async with sessionmaker_() as s:
        admin = _perfil_admin()
        leitura = _perfil_leitura()
        sem_acesso = _perfil_sem_acesso()
        s.add_all([admin, leitura, sem_acesso])
        await s.flush()

        emp1 = Empresa(razao_social="Empresa 1", cnpj="11.111.111/0001-11")
        emp2 = Empresa(razao_social="Empresa 2", cnpj="22.222.222/0001-22")
        s.add_all([emp1, emp2])
        await s.flush()

        admin1 = Usuario(
            empresa_id=emp1.id, perfil_id=admin.id, nome="Admin E1",
            email="admin@e1.com", senha_hash=hash_senha("admin123"),
        )
        leitor1 = Usuario(
            empresa_id=emp1.id, perfil_id=leitura.id, nome="Leitor E1",
            email="leitor@e1.com", senha_hash=hash_senha("leitor123"),
        )
        semacesso1 = Usuario(
            empresa_id=emp1.id, perfil_id=sem_acesso.id, nome="Sem Acesso E1",
            email="semacesso@e1.com", senha_hash=hash_senha("semacesso123"),
        )
        inativo1 = Usuario(
            empresa_id=emp1.id, perfil_id=admin.id, nome="Inativo E1",
            email="inativo@e1.com", senha_hash=hash_senha("inativo123"), ativo=False,
        )
        admin2 = Usuario(
            empresa_id=emp2.id, perfil_id=admin.id, nome="Admin E2",
            email="admin@e2.com", senha_hash=hash_senha("admin123"),
        )
        s.add_all([admin1, leitor1, semacesso1, inativo1, admin2])
        await s.commit()

        return {
            "empresa1_id": str(emp1.id),
            "empresa2_id": str(emp2.id),
            "perfil_admin_id": str(admin.id),
            "perfil_leitura_id": str(leitura.id),
            "perfil_sem_acesso_id": str(sem_acesso.id),
            "admin1_id": str(admin1.id),
            "leitor1_id": str(leitor1.id),
            "admin2_id": str(admin2.id),
            "admin1_token": criar_access_token(admin1.id),
            "leitor1_token": criar_access_token(leitor1.id),
            "semacesso1_token": criar_access_token(semacesso1.id),
            "admin2_token": criar_access_token(admin2.id),
            "inativo1_token": criar_access_token(inativo1.id),
        }


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
