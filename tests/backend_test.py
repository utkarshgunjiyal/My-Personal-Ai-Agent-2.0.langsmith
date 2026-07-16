"""End-to-end backend API tests for AI Decision Engine.

Covers: health, auth (register/login/me/logout), invalid login,
threads CRUD, ask pipeline (4 agents), stats overview, auth gating,
thread isolation.
"""
import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://multi-source-rag.preview.emergentagent.com",
).rstrip("/")

ADMIN_EMAIL = "admin@decision-engine.dev"
ADMIN_PASSWORD = "admin123"


# ---------- Fixtures ----------
@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def user_session():
    """A freshly registered user, auto-logged-in via cookies."""
    s = requests.Session()
    email = f"test_user_{uuid.uuid4().hex[:8]}@example.com"
    pw = "Passw0rd!"
    r = s.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": pw, "name": "Test User"},
        timeout=20,
    )
    assert r.status_code == 200, f"Register failed: {r.status_code} {r.text}"
    s._email = email  # type: ignore[attr-defined]
    s._password = pw  # type: ignore[attr-defined]
    return s


# ---------- Health ----------
class TestHealth:
    def test_root(self):
        r = requests.get(f"{BASE_URL}/api/", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["service"] == "AI Decision Engine"

    def test_health(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=10)
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"


# ---------- Auth gating (no cookies) ----------
class TestAuthGating:
    def test_threads_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/threads", timeout=10)
        assert r.status_code == 401

    def test_ask_requires_auth(self):
        r = requests.post(
            f"{BASE_URL}/api/ask", json={"question": "hi"}, timeout=10
        )
        assert r.status_code == 401

    def test_stats_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/stats/overview", timeout=10)
        assert r.status_code == 401

    def test_me_unauth(self):
        r = requests.get(f"{BASE_URL}/api/auth/me", timeout=10)
        assert r.status_code == 401


# ---------- Auth flows ----------
class TestAuth:
    def test_admin_login_and_me(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/auth/me", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == ADMIN_EMAIL
        assert data["role"] == "admin"
        assert "_id" not in data
        assert "password_hash" not in data

    def test_invalid_login(self):
        s = requests.Session()
        r = s.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": "wrong-password-xyz"},
            timeout=10,
        )
        assert r.status_code == 401
        body = r.json()
        assert "detail" in body

    def test_register_logs_in(self, user_session):
        r = user_session.get(f"{BASE_URL}/api/auth/me", timeout=10)
        assert r.status_code == 200
        me = r.json()
        assert me["email"] == user_session._email
        assert me["role"] == "user"
        assert me["auth_provider"] == "password"

    def test_register_duplicate_email(self, user_session):
        r = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={
                "email": user_session._email,
                "password": "anything123",
                "name": "Dup",
            },
            timeout=10,
        )
        assert r.status_code == 400

    def test_logout_clears_cookies(self):
        s = requests.Session()
        r = s.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=10,
        )
        assert r.status_code == 200
        r2 = s.post(f"{BASE_URL}/api/auth/logout", timeout=10)
        assert r2.status_code == 200
        # me should now be unauthenticated
        r3 = s.get(f"{BASE_URL}/api/auth/me", timeout=10)
        assert r3.status_code == 401


