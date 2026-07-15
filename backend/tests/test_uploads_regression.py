"""Regression tests for upload grounding and repeat-question behavior.

Covers:
  1) Upload-grounded answer regression: token must appear in final_answer,
     judge_scores.best_index must point to thread_files, uploads_used emitted.
  2) Repeating the same question on an upload thread must run the engine
     again and stay grounded in the uploaded content.
  3) The semantic cache was removed (it produced false hits on merely-similar
     questions): repeating an identical question on a no-upload thread must
     also re-run the full agent pipeline instead of returning a canned answer.
"""
import io
import json
import os
import re
import uuid

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin@decision-engine.dev"
ADMIN_PASSWORD = "admin123"


# ------------------------- Fixtures -------------------------
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code}: {r.text[:200]}")
    return s


# ------------------------- Helpers -------------------------
def _parse_sse(resp) -> list[tuple[str, dict | str]]:
    """Parse SSE stream into [(event_name, data_dict_or_str), ...]."""
    events: list[tuple[str, dict | str]] = []
    current_event = None
    for raw in resp.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        if raw.startswith("event:"):
            current_event = raw.split(":", 1)[1].strip()
        elif raw.startswith("data:"):
            data_str = raw[5:].strip()
            try:
                data = json.loads(data_str)
            except Exception:
                data = data_str
            events.append((current_event or "", data))
    return events


def _stream_ask(session, question: str, thread_id: str | None = None) -> list[tuple[str, dict | str]]:
    payload = {"question": question}
    if thread_id:
        payload["thread_id"] = thread_id
    with session.post(
        f"{BASE_URL}/api/ask/stream",
        json=payload,
        stream=True,
        timeout=240,
    ) as r:
        assert r.status_code == 200, r.text[:300]
        return _parse_sse(r)


def _get_event(events, name):
    for ev, data in events:
        if ev == name:
            return data
    return None


def _get_all_events(events, name):
    return [data for ev, data in events if ev == name]


# ------------------------- Tests -------------------------
class TestUploadGroundedAnswer:
    """Regression #1: token-grounded answer must surface in final_answer +
    judge picks thread_files + uploads_used emitted."""

    def test_token_in_final_answer_and_best_index_is_local(self, session):
        # Upload a unique-token file on a fresh thread
        unique_token = f"BANANA-PHONE-{uuid.uuid4().hex[:6].upper()}"
        content = (
            f"My secret token is {unique_token}. "
            "The project is named Project Helios. "
            "It launches in February 2026."
        ).encode()
        files = {"file": (f"secret_{uuid.uuid4().hex[:6]}.txt", content, "text/plain")}
        r = session.post(f"{BASE_URL}/api/uploads", files=files, timeout=60)
        assert r.status_code == 200, r.text
        thread_id = r.json()["thread_id"]

        # Ask the canonical question
        events = _stream_ask(
            session, "What is the secret token in my uploaded file?", thread_id
        )

        # uploads_used must fire before agent_start
        ev_names = [ev for ev, _ in events]
        assert "uploads_used" in ev_names, "uploads_used event missing"
        uploads_used = _get_event(events, "uploads_used")
        assert uploads_used and uploads_used.get("file_count", 0) >= 1

        # Order check
        first_uploads = ev_names.index("uploads_used")
        first_agent = ev_names.index("agent_start") if "agent_start" in ev_names else -1
        assert first_agent > first_uploads, "uploads_used must come before agent_start"

        # judge_scores best_index must point at the thread_files agent
        # (AI Mentor 2.0: user-uploaded files now have a dedicated agent, not local_retrieval).
        judge = _get_event(events, "judge_scores")
        assert judge is not None, "judge_scores event missing"
        agent_start_events = _get_all_events(events, "agent_start")
        target_idx = next(
            (e["index"] for e in agent_start_events if e.get("name") == "thread_files"),
            None,
        )
        assert target_idx is not None, "thread_files agent did not start (uploads not detected?)"
        assert judge["best_index"] == target_idx, (
            f"best_index={judge['best_index']} expected thread_files idx={target_idx}, "
            f"scores={judge.get('scores')}"
        )

        # done event final_answer must contain the unique token (case-insensitive,
        # allow any separators between segments)
        done = _get_event(events, "done")
        assert done is not None, "done event missing"
        final = done.get("final_answer", "") or ""
        # token has form X-Y-Z; check loosely
        parts = unique_token.split("-")
        pattern = r"[\-\s]?".join(re.escape(p) for p in parts)
        assert re.search(pattern, final, re.I), (
            f"final answer missing token {unique_token!r}: {final[:400]}"
        )


class TestRepeatQuestionOnUploadThread:
    """Regression #2: repeating an identical question on an upload thread
    must run the engine again and stay grounded in the uploaded content."""

    def test_repeat_question_stays_grounded(self, session):
        unique_token = f"NEBULA-OMEGA-{uuid.uuid4().hex[:6].upper()}"
        content = f"Codename {unique_token}. It has three modes.".encode()
        files = {"file": (f"codename_{uuid.uuid4().hex[:6]}.txt", content, "text/plain")}
        r = session.post(f"{BASE_URL}/api/uploads", files=files, timeout=60)
        assert r.status_code == 200, r.text
        thread_id = r.json()["thread_id"]

        q = "What codename does my uploaded file mention?"

        # First run
        ev1 = _stream_ask(session, q, thread_id)
        done1 = _get_event(ev1, "done")
        assert done1 is not None
        assert "uploads_used" in [e for e, _ in ev1]

        # Second run — same thread, same question; must run the engine again
        ev2 = _stream_ask(session, q, thread_id)
        done2 = _get_event(ev2, "done")
        assert done2 is not None
        assert "agent_start" in [e for e, _ in ev2], (
            "repeat question must re-run the agents"
        )
        assert "uploads_used" in [e for e, _ in ev2]
        # And the second answer must still be grounded
        final2 = done2.get("final_answer", "") or ""
        parts = unique_token.split("-")
        pattern = r"[\-\s]?".join(re.escape(p) for p in parts)
        assert re.search(pattern, final2, re.I), (
            f"second run lost grounding: {final2[:400]}"
        )


class TestRepeatQuestionAlwaysRunsEngine:
    """Regression #3: with the semantic cache removed, an identical repeat
    question (no uploads) must re-run the full pipeline — agents, judge and
    refiner all fire on both runs."""

    def test_repeat_question_runs_engine_twice(self, session):
        marker = uuid.uuid4().hex[:8]
        question = (
            f"Pretend ZX-{marker} is a fictional sorting algorithm I just invented. "
            "Give it a one-sentence definition."
        )
        ev1 = _stream_ask(session, question)
        done1 = _get_event(ev1, "done")
        assert done1 is not None
        assert "agent_start" in [e for e, _ in ev1]

        # Repeat on a fresh thread — must run the engine again, never a
        # canned answer.
        ev2 = _stream_ask(session, question)
        done2 = _get_event(ev2, "done")
        assert done2 is not None
        ev2_names = [e for e, _ in ev2]
        for required in ("agent_start", "agent_complete", "judge_scores", "refine_token"):
            assert required in ev2_names, (
                f"repeat question must emit {required}; got {ev2_names}"
            )
        assert done2.get("final_answer")
