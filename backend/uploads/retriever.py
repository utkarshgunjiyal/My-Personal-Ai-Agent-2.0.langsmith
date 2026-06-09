"""Hybrid retrieval over per-thread uploaded documents.

Combines:
    • Sparse: BM25 (rank-bm25)
    • Dense: FAISS over fastembed embeddings (vectorstore module)

Merges results via Reciprocal Rank Fusion (RRF), then returns top-k.
If a thread's FAISS index is missing on disk but chunks exist in Mongo,
:func:`vectorstore.ensure_index` will lazily rebuild it.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List

from rank_bm25 import BM25Okapi

import vectorstore

log = logging.getLogger("uploads.retriever")

# RRF constant — k=60 is standard
RRF_K = 60


@dataclass
class UserDoc:
    content: str
    filename: str
    file_id: str
    doc_id: str
    chunk_index: int
    page: int | None
    source: str
    score: float


def _tokenize(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


async def retrieve_thread_docs(
    db, *, thread_id: str, user_id: str, query: str, top_k: int = 5
) -> List[UserDoc]:
    """Top-k hybrid-retrieved chunks for the thread.

    Empty list if the thread has no uploaded documents.
    """
    if not thread_id:
        return []

    cursor = db.thread_documents.find(
        {"thread_id": thread_id, "user_id": user_id},
        {"_id": 0},
    ).sort("chunk_index", 1)
    docs = await cursor.to_list(length=20000)
    if not docs:
        return []

    by_doc_id = {d["doc_id"]: d for d in docs}

    # --- Sparse (BM25) ---
    tokenized_corpus = [_tokenize(d["content"]) for d in docs]
    sparse_ranking: list[str] = []
    try:
        bm25 = BM25Okapi(tokenized_corpus)
        scores = bm25.get_scores(_tokenize(query))
        ranked_idx = sorted(
            range(len(docs)), key=lambda i: scores[i], reverse=True
        )[: top_k * 4]
        sparse_ranking = [
            docs[i]["doc_id"] for i in ranked_idx if scores[i] > 0
        ]
    except Exception as e:
        log.warning("BM25 failed: %s", e)

    # --- Dense (FAISS) ---
    dense_ranking: list[str] = []
    try:
        await vectorstore.ensure_index(db, thread_id)
        dense_hits = await vectorstore.search(thread_id, query, top_k=top_k * 4)
        dense_ranking = [doc_id for doc_id, _ in dense_hits]
    except Exception as e:
        log.warning("Dense search failed: %s", e)

    # --- RRF fusion ---
    rrf: dict[str, float] = {}
    for rank, doc_id in enumerate(sparse_ranking):
        rrf[doc_id] = rrf.get(doc_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    for rank, doc_id in enumerate(dense_ranking):
        rrf[doc_id] = rrf.get(doc_id, 0.0) + 1.0 / (RRF_K + rank + 1)

    if not rrf:
        # Fallback: return first N chunks so the agent still has _some_ context
        return [
            UserDoc(
                content=d["content"],
                filename=d.get("filename", "uploaded"),
                file_id=d.get("file_id", ""),
                doc_id=d.get("doc_id", ""),
                chunk_index=d.get("chunk_index", 0),
                page=d.get("page"),
                source=d.get("source", "text"),
                score=0.0,
            )
            for d in docs[:top_k]
        ]

    ordered = sorted(rrf.items(), key=lambda x: x[1], reverse=True)[:top_k]
    out: list[UserDoc] = []
    for doc_id, score in ordered:
        d = by_doc_id.get(doc_id)
        if not d:
            continue
        out.append(
            UserDoc(
                content=d["content"],
                filename=d.get("filename", "uploaded"),
                file_id=d.get("file_id", ""),
                doc_id=d.get("doc_id", ""),
                chunk_index=d.get("chunk_index", 0),
                page=d.get("page"),
                source=d.get("source", "text"),
                score=float(score),
            )
        )
    return out


def format_docs_for_context(docs: List[UserDoc]) -> str:
    if not docs:
        return ""
    parts = []
    for d in docs:
        loc = f" · page {d.page}" if d.page else ""
        src = f" · {d.source}" if d.source and d.source not in ("text",) else ""
        parts.append(
            f"[Uploaded · {d.filename}{loc}{src} · chunk {d.chunk_index + 1}]\n{d.content}"
        )
    return "\n\n".join(parts)
