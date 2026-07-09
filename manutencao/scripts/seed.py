"""Seed idempotente: perfis padrão + permissões + empresa/usuário admin de bootstrap.

Uso:
    python -m scripts.seed

Variáveis de ambiente opcionais:
    SEED_ADMIN_EMAIL   (default: admin@demo.local)
    SEED_ADMIN_SENHA   (default: admin123)
    SEED_EMPRESA_CNPJ  (default: 00.000.000/0001-00)
"""
from __future__ import annotations

import asyncio
import os

from sqlalchemy import select

from app.core.security import hash_senha
from app.db.base import AsyncSessionLocal
from app.models.empresa import Empresa
from app.models.perfil import Perfil
from app.models.permissao import Permissao
from app.models.usuario import Usuario

# Módulos do sistema para os quais definimos permissões.
MODULOS = [
    "empresas",
    "perfis",
    "usuarios",
    "equipamentos",
    "manutencoes",
    "estoque",
    "lubrificantes",
    "relatorios",
    "dashboard",
]

# Perfil -> (nivel_acesso, descricao, função que decide as flags por módulo).
PERFIS = {
    "Admin": (1, "Acesso total ao sistema", lambda m: (True, True, True, True)),
    "Gestor": (2, "Gestão sem exclusão", lambda m: (True, True, True, False)),
    "Tecnico": (
        3,
        "Execução de manutenções e estoque",
        lambda m: (
            (m in {"manutencoes", "estoque"}),  # criar
            True,  # ler
            (m in {"manutencoes", "estoque"}),  # editar
            False,  # excluir
        ),
    ),
    "Leitura": (4, "Somente leitura", lambda m: (False, True, False, False)),
}


async def _garantir_perfis(session) -> dict[str, Perfil]:
    perfis: dict[str, Perfil] = {}
    for nome, (nivel, descricao, regra) in PERFIS.items():
        perfil = (
            await session.execute(select(Perfil).where(Perfil.nome == nome))
        ).scalar_one_or_none()
        if perfil is None:
            perfil = Perfil(nome=nome, descricao=descricao, nivel_acesso=nivel)
            session.add(perfil)
            await session.flush()
        existentes = {
            p.modulo
            for p in (
                await session.execute(
                    select(Permissao).where(Permissao.perfil_id == perfil.id)
                )
            ).scalars()
        }
        for modulo in MODULOS:
            if modulo in existentes:
                continue
            criar, ler, editar, excluir = regra(modulo)
            session.add(
                Permissao(
                    perfil_id=perfil.id,
                    modulo=modulo,
                    pode_criar=criar,
                    pode_ler=ler,
                    pode_editar=editar,
                    pode_excluir=excluir,
                )
            )
        perfis[nome] = perfil
    return perfis


async def _garantir_admin(session, perfil_admin: Perfil) -> None:
    cnpj = os.getenv("SEED_EMPRESA_CNPJ", "00.000.000/0001-00")
    email = os.getenv("SEED_ADMIN_EMAIL", "admin@demo.local")
    senha = os.getenv("SEED_ADMIN_SENHA", "admin123")

    empresa = (
        await session.execute(select(Empresa).where(Empresa.cnpj == cnpj))
    ).scalar_one_or_none()
    if empresa is None:
        empresa = Empresa(razao_social="Empresa Demo", nome_fantasia="Demo", cnpj=cnpj)
        session.add(empresa)
        await session.flush()

    usuario = (
        await session.execute(select(Usuario).where(Usuario.email == email))
    ).scalar_one_or_none()
    if usuario is None:
        session.add(
            Usuario(
                empresa_id=empresa.id,
                perfil_id=perfil_admin.id,
                nome="Administrador",
                email=email,
                senha_hash=hash_senha(senha),
                cargo="Administrador",
            )
        )
        print(f"Usuário admin criado: {email} / {senha}")
    else:
        print(f"Usuário admin já existe: {email}")


async def main() -> None:
    async with AsyncSessionLocal() as session:
        perfis = await _garantir_perfis(session)
        await _garantir_admin(session, perfis["Admin"])
        await session.commit()
    print("Seed concluído.")


if __name__ == "__main__":
    asyncio.run(main())
