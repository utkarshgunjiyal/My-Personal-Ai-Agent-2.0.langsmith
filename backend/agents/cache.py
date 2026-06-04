"""Persistent semantic cache backed by MongoDB.

Stores question-answer pairs as TF-IDF vectors and retrieves the closest match
by cosine similarity. Persistence survives server restarts.
"""
from datetime import datetime, timezone

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class SemanticCache:
    """A per-process semantic cache, hydrated from the `semantic_cache` collection."""

    def __init__(self, threshold: float = 0.72):
        self.threshold = threshold
        self.vectorizer: TfidfVectorizer | None = None
        self.matrix = None
        self.entries: list[dict] = []  # {question, answer}

    def _refit(self):
        if not self.entries:
            self.vectorizer = None
            self.matrix = None
            return
        self.vectorizer = TfidfVectorizer(stop_words="english")
        self.matrix = self.vectorizer.fit_transform([e["question"] for e in self.entries])

    async def hydrate(self, db, user_id: str):
        """Load all cache entries for a user."""
        docs = await db.semantic_cache.find({"user_id": user_id}, {"_id": 0}).to_list(length=2000)
        self.entries = [{"question": d["question"], "answer": d["answer"]} for d in docs]
        self._refit()

    def search(self, question: str) -> dict | None:
        if not self.entries or self.vectorizer is None:
            return None
        q_vec = self.vectorizer.transform([question])
        sims = cosine_similarity(q_vec, self.matrix).flatten()
        idx = int(np.argmax(sims))
        sim = float(sims[idx])
        if sim >= self.threshold:
            return {
                "answer": self.entries[idx]["answer"],
                "similarity": sim,
                "matched_question": self.entries[idx]["question"],
            }
        return None

    async def add(self, db, user_id: str, question: str, answer: str):
        self.entries.append({"question": question, "answer": answer})
        self._refit()
        await db.semantic_cache.insert_one(
            {
                "user_id": user_id,
                "question": question,
                "answer": answer,
                "created_at": datetime.now(timezone.utc),
            }
        )
