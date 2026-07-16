"""Tests for the new /api/ask/stream SSE endpoint and regression on /api/ask."""
import json
import os
import uuid

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

ADMIN_EMAIL = "admin@decision-engine.dev"
ADMIN_PASSWORD = "admin123"


def parse_sse_stream(resp):
    """Yield (event, data_dict_or_str) tuples from an SSE response."""
    buf = ""
    for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
        if chunk is None:
            continue
        buf += chunk
        while "\n\n" in buf:
            raw, buf = buf.split("\n\n", 1)
            event = "message"
            data_lines = []
            for line in raw.split("\n"):
                if line.startswith("event: "):
                    event = line[7:].strip()
                elif line.startswith("data: "):
                    data_lines.append(line[6:])
            if not data_lines:
                continue
            data_str = "\n".join(data_lines)
            try:
                data = json.loads(data_str)
            except Exception:
                data = data_str
            yield event, data


@pytest.fixture(scope="module")
def user_session():
    s = requests.Session()
    email = f"test_stream_{uuid.uuid4().hex[:8]}@example.com"
    r = s.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": "Passw0rd!", "name": "Stream Tester"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    return s


# ---------- Auth gating ----------
class TestStreamAuthGating:
    def test_stream_requires_auth(self):
        r = requests.post(
            f"{BASE_URL}/api/ask/stream",
            json={"question": "hi"},
            stream=True,
            timeout=15,
        )
        assert r.status_code == 401, f"expected 401, got {r.status_code}"


# ---------- Streaming flow ----------
class TestStreamFlow:
    def test_full_stream_events_in_order(self, user_session):
        unique_q = f"What is RAG in AI? (stream-test-{uuid.uuid4().hex[:6]})"
        r = user_session.post(
            f"{BASE_URL}/api/ask/stream",
            json={"question": unique_q, "thread_id": None},
            stream=True,
            timeout=120,
        )
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("Content-Type", "")

        events = []
        thread_id = None
        message_id = None
        agent_starts = 0
        agent_completes = 0
        refine_tokens = 0
        judge_scores = None
        done_payload = None
        for event, data in parse_sse_stream(r):
            events.append(event)
            if event == "thread":
                thread_id = data["thread_id"]
            elif event == "agent_start":
                agent_starts += 1
            elif event == "agent_complete":
                agent_completes += 1
            elif event == "judge_scores":
                judge_scores = data
            elif event == "refine_token":
                refine_tokens += 1
            elif event == "done":
                done_payload = data
                message_id = data.get("message_id")
                break
            elif event == "error":
                pytest.fail(f"stream errored: {data}")

        # Order/structural assertions
        assert events[0] == "thread", f"first event must be 'thread', got {events[:3]}"
        assert agent_starts == 4, f"expected 4 agent_start, got {agent_starts}"
        assert agent_completes == 4, f"expected 4 agent_complete, got {agent_completes}"
        assert judge_scores is not None and len(judge_scores["scores"]) == 4
        assert refine_tokens >= 1, "expected at least one refine_token"
        assert done_payload is not None
        assert done_payload["thread_id"] == thread_id
        assert done_payload["final_answer"]
        assert len(done_payload["traces"]) == 4

        # Persistence verification (GET thread)
        gr = user_session.get(f"{BASE_URL}/api/threads/{thread_id}", timeout=20)
        assert gr.status_code == 200
        body = gr.json()
        msgs = body["messages"]
        assert any(m["message_id"] == message_id for m in msgs)
        asst = next(m for m in msgs if m["message_id"] == message_id)
        assert asst["role"] == "assistant"
        assert len(asst.get("traces", [])) == 4
        assert len(asst.get("scores", [])) == 4
        assert asst.get("best_index") in [0, 1, 2, 3]
        assert asst.get("elapsed_ms", 0) > 0

        # Save for the repeat-question test on same session/thread
        TestStreamFlow._repeat_q = unique_q  # type: ignore[attr-defined]
        TestStreamFlow._thread = thread_id  # type: ignore[attr-defined]

    def test_repeat_question_runs_engine_again(self, user_session):
        """No semantic cache: repeating the exact same question must run the
        full agent pipeline again instead of returning a canned answer."""
        q = getattr(TestStreamFlow, "_repeat_q", None)
        tid = getattr(TestStreamFlow, "_thread", None)
        assert q and tid, "depends on first test"

        r = user_session.post(
            f"{BASE_URL}/api/ask/stream",
            json={"question": q, "thread_id": tid},
            stream=True,
            timeout=120,
        )
        assert r.status_code == 200

        events = []
        done_payload = None
        for event, data in parse_sse_stream(r):
            events.append(event)
            if event == "done":
                done_payload = data
                break
            elif event == "error":
                pytest.fail(f"repeat stream errored: {data}")

        # The engine must actually run: agents, judge and refiner all fire.
        for required in ("agent_start", "agent_complete", "judge_scores", "refine_token"):
            assert required in events, f"repeat question must emit {required}, got {events}"
        assert done_payload is not None
        assert done_payload.get("final_answer")
        assert len(done_payload.get("traces", [])) == 4


# ---------- Regression: non-streaming /api/ask still works ----------
class TestNonStreamRegression:
    def test_non_stream_ask_still_works(self, user_session):
        r = user_session.post(
            f"{BASE_URL}/api/ask",
            json={"question": f"Regression test: {uuid.uuid4().hex[:6]} - what is BM25?"},
            timeout=120,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "thread_id" in data
        msg = data.get("message") or data
        assert msg.get("content"), f"missing content in {data}"
        assert len(msg.get("traces", [])) == 4
        assert len(msg.get("scores", [])) == 4
