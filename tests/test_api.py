"""Smoke tests that exercise the public API without invoking the LLM."""

import os
import time
import uuid

import httpx
import pytest


BASE = os.environ.get("E2E_BACKEND_URL", "http://localhost:8001")


def test_root():
    response = httpx.get(f"{BASE}/api/", timeout=10)
    assert response.status_code == 200
    assert response.json()["service"] == "AI Decision Engine"


def test_health():
    response = httpx.get(f"{BASE}/api/health", timeout=10)
    assert response.status_code == 200
    assert response.json()["status"] in {"healthy", "degraded"}


def _register_user(email: str, password: str, name: str = "Test User"):
    with httpx.Client(base_url=BASE, timeout=20) as client:
        return client.post(
            "/api/auth/register",
            json={"email": email, "password": password, "name": name},
        )


def test_auth_register_and_me():
    email = f"ci-{uuid.uuid4().hex[:10]}@example.com"

    # Keep the same client open so its authentication cookie is retained.
    with httpx.Client(base_url=BASE, timeout=20) as client:
        register = client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "TestPass123!",
                "name": "CI Tester",
            },
        )
        assert register.status_code in (200, 201), register.text

        me = client.get("/api/auth/me")
        assert me.status_code == 200, me.text


def test_auth_login_wrong_password():
    email = f"smoke2_{int(time.time())}@example.com"
    register = _register_user(email, "secret123")
    assert register.status_code in (200, 201), register.text

    response = httpx.post(
        f"{BASE}/api/auth/login",
        json={"email": email, "password": "WRONG"},
        timeout=15,
    )
    assert response.status_code == 401


def test_threads_require_auth():
    response = httpx.get(f"{BASE}/api/threads", timeout=10)
    assert response.status_code == 401


def test_stats_require_auth():
    response = httpx.get(f"{BASE}/api/stats/overview", timeout=10)
    assert response.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
