"""Regression tests for iteration-4 CRITICAL bugs (judge mis-score + cache pollution).

Covers the spec from /app/test_reports/iteration_5 review_request:
  1) Upload-grounded answer regression: token must appear in final_answer,
     judge_scores.best_index must point to local_retrieval, uploads_used emitted.
  2) Semantic-cache must be skipped when thread has uploads. Repeating the same
     question on an upload thread should run the engine twice (cache_hit=false).
  3) Cross-thread cache isolation: an upload-bearing thread must not be served
     the cached answer from a no-upload thread.
  4) Existing /api/ask/stream without uploads still caches (miss then hit).
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
    judge picks local_retrieval + uploads_used emitted."""

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

        # judge_scores best_index must be local_retrieval (index 0 per AGENT_META)
        judge = _get_event(events, "judge_scores")
        assert judge is not None, "judge_scores event missing"
        # local_retrieval is the first agent in AGENT_META
        agent_start_events = _get_all_events(events, "agent_start")
        local_idx = next(
            (e["index"] for e in agent_start_events if e.get("name") == "local_retrieval"),
            0,
        )
        assert judge["best_index"] == local_idx, (
            f"best_index={judge['best_index']} expected local_retrieval idx={local_idx}, "
            f"scores={judge.get('scores')}"
        )

        # done event final_answer must contain the unique token (case-insensitive,
        # allow any separators between segments)
        done = _get_event(events, "done")
        assert done is not None, "done event missing"
        assert done.get("cache_hit") is False
        final = done.get("final_answer", "") or ""
        # token has form X-Y-Z; check loosely
        parts = unique_token.split("-")
        pattern = r"[\-\s]?".join(re.escape(p) for p in parts)
        assert re.search(pattern, final, re.I), (
            f"final answer missing token {unique_token!r}: {final[:400]}"
        )


class TestCacheSkippedOnUploadThread:
    """Regression #2: when thread has uploads, cache lookup MUST be skipped
    on every request, and cache.add() MUST be skipped, so repeated identical
    questions still run the engine."""

    def test_repeat_question_does_not_cache_on_upload_thread(self, session):
        unique_token = f"NEBULA-OMEGA-{uuid.uuid4().hex[:6].upper()}"
        content = f"Codename {unique_token}. It has three modes.".encode()
        files = {"file": (f"codename_{uuid.uuid4().hex[:6]}.txt", content, "text/plain")}
        r = session.post(f"{BASE_URL}/api/uploads", files=files, timeout=60)
        assert r.status_code == 200, r.text
        thread_id = r.json()["thread_id"]

        q = "What codename does my uploaded file mention?"

        # First run
        ev1 = _stream_ask(session, q, thread_id)
        cc1 = _get_event(ev1, "cache_check")
        done1 = _get_event(ev1, "done")
        assert cc1 is not None and cc1.get("hit") is False, f"cache_check1={cc1}"
        assert done1 is not None and done1.get("cache_hit") is False
        assert "uploads_used" in [e for e, _ in ev1]

        # Second run — same thread, same question; must STILL not hit cache
        ev2 = _stream_ask(session, q, thread_id)
        cc2 = _get_event(ev2, "cache_check")
        done2 = _get_event(ev2, "done")
        assert cc2 is not None and cc2.get("hit") is False, (
            f"cache should be skipped on upload thread, got cache_check={cc2}"
        )
        assert done2 is not None and done2.get("cache_hit") is False, (
            f"done.cache_hit must be false on upload thread; got {done2}"
        )
        assert "uploads_used" in [e for e, _ in ev2]
        # And the second answer must still be grounded
        final2 = done2.get("final_answer", "") or ""
        parts = unique_token.split("-")
        pattern = r"[\-\s]?".join(re.escape(p) for p in parts)
        assert re.search(pattern, final2, re.I), (
            f"second run lost grounding: {final2[:400]}"
        )


class TestCrossThreadCacheIsolation:
    """Regression #3: thread A (no uploads) caches its answer; thread B (with
    uploads) asking the SAME question must NOT be served the cached answer."""

    def test_upload_thread_does_not_consume_cache_from_no_upload_thread(self, session):
        question = "What is RAG in the context of large language models?"

        # Thread A: no uploads (new thread, auto-created)
        evA = _stream_ask(session, question)
        # Run again on the same thread to confirm cache works there
        threadA = _get_event(evA, "thread")["thread_id"]
        evA2 = _stream_ask(session, question, threadA)
        ccA2 = _get_event(evA2, "cache_check")
        # cache may or may not hit depending on semantic threshold; we don't
        # strictly require it. We only require that thread B is NOT served the
        # cached answer.

        # Thread B: upload a file whose content is DIFFERENT
        unique_token = f"HELIOS-{uuid.uuid4().hex[:6].upper()}"
        content = (
            f"This file is about acronym {unique_token}. Nothing to do with retrieval-augmented "
            "generation."
        ).encode()
        files = {"file": (f"helios_{uuid.uuid4().hex[:6]}.txt", content, "text/plain")}
        r = session.post(f"{BASE_URL}/api/uploads", files=files, timeout=60)
        assert r.status_code == 200
        threadB = r.json()["thread_id"]

        evB = _stream_ask(session, question, threadB)
        ccB = _get_event(evB, "cache_check")
        doneB = _get_event(evB, "done")
        assert ccB is not None and ccB.get("hit") is False, (
            f"thread B (with uploads) must skip cache; got {ccB}"
        )
        assert doneB is not None and doneB.get("cache_hit") is False
        assert "uploads_used" in [e for e, _ in evB]


class TestStreamWithoutUploadsCachesNormally:
    """Regression #4: existing flow without uploads — first run miss, second
    identical question on the same user should be cache_hit=true."""

    def test_no_uploads_cache_miss_then_hit(self, session):
        # Use a question phrased uniquely so we don't collide with prior cache
        marker = uuid.uuid4().hex[:6]
        question = f"Briefly, what does the acronym TST-{marker} mean in computing?"
        ev1 = _stream_ask(session, question)
        cc1 = _get_event(ev1, "cache_check")
        done1 = _get_event(ev1, "done")
        assert cc1 is not None and cc1.get("hit") is False
        assert done1 is not None and done1.get("cache_hit") is False

        # Repeat on a fresh thread (no uploads anywhere); should serve from cache
        ev2 = _stream_ask(session, question)
        cc2 = _get_event(ev2, "cache_check")
        done2 = _get_event(ev2, "done")
        # SemanticCache threshold = 0.72; exact-question repeat should hit
        assert cc2 is not None and cc2.get("hit") is True, (
            f"expected cache hit on identical question; got {cc2}"
        )
        assert done2 is not None and done2.get("cache_hit") is True
