from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from graph import app as decision_engine


api = FastAPI(
    title="AI Decision Engine API",
    description=(
        "A multi-agent RAG decision engine using LangGraph, hybrid retrieval, "
        "LLM evaluation, answer refinement, and semantic caching."
    ),
    version="1.0.0",
)

# API-level in-memory history.
# This is separate from LangGraph checkpointing and resets when the server restarts.
history: List[Dict[str, Any]] = []


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, description="User question")
    thread_id: Optional[str] = Field(
        default="fastapi-user",
        description="Thread ID used by LangGraph MemorySaver checkpointer",
    )


class AskResponse(BaseModel):
    question: str
    answer: str
    scores: List[float]
    cache_hit: bool
    cache_similarity: float
    thread_id: str
    request_id: str


@api.get("/")
def root() -> Dict[str, str]:
    return {
        "message": "AI Decision Engine API is running",
        "docs": "/docs",
        "health": "/health",
        "ask_endpoint": "/ask",
    }


@api.get("/health")
def health_check() -> Dict[str, str]:
    return {"status": "healthy"}


@api.post("/ask", response_model=AskResponse)
def ask_question(payload: AskRequest) -> AskResponse:
    question = payload.question.strip()

    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    thread_id = payload.thread_id or "fastapi-user"
    request_id = str(uuid4())

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    try:
        result = decision_engine.invoke(
            {
                "question": question,
                "answers": [],
                "scores": [],
                "best_answer": None,
                "final_answer": None,
                "cache_hit": False,
                "cache_similarity": 0.0,
            },
            config=config,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Decision engine failed: {str(exc)}",
        ) from exc

    response = AskResponse(
        question=question,
        answer=result.get("final_answer", ""),
        scores=result.get("scores", []),
        cache_hit=bool(result.get("cache_hit", False)),
        cache_similarity=float(result.get("cache_similarity", 0.0)),
        thread_id=thread_id,
        request_id=request_id,
    )

    history.append(response.model_dump())
    return response


@api.get("/history")
def get_history() -> Dict[str, Any]:
    return {
        "total": len(history),
        "items": list(reversed(history)),
    }


@api.delete("/history")
def clear_history() -> Dict[str, str]:
    history.clear()
    return {"message": "History cleared"}
