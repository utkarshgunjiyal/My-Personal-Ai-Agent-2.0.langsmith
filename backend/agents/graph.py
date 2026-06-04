"""LangGraph workflow for the multi-agent decision engine.

Pipeline:
    check_cache  ─►  (if hit) ──► END
                 │
                 └─►  agent_retrieval ─► agent_general ─► agent_tavily ─►
                       agent_arxiv ─► evaluate ─► refine ─► write_cache ─► END
"""
import asyncio
import time
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from agents.cache import SemanticCache
from agents.external import arxiv_search_context, tavily_search_context
from agents.llm import call_llm
from agents.retrieval import HybridRetriever

# Global stateless retriever (KB is static)
retriever = HybridRetriever()


class AgentTrace(TypedDict):
    name: str
    color: str
    answer: str
    score: float
    elapsed_ms: int
    context: str


class EngineState(TypedDict, total=False):
    question: str
    user_id: str
    thread_id: str
    cache: SemanticCache  # injected per-user, hydrated
    db: object  # motor db handle
    # outputs
    traces: list[AgentTrace]
    scores: list[float]
    best_index: int
    best_answer: str
    final_answer: str
    cache_hit: bool
    cache_similarity: float
    cached_question: Optional[str]
    elapsed_ms: int
    started_at: float


AGENT_META = [
    ("local_retrieval", "#007AFF"),
    ("general_llm", "#FFCC00"),
    ("tavily_web", "#34C759"),
    ("arxiv_research", "#FF3B30"),
]


# ---------- Nodes ----------
async def check_cache(state: EngineState) -> EngineState:
    cache: SemanticCache = state["cache"]
    hit = cache.search(state["question"])
    if hit:
        state["final_answer"] = hit["answer"]
        state["cache_hit"] = True
        state["cache_similarity"] = hit["similarity"]
        state["cached_question"] = hit["matched_question"]
        state["traces"] = []
        state["scores"] = []
        state["best_index"] = -1
    else:
        state["cache_hit"] = False
        state["cache_similarity"] = 0.0
        state["traces"] = []
    return state


async def _run_agent(name: str, color: str, system: str, prompt: str, context: str) -> AgentTrace:
    started = time.perf_counter()
    try:
        answer = await call_llm(system, prompt)
    except Exception as e:
        # Resilience: a single agent failure should NOT crash the pipeline.
        msg = str(e)
        if "Budget" in msg or "budget" in msg:
            answer = (
                f"[{name} unavailable: LLM provider budget exceeded. "
                "Please refresh your Emergent LLM key budget — Profile → Universal Key → Add Balance.]"
            )
        elif "rate" in msg.lower():
            answer = f"[{name} rate-limited by LLM provider — please retry in a moment.]"
        else:
            answer = f"[{name} error: {msg[:200]}]"
    return AgentTrace(
        name=name,
        color=color,
        answer=answer,
        score=0.0,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        context=context,
    )


async def run_agents(state: EngineState) -> EngineState:
    """Fan-out all 4 agents concurrently for speed."""
    question = state["question"]

    # Build contexts
    docs = retriever.search(question)
    local_ctx = "\n".join(f"- {d.content}" for d in docs)
    web_ctx = await asyncio.to_thread(tavily_search_context, question, 3)
    arxiv_ctx = await asyncio.to_thread(arxiv_search_context, question, 3)

    tasks = [
        _run_agent(
            "local_retrieval",
            "#007AFF",
            "You are a precise technical assistant. Answer using ONLY the local retrieved context. "
            "If the context is insufficient, say so explicitly. Be concise (4-8 sentences).",
            f"Local Context:\n{local_ctx}\n\nQuestion: {question}",
            local_ctx,
        ),
        _run_agent(
            "general_llm",
            "#FFCC00",
            "You are a knowledgeable AI assistant. Answer clearly and concisely (4-8 sentences). "
            "Avoid hedging; be specific.",
            f"Question: {question}",
            "(no external context)",
        ),
        _run_agent(
            "tavily_web",
            "#34C759",
            "You are a live-web research agent. Use the provided web search context to answer. "
            "If the context indicates web search is disabled or unavailable, state that clearly and "
            "fall back to general knowledge with a note.",
            f"Web Context:\n{web_ctx}\n\nQuestion: {question}",
            web_ctx,
        ),
        _run_agent(
            "arxiv_research",
            "#FF3B30",
            "You are a research-paper analyst. Use the arXiv context to answer with a research lens. "
            "Cite paper titles when relevant. If no papers were retrieved, say so plainly.",
            f"arXiv Context:\n{arxiv_ctx}\n\nQuestion: {question}",
            arxiv_ctx,
        ),
    ]
    state["traces"] = await asyncio.gather(*tasks, return_exceptions=False)
    return state


