"""Per-thread vector store with persistent FAISS indices.

Embeddings: `BAAI/bge-small-en-v1.5` via fastembed (ONNX, ~80 MB, 384-dim).
Index: FAISS IndexFlatIP (inner-product on L2-normalized vectors = cosine).
Persistence: `/app/data/faiss/<thread_id>.{index,ids.json}`.

If a thread's FAISS index file is missing on disk, callers can rebuild it
from the MongoDB `thread_documents` chunks via :func:`rebuild_for_thread`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Iterable

import faiss
import numpy as np

log = logging.getLogger("vectorstore")

EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_DIM = 384
FAISS_DIR = Path(os.environ.get("FAISS_DIR", "/app/data/faiss"))
FAISS_DIR.mkdir(parents=True, exist_ok=True)


_embedder = None
_embedder_lock = asyncio.Lock()


async def _get_embedder():
    """Lazily load the fastembed model (downloads once to local cache)."""
    global _embedder
    if _embedder is not None:
        return _embedder
    async with _embedder_lock:
        if _embedder is None:
            from fastembed import TextEmbedding
            log.info("Loading embedding model: %s", EMBED_MODEL)
            _embedder = await asyncio.to_thread(TextEmbedding, model_name=EMBED_MODEL)
    return _embedder


async def embed_texts(texts: list[str]) -> np.ndarray:
    """Return float32 L2-normalized embeddings of shape (n, EMBED_DIM)."""
    if not texts:
        return np.zeros((0, EMBED_DIM), dtype=np.float32)
    m = await _get_embedder()
    vecs = await asyncio.to_thread(lambda: list(m.embed(texts)))
    arr = np.asarray(vecs, dtype=np.float32)
    # L2-normalize for cosine-as-inner-product
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


def _paths(thread_id: str) -> tuple[Path, Path]:
    return FAISS_DIR / f"{thread_id}.index", FAISS_DIR / f"{thread_id}.ids.json"


def _new_index() -> faiss.IndexFlatIP:
    return faiss.IndexFlatIP(EMBED_DIM)


def load_or_new(thread_id: str) -> tuple[faiss.Index, list[str]]:
    """Load FAISS + parallel doc_id list from disk; create empty if missing."""
    idx_path, ids_path = _paths(thread_id)
    if idx_path.exists() and ids_path.exists():
        try:
            idx = faiss.read_index(str(idx_path))
            ids = json.loads(ids_path.read_text())
            return idx, ids
        except Exception as e:
            log.warning("FAISS load failed for %s: %s — starting fresh", thread_id, e)
    return _new_index(), []


def save(thread_id: str, index: faiss.Index, ids: list[str]) -> None:
    idx_path, ids_path = _paths(thread_id)
    faiss.write_index(index, str(idx_path))
    ids_path.write_text(json.dumps(ids))


def delete(thread_id: str) -> None:
    for p in _paths(thread_id):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


async def add_chunks(
    thread_id: str, doc_ids: list[str], texts: list[str]
) -> int:
    """Embed new chunks and append them to the thread's FAISS index."""
    assert len(doc_ids) == len(texts)
    if not texts:
        return 0
    vecs = await embed_texts(texts)
    index, ids = load_or_new(thread_id)
    index.add(vecs)
    ids.extend(doc_ids)
    save(thread_id, index, ids)
    return len(texts)


async def search(
    thread_id: str, query: str, top_k: int = 8
) -> list[tuple[str, float]]:
    """Return [(doc_id, score)] for top_k most similar chunks. Empty if no index."""
    idx_path, ids_path = _paths(thread_id)
    if not idx_path.exists() or not ids_path.exists():
        return []
    index = faiss.read_index(str(idx_path))
    ids = json.loads(ids_path.read_text())
    if index.ntotal == 0 or not ids:
        return []
    qv = await embed_texts([query])
    scores, idxs = index.search(qv, min(top_k, index.ntotal))
    out: list[tuple[str, float]] = []
    for i, s in zip(idxs[0], scores[0]):
        if 0 <= i < len(ids):
            out.append((ids[int(i)], float(s)))
    return out


async def rebuild_for_thread(db, thread_id: str) -> int:
    """Rebuild FAISS index from MongoDB chunks (recovery path).

    Used when the on-disk FAISS file is missing or corrupted but chunks still
    exist in MongoDB — guaranteeing the user never has to re-upload.
    """
    cursor = db.thread_documents.find(
        {"thread_id": thread_id},
        {"_id": 0, "doc_id": 1, "content": 1},
    ).sort("chunk_index", 1)
    docs = await cursor.to_list(length=20000)
    if not docs:
        delete(thread_id)
        return 0
    doc_ids = [d["doc_id"] for d in docs]
    texts = [d["content"] for d in docs]
    delete(thread_id)
    return await add_chunks(thread_id, doc_ids, texts)


async def ensure_index(db, thread_id: str) -> int:
    """Ensure on-disk FAISS is consistent with MongoDB chunks. Returns total ntotal."""
    idx_path, ids_path = _paths(thread_id)
    chunk_count = await db.thread_documents.count_documents({"thread_id": thread_id})
    if chunk_count == 0:
        delete(thread_id)
        return 0
    if idx_path.exists() and ids_path.exists():
        try:
            index = faiss.read_index(str(idx_path))
            if index.ntotal == chunk_count:
                return chunk_count
        except Exception:
            pass
    return await rebuild_for_thread(db, thread_id)


def index_stats(thread_id: str) -> dict:
    idx_path, ids_path = _paths(thread_id)
    if not idx_path.exists():
        return {"exists": False, "ntotal": 0}
    try:
        index = faiss.read_index(str(idx_path))
        return {"exists": True, "ntotal": int(index.ntotal), "dim": EMBED_DIM}
    except Exception:
        return {"exists": False, "ntotal": 0}
