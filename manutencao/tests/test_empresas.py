"""Testes de empresas: CRUD completo, conflitos, 404, permissões, validação."""
from __future__ import annotations

from tests.conftest import auth


def _nova(**over):
    base = {"razao_social": "Nova Empresa", "cnpj": "33.333.333/0001-33"}
    base.update(over)
    return base


async def test_criar_empresa(client, dados):
    resp = await client.post(
        "/api/v1/empresas", headers=auth(dados["admin1_token"]), json=_nova()
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["razao_social"] == "Nova Empresa"
    assert body["ativo"] is True
    assert body["id"]


async def test_criar_empresa_cnpj_duplicado(client, dados):
    resp = await client.post(
        "/api/v1/empresas",
        headers=auth(dados["admin1_token"]),
        json=_nova(cnpj="11.111.111/0001-11"),  # já existe (Empresa 1)
    )
    assert resp.status_code == 409


async def test_criar_empresa_sem_permissao(client, dados):
    resp = await client.post(
        "/api/v1/empresas", headers=auth(dados["leitor1_token"]), json=_nova()
    )
    assert resp.status_code == 403


async def test_criar_empresa_payload_invalido_422(client, dados):
    resp = await client.post(
        "/api/v1/empresas",
        headers=auth(dados["admin1_token"]),
        json={"nome_fantasia": "sem razao nem cnpj"},
    )
    assert resp.status_code == 422


async def test_listar_empresas(client, dados):
    resp = await client.get("/api/v1/empresas", headers=auth(dados["admin1_token"]))
    assert resp.status_code == 200
    body = resp.json()
    # Empresas do seed do fixture: Empresa 1 e Empresa 2.
    assert body["total"] == 2


async def test_listar_empresas_sem_permissao(client, dados):
    resp = await client.get("/api/v1/empresas", headers=auth(dados["semacesso1_token"]))
    assert resp.status_code == 403


async def test_obter_empresa(client, dados):
    resp = await client.get(
        f"/api/v1/empresas/{dados['empresa1_id']}", headers=auth(dados["admin1_token"])
    )
    assert resp.status_code == 200
    assert resp.json()["razao_social"] == "Empresa 1"


async def test_obter_empresa_inexistente_404(client, dados):
    resp = await client.get(
        "/api/v1/empresas/00000000-0000-0000-0000-000000000000",
        headers=auth(dados["admin1_token"]),
    )
    assert resp.status_code == 404


async def test_atualizar_empresa(client, dados):
    resp = await client.put(
        f"/api/v1/empresas/{dados['empresa1_id']}",
        headers=auth(dados["admin1_token"]),
        json={"nome_fantasia": "Fantasia Nova"},
    )
    assert resp.status_code == 200
    assert resp.json()["nome_fantasia"] == "Fantasia Nova"


async def test_atualizar_empresa_sem_permissao(client, dados):
    resp = await client.put(
        f"/api/v1/empresas/{dados['empresa1_id']}",
        headers=auth(dados["leitor1_token"]),
        json={"nome_fantasia": "X"},
    )
    assert resp.status_code == 403


async def test_inativar_empresa(client, dados):
    resp = await client.delete(
        f"/api/v1/empresas/{dados['empresa1_id']}", headers=auth(dados["admin1_token"])
    )
    assert resp.status_code == 204
    # Depois: 404 no obter e sai da listagem.
    get = await client.get(
        f"/api/v1/empresas/{dados['empresa1_id']}", headers=auth(dados["admin1_token"])
    )
    assert get.status_code == 404
    lista = await client.get("/api/v1/empresas", headers=auth(dados["admin1_token"]))
    assert lista.json()["total"] == 1


async def test_inativar_empresa_sem_permissao(client, dados):
    resp = await client.delete(
        f"/api/v1/empresas/{dados['empresa1_id']}", headers=auth(dados["leitor1_token"])
    )
    assert resp.status_code == 403