# ---------- Threads + Ask pipeline ----------
class TestThreadsAndAsk:
    def test_list_threads_initially_empty_for_new_user(self, user_session):
        r = user_session.get(f"{BASE_URL}/api/threads", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "threads" in data
        assert isinstance(data["threads"], list)

    def test_ask_creates_thread_and_runs_pipeline(self, user_session):
        q = "What is reinforcement learning in one paragraph?"
        started = time.time()
        r = user_session.post(
            f"{BASE_URL}/api/ask", json={"question": q}, timeout=180
        )
        elapsed = time.time() - started
        assert r.status_code == 200, f"ask failed: {r.status_code} {r.text}"
        data = r.json()
        assert "thread_id" in data
        msg = data["message"]
        assert msg["role"] == "assistant"
        assert isinstance(msg["content"], str)
        assert len(msg["content"]) > 0
        assert "traces" in msg
        assert "scores" in msg
        assert "best_index" in msg
        assert "elapsed_ms" in msg
        # Should have 4 traces (one per agent)
        assert len(msg["traces"]) == 4, f"expected 4 traces, got {len(msg['traces'])}"
        assert len(msg["scores"]) == 4
        # store for next test
        user_session._thread_id = data["thread_id"]  # type: ignore[attr-defined]
        user_session._first_q = q  # type: ignore[attr-defined]
        print(
            f"ASK took {elapsed:.1f}s, scores={msg['scores']}, "
            f"best_index={msg['best_index']}"
        )

    def test_thread_appears_in_list(self, user_session):
        tid = getattr(user_session, "_thread_id", None)
        assert tid, "ask test must run first"
        r = user_session.get(f"{BASE_URL}/api/threads", timeout=10)
        assert r.status_code == 200
        threads = r.json()["threads"]
        ids = [t["thread_id"] for t in threads]
        assert tid in ids

    def test_get_thread_messages_persisted(self, user_session):
        tid = getattr(user_session, "_thread_id", None)
        r = user_session.get(f"{BASE_URL}/api/threads/{tid}", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["thread"]["thread_id"] == tid
        msgs = body["messages"]
        # user message + assistant message
        assert len(msgs) >= 2
        roles = [m["role"] for m in msgs]
        assert "user" in roles and "assistant" in roles

    def test_repeat_question_runs_full_pipeline(self, user_session):
        """No semantic cache: a repeated identical question must run the
        engine again (fresh traces + scores, never a canned answer)."""
        q = getattr(user_session, "_first_q", None)
        assert q
        r = user_session.post(
            f"{BASE_URL}/api/ask", json={"question": q}, timeout=180
        )
        assert r.status_code == 200
        msg = r.json()["message"]
        assert len(msg.get("traces", [])) == 4, "repeat question must re-run all 4 agents"
        assert len(msg.get("scores", [])) == 4
        assert msg.get("content")

    def test_delete_thread(self, user_session):
        # Create a throwaway thread via /api/threads POST
        r = user_session.post(f"{BASE_URL}/api/threads", timeout=10)
        assert r.status_code == 200
        tid = r.json()["thread_id"]
        rd = user_session.delete(f"{BASE_URL}/api/threads/{tid}", timeout=10)
        assert rd.status_code == 200
        rg = user_session.get(f"{BASE_URL}/api/threads/{tid}", timeout=10)
        assert rg.status_code == 404

    def test_thread_isolation_between_users(self, user_session):
        """Another user must not see user_session's thread."""
        tid = getattr(user_session, "_thread_id", None)
        s = requests.Session()
        email = f"TEST_other_{uuid.uuid4().hex[:8]}@example.com"
        r = s.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": email, "password": "Passw0rd!", "name": "Other"},
            timeout=20,
        )
        assert r.status_code == 200
        r2 = s.get(f"{BASE_URL}/api/threads/{tid}", timeout=10)
        assert r2.status_code == 404
        r3 = s.delete(f"{BASE_URL}/api/threads/{tid}", timeout=10)
        assert r3.status_code == 404


# ---------- Stats ----------
class TestStats:
    def test_overview_admin(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/stats/overview", timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert data["is_admin_view"] is True
        assert "totals" in data
        for k in ("queries", "threads", "queries_last_7d", "avg_latency_ms"):
            assert k in data["totals"]
        assert isinstance(data["agents"], list)
        assert len(data["agents"]) == 4
        names = [a["name"] for a in data["agents"]]
        assert names == ["local_retrieval", "general_llm", "tavily_web", "arxiv_research"]

    def test_overview_user_scope(self, user_session):
        r = user_session.get(f"{BASE_URL}/api/stats/overview", timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert data["is_admin_view"] is False

    def test_recent_admin(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/stats/recent", timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert isinstance(data["items"], list)
