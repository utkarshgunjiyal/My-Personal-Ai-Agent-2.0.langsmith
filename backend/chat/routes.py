"""Chat routes: threads, messages, ask."""
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agents.cache import SemanticCache
from agents.graph import run_engine
from auth.deps import get_current_user
from db import get_db

router = APIRouter(prefix="/api", tags=["chat"])


# In-process cache per user. Persistent via MongoDB hydration on access.
_user_caches: dict[str, SemanticCache] = {}


async def _get_user_cache(user_id: str) -> SemanticCache:
    if user_id not in _user_caches:
        cache = SemanticCache(threshold=0.72)
        await cache.hydrate(get_db(), user_id)
        _user_caches[user_id] = cache
    return _user_caches[user_id]


# ----- Schemas -----
class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None


class ThreadOut(BaseModel):
    thread_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


# ----- Routes -----
@router.get("/threads")
async def list_threads(user=Depends(get_current_user)):
    db = get_db()
    threads = (
        await db.threads.find({"user_id": user["user_id"]}, {"_id": 0})
        .sort("updated_at", -1)
        .to_list(length=200)
    )
    return {"threads": threads}


@router.post("/threads")
async def create_thread(user=Depends(get_current_user)):
    db = get_db()
    thread_id = f"thr_{uuid.uuid4().hex[:14]}"
    now = datetime.now(timezone.utc)
    doc = {
        "thread_id": thread_id,
        "user_id": user["user_id"],
        "title": "New conversation",
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
    }
    await db.threads.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: str, user=Depends(get_current_user)):
    db = get_db()
    thread = await db.threads.find_one(
        {"thread_id": thread_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    messages = (
        await db.messages.find({"thread_id": thread_id}, {"_id": 0})
        .sort("created_at", 1)
        .to_list(length=500)
    )
    return {"thread": thread, "messages": messages}


@router.delete("/threads/{thread_id}")
async def delete_thread(thread_id: str, user=Depends(get_current_user)):
    db = get_db()
    res = await db.threads.delete_one(
        {"thread_id": thread_id, "user_id": user["user_id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Thread not found")
    await db.messages.delete_many({"thread_id": thread_id})
    return {"ok": True}


@router.post("/ask")
async def ask(body: AskIn, user=Depends(get_current_user)):
    db = get_db()
    user_id = user["user_id"]
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    # Resolve / create thread
    thread_id = body.thread_id
    is_new_thread = False
    if thread_id:
        thread = await db.threads.find_one(
            {"thread_id": thread_id, "user_id": user_id}, {"_id": 0}
        )
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
    else:
        thread_id = f"thr_{uuid.uuid4().hex[:14]}"
        now = datetime.now(timezone.utc)
        await db.threads.insert_one(
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "title": question[:60] + ("…" if len(question) > 60 else ""),
                "created_at": now,
                "updated_at": now,
                "message_count": 0,
            }
        )
        is_new_thread = True

    # Persist user message
    user_msg_id = f"msg_{uuid.uuid4().hex[:14]}"
    now = datetime.now(timezone.utc)
    await db.messages.insert_one(
        {
            "message_id": user_msg_id,
            "thread_id": thread_id,
            "user_id": user_id,
            "role": "user",
            "content": question,
            "created_at": now,
        }
    )

    # Run engine
    cache = await _get_user_cache(user_id)
    started = time.perf_counter()
    result = await run_engine(
        question=question, user_id=user_id, thread_id=thread_id, cache=cache, db=db
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    # Persist assistant message
    asst_msg_id = f"msg_{uuid.uuid4().hex[:14]}"
    asst_doc = {
        "message_id": asst_msg_id,
        "thread_id": thread_id,
        "user_id": user_id,
        "role": "assistant",
        "content": result["final_answer"],
        "cache_hit": bool(result.get("cache_hit")),
        "cache_similarity": float(result.get("cache_similarity", 0.0)),
        "cached_question": result.get("cached_question"),
        "traces": result.get("traces", []),
        "scores": result.get("scores", []),
        "best_index": result.get("best_index", -1),
        "elapsed_ms": elapsed_ms,
        "created_at": datetime.now(timezone.utc),
    }
    await db.messages.insert_one(asst_doc)

    # Update thread metadata
    new_title_set = (
        {"title": question[:60] + ("…" if len(question) > 60 else "")}
        if is_new_thread
        else {}
    )
    await db.threads.update_one(
        {"thread_id": thread_id},
        {
            "$inc": {"message_count": 2},
            "$set": {"updated_at": datetime.now(timezone.utc), **new_title_set},
        },
    )

    # Persist agent run for stats
    await db.agent_runs.insert_one(
        {
            "user_id": user_id,
            "thread_id": thread_id,
            "question": question,
            "cache_hit": bool(result.get("cache_hit")),
            "scores": result.get("scores", []),
            "best_index": result.get("best_index", -1),
            "elapsed_ms": elapsed_ms,
            "created_at": datetime.now(timezone.utc),
        }
    )

    asst_doc.pop("_id", None)
    return {
        "thread_id": thread_id,
        "message": asst_doc,
    }
