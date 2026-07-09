async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_openapi_disponivel(client):
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    # Rotas principais registradas sob /api/v1.
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/usuarios" in paths
    assert "/api/v1/empresas" in paths
    assert "/api/v1/perfis" in paths
