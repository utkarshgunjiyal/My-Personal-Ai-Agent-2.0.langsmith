"""Backend tests for file-upload + RAG integration.

Covers:
  - Auth (login as seeded admin)
  - POST /api/uploads (text, pdf, image vision)
  - GET  /api/uploads?thread_id=
  - DELETE /api/uploads/{file_id}
  - Negative cases: unsupported mime (415), oversize (413)
  - RAG: /api/ask/stream uses uploaded content + emits 'uploads_used'
  - Thread deletion cascades to uploaded_files + thread_documents
"""
import io
import os
import re
import uuid

import pytest
import requests
from PIL import Image, ImageDraw, ImageFont

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin@decision-engine.dev"
ADMIN_PASSWORD = "admin123"


# ------------------------- Fixtures -------------------------
@pytest.fixture(scope="session")
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


@pytest.fixture(scope="session")
def created_threads():
    return []


# ------------------------- Helpers -------------------------
def _make_pdf(text: str) -> bytes:
    """Tiny one-page PDF with given text."""
    from pypdf import PdfWriter
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Helvetica", 14)
    y = 750
    for line in text.split("\n"):
        c.drawString(72, y, line)
        y -= 18
    c.showPage()
    c.save()
    return buf.getvalue()


def _make_jpeg() -> bytes:
    """A non-blank JPEG with shapes + text (vision-compatible)."""
    img = Image.new("RGB", (640, 360), (240, 245, 255))
    d = ImageDraw.Draw(img)
    # Shapes
    d.rectangle([40, 40, 200, 160], fill=(220, 70, 70), outline=(20, 20, 20), width=3)
    d.ellipse([240, 60, 380, 200], fill=(70, 160, 220), outline=(20, 20, 20), width=3)
    d.polygon([(440, 60), (520, 60), (480, 180)], fill=(70, 200, 120), outline=(20, 20, 20))
    # Text
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
    except Exception:
        font = ImageFont.load_default()
    d.text((40, 220), "PROJECT HELIOS", fill=(20, 20, 20), font=font)
    d.text((40, 270), "Token: BANANA-9472", fill=(20, 20, 80), font=font)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88)
    return out.getvalue()


