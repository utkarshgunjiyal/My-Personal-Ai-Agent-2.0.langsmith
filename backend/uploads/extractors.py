"""Extract searchable text from uploaded files (PDF, plain text, images)."""
import asyncio
import base64
import io
import logging
import re
from typing import Tuple

from PIL import Image
from emergentintegrations.llm.chat import ImageContent, LlmChat, UserMessage
import os
import uuid

log = logging.getLogger("uploads.extractors")

# ---- Constants ----
TEXT_MIME_TYPES = {
    "text/plain", "text/markdown", "text/csv", "text/x-python", "text/html",
    "application/json", "application/xml",
}
PDF_MIME_TYPES = {"application/pdf"}
IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}

ALLOWED_MIME = TEXT_MIME_TYPES | PDF_MIME_TYPES | IMAGE_MIME_TYPES

# Max chunk size (chars) and overlap for retrieval
CHUNK_SIZE = 900
CHUNK_OVERLAP = 150


def classify(mime: str, filename: str) -> str:
    """Return one of 'pdf', 'image', 'text', or 'unsupported'."""
    mime = (mime or "").lower()
    if mime in PDF_MIME_TYPES or filename.lower().endswith(".pdf"):
        return "pdf"
    if mime in IMAGE_MIME_TYPES or filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        return "image"
    if mime in TEXT_MIME_TYPES or filename.lower().endswith(
        (".txt", ".md", ".markdown", ".csv", ".json", ".xml", ".html", ".py", ".js", ".ts")
    ):
        return "text"
    return "unsupported"


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Sentence-aware sliding-window chunking."""
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    i = 0
    while i < len(text):
        end = min(i + size, len(text))
        # try to extend to nearest sentence break
        if end < len(text):
            window = text.rfind(". ", i + size // 2, end)
            if window != -1:
                end = window + 1
        chunks.append(text[i:end].strip())
        if end >= len(text):
            break
        i = max(end - overlap, i + 1)
    return [c for c in chunks if c]


# ---- PDF ----
def extract_pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    for i, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ""
        except Exception as e:  # pragma: no cover
            log.warning("PDF page %d extract failed: %s", i, e)
            t = ""
        t = t.strip()
        if t:
            parts.append(f"[Page {i + 1}]\n{t}")
    return "\n\n".join(parts)


# ---- Text ----
def extract_text_text(data: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# ---- Image ----
def _normalize_image(data: bytes, mime: str) -> Tuple[bytes, str]:
    """Ensure PNG/JPEG/WEBP, RGB, max 1600px. Returns (bytes, normalized_mime)."""
    img = Image.open(io.BytesIO(data))
    # Animated (e.g. APNG) -> first frame
    if getattr(img, "is_animated", False):
        img.seek(0)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    elif img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    # Resize
    max_side = 1600
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / float(max(w, h))
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    fmt = "JPEG"
    out_mime = "image/jpeg"
    img.save(buf, format=fmt, quality=88)
    return buf.getvalue(), out_mime


async def describe_image(data: bytes, mime: str, filename: str) -> str:
    """Use a vision LLM to describe the image + transcribe any text in it.

    Returns a long descriptive paragraph suitable for retrieval.
    """
    normalized, _ = _normalize_image(data, mime)
    b64 = base64.b64encode(normalized).decode("ascii")
    model = os.environ.get("VISION_MODEL", "gpt-4o")
    provider = os.environ.get("VISION_PROVIDER", "openai")
    api_key = os.environ["EMERGENT_LLM_KEY"]
    chat = (
        LlmChat(
            api_key=api_key,
            session_id=f"vision-{uuid.uuid4().hex[:10]}",
            system_message=(
                "You are a vision assistant. Given an image, produce a thorough, factual "
                "description suitable for search/retrieval. Include: (1) what the image shows "
                "(scene, objects, people, layout), (2) ALL visible text transcribed verbatim, "
                "(3) charts/tables: report data points, axes, labels. Be specific. No commentary."
            ),
        )
        .with_model(provider, model)
    )
    image_content = ImageContent(image_base64=b64)
    user_msg = UserMessage(
        text=(
            f"Filename: {filename}\n\n"
            "Describe this image in detail and transcribe any visible text. "
            "Return a single dense paragraph (no markdown headings)."
        ),
        file_contents=[image_content],
    )
    try:
        response = await chat.send_message(user_msg)
        if isinstance(response, str):
            return response.strip()
        text = getattr(response, "text", None) or getattr(response, "content", None)
        return (text or str(response)).strip()
    except Exception as e:
        log.exception("Vision describe failed: %s", e)
        return f"[Vision unavailable: {str(e)[:160]}]"


async def extract(filename: str, mime: str, data: bytes) -> dict:
    """Top-level dispatch. Returns:
        {
            'kind': 'pdf'|'image'|'text',
            'text': full extracted text,
            'chunks': list[str],
            'description': str (images only, mirrors text)
        }
    Raises ValueError on unsupported.
    """
    kind = classify(mime, filename)
    if kind == "unsupported":
        raise ValueError(f"Unsupported file type: {mime or filename}")

    if kind == "pdf":
        text = await asyncio.to_thread(extract_pdf_text, data)
    elif kind == "text":
        text = extract_text_text(data)
    elif kind == "image":
        text = await describe_image(data, mime, filename)
    else:  # pragma: no cover
        raise ValueError(f"Unhandled kind: {kind}")

    text = (text or "").strip()
    # Don't index error/unavailable strings emitted by failed extractors
    looks_error = bool(text) and text.startswith("[") and (
        "error" in text.lower() or "unavailable" in text.lower()
    )
    chunks = chunk_text(text) if text and not looks_error else []
    return {
        "kind": kind,
        "text": text,
        "chunks": chunks,
        "description": text if kind == "image" else "",
    }
