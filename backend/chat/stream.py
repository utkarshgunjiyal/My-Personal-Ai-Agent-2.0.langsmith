"""Streaming /api/ask/stream endpoint.

Emits Server-Sent Events for live UI updates:
    cache_check    {hit, similarity?, cached_question?}
    agent_start    {index, name, color}
    agent_complete {index, name, answer, elapsed_ms}
    judge_scores   {scores: number[], best_index}
    refine_token   {delta}
    done           {message_id, thread_id, elapsed_ms}
    error          {message}
"""
import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agents.cache import SemanticCache
from agents.external import arxiv_search_context, tavily_search_context
from agents.graph import AGENT_META, _is_error_trace
from agents.llm import call_llm, stream_llm
from agents.retrieval import HybridRetriever
from auth.deps import get_current_user
from db import get_db
from uploads.retriever import retrieve_thread_docs, format_docs_for_context

router = APIRouter(prefix="/api", tags=["chat-stream"])

_retriever = HybridRetriever()
_caches: dict[str, SemanticCache] = {}


async def _user_cache(user_id: str) -> SemanticCache:
    if user_id not in _caches:
        c = SemanticCache(threshold=0.72)
        await c.hydrate(get_db(), user_id)
        _caches[user_id] = c
    return _caches[user_id]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


class AskStreamIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None


AGENT_SYSTEMS = {
    "local_retrieval": (
        "You are a precise technical assistant. Answer using ONLY the local retrieved context. "
        "If the context is insufficient, say so explicitly. Be concise (4-8 sentences)."
    ),
    "general_llm": (
        "You are a knowledgeable AI assistant. Answer clearly and concisely (4-8 sentences). "
        "Avoid hedging; be specific."
    ),
    "tavily_web": (
        "You are a live-web research agent. Use the provided web search context to answer. "
        "If the context indicates web search is disabled or unavailable, state that clearly and "
        "fall back to general knowledge with a note."
    ),
    "arxiv_research": (
        "You are a research-paper analyst. Use the arXiv context to answer with a research lens. "
        "Cite paper titles when relevant. If no papers were retrieved, say so plainly."
    ),
}


async def _run_one_agent(
    index: int,
    name: str,
    color: str,
    system: str,
    prompt: str,
    context: str,
    queue: asyncio.Queue,
):
    """Push agent_start then run, then push agent_complete (with answer)."""
    await queue.put(_sse("agent_start", {"index": index, "name": name, "color": color}))
    started = time.perf_counter()
    try:
        answer = await call_llm(system, prompt)
    except Exception as e:
        msg = str(e)
        if "Budget" in msg or "budget" in msg:
            answer = f"[{name} unavailable: LLM provider budget exceeded.]"
        elif "rate" in msg.lower():
            answer = f"[{name} rate-limited.]"
        else:
            answer = f"[{name} error: {msg[:200]}]"
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    trace = {
        "name": name,
        "color": color,
        "answer": answer,
        "score": 0.0,
        "elapsed_ms": elapsed_ms,
        "context": context,
    }
    await queue.put(
        _sse(
            "agent_complete",
            {
                "index": index,
                "name": name,
                "answer": answer,
                "elapsed_ms": elapsed_ms,
                "color": color,
            },
        )
    )
    return trace


async def _score_trace(trace: dict, question: str, *, has_uploads: bool = False) -> float:
    if _is_error_trace(trace):
        return 0.0
    base_rules = (
        "You are a strict evaluator. Score the candidate answer from 0 to 10 based on: "
        "correctness, relevance, clarity, technical accuracy, and grounding in evidence. "
        "Penalize unsupported claims. "
        "Special rule: If the question mentions RAG and the answer interprets it as 'Red Amber Green', score below 3. "
        "If the question mentions RAG and the answer interprets it as 'Retrieval-Augmented Generation', score above 8. "
    )
    if has_uploads:
        base_rules += (
            "IMPORTANT: The user has uploaded their OWN documents to this thread. "
            "An answer that uses or quotes the user's uploaded content (e.g. cites a filename, "
            "transcribes a value from their file, or paraphrases an uploaded passage) MUST be "
            "scored 9 or 10 — that is the desired behavior. Do NOT penalise answers for "
            "revealing content from the user's own uploaded files; that content belongs to the user. "
            "Conversely, an answer that refuses or claims it 'cannot see the attachment' when the "
            "user clearly attached one MUST be scored 2 or below. "
        )
    system = base_rules + "Reply with ONLY a single number between 0 and 10. No other text."
    prompt = f"Question:\n{question}\n\nAnswer:\n{trace['answer']}"
    try:
        raw = await call_llm(system, prompt)
        m = re.search(r"-?\d+(?:\.\d+)?", raw)
        return max(0.0, min(10.0, float(m.group()))) if m else 0.0
    except Exception:
        n = len(trace["answer"])
        return max(3.0, min(7.0, 3.0 + (n / 600.0)))


