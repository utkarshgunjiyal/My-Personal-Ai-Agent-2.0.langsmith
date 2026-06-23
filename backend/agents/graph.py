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
from tracing import (
    add_current_tags,
    add_feedback,
    current_run_id,
    set_current_outputs,
    trace_root,
    trace_url,
    traceable,
    update_current_metadata,
)

# Global stateless retriever (KB is static)
retriever = HybridRetriever()


# --- LangSmith I/O shapers ---------------------------------------------------
# The graph state carries non-serializable objects (motor db handle, the
# SemanticCache with numpy matrices). These shapers project each node's
# inputs/outputs down to a small, JSON-safe view so the trace stays readable.
def _safe_state(d) -> dict:
    if not isinstance(d, dict):
        return {"value": str(d)[:200]}
    out: dict = {}
    for k in (
        "question",
        "user_id",
        "thread_id",
        "cache_hit",
        "cache_similarity",
        "cached_question",
        "scores",
        "best_index",
        "elapsed_ms",
    ):
        if k in d:
            out[k] = d[k]
    if d.get("best_answer"):
        out["best_answer"] = str(d["best_answer"])[:300]
    if d.get("final_answer"):
        out["final_answer"] = str(d["final_answer"])[:300]
    if isinstance(d.get("traces"), list):
        out["agent_count"] = len(d["traces"])
    return out


def _agent_inputs(inputs: dict) -> dict:
    return {
        "name": inputs.get("name"),
        "system": (inputs.get("system") or "")[:200],
        "prompt": (inputs.get("prompt") or "")[:500],
    }


def _agent_outputs(output) -> dict:
    if not isinstance(output, dict):
        return {"value": str(output)[:200]}
    return {
        "name": output.get("name"),
        "elapsed_ms": output.get("elapsed_ms"),
        "answer": (output.get("answer") or "")[:500],
    }


def _judge_inputs(inputs: dict) -> dict:
    t = inputs.get("trace") or {}
    return {"agent": t.get("name"), "answer": (t.get("answer") or "")[:500]}


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
@traceable(
    run_type="chain",
    name="check_cache",
    process_inputs=_safe_state,
    process_outputs=_safe_state,
)
async def check_cache(state: EngineState) -> EngineState:
    cache: SemanticCache = state["cache"]
    hit = cache.search(state["question"])
    if hit:
        add_current_tags("cache_hit")
        update_current_metadata(cache_similarity=float(hit["similarity"]))
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


@traceable(
    run_type="chain",
    name="agent",
    tags=["agent"],
    process_inputs=_agent_inputs,
    process_outputs=_agent_outputs,
)
async def _run_agent(name: str, color: str, system: str, prompt: str, context: str) -> AgentTrace:
    add_current_tags(f"agent:{name}")
    update_current_metadata(agent_name=name)
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


@traceable(
    run_type="chain",
    name="run_agents",
    process_inputs=_safe_state,
    process_outputs=_safe_state,
)
async def run_agents(state: EngineState) -> EngineState:
    """Fan-out all 4 agents concurrently for speed."""
    question = state["question"]
    db = state.get("db")
    thread_id = state.get("thread_id")
    user_id = state.get("user_id")

    # Build contexts
    docs = retriever.search(question)
    local_ctx = "\n".join(f"- {d.content}" for d in docs)

    # Augment with user-uploaded thread documents (if any).
    user_docs = []
    if db is not None and thread_id and user_id:
        from uploads.retriever import retrieve_thread_docs, format_docs_for_context
        user_docs = await retrieve_thread_docs(
            db, thread_id=thread_id, user_id=user_id, query=question, top_k=4
        )
        user_ctx = format_docs_for_context(user_docs)
        if user_ctx:
            local_ctx = (
                f"=== Your Uploaded Documents ===\n{user_ctx}\n\n"
                f"=== Built-in Knowledge Base ===\n{local_ctx}"
            )

    web_ctx = await asyncio.to_thread(tavily_search_context, question, 3)
    arxiv_ctx = await asyncio.to_thread(arxiv_search_context, question, 3)

    local_sys = (
        "You are a precise technical assistant. Answer using ONLY the local retrieved context. "
        "If the context is insufficient, say so explicitly. Be concise (4-8 sentences)."
    )
    if user_docs:
        local_sys = (
            "You are a precise technical assistant. Answer using the provided context, "
            "PRIORITIZING the user's uploaded documents over the built-in knowledge base. "
            "Quote / cite filenames inline when you use them. "
            "If neither source is sufficient, say so explicitly. Be concise (4-8 sentences)."
        )

    tasks = [
        _run_agent(
            "local_retrieval",
            "#007AFF",
            local_sys,
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


@traceable(
    run_type="chain",
    name="evaluate",
    process_inputs=_safe_state,
    process_outputs=_safe_state,
)
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

    @traceable(run_type="chain", name="judge_score", tags=["judge"], process_inputs=_judge_inputs)
    async def score_one(trace: AgentTrace) -> float:
        update_current_metadata(agent_name=trace.get("name"))
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


@traceable(
    run_type="chain",
    name="refine",
    process_inputs=_safe_state,
    process_outputs=_safe_state,
)
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


@traceable(
    run_type="chain",
    name="write_cache",
    process_inputs=_safe_state,
    process_outputs=_safe_state,
)
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

    # Root trace for the entire non-streaming engine run. Every @traceable
    # node (check_cache, run_agents, agents, judge, refine, write_cache) plus
    # the retriever / cache / external-tool spans attach as children.
    async with trace_root(
        name="ask_engine",
        run_type="chain",
        inputs={"question": question, "thread_id": thread_id},
        metadata={"user_id": user_id, "thread_id": thread_id},
        tags=["ask_engine", "api", "non_streaming"],
    ):
        root_run_id = current_run_id()
        result = await engine_graph.ainvoke(state)
        result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)

        scores = result.get("scores", []) or []
        best_idx = result.get("best_index", -1)
        best_score = float(scores[best_idx]) if scores and 0 <= best_idx < len(scores) else None
        best_agent = (
            result["traces"][best_idx]["name"]
            if result.get("traces") and 0 <= best_idx < len(result["traces"])
            else ("cache" if result.get("cache_hit") else None)
        )

        update_current_metadata(
            cache_hit=bool(result.get("cache_hit")),
            cache_similarity=float(result.get("cache_similarity", 0.0)),
            best_index=best_idx,
            best_agent=best_agent,
            best_score=best_score,
        )
        set_current_outputs(
            {
                "final_answer": (result.get("final_answer") or "")[:1000],
                "cache_hit": bool(result.get("cache_hit")),
                "best_agent": best_agent,
                "best_score": best_score,
                "scores": [float(s) for s in scores],
                "best_index": best_idx,
            }
        )
        if root_run_id and best_score is not None:
            add_feedback(
                root_run_id,
                "judge_best_score",
                score=best_score,
                comment=f"best agent: {best_agent}" if best_agent else None,
            )

        result["ls_run_id"] = root_run_id
        result["ls_url"] = trace_url(root_run_id)

    return result
