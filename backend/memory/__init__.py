"""Rolling-summary based conversation memory per thread.

Three-tier memory composed at query time:
    long-term  → conversation summary (one row in `summaries`)
    short-term → last 5 messages
    document   → retrieved chunks (handled by retriever)

A summary is (re)generated every `SUMMARIZE_EVERY` assistant messages.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from agents.llm import call_llm

log = logging.getLogger("memory")

SHORT_TERM_WINDOW = int(os.environ.get("MEMORY_SHORT_TERM", "5"))
SUMMARIZE_EVERY = int(os.environ.get("MEMORY_SUMMARIZE_EVERY", "10"))


async def get_recent_messages(db, thread_id: str, limit: int = SHORT_TERM_WINDOW) -> list[dict]:
    """Return the most recent N messages in chronological order."""
    cursor = (
        db.messages.find(
            {"thread_id": thread_id},
            {"_id": 0, "role": 1, "content": 1, "created_at": 1},
        )
        .sort("created_at", -1)
        .limit(limit)
    )
    msgs = await cursor.to_list(length=limit)
    msgs.reverse()
    return msgs


async def get_summary(db, thread_id: str) -> str:
    doc = await db.summaries.find_one(
        {"thread_id": thread_id}, {"_id": 0, "summary": 1}
    )
    return (doc or {}).get("summary", "") if doc else ""


def format_history(msgs: list[dict]) -> str:
    if not msgs:
        return ""
    lines = []
    for m in msgs:
        role = m.get("role", "user").upper()
        content = (m.get("content") or "").strip()
        if not content:
            continue
        # Truncate any single message to keep prompt bounded
        if len(content) > 800:
            content = content[:800].rstrip() + "…"
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)


async def compose_context(db, thread_id: str) -> dict[str, str]:
    """Return {'summary': str, 'history': str} for the current thread."""
    summary = await get_summary(db, thread_id)
    recents = await get_recent_messages(db, thread_id)
    return {"summary": summary, "history": format_history(recents)}


async def maybe_update_summary(db, thread_id: str, message_count: int) -> bool:
    """If `message_count` crosses a SUMMARIZE_EVERY boundary, regenerate summary.

    Returns True if a summary was rewritten.
    """
    if message_count < SUMMARIZE_EVERY:
        return False
    if message_count % SUMMARIZE_EVERY != 0:
        return False

    # Pull a wider window for summarization (last 20 messages).
    msgs = await get_recent_messages(db, thread_id, limit=20)
    if not msgs:
        return False
    prior_summary = await get_summary(db, thread_id)

    system = (
        "You are a conversation memory summarizer. Produce a concise running summary "
        "of an ongoing chat between a user and an AI assistant. Capture: user goals, "
        "key facts established, names, numbers, decisions, open questions. Skip pleasantries. "
        "Output ONLY the new summary text (no headings, no preamble), max 180 words."
    )
    prompt = (
        f"PRIOR_SUMMARY:\n{prior_summary or '(none)'}\n\n"
        f"RECENT_MESSAGES:\n{format_history(msgs)}\n\n"
        "Write the updated running summary."
    )
    try:
        new_summary = (await call_llm(system, prompt)).strip()
    except Exception as e:
        log.warning("Summary regeneration failed: %s", e)
        return False

    await db.summaries.update_one(
        {"thread_id": thread_id},
        {
            "$set": {
                "summary": new_summary,
                "updated_at": datetime.now(timezone.utc),
                "message_count": message_count,
            }
        },
        upsert=True,
    )
    return True
