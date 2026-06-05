"""Per-thread document retrieval over uploaded file chunks.

Builds a small TF-IDF index on-demand from `thread_documents` for the given
thread, and returns the top-k most relevant chunks.
"""
from dataclasses import dataclass
from typing import List

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class UserDoc:
    content: str
    filename: str
    file_id: str
    chunk_index: int
    score: float


async def retrieve_thread_docs(
    db, *, thread_id: str, user_id: str, query: str, top_k: int = 4
) -> List[UserDoc]:
    """Return up to top_k user-document chunks most relevant to `query`.

    Empty list if no documents have been uploaded for the thread.
    """
    if not thread_id:
        return []
    cursor = db.thread_documents.find(
        {"thread_id": thread_id, "user_id": user_id},
        {"_id": 0},
    )
    docs = await cursor.to_list(length=5000)
    if not docs:
        return []
    corpus = [d["content"] for d in docs]
    try:
        vec = TfidfVectorizer(stop_words="english")
        matrix = vec.fit_transform(corpus)
        q = vec.transform([query])
        sims = cosine_similarity(q, matrix).flatten()
    except ValueError:
        # Corpus may be empty after stop-word stripping; fall back to substring.
        return [
            UserDoc(
                content=d["content"],
                filename=d.get("filename", "uploaded"),
                file_id=d.get("file_id", ""),
                chunk_index=d.get("chunk_index", 0),
                score=0.0,
            )
            for d in docs[:top_k]
        ]
    top_idx = np.argsort(-sims)[:top_k]
    results: list[UserDoc] = []
    for i in top_idx:
        i = int(i)
        if float(sims[i]) <= 0.0:
            continue
        d = docs[i]
        results.append(
            UserDoc(
                content=d["content"],
                filename=d.get("filename", "uploaded"),
                file_id=d.get("file_id", ""),
                chunk_index=d.get("chunk_index", 0),
                score=float(sims[i]),
            )
        )
    return results


def format_docs_for_context(docs: List[UserDoc]) -> str:
    if not docs:
        return ""
    parts = []
    for d in docs:
        parts.append(
            f"[Uploaded · {d.filename} · chunk {d.chunk_index + 1}]\n{d.content}"
        )
    return "\n\n".join(parts)