def _is_error_trace(t: AgentTrace) -> bool:
    a = (t.get("answer") or "").strip()
    return a.startswith("[") and ("error" in a.lower() or "unavailable" in a.lower() or "rate-limited" in a.lower())


async def evaluate(state: EngineState) -> EngineState:
    """LLM-as-judge: score each agent's answer 0-10."""
    question = state["question"]
    system = (
        "You are a strict evaluator. Score the candidate answer from 0 to 10 based on: "
        "correctness, relevance, clarity, technical accuracy, and grounding in evidence. "
        "Penalize unsupported claims. "
        "Special rule: If the question mentions RAG and the answer interprets it as 'Red Amber Green', score below 3. "
        "If the question mentions RAG and the answer interprets it as 'Retrieval-Augmented Generation', score above 8. "
        "Reply with ONLY a single number between 0 and 10. No other text."
    )

    async def score_one(trace: AgentTrace) -> float:
        if _is_error_trace(trace):
            return 0.0
        prompt = f"Question:\n{question}\n\nAnswer:\n{trace['answer']}"
        try:
            raw = await call_llm(system, prompt)
        except Exception:
            # Heuristic fallback: length-based score in [3, 7]
            n = len(trace["answer"])
            return max(3.0, min(7.0, 3.0 + (n / 600.0)))
        try:
            import re
            m = re.search(r"-?\d+(?:\.\d+)?", raw)
            return max(0.0, min(10.0, float(m.group()))) if m else 0.0
        except Exception:
            return 0.0

    scores = await asyncio.gather(*(score_one(t) for t in state["traces"]))
    for t, s in zip(state["traces"], scores):
        t["score"] = s
    state["scores"] = list(scores)
    best_idx = int(max(range(len(scores)), key=lambda i: scores[i])) if scores else -1
    state["best_index"] = best_idx
    state["best_answer"] = state["traces"][best_idx]["answer"] if best_idx >= 0 else ""
    return state


async def refine(state: EngineState) -> EngineState:
    state["final_answer"] = await _safe_refine(
        state["question"], state["traces"], state["best_answer"]
    )
    return state


async def _safe_refine(question: str, traces: list[AgentTrace], best_answer: str) -> str:
    candidates = "\n\n".join(
        f"=== Agent {i + 1} ({t['name']}, score={t['score']}) ===\n{t['answer']}"
        for i, t in enumerate(traces)
    )
    system = (
        "You are the final answer refiner for a multi-agent AI system. "
        "Synthesize a single, definitive answer that is technically accurate, clear and concise. "
        "Prefer the best-scored answer's content, but incorporate useful detail from others. "
        "Do not include unsupported claims. Do not mention the agents."
    )
    prompt = (
        f"Question:\n{question}\n\nCandidate Answers:\n{candidates}\n\n"
        f"Best (selected by judge):\n{best_answer}\n\n"
        "Produce the final answer."
    )
    try:
        return await call_llm(system, prompt)
    except Exception as e:
        # Fall back to the best non-error candidate
        non_err = [t for t in traces if not _is_error_trace(t)]
        if non_err:
            non_err.sort(key=lambda t: t.get("score", 0), reverse=True)
            return non_err[0]["answer"]
        return f"[Engine temporarily unavailable: {str(e)[:200]}]"


async def write_cache(state: EngineState) -> EngineState:
    cache: SemanticCache = state["cache"]
    db = state["db"]
    await cache.add(db, state["user_id"], state["question"], state["final_answer"])
    return state


def _route_after_cache(state: EngineState):
    return END if state.get("cache_hit") else "run_agents"


# ---------- Build graph ----------
def build_graph():
    g = StateGraph(EngineState)
    g.add_node("check_cache", check_cache)
    g.add_node("run_agents", run_agents)
    g.add_node("evaluate", evaluate)
    g.add_node("refine", refine)
    g.add_node("write_cache", write_cache)

    g.set_entry_point("check_cache")
    g.add_conditional_edges("check_cache", _route_after_cache, {END: END, "run_agents": "run_agents"})
    g.add_edge("run_agents", "evaluate")
    g.add_edge("evaluate", "refine")
    g.add_edge("refine", "write_cache")
    g.add_edge("write_cache", END)
    return g.compile()


engine_graph = build_graph()


async def run_engine(*, question: str, user_id: str, thread_id: str, cache: SemanticCache, db) -> dict:
    state: EngineState = {
        "question": question,
        "user_id": user_id,
        "thread_id": thread_id,
        "cache": cache,
        "db": db,
        "traces": [],
        "scores": [],
        "best_index": -1,
        "best_answer": "",
        "final_answer": "",
        "cache_hit": False,
        "cache_similarity": 0.0,
        "cached_question": None,
        "started_at": time.perf_counter(),
    }
    started = time.perf_counter()
    result = await engine_graph.ainvoke(state)
    result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    return result
