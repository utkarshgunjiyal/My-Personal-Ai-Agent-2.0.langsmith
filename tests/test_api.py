"""Smoke tests that exercise the public API without invoking the LLM (where possible)."""
import os
import time

import httpx
import pytest

BASE = os.environ.get("E2E_BACKEND_URL", "http://localhost:8001")


def test_root():
    r = httpx.get(f"{BASE}/api/", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "AI Decision Engine"


def test_health():
    r = httpx.get(f"{BASE}/api/health", timeout=10)
    assert r.status_code == 200
    assert r.json()["status"] in {"healthy", "degraded"}


def _register_user(email: str, password: str, name: str = "Test User"):
    with httpx.Client(base_url=BASE, timeout=20) as c:
        r = c.post(
            "/api/auth/register",
            json={"email": email, "password": password, "name": name},
        )
        return r, c


def test_auth_register_and_me():
    email = f"smoke_{int(time.time())}@example.com"
    r, c = _register_user(email, "secret123")
    assert r.status_code == 200, r.text
    user = r.json()
    assert user["email"] == email
    me = c.get("/api/auth/me", cookies=r.cookies)
    assert me.status_code == 200


def test_auth_login_wrong_password():
    email = f"smoke2_{int(time.time())}@example.com"
    _register_user(email, "secret123")
    r = httpx.post(
        f"{BASE}/api/auth/login",
        json={"email": email, "password": "WRONG"},
        timeout=15,
    )
    assert r.status_code == 401


def test_threads_require_auth():
    r = httpx.get(f"{BASE}/api/threads", timeout=10)
    assert r.status_code == 401


def test_stats_require_auth():
    r = httpx.get(f"{BASE}/api/stats/overview", timeout=10)
    assert r.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
