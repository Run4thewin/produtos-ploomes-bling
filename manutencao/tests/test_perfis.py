"""Testes de perfis: criar (com permissões), listar, obter, atualizar, conflitos, permissões."""
from __future__ import annotations

from tests.conftest import auth


def _novo(**over):
    base = {
        "nome": "Supervisor",
        "descricao": "Perfil de supervisão",
        "nivel_acesso": 2,
        "permissoes": [
            {"modulo": "manutencoes", "pode_criar": True, "pode_ler": True,
             "pode_editar": True, "pode_excluir": False},
            {"modulo": "estoque", "pode_ler": True},
        ],
    }
    base.update(over)
    return base


async def test_criar_perfil_com_permissoes(client, dados):
    resp = await client.post(
        "/api/v1/perfis", headers=auth(dados["admin1_token"]), json=_novo()
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["nome"] == "Supervisor"
    assert len(body["permissoes"]) == 2
    modulos = {p["modulo"] for p in body["permissoes"]}
    assert modulos == {"manutencoes", "estoque"}


async def test_criar_perfil_nome_duplicado(client, dados):
    resp = await client.post(
        "/api/v1/perfis",
        headers=auth(dados["admin1_token"]),
        json=_novo(nome="Admin"),  # já existe
    )
    assert resp.status_code == 409


async def test_criar_perfil_sem_permissao(client, dados):
    resp = await client.post(
        "/api/v1/perfis", headers=auth(dados["leitor1_token"]), json=_novo()
    )
    assert resp.status_code == 403


async def test_criar_perfil_invalido_422(client, dados):
    resp = await client.post(
        "/api/v1/perfis",
        headers=auth(dados["admin1_token"]),
        json={"descricao": "sem nome nem nivel"},
    )
    assert resp.status_code == 422


async def test_listar_perfis(client, dados):
    resp = await client.get("/api/v1/perfis", headers=auth(dados["admin1_token"]))
    assert resp.status_code == 200
    body = resp.json()
    # Admin, Leitura, SemAcesso do fixture.
    assert body["total"] == 3
    nomes = {p["nome"] for p in body["items"]}
    assert {"Admin", "Leitura", "SemAcesso"} <= nomes


async def test_obter_perfil(client, dados):
    resp = await client.get(
        f"/api/v1/perfis/{dados['perfil_admin_id']}", headers=auth(dados["admin1_token"])
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["nome"] == "Admin"
    assert len(body["permissoes"]) >= 1


async def test_obter_perfil_inexistente_404(client, dados):
    resp = await client.get(
        "/api/v1/perfis/00000000-0000-0000-0000-000000000000",
        headers=auth(dados["admin1_token"]),
    )
    assert resp.status_code == 404


async def test_atualizar_perfil(client, dados):
    resp = await client.put(
        f"/api/v1/perfis/{dados['perfil_leitura_id']}",
        headers=auth(dados["admin1_token"]),
        json={"descricao": "Somente leitura (atualizado)"},
    )
    assert resp.status_code == 200
    assert resp.json()["descricao"] == "Somente leitura (atualizado)"


async def test_atualizar_perfil_sem_permissao(client, dados):
    resp = await client.put(
        f"/api/v1/perfis/{dados['perfil_leitura_id']}",
        headers=auth(dados["leitor1_token"]),
        json={"descricao": "X"},
    )
    assert resp.status_code == 403


async def test_perfis_exige_autenticacao(client, dados):
    resp = await client.get("/api/v1/perfis")
    assert resp.status_code == 403
