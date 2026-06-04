"""Unit tests for the hybrid retriever — these run without the LLM."""
from backend.agents.retrieval import HybridRetriever


def test_retriever_returns_relevant_doc_for_rag_query():
    r = HybridRetriever()
    docs = r.search("What is RAG retrieval augmented generation?", top_k=3)
    assert len(docs) == 3
    assert any("Retrieval-Augmented" in d.content for d in docs)


def test_retriever_returns_relevant_doc_for_langgraph_query():
    r = HybridRetriever()
    docs = r.search("LangGraph stateful workflows", top_k=2)
    assert any("LangGraph" in d.content for d in docs)


def test_retriever_handles_empty_query():
    r = HybridRetriever()
    docs = r.search("", top_k=2)
    assert len(docs) == 2  # falls back to defaults
