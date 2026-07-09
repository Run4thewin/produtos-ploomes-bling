"""Testes unitários de hashing e JWT."""
from __future__ import annotations

from uuid import uuid4

import jwt
import pytest

from app.core import security


def test_hash_e_verificacao():
    h = security.hash_senha("segredo123")
    assert h != "segredo123"
    assert security.verificar_senha("segredo123", h)
    assert not security.verificar_senha("errada", h)


def test_hash_gera_valores_diferentes():
    # bcrypt usa salt aleatório: hashes diferentes, ambos válidos.
    a = security.hash_senha("igual")
    b = security.hash_senha("igual")
    assert a != b
    assert security.verificar_senha("igual", a)
    assert security.verificar_senha("igual", b)


def test_access_token_roundtrip():
    uid = uuid4()
    token = security.criar_access_token(uid)
    assert security.decodificar_token(token, security.TOKEN_ACCESS) == uid


def test_refresh_e_reset_roundtrip():
    uid = uuid4()
    assert security.decodificar_token(
        security.criar_refresh_token(uid), security.TOKEN_REFRESH
    ) == uid
    assert security.decodificar_token(
        security.criar_reset_token(uid), security.TOKEN_RESET
    ) == uid


def test_tipo_incorreto_rejeitado():
    uid = uuid4()
    access = security.criar_access_token(uid)
    with pytest.raises(jwt.InvalidTokenError):
        security.decodificar_token(access, security.TOKEN_REFRESH)


def test_token_adulterado_rejeitado():
    uid = uuid4()
    token = security.criar_access_token(uid) + "x"
    with pytest.raises(jwt.InvalidTokenError):
        security.decodificar_token(token, security.TOKEN_ACCESS)


def test_token_expirado_rejeitado(monkeypatch):
    from datetime import timedelta

    uid = uuid4()
    # Emite um token já expirado.
    token = security._criar_token(uid, security.TOKEN_ACCESS, timedelta(minutes=-1))
    with pytest.raises(jwt.ExpiredSignatureError):
        security.decodificar_token(token, security.TOKEN_ACCESS)
