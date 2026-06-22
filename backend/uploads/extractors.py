"""Extract searchable text from uploaded files (PDF, plain text, images).

PDF strategy:
    1. Try text extraction via pypdf per page.
    2. If a page yields < OCR_THRESHOLD chars of text, render that page with
       pdf2image and OCR it via Tesseract (`pytesseract`).
    3. Emit page-aware chunks: `{content, page, source}`.

Image strategy:
    1. Run Tesseract OCR for any embedded text.
    2. Run vision LLM (gpt-4o) for visual description.
    3. Combine into a single dense document.
"""
import asyncio
import base64
import io
import logging
import os
import re
from typing import Tuple

from PIL import Image
from openai import AsyncOpenAI

log = logging.getLogger("uploads.extractors")

# ---- Constants ----
TEXT_MIME_TYPES = {
    "text/plain", "text/markdown", "text/csv", "text/x-python", "text/html",
    "application/json", "application/xml",
}
PDF_MIME_TYPES = {"application/pdf"}
IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}

ALLOWED_MIME = TEXT_MIME_TYPES | PDF_MIME_TYPES | IMAGE_MIME_TYPES

CHUNK_SIZE = 900
CHUNK_OVERLAP = 150
OCR_THRESHOLD = 30  # if a page yields < this many chars, treat as scanned and OCR


def classify(mime: str, filename: str) -> str:
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
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    i = 0
    while i < len(text):
        end = min(i + size, len(text))
        if end < len(text):
            window = text.rfind(". ", i + size // 2, end)
            if window != -1:
                end = window + 1
        chunks.append(text[i:end].strip())
        if end >= len(text):
            break
        i = max(end - overlap, i + 1)
    return [c for c in chunks if c]


# ---- OCR helpers ----
def _ocr_image(img: Image.Image) -> str:
    """Run Tesseract on a PIL image. Returns empty string on any failure."""
    try:
        import pytesseract
        return (pytesseract.image_to_string(img) or "").strip()
    except Exception as e:
        log.warning("Tesseract OCR failed: %s", e)
        return ""


# ---- PDF (with selective OCR for scanned pages) ----
def _extract_pdf_pages(data: bytes) -> list[dict]:
    """Return [{page, text, source}] for every page (1-indexed)."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages: list[dict] = []

    # Lazy-import for OCR
    rendered = None
    for i, page in enumerate(reader.pages):
        page_num = i + 1
        try:
            t = (page.extract_text() or "").strip()
        except Exception as e:  # pragma: no cover
            log.warning("PDF page %d text extract failed: %s", page_num, e)
            t = ""

        if len(t) >= OCR_THRESHOLD:
            pages.append({"page": page_num, "text": t, "source": "text"})
            continue

        # Render this page and OCR it.
        try:
            if rendered is None:
                from pdf2image import convert_from_bytes
                rendered = convert_from_bytes(data, dpi=200)
            if 0 <= i < len(rendered):
                ocr_text = _ocr_image(rendered[i])
            else:
                ocr_text = ""
        except Exception as e:
            log.warning("PDF page %d OCR pipeline failed: %s", page_num, e)
            ocr_text = ""

        if ocr_text:
            pages.append({"page": page_num, "text": ocr_text, "source": "ocr"})
        elif t:
            pages.append({"page": page_num, "text": t, "source": "text"})
        else:
            pages.append({"page": page_num, "text": "", "source": "empty"})

    return pages


# ---- Text ----
def extract_text_text(data: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# ---- Image (OCR + vision) ----
def _normalize_image(data: bytes, mime: str) -> Tuple[bytes, str, Image.Image]:
    img = Image.open(io.BytesIO(data))
    if getattr(img, "is_animated", False):
        img.seek(0)
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    max_side = 1600
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / float(max(w, h))
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue(), "image/jpeg", img


async def describe_image(data: bytes, mime: str, filename: str) -> dict:
    """Return {'description': str, 'ocr': str} via vision LLM + Tesseract."""
    bytes_norm, _, pil_img = _normalize_image(data, mime)

    # OCR runs locally and is fast; do it in parallel with vision.
    ocr_task = asyncio.to_thread(_ocr_image, pil_img)

    b64 = base64.b64encode(bytes_norm).decode("ascii")
    model = os.environ.get("VISION_MODEL", "gpt-4o-mini")
    data_url = f"data:image/jpeg;base64,{b64}"

    description = ""
    try:
        client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a vision assistant. Given an image, produce a thorough, factual "
                        "description suitable for search/retrieval. Include: (1) what the image shows "
                        "(scene, objects, people, layout), (2) any visible text transcribed verbatim, "
                        "(3) charts/tables: report data points, axes, labels. Be specific. No commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Filename: {filename}\n\n"
                                "Describe this image in detail and transcribe any visible text. "
                                "Return a single dense paragraph (no markdown headings)."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        )
        description = (response.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("Vision describe failed")
        description = f"[Vision unavailable: {str(e)[:160]}]"

    ocr = (await ocr_task).strip()
    return {"description": description, "ocr": ocr}


async def extract(filename: str, mime: str, data: bytes) -> dict:
    """Top-level dispatch.

    Returns:
        {
            kind: 'pdf' | 'image' | 'text',
            text: full extracted text (string),
            chunks: [ {content, page, source} ],   # page=None for text/image
            description: image-only summary string,
            ocr_used: bool                          # any chunk came from OCR
        }
    """
    kind = classify(mime, filename)
    if kind == "unsupported":
        raise ValueError(f"Unsupported file type: {mime or filename}")

    ocr_used = False
    if kind == "pdf":
        pages = await asyncio.to_thread(_extract_pdf_pages, data)
        chunks: list[dict] = []
        full_parts: list[str] = []
        for p in pages:
            if not p["text"]:
                continue
            if p["source"] == "ocr":
                ocr_used = True
            full_parts.append(f"[Page {p['page']}] {p['text']}")
            for c in chunk_text(p["text"]):
                chunks.append({"content": c, "page": p["page"], "source": p["source"]})
        text = "\n\n".join(full_parts)
        return {
            "kind": "pdf",
            "text": text,
            "chunks": chunks,
            "description": "",
            "ocr_used": ocr_used,
        }

    if kind == "text":
        raw = extract_text_text(data)
        chunks = [{"content": c, "page": None, "source": "text"} for c in chunk_text(raw)]
        return {
            "kind": "text",
            "text": raw,
            "chunks": chunks,
            "description": "",
            "ocr_used": False,
        }

    # image
    res = await describe_image(data, mime, filename)
    description = res["description"]
    ocr = res["ocr"]
    # Be precise about which descriptions to drop: only those produced by the
    # vision-unavailable fallback (which start with this exact prefix).
    looks_error = description.startswith("[Vision unavailable")

    parts = []
    if not looks_error and description:
        parts.append(description)
    if ocr:
        ocr_used = True
        parts.append(f"\n\nText detected in image (OCR):\n{ocr}")
    combined = "\n".join(parts).strip()

    chunks = [
        {"content": c, "page": None, "source": "ocr+vision" if ocr_used else "vision"}
        for c in chunk_text(combined)
    ] if combined and not looks_error else []

    return {
        "kind": "image",
        "text": combined,
        "chunks": chunks,
        "description": description if not looks_error else "",
        "ocr_used": ocr_used,
    }