# ------------------------- Tests -------------------------
class TestAuth:
    def test_login_ok(self, session):
        r = session.get(f"{BASE_URL}/api/auth/me", timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("email") == ADMIN_EMAIL


class TestUploads:
    def test_upload_text_autocreates_thread(self, session, created_threads):
        content = (
            "My secret token is BANANA-PHONE-9472. "
            "The project is named Project Helios. "
            "It launches in February 2026."
        ).encode()
        files = {"file": ("secret_notes.txt", content, "text/plain")}
        r = session.post(f"{BASE_URL}/api/uploads", files=files, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kind"] == "text"
        assert body["chunk_count"] >= 1
        assert body["thread_id"].startswith("thr_")
        assert body["file_id"].startswith("file_")
        created_threads.append(body["thread_id"])
        # Stash for downstream tests via pytest namespace
        pytest.text_thread_id = body["thread_id"]
        pytest.text_file_id = body["file_id"]

    def test_list_uploads(self, session):
        thr = pytest.text_thread_id
        r = session.get(f"{BASE_URL}/api/uploads", params={"thread_id": thr}, timeout=15)
        assert r.status_code == 200
        files = r.json()["files"]
        assert any(f["file_id"] == pytest.text_file_id for f in files)
        f = next(f for f in files if f["file_id"] == pytest.text_file_id)
        assert f["filename"] == "secret_notes.txt"
        assert f["kind"] == "text"
        assert f["chunk_count"] >= 1

    def test_upload_pdf(self, session):
        thr = pytest.text_thread_id
        pdf_bytes = _make_pdf(
            "QuantumWidget Alpha\n"
            "Codename: NEBULA-OMEGA-2025.\n"
            "It has three modes: idle, active, and hyperdrive."
        )
        files = {"file": ("notes.pdf", pdf_bytes, "application/pdf")}
        data = {"thread_id": thr}
        r = session.post(f"{BASE_URL}/api/uploads", files=files, data=data, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kind"] == "pdf"
        assert body["chunk_count"] >= 1
        assert body["thread_id"] == thr

    def test_upload_image_vision(self, session):
        thr = pytest.text_thread_id
        jpeg = _make_jpeg()
        files = {"file": ("chart.jpg", jpeg, "image/jpeg")}
        data = {"thread_id": thr}
        # Vision may be slow
        r = session.post(f"{BASE_URL}/api/uploads", files=files, data=data, timeout=120)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kind"] == "image"
        assert body["chunk_count"] >= 1
        desc = body.get("description") or ""
        assert isinstance(desc, str) and len(desc) > 20, f"empty/weak desc: {desc!r}"
        assert not desc.startswith("[Vision unavailable"), desc

    def test_unsupported_mime_415(self, session):
        files = {"file": ("trojan.exe", b"MZ\x90\x00binarydata", "application/x-msdownload")}
        r = session.post(f"{BASE_URL}/api/uploads", files=files, timeout=30)
        assert r.status_code == 415, f"{r.status_code} {r.text[:200]}"

    def test_oversize_413(self, session):
        big = b"A" * (16 * 1024 * 1024)  # 16 MB
        files = {"file": ("big.txt", big, "text/plain")}
        r = session.post(f"{BASE_URL}/api/uploads", files=files, timeout=120)
        assert r.status_code == 413, f"{r.status_code} {r.text[:200]}"


class TestRAGIntegration:
    def test_stream_with_uploads(self, session):
        thr = pytest.text_thread_id
        payload = {
            "question": "What is the secret token in my uploaded file?",
            "thread_id": thr,
        }
        with session.post(
            f"{BASE_URL}/api/ask/stream",
            json=payload,
            stream=True,
            timeout=180,
        ) as r:
            assert r.status_code == 200, r.text[:300]
            saw_uploads = False
            saw_agent_start = False
            saw_done = False
            final_answer = ""
            uploads_before_agent = False
            current_event = None
            for raw in r.iter_lines(decode_unicode=True):
                if raw is None:
                    continue
                line = raw
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                    if current_event == "uploads_used":
                        saw_uploads = True
                        if not saw_agent_start:
                            uploads_before_agent = True
                    if current_event == "agent_start":
                        saw_agent_start = True
                elif line.startswith("data:"):
                    data = line[5:].strip()
                    if current_event == "done":
                        saw_done = True
                        import json as _json
                        try:
                            d = _json.loads(data)
                            final_answer = d.get("final_answer", "")
                        except Exception:
                            pass
            assert saw_uploads, "expected uploads_used SSE event"
            assert uploads_before_agent, "uploads_used should fire before agent_start"
            assert saw_done, "stream did not complete"
            assert re.search(r"BANANA[\-\s]?PHONE[\-\s]?9472", final_answer, re.I), (
                f"final answer missing token: {final_answer[:400]}"
            )

    def test_delete_upload_removes_chunks(self, session):
        # Create then delete a one-off text file
        files = {"file": ("ephemeral.txt", b"ephemeral content for deletion test", "text/plain")}
        data = {"thread_id": pytest.text_thread_id}
        r = session.post(f"{BASE_URL}/api/uploads", files=files, data=data, timeout=30)
        assert r.status_code == 200
        fid = r.json()["file_id"]
        d = session.delete(f"{BASE_URL}/api/uploads/{fid}", timeout=15)
        assert d.status_code == 200, d.text
        assert d.json().get("ok") is True
        # Verify it's gone from list
        lst = session.get(
            f"{BASE_URL}/api/uploads",
            params={"thread_id": pytest.text_thread_id},
            timeout=15,
        ).json()
        assert not any(f["file_id"] == fid for f in lst["files"])

    def test_thread_delete_cascades(self, session, created_threads):
        # Create a fresh thread with an upload
        files = {"file": ("cascade.txt", b"cascade test content", "text/plain")}
        r = session.post(f"{BASE_URL}/api/uploads", files=files, timeout=30)
        assert r.status_code == 200
        thr = r.json()["thread_id"]
        # Delete thread
        d = session.delete(f"{BASE_URL}/api/threads/{thr}", timeout=15)
        assert d.status_code == 200, d.text
        # GET /api/uploads should return empty list (thread is gone, but endpoint
        # filters by thread_id+user_id so returns empty)
        lst = session.get(
            f"{BASE_URL}/api/uploads", params={"thread_id": thr}, timeout=15
        ).json()
        assert lst["files"] == []


class TestStreamWithoutUploads:
    def test_stream_no_uploads_existing_thread(self, session):
        # Create a brand-new thread by streaming without uploads
        payload = {"question": "Briefly: what is 2+2?"}
        events_seen = set()
        with session.post(
            f"{BASE_URL}/api/ask/stream", json=payload, stream=True, timeout=180
        ) as r:
            assert r.status_code == 200
            for line in r.iter_lines(decode_unicode=True):
                if line and line.startswith("event:"):
                    events_seen.add(line.split(":", 1)[1].strip())
        # Existing flows still work; uploads_used must NOT fire on a thread with no uploads
        assert "agent_start" in events_seen
        assert "agent_complete" in events_seen
        assert "judge_scores" in events_seen
        assert "done" in events_seen
        assert "uploads_used" not in events_seen
