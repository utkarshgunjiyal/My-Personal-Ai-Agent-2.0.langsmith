"""File upload routes: PDF (text + OCR), text, and image (vision + OCR)."""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

import vectorstore
from agents.llm import call_llm
from auth.deps import get_current_user
from db import get_db
from uploads.extractors import classify, extract

log = logging.getLogger("uploads")
router = APIRouter(prefix="/api/uploads", tags=["uploads"])

MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB


class UploadOut(BaseModel):
    file_id: str
    thread_id: str
    filename: str
    mime_type: str
    size: int
    kind: str
    chunk_count: int
    ocr_used: bool = False
    description: str | None = None
    created_at: datetime


async def _ensure_thread(db, user_id: str, thread_id: str | None, filename: str) -> tuple[str, bool]:
    if thread_id:
        t = await db.threads.find_one({"thread_id": thread_id, "user_id": user_id})
        if not t:
            raise HTTPException(status_code=404, detail="Thread not found")
        return thread_id, False
    new_id = f"thr_{uuid.uuid4().hex[:14]}"
    now = datetime.now(timezone.utc)
    await db.threads.insert_one(
        {
            "thread_id": new_id,
            "user_id": user_id,
            "title": f"📎 {filename[:48]}",
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
        }
    )
    return new_id, True


@router.post("", response_model=UploadOut)
async def upload_file(
    file: UploadFile = File(...),
    thread_id: str | None = Form(None),
    user=Depends(get_current_user),
):
    db = get_db()
    user_id = user["user_id"]

    data = await file.read()
    size = len(data)
    if size == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_FILE_SIZE // (1024 * 1024)} MB)",
        )

    mime = (file.content_type or "").lower()
    kind = classify(mime, file.filename or "")
    if kind == "unsupported":
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Supported: PDF, TXT/MD/CSV, PNG/JPEG/WEBP images.",
        )

    thread_id, _ = await _ensure_thread(db, user_id, thread_id, file.filename or "upload")

    try:
        result = await extract(file.filename or "upload", mime, data)
    except ValueError as e:
        raise HTTPException(status_code=415, detail=str(e))
    except Exception as e:
        log.exception("Extract failed")
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)[:200]}")

    file_id = f"file_{uuid.uuid4().hex[:14]}"
    now = datetime.now(timezone.utc)
    chunks = result["chunks"]
    ocr_used = bool(result.get("ocr_used"))

    await db.uploaded_files.insert_one(
        {
            "file_id": file_id,
            "thread_id": thread_id,
            "user_id": user_id,
            "filename": file.filename or "upload",
            "mime_type": mime,
            "size": size,
            "kind": result["kind"],
            "ocr_used": ocr_used,
            "description": result.get("description") or None,
            "chunk_count": len(chunks),
            "full_text": result.get("text", "")[:200_000],  # cap stored text
            "created_at": now,
        }
    )

    if chunks:
        chunk_docs = []
        doc_ids: list[str] = []
        texts: list[str] = []
        for idx, c in enumerate(chunks):
            doc_id = f"doc_{uuid.uuid4().hex[:14]}"
            chunk_docs.append(
                {
                    "doc_id": doc_id,
                    "file_id": file_id,
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "filename": file.filename or "upload",
                    "chunk_index": idx,
                    "content": c["content"],
                    "page": c.get("page"),
                    "source": c.get("source", "text"),
                    "kind": result["kind"],
                    "created_at": now,
                }
            )
            doc_ids.append(doc_id)
            texts.append(c["content"])
        await db.thread_documents.insert_many(chunk_docs)

        # Embed + persist into FAISS (best-effort: chunks are still usable for
        # BM25 even if FAISS write fails).
        try:
            await vectorstore.add_chunks(thread_id, doc_ids, texts)
        except Exception as e:
            log.exception("FAISS add failed for %s: %s", thread_id, e)

    return UploadOut(
        file_id=file_id,
        thread_id=thread_id,
        filename=file.filename or "upload",
        mime_type=mime,
        size=size,
        kind=result["kind"],
        chunk_count=len(chunks),
        ocr_used=ocr_used,
        description=(result.get("description") or None),
        created_at=now,
    )


@router.get("")
async def list_uploads(thread_id: str, user=Depends(get_current_user)):
    db = get_db()
    cursor = db.uploaded_files.find(
        {"thread_id": thread_id, "user_id": user["user_id"]},
        {"_id": 0, "full_text": 0},
    ).sort("created_at", 1)
    files = await cursor.to_list(length=200)
    return {"files": files}


@router.delete("/{file_id}")
async def delete_upload(file_id: str, user=Depends(get_current_user)):
    db = get_db()
    f = await db.uploaded_files.find_one(
        {"file_id": file_id, "user_id": user["user_id"]},
        {"_id": 0, "thread_id": 1},
    )
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    await db.uploaded_files.delete_one({"file_id": file_id, "user_id": user["user_id"]})
    await db.thread_documents.delete_many(
        {"file_id": file_id, "user_id": user["user_id"]}
    )
    # Rebuild the FAISS index for this thread without the deleted file's chunks
    try:
        await vectorstore.rebuild_for_thread(get_db(), f["thread_id"])
    except Exception as e:
        log.warning("FAISS rebuild after delete failed: %s", e)
    return {"ok": True}


class SummarizeOut(BaseModel):
    file_id: str
    summary: str


@router.post("/{file_id}/summarize", response_model=SummarizeOut)
async def summarize_upload(file_id: str, user=Depends(get_current_user)):
    db = get_db()
    f = await db.uploaded_files.find_one(
        {"file_id": file_id, "user_id": user["user_id"]},
        {"_id": 0},
    )
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    # Pull chunks (in order) to build the summarization prompt.
    cursor = db.thread_documents.find(
        {"file_id": file_id, "user_id": user["user_id"]},
        {"_id": 0, "content": 1, "chunk_index": 1},
    ).sort("chunk_index", 1)
    chunks = await cursor.to_list(length=2000)
    body = "\n\n".join(c["content"] for c in chunks)[:60_000]

    if not body and f.get("description"):
        body = f["description"]

    if not body:
        raise HTTPException(status_code=422, detail="No extractable content to summarize")

    system = (
        "You are a document summarizer. Produce a clean, useful summary that an "
        "engineer or analyst could act on. Use this exact structure (markdown):\n"
        "**TL;DR:** one sentence.\n"
        "**Key points:** 5 concise bullets.\n"
        "**Entities / numbers worth noting:** brief list (people, dates, $$).\n"
        "**Open questions / next actions:** 2-3 bullets, only if clearly implied.\n"
        "Do not invent content not present in the source."
    )
    prompt = f"Filename: {f.get('filename')}\n\nSource:\n{body}"
    try:
        summary = (await call_llm(system, prompt)).strip()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Summarizer unavailable: {str(e)[:200]}")

    await db.uploaded_files.update_one(
        {"file_id": file_id},
        {"$set": {"summary": summary, "summary_at": datetime.now(timezone.utc)}},
    )
    return SummarizeOut(file_id=file_id, summary=summary)
