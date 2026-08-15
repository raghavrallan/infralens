"""API health, login, JWT middleware, and viewer write-block."""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def test_health_is_public(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "skill_count" in body


def test_protected_route_requires_authentication(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert "authenticated" in response.json()["detail"].lower()


def test_invalid_and_malformed_tokens_are_rejected(client):
    assert client.get("/api/skills", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
    assert client.get("/api/skills", headers={"Authorization": "Token abc"}).status_code == 401
    assert client.get("/api/skills", headers={"Authorization": "Bearer"}).status_code == 401


def test_login_success_and_me(client, make_user):
    user = make_user(role="developer", password="secret12")
    response = client.post(
        "/api/auth/login",
        json={"username": user["username"], "password": "secret12"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["token"]
    assert "password" not in str(payload).lower() or "password_hash" not in str(payload)
    me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {payload['token']}"},
    )
    assert me.status_code == 200
    assert me.json()["user"]["username"] == user["username"]
    assert "password_hash" not in me.json()["user"]


def test_login_rejects_invalid_and_missing_credentials(client, make_user):
    user = make_user(password="secret12")
    bad = client.post(
        "/api/auth/login",
        json={"username": user["username"], "password": "wrong-password"},
    )
    assert bad.status_code == 401
    missing = client.post("/api/auth/login", json={"username": user["username"]})
    assert missing.status_code == 422


def test_inactive_user_cannot_login(client, make_user):
    user = make_user(password="secret12", is_active=False)
    response = client.post(
        "/api/auth/login",
        json={"username": user["username"], "password": "secret12"},
    )
    assert response.status_code == 401


def test_viewer_can_read_but_cannot_write(client, viewer):
    headers = {"Authorization": f"Bearer {viewer['token']}"}
    skills = client.get("/api/skills", headers=headers)
    assert skills.status_code == 200
    create = client.post("/api/projects", json={"name": "blocked"}, headers=headers)
    assert create.status_code == 403
    assert "read-only" in create.json()["detail"].lower() or "viewer" in create.json()["detail"].lower()


def test_unknown_skill_returns_404(client, developer):
    headers = {"Authorization": f"Bearer {developer['token']}"}
    response = client.get("/api/skills/not-a-skill", headers=headers)
    assert response.status_code == 404


def test_roles_endpoint(client, developer):
    headers = {"Authorization": f"Bearer {developer['token']}"}
    response = client.get("/api/roles", headers=headers)
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert "super_admin" in ids
    assert "viewer" in ids
