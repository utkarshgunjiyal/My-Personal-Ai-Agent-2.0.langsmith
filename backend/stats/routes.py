"""Stats / admin dashboard endpoints."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from auth.deps import get_current_user
from db import get_db

router = APIRouter(prefix="/api/stats", tags=["stats"])

AGENT_NAMES = ["local_retrieval", "general_llm", "tavily_web", "arxiv_research"]


@router.get("/overview")
async def overview(user=Depends(get_current_user)):
    db = get_db()
    is_admin = user.get("role") == "admin"
    base_filter = {} if is_admin else {"user_id": user["user_id"]}

    total = await db.agent_runs.count_documents(base_filter)
    threads = await db.threads.count_documents(base_filter)

    since = datetime.now(timezone.utc) - timedelta(days=7)
    weekly = await db.agent_runs.count_documents(
        {**base_filter, "created_at": {"$gte": since}}
    )

    # Avg latency. Legacy runs recorded before the semantic cache was removed
    # may carry cache_hit=true with ~10ms latencies; exclude them so they
    # don't skew the average ($ne also matches new docs without the field).
    pipeline_latency = [
        {"$match": {**base_filter, "cache_hit": {"$ne": True}}},
        {"$group": {"_id": None, "avg_ms": {"$avg": "$elapsed_ms"}}},
    ]
    cur = db.agent_runs.aggregate(pipeline_latency)
    latency_doc = await cur.to_list(length=1)
    avg_latency_ms = int(latency_doc[0]["avg_ms"]) if latency_doc else 0

    # Average per-agent score
    pipeline_scores = [
        {"$match": {**base_filter, "scores.0": {"$exists": True}}},
        {
            "$project": {
                "scores": 1,
                "best_index": 1,
            }
        },
    ]
    avg_scores = [0.0, 0.0, 0.0, 0.0]
    counts = [0, 0, 0, 0]
    wins = [0, 0, 0, 0]
    async for doc in db.agent_runs.aggregate(pipeline_scores):
        scores = doc.get("scores") or []
        for i, s in enumerate(scores[:4]):
            avg_scores[i] += float(s)
            counts[i] += 1
        bi = doc.get("best_index", -1)
        if 0 <= bi < 4:
            wins[bi] += 1
    for i in range(4):
        if counts[i] > 0:
            avg_scores[i] = round(avg_scores[i] / counts[i], 2)

    agent_perf = [
        {
            "name": AGENT_NAMES[i],
            "avg_score": avg_scores[i],
            "samples": counts[i],
            "wins": wins[i],
        }
        for i in range(4)
    ]

    return {
        "is_admin_view": is_admin,
        "totals": {
            "queries": total,
            "threads": threads,
            "queries_last_7d": weekly,
            "avg_latency_ms": avg_latency_ms,
        },
        "agents": agent_perf,
    }


@router.get("/recent")
async def recent(user=Depends(get_current_user)):
    db = get_db()
    is_admin = user.get("role") == "admin"
    base_filter = {} if is_admin else {"user_id": user["user_id"]}
    cur = db.agent_runs.find(base_filter, {"_id": 0}).sort("created_at", -1).limit(20)
    items = await cur.to_list(length=20)
    return {"items": items}
