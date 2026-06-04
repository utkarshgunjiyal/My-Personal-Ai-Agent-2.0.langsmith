"""Hybrid retrieval: BM25 (sparse) + TF-IDF cosine (dense substitute).

Uses scikit-learn TF-IDF instead of sentence-transformers to keep the project
lightweight and fast to start in container environments. This is ample for
demo / resume purposes — the multi-agent architecture is the differentiator.
"""
import re
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# A small built-in technical knowledge base — extended beyond original 6 docs
KNOWLEDGE_BASE: list[str] = [
    "LangGraph is a framework for building stateful, multi-actor AI applications with LLMs. "
    "It models workflows as directed graphs of nodes (agents) connected by edges, with shared state.",
    "RAG (Retrieval-Augmented Generation) improves LLM responses by retrieving relevant external context "
    "from a knowledge base before generation, reducing hallucinations and grounding answers in evidence.",
    "FAISS is Facebook AI Similarity Search, a library for efficient dense vector similarity search "
    "over embeddings. It supports both exact and approximate nearest-neighbour search at scale.",
    "BM25 (Best Matching 25) is a sparse, keyword-based ranking function descended from TF-IDF. "
    "It excels at exact term matching and complements dense retrieval in hybrid search.",
    "Hybrid retrieval combines sparse retrievers (BM25) with dense retrievers (FAISS/embeddings) and "
    "fuses their scores - producing better recall than either method alone.",
    "Semantic caching stores prior question-answer pairs as embeddings, then reuses an answer if a new "
    "question is semantically similar to a cached one. This dramatically reduces LLM cost and latency.",
    "LLM-as-a-judge is an evaluation pattern where a separate LLM call scores candidate answers on "
    "correctness, relevance and clarity. It's used to select the best answer from multiple agents.",
    "FastAPI is a modern, async Python web framework built on Starlette and Pydantic. It provides "
    "automatic OpenAPI/Swagger documentation, request validation, and high performance.",
    "MongoDB is a document-oriented NoSQL database. It stores JSON-like documents with dynamic schemas, "
    "making it well-suited for evolving application data such as chat history.",
    "Vector embeddings are dense numeric representations of text where semantically similar inputs map "
    "to nearby points. Embedding models include OpenAI text-embedding-3, Cohere, and SentenceTransformers.",
    "Chain-of-Thought (CoT) prompting asks an LLM to reason step by step before answering, which improves "
    "accuracy on multi-step problems but consumes more tokens.",
    "ReAct (Reason + Act) is an agent pattern where an LLM alternates between reasoning steps and tool calls, "
    "using observations from tools to guide further reasoning.",
    "Tavily is a search API designed for AI agents - it returns clean, structured web search results that "
    "are easy to feed back into an LLM prompt.",
    "arXiv is an open-access repository for research papers in physics, math, CS and other fields. The "
    "arxiv-py Python client lets agents fetch paper titles, abstracts and metadata programmatically.",
]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _minmax(arr: np.ndarray) -> np.ndarray:
    if arr.size == 0:
        return arr
    lo, hi = arr.min(), arr.max()
    if hi == lo:
        return np.ones_like(arr)
    return (arr - lo) / (hi - lo)


@dataclass
class RetrievedDoc:
    content: str
    score: float


class HybridRetriever:
    def __init__(self, docs: list[str] | None = None):
        self.docs = docs or KNOWLEDGE_BASE
        self.bm25 = BM25Okapi([_tokenize(d) for d in self.docs])
        self.vectorizer = TfidfVectorizer(stop_words="english")
        self.tfidf_matrix = self.vectorizer.fit_transform(self.docs)

    def search(self, query: str, alpha: float = 0.6, top_k: int = 3) -> list[RetrievedDoc]:
        # Sparse
        sparse_raw = self.bm25.get_scores(_tokenize(query))
        # Dense (TF-IDF cosine)
        q_vec = self.vectorizer.transform([query])
        dense_raw = cosine_similarity(q_vec, self.tfidf_matrix).flatten()

        sparse = _minmax(np.asarray(sparse_raw, dtype=float))
        dense = _minmax(np.asarray(dense_raw, dtype=float))
        combined = alpha * dense + (1 - alpha) * sparse

        top_idx = np.argsort(-combined)[:top_k]
        return [RetrievedDoc(content=self.docs[i], score=float(combined[i])) for i in top_idx]
