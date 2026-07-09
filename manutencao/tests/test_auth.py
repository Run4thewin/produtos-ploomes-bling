"""Testes de autenticação: login, refresh, recuperação/redefinição de senha, /me."""
from __future__ import annotations

from tests.conftest import auth


# --- login ----------------------------------------------------------------
async def test_login_sucesso(client, dados):
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "admin@e1.com", "senha": "admin123"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_login_senha_invalida(client, dados):
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "admin@e1.com", "senha": "errada"}
    )
    assert resp.status_code == 401


async def test_login_email_inexistente(client, dados):
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "naoexiste@e1.com", "senha": "x"}
    )
    assert resp.status_code == 401


async def test_login_usuario_inativo(client, dados):
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "inativo@e1.com", "senha": "inativo123"}
    )
    assert resp.status_code == 401


async def test_login_email_malformado_422(client, dados):
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "sem-arroba", "senha": "x"}
    )
    assert resp.status_code == 422


# --- /me -------------------------------------------------------------------
async def test_me_com_token(client, dados):
    resp = await client.get("/api/v1/usuarios/me", headers=auth(dados["admin1_token"]))
    assert resp.status_code == 200
    assert resp.json()["email"] == "admin@e1.com"


async def test_me_sem_token(client, dados):
    resp = await client.get("/api/v1/usuarios/me")
    assert resp.status_code == 403  # HTTPBearer sem credenciais


async def test_me_token_invalido(client, dados):
    resp = await client.get("/api/v1/usuarios/me", headers=auth("token.invalido"))
    assert resp.status_code == 401


async def test_me_usuario_inativo_401(client, dados):
    # Token válido, mas usuário está inativo.
    resp = await client.get("/api/v1/usuarios/me", headers=auth(dados["inativo1_token"]))
    assert resp.status_code == 401


# --- refresh ---------------------------------------------------------------
async def test_refresh_sucesso(client, dados):
    login = await client.post(
        "/api/v1/auth/login", json={"email": "admin@e1.com", "senha": "admin123"}
    )
    refresh = login.json()["refresh_token"]
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_refresh_token_invalido(client, dados):
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "xxx"})
    assert resp.status_code == 401


async def test_refresh_com_access_token_rejeitado(client, dados):
    # Access token não serve como refresh (type errado).
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": dados["admin1_token"]}
    )
    assert resp.status_code == 401


# --- recuperação / redefinição de senha ------------------------------------
async def test_recuperar_senha_email_existente_retorna_token_em_debug(client, dados):
    resp = await client.post(
        "/api/v1/auth/recuperar-senha", json={"email": "admin@e1.com"}
    )
    assert resp.status_code == 200
    assert resp.json()["reset_token"]  # debug=true expõe o token


async def test_recuperar_senha_email_inexistente_generico(client, dados):
    resp = await client.post(
        "/api/v1/auth/recuperar-senha", json={"email": "naoexiste@e1.com"}
    )
    assert resp.status_code == 200
    assert resp.json()["reset_token"] is None


async def test_redefinir_senha_fluxo_completo(client, dados):
    # 1) solicita reset
    r1 = await client.post(
        "/api/v1/auth/recuperar-senha", json={"email": "admin@e1.com"}
    )
    reset_token = r1.json()["reset_token"]

    # 2) redefine
    r2 = await client.post(
        "/api/v1/auth/redefinir-senha",
        json={"reset_token": reset_token, "nova_senha": "novaSenha1"},
    )
    assert r2.status_code == 204

    # 3) senha antiga falha, nova funciona
    velho = await client.post(
        "/api/v1/auth/login", json={"email": "admin@e1.com", "senha": "admin123"}
    )
    assert velho.status_code == 401
    novo = await client.post(
        "/api/v1/auth/login", json={"email": "admin@e1.com", "senha": "novaSenha1"}
    )
    assert novo.status_code == 200


async def test_redefinir_senha_token_invalido(client, dados):
    resp = await client.post(
        "/api/v1/auth/redefinir-senha",
        json={"reset_token": "invalido", "nova_senha": "novaSenha1"},
    )
    assert resp.status_code == 401


async def test_redefinir_senha_com_access_token_rejeitado(client, dados):
    resp = await client.post(
        "/api/v1/auth/redefinir-senha",
        json={"reset_token": dados["admin1_token"], "nova_senha": "novaSenha1"},
    )
    assert resp.status_code == 401


async def test_redefinir_senha_curta_422(client, dados):
    r1 = await client.post(
        "/api/v1/auth/recuperar-senha", json={"email": "admin@e1.com"}
    )
    reset_token = r1.json()["reset_token"]
    resp = await client.post(
        "/api/v1/auth/redefinir-senha",
        json={"reset_token": reset_token, "nova_senha": "123"},  # < 6
    )
    assert resp.status_code == 422
