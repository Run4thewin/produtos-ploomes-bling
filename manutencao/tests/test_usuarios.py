"""Testes de usuários: CRUD, permissões, isolamento multi-tenant, validações."""
from __future__ import annotations

from tests.conftest import auth


def _novo(dados, **over):
    base = {
        "nome": "Novo Usuario",
        "email": "novo@e1.com",
        "perfil_id": dados["perfil_leitura_id"],
        "senha": "senha123",
    }
    base.update(over)
    return base


# --- criar -----------------------------------------------------------------
async def test_criar_usuario_admin(client, dados):
    resp = await client.post(
        "/api/v1/usuarios", headers=auth(dados["admin1_token"]), json=_novo(dados)
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "novo@e1.com"
    # empresa_id deriva do token, nunca do payload.
    assert body["empresa_id"] == dados["empresa1_id"]


async def test_criar_usuario_sem_permissao(client, dados):
    resp = await client.post(
        "/api/v1/usuarios", headers=auth(dados["leitor1_token"]), json=_novo(dados)
    )
    assert resp.status_code == 403


async def test_criar_usuario_email_duplicado(client, dados):
    resp = await client.post(
        "/api/v1/usuarios",
        headers=auth(dados["admin1_token"]),
        json=_novo(dados, email="admin@e1.com"),
    )
    assert resp.status_code == 409


async def test_criar_usuario_perfil_inexistente(client, dados):
    resp = await client.post(
        "/api/v1/usuarios",
        headers=auth(dados["admin1_token"]),
        json=_novo(dados, perfil_id="00000000-0000-0000-0000-000000000000"),
    )
    assert resp.status_code == 404


async def test_criar_usuario_payload_invalido_422(client, dados):
    resp = await client.post(
        "/api/v1/usuarios",
        headers=auth(dados["admin1_token"]),
        json={"nome": "X"},  # faltam campos obrigatórios
    )
    assert resp.status_code == 422


# --- listar / isolamento ---------------------------------------------------
async def test_listar_isola_por_empresa(client, dados):
    resp = await client.get("/api/v1/usuarios", headers=auth(dados["admin1_token"]))
    assert resp.status_code == 200
    body = resp.json()
    emails = {u["email"] for u in body["items"]}
    # Só ativos da empresa 1 (admin1, leitor1, semacesso1) — inativo e empresa2 fora.
    assert emails == {"admin@e1.com", "leitor@e1.com", "semacesso@e1.com"}
    assert body["total"] == 3


async def test_listar_paginacao(client, dados):
    resp = await client.get(
        "/api/v1/usuarios?page=1&page_size=2", headers=auth(dados["admin1_token"])
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["total"] == 3
    assert body["page_size"] == 2


async def test_listar_sem_permissao(client, dados):
    resp = await client.get("/api/v1/usuarios", headers=auth(dados["semacesso1_token"]))
    assert resp.status_code == 403


# --- obter -----------------------------------------------------------------
async def test_obter_usuario_da_empresa(client, dados):
    resp = await client.get(
        f"/api/v1/usuarios/{dados['leitor1_id']}", headers=auth(dados["admin1_token"])
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "leitor@e1.com"


async def test_obter_usuario_de_outra_empresa_404(client, dados):
    # admin1 não enxerga usuário da empresa 2.
    resp = await client.get(
        f"/api/v1/usuarios/{dados['admin2_id']}", headers=auth(dados["admin1_token"])
    )
    assert resp.status_code == 404


# --- atualizar -------------------------------------------------------------
async def test_atualizar_usuario_nome(client, dados):
    resp = await client.put(
        f"/api/v1/usuarios/{dados['leitor1_id']}",
        headers=auth(dados["admin1_token"]),
        json={"nome": "Leitor Renomeado"},
    )
    assert resp.status_code == 200
    assert resp.json()["nome"] == "Leitor Renomeado"


async def test_atualizar_senha_permite_novo_login(client, dados):
    resp = await client.put(
        f"/api/v1/usuarios/{dados['leitor1_id']}",
        headers=auth(dados["admin1_token"]),
        json={"senha": "outraSenha9"},
    )
    assert resp.status_code == 200
    login = await client.post(
        "/api/v1/auth/login", json={"email": "leitor@e1.com", "senha": "outraSenha9"}
    )
    assert login.status_code == 200


async def test_atualizar_email_conflito(client, dados):
    resp = await client.put(
        f"/api/v1/usuarios/{dados['leitor1_id']}",
        headers=auth(dados["admin1_token"]),
        json={"email": "admin@e1.com"},  # já existe
    )
    assert resp.status_code == 409


async def test_atualizar_perfil_inexistente_404(client, dados):
    resp = await client.put(
        f"/api/v1/usuarios/{dados['leitor1_id']}",
        headers=auth(dados["admin1_token"]),
        json={"perfil_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 404


async def test_atualizar_sem_permissao(client, dados):
    resp = await client.put(
        f"/api/v1/usuarios/{dados['leitor1_id']}",
        headers=auth(dados["leitor1_token"]),  # Leitura não pode editar
        json={"nome": "X"},
    )
    assert resp.status_code == 403


async def test_atualizar_outra_empresa_404(client, dados):
    resp = await client.put(
        f"/api/v1/usuarios/{dados['admin2_id']}",
        headers=auth(dados["admin1_token"]),
        json={"nome": "X"},
    )
    assert resp.status_code == 404


# --- inativar (soft delete) ------------------------------------------------
async def test_inativar_usuario(client, dados):
    resp = await client.delete(
        f"/api/v1/usuarios/{dados['leitor1_id']}", headers=auth(dados["admin1_token"])
    )
    assert resp.status_code == 204

    # Depois de inativar: não aparece mais e obter retorna 404.
    get = await client.get(
        f"/api/v1/usuarios/{dados['leitor1_id']}", headers=auth(dados["admin1_token"])
    )
    assert get.status_code == 404
    lista = await client.get("/api/v1/usuarios", headers=auth(dados["admin1_token"]))
    emails = {u["email"] for u in lista.json()["items"]}
    assert "leitor@e1.com" not in emails


async def test_inativar_sem_permissao(client, dados):
    resp = await client.delete(
        f"/api/v1/usuarios/{dados['leitor1_id']}", headers=auth(dados["leitor1_token"])
    )
    assert resp.status_code == 403
