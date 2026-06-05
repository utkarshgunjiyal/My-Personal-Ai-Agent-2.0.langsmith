"""File upload routes: PDF, text, and image uploads tied to a chat thread.

Uploaded files are parsed for text (images use vision LLM for description),
chunked, and persisted into `thread_documents` so the retrieval pipeline can
ground the user's questions in their own files.
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from auth.deps import get_current_user
from db import get_db
from uploads.extractors import ALLOWED_MIME, classify, extract

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
    description: str | None = None
    created_at: datetime


async def _ensure_thread(db, user_id: str, thread_id: str | None, filename: str) -> tuple[str, bool]:
    """Return (thread_id, was_created)."""
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
            status_code=413, detail=f"File too large (max {MAX_FILE_SIZE // (1024 * 1024)} MB)"
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

    # Persist file metadata
    await db.uploaded_files.insert_one(
        {
            "file_id": file_id,
            "thread_id": thread_id,
            "user_id": user_id,
            "filename": file.filename or "upload",
            "mime_type": mime,
            "size": size,
            "kind": result["kind"],
            "description": result.get("description") or None,
            "chunk_count": len(result["chunks"]),
            "created_at": now,
        }
    )

    # Persist chunks for retrieval
    if result["chunks"]:
        chunk_docs = [
            {
                "doc_id": f"doc_{uuid.uuid4().hex[:14]}",
                "file_id": file_id,
                "thread_id": thread_id,
                "user_id": user_id,
                "filename": file.filename or "upload",
                "chunk_index": idx,
                "content": chunk,
                "kind": result["kind"],
                "created_at": now,
            }
            for idx, chunk in enumerate(result["chunks"])
        ]
        await db.thread_documents.insert_many(chunk_docs)

    return UploadOut(
        file_id=file_id,
        thread_id=thread_id,
        filename=file.filename or "upload",
        mime_type=mime,
        size=size,
        kind=result["kind"],
        chunk_count=len(result["chunks"]),
        description=(result.get("description") or None),
        created_at=now,
    )


@router.get("")
async def list_uploads(thread_id: str, user=Depends(get_current_user)):
    db = get_db()
    cursor = db.uploaded_files.find(
        {"thread_id": thread_id, "user_id": user["user_id"]},
        {"_id": 0},
    ).sort("created_at", 1)
    files = await cursor.to_list(length=200)
    return {"files": files}


@router.delete("/{file_id}")
async def delete_upload(file_id: str, user=Depends(get_current_user)):
    db = get_db()
    res = await db.uploaded_files.delete_one(
        {"file_id": file_id, "user_id": user["user_id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="File not found")
    await db.thread_documents.delete_many(
        {"file_id": file_id, "user_id": user["user_id"]}
    )
    return {"ok": True}
