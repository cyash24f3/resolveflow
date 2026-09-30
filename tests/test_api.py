from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from resolveflow.api import app as module
from resolveflow.settings import get_settings


@pytest.fixture
def client(db, monkeypatch):
    factory, _, _ = db
    monkeypatch.setattr(module, "sessions", lambda: factory)
    monkeypatch.setattr(get_settings(), "demo_mode", True)
    monkeypatch.setattr(get_settings(), "cookie_secure", False)
    with TestClient(module.app) as client:
        yield client


def auth(client, role="operator"):
    result = client.post("/api/v1/auth/demo/" + role)
    assert result.status_code == 200
    return {"X-CSRF-Token": result.json()["csrf"]}


def test_auth_public_csrf_trace_and_scope(client):
    assert client.get("/api/v1/runs").status_code == 401
    assert client.get("/api/v1/sample").json()["read_only"]
    headers = auth(client)
    body = {"customer_id": "C-100", "message": "ORD-1001 damaged", "idempotency_key": uuid4().hex}
    assert client.post("/api/v1/runs", json=body).status_code == 403
    first = client.post("/api/v1/runs", json=body, headers=headers)
    assert first.status_code == 201
    assert (
        client.post("/api/v1/runs", json=body, headers=headers).json()["id"] == first.json()["id"]
    )
    assert (
        client.post(
            "/api/v1/runs", json={**body, "message": "changed"}, headers=headers
        ).status_code
        == 409
    )
    assert client.get("/api/v1/runs/" + first.json()["id"] + "/trace").status_code == 403
    assert client.get("/api/v1/sandbox/orders/ORD-2001").status_code == 404
    assert client.get("/api/v1/sandbox/orders/ORD-9001").status_code == 404
    assert (
        client.post(
            "/api/v1/runs",
            json={**body, "customer_id": "C-900", "idempotency_key": uuid4().hex},
            headers=headers,
        ).status_code
        == 404
    )


def test_api_clarification_approval_integration(client, work):
    headers = auth(client)
    run = client.post(
        "/api/v1/runs",
        json={
            "customer_id": "C-100",
            "message": "My order arrived damaged.",
            "idempotency_key": uuid4().hex,
        },
        headers=headers,
    ).json()
    id_ = run["id"]
    work()
    facts = {"facts": {"order_id": "ORD-1001"}, "idempotency_key": uuid4().hex}
    assert (
        client.post(f"/api/v1/runs/{id_}/clarification", json=facts, headers=headers).status_code
        == 200
    )
    assert (
        client.post(f"/api/v1/runs/{id_}/clarification", json=facts, headers=headers).status_code
        == 200
    )
    work()
    assert (
        client.post(
            f"/api/v1/runs/{id_}/clarification",
            json={
                "facts": {
                    "damage_description": "crack",
                    "damage_reported_at": "2026-09-10T10:00:00Z",
                    "photo_reviewed": True,
                },
                "idempotency_key": uuid4().hex,
            },
            headers=headers,
        ).status_code
        == 200
    )
    work()
    detail = client.get(f"/api/v1/runs/{id_}").json()
    p = detail["proposal"]
    body = {
        "decision": "approve",
        "expected_revision": p["revision"],
        "expected_hash": p["payload_hash"],
    }
    assert (
        client.post(f"/api/v1/proposals/{p['id']}/decision", json=body, headers=headers).status_code
        == 403
    )
    headers = auth(client, "supervisor")
    assert (
        client.post(f"/api/v1/proposals/{p['id']}/decision", json=body, headers=headers).status_code
        == 200
    )
    work()
    assert client.get(f"/api/v1/runs/{id_}").json()["final"]["outcome"] == "resolved"
    assert len(client.get("/api/v1/sandbox").json()["effects"]) == 1


def test_public_mode_forbids_mutations(client, monkeypatch):
    headers = auth(client)
    monkeypatch.setattr(get_settings(), "public_read_only", True)
    assert (
        client.post(
            "/api/v1/runs",
            json={"customer_id": "C-100", "message": "ORD-1001", "idempotency_key": uuid4().hex},
            headers=headers,
        ).status_code
        == 403
    )
    assert client.post("/api/v1/auth/demo/developer").status_code == 403


def test_hosted_login_and_public_example(client, monkeypatch):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "demo_mode", False)
    monkeypatch.setattr(cfg, "remote_deployment", True)
    monkeypatch.setattr(cfg, "cookie_secure", True)
    html = client.get("/").text
    assert "HOSTED SANDBOX" in html
    assert 'data-login="supervisor"' not in html
    assert 'data-demo-mode="false"' in html
    assert "data-sample" in html
    for role in ("operator", "supervisor", "developer"):
        assert client.post("/api/v1/auth/demo/" + role).status_code == 403
    assert client.get("/api/v1/sample").json()["read_only"]
    assert client.get("/api/v1/runs").status_code == 401
    monkeypatch.setattr(cfg, "operator_password", SecretStr("test-only-operator-password"))
    login = client.post(
        "/api/v1/auth/login",
        json={"role": "operator", "password": "test-only-operator-password"},
    )
    assert login.status_code == 200
    cookie = login.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie
