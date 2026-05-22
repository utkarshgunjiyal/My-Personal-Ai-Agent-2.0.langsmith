import re
import numpy as np
from rank_bm25 import BM25Okapi

from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings


def tokenize(text: str):
    return re.findall(r"\w+", text.lower())


def normalize(scores):
    scores = np.array(scores)

    if len(scores) == 0:
        return scores

    if scores.max() == scores.min():
        return np.ones_like(scores)

    return (scores - scores.min()) / (scores.max() - scores.min())


class HybridRetriever:
    def __init__(self):
        self.embedding_model = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )

        self.docs = [
            Document(page_content="LangGraph is a framework for building stateful multi-agent AI workflows."),
            Document(page_content="RAG improves LLM responses by retrieving relevant external context before generation."),
            Document(page_content="FAISS is used for dense vector similarity search over embeddings."),
            Document(page_content="BM25 is a sparse keyword-based retrieval algorithm useful for exact term matching."),
            Document(page_content="Semantic caching stores previous answers and reuses them for similar future queries."),
            Document(page_content="LLM evaluation can score candidate answers based on correctness, clarity, and relevance."),
        ]

        self.vector_store = FAISS.from_documents(self.docs, self.embedding_model)
        self.bm25 = BM25Okapi([tokenize(doc.page_content) for doc in self.docs])

    def search(self, query: str, alpha: float = 0.7, top_k: int = 3):
        dense_results = self.vector_store.similarity_search_with_score(query, k=5)
        sparse_scores = self.bm25.get_scores(tokenize(query))

        combined_scores = {}
        doc_map = {}

        dense_similarities = normalize([-score for _, score in dense_results])

        for (doc, _), score in zip(dense_results, dense_similarities):
            key = doc.page_content
            doc_map[key] = doc
            combined_scores[key] = combined_scores.get(key, 0) + alpha * score

        sparse_normalized = normalize(sparse_scores)

        for doc, score in zip(self.docs, sparse_normalized):
            key = doc.page_content
            doc_map[key] = doc
            combined_scores[key] = combined_scores.get(key, 0) + (1 - alpha) * score

        ranked_docs = sorted(
            combined_scores.items(),
            key=lambda item: item[1],
            reverse=True
        )

        return [doc_map[key] for key, _ in ranked_docs[:top_k]]