async def _stream_engine(
    *, question: str, user_id: str, thread_id: str | None, request: Request
) -> AsyncIterator[bytes]:
    db = get_db()
    started_total = time.perf_counter()

    # --- Resolve / create thread ---
    is_new_thread = False
    if thread_id:
        thread = await db.threads.find_one({"thread_id": thread_id, "user_id": user_id})
        if not thread:
            yield _sse("error", {"message": "Thread not found"}).encode()
            return
    else:
        thread_id = f"thr_{uuid.uuid4().hex[:14]}"
        is_new_thread = True
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

    yield _sse("thread", {"thread_id": thread_id, "is_new": is_new_thread}).encode()

    # --- Persist user message ---
    user_msg_id = f"msg_{uuid.uuid4().hex[:14]}"
    await db.messages.insert_one(
        {
            "message_id": user_msg_id,
            "thread_id": thread_id,
            "user_id": user_id,
            "role": "user",
            "content": question,
            "created_at": datetime.now(timezone.utc),
        }
    )

    # --- Check semantic cache (skipped when thread has uploaded files, since
    # grounded answers depend on per-thread context and must not pollute the
    # per-user cache) ---
    upload_count = await db.uploaded_files.count_documents(
        {"thread_id": thread_id, "user_id": user_id}
    )
    cache = await _user_cache(user_id)
    hit = cache.search(question) if upload_count == 0 else None
    if hit:
        # Emit cache event + done; persist assistant message with cache hit.
        yield _sse(
            "cache_check",
            {
                "hit": True,
                "similarity": hit["similarity"],
                "matched_question": hit["matched_question"],
                "answer": hit["answer"],
            },
        ).encode()
        msg_id = f"msg_{uuid.uuid4().hex[:14]}"
        elapsed_ms = int((time.perf_counter() - started_total) * 1000)
        asst_doc = {
            "message_id": msg_id,
            "thread_id": thread_id,
            "user_id": user_id,
            "role": "assistant",
            "content": hit["answer"],
            "cache_hit": True,
            "cache_similarity": float(hit["similarity"]),
            "cached_question": hit["matched_question"],
            "traces": [],
            "scores": [],
            "best_index": -1,
            "elapsed_ms": elapsed_ms,
            "created_at": datetime.now(timezone.utc),
        }
        await db.messages.insert_one(asst_doc)
        await db.threads.update_one(
            {"thread_id": thread_id},
            {"$inc": {"message_count": 2}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        )
        await db.agent_runs.insert_one(
            {
                "user_id": user_id,
                "thread_id": thread_id,
                "question": question,
                "cache_hit": True,
                "scores": [],
                "best_index": -1,
                "elapsed_ms": elapsed_ms,
                "created_at": datetime.now(timezone.utc),
            }
        )
        yield _sse(
            "done",
            {
                "thread_id": thread_id,
                "message_id": msg_id,
                "elapsed_ms": elapsed_ms,
                "cache_hit": True,
                "cache_similarity": float(hit["similarity"]),
                "cached_question": hit["matched_question"],
                "final_answer": hit["answer"],
            },
        ).encode()
        return

    yield _sse("cache_check", {"hit": False}).encode()

    # --- Build agent contexts ---
    docs = _retriever.search(question)
    local_ctx = "\n".join(f"- {d.content}" for d in docs)

    # Per-thread uploaded-document retrieval (user's own PDFs / images / text)
    user_docs = await retrieve_thread_docs(
        db, thread_id=thread_id, user_id=user_id, query=question, top_k=4
    )
    user_ctx = format_docs_for_context(user_docs)
    has_uploads = upload_count > 0
    if user_ctx:
        local_ctx = f"=== Your Uploaded Documents ===\n{user_ctx}\n\n=== Built-in Knowledge Base ===\n{local_ctx}"

    web_ctx = await asyncio.to_thread(tavily_search_context, question, 3)
    arxiv_ctx = await asyncio.to_thread(arxiv_search_context, question, 3)

    local_system = AGENT_SYSTEMS["local_retrieval"]
    if user_ctx:
        local_system = (
            "You are a precise technical assistant. Answer using the provided context, "
            "PRIORITIZING the user's uploaded documents over the built-in knowledge base. "
            "Quote / cite filenames inline when you use them (e.g., '(per resume.pdf)'). "
            "If neither source is sufficient, say so explicitly. Be concise (4-8 sentences)."
        )

    contexts = {
        "local_retrieval": (f"Local Context:\n{local_ctx}\n\nQuestion: {question}", local_ctx),
        "general_llm": (f"Question: {question}", "(no external context)"),
        "tavily_web": (f"Web Context:\n{web_ctx}\n\nQuestion: {question}", web_ctx),
        "arxiv_research": (f"arXiv Context:\n{arxiv_ctx}\n\nQuestion: {question}", arxiv_ctx),
    }

    if upload_count > 0:
        yield _sse(
            "uploads_used",
            {"file_count": int(upload_count), "matched_chunks": len(user_docs)},
        ).encode()

    # --- Run agents concurrently, push events as each completes ---
    queue: asyncio.Queue = asyncio.Queue()
    agent_tasks: list[asyncio.Task] = []
    for idx, (name, color) in enumerate(AGENT_META):
        prompt, ctx = contexts[name]
        sys_prompt = local_system if name == "local_retrieval" else AGENT_SYSTEMS[name]
        agent_tasks.append(
            asyncio.create_task(
                _run_one_agent(idx, name, color, sys_prompt, prompt, ctx, queue)
            )
        )
    pending = set(agent_tasks)

    # Drain events from the queue as they arrive, finishing when all agent
    # tasks complete AND the queue is empty.
    async def event_pump():
        while True:
            # If all tasks done and queue empty, exit
            if all(t.done() for t in agent_tasks) and queue.empty():
                return
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=0.25)
                yield ev
            except asyncio.TimeoutError:
                continue

    async for ev in event_pump():
        yield ev.encode()

    traces = [t.result() for t in agent_tasks]

    # --- Score traces (judge) in parallel ---
    scores = await asyncio.gather(
        *(_score_trace(t, question, has_uploads=has_uploads) for t in traces)
    )
    for t, s in zip(traces, scores):
        t["score"] = float(s)
    best_index = int(max(range(len(scores)), key=lambda i: scores[i])) if scores else -1

    # Hard override: when the user has uploaded files AND the local_retrieval
    # agent actually grounded its answer in them, prefer it. This corrects for
    # LLM-judge bias against revealing content from user-owned uploads.
    if has_uploads and user_docs and traces:
        local_idx = next((i for i, t in enumerate(traces) if t.get("name") == "local_retrieval"), -1)
        if local_idx >= 0 and not _is_error_trace(traces[local_idx]):
            local_ans = (traces[local_idx].get("answer") or "").lower()
            # Heuristic: if the local agent's answer references a known uploaded
            # filename OR contains a substring from any retrieved chunk, prefer it.
            uploaded_filenames = {d.filename.lower() for d in user_docs}
            chunk_tokens = set()
            for d in user_docs:
                for tok in re.findall(r"[A-Za-z0-9_\-]{6,}", d.content):
                    chunk_tokens.add(tok.lower())
            grounded = (
                any(fn in local_ans for fn in uploaded_filenames)
                or any(tok in local_ans for tok in list(chunk_tokens)[:200])
            )
            if grounded:
                # Boost local score so the trace reflects the override too.
                scores = list(scores)
                scores[local_idx] = max(scores[local_idx], 9.5)
                traces[local_idx]["score"] = float(scores[local_idx])
                best_index = local_idx

    yield _sse(
        "judge_scores",
        {"scores": [float(s) for s in scores], "best_index": best_index},
    ).encode()

    # --- Refine (streamed) ---
    candidates = "\n\n".join(
        f"=== Agent {i + 1} ({t['name']}, score={t['score']}) ===\n{t['answer']}"
        for i, t in enumerate(traces)
    )
    refine_system = (
        "You are the final answer refiner for a multi-agent AI system. "
        "Synthesize a single, definitive answer that is technically accurate, clear and concise. "
        "Prefer the best-scored answer's content, but incorporate useful detail from others. "
        "Do not include unsupported claims. Do not mention the agents."
    )
    if has_uploads:
        refine_system += (
            " The user has uploaded their own documents to this thread; their content "
            "is reproduced in the candidate answers and belongs to the user. You MUST "
            "faithfully include any specific values (names, tokens, numbers, quotes) that "
            "appear in the best candidate's grounded answer — do NOT refuse, redact, or "
            "claim the attachment cannot be seen."
        )
    best_answer = traces[best_index]["answer"] if best_index >= 0 else ""
    refine_prompt = (
        f"Question:\n{question}\n\nCandidate Answers:\n{candidates}\n\n"
        f"Best (selected by judge):\n{best_answer}\n\nProduce the final answer."
    )

    final_text_parts: list[str] = []
    try:
        async for delta in stream_llm(refine_system, refine_prompt):
            final_text_parts.append(delta)
            yield _sse("refine_token", {"delta": delta}).encode()
    except Exception as e:
        # Fallback: pick best non-error candidate
        non_err = [t for t in traces if not _is_error_trace(t)]
        if non_err:
            non_err.sort(key=lambda t: t.get("score", 0), reverse=True)
            fallback = non_err[0]["answer"]
        else:
            fallback = f"[Refiner unavailable: {str(e)[:160]}]"
        final_text_parts = [fallback]
        yield _sse("refine_token", {"delta": fallback}).encode()

    final_answer = "".join(final_text_parts).strip()

    # --- Persist assistant message + cache + agent_run ---
    elapsed_ms = int((time.perf_counter() - started_total) * 1000)
    msg_id = f"msg_{uuid.uuid4().hex[:14]}"
    asst_doc = {
        "message_id": msg_id,
        "thread_id": thread_id,
        "user_id": user_id,
        "role": "assistant",
        "content": final_answer,
        "cache_hit": False,
        "cache_similarity": 0.0,
        "cached_question": None,
        "traces": traces,
        "scores": [float(s) for s in scores],
        "best_index": best_index,
        "elapsed_ms": elapsed_ms,
        "created_at": datetime.now(timezone.utc),
    }
    await db.messages.insert_one(asst_doc)
    # Skip cross-thread semantic cache when the answer depends on the user's
    # per-thread uploaded documents — caching would serve the wrong answer
    # in other threads (or after the user removes the file).
    if not has_uploads:
        await cache.add(db, user_id, question, final_answer)
    await db.threads.update_one(
        {"thread_id": thread_id},
        {"$inc": {"message_count": 2}, "$set": {"updated_at": datetime.now(timezone.utc)}},
    )
    await db.agent_runs.insert_one(
        {
            "user_id": user_id,
            "thread_id": thread_id,
            "question": question,
            "cache_hit": False,
            "scores": [float(s) for s in scores],
            "best_index": best_index,
            "elapsed_ms": elapsed_ms,
            "created_at": datetime.now(timezone.utc),
        }
    )

    yield _sse(
        "done",
        {
            "thread_id": thread_id,
            "message_id": msg_id,
            "elapsed_ms": elapsed_ms,
            "cache_hit": False,
            "final_answer": final_answer,
            "traces": traces,
            "scores": [float(s) for s in scores],
            "best_index": best_index,
        },
    ).encode()


@router.post("/ask/stream")
async def ask_stream(body: AskStreamIn, request: Request, user=Depends(get_current_user)):
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    async def gen():
        try:
            async for chunk in _stream_engine(
                question=question, user_id=user["user_id"], thread_id=body.thread_id, request=request
            ):
                yield chunk
        except Exception as e:
            yield _sse("error", {"message": str(e)[:300]}).encode()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